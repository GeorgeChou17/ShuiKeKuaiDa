"""
配置管理模块
使用 JSON 文件持久化用户配置，避免 QSettings 的类型转换问题

新增功能配置：
- 最多12个选项，支持自定义选项名称
- 题型预设（名称、选项位置、下一题位置、自动切换开关）
- LLM 身份（自定义 system prompt）
- 主观题关键词及弹出答案窗口
- 自定义快捷键
- 答题过程浮动窗口设置
"""
import json
import os
from PyQt5.QtCore import QRect, QPoint


class ConfigManager:
    """管理所有用户配置（JSON 文件存储）"""

    ORG_NAME = "AnswerAssistant"
    APP_NAME = "LLMAnswerAssistant"

    def __init__(self):
        # 配置文件路径：放在用户 AppData/Local 下
        appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        config_dir = os.path.join(appdata, self.ORG_NAME, self.APP_NAME)
        os.makedirs(config_dir, exist_ok=True)
        self._config_path = os.path.join(config_dir, "config.json")
        self._data = self._load_file()
        self._defaults = self._get_defaults()
        # 合并默认值（新增字段自动补齐）
        for k, v in self._defaults.items():
            if k not in self._data:
                self._data[k] = v
        # 迁移：旧版 max_tokens 默认 512 → 新版默认 2048
        if self._data.get("llm/max_tokens") == 512:
            self._data["llm/max_tokens"] = 2048
        # 迁移：旧版默认 OpenAI → 新版默认七牛云
        if self._data.get("llm/base_url") == "https://api.openai.com/v1":
            self._data["llm/base_url"] = "https://api.qnaigc.com/v1"
        if self._data.get("llm/model_name") == "gpt-4o":
            self._data["llm/model_name"] = "z-ai/glm-4.5-air-free"
        self._save_file()

    def _load_file(self) -> dict:
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_file(self):
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def _get_defaults(self) -> dict:
        return {
            # LLM API (默认使用七牛云免费模型)
            "llm/base_url": "https://api.qnaigc.com/v1",
            "llm/api_key": "",
            "llm/model_name": "z-ai/glm-4.5-air-free",
            "llm/thinking_enabled": False,
            "llm/stream_enabled": False,     # 流式输出（免费模型通常不支持）
            "llm/temperature": 0.0,
            "llm/max_tokens": 2048,
            "llm/timeout": 300,
            # LLM 身份（自定义 system prompt 前缀）
            "llm/identity": "",
            # 工作模式
            "mode": "ocr",
            # 截图区域（x, y, w, h）
            "screenshot/region": None,
            # 选项配置：[{"name": "A", "x": x, "y": y}, ...]
            "positions/options": [],
            # "下一题"按钮坐标 (x, y)
            "positions/next_button": None,
            # 题型预设：{"预设名": {"options": [...], "next_button": (x,y)}}
            "presets": {},
            # 题型自动切换（OCR 检测后自动切换预设）
            "presets/auto_switch": True,
            # 主观题关键词（逗号分隔）
            "subjective/keywords": "主观题,简答题,论述题,分析题,材料题",
            # 主观题答案窗口置顶
            "subjective/window_pinned": True,
            # 自定义快捷键
            "hotkeys/start": "F9",
            "hotkeys/pause": "F10",
            "hotkeys/switch_mode": "F11",
            "hotkeys/manual_subjective": "F12",
            # 答题过程浮动窗口
            "floating_window/enabled": True,
            "floating_window/pinned": True,
            # OCR 引擎选择
            "ocr/engine": "paddleocr",
            # OCR 性能设置
            "ocr/use_angle_cls": True,      # 角度分类（关闭可提速 ~30%）
            "ocr/lang": "ch",                # 语言模型：ch/en/ch_en
            "ocr/max_img_side": 960,         # 图片预处理最大边长（减少可提速）
            "ocr/device": "auto",            # 计算设备：auto/gpu/cpu（auto=优先GPU）
            # 自动刷题延迟
            "auto/delay_ms": 200,
        }

    # ========== 通用 ==========
    def get(self, key, default=None):
        val = self._data.get(key)
        if val is None:
            return self._defaults.get(key, default)
        return val

    def set(self, key, value):
        self._data[key] = value
        self._save_file()

    def reset(self):
        self._data = dict(self._defaults)
        self._save_file()

    # ========== LLM 配置 ==========
    def get_llm_config(self) -> dict:
        return {
            "base_url": self.get("llm/base_url"),
            "api_key": self.get("llm/api_key"),
            "model_name": self.get("llm/model_name"),
            "thinking_enabled": self.get("llm/thinking_enabled"),
            "temperature": self.get("llm/temperature"),
            "max_tokens": self.get("llm/max_tokens"),
            "timeout": self.get("llm/timeout"),
            "stream_enabled": self.get("llm/stream_enabled"),
            "identity": self.get("llm/identity"),
        }

    def set_llm_config(self, **kwargs):
        for k, v in kwargs.items():
            self.set(f"llm/{k}", v)

    def get_llm_identity(self) -> str:
        return self.get("llm/identity", "")

    def set_llm_identity(self, text: str):
        self.set("llm/identity", text)

    # ========== 截图区域 ==========
    def get_screenshot_region(self):
        v = self.get("screenshot/region")
        if v is None:
            return None
        try:
            x, y, w, h = int(v[0]), int(v[1]), int(v[2]), int(v[3])
            return QRect(x, y, w, h)
        except (TypeError, ValueError, IndexError):
            return None

    def set_screenshot_region(self, rect: QRect):
        self.set("screenshot/region", [rect.x(), rect.y(), rect.width(), rect.height()])

    # ========== 选项坐标（支持自定义名称和最多12个）==========
    def get_option_positions(self) -> list:
        """
        返回 [{"name": "A", "x": x, "y": y}, ...]
        兼容旧格式 [(x,y), ...] 以实现平滑迁移
        """
        raw = self.get("positions/options", [])
        if not raw:
            return []
        # 兼容旧格式
        if isinstance(raw[0], (list, tuple)):
            names = ["A","B","C","D","E","F","G","H","I","J","K","L"]
            return [{"name": names[i] if i < len(names) else str(i+1),
                     "x": int(v[0]), "y": int(v[1])} for i, v in enumerate(raw)]
        # 确保类型正确
        return [{"name": o.get("name", "?"), "x": int(o["x"]), "y": int(o["y"])} for o in raw]

    def set_option_positions(self, options: list):
        self.set("positions/options", options)

    def get_option_count(self) -> int:
        return len(self.get_option_positions())

    # ========== 下一题按钮坐标 ==========
    def get_next_button_pos(self):
        v = self.get("positions/next_button")
        if v is None:
            return None
        try:
            if isinstance(v, dict):
                return (int(v["x"]), int(v["y"]))
            return (int(v[0]), int(v[1]))
        except (TypeError, ValueError, IndexError):
            return None

    def set_next_button_pos(self, pos):
        if isinstance(pos, (list, tuple)):
            self.set("positions/next_button", [int(pos[0]), int(pos[1])])
        else:
            self.set("positions/next_button", pos)

    # ========== 题型预设管理 ==========
    def get_presets(self) -> dict:
        return self.get("presets", {})

    def save_preset(self, name: str, options: list, next_button=None):
        presets = self.get_presets()
        presets[name] = {
            "options": options,
            "next_button": list(next_button) if next_button else None,
        }
        self.set("presets", presets)

    def delete_preset(self, name: str):
        presets = self.get_presets()
        if name in presets:
            del presets[name]
            self.set("presets", presets)

    def load_preset(self, name: str):
        presets = self.get_presets()
        if name not in presets:
            return False
        p = presets[name]
        self.set_option_positions(p["options"])
        self.set_next_button_pos(p["next_button"])
        return True

    def get_auto_switch_preset(self) -> bool:
        return bool(self.get("presets/auto_switch", True))

    def set_auto_switch_preset(self, enabled: bool):
        self.set("presets/auto_switch", enabled)

    # ========== 主观题 ==========
    def get_subjective_keywords(self) -> list:
        raw = self.get("subjective/keywords", "")
        return [k.strip() for k in raw.split(",") if k.strip()]

    def set_subjective_keywords(self, keywords: list):
        self.set("subjective/keywords", ",".join(keywords))

    def get_subjective_window_pinned(self) -> bool:
        return bool(self.get("subjective/window_pinned", True))

    def set_subjective_window_pinned(self, pinned: bool):
        self.set("subjective/window_pinned", pinned)

    # ========== 自定义快捷键 ==========
    def get_hotkey(self, action: str) -> str:
        return self.get(f"hotkeys/{action}", "")

    def set_hotkey(self, action: str, key: str):
        self.set(f"hotkeys/{action}", key)

    def get_all_hotkeys(self) -> dict:
        return {
            "start": self.get("hotkeys/start", "F9"),
            "pause": self.get("hotkeys/pause", "F10"),
            "switch_mode": self.get("hotkeys/switch_mode", "F11"),
            "manual_subjective": self.get("hotkeys/manual_subjective", "F12"),
        }

    def set_all_hotkeys(self, hotkeys: dict):
        for k, v in hotkeys.items():
            self.set(f"hotkeys/{k}", v)

    # ========== 浮动答题窗口 ==========
    def get_floating_window_enabled(self) -> bool:
        return bool(self.get("floating_window/enabled", True))

    def set_floating_window_enabled(self, enabled: bool):
        self.set("floating_window/enabled", enabled)

    def get_floating_window_pinned(self) -> bool:
        return bool(self.get("floating_window/pinned", True))

    def set_floating_window_pinned(self, pinned: bool):
        self.set("floating_window/pinned", pinned)

    # ========== 模式 ==========
    def get_mode(self) -> str:
        return self.get("mode", "ocr")

    def set_mode(self, mode: str):
        self.set("mode", mode)

    # ========== OCR 引擎 ==========
    def get_ocr_engine(self) -> str:
        return self.get("ocr/engine", "paddleocr")

    def set_ocr_engine(self, engine: str):
        self.set("ocr/engine", engine)
    
    def get_ocr_settings(self) -> dict:
        return {
            "use_angle_cls": bool(self.get("ocr/use_angle_cls", True)),
            "lang": self.get("ocr/lang", "ch"),
            "max_img_side": int(self.get("ocr/max_img_side", 960)),
            "device": self.get("ocr/device", "auto"),
        }
    
    def set_ocr_settings(self, use_angle_cls: bool = True, lang: str = "ch", max_img_side: int = 960, device: str = "auto"):
        self.set("ocr/use_angle_cls", use_angle_cls)
        self.set("ocr/lang", lang)
        self.set("ocr/max_img_side", max_img_side)
        self.set("ocr/device", device)

    # ========== 自动刷题 ==========
    def get_auto_delay(self) -> int:
        return int(self.get("auto/delay_ms", 200))

    def set_auto_delay(self, ms: int):
        self.set("auto/delay_ms", ms)
