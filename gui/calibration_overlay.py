"""校准浮层：红色圆点 + 网格红线 + 实时偏移/间距调节"""
from PyQt5.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QSpinBox
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QFont


class CalibrationOverlay(QWidget):
    """全屏透明浮层，显示红色圆点 + 网格线 + 实时调节"""
    closed = pyqtSignal()
    offset_changed = pyqtSignal(int, int)
    spacing_changed = pyqtSignal(int, int)  # spacing_x, spacing_y

    def __init__(self, parent=None, offset_x=0, offset_y=0,
                 grid_rows=1, grid_cols=1, spacing_x=0, spacing_y=0):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        screen = self.screen().geometry() if self.screen() else self.geometry()
        self._screen_w = screen.width()
        self._screen_h = screen.height()

        self._base_x = 0
        self._base_y = 0
        self._circle_x = 0
        self._circle_y = 0
        self._grid_anchor_x = 0  # 网格锚点（选项A的位置）
        self._grid_anchor_y = 0
        self._radius = 18
        self._target_name = "?"

        self._grid_rows = grid_rows
        self._grid_cols = grid_cols
        self._spacing_x = spacing_x
        self._spacing_y = spacing_y

        # --- 控制栏（右下角） ---
        self._ctrl = QWidget(self)
        self._ctrl.setStyleSheet("background:rgba(30,30,30,220); border-radius:8px; padding:8px; color:#fff;")
        ctrl_layout = QVBoxLayout(self._ctrl)
        ctrl_layout.setContentsMargins(10, 8, 10, 8)

        title = QLabel("校准模式")
        title.setStyleSheet("color:#fff; font-weight:bold; font-size:14px;")
        ctrl_layout.addWidget(title)

        # 偏移
        row_off = QHBoxLayout()
        row_off.addWidget(self._make_label("偏移X:"))
        self._spin_dx = QSpinBox()
        self._spin_dx.setRange(-200, 200); self._spin_dx.setValue(offset_x)
        self._spin_dx.valueChanged.connect(self._redraw)
        row_off.addWidget(self._spin_dx)
        row_off.addWidget(self._make_label("Y:"))
        self._spin_dy = QSpinBox()
        self._spin_dy.setRange(-200, 200); self._spin_dy.setValue(offset_y)
        self._spin_dy.valueChanged.connect(self._redraw)
        row_off.addWidget(self._spin_dy)
        ctrl_layout.addLayout(row_off)

        # 间距（仅当网格 ≥ 1×1 时显示）
        if grid_rows * grid_cols >= 2:
            row_sp = QHBoxLayout()
            row_sp.addWidget(self._make_label("间距X:"))
            self._spin_sx = QSpinBox()
            self._spin_sx.setRange(0, 2000); self._spin_sx.setValue(spacing_x)
            self._spin_sx.valueChanged.connect(self._redraw)
            row_sp.addWidget(self._spin_sx)
            row_sp.addWidget(self._make_label("Y:"))
            self._spin_sy = QSpinBox()
            self._spin_sy.setRange(0, 500); self._spin_sy.setValue(spacing_y)
            self._spin_sy.valueChanged.connect(self._redraw)
            row_sp.addWidget(self._spin_sy)
            ctrl_layout.addLayout(row_sp)
        else:
            self._spin_sx = None
            self._spin_sy = None

        self._info_label = QLabel("目标: ?")
        self._info_label.setStyleSheet("color:#ff6; font-size:11px;")
        ctrl_layout.addWidget(self._info_label)

        btn_row = QHBoxLayout()
        self._btn_ok = QPushButton("保存校准")
        self._btn_ok.clicked.connect(self._on_save)
        self._btn_ok.setStyleSheet("background:#4a4; color:#fff; padding:4px 12px; border-radius:4px;")
        btn_row.addWidget(self._btn_ok)
        self._btn_cancel = QPushButton("关闭")
        self._btn_cancel.clicked.connect(lambda: self.close())
        self._btn_cancel.setStyleSheet("background:#555; color:#ccc; padding:4px 12px; border-radius:4px;")
        btn_row.addWidget(self._btn_cancel)
        ctrl_layout.addLayout(btn_row)

        self._ctrl.adjustSize()
        self._ctrl.move(screen.width() - self._ctrl.width() - 20,
                        screen.height() - self._ctrl.height() - 20)

        self.resize(self._screen_w, self._screen_h)
        self.move(0, 0)
        self.show()
        self.raise_()

    @staticmethod
    def _make_label(text):
        l = QLabel(text)
        l.setStyleSheet("color:#ddd; font-size:12px;")
        return l

    def set_target_and_grid(self, name, target_base_x, target_base_y, grid_anchor_x, grid_anchor_y):
        """设置目标圆点基准 + 网格锚点（选项A的位置）"""
        self._target_name = name
        self._base_x = target_base_x
        self._base_y = target_base_y
        self._grid_anchor_x = grid_anchor_x
        self._grid_anchor_y = grid_anchor_y
        self._redraw()

    def _redraw(self):
        dx = self._spin_dx.value(); dy = self._spin_dy.value()
        self._circle_x = self._base_x + dx
        self._circle_y = self._base_y + dy
        if self._spin_sx: self._spacing_x = self._spin_sx.value()
        if self._spin_sy: self._spacing_y = self._spin_sy.value()
        self._info_label.setText(
            f"目标:{self._target_name}  预测:({self._circle_x},{self._circle_y})"
        )
        self.repaint()

    def _on_save(self):
        self.offset_changed.emit(self._spin_dx.value(), self._spin_dy.value())
        if self._spin_sx and self._spin_sy:
            self.spacing_changed.emit(self._spin_sx.value(), self._spin_sy.value())
        self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 网格线：当行列≥2或间距>0时显示
        r, c = self._grid_rows, self._grid_cols
        draw_grid = (r * c >= 2) or self._spacing_x > 0 or self._spacing_y > 0
        if draw_grid:
            sx = self._spacing_x if self._spacing_x > 0 else 0
            sy = self._spacing_y if self._spacing_y > 0 else 70  # 默认行距70px供预览
            anchor_x = self._grid_anchor_x + self._spin_dx.value()
            anchor_y = self._grid_anchor_y + self._spin_dy.value()

            grid_pen = QPen(QColor(255, 80, 80, 60), 1, Qt.DashLine)
            painter.setPen(grid_pen)
            font = QFont("Arial", 9)
            painter.setFont(font)

            for col in range(c):
                # 每列一条竖线（向下贯穿所有行）
                x = anchor_x + col * sx
                y1 = anchor_y
                y2 = anchor_y + (r - 1) * sy
                if col > 0 or sx > 0:  # 第一列且间距为0时不画竖线
                    painter.drawLine(int(x), int(y1), int(x), int(y2))

            for row in range(r):
                # 每行一条横线（向右贯穿所有列）
                y = anchor_y + row * sy
                x1 = anchor_x
                x2 = anchor_x + (c - 1) * sx
                painter.drawLine(int(x1), int(y), int(x2), int(y))

            # 在交叉点画小圆点标记
            dot_pen = QPen(QColor(255, 100, 100, 100), 2)
            painter.setPen(dot_pen)
            for col in range(c):
                for row in range(r):
                    px, py = int(anchor_x + col * sx), int(anchor_y + row * sy)
                    painter.drawEllipse(px - 3, py - 3, 6, 6)

        # 目标圆点（高亮）
        cx, cy = self._circle_x, self._circle_y
        if cx > 0 and cy > 0:
            painter.setPen(QPen(QColor(255, 40, 40), 3))
            painter.setBrush(QColor(255, 60, 60, 80))
            painter.drawEllipse(int(cx - self._radius), int(cy - self._radius),
                                self._radius * 2, self._radius * 2)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawLine(int(cx - 8), int(cy), int(cx + 8), int(cy))
            painter.drawLine(int(cx), int(cy - 8), int(cx), int(cy + 8))

        painter.fillRect(self.rect(), QColor(0, 0, 0, 30))

    def closeEvent(self, event):
        self.closed.emit()
        event.accept()
