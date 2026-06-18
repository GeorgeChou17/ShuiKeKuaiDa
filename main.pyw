"""
启动入口（.pyw 扩展名，无控制台窗口）
- Windows 下 .pyw 文件默认用 pythonw.exe 打开，不显示黑色 CMD 窗口
- 将 stdout/stderr 重定向到 log 文件，防止 print()/logging 崩溃
"""
import sys
import os
import traceback
import datetime

# 全局异常钩子：捕获所有未处理的异常，记录到 crash.log
def _global_exception_handler(exc_type, exc_value, exc_tb):
    crash_log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash.log")
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        with open(crash_log, "a", encoding="utf-8") as f:
            f.write(f"\n\n=== {datetime.datetime.now()} ===\n")
            f.write(tb_str)
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _global_exception_handler

# PaddleOCR 3.x 在 Windows CPU 上必须禁用 OneDNN，否则推理崩溃
# 必须在 import paddle/paddleocr 之前设置
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")

# 修复 Qt 平台插件找不到的问题（qwindows.dll）
try:
    import PyQt5
    _qt_plugin_path = os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins", "platforms")
    if os.path.isdir(_qt_plugin_path):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = _qt_plugin_path
except Exception:
    pass

# 关键修复：防止 PaddlePaddle 调用 where.exe 导致 0xc0000142 崩溃
# （同 main.py 中的 _patch_subprocess_for_paddle）
def _patch_subprocess_for_paddle():
    if sys.platform != "win32":
        return
    import subprocess
    _orig = subprocess.check_output
    def _safe(*a, **kw):
        cmd = a[0] if a else kw.get("args", [])
        if isinstance(cmd, (list, tuple)) and cmd:
            if str(cmd[0]).lower() in ("where", "where.exe", "which"):
                raise FileNotFoundError(f"[patched] {cmd}")
        return _orig(*a, **kw)
    subprocess.check_output = _safe

_patch_subprocess_for_paddle()

# 将 stdout/stderr 重定向到文件，避免 pythonw.exe 下 print() 崩溃
_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stdout.log")
try:
    _log_file = open(_log_path, "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_file
    sys.stderr = _log_file
except Exception:
    pass

# 配置 logging 输出到文件（pythonw.exe 下无控制台）
import logging
_log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
try:
    os.makedirs(_log_dir, exist_ok=True)
    _log_file_path = os.path.join(_log_dir, "app.log")
    _file_handler = logging.FileHandler(_log_file_path, encoding="utf-8")
    _file_handler.setLevel(logging.DEBUG)
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    _root_logger = logging.getLogger()
    _root_logger.setLevel(logging.DEBUG)
    # 清除已有的 handler（避免重复）
    _root_logger.handlers.clear()
    _root_logger.addHandler(_file_handler)
except Exception:
    pass

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入并运行主函数
from main import main

if __name__ == "__main__":
    main()
