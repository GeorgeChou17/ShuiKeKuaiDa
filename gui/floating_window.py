"""
主观题答案浮动窗口
- 始终置顶（可切换）
- 可拖动位置
- 显示 LLM 答题过程和答案
- 支持复制答案文本
"""
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QLabel, QCheckBox,
    QSplitter, QTextBrowser,
)


class FloatingAnswerWindow(QMainWindow):
    """
    浮动答案窗口，显示 LLM 答题过程和最终答案
    支持：置顶切换、拖动、复制、清除
    """

    def __init__(self):
        super().__init__()
        self._old_pos = QPoint()
        self._is_pinned = True
        self._setup_ui()
        # 默认隐藏，有内容时才显示
        self.hide()

    def _setup_ui(self):
        self.setWindowTitle("答题过程 - LLM 答题助手")
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.resize(480, 360)
        # 移动到右上角
        try:
            from PyQt5.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen:
                sg = screen.geometry()
                self.move(sg.width() - 520, 40)
            else:
                self.move(400, 40)
        except Exception:
            self.move(400, 40)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)

        # ---- 顶部工具栏 ----
        top_bar = QHBoxLayout()

        self.btn_pin = QPushButton("📌 置顶")
        self.btn_pin.setCheckable(True)
        self.btn_pin.setChecked(True)
        self.btn_pin.clicked.connect(self._toggle_pin)
        self.btn_pin.setMaximumWidth(80)
        self.btn_pin.setStyleSheet(self._pin_button_style(True))

        self.lbl_title = QLabel("LLM 答题过程")
        self.lbl_title.setStyleSheet("color:#fff; font-weight:bold; font-size:13px;")

        self.btn_clear = QPushButton("清除")
        self.btn_clear.clicked.connect(self.clear_all)
        self.btn_clear.setMaximumWidth(60)

        self.btn_hide = QPushButton("✕")
        self.btn_hide.clicked.connect(self.hide)
        self.btn_hide.setMaximumWidth(30)
        self.btn_hide.setStyleSheet("background:#f44336; color:white; border-radius:4px;")

        top_bar.addWidget(self.btn_pin)
        top_bar.addWidget(self.lbl_title)
        top_bar.addStretch()
        top_bar.addWidget(self.btn_clear)
        top_bar.addWidget(self.btn_hide)
        main_layout.addLayout(top_bar)

        # ---- 分割：思考过程 + 答案 ----
        splitter = QSplitter(Qt.Vertical)

        # 思考过程（流式显示）
        thinking_widget = QWidget()
        thinking_layout = QVBoxLayout(thinking_widget)
        thinking_layout.setContentsMargins(0, 0, 0, 0)
        lbl_think = QLabel("思考过程：")
        lbl_think.setStyleSheet("color:#aaa; font-size:11px;")
        thinking_layout.addWidget(lbl_think)
        self.txt_thinking = QTextEdit()
        self.txt_thinking.setReadOnly(True)
        self.txt_thinking.setMaximumHeight(160)
        self.txt_thinking.setStyleSheet(
            "background:#1e1e1e; color:#ddd; font-size:11px; border:1px solid #444; border-radius:4px;"
        )
        thinking_layout.addWidget(self.txt_thinking)
        splitter.addWidget(thinking_widget)

        # 答案区域
        answer_widget = QWidget()
        answer_layout = QVBoxLayout(answer_widget)
        answer_layout.setContentsMargins(0, 0, 0, 0)
        lbl_ans = QLabel("答案：")
        lbl_ans.setStyleSheet("color:#4CAF50; font-size:11px; font-weight:bold;")
        answer_layout.addWidget(lbl_ans)
        self.txt_answer = QTextEdit()
        self.txt_answer.setReadOnly(False)   # 允许选择复制
        self.txt_answer.setStyleSheet(
            "background:#1e1e1e; color:#4CAF50; "
            "font-size:13px; font-weight:bold; border:1px solid #4CAF50; border-radius:4px;"
        )
        answer_layout.addWidget(self.txt_answer)
        splitter.addWidget(answer_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter)

        # ---- 底部状态 ----
        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet("color:#888; font-size:10px;")
        main_layout.addWidget(self.lbl_status)

        # 整体样式
        self.setStyleSheet("""
            QMainWindow {
                background: #2b2b2b;
                border: 1px solid #555;
                border-radius: 8px;
            }
            QTextEdit {
                background: #1e1e1e;
                color: #ddd;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 4px;
            }
            QPushButton {
                background: #444;
                color: #ddd;
                border: none;
                padding: 3px 8px;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:checked {
                background: #4CAF50;
                color: white;
            }
            QPushButton:hover {
                background: #666;
            }
        """)

    def _pin_button_style(self, pinned: bool) -> str:
        if pinned:
            return "background:#4CAF50; color:white; border-radius:4px; padding:3px 8px; font-size:11px;"
        return "background:#555; color:#ddd; border-radius:4px; padding:3px 8px; font-size:11px;"

    def _toggle_pin(self):
        self._is_pinned = not self._is_pinned
        self.btn_pin.setChecked(self._is_pinned)
        self.btn_pin.setText("📌 置顶" if self._is_pinned else "📌 普通")
        self.btn_pin.setStyleSheet(self._pin_button_style(self._is_pinned))

        if self._is_pinned:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()   # 刷新窗口标志需要 hide+show

    def set_subjective_mode(self, is_subjective: bool):
        """主观题模式：更新标题"""
        if is_subjective:
            self.lbl_title.setText("主观题答案")
            self.txt_answer.setStyleSheet(
                "background:#1e1e1e; color:#FF9800; "
                "font-size:13px; border:1px solid #FF9800; border-radius:4px;"
            )
        else:
            self.lbl_title.setText("LLM 答题过程")
            self.txt_answer.setStyleSheet(
                "background:#1e1e1e; color:#4CAF50; "
                "font-size:13px; font-weight:bold; border:1px solid #4CAF50; border-radius:4px;"
            )

    def append_thinking(self, text: str):
        """流式追加思考过程"""
        self.txt_thinking.append(text)
        # 自动滚动
        cursor = self.txt_thinking.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.txt_thinking.setTextCursor(cursor)

    def set_answer(self, text: str):
        """设置最终答案"""
        self.txt_answer.setText(text)
        self.lbl_status.setText("答案已更新")
        self.show()
        self.raise_()
        self.activateWindow()

    def clear_all(self):
        self.txt_thinking.clear()
        self.txt_answer.clear()
        self.lbl_status.setText("已清除")

    def clear_for_new_question(self):
        """新题目开始前清空，并设置初始状态"""
        self.txt_thinking.clear()
        self.txt_answer.clear()
        self.lbl_status.setText("Waiting for LLM...")
        self.show()
        self.raise_()
        self.activateWindow()

    def set_status(self, text: str):
        self.lbl_status.setText(text)

    # ========== 鼠标拖动支持 ==========
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._old_pos = ev.globalPos()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if not self._old_pos.isNull():
            delta = ev.globalPos() - self._old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self._old_pos = ev.globalPos()
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        self._old_pos = QPoint()
        super().mouseReleaseEvent(ev)

    def closeEvent(self, ev):
        # 隐藏而非关闭
        self.hide()
        ev.ignore()
