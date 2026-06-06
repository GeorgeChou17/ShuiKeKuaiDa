"""
OCR 识别模块
- 封装 PaddleOCR 3.x，提供本地 OCR 识别接口
- 支持中英文混合识别
- 返回结构化文字结果（题干、选项列表）

重要修复记录：
1. PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0 — 避免 OneDNN 推理崩溃
2. monkey-patch subprocess — 避免 PaddlePaddle 调用 where.exe 触发 0xc0000142
"""
import os
import sys
import logging

# 必须在 import paddleocr 之前设置，否则 Windows CPU 推理会崩溃
# 见 https://www.cnblogs.com/zmm521/p/18684355
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")


# ============================================================
# 关键修复：防止 PaddlePaddle 调用 where.exe 导致 0xc0000142 崩溃
#
# PaddlePaddle 的 extension_utils.py 在初始化时会调用:
#   subprocess.check_output(['where', 'nvcc'])
#   subprocess.check_output(['where', 'ccache'])
# 在 CPU-only 环境下这些命令必然失败，但 where.exe 子进程
# 因 PaddlePaddle 已加载大量 DLL 而无法初始化（0xc0000142），
# 弹出 Windows 错误对话框。
#
# 解决方案：monkey-patch subprocess.check_output，拦截 where/which
# 命令，直接抛出 FileNotFoundError（与正常找不到程序的行为一致），
# 不启动真实子进程。
# ============================================================
def _patch_subprocess_to_avoid_where_exe():
    """在 Windows 上拦截 where.exe 调用，防止 0xc0000142 崩溃"""
    if sys.platform != "win32":
        return

    import subprocess
    _original_check_output = subprocess.check_output

    def _safe_check_output(*args, **kwargs):
        # 检测是否在调用 where/which 命令
        cmd = args[0] if args else kwargs.get("args", [])
        if isinstance(cmd, (list, tuple)) and len(cmd) > 0:
            prog = str(cmd[0]).lower()
            # 拦截 where.exe / which 命令（PaddlePaddle 用于查找 nvcc/ccache/hipcc）
            if prog in ("where", "where.exe", "which"):
                # 直接抛出 FileNotFoundError，模拟"找不到程序"
                # PaddlePaddle 对此已有 try/except 处理
                raise FileNotFoundError(f"[已拦截] {cmd}")
        return _original_check_output(*args, **kwargs)

    subprocess.check_output = _safe_check_output


_patch_subprocess_to_avoid_where_exe()

logger = logging.getLogger(__name__)

# PaddleOCR 延迟导入，避免启动时就加载大模型
_paddle_ocr = None
_paddle_ocr_initialized = False
_last_ocr_params = (True, "ch", "auto")  # (use_angle_cls, lang, device)


def detect_gpu_info() -> dict:
    """
    检测系统中的 GPU 设备信息
    优先级：NVIDIA > AMD > Intel
    返回: {"available": bool, "type": str, "name": str, "count": int}
    """
    info = {"available": False, "type": "cpu", "name": "CPU", "count": 0}
    
    try:
        import paddle
        if paddle.is_compiled_with_cuda():
            count = paddle.device.cuda.device_count()
            if count > 0:
                info["available"] = True
                info["type"] = "nvidia"
                info["count"] = count
                # 获取 GPU 名称
                try:
                    info["name"] = paddle.device.cuda.get_device_name(0)
                except Exception:
                    info["name"] = f"NVIDIA CUDA GPU x{count}"
                return info
        
        # TODO: AMD ROCm 和 Intel XPU 检测（PaddlePaddle 3.x 开始支持）
        # 目前 PaddlePaddle 主要支持 NVIDIA CUDA
    except ImportError:
        pass
    
    return info


def resolve_device(device_pref: str = "auto") -> str:
    """
    根据用户偏好解析实际使用的设备
    
    参数:
        device_pref: "auto" / "gpu" / "cpu" / "gpu:nvidia" / "gpu:amd" / "gpu:intel"
    返回:
        "gpu" 或 "cpu"
    """
    if device_pref == "cpu":
        return "cpu"
    
    if device_pref == "gpu" or device_pref == "auto" or device_pref.startswith("gpu:"):
        gpu_info = detect_gpu_info()
        if gpu_info["available"]:
            # 检查优先级匹配
            if device_pref.startswith("gpu:"):
                vendor = device_pref.split(":", 1)[1]
                if gpu_info["type"] == vendor:
                    return "gpu"
                else:
                    logger.warning(f"未找到 {vendor} GPU，回退到 CPU")
                    return "cpu"
            return "gpu"
        else:
            if device_pref == "gpu":
                logger.warning("GPU 模式请求失败：未检测到可用 GPU，回退到 CPU")
            return "cpu"
    
    return "cpu"


def _get_paddle_ocr(use_angle_cls: bool = True, lang: str = "ch", device: str = "auto"):
    """懒加载 PaddleOCR，支持参数变化时重建"""
    global _paddle_ocr, _paddle_ocr_initialized, _last_ocr_params
    current_params = (use_angle_cls, lang, device)
    if _paddle_ocr_initialized and _last_ocr_params == current_params:
        return _paddle_ocr

    try:
        # 解析实际使用的设备
        actual_device = resolve_device(device)
        gpu_info = detect_gpu_info()
        logger.info(f"OCR 设备选择: 偏好={device}, 实际={actual_device}, GPU={gpu_info}")

        from paddleocr import PaddleOCR as _PaddleOCR
        
        # PaddleOCR 3.x — GPU 自动使用（如果安装了 paddlepaddle-gpu）
        # 通过设置环境变量或 Paddle API 控制设备
        if actual_device == "gpu":
            # 确保 Paddle 使用 GPU
            try:
                import paddle
                if paddle.is_compiled_with_cuda():
                    paddle.set_device("gpu")
                    logger.info("Paddle 已设置为 GPU 模式")
            except Exception as e:
                logger.warning(f"设置 GPU 模式失败: {e}，回退 CPU")
        
        _paddle_ocr = _PaddleOCR(
            lang=lang,
            use_textline_orientation=use_angle_cls,
        )
        _paddle_ocr_initialized = True
        _last_ocr_params = current_params
        logger.info(f"PaddleOCR 初始化成功 (lang={lang}, angle_cls={use_angle_cls}, device={actual_device})")
        return _paddle_ocr
    except Exception as e:
        logger.error(f"PaddleOCR 初始化失败: {e}")
        return None


def recognize_image(
    img_path: str | None = None,
    img=None,
    detail: bool = False,
    use_angle_cls: bool = True,
    lang: str = "ch",
    max_img_side: int = 960,
    device: str = "auto",
) -> dict:
    """
    使用 PaddleOCR 识别图片中的文字

    参数:
        img_path: 图片路径（可选）
        img: PIL Image 对象（可选，与 img_path 二选一）
        detail: 是否返回详细信息（置信度、坐标框）
        use_angle_cls: 是否启用角度分类（关闭可提速）
        lang: 语言模型（ch/en/ch_en）
        max_img_side: 图片预处理最大边长（缩小图片可提速）

    返回:
        {
            "text": "全部识别文字（合并）",
            "lines": [{"text": "...", "confidence": 0.99, "box": [...]}, ...],
            "success": True/False,
            "error": "错误信息（如果有）",
        }
    """
    result = {"text": "", "lines": [], "success": False, "error": None}

    ocr = _get_paddle_ocr(use_angle_cls=use_angle_cls, lang=lang, device=device)
    if ocr is None:
        result["error"] = "PaddleOCR 未初始化，请检查安装"
        return result

    try:
        # 准备输入：PaddleOCR 3.x predict() 接受图片路径或 numpy array
        if img is not None:
            import numpy as np
            from PIL import Image
            if isinstance(img, Image.Image):
                img = img.convert("RGB")
                # 图片预处理：限制最大边长以提速 OCR
                w, h = img.size
                if max(w, h) > max_img_side:
                    ratio = max_img_side / max(w, h)
                    new_size = (int(w * ratio), int(h * ratio))
                    # 使用高效的重采样
                    try:
                        img = img.resize(new_size, Image.LANCZOS)
                    except AttributeError:
                        img = img.resize(new_size, Image.BILINEAR)
                    logger.debug(f"图片已缩放: {w}x{h} → {new_size[0]}x{new_size[1]}")
                img = np.array(img)
            input_data = img
        elif img_path is not None:
            input_data = img_path
        else:
            result["error"] = "必须提供 img_path 或 img 参数"
            return result

        # PaddleOCR 3.x: 使用 predict() 代替已弃用的 ocr()
        ocr_results = list(ocr.predict(input_data))

        # 解析 PaddleOCR 3.x 返回结果（OCRResult 对象）
        lines = []
        all_text_parts = []

        if ocr_results:
            for ocr_res in ocr_results:
                try:
                    # OCRResult.json 是字典，格式：{"res": {"rec_texts": [...], "rec_scores": [...], ...}}
                    res_data = ocr_res.json
                    res = res_data.get("res", res_data) if isinstance(res_data, dict) else {}

                    rec_texts = res.get("rec_texts", [])
                    rec_scores = res.get("rec_scores", [])
                    rec_polys = res.get("rec_polys", res.get("dt_polys", []))

                    for i, text in enumerate(rec_texts):
                        confidence = float(rec_scores[i]) if i < len(rec_scores) else 0.0
                        box = rec_polys[i] if i < len(rec_polys) else []
                        lines.append({
                            "text": text,
                            "confidence": confidence,
                            "box": box,
                        })
                        all_text_parts.append(text)
                except Exception as e:
                    logger.warning(f"解析 OCRResult 失败: {e}")
                    # 尝试旧格式兼容
                    try:
                        if isinstance(ocr_res, list):
                            for line in ocr_res:
                                if isinstance(line, (list, tuple)) and len(line) >= 2:
                                    box = line[0]
                                    text = line[1][0] if isinstance(line[1], (list, tuple)) else str(line[1])
                                    confidence = line[1][1] if isinstance(line[1], (list, tuple)) and len(line[1]) > 1 else 0.0
                                    lines.append({"text": text, "confidence": float(confidence), "box": box})
                                    all_text_parts.append(text)
                    except Exception as e2:
                        logger.error(f"旧格式解析也失败: {e2}")

        full_text = "\n".join(all_text_parts)

        result["text"] = full_text
        result["lines"] = lines
        result["success"] = True
        return result

    except Exception as e:
        logger.error(f"OCR 识别失败: {e}")
        result["error"] = str(e)
        return result


def parse_question_text(ocr_text: str) -> dict:
    """
    将 OCR 识别到的题目文字解析为结构化数据
    尝试识别：题型、题干、选项（A/B/C/D）

    返回:
        {
            "raw_text": "原始 OCR 文字",
            "question_type": "单选/多选/判断/填空/简答（推测）",
            "stem": "题干文字",
            "options": ["A. xxx", "B. xxx", ...],   # 有序选项列表
            "option_map": {"A": "xxx", "B": "xxx", ...},  # 选项映射
        }
    """
    import re

    raw = ocr_text.strip()
    result = {
        "raw_text": raw,
        "question_type": "未知",
        "stem": "",
        "options": [],
        "option_map": {},
    }

    # 推测题型 — 优先匹配医学考试题型
    lower_raw = raw.lower()
    
    # A型题（A1/A2/A3/A4）：单选题变体
    if any(kw in raw for kw in ["A1型", "A1型题", "A1题型", "a1型"]):
        result["question_type"] = "单选"
    elif any(kw in raw for kw in ["A2型", "A2型题", "A2题型", "a2型"]):
        result["question_type"] = "单选"
    elif any(kw in raw for kw in ["A3型", "A3型题", "A3题型", "a3型"]):
        result["question_type"] = "单选"
    elif any(kw in raw for kw in ["A4型", "A4型题", "A4题型", "a4型"]):
        result["question_type"] = "单选"
    elif any(kw in raw for kw in ["A型", "A型题", "A题型"]):
        result["question_type"] = "单选"
    # B型题（配伍题）：一组题目共用选项
    elif any(kw in raw for kw in ["B型", "B型题", "B题型", "配伍", "共用选项"]):
        result["question_type"] = "单选"
    # X型题：多选题
    elif any(kw in raw for kw in ["X型", "X型题", "X题型", "x型"]):
        result["question_type"] = "多选"
    # 通用题型关键词
    elif any(kw in raw for kw in ["多选", "多选题", "多选題", "multiple"]):
        result["question_type"] = "多选"
    elif any(kw in raw for kw in ["单选", "单选题", "单选題", "single", "单项选择"]):
        result["question_type"] = "单选"
    elif any(kw in raw for kw in ["判断", "判断题", "判断題", "true/false", "T/F", "是非"]):
        result["question_type"] = "判断"
    elif any(kw in raw for kw in ["填空", "填空题", "填空題", "fill"]):
        result["question_type"] = "填空"
    elif any(kw in raw for kw in ["简答", "简答题", "简答題", "essay"]):
        result["question_type"] = "简答"

    # 提取选项（A. xxx / A、xxx / A xxx）
    # 支持 A-L 及中文选项符号
    option_pattern = re.compile(
        r"^[\s]*([A-La-lＡ-Ｌ①-⑫1-9])[\.\、\s、\.、\)](.*)$",
        re.MULTILINE
    )
    # 全角→半角，中文数字→字母 映射表
    _FULLWIDTH_MAP = {
        "Ａ": "A", "Ｂ": "B", "Ｃ": "C", "Ｄ": "D", "Ｅ": "E", "Ｆ": "F",
        "Ｇ": "G", "Ｈ": "H", "Ｉ": "I", "Ｊ": "J", "Ｋ": "K", "Ｌ": "L",
        "①": "A", "②": "B", "③": "C", "④": "D",
        "⑤": "E", "⑥": "F", "⑦": "G", "⑧": "H",
        "⑨": "I", "⑩": "J", "⑪": "K", "⑫": "L",
        "1": "A", "2": "B", "3": "C", "4": "D",
        "5": "E", "6": "F", "7": "G", "8": "H", "9": "I",
    }
    lines = raw.split("\n")
    option_lines = []
    stem_lines = []

    in_options = False
    for line in lines:
        m = option_pattern.match(line.strip())
        if m:
            in_options = True
            label = m.group(1).upper()
            # 统一转为 A/B/C/D...
            label = _FULLWIDTH_MAP.get(label, label)
            text = m.group(2).strip()
            option_lines.append((label, text))
            result["option_map"][label] = text
        else:
            if not in_options:
                stem_lines.append(line.strip())

    result["stem"] = " ".join(l for l in stem_lines if l)
    result["options"] = [f"{lbl}. {txt}" for lbl, txt in option_lines]

    return result


# ========== 异步识别封装（供 GUI 线程调用）==========
from PyQt5.QtCore import QObject, pyqtSignal, QThread


class OCRWorker(QThread):
    """
    在后台线程运行 OCR，避免界面卡顿
    finished(text: str, parsed: dict): 识别完成信号
    error(msg: str): 错误信号
    """
    finished = pyqtSignal(str, dict)   # raw_text, parsed_dict
    error = pyqtSignal(str)

    def __init__(self, img_path: str | None = None, img=None,
                 use_angle_cls: bool = True, lang: str = "ch", max_img_side: int = 960,
                 device: str = "auto"):
        super().__init__()
        self.img_path = img_path
        self.img = img
        self.use_angle_cls = use_angle_cls
        self.lang = lang
        self.max_img_side = max_img_side
        self.device = device

    def run(self):
        try:
            ocr_result = recognize_image(
                img=self.img, img_path=self.img_path,
                use_angle_cls=self.use_angle_cls,
                lang=self.lang,
                max_img_side=self.max_img_side,
                device=self.device,
            )
            if not ocr_result["success"]:
                self.error.emit(ocr_result.get("error", "OCR 识别失败"))
                return
            raw_text = ocr_result["text"]
            parsed = parse_question_text(raw_text)
            self.finished.emit(raw_text, parsed)
        except Exception as e:
            self.error.emit(str(e))
