"""
主入口
- 启动 PyQt5 应用
- 加载主窗口
"""
import sys
import os
import traceback
import datetime

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

# ============================================================
# 关键修复：防止 PaddlePaddle 调用 where.exe 导致 0xc0000142 崩溃
# PaddlePaddle 初始化时会调用 where.exe 查找 nvcc/ccache/hipcc，
# 但在加载大量 DLL 后 where.exe 子进程无法初始化，弹出 Windows 错误对话框。
# 拦截 where/which 命令，直接模拟"找不到程序"。
# ============================================================
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

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon


# 全局异常捕获：防止闪退看不到错误
def _global_excepthook(etype, value, tb):
    error_msg = "".join(traceback.format_exception(etype, value, tb))
    # 写入日志文件（即使没有控制台也能工作）
    try:
        log_path = os.path.join(os.path.dirname(__file__), "crash.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.datetime.now()} ===\n")
            f.write(error_msg)
            f.write("\n")
    except Exception:
        pass
    # 尝试打印到控制台（如果有），失败则忽略
    try:
        sys.__excepthook__(etype, value, tb)
    except Exception:
        pass

sys.excepthook = _global_excepthook


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LLM答题助手")
    app.setApplicationDisplayName("LLM 答题助手")
    # app.setWindowIcon(QIcon("resources/icon.ico"))  # 暂时注释，需自行添加图标文件

    from gui.main_window import MainWindow
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
