"""
截图与区域选择模块
- ScreenshotTaker：使用 PyQt5 QScreen 截图，输出 PIL Image 或 base64
- RegionSelector：全屏透明覆盖层 + 橡皮筋框选截图区域（先截取桌面作为背景）
- PositionCalibrator：点击标定选项 & 下一题按钮坐标
"""
import base64
import io
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal, QTimer, QBuffer, QByteArray
from PyQt5.QtGui import QPixmap, QPainter, QPen, QColor, QScreen, QImage
from PyQt5.QtWidgets import QWidget, QApplication, QRubberBand

from PIL import Image


# ============================================================
# 1. 截图工具（PyQt5 QScreen，替代 mss，避免格式兼容问题）
# ============================================================
class ScreenshotTaker:
    """使用 PyQt5 QScreen 截图，输出 PIL Image 或 base64"""

    def __init__(self):
        # 延迟获取 screen，确保 QApplication 已存在
        self._screen = None

    def _get_screen(self):
        if self._screen is None:
            self._screen = QApplication.primaryScreen()
        return self._screen

    def grab_full(self) -> Image.Image:
        """全屏截图，返回 PIL Image（RGB）"""
        screen = self._get_screen()
        pixmap = screen.grabWindow(0)  # 截图整个屏幕
        return self._pixmap_to_pil(pixmap)

    def grab_region(self, rect: QRect) -> Image.Image:
        """
        截取指定区域
        rect: QRect，坐标系为屏幕坐标
        """
        screen = self._get_screen()
        # 截图整个屏幕，然后裁剪指定区域
        full_pixmap = screen.grabWindow(0)
        pixmap = full_pixmap.copy(rect)
        return self._pixmap_to_pil(pixmap)

    def _pixmap_to_pil(self, pixmap: QPixmap) -> Image.Image:
        """QPixmap → PIL Image（RGB）"""
        # 使用 QBuffer + QByteArray 正确转换（PyQt5 要求 QIODevice 类型）
        ba = QByteArray()
        buffer = QBuffer(ba)
        buffer.open(QBuffer.WriteOnly)
        pixmap.save(buffer, "PNG")
        buffer.close()
        return Image.open(io.BytesIO(ba.data())).convert("RGB")

    def to_base64(self, img: Image.Image, fmt: str = "PNG") -> str:
        """PIL Image → base64 字符串"""
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def save(self, img: Image.Image, path: str, fmt: str = "PNG"):
        img.save(path, format=fmt)

    def close(self):
        """兼容旧接口，无实际操作"""
        pass


# ============================================================
# 2. 橡皮筋框选覆盖层（先截桌面图作为背景，消除黑屏）
# ============================================================
class RegionSelector(QWidget):
    """
    全屏覆盖层，先截取当前桌面作为背景图，
    用户在该背景图上拖拽框选区域，不会黑屏。
    - 按 Esc 取消
    - 松开鼠标发射 region_selected(QRect)
    """
    region_selected = pyqtSignal(QRect)

    def __init__(self):
        super().__init__()
        # 无边框 + 置顶 + 工具窗口（不在任务栏显示）
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.CrossCursor)

        # 截取当前桌面作为背景
        screen = QApplication.primaryScreen()
        self._bg_pixmap = screen.grabWindow(0)

        # 全屏
        geom = screen.geometry()
        self.setGeometry(geom)
        self._screen_geom = geom

        self._origin = QPoint()
        self._rubber = QRubberBand(QRubberBand.Rectangle, self)
        # 橡皮筋样式：红色虚线边框 + 半透明填充
        self._rubber.setStyleSheet(
            "QRubberBand {"
            "  border: 2px dashed #E53935;"
            "  background: rgba(229, 57, 53, 40);"
            "}"
        )

    def paintEvent(self, ev):
        """绘制桌面背景图，让用户能看清底层内容"""
        painter = QPainter(self)
        # 绘制截取的桌面背景
        painter.drawPixmap(0, 0, self._bg_pixmap)
        # 绘制半透明暗色层（让用户知道进入了框选模式）
        overlay = QColor(0, 0, 0, 60)  # 仅 60/255 暗度，几乎不影响可视
        painter.fillRect(self.rect(), overlay)
        painter.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._origin = ev.globalPos()
            rect = QRect(self._origin, self._origin)
            self._rubber.setGeometry(rect)
            self._rubber.show()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if not self._origin.isNull():
            self._rubber.setGeometry(
                QRect(self._origin, ev.globalPos()).normalized()
            )
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._rubber.hide()
            rect = QRect(self._origin, ev.globalPos()).normalized()
            # 过滤极小框选（可能是误触）
            if rect.width() > 10 and rect.height() > 10:
                self.region_selected.emit(rect)
            else:
                pass  # 忽略过小框选
            self.close()
        super().mouseReleaseEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.close()
        super().keyPressEvent(ev)


# ============================================================
# 3. 坐标标定覆盖层（点击记录坐标）
# ============================================================
class PositionCalibrator(QWidget):
    """
    全屏透明覆盖层，每次点击记录全局坐标并发射
    - 右键 / Esc 结束
    - 用于标定：选项位置、"下一题"按钮位置
    """
    position_clicked = pyqtSignal(QPoint)  # 每次点击发射一个坐标
    finished = pyqtSignal()

    def __init__(self, max_clicks: int = 0, tip_text: str = "点击标定坐标"):
        """
        max_clicks: 最大点击次数，0 表示不限（手动结束）
        tip_text: 显示在顶部的提示文字
        """
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.PointingHandCursor)

        # 截取桌面背景，避免黑屏
        screen = QApplication.primaryScreen()
        self._bg_pixmap = screen.grabWindow(0)
        geom = screen.geometry()
        self.setGeometry(geom)
        self._max_clicks = max_clicks
        self._click_count = 0
        self._tip_text = tip_text

    def paintEvent(self, ev):
        painter = QPainter(self)
        # 绘制桌面背景
        painter.drawPixmap(0, 0, self._bg_pixmap)
        # 半透明暗色覆盖
        painter.fillRect(self.rect(), QColor(0, 0, 0, 45))
        # 顶部提示条
        painter.fillRect(0, 0, self.width(), 40, QColor(0, 0, 0, 180))
        painter.setPen(QColor(255, 255, 255))
        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        max_str = str(self._max_clicks) if self._max_clicks else "∞"
        tip = f"{self._tip_text}（已点击 {self._click_count}/{max_str}）｜左键点击 ｜ 右键/Esc 结束"
        painter.drawText(16, 26, tip)
        painter.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.RightButton:
            self.close()
            self.finished.emit()
            return
        if ev.button() == Qt.LeftButton:
            pos = ev.globalPos()
            self._click_count += 1
            self.position_clicked.emit(pos)
            self.update()  # 刷新提示文字
            if self._max_clicks > 0 and self._click_count >= self._max_clicks:
                self.close()
                self.finished.emit()
        super().mousePressEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.close()
            self.finished.emit()
        super().keyPressEvent(ev)
