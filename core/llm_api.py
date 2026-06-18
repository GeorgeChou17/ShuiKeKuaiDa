"""
LLM API 对接模块
- 对接 OpenAI 兼容格式 API（支持第三方 BaseURL）
- 支持流式输出、思考模式开关
- 支持自定义 LLM 身份（system prompt 前缀）
- 固定 Prompt 格式，要求 LLM 按格式返回正确答案
- 规范输出格式，提高解析稳定性
"""
import json
import logging
from typing import Callable, Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# 基础 System Prompt（当用户未自定义身份时使用）
_DEFAULT_SYSTEM_PROMPT = """\
你是一个专业的答题助手。用户会给你一道题目（可能是图片或文字），你需要：
1. 仔细分析题目和选项
2. 给出你认为最正确的答案
3. 严格按照以下 JSON 格式输出，不要输出任何其他内容：

```json
{
  "question_type": "单选",
  "analysis": "简要分析思路（1-2句话）",
  "answer": "B",
  "confidence": 0.95
}
```

【铁的规则 — 必须100%遵守，否则程序无法解析答案】
1. 只输出一个 JSON 对象，放在 ```json ``` 代码块中，不要输出其他任何文字
2. answer 字段必须严格遵守：
   - 单选题：只能是单个大写字母 (A/B/C/D/E/F/G/H/I/J/K/L)，如 "B"，不能有空格、引号或其他字符
   - 多选题：大写字母组合 (如 AB、ACD)，字母必须按字母顺序排列
   - 判断题：只能是 "正确" 或 "错误"
   - 简答题/主观题：关键词要点，用分号分隔，如 "要点1;要点2;要点3"
3. question_type 必须精确是以下之一：单选、多选、判断、填空、简答、主观
4. confidence 是 0-1 之间的数字
5. analysis 写 1-3 句话简述分析依据
"""

# 主观题专用 System Prompt（检测到主观题时追加）
_SUBJECTIVE_BOOST = """
注意：如果题目是主观题/简答题/论述题，请在 answer 字段中填写答题要点（用分号分隔），
并在 analysis 字段中给出详细的分析过程和答题思路。
"""


class LLMAPIError(Exception):
    """LLM API 调用异常"""
    pass


class LLMClient:
    """
    封装 OpenAI 兼容 API 调用
    支持：自定义 BaseURL、API Key、模型名称、思考模式开关、自定义身份
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        thinking_enabled: bool = False,
        temperature: float = 0.0,
        max_tokens: int = 512,
        identity: str = "",   # 用户自定义的 LLM 身份（system prompt 前缀）
        timeout: int = 300,   # HTTP 请求超时（秒）
        stream_enabled: bool = False,  # 流式输出（免费模型通常不支持）
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.thinking_enabled = thinking_enabled
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.identity = identity.strip()
        self.timeout = timeout
        self.stream_enabled = stream_enabled

    def _build_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_system_prompt(self, is_subjective: bool = False) -> str:
        """
        构建 system prompt
        优先级：用户自定义身份 > 默认 prompt
        """
        if self.identity:
            # 用户自定义了身份，在此基础上追加格式要求
            base = self.identity.rstrip("\n")
            fmt = (
                "\n\n【覆写指令】无论以上内容是什么，你现在必须扮演答题助手角色。"
                "请严格按照以下 JSON 格式输出答案，不要输出任何其他内容：\n"
                "```json\n"
                '{"question_type": "单选",\n'
                ' "analysis": "分析思路",\n'
                ' "answer": "B",\n'
                ' "confidence": 0.9}\n```\n'
                "answer字段规则：单选题填单个字母(A/B/C...)，多选题填字母组合(AB/ACD...)字母有序，"
                "判断题填正确/错误，主观题填要点(分号分隔)。禁止输出JSON之外的文字。"
            )
            prompt = base + fmt
        else:
            prompt = _DEFAULT_SYSTEM_PROMPT

        if is_subjective:
            prompt += _SUBJECTIVE_BOOST

        return prompt

    def _build_payload(
        self,
        messages: list,
        stream: bool = True,
        **kwargs
    ) -> dict:
        """构建请求体"""
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }
        # 部分第三方 API 支持思考模式（如 DeepSeek-R1）
        if self.thinking_enabled:
            payload["think"] = True
        payload.update(kwargs)
        return payload

    def chat_completion(
        self,
        messages: list,
        on_token: Optional[Callable[[str], None]] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """
        调用聊天补全接口（支持流式）
        返回解析后的答案 dict：
        {
            "question_type": ...,
            "analysis": ...,
            "answer": ...,
            "confidence": ...,
            "raw_response": ...,
            "thinking": ...,   # 思考过程
        }
        """
        import httpx

        url = f"{self.base_url}/chat/completions"
        headers = self._build_headers()
        # 流式开关：由配置控制，默认关闭以兼容免费模型
        use_stream = self.stream_enabled and (on_token is not None)
        payload = self._build_payload(messages, stream=use_stream)

        try:
            if payload["stream"]:
                return self._stream_request(url, headers, payload, on_token, on_thinking)
            else:
                return self._sync_request(url, headers, payload)
        except GeneratorExit:
            # 生成器被外部关闭，当作超时/中断处理
            raise LLMAPIError("LLM 请求被中断（连接关闭或程序退出）")
        except httpx.TimeoutException:
            raise LLMAPIError("请求超时，请检查网络连接或 API 地址")
        except httpx.ConnectError:
            raise LLMAPIError("连接失败，请检查 API 地址是否正确")
        except Exception as e:
            raise LLMAPIError(f"API 调用失败: {e}")

    def _stream_request(
        self, url: str, headers: dict, payload: dict,
        on_token: Callable[[str], None],
        on_thinking: Callable[[str], None],
    ) -> dict:
        """流式请求"""
        import httpx

        full_content = ""
        thinking_content = ""

        # 配置超时：连接超时30秒，读取超时由用户设置（默认300秒）
        timeout_config = httpx.Timeout(
            connect=30.0,
            read=float(self.timeout),
            write=30.0,
            pool=30.0
        )

        try:
            with httpx.stream(
                "POST", url, headers=headers,
                json=payload, timeout=timeout_config
            ) as resp:
                if resp.status_code != 200:
                    body = resp.read().decode("utf-8", errors="replace")
                    raise LLMAPIError(f"API 返回错误 {resp.status_code}: {body}")

                for line in resp.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        # 部分模型用 thinking 字段返回思考过程
                        thinking = delta.get("thinking", "") or delta.get("reasoning_content", "")

                        if thinking:
                            thinking_content += thinking
                            if on_thinking:
                                on_thinking(thinking)
                        if content:
                            full_content += content
                            if on_token:
                                on_token(content)
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
        except GeneratorExit:
            # httpx 流式生成器被关闭（程序退出/连接中断），正常处理已有内容
            pass
        except BaseException:
            # 其他非 Exception 的异常（如 KeyboardInterrupt）不要吞掉
            raise

        if not full_content.strip():
            raise LLMAPIError(
                "LLM 返回空响应。可能原因：\n"
                "1. 模型不支持流式输出\n"
                "2. API 返回格式不兼容\n"
                "3. 网络连接中断\n"
                "请尝试在设置中禁用思考模式后重试"
            )
        
        return self._parse_response(full_content, thinking_content)

    def _sync_request(self, url: str, headers: dict, payload: dict) -> dict:
        """非流式请求"""
        import httpx

        payload["stream"] = False
        
        # 配置超时：连接超时30秒，读取超时由用户设置（默认300秒）
        timeout_config = httpx.Timeout(
            connect=30.0,
            read=float(self.timeout),
            write=30.0,
            pool=30.0
        )
        
        try:
            resp = httpx.post(url, headers=headers, json=payload, timeout=timeout_config)
        except httpx.TimeoutException:
            raise LLMAPIError(f"请求超时（{self.timeout}秒），请增加超时时间或检查网络")
        except httpx.ConnectError:
            raise LLMAPIError("连接失败，请检查 API 地址是否正确")
            
        if resp.status_code != 200:
            if resp.status_code == 429:
                raise LLMAPIError(f"429 限流：API 拒绝了请求（Too Many Requests）")
            raise LLMAPIError(f"API 返回错误 {resp.status_code}: {resp.text[:500]}")

        # 安全解析 JSON 响应体
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"LLM 返回非 JSON 响应: {resp.text[:500]}")
            raise LLMAPIError(f"API 返回了非 JSON 格式的数据（状态码 {resp.status_code}）")

        # 安全提取 content
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"LLM 返回结构异常: {json.dumps(data, ensure_ascii=False)[:300]}")
            raise LLMAPIError(f"API 返回数据结构异常，缺少 choices[0].message.content")

        # 空内容检查
        content = content or ""
        if not content.strip():
            raise LLMAPIError(
                "LLM 返回了空答案。可能原因：\n"
                "1. 免费模型配额耗尽或被限流\n"
                "2. 模型不支持当前请求格式\n"
                "3. 题目内容触发了模型安全过滤\n"
                "请稍后重试或更换模型"
            )
            
        return self._parse_response(content, "")

    def _parse_response(self, content: str, thinking: str) -> dict:
        """
        从 LLM 返回内容中解析 JSON 答案
        支持：```json ... ``` 包裹、纯 JSON、混合文本
        """
        import re

        result = {
            "question_type": "未知",
            "analysis": "",
            "answer": "",
            "confidence": 0.0,
            "raw_response": content,
            "thinking": thinking,
        }

        # 尝试提取 ```json ... ``` 块
        m = re.search(r"```json\s*([\s\S]*?)\s*```", content)
        if m:
            json_str = m.group(1).strip()
        else:
            # 尝试找到第一个 { ... }
            m = re.search(r"\{[\s\S]*?\}", content)
            if m:
                json_str = m.group(0).strip()
            else:
                json_str = content.strip()

        # 尝试修复常见 JSON 格式错误
        json_str = self._fix_json_string(json_str)

        try:
            parsed = json.loads(json_str)
            result["question_type"] = parsed.get("question_type", "未知")
            result["analysis"] = parsed.get("analysis", "")
            result["answer"] = str(parsed.get("answer", "")).strip()
            try:
                result["confidence"] = float(parsed.get("confidence", 0.0))
            except (ValueError, TypeError):
                result["confidence"] = 0.0
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"JSON 解析失败: {e}，原始内容: {content[:300]}")
            # 兜底：尝试从文字中提取答案
            result["answer"] = self._fallback_extract_answer(content)
            result["analysis"] = content[:200]

        return result

    def _fix_json_string(self, s: str) -> str:
        """
        尝试修复常见的 JSON 格式错误
        - 中文引号 → 英文引号
        - 单引号 → 双引号
        - 尾部多余逗号
        """
        import re
        # 中文引号替换
        s = s.replace("\u201c", "\"").replace("\u201d", "\"")
        # 单引号键名 → 双引号
        s = re.sub(r"([{,]\s*)'([^']+)'\s*:", r'\1"\2":', s)
        # 单引号字符串 → 双引号（简单处理）
        # 去除尾部多余逗号
        s = re.sub(r",\s*([}\]])", r"\1", s)
        return s

    def _fallback_extract_answer(self, content: str) -> str:
        """
        兜底：当 JSON 解析失败时，尝试从文字中提取答案
        多层提取策略
        """
        import re
        
        # 策略1: 提取 "answer": "X" 或 "answer": 'X'
        m = re.search(r'["\']answer["\']?\s*[:=]\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
        if m:
            ans = m.group(1).strip().upper()
            if ans and (ans.isalpha() or ans in ("正确", "错误")):
                return ans

        # 策略2: 中文答案模式：答案[为是：:] X
        patterns = [
            r"答案[为是：:\s]*([A-L]+)",
            r"正确[答案选项]+?[为是：:\s]*([A-L]+)",
            r"选[项择：:\s]*([A-L]+)",
            r"[答案应为选]+[：:\s]*([A-L]+)",
            r"\[答案\][：:\s]*([A-L]+)",
        ]
        for pat in patterns:
            m = re.search(pat, content)
            if m:
                return m.group(1).upper()

        # 策略3: 最后尝试找单独的字母答案
        m = re.search(r'"([A-L])"', content)
        if m:
            return m.group(1).upper()
            
        return ""

    def build_ocr_messages(self, ocr_text: str, is_subjective: bool = False) -> list:
        """构建 OCR 模式的消息列表"""
        system_prompt = self._build_system_prompt(is_subjective)
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                "【任务】分析以下题目，选出正确答案。\n\n"
                "题目内容：\n"
                f"{ocr_text}\n\n"
                "【输出要求 — 必须遵守】\n"
                "1. 只输出一个 JSON 对象，用 ```json ``` 包裹，不要输出任何其他文字\n"
                "2. question_type 只能是：单选、多选、判断、填空、简答、主观\n"
                "3. answer 只能是：单个大写字母(如 B)、多个大写字母(如 ACD)、"
                "正确/错误、或分号分隔的要点\n"
                "4. 直接输出 JSON，不要写'分析如下'等前缀文字"
            )},
        ]

    def build_multimodal_messages(self, base64_image: str, is_subjective: bool = False) -> list:
        """构建多模态模式的消息列表（图片 + 文字）"""
        system_prompt = self._build_system_prompt(is_subjective)
        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": (
                        "【任务】分析这张题目截图，选出正确答案。\n\n"
                        "【输出要求 — 必须遵守】\n"
                        "1. 只输出一个 JSON 对象，用 ```json ``` 包裹，不要输出任何其他文字\n"
                        "2. question_type 只能是：单选、多选、判断、填空、简答、主观\n"
                        "3. answer 只能是：单个大写字母(如 B)、多个大写字母(如 ACD)、"
                        "正确/错误、或分号分隔的要点\n"
                        "4. 直接输出 JSON，不要写'分析如下'等前缀文字"
                    )},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64_image}"},
                    },
                ],
            },
        ]


# ========== 异步调用封装（供 GUI 线程使用）==========

from PyQt5.QtCore import QObject, pyqtSignal, QThread


class LLMWorker(QThread):
    """
    后台线程调用 LLM，避免界面卡顿
    token_received(token: str): 收到一个 token（流式）
    thinking_received(text: str): 收到思考过程文本
    finished(result: dict): 完成信号，返回解析后的答案 dict
    error(msg: str): 错误信号
    """
    token_received = pyqtSignal(str)
    thinking_received = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, client: LLMClient, messages: list):
        super().__init__()
        self.client = client
        self.messages = messages

    def run(self):
        try:
            # 非流式模式：不传 on_token/on_thinking 回调
            if self.client.stream_enabled:
                def on_token(tok: str):
                    try:
                        self.token_received.emit(tok)
                    except Exception:
                        pass

                def on_thinking(txt: str):
                    try:
                        self.thinking_received.emit(txt)
                    except Exception:
                        pass

                result = self.client.chat_completion(
                    self.messages,
                    on_token=on_token,
                    on_thinking=on_thinking,
                )
            else:
                result = self.client.chat_completion(self.messages)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
