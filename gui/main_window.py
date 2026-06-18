"""
主界面 GUI（PyQt5）- 完整版
集成了全部功能：
1. 修复黑屏问题（截图背景预览）
2. 支持最多12个选项，自定义选项名称
3. 题型预设管理及OCR自动切换
4. LLM 身份（自定义 system prompt）及输出格式规范
5. 主观题检测 + 浮动答案窗口
6. 自定义快捷键
7. 答题过程浮动窗口（可置顶/拖动）
"""
import sys
import logging
import json
import re
import time
from typing import List, Dict, Any, Optional

from PyQt5.QtCore import (
    Qt, QRect, QPoint, pyqtSignal, QObject,
    QThread, pyqtSlot, QTimer, QSettings
)
from PyQt5.QtGui import QPixmap, QIcon, QTextCursor, QFont, QKeySequence
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QDoubleSpinBox,
    QTextEdit, QGroupBox, QFormLayout, QLineEdit, QCheckBox,
    QStatusBar, QMessageBox, QFileDialog, QProgressBar,
    QTabWidget, QApplication, QListWidget, QListWidgetItem,
    QInputDialog, QSpinBox, QLineEdit, QLabel, QPushButton,
    QCheckBox, QComboBox, QTabWidget, QWidget, QVBoxLayout,
    QHBoxLayout, QGroupBox, QFormLayout, QTextEdit,
    QProgressBar, QStatusBar, QMessageBox, QDialog,
)

from core.config_manager import ConfigManager
from core.screenshot import ScreenshotTaker, RegionSelector, PositionCalibrator
from core.ocr_module import recognize_image, parse_question_text, OCRWorker
from core.llm_api import LLMClient, LLMWorker, LLMAPIError
from core.mouse_controller import MouseController, AnswerWorker
from gui.floating_window import FloatingAnswerWindow


# ============================================================
# 日志重定向到 QTextEdit
# ============================================================
class QTextEditLogger(logging.Handler):
    def __init__(self, text_edit: QTextEdit):
        super().__init__()
        self.widget = text_edit

    def emit(self, record):
        msg = self.format(record)
        self.widget.append(msg)
        cursor = self.widget.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.widget.setTextCursor(cursor)


# ============================================================
# 429 倒计时弹窗（非模态，确保 QTimer 可靠触发）
# ============================================================
class CountdownDialog(QDialog):
    """带倒计时的弹窗，超时后自动触发默认操作。使用非模态 show() 避免 exec_() 阻塞事件循环。"""

    retry_clicked = pyqtSignal()
    cancel_clicked = pyqtSignal()

    def __init__(self, parent, title, message, timeout_seconds):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.ApplicationModal)  # 对应用模态，但不阻塞事件循环处理 timer

        layout = QVBoxLayout(self)

        self.msg_label = QLabel(message)
        self.msg_label.setWordWrap(True)
        layout.addWidget(self.msg_label)

        self.countdown_label = QLabel(f"将在 {timeout_seconds} 秒后自动重试...")
        self.countdown_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.countdown_label)

        btn_layout = QHBoxLayout()
        self.retry_btn = QPushButton("立即重试")
        self.retry_btn.clicked.connect(self.on_retry)
        btn_layout.addWidget(self.retry_btn)

        self.cancel_btn = QPushButton("取消答题")
        self.cancel_btn.clicked.connect(self.on_cancel)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)
        self.setFixedSize(450, 200)

        # 倒计时
        self.remaining = timeout_seconds
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_countdown)
        self.timer.start(1000)

    def update_countdown(self):
        self.remaining -= 1
        if self.remaining <= 0:
            self.timer.stop()
            self.retry_clicked.emit()
            self.close()
        else:
            self.countdown_label.setText(f"将在 {self.remaining} 秒后自动重试...")

    def on_retry(self):
        self.timer.stop()
        self.retry_clicked.emit()
        self.close()

    def on_cancel(self):
        self.timer.stop()
        self.cancel_clicked.emit()
        self.close()

    def closeEvent(self, event):
        # 如果用户点击 X 关闭，默认重试
        self.timer.stop()
        if self.remaining > 0:
            self.retry_clicked.emit()
        event.accept()


# ============================================================
# 主窗口
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("水课快答 v1.3.3")
        self.setWindowIcon(QIcon("logo.ico"))
        self.resize(1000, 720)
        # 主界面字体
        font = self.font()
        font.setFamily("黑体")
        self.setFont(font)

        # 核心对象
        self.config = ConfigManager()
        self.screenshot_taker = ScreenshotTaker()
        self.mouse_ctrl = MouseController(
            click_delay_ms=self.config.get_auto_delay()
        )
        self.llm_client = None
        self.floating_win = None   # 浮动答案窗口

        # 运行时状态
        self._running = False
        self._paused = False
        self._current_ocr_text = ""
        self._current_image = None
        self._current_image_base64 = ""
        self._hotkey_handles = []   # 快捷键句柄列表

        # 初始化 UI
        self._setup_ui()
        self._load_config_to_ui()
        # 日志：将 logging 输出到 txt_log 控件
        logger = QTextEditLogger(self.txt_log)
        logger.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
        logging.getLogger().addHandler(logger)
        logging.getLogger().setLevel(logging.DEBUG)
        self._setup_hotkeys()   # 注册全局快捷键
        self._init_floating_window()

        logging.info("水课快答 v1.3.3 启动成功")

    # ========================================================
    # UI 构建
    # ========================================================
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # ---- 顶部：模式切换 + 状态 ----
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("工作模式："))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["OCR 模式", "多模态模式"])
        self.combo_mode.currentTextChanged.connect(self._on_mode_changed)
        top_bar.addWidget(self.combo_mode)
        top_bar.addStretch()
        self.lbl_status = QLabel("就绪")
        self.lbl_status.setStyleSheet("color:#888; font-size:12px;")
        top_bar.addWidget(self.lbl_status)
        main_layout.addLayout(top_bar)

        # ---- Tab 页 ----
        tabs = QTabWidget()
        main_layout.addWidget(tabs)

        # Tab1：主操作
        tab_main = QWidget()
        tabs.addTab(tab_main, "主操作")
        self._build_main_tab(tab_main)

        # Tab2：LLM 设置
        tab_llm = QWidget()
        tabs.addTab(tab_llm, "LLM 设置")
        self._build_llm_tab(tab_llm)

        # Tab3：题型预设
        tab_presets = QWidget()
        tabs.addTab(tab_presets, "题型预设")
        self._build_presets_tab(tab_presets)

        # Tab4：快捷键设置
        tab_hotkey = QWidget()
        tabs.addTab(tab_hotkey, "快捷键")
        self._build_hotkey_tab(tab_hotkey)

        # Tab5：运行日志
        tab_log = QWidget()
        tabs.addTab(tab_log, "运行日志")
        self._build_log_tab(tab_log)

        # Tab6：关于程序
        tab_about = QWidget()
        tabs.addTab(tab_about, "关于程序")
        self._build_about_tab(tab_about)

        # ---- 底部进度条 ----
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        main_layout.addWidget(self.progress)

        self.statusBar().showMessage("就绪")

    # ========================================================
    # Tab：主操作
    # ========================================================
    def _build_main_tab(self, tab: QWidget):
        layout = QVBoxLayout(tab)

        # ---- 区域选择 ----
        grp_region = QGroupBox("① 截图区域选择")
        region_layout = QHBoxLayout(grp_region)
        btn_region = QPushButton("📷 框选截图区域")
        btn_region.clicked.connect(self._select_region)
        self.lbl_region = QLabel("未选择")
        self.lbl_region.setStyleSheet("color:#888;")
        region_layout.addWidget(btn_region)
        region_layout.addWidget(self.lbl_region)
        region_layout.addStretch()
        layout.addWidget(grp_region)

        # ---- 选项配置 ----
        grp_opts = QGroupBox("② 选项配置（支持最多12个）")
        opts_layout = QVBoxLayout(grp_opts)

        # 选项数量
        h_count = QHBoxLayout()
        h_count.addWidget(QLabel("选项数量："))
        self.spin_opt_count = QSpinBox()
        self.spin_opt_count.setRange(2, 12)
        self.spin_opt_count.setValue(4)
        self.spin_opt_count.valueChanged.connect(self._on_option_count_changed)
        h_count.addWidget(self.spin_opt_count)
        h_count.addWidget(QLabel("  自定义选项名称（逗号分隔，留空使用 A/B/C...）："))
        self.edit_opt_names = QLineEdit()
        self.edit_opt_names.setPlaceholderText("例：A,B,C,D 或 一,二,三,四,五")
        self.edit_opt_names.setText("A,B,C,D,E,F,G,H,I,J,K,L")
        h_count.addWidget(self.edit_opt_names)
        h_count.addStretch()
        opts_layout.addLayout(h_count)

        # 标定按钮
        h_cal = QHBoxLayout()
        btn_cal_opts = QPushButton("🎯 标定选项位置")
        btn_cal_opts.clicked.connect(self._calibrate_options)
        self.lbl_options = QLabel("未标定")
        self.lbl_options.setStyleSheet("color:#888;")
        h_cal.addWidget(btn_cal_opts)
        h_cal.addWidget(self.lbl_options)
        h_cal.addStretch()
        opts_layout.addLayout(h_cal)

        # 下一题按钮
        h_next = QHBoxLayout()
        btn_cal_next = QPushButton("🎯 标定「下一题」按钮位置")
        btn_cal_next.clicked.connect(self._calibrate_next)
        self.lbl_next = QLabel("未标定")
        self.lbl_next.setStyleSheet("color:#888;")
        h_next.addWidget(btn_cal_next)
        h_next.addWidget(self.lbl_next)
        h_next.addStretch()
        opts_layout.addLayout(h_next)

        layout.addWidget(grp_opts)

        # ---- 题型预设快速切换 ----
        grp_preset = QGroupBox("③ 题型预设（自动切换）")
        pre_layout = QVBoxLayout(grp_preset)
        
        # 预设类别选择
        pre_row0 = QHBoxLayout()
        pre_row0.addWidget(QLabel("预设类别："))
        self.combo_category = QComboBox()
        self._refresh_category_combo()
        self.combo_category.currentTextChanged.connect(self._on_category_changed)
        pre_row0.addWidget(self.combo_category)
        pre_row0.addStretch()
        pre_layout.addLayout(pre_row0)
        
        pre_row1 = QHBoxLayout()
        pre_row1.addWidget(QLabel("当前预设："))
        self.combo_presets = QComboBox()
        self.combo_presets.addItem("（无预设）")
        self._refresh_presets_combo()
        self.combo_presets.currentTextChanged.connect(self._on_preset_selected)
        pre_row1.addWidget(self.combo_presets)
        btn_save_preset = QPushButton("💾 保存当前为预设")
        btn_save_preset.clicked.connect(self._save_current_preset)
        pre_row1.addWidget(btn_save_preset)
        btn_del_preset = QPushButton("🗑 删除预设")
        btn_del_preset.clicked.connect(self._delete_preset)
        pre_row1.addWidget(btn_del_preset)
        pre_row1.addStretch()
        pre_layout.addLayout(pre_row1)
        # 自动切换
        self.chk_auto_preset = QCheckBox("OCR 检测后自动切换预设（仅在当前类别内搜索）")
        self.chk_auto_preset.setChecked(self.config.get_auto_switch_preset())
        self.chk_auto_preset.toggled.connect(
            lambda v: self.config.set_auto_switch_preset(v)
        )
        pre_layout.addWidget(self.chk_auto_preset)
        layout.addWidget(grp_preset)

        # ---- 动态定位 ----
        grp_dynamic = QGroupBox("③½ 选项定位模式")
        dyn_layout = QVBoxLayout(grp_dynamic)
        
        dyn_row1 = QHBoxLayout()
        self.chk_dynamic_click = QCheckBox("启用动态选项定位（OCR 实时识别按钮坐标，解决题干长度变化导致选项偏移）")
        self.chk_dynamic_click.setChecked(self.config.get_dynamic_click())
        self.chk_dynamic_click.toggled.connect(self._on_dynamic_click_toggled)
        dyn_row1.addWidget(self.chk_dynamic_click)
        self.chk_dynamic_fallback = QCheckBox("动态定位不足时回退到固定坐标")
        self.chk_dynamic_fallback.setChecked(self.config.get_dynamic_fallback())
        self.chk_dynamic_fallback.toggled.connect(self._on_dynamic_fallback_toggled)
        dyn_row1.addWidget(self.chk_dynamic_fallback)
        dyn_layout.addLayout(dyn_row1)
        
        # 选项网格布局（预设中包含，非动态定位也生效）
        grid_row = QHBoxLayout()
        grid_row.addWidget(QLabel("选项布局（行列）："))
        self.spin_grid_rows = QSpinBox()
        self.spin_grid_rows.setRange(1, 10)
        self.spin_grid_rows.setValue(max(1, self.config.get_option_grid_rows()))
        self.spin_grid_rows.setToolTip("选项行数（如 5×1 填 5，3×2 填 3）")
        self.spin_grid_rows.valueChanged.connect(self._on_grid_changed)
        grid_row.addWidget(self.spin_grid_rows)
        grid_row.addWidget(QLabel("×"))
        self.spin_grid_cols = QSpinBox()
        self.spin_grid_cols.setRange(1, 10)
        self.spin_grid_cols.setValue(max(1, self.config.get_option_grid_cols()))
        self.spin_grid_cols.setToolTip("选项列数（如 5×1 填 1，3×2 填 2）")
        self.spin_grid_cols.valueChanged.connect(self._on_grid_changed)
        grid_row.addWidget(self.spin_grid_cols)
        grid_row.addStretch()
        dyn_layout.addLayout(grid_row)
        
        # 网格间距
        spacing_row = QHBoxLayout()
        spacing_row.addWidget(QLabel("网格间距（X/Y）："))
        self.spin_spacing_x = QSpinBox()
        self.spin_spacing_x.setRange(0, 2000)
        self.spin_spacing_x.setValue(max(0, self.config.get_grid_spacing_x()))
        self.spin_spacing_x.setToolTip("选项列间距（像素），0=使用默认")
        self.spin_spacing_x.valueChanged.connect(self._on_grid_changed)
        spacing_row.addWidget(self.spin_spacing_x)
        spacing_row.addWidget(QLabel("×"))
        self.spin_spacing_y = QSpinBox()
        self.spin_spacing_y.setRange(0, 500)
        self.spin_spacing_y.setValue(max(0, self.config.get_grid_spacing_y()))
        self.spin_spacing_y.setToolTip("选项行间距（像素），0=使用默认")
        self.spin_spacing_y.valueChanged.connect(self._on_grid_changed)
        spacing_row.addWidget(self.spin_spacing_y)
        spacing_row.addStretch()
        dyn_layout.addLayout(spacing_row)
        
        dyn_row2 = QHBoxLayout()
        self.btn_cal_btn_region = QPushButton("📷 框选选项按钮区域")
        self.btn_cal_btn_region.clicked.connect(self._calibrate_button_region)
        self.lbl_btn_region = QLabel("未框选")
        self.lbl_btn_region.setStyleSheet("color:#888;")
        dyn_row2.addWidget(self.btn_cal_btn_region)
        dyn_row2.addWidget(self.lbl_btn_region)
        dyn_row2.addStretch()
        dyn_layout.addLayout(dyn_row2)
        
        # 题型区域框选（用于自动切换预设）
        dyn_row3 = QHBoxLayout()
        self.btn_cal_type_region = QPushButton("📷 框选题型文字区域")
        self.btn_cal_type_region.clicked.connect(self._calibrate_type_region)
        self.lbl_type_region = QLabel("未框选")
        self.lbl_type_region.setStyleSheet("color:#888;")
        dyn_row3.addWidget(self.btn_cal_type_region)
        dyn_row3.addWidget(self.lbl_type_region)
        dyn_row3.addStretch()
        dyn_layout.addLayout(dyn_row3)
        
        # 校准模式 + 手动偏移
        cal_row = QHBoxLayout()
        self.chk_calibration = QCheckBox("校准模式（红色圆点预览，不实际点击）")
        self.chk_calibration.toggled.connect(self._on_calibration_toggled)
        cal_row.addWidget(self.chk_calibration)

        cal_row.addWidget(QLabel("  X偏移:"))
        self.spin_offset_x = QSpinBox()
        self.spin_offset_x.setRange(-200, 200)
        self.spin_offset_x.setValue(self.config.get_dynamic_offset().get("dx", 0) if self.config.get_dynamic_offset() else 0)
        self.spin_offset_x.setEnabled(False)
        self.spin_offset_x.valueChanged.connect(self._on_offset_changed)
        cal_row.addWidget(self.spin_offset_x)

        cal_row.addWidget(QLabel("Y偏移:"))
        self.spin_offset_y = QSpinBox()
        self.spin_offset_y.setRange(-200, 200)
        self.spin_offset_y.setValue(self.config.get_dynamic_offset().get("dy", 0) if self.config.get_dynamic_offset() else 0)
        self.spin_offset_y.setEnabled(False)
        self.spin_offset_y.valueChanged.connect(self._on_offset_changed)
        cal_row.addWidget(self.spin_offset_y)

        self.lbl_offset = QLabel("未校准")
        self.lbl_offset.setStyleSheet("color:#888;")
        cal_row.addWidget(self.lbl_offset)
        cal_row.addStretch()
        dyn_layout.addLayout(cal_row)
        
        layout.addWidget(grp_dynamic)

        # ---- 答题自动停止 ----
        grp_stop = QGroupBox("④ 答题自动停止")
        stop_layout = QVBoxLayout(grp_stop)
        
        stop_row1 = QHBoxLayout()
        stop_row1.addWidget(QLabel("停止模式："))
        self.combo_stop_mode = QComboBox()
        self.combo_stop_mode.addItems(["不自动停止", "OCR 识别题号（例如：1/100）", "手动设总题数"])
        self.combo_stop_mode.setCurrentIndex(0)
        self.combo_stop_mode.currentIndexChanged.connect(self._on_stop_mode_changed)
        stop_row1.addWidget(self.combo_stop_mode)
        stop_row1.addStretch()
        stop_layout.addLayout(stop_row1)
        
        # OCR 模式：框选题号区域
        stop_ocr_row = QHBoxLayout()
        self.btn_cal_progress = QPushButton("📷 框选题号区域")
        self.btn_cal_progress.clicked.connect(self._calibrate_progress_region)
        self.lbl_progress_region = QLabel("未框选")
        self.lbl_progress_region.setStyleSheet("color:#888;")
        stop_ocr_row.addWidget(self.btn_cal_progress)
        stop_ocr_row.addWidget(self.lbl_progress_region)
        stop_ocr_row.addStretch()
        stop_layout.addLayout(stop_ocr_row)
        
        # Count 模式：总题数
        stop_count_row = QHBoxLayout()
        stop_count_row.addWidget(QLabel("总题数："))
        self.spin_total_questions = QSpinBox()
        self.spin_total_questions.setRange(1, 9999)
        self.spin_total_questions.setValue(0)
        stop_count_row.addWidget(self.spin_total_questions)
        stop_count_row.addWidget(QLabel("道"))
        stop_count_row.addStretch()
        stop_layout.addLayout(stop_count_row)
        
        # 进度显示
        self.lbl_stop_progress = QLabel("")
        self.lbl_stop_progress.setStyleSheet("color:#4CAF50; font-weight:bold;")
        stop_layout.addWidget(self.lbl_stop_progress)
        
        layout.addWidget(grp_stop)

        # ---- 操作按钮 ----
        grp_action = QGroupBox("⑤ 开始答题")
        action_layout = QHBoxLayout(grp_action)
        self.btn_start = QPushButton("▶ 开始自动答题")
        self.btn_start.setStyleSheet(
            "background:#4CAF50; color:white; font-weight:bold; padding:8px 16px; font-size:14px;"
        )
        self.btn_start.clicked.connect(self._start_answering)
        self.btn_pause = QPushButton("⏸ 暂停")
        self.btn_pause.setStyleSheet("padding:8px 16px; font-size:14px;")
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_pause.setEnabled(False)
        self.btn_stop = QPushButton("■ 停止")
        self.btn_stop.setStyleSheet("background:#f44336; color:white; padding:8px 16px;")
        self.btn_stop.clicked.connect(self._stop_answering)
        self.btn_stop.setEnabled(False)
        action_layout.addWidget(self.btn_start)
        action_layout.addWidget(self.btn_pause)
        action_layout.addWidget(self.btn_stop)
        action_layout.addStretch()
        layout.addWidget(grp_action)

        # ---- 当前题目信息 ----
        grp_info = QGroupBox("当前题目信息")
        info_layout = QVBoxLayout(grp_info)
        self.txt_question_info = QTextEdit()
        self.txt_question_info.setReadOnly(True)
        self.txt_question_info.setMaximumHeight(100)
        info_layout.addWidget(self.txt_question_info)
        layout.addWidget(grp_info)

        layout.addStretch()

    # ========================================================
    # Tab：LLM 设置
    # ========================================================
    def _build_llm_tab(self, tab: QWidget):
        layout = QFormLayout(tab)

        # 七牛云引导链接
        from PyQt5.QtWidgets import QLabel as QLabelWidget
        link_label = QLabelWidget(
            '<a href="https://portal.qiniu.com/ai-inference/model" '
            'style="color:#2196F3; text-decoration:none;">'
            '免费 API 申请：七牛云平台 → 注册后获取 Key（学生免费额度）</a>'
        )
        link_label.setOpenExternalLinks(True)
        layout.addRow("", link_label)

        self.edit_base_url = QLineEdit()
        self.edit_base_url.setPlaceholderText("https://api.qnaigc.com/v1")
        layout.addRow("API Base URL：", self.edit_base_url)

        self.edit_api_key = QLineEdit()
        self.edit_api_key.setEchoMode(QLineEdit.Password)
        self.edit_api_key.setPlaceholderText("sk-...（七牛云控制台获取）")
        layout.addRow("API Key：", self.edit_api_key)

        self.edit_model = QLineEdit()
        self.edit_model.setPlaceholderText("z-ai/glm-4.5-air-free")
        layout.addRow("模型名称：", self.edit_model)

        self.chk_thinking = QCheckBox("启用思考模式（DeepSeek-R1 等支持）")
        layout.addRow("", self.chk_thinking)
        
        self.chk_stream = QCheckBox("启用流式输出（实时显示，免费模型建议关）")
        self.chk_stream.setChecked(False)
        layout.addRow("", self.chk_stream)

        # LLM 身份（自定义 system prompt）
        layout.addRow(QLabel("LLM 身份（自定义 System Prompt）："))
        self.edit_identity = QTextEdit()
        self.edit_identity.setPlaceholderText(
            "留空使用默认身份。\n"
            "可在此输入自定义角色设定，如："
            "「你是一名医学专业导师，擅长解答临床医学问题。」"
        )
        self.edit_identity.setMaximumHeight(80)
        layout.addRow(self.edit_identity)

        # 主观题关键词
        layout.addRow(QLabel("主观题关键词（逗号分隔）："))
        self.edit_subjective_kw = QLineEdit()
        self.edit_subjective_kw.setPlaceholderText("主观题,简答题,论述题,分析题,材料题")
        layout.addRow("", self.edit_subjective_kw)

        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(0.0, 2.0)
        self.spin_temp.setSingleStep(0.1)
        self.spin_temp.setValue(0.0)
        layout.addRow("温度（temperature）：", self.spin_temp)

        self.spin_max_tokens = QSpinBox()
        self.spin_max_tokens.setRange(64, 16384)
        self.spin_max_tokens.setValue(2048)
        layout.addRow("最大 Token 数：", self.spin_max_tokens)
        
        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(30, 600)
        self.spin_timeout.setValue(300)
        self.spin_timeout.setSuffix(" 秒")
        layout.addRow("LLM 超时时间：", self.spin_timeout)
        
        # 答题速度控制
        layout.addRow(QLabel("—— 答题速度与限流控制 ——"))
        
        self.spin_answer_interval = QSpinBox()
        self.spin_answer_interval.setRange(0, 120)
        self.spin_answer_interval.setValue(0)
        self.spin_answer_interval.setSuffix(" 秒")
        layout.addRow("答题间隔（0=无限制）：", self.spin_answer_interval)
        
        self.spin_retry_delay = QSpinBox()
        self.spin_retry_delay.setRange(5, 300)
        self.spin_retry_delay.setValue(30)
        self.spin_retry_delay.setSuffix(" 秒")
        layout.addRow("429 限流后重试等待：", self.spin_retry_delay)
        
        # ---- OCR 性能设置 ----
        layout.addRow(QLabel("—— OCR 性能设置 ——"))
        
        self.combo_ocr_device = QComboBox()
        self.combo_ocr_device.addItems(["cpu（仅CPU，推荐）", "auto（自动选择，可能不稳定）", "gpu（强制GPU）"])
        layout.addRow("OCR 计算设备：", self.combo_ocr_device)
        
        self.chk_ocr_angle = QCheckBox("启用角度分类（√=更准但更慢，取消可提速 ~30%）")
        self.chk_ocr_angle.setChecked(True)
        layout.addRow("", self.chk_ocr_angle)
        
        self.combo_ocr_lang = QComboBox()
        self.combo_ocr_lang.addItems(["ch（中英文）", "en（英文）", "ch_en（繁中+英文）"])
        layout.addRow("OCR 语言：", self.combo_ocr_lang)
        
        self.spin_ocr_size = QSpinBox()
        self.spin_ocr_size.setRange(480, 2560)
        self.spin_ocr_size.setValue(960)
        self.spin_ocr_size.setSuffix(" px")
        layout.addRow("图片预处理最大边长：", self.spin_ocr_size)

        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(0, 5000)
        self.spin_delay.setValue(200)
        self.spin_delay.setSuffix(" ms")
        layout.addRow("点击后延迟：", self.spin_delay)

        # 浮动窗口设置
        self.chk_float_enabled = QCheckBox("显示答题过程浮动窗口")
        self.chk_float_enabled.setChecked(self.config.get_floating_window_enabled())
        layout.addRow("", self.chk_float_enabled)
        self.chk_float_pinned = QCheckBox("浮动窗口始终置顶")
        self.chk_float_pinned.setChecked(self.config.get_floating_window_pinned())
        layout.addRow("", self.chk_float_pinned)

        btn_test = QPushButton("测试 API 连接")
        btn_test.clicked.connect(self._test_llm_connection)
        layout.addRow("", btn_test)

        btn_save = QPushButton("💾 保存配置")
        btn_save.setStyleSheet("background:#2196F3; color:white; padding:6px 12px;")
        btn_save.clicked.connect(self._save_llm_config)
        layout.addRow("", btn_save)

    # ========================================================
    # Tab：题型预设
    # ========================================================
    def _build_presets_tab(self, tab: QWidget):
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("已保存的题型预设："))
        
        hint = QLabel(
            "💡 命名建议：为让自动切换更准确，请使用题型全称，如 A1型题、B型题、X型题（多选题）、判断题"
        )
        hint.setStyleSheet("color:#888; font-size:11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 预设分类管理
        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("分类："))
        self.combo_preset_cat = QComboBox()
        self._refresh_preset_cat_combo()
        self.combo_preset_cat.currentTextChanged.connect(self._on_preset_cat_changed)
        cat_row.addWidget(self.combo_preset_cat)
        btn_add_cat = QPushButton("➕ 新建分类")
        btn_add_cat.clicked.connect(self._add_preset_category)
        cat_row.addWidget(btn_add_cat)
        btn_del_cat = QPushButton("🗑 删除分类")
        btn_del_cat.clicked.connect(self._delete_preset_category)
        cat_row.addWidget(btn_del_cat)
        cat_row.addStretch()
        layout.addLayout(cat_row)

        self.list_presets = QListWidget()
        self._refresh_presets_list()
        layout.addWidget(self.list_presets)

        h_btns = QHBoxLayout()
        btn_load = QPushButton("📂 加载选中预设")
        btn_load.clicked.connect(self._load_selected_preset)
        h_btns.addWidget(btn_load)
        btn_refresh = QPushButton("🔄 刷新列表")
        btn_refresh.clicked.connect(self._refresh_presets_list)
        h_btns.addWidget(btn_refresh)
        h_btns.addStretch()
        layout.addLayout(h_btns)

        # 预设详情
        layout.addWidget(QLabel("预设详情："))
        self.txt_preset_detail = QTextEdit()
        self.txt_preset_detail.setReadOnly(True)
        self.txt_preset_detail.setMaximumHeight(150)
        layout.addWidget(self.txt_preset_detail)

        self.list_presets.currentItemChanged.connect(self._on_preset_item_changed)

    # ========================================================
    # Tab：快捷键
    # ========================================================
    def _build_hotkey_tab(self, tab: QWidget):
        layout = QFormLayout(tab)
        layout.addRow(QLabel("设置全局快捷键（点击按钮后按下想要的键）："))

        self.btn_hk_start = QPushButton(self.config.get_hotkey("start") or "F9")
        self.btn_hk_start.clicked.connect(lambda: self._record_hotkey("start", self.btn_hk_start))
        layout.addRow("开始答题：", self.btn_hk_start)

        self.btn_hk_pause = QPushButton(self.config.get_hotkey("pause") or "F10")
        self.btn_hk_pause.clicked.connect(lambda: self._record_hotkey("pause", self.btn_hk_pause))
        layout.addRow("暂停/继续：", self.btn_hk_pause)

        self.btn_hk_switch = QPushButton(self.config.get_hotkey("switch_mode") or "F11")
        self.btn_hk_switch.clicked.connect(lambda: self._record_hotkey("switch_mode", self.btn_hk_switch))
        layout.addRow("切换模式：", self.btn_hk_switch)

        self.btn_hk_subjective = QPushButton(self.config.get_hotkey("manual_subjective") or "F12")
        self.btn_hk_subjective.clicked.connect(lambda: self._record_hotkey("manual_subjective", self.btn_hk_subjective))
        layout.addRow("手动标记主观题：", self.btn_hk_subjective)

        btn_apply = QPushButton("✅ 应用快捷键")
        btn_apply.setStyleSheet("background:#4CAF50; color:white; padding:6px 12px;")
        btn_apply.clicked.connect(self._apply_hotkeys)
        layout.addRow("", btn_apply)

    # ========================================================
    # Tab：运行日志
    # ========================================================
    def _build_log_tab(self, tab: QWidget):
        layout = QVBoxLayout(tab)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setFont(QFont("Consolas", 10))
        layout.addWidget(self.txt_log)
        btn_clear = QPushButton("清空日志")
        btn_clear.clicked.connect(lambda: self.txt_log.clear())
        layout.addWidget(btn_clear)

    # ========================================================
    # Tab：关于程序
    # ========================================================
    def _build_about_tab(self, tab: QWidget):
        layout = QVBoxLayout(tab)
        layout.setAlignment(Qt.AlignCenter)

        title = QLabel("水课快答 v1.3.3")
        title.setStyleSheet("font-size:24px; font-weight:bold; color:#2196F3;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        desc = QLabel("把大学生从烦人的水课中解脱出来，免费、高效地完成在线作业。")
        desc.setAlignment(Qt.AlignCenter)
        desc.setStyleSheet("color:#666; margin:10px;")
        layout.addWidget(desc)

        from PyQt5.QtWidgets import QLabel as QLabelWidget
        github_link = QLabelWidget(
            '<a href="https://github.com/GeorgeChou17?tab=repositories" '
            'style="color:#2196F3; text-decoration:none; font-size:14px;">'
            'GitHub：GeorgeChou17</a>'
        )
        github_link.setOpenExternalLinks(True)
        github_link.setAlignment(Qt.AlignCenter)
        layout.addWidget(github_link)

        layout.addStretch()

    # ========================================================
    # 配置加载/保存
    # ========================================================
    def _load_config_to_ui(self):
        # 模式
        mode = self.config.get_mode()
        idx = 0 if mode == "ocr" else 1
        self.combo_mode.setCurrentIndex(idx)

        # LLM
        cfg = self.config.get_llm_config()
        self.edit_base_url.setText(cfg.get("base_url", ""))
        self.edit_api_key.setText(cfg.get("api_key", ""))
        self.edit_model.setText(cfg.get("model_name", ""))
        self.chk_thinking.setChecked(cfg.get("thinking_enabled", False))
        self.chk_stream.setChecked(cfg.get("stream_enabled", False))
        self.spin_temp.setValue(cfg.get("temperature", 0.0))
        self.spin_max_tokens.setValue(cfg.get("max_tokens", 2048))
        self.spin_timeout.setValue(cfg.get("timeout", 300))
        # 答题速度
        self.spin_answer_interval.setValue(self.config.get_answer_interval())
        self.spin_retry_delay.setValue(self.config.get_retry_delay())
        # OCR 设置
        ocr_cfg = self.config.get_ocr_settings()
        self.chk_ocr_angle.setChecked(ocr_cfg.get("use_angle_cls", True))
        lang_map = {"ch": 0, "en": 1, "ch_en": 2}
        self.combo_ocr_lang.setCurrentIndex(lang_map.get(ocr_cfg.get("lang", "ch"), 0))
        self.spin_ocr_size.setValue(ocr_cfg.get("max_img_side", 960))
        device_map = {"cpu": 0, "auto": 1, "gpu": 2}
        self.combo_ocr_device.setCurrentIndex(device_map.get(ocr_cfg.get("device", "cpu"), 0))
        # 身份
        self.edit_identity.setPlainText(self.config.get_llm_identity())
        # 主观题关键词
        kws = self.config.get_subjective_keywords()
        self.edit_subjective_kw.setText(",".join(kws))
        # 延迟
        self.spin_delay.setValue(self.config.get_auto_delay())

        # 区域
        rect = self.config.get_screenshot_region()
        if rect:
            self.lbl_region.setText(f"已选择：{rect.x()},{rect.y()} {rect.width()}x{rect.height()}")
        # 选项
        self._refresh_options_label()
        # 下一题
        nxt = self.config.get_next_button_pos()
        if nxt:
            if isinstance(nxt, dict):
                self.lbl_next.setText(f"已标定：({nxt['x']},{nxt['y']})")
            else:
                self.lbl_next.setText(f"已标定：({nxt[0]},{nxt[1]})")
        # 按钮区域
        btn_region = self.config.get_button_region()
        if btn_region:
            self.lbl_btn_region.setText(
                f"已框选：({btn_region['x']},{btn_region['y']}) {btn_region['w']}x{btn_region['h']}"
            )
        type_region = self.config.get_type_region()
        if type_region:
            self.lbl_type_region.setText(
                f"已框选：({type_region['x']},{type_region['y']}) {type_region['w']}x{type_region['h']}"
            )
        offset = self.config.get_dynamic_offset()
        if offset:
            self.lbl_offset.setText(f"已校准：dx={offset['dx']}, dy={offset['dy']}")
        # 自动停止
        mode_map = {"none": 0, "ocr": 1, "count": 2}
        self.combo_stop_mode.setCurrentIndex(mode_map.get(self.config.get_stop_mode(), 0))
        self.spin_total_questions.setValue(self.config.get_total_questions())
        prog_region = self.config.get_progress_region()
        if prog_region:
            self.lbl_progress_region.setText(
                f"已框选：({prog_region['x']},{prog_region['y']}) {prog_region['w']}x{prog_region['h']}"
            )
        self._on_stop_mode_changed(self.combo_stop_mode.currentIndex())

    def _save_llm_config(self, show_message: bool = True):
        identity = self.edit_identity.toPlainText().strip()
        self.config.set_llm_config(
            base_url=self.edit_base_url.text().strip(),
            api_key=self.edit_api_key.text().strip(),
            model_name=self.edit_model.text().strip(),
            thinking_enabled=self.chk_thinking.isChecked(),
            stream_enabled=self.chk_stream.isChecked(),
            temperature=self.spin_temp.value(),
            max_tokens=self.spin_max_tokens.value(),
            timeout=self.spin_timeout.value(),
            identity=identity,
        )
        self.config.set_auto_delay(self.spin_delay.value())
        self.config.set_answer_interval(self.spin_answer_interval.value())
        self.config.set_retry_delay(self.spin_retry_delay.value())
        # 自动停止
        modes = ["none", "ocr", "count"]
        self.config.set_stop_mode(modes[self.combo_stop_mode.currentIndex()])
        self.config.set_total_questions(self.spin_total_questions.value())
        self.mouse_ctrl.set_click_delay(self.spin_delay.value())
        # 主观题关键词
        kws = [k.strip() for k in self.edit_subjective_kw.text().split(",") if k.strip()]
        self.config.set_subjective_keywords(kws)
        # 浮动窗口
        self.config.set_floating_window_enabled(self.chk_float_enabled.isChecked())
        self.config.set_floating_window_pinned(self.chk_float_pinned.isChecked())
        if self.floating_win:
            self.floating_win.setVisible(self.chk_float_enabled.isChecked())
            # 更新置顶状态
            if self.chk_float_pinned.isChecked():
                self.floating_win.setWindowFlags(
                    self.floating_win.windowFlags() | Qt.WindowStaysOnTopHint
                )
            else:
                self.floating_win.setWindowFlags(
                    self.floating_win.windowFlags() & ~Qt.WindowStaysOnTopHint
                )
            self.floating_win.show()

        if show_message:
            QMessageBox.information(self, "保存成功", "配置已保存！")
        logging.info("LLM 配置已保存")
        
        # OCR 性能设置
        lang_map = {0: "ch", 1: "en", 2: "ch_en"}
        device_map = {0: "cpu", 1: "auto", 2: "gpu"}
        self.config.set_ocr_settings(
            use_angle_cls=self.chk_ocr_angle.isChecked(),
            lang=lang_map.get(self.combo_ocr_lang.currentIndex(), "ch"),
            max_img_side=self.spin_ocr_size.value(),
            device=device_map.get(self.combo_ocr_device.currentIndex(), "cpu"),
        )

    # ========================================================
    # 快捷键管理
    # ========================================================
    def _setup_hotkeys(self):
        """注册全局快捷键"""
        try:
            import keyboard
            hotkeys = self.config.get_all_hotkeys()
            # 先清除旧快捷键
            try:
                keyboard.unhook_all()
            except Exception:
                pass
            self._hotkey_handles.clear()
            # 注册新快捷键
            registered = {}
            for action, key_str in hotkeys.items():
                if not key_str:
                    continue
                try:
                    cb_map = {
                        "start": self._hotkey_start,
                        "pause": self._hotkey_pause,
                        "switch_mode": self._hotkey_switch_mode,
                        "manual_subjective": self._hotkey_manual_subjective,
                    }
                    h = keyboard.add_hotkey(key_str, cb_map.get(action, lambda: None))
                    self._hotkey_handles.append(h)
                    registered[action] = key_str
                except Exception as e:
                    logging.warning(f"快捷键 {action}({key_str}) 注册失败：{e}")
            if registered:
                logging.info(f"快捷键已注册：{registered}")
            else:
                logging.warning("未注册任何快捷键（可能需要管理员权限）")
        except ImportError:
            logging.warning("keyboard 库未安装，快捷键功能不可用")
        except Exception as e:
            logging.warning(f"快捷键注册失败：{e}（请尝试以管理员身份运行）")

    def _record_hotkey(self, action: str, btn: QPushButton):
        """让用户按下快捷键并记录"""
        msg = QMessageBox(self)
        msg.setWindowTitle("录制快捷键")
        msg.setText(f"请按下想要设置的快捷键...\n（当前：{btn.text()}）\n按 ESC 取消")
        msg.setStandardButtons(QMessageBox.Cancel)
        msg.show()
        QApplication.processEvents()
        # 使用 keyboard 库临时监听
        try:
            import keyboard
            event = keyboard.read_event(suppress=True, timeout=5)
            if event and event.event_type == keyboard.KEY_DOWN:
                if event.name == "esc":
                    msg.close()
                    return
                hotkey_str = event.name
                # 检查修饰键
                if keyboard.is_pressed("ctrl"):
                    hotkey_str = "ctrl+" + hotkey_str
                if keyboard.is_pressed("alt"):
                    hotkey_str = "alt+" + hotkey_str
                if keyboard.is_pressed("shift"):
                    hotkey_str = "shift+" + hotkey_str
                btn.setText(hotkey_str)
                QMessageBox.information(self, "成功", f"快捷键已设置为：{hotkey_str}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"录制失败：{e}")
        msg.close()

    def _apply_hotkeys(self):
        """应用快捷键设置"""
        hotkeys = {
            "start": self.btn_hk_start.text(),
            "pause": self.btn_hk_pause.text(),
            "switch_mode": self.btn_hk_switch.text(),
            "manual_subjective": self.btn_hk_subjective.text(),
        }
        self.config.set_all_hotkeys(hotkeys)
        self._setup_hotkeys()
        QMessageBox.information(self, "成功", "快捷键已应用！")

    def _hotkey_start(self):
        QTimer.singleShot(0, self._start_answering)

    def _hotkey_pause(self):
        QTimer.singleShot(0, self._toggle_pause)

    def _hotkey_switch_mode(self):
        idx = self.combo_mode.currentIndex()
        self.combo_mode.setCurrentIndex(1 - idx)

    def _hotkey_manual_subjective(self):
        QTimer.singleShot(0, lambda: self._mark_subjective_manual())

    def _mark_subjective_manual(self):
        """手动标记当前题为不定项主观题"""
        self._handle_subjective_question(self._current_ocr_text, self._current_image)

    # ========================================================
    # 浮动答案窗口
    # ========================================================
    def _init_floating_window(self):
        """初始化浮动答案窗口（默认隐藏，答题时才显示）"""
        if not self.config.get_floating_window_enabled():
            return
        try:
            self.floating_win = FloatingAnswerWindow()
            if not self.config.get_floating_window_pinned():
                # 去掉置顶标志（默认是置顶的）
                flags = self.floating_win.windowFlags() & ~Qt.WindowStaysOnTopHint
                self.floating_win.setWindowFlags(flags)
            # 不在这里 show()，窗口在答题时由 clear_for_new_question() 显示
        except Exception as e:
            logging.error(f"浮动窗口初始化失败：{e}")

    # ========================================================
    # 模式切换
    # ========================================================
    def _on_mode_changed(self, text: str):
        mode = "ocr" if "OCR" in text else "multimodal"
        self.config.set_mode(mode)
        logging.info(f"切换模式：{mode}")

    # ========================================================
    # 截图区域选择（修复黑屏：RegionSelector 已支持桌面预览）
    # ========================================================
    def _select_region(self):
        self.hide()
        QApplication.processEvents()
        QTimer.singleShot(300, self._do_select_region)

    def _do_select_region(self):
        def on_region_selected(rect: QRect):
            self.config.set_screenshot_region(rect)
            self.config._save_category_config(self.config.get_current_category())
            self.lbl_region.setText(f"已选择：{rect.x()},{rect.y()} {rect.width()}x{rect.height()}")
            logging.info(f"截图区域已选择：{rect}")
            self.show()
        self._selector = RegionSelector()
        self._selector.region_selected.connect(on_region_selected)
        self._selector.showFullScreen()

    # ========================================================
    # 选项数量变化
    # ========================================================
    def _on_option_count_changed(self, count: int):
        """选项数量变化，更新 UI 提示"""
        names = self._get_option_names()
        actual = names if names else [chr(ord("A") + i) for i in range(count)]
        self.lbl_options.setText(f"需标定 {count} 个选项：{', '.join(actual)}")

    def _get_option_names(self) -> list:
        """从编辑框获取自定义选项名称，不足部分用 A/B/C... 补齐"""
        raw = self.edit_opt_names.text().strip()
        if not raw:
            return []
        names = [x.strip() for x in raw.split(",") if x.strip()]
        return names

    def _refresh_options_label(self):
        """刷新选项坐标显示"""
        opts = self.config.get_option_positions()
        if not opts:
            self.lbl_options.setText("未标定")
            return
        labels = [f"{o.get('name','?')}({o.get('x',0)},{o.get('y',0)})" for o in opts]
        self.lbl_options.setText(" | ".join(labels))

    # ========================================================
    # 标定选项位置（支持最多12个）
    # ========================================================
    def _calibrate_options(self):
        self.hide()
        QApplication.processEvents()
        QTimer.singleShot(300, self._do_calibrate_options)

    def _do_calibrate_options(self):
        count = self.spin_opt_count.value()
        names = self._get_option_names()
        # 补齐名称
        while len(names) < count:
            names.append(chr(ord("A") + len(names)))
        self._calib_positions = []
        self._calib_names = names[:count]
        self._calib_idx = 0
        self._calib_count = count
        self._start_next_option_calibration()

    def _start_next_option_calibration(self):
        if self._calib_idx >= self._calib_count:
            # 全部标定完成
            self.config.set_option_positions(self._calib_positions)
            self._refresh_options_label()
            logging.info(f"选项坐标标定完成：{self._calib_positions}")
            self.show()
            return
        tip = f"请点击第 {self._calib_idx+1} 个选项的位置（{self._calib_names[self._calib_idx]}）"
        self._calib_current_name = self._calib_names[self._calib_idx]
        calibrator = PositionCalibrator(max_clicks=1, tip_text=tip)
        calibrator.position_clicked.connect(self._on_one_option_calibrated)
        calibrator.finished.connect(self._on_option_calib_step_finished)
        calibrator.showFullScreen()
        self._calibrator = calibrator

    def _on_one_option_calibrated(self, pos: QPoint):
        self._calib_positions.append({
            "name": self._calib_current_name,
            "x": pos.x(),
            "y": pos.y(),
        })
        logging.info(f"选项 {self._calib_current_name} 坐标：({pos.x()}, {pos.y()})")

    def _on_option_calib_step_finished(self):
        self._calib_idx += 1
        QTimer.singleShot(200, self._start_next_option_calibration)

    # ========================================================
    # 标定下一题按钮
    # ========================================================
    def _calibrate_next(self):
        self.hide()
        QApplication.processEvents()
        QTimer.singleShot(300, self._do_calibrate_next)

    def _do_calibrate_next(self):
        def on_pos(p: QPoint):
            pos = (p.x(), p.y())
            self.config.set_next_button_pos(pos)
            self.lbl_next.setText(f"已标定：({pos[0]},{pos[1]})")
            logging.info(f"下一题按钮坐标：{pos}")
            self.show()
        calibrator = PositionCalibrator(max_clicks=1, tip_text="请点击「下一题」按钮")
        calibrator.position_clicked.connect(on_pos)
        calibrator.finished.connect(lambda: self.show())
        calibrator.showFullScreen()
        self._calibrator = calibrator

    # ========================================================
    # 预设管理
    # ========================================================
    def _refresh_presets_combo(self):
        prev = self.combo_presets.currentText() if self.combo_presets.count() > 0 else ""
        self.combo_presets.blockSignals(True)
        self.combo_presets.clear()
        self.combo_presets.addItem("（无预设）")
        cat = self.config.get_current_category()
        for name in self.config.get_presets(cat).keys():
            if name != "（无预设）":
                self.combo_presets.addItem(name)
        if prev and prev != "（无预设）":
            idx = self.combo_presets.findText(prev)
            if idx >= 0:
                self.combo_presets.setCurrentIndex(idx)
        self.combo_presets.blockSignals(False)

    def _refresh_presets_list(self):
        self.list_presets.clear()
        cat = self.config.get_current_category()
        for name in self.config.get_presets(cat).keys():
            if name != "（无预设）":
                self.list_presets.addItem(name)

    def _on_preset_selected(self, name: str):
        # 切走时自动保存当前坐标到上一个预设
        if hasattr(self, '_active_preset_name') and self._active_preset_name and self._active_preset_name not in (name, "（无预设）"):
            self.config.save_preset(self._active_preset_name,
                self.config.get_option_positions(),
                self.config.get_next_button_pos())
            logging.info(f"已自动保存预设：{self._active_preset_name}")
        self._active_preset_name = name if name != "（无预设）" else None
        
        if name == "（无预设）" or not name:
            logging.info("已切换至（无预设）")
            return
        # 加载目标预设
        presets = self.config.get_presets()
        if name in presets:
            self.config.load_preset(name)
            nb = self.config.get_next_button_pos()
            if nb:
                self.lbl_next.setText(f"已标定：({nb[0]},{nb[1]})")
            # 同步选项数量到 UI
            p = presets[name]
            opt_count = len(p.get('options', []))
            if opt_count > 0:
                self.spin_opt_count.blockSignals(True)
                self.spin_opt_count.setValue(opt_count)
                self.spin_opt_count.blockSignals(False)
                self._on_option_count_changed(opt_count)
            self._refresh_options_label()  # 放在最后，不被 _on_option_count_changed 覆盖
            logging.info(f"已切换预设：{name}（选项数={opt_count}）")
            # 同步动态定位开关到 UI
            self.chk_dynamic_click.blockSignals(True)
            self.chk_dynamic_click.setChecked(self.config.get_dynamic_click())
            self.chk_dynamic_click.blockSignals(False)
            self.chk_dynamic_fallback.blockSignals(True)
            self.chk_dynamic_fallback.setChecked(self.config.get_dynamic_fallback())
            self.chk_dynamic_fallback.blockSignals(False)
            self.spin_grid_rows.blockSignals(True)
            self.spin_grid_rows.setValue(max(1, self.config.get_option_grid_rows()))
            self.spin_grid_rows.blockSignals(False)
            self.spin_grid_cols.blockSignals(True)
            self.spin_grid_cols.setValue(max(1, self.config.get_option_grid_cols()))
            self.spin_grid_cols.blockSignals(False)
            self.spin_spacing_x.blockSignals(True)
            self.spin_spacing_x.setValue(max(0, self.config.get_grid_spacing_x()))
            self.spin_spacing_x.blockSignals(False)
            self.spin_spacing_y.blockSignals(True)
            self.spin_spacing_y.setValue(max(0, self.config.get_grid_spacing_y()))
            self.spin_spacing_y.blockSignals(False)
            # 同步更新预设详情
            detail = f"预设名：{name}\n"
            detail += f"选项数：{opt_count}\n"
            nb = p.get('next_button')
            detail += f"下一题坐标：{nb}\n"
            self.txt_preset_detail.setText(detail)

    def _on_dynamic_click_toggled(self, enabled: bool):
        self.config.set_dynamic_click(enabled)
        self.config._save_category_config(self.config.get_current_category())
        logging.info(f"动态选项定位：{'启用' if enabled else '禁用'}（已保存到当前分类）")

    def _on_dynamic_fallback_toggled(self, enabled: bool):
        self.config.set_dynamic_fallback(enabled)
        self.config._save_category_config(self.config.get_current_category())

    def _on_grid_changed(self):
        self.config.set_option_grid_rows(self.spin_grid_rows.value())
        self.config.set_option_grid_cols(self.spin_grid_cols.value())
        self.config.set_grid_spacing_x(self.spin_spacing_x.value())
        self.config.set_grid_spacing_y(self.spin_spacing_y.value())
        self.config._save_category_config(self.config.get_current_category())

    def _on_calibration_toggled(self, enabled: bool):
        self.spin_offset_x.setEnabled(enabled)
        self.spin_offset_y.setEnabled(enabled)
        if enabled:
            self.lbl_offset.setText("校准模式")
            self.lbl_offset.setStyleSheet("color:#f44;")
        else:
            self.lbl_offset.setText("未校准")
            self.lbl_offset.setStyleSheet("color:#888;")

    def _on_offset_changed(self):
        dx, dy = self.spin_offset_x.value(), self.spin_offset_y.value()
        self.config.set_dynamic_offset({"dx": dx, "dy": dy})
        self.config._save_category_config(self.config.get_current_category())
        self.lbl_offset.setText(f"已校准：dx={dx}, dy={dy}")
        self.lbl_offset.setStyleSheet("color:#4a4;")

    # ---- 预设分类管理（Tab内） ----
    def _refresh_preset_cat_combo(self):
        self.combo_preset_cat.blockSignals(True)
        self.combo_preset_cat.clear()
        cats = self.config.get_categories()
        if not cats:
            cats = ["默认"]
        self.combo_preset_cat.addItems(cats)
        current = self.config.get_current_category()
        if current in cats:
            self.combo_preset_cat.setCurrentText(current)
        self.combo_preset_cat.blockSignals(False)

    def _on_preset_cat_changed(self, name: str):
        if not name:
            return
        self.config.set_current_category(name)
        self._refresh_presets_list()
        self._refresh_category_combo()

    def _add_preset_category(self):
        name, ok = QInputDialog.getText(self, "新建分类", "分类名（如 人卫、超星、智慧树）：")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.config.get_categories():
            QMessageBox.warning(self, "重复", f"分类「{name}」已存在")
            return
        self.config.add_category(name)
        self.config.set_current_category(name)
        self._refresh_preset_cat_combo()
        self._refresh_presets_list()
        self._refresh_category_combo()

    def _delete_preset_category(self):
        name = self.combo_preset_cat.currentText()
        if not name or name == "默认":
            QMessageBox.warning(self, "提示", "不能删除「默认」分类")
            return
        presets = self.config.get_presets(name)
        if presets:
            r = QMessageBox.question(self, "确认", f"分类「{name}」下有 {len(presets)} 个预设，删除分类会同时删除所有预设。确认？")
            if r != QMessageBox.Yes:
                return
        self.config.delete_category(name)
        self.config.set_current_category("默认")
        self._refresh_preset_cat_combo()
        self._refresh_presets_list()
        self._refresh_category_combo()

    # ---- 预设分类 ----
    def _refresh_category_combo(self):
        self.combo_category.blockSignals(True)
        self.combo_category.clear()
        cats = self.config.get_categories()
        if not cats:
            cats = ["默认"]
        self.combo_category.addItems(cats)
        current = self.config.get_current_category()
        if current in cats:
            self.combo_category.setCurrentText(current)
        self.combo_category.blockSignals(False)

    def _on_category_changed(self, name: str):
        if not name:
            return
        # 保存当前分类的配置
        self.config._save_category_config(self.config.get_current_category())
        self.config.set_current_category(name)
        self._refresh_presets_combo()
        self._refresh_ui_from_category()
        logging.info(f"已切换到预设类别：{name}")
    
    def _refresh_ui_from_category(self):
        """更新UI以反映当前分类的配置"""
        rect = self.config.get_screenshot_region()
        if rect:
            self.lbl_region.setText(f"已选择：{rect.x()},{rect.y()} {rect.width()}x{rect.height()}")
        btn_region = self.config.get_button_region()
        if btn_region:
            self.lbl_btn_region.setText(f"已框选：({btn_region['x']},{btn_region['y']}) {btn_region['w']}x{btn_region['h']}")
        else:
            self.lbl_btn_region.setText("未框选")
        type_region = self.config.get_type_region()
        if type_region:
            self.lbl_type_region.setText(f"已框选：({type_region['x']},{type_region['y']}) {type_region['w']}x{type_region['h']}")
        else:
            self.lbl_type_region.setText("未框选")
        offset = self.config.get_dynamic_offset()
        if offset:
            self.lbl_offset.setText(f"已校准：dx={offset['dx']}, dy={offset['dy']}")
        else:
            self.lbl_offset.setText("未校准")
        # 同步动态定位开关
        self.chk_dynamic_click.blockSignals(True)
        self.chk_dynamic_click.setChecked(self.config.get_dynamic_click())
        self.chk_dynamic_click.blockSignals(False)
        self.chk_dynamic_fallback.blockSignals(True)
        self.chk_dynamic_fallback.setChecked(self.config.get_dynamic_fallback())
        self.chk_dynamic_fallback.blockSignals(False)
        self.spin_grid_rows.blockSignals(True)
        self.spin_grid_rows.setValue(max(1, self.config.get_option_grid_rows()))
        self.spin_grid_rows.blockSignals(False)
        self.spin_grid_cols.blockSignals(True)
        self.spin_grid_cols.setValue(max(1, self.config.get_option_grid_cols()))
        self.spin_grid_cols.blockSignals(False)
        self.spin_spacing_x.blockSignals(True)
        self.spin_spacing_x.setValue(max(0, self.config.get_grid_spacing_x()))
        self.spin_spacing_x.blockSignals(False)
        self.spin_spacing_y.blockSignals(True)
        self.spin_spacing_y.setValue(max(0, self.config.get_grid_spacing_y()))
        self.spin_spacing_y.blockSignals(False)
        # 同步校准偏移
        offset = self.config.get_dynamic_offset() or {}
        self.spin_offset_x.blockSignals(True)
        self.spin_offset_x.setValue(offset.get("dx", 0))
        self.spin_offset_x.blockSignals(False)
        self.spin_offset_y.blockSignals(True)
        self.spin_offset_y.setValue(offset.get("dy", 0))
        self.spin_offset_y.blockSignals(False)
        self.lbl_offset.setText(f"已校准：dx={offset.get('dx',0)}, dy={offset.get('dy',0)}" if offset else "未校准")

    # ---- 答题自动停止 ----
    def _on_stop_mode_changed(self, idx: int):
        modes = ["none", "ocr", "count"]
        self.config.set_stop_mode(modes[idx])
        self.btn_cal_progress.setVisible(idx == 1)
        self.lbl_progress_region.setVisible(idx == 1)
        self.spin_total_questions.setVisible(idx == 2)

    def _calibrate_progress_region(self):
        self.hide()
        QApplication.processEvents()
        QTimer.singleShot(300, self._do_calibrate_progress_region)

    def _do_calibrate_progress_region(self):
        from core.screenshot import RegionSelector
        def on_region(rect):
            region = {"x": rect.x(), "y": rect.y(), "w": rect.width(), "h": rect.height()}
            self.config.set_progress_region(region)
            self.lbl_progress_region.setText(
                f"已框选：({region['x']},{region['y']}) {region['w']}x{region['h']}"
            )
            self.show()
        self._selector = RegionSelector()
        self._selector.region_selected.connect(on_region)
        self._selector.showFullScreen()

    def _calibrate_button_region(self):
        """框选选项按钮所在的大致区域（用于空间过滤）"""
        self.hide()
        QApplication.processEvents()
        QTimer.singleShot(300, self._do_calibrate_button_region)

    def _do_calibrate_button_region(self):
        from core.screenshot import RegionSelector
        def on_region(rect: QRect):
            region = {"x": rect.x(), "y": rect.y(), "w": rect.width(), "h": rect.height()}
            self.config.set_button_region(region)
            self.config._save_category_config(self.config.get_current_category())
            self.lbl_btn_region.setText(f"已框选：({region['x']},{region['y']}) {region['w']}x{region['h']}")
            logging.info(f"选项按钮区域：{region}")
            self.show()
        self._selector = RegionSelector()
        self._selector.region_selected.connect(on_region)
        self._selector.showFullScreen()

    def _calibrate_type_region(self):
        """框选题型文字所在区域（如 A1型题 / X型题 显示位置）"""
        self.hide(); QApplication.processEvents()
        QTimer.singleShot(300, self._do_calibrate_type_region)

    def _do_calibrate_type_region(self):
        from core.screenshot import RegionSelector
        def on_region(rect: QRect):
            region = {"x": rect.x(), "y": rect.y(), "w": rect.width(), "h": rect.height()}
            self.config.set_type_region(region)
            self.config._save_category_config(self.config.get_current_category())
            self.lbl_type_region.setText(f"已框选：({region['x']},{region['y']}) {region['w']}x{region['h']}")
            logging.info(f"题型文字区域：{region}"); self.show()
        self._selector = RegionSelector()
        self._selector.region_selected.connect(on_region)
        self._selector.showFullScreen()

    def _ocr_type_region_from_lines(self, ocr_lines: list, scale_factor: float, offset_x: int, offset_y: int) -> str | None:
        """从主 OCR 文字块中提取题型区域内的文字（避免二次 OCR）"""
        region = self.config.get_type_region()
        if not region or not ocr_lines:
            return None
        try:
            rx = region["x"] - offset_x
            ry = region["y"] - offset_y
            rw, rh = region["w"], region["h"]
            texts = []
            for line in ocr_lines:
                box = line.get("box", [])
                if not box or len(box) < 4:
                    continue
                xs = [p[0] * scale_factor for p in box if len(p) >= 2]
                ys = [p[1] * scale_factor for p in box if len(p) >= 2]
                if not xs or not ys:
                    continue
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                if rx <= cx <= rx + rw and ry <= cy <= ry + rh:
                    texts.append(line.get("text", ""))
            if texts:
                text = self._fix_ocr_type_errors(" ".join(texts))
                logging.info(f"题型区域（从OCR提取）：{text}")
                return text
        except Exception as e:
            logging.warning(f"题型区域提取失败：{e}")
        return None

    def _check_ocr_stop_from_lines(self, ocr_lines: list, scale_factor: float, offset_x: int, offset_y: int) -> bool:
        """从主 OCR 文字块中提取题号区域文字并检查是否最后一题"""
        if getattr(self, '_completion_dialog_shown', False):
            return False  # 用户已选择继续，不再重复弹窗
        region = self.config.get_progress_region()
        if not region or not ocr_lines:
            return False
        try:
            rx = region["x"] - offset_x
            ry = region["y"] - offset_y
            rw, rh = region["w"], region["h"]
            texts = []
            for line in ocr_lines:
                box = line.get("box", [])
                if not box or len(box) < 4:
                    continue
                xs = [p[0] * scale_factor for p in box if len(p) >= 2]
                ys = [p[1] * scale_factor for p in box if len(p) >= 2]
                if not xs or not ys:
                    continue
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                if rx <= cx <= rx + rw and ry <= cy <= ry + rh:
                    texts.append(line.get("text", ""))
            if texts:
                progress_text = " ".join(texts)
                current, total = self._parse_progress(progress_text)
                if current and total and current >= total:
                    self._question_counter = total
                    self.lbl_stop_progress.setText(f"已答：{current} / {total}")
                    return True
                if current and total:
                    self.lbl_stop_progress.setText(f"进度：{current} / {total}")
        except Exception as e:
            logging.warning(f"题号识别失败：{e}")
        return False
        region = self.config.get_type_region()
        if not region or not self._current_image:
            return None
        try:
            from PIL import Image
            r = region
            cropped = self._current_image.crop((r["x"], r["y"], r["x"]+r["w"], r["y"]+r["h"]))
            from core.ocr_module import recognize_image
            result = recognize_image(img=cropped, use_angle_cls=False, max_img_side=0)
            if result["success"] and result["text"].strip():
                text = result["text"].strip().replace("\n", " ")
                text = self._fix_ocr_type_errors(text)
                logging.info(f"题型区域 OCR：{text}")
                return text
        except Exception as e:
            logging.warning(f"题型区域 OCR 失败：{e}")
        return None

    def _calibrate_offset(self):
        """校准：对比混合定位(固定X+OCR_Y)与手动按钮点击"""
        count = self.spin_opt_count.value()
        if count < 1:
            QMessageBox.warning(self, "提示", "请先设置选项数量")
            return
        if not hasattr(self, '_ocr_content_y') or not self._ocr_content_y:
            QMessageBox.warning(self, "提示", "请先跑一题让OCR识别选项位置")
            return
        r = QMessageBox.question(self, "坐标校准",
            f"将对比混合定位（OCR_Y={list(self._ocr_content_y.values())[:3]}...）与手动点击",
            QMessageBox.Ok | QMessageBox.Cancel)
        if r != QMessageBox.Ok:
            return
        names = [chr(ord("A") + i) for i in range(count)]
        self._calib_offset_clicks = []
        self._calibrator = PositionCalibrator(max_clicks=count, tip_text=f"依次点击: {', '.join(names)}")
        self._calibrator.position_clicked.connect(lambda pos: self._calib_offset_clicks.append((pos.x(),pos.y())))
        self._calibrator.finished.connect(self._on_offset_calib_finished)
        self.hide(); QApplication.processEvents()
        self._calibrator.showFullScreen()

    def _on_offset_calib_finished(self):
        self.show()
        if len(self._calib_offset_clicks) < self.spin_opt_count.value():
            return
        dx = dy = cnt = 0
        names = [chr(ord("A") + i) for i in range(self.spin_opt_count.value())]
        for i, (mx, my) in enumerate(self._calib_offset_clicks):
            name = names[i]
            if hasattr(self, '_ocr_content_y') and name in self._ocr_content_y:
                # 混合定位：固定X + OCR_Y
                fixed = self.config.get_option_positions()
                fx = int(fixed[i].get("x", 0)) if i < len(fixed) else 0
                fy = int(self._ocr_content_y[name])
                dx += mx - fx; dy += my - fy; cnt += 1
                logging.debug(f"校准[{name}]: 点击=({mx},{my}) 混合=({fx},{fy}) 差=({mx-fx},{my-fy})")
        if cnt > 0:
            offset = {"dx": int(dx/cnt), "dy": int(dy/cnt)}
            self.config.set_dynamic_offset(offset)
            self.config._save_category_config(self.config.get_current_category())
            self.lbl_offset.setText(f"已校准：dx={offset['dx']}, dy={offset['dy']}")
            logging.info(f"坐标偏移校准（混合模式）：{offset}")

    @staticmethod
    def _fix_ocr_type_errors(text: str) -> str:
        """修复 OCR 对题型文字的常见识别错误"""
        import re
        t = text.strip()
        # 大小写统一
        t = t.upper()
        # 常见 OCR 错字修正（罗马数字/字母混淆）
        t = re.sub(r'A[IⅠLl1一]', 'A1', t)  # AI/AⅠ/Al/A一 → A1
        t = re.sub(r'B[IⅠLl1一]', 'B1', t)  # BI → B1
        t = re.sub(r'[×✕xX]', 'X', t)        # × → X
        t = re.sub(r'[Oo0]', '0', t)          # O → 0 (用于题号)
        # 中文错字
        t = re.sub(r'[夕タ多]', '多', t)       # 夕 → 多
        t = re.sub(r'逸', '选', t)             # 逸 → 选
        t = re.sub(r'单[题逸]', '单选', t)     # 单逸 → 单选
        t = re.sub(r'判[斯断]', '判断', t)     # 判斯 → 判断
        t = re.sub(r'填[空控]', '填空', t)     # 填空 → 填空
        return t

    def _on_preset_item_changed(self, current, previous):
        if not current:
            return
        name = current.text()
        presets = self.config.get_presets()
        if name in presets:
            p = presets[name]
            detail = f"预设名：{name}\n"
            detail += f"选项数：{len(p.get('options', []))}\n"
            for opt in p.get("options", []):
                detail += f"  {opt.get('name','?')}：({opt.get('x',0)}, {opt.get('y',0)})\n"
            nb = p.get("next_button")
            detail += f"下一题：{nb}\n"
            self.txt_preset_detail.setText(detail)

    def _save_current_preset(self):
        current = self.combo_presets.currentText()
        if current and current != "（无预设）":
            # 已有预设选中 → 询问是否更新
            r = QMessageBox.question(self, "更新预设",
                f"预设「{current}」已存在，是否覆盖更新？",
                QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
            name = current
        else:
            name, ok = QInputDialog.getText(self, "保存预设", "请输入预设名称：")
            if not ok or not name.strip():
                return
            name = name.strip()
        # 快照当前所有配置
        options = list(self.config.get_option_positions())
        next_pos = self.config.get_next_button_pos()
        button_region = self.config.get_button_region()
        type_region = self.config.get_type_region()
        opt_count = self.spin_opt_count.value()
        self.config.save_preset(name, options, next_pos, button_region, type_region)
        self._refresh_presets_combo()
        self._refresh_presets_list()
        # 确保选项数量不变
        self.spin_opt_count.setValue(opt_count)
        QMessageBox.information(self, "成功", f"预设「{name}」已保存！")

    def _load_selected_preset(self):
        item = self.list_presets.currentItem()
        if not item:
            QMessageBox.warning(self, "提示", "请先选择预设")
            return
        name = item.text()
        if self.config.load_preset(name):
            self._refresh_options_label()
            nb = self.config.get_next_button_pos()
            if nb:
                self.lbl_next.setText(f"已标定：({nb[0]},{nb[1]})")
            # 同步选项数量到 UI
            opts = self.config.get_option_positions()
            opt_count = len(opts)
            if opt_count > 0:
                self.spin_opt_count.blockSignals(True)
                self.spin_opt_count.setValue(opt_count)
                self.spin_opt_count.blockSignals(False)
                self._on_option_count_changed(opt_count)
            logging.info(f"已加载预设：{name}（选项数={opt_count}）")
            QMessageBox.information(self, "成功", f"预设「{name}」已加载！")
        else:
            QMessageBox.warning(self, "失败", f"加载预设失败：{name}")

    def _delete_preset(self):
        # 优先从 combobox 获取当前选中的预设名（主Tab的删除按钮）
        name = self.combo_presets.currentText()
        if not name or name == "（无预设）":
            # 回退：尝试从预设Tab的列表获取
            item = self.list_presets.currentItem()
            if item:
                name = item.text()
            else:
                QMessageBox.warning(self, "提示", "请先在「题型预设」下拉框或列表中选中一个预设！")
                return
        r = QMessageBox.question(self, "确认", f"确定删除预设「{name}」？",
                                   QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            self.config.delete_preset(name)
            self._refresh_presets_combo()
            self._refresh_presets_list()
            self.txt_preset_detail.clear()
            self.combo_presets.setCurrentIndex(0)  # 回到"无预设"
            logging.info(f"已删除预设：{name}")

    # ========================================================
    # 主观题检测
    # ========================================================
    def _check_subjective(self, text: str) -> bool:
        """OCR 文本中是否包含主观题关键词"""
        if not text:
            return False
        keywords = self.config.get_subjective_keywords()
        for kw in keywords:
            if kw in text:
                return True
        return False

    def _handle_subjective_question(self, ocr_text: str, image=None):
        """处理主观题：调用 LLM 获取答案，显示在浮动窗口"""
        logging.info("检测到主观题，正在获取答案...")
        if self.floating_win:
            self.floating_win.set_subjective_mode(True)
            self.floating_win.set_status("正在获取主观题答案...")
            self.floating_win.show()
            self.floating_win.raise_()
        # 异步调用 LLM
        client = self._build_llm_client()
        messages = client.build_ocr_messages(ocr_text, is_subjective=True)
        worker = LLMWorker(client, messages)
        worker.token_received.connect(
            lambda t: self.floating_win.append_thinking(t) if self.floating_win else None
        )
        worker.thinking_received.connect(
            lambda t: self.floating_win.append_thinking(t) if self.floating_win else None
        )
        worker.finished.connect(lambda r: self._on_subjective_finished(r))
        worker.error.connect(lambda e: logging.error(f"主观题答案获取失败：{e}"))
        worker.start()
        self._subjective_worker = worker

    def _on_subjective_finished(self, result: dict):
        answer = result.get("answer", "")
        analysis = result.get("analysis", "")
        full = f"分析：{analysis}\n\n答案要点：\n{answer}"
        if self.floating_win:
            self.floating_win.set_answer(full)
            self.floating_win.set_status("主观题答案已更新（可复制）")
        logging.info(f"主观题答案已显示：{answer[:100]}")

    # ========================================================
    # 测试 LLM 连接
    # ========================================================
    def _test_llm_connection(self):
        try:
            client = self._build_llm_client()
            from core.llm_api import _DEFAULT_SYSTEM_PROMPT
            messages = [
                {"role": "system", "content": "你是一个有用的助手。"},
                {"role": "user", "content": "请回复'连接成功'三个字。"},
            ]
            import httpx
            url = f"{client.base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {client.api_key}",
                       "Content-Type": "application/json"}
            payload = {
                "model": client.model_name,
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": 32,
                "stream": False,
            }
            resp = httpx.post(url, headers=headers, json=payload, timeout=15.0)
            if resp.status_code == 200:
                QMessageBox.information(self, "连接成功", "LLM API 连接正常！")
                logging.info("LLM API 连接测试成功")
            else:
                QMessageBox.warning(self, "连接失败", f"状态码 {resp.status_code}：{resp.text[:200]}")
        except Exception as e:
            QMessageBox.critical(self, "连接失败", str(e))
            logging.error(f"LLM 连接测试失败：{e}")

    def _build_llm_client(self) -> LLMClient:
        return LLMClient(
            base_url=self.edit_base_url.text().strip(),
            api_key=self.edit_api_key.text().strip(),
            model_name=self.edit_model.text().strip(),
            thinking_enabled=self.chk_thinking.isChecked(),
            stream_enabled=self.chk_stream.isChecked(),
            temperature=self.spin_temp.value(),
            max_tokens=self.spin_max_tokens.value(),
            identity=self.edit_identity.toPlainText().strip(),
            timeout=self.spin_timeout.value(),
        )

    # ========================================================
    # 答题主流程
    # ========================================================
    def _start_answering(self):
        if self._running:
            return
        if not self._validate_before_start():
            return
        self._running = True
        self._paused = False
        self._question_counter = 0
        self._last_ocr_texts = []
        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self.progress.setVisible(True)
        self.lbl_status.setText("正在运行...")
        self.lbl_status.setStyleSheet("color:#4CAF50; font-size:12px;")
        logging.info("=== 开始自动答题 ===")
        # 将浮动窗口移到主窗口所在屏幕的右上角
        if self.floating_win and self.config.get_floating_window_enabled():
            self.floating_win.reposition_to_widget(self)
        self._step_screenshot()

    def _toggle_pause(self):
        if not self._running:
            return
        self._paused = not self._paused
        if self._paused:
            self.btn_pause.setText("▶ 继续")
            self.lbl_status.setText("已暂停")
            logging.info("答题已暂停")
        else:
            self.btn_pause.setText("⏸ 暂停")
            self.lbl_status.setText("正在运行...")
            logging.info("答题继续")

    def _stop_answering(self):
        self._running = False
        self._paused = False
        self.lbl_status.setText("已停止")
        self.lbl_status.setStyleSheet("color:#f44336; font-size:12px;")
        logging.info("用户手动停止")
        self._finish_flow()

    def _validate_before_start(self) -> bool:
        if self.config.get_screenshot_region() is None:
            QMessageBox.warning(self, "配置不完整", "请先框选截图区域！")
            return False
        if not self.config.get_option_positions():
            QMessageBox.warning(self, "配置不完整", "请先标定选项位置！")
            return False
        cfg = self.config.get_llm_config()
        if not cfg.get("api_key"):
            QMessageBox.warning(self, "配置不完整", "请先填写 API Key！")
            return False
        return True

    def _finish_flow(self):
        self._running = False
        self._paused = False
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸ 暂停")
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)
        self.lbl_status.setText("就绪")
        self.lbl_status.setStyleSheet("color:#888; font-size:12px;")
        
        # 清理 LLM 工作线程
        if hasattr(self, '_llm_worker') and self._llm_worker is not None:
            try:
                if self._llm_worker.isRunning():
                    self._llm_worker.terminate()
                    self._llm_worker.wait(1000)  # 等待最多1秒
            except Exception:
                pass
            self._llm_worker = None
        
        # 清理截图器
        if hasattr(self, 'screenshot_taker'):
            try:
                self.screenshot_taker.close()
            except Exception:
                pass
        
        # 清理 OCR 缓存（释放内存）
        try:
            from core.ocr_module import clear_ocr_cache
            clear_ocr_cache()
        except Exception:
            pass
        
        # 强制垃圾回收
        import gc
        gc.collect()

    # ========================================================
    # 答题步骤
    # ========================================================
    def _step_screenshot(self):
        if not self._running:
            self._finish_flow()
            return
        while self._paused and self._running:
            QApplication.processEvents()
            time.sleep(0.05)
        logging.info("【步骤1】截图...")
        rect = self.config.get_screenshot_region()
        self.screenshot_taker = ScreenshotTaker()
        img = self.screenshot_taker.grab_region(rect)
        self._current_image = img
        self._current_image_base64 = self.screenshot_taker.to_base64(img)
        mode = self.config.get_mode()
        if mode == "ocr":
            self._step_ocr(img)
        else:
            self._step_llm_multimodal()

    def _step_ocr(self, img):
        logging.info("【步骤2】OCR 识别中...")
        self.lbl_status.setText("OCR 识别中...")
        ocr_cfg = self.config.get_ocr_settings()
        self._ocr_worker = OCRWorker(
            img=img,
            use_angle_cls=ocr_cfg.get("use_angle_cls", True),
            lang=ocr_cfg.get("lang", "ch"),
            max_img_side=ocr_cfg.get("max_img_side", 960),
            device=ocr_cfg.get("device", "cpu"),
        )
        self._ocr_worker.finished.connect(self._on_ocr_finished)
        self._ocr_worker.error.connect(self._on_ocr_error)
        self._ocr_worker.start()

    def _on_ocr_finished(self, raw_text: str, parsed: dict, ocr_lines: list = None, scale_factor: float = 1.0):
        self._current_ocr_text = raw_text
        qtype = parsed.get("question_type", "未知")
        info = f"题型：{qtype}\n题干：{parsed.get('stem','')[:100]}...\n选项数：{len(parsed.get('options',[]))}"
        self.txt_question_info.setText(info)
        logging.info(f"OCR 完成：{qtype}")
        
        rect = self.config.get_screenshot_region()
        offset_x = rect.x() if rect else 0
        offset_y = rect.y() if rect else 0
        
        # OCR 题号识别（从主 OCR 结果中提取，避免二次 OCR）
        if self.config.get_stop_mode() == "ocr":
            if self._check_ocr_stop_from_lines(ocr_lines, scale_factor, offset_x, offset_y):
                self._show_completion_dialog()
                return
        
        # 计数模式去重
        if self.config.get_stop_mode() == "count" and self._is_duplicate_question(raw_text):
            logging.info("检测到重复题目（LLM 重扫），跳过计数")
            QTimer.singleShot(1000, self._step_screenshot)
            return
        
        # 动态选项定位：OCR 给出 A 的 Y 偏移，所有选项统一平移
        self._dynamic_options = {}
        if self.config.get_dynamic_click() and ocr_lines:
            opt_names = [chr(ord("A") + i) for i in range(self.spin_opt_count.value())]
            
            # 步骤1：构建 OCR 文字块
            ocr_blocks = []
            for line in ocr_lines:
                text = line.get("text", "").strip()
                box = line.get("box", [])
                if not text or not box or len(box) < 4:
                    continue
                xs = [p[0] * scale_factor for p in box if len(p) >= 2]
                ys = [p[1] * scale_factor for p in box if len(p) >= 2]
                if not xs or not ys:
                    continue
                ocr_blocks.append({"text": text, "cx": sum(xs)/len(xs), "cy": sum(ys)/len(ys)})
            logging.debug(f"OCR文字块({len(ocr_blocks)}个): " + " | ".join(
                f"{b['text'][:15]}({b['cx']:.0f},{b['cy']:.0f})" for b in sorted(ocr_blocks, key=lambda b: b['cy'])))
            
            # 步骤2：收集选项内容候选（按钮下方、非单字母、非题干）
            fixed = {o["name"]: o for o in self.config.get_option_positions()}
            fixed_y_min = min(f.get("y", 99999) for f in fixed.values()) if fixed else 99999
            candidates = []
            for b in ocr_blocks:
                if b["cy"] < fixed_y_min - 130 or len(b["text"]) < 2:
                    continue
                text = b["text"]
                if len(text) == 1 and text.isascii():
                    continue
                # 过滤题干干扰行和评分标记（如 "(1分）"、"分）"）
                if "分）" in text or "分)" in text:
                    continue
                if text[0].isdigit():
                    if any(kw in text for kw in ["下面","以下","正确","错误","哪一","分）","不属于","属于","主要","常见","关于","下列","不宜","适宜"]):
                        continue
                    if len(text) >= 8:
                        continue
                candidates.append((b["cx"], b["cy"]))
            candidates.sort(key=lambda b: b[1])  # 按Y排序
            
            # 步骤3：网格定位 — 当间距设置后，用网格精确计算
            rect = self.config.get_screenshot_region()
            offset_y = rect.y() if rect else 0
            cal = self.config.get_dynamic_offset() or {"dx": 0, "dy": 0}
            screen_positions = {}
            
            spacing_x = self.config.get_grid_spacing_x()
            spacing_y = self.config.get_grid_spacing_y()
            grid_rows = max(1, self.config.get_option_grid_rows())
            grid_cols = max(1, self.config.get_option_grid_cols())
            use_grid = spacing_y > 0 and grid_rows * grid_cols >= len(opt_names)
            
            if candidates and "A" in fixed:
                a_ocr_screen_y = int(candidates[0][1] + offset_y)  # OCR内容屏幕Y（不含预估偏移，由校准dy补偿）
                shift = a_ocr_screen_y - fixed["A"].get("y", 0)
                
                if use_grid:
                    # 网格模式：用OCR内容Y检测滚动偏移，再用固定坐标+间距计算
                    a_x = int(fixed["A"].get("x", 0))
                    anchor_y = int(fixed["A"].get("y", 0)) + shift  # 固定Y + 滚动偏移
                    for i, name in enumerate(opt_names):
                        if name in fixed:
                            row, col = i % grid_rows, i // grid_rows
                            screen_positions[name] = (
                                a_x + col * spacing_x + cal.get("dx", 0),
                                anchor_y + row * spacing_y + cal.get("dy", 0)
                            )
                else:
                    # 无间距：A锚点 + 固定坐标偏移
                    for name in opt_names:
                        if name in fixed:
                            screen_positions[name] = (
                                int(fixed[name].get("x", 0)) + cal.get("dx", 0),
                                int(fixed[name].get("y", 0)) + shift + cal.get("dy", 0)
                            )
            # 兜底：直接用固定坐标
            if not screen_positions:
                for name in opt_names:
                    if name in fixed:
                        screen_positions[name] = (int(fixed[name].get("x",0)), int(fixed[name].get("y",0)))
            
            self._dynamic_options = screen_positions
            found = sum(1 for v in screen_positions.values() if v is not None)
            if use_grid:
                logging.info(f"网格定位：{grid_rows}x{grid_cols} 间距({spacing_x}x{spacing_y}), {found}/{len(opt_names)} 个选项")
            else:
                logging.info(f"动态定位：找到 {found}/{len(opt_names)} 个选项坐标 (A锚点偏移={shift if candidates and 'A' in fixed else 'N/A'})")
        
        # 主观题检测
        if self._check_subjective(raw_text):
            logging.info("OCR 检测到主观题关键词！")
            self._handle_subjective_question(raw_text, self._current_image)
            QTimer.singleShot(2000, lambda: self._step_click_next_only())
            return
        # 自动切换预设（从主 OCR 结果中提取题型文字）
        if self.config.get_auto_switch_preset():
            type_text = self._ocr_type_region_from_lines(ocr_lines, scale_factor, offset_x, offset_y)
            if type_text:
                self._auto_switch_preset_by_type(type_text)
            else:
                self._auto_switch_preset_by_type(qtype)
        self._step_llm_ocr(raw_text)

    def _on_ocr_error(self, msg: str):
        logging.error(f"OCR 失败：{msg}")
        QMessageBox.warning(self, "OCR 失败", msg)
        self._finish_flow()

    def _auto_switch_preset_by_type(self, qtype: str):
        """根据题型自动切换预设（仅在当前类别内搜索）"""
        category = self.config.get_current_category()
        presets = self.config.get_presets(category)
        if not presets or not qtype:
            return
        
        # 规范化题型文本：去掉"型"、"题"、"题型"等后缀，保留核心标识
        def _normalize(s: str) -> str:
            s = self._fix_ocr_type_errors(s)
            import re
            s = s.strip().lower()
            s = re.sub(r'[型题]+$', '', s)
            s = re.sub(r'题型$', '', s)
            s = s.strip()
            return s
        
        norm_qtype = _normalize(qtype)
        logger = logging.getLogger(__name__)
        
        # 构建预设名称的规范化映射
        preset_norm = {_normalize(name): name for name in presets.keys()}
        
        best_match = None
        
        # 策略1：精确匹配规范化后的名称
        if norm_qtype in preset_norm:
            best_match = preset_norm[norm_qtype]
        else:
            # 策略2：qtype 包含预设名（如"a1型题"匹配"a1"）
            for norm_name, orig_name in preset_norm.items():
                if norm_name and (norm_name in norm_qtype or norm_qtype in norm_name):
                    best_match = orig_name
                    break
        
        # 策略3：对于无法精确匹配的，按大类别匹配
        if not best_match:
            # 多选题大类
            if any(k in norm_qtype for k in ('多选', 'x', 'x型')):
                multi_keys = [k for k in preset_norm if any(x in k for x in ('多选', 'x', 'x型'))]
                if multi_keys:
                    best_match = preset_norm[multi_keys[0]]
            # 单选题大类（A1-A4, B1-B2）
            elif any(k in norm_qtype for k in ('单选', 'a1', 'a2', 'a3', 'a4', 'b1', 'b2', 'a型', 'b型')):
                single_keys = [k for k in preset_norm if any(x in k for x in ('单选', 'a1', 'a2', 'a3', 'a4', 'b1', 'b2', 'a型', 'b型'))]
                if single_keys:
                    best_match = preset_norm[single_keys[0]]
        
        if best_match:
            logging.info(f"自动切换预设：{best_match}（题型={qtype}, 规范化={norm_qtype}）")
            self.config.load_preset(best_match, keep_positions=True)
            self._active_preset_name = best_match
            # 同步 UI
            self.combo_presets.blockSignals(True)
            idx = self.combo_presets.findText(best_match)
            if idx >= 0:
                self.combo_presets.setCurrentIndex(idx)
            self.combo_presets.blockSignals(False)
            presets = self.config.get_presets(category)
            p = presets.get(best_match, {})
            opt_count = len(p.get("options", []))
            if opt_count > 0:
                self.spin_opt_count.blockSignals(True)
                self.spin_opt_count.setValue(opt_count)
                self.spin_opt_count.blockSignals(False)
            self._refresh_options_label()
            nb = self.config.get_next_button_pos()
            if nb:
                self.lbl_next.setText(f"已标定：({nb[0]},{nb[1]})")

    def _step_llm_ocr(self, ocr_text: str):
        logging.info("【步骤3】调用 LLM（OCR 模式）...")
        self.lbl_status.setText("LLM 思考中...")
        
        # 答题速度限制：等待间隔后发送请求
        interval = self.config.get_answer_interval()
        if interval > 0 and self._running:
            logging.info(f"等待答题间隔 {interval} 秒...")
            self.lbl_status.setText(f"等待 {interval} 秒后请求 LLM...")
            QTimer.singleShot(interval * 1000, lambda: self._do_step_llm_ocr(ocr_text))
            return
        self._do_step_llm_ocr(ocr_text)
    
    def _do_step_llm_ocr(self, ocr_text: str):
        if not self._running:
            return
        is_sub = self._check_subjective(ocr_text)
        client = self._build_llm_client()
        messages = client.build_ocr_messages(ocr_text, is_subjective=is_sub)
        self._llm_worker = LLMWorker(client, messages)
        if self.floating_win and self.config.get_floating_window_enabled():
            self.floating_win.clear_for_new_question()
            self._llm_worker.token_received.connect(
                lambda t: self.floating_win.append_thinking(t)
            )
            self._llm_worker.thinking_received.connect(
                lambda t: self.floating_win.append_thinking("[思考] " + t)
            )
        self._llm_worker.finished.connect(self._on_llm_finished)
        self._llm_worker.error.connect(self._on_llm_error)
        self._llm_worker.start()

    def _step_llm_multimodal(self):
        logging.info("【步骤3】调用 LLM（多模态模式）...")
        self.lbl_status.setText("LLM 识别题目中...")
        
        interval = self.config.get_answer_interval()
        if interval > 0 and self._running:
            logging.info(f"等待答题间隔 {interval} 秒...")
            self.lbl_status.setText(f"等待 {interval} 秒后请求 LLM...")
            QTimer.singleShot(interval * 1000, self._do_step_llm_multimodal)
            return
        self._do_step_llm_multimodal()
    
    def _do_step_llm_multimodal(self):
        if not self._running:
            return
        client = self._build_llm_client()
        messages = client.build_multimodal_messages(self._current_image_base64, is_subjective=False)
        self._llm_worker = LLMWorker(client, messages)
        if self.floating_win and self.config.get_floating_window_enabled():
            self.floating_win.clear_for_new_question()
            self._llm_worker.token_received.connect(
                lambda t: self.floating_win.append_thinking(t)
            )
        self._llm_worker.finished.connect(self._on_llm_finished)
        self._llm_worker.error.connect(self._on_llm_error)
        self._llm_worker.start()

    def _on_llm_finished(self, result: dict):
        try:
            if not self._running:  # 用户已停止，忽略回传
                return
            answer = result.get("answer", "")
            qtype = result.get("question_type", "未知")
            analysis = result.get("analysis", "")
            confidence = result.get("confidence", 0.0)
            thinking = result.get("thinking", "")

            info = f"题型：{qtype}\n分析：{analysis}\n答案：{answer}\n置信度：{confidence:.0%}"
            self.txt_question_info.setText(info)
            logging.info(f"LLM 返回：答案={answer}，置信度={confidence:.0%}")

            if self.floating_win and self.config.get_floating_window_enabled():
                self.floating_win.set_subjective_mode(False)
                self.floating_win.set_answer(f"答案：{answer}\n\n分析：{analysis}")
                if thinking:
                    self.floating_win.append_thinking("[思考过程] " + thinking)
                self.floating_win.show()
                self.floating_win.raise_()

            self._current_answer = answer
            self._step_click_answer(answer)
        except Exception as e:
            logging.error(f"_on_llm_finished 异常: {e}")
            self._on_llm_error(str(e))

    def _on_llm_error(self, msg: str):
        logging.error(f"LLM 调用失败：{msg}")
        if not self._running:
            QMessageBox.warning(self, "LLM 失败", msg)
            self._finish_flow()
            return
        
        is_429 = "429" in msg or "限流" in msg or "Too Many Requests" in msg
        is_empty_or_timeout = "空答案" in msg or "空响应" in msg or "超时" in msg
        retry_delay = self.config.get_retry_delay()
        
        # 空答案/超时：自动重试但限制次数
        if is_empty_or_timeout:
            if not hasattr(self, '_empty_answer_retries'):
                self._empty_answer_retries = 0
            self._empty_answer_retries += 1
            
            if self._empty_answer_retries > 3:
                self._empty_answer_retries = 0
                QMessageBox.warning(
                    self, "LLM 出错",
                    f"LLM 连续返回空答案/超时（已重试 3 次）。\n\n"
                    f"可能原因：\n"
                    f"1. API 配额已耗尽\n"
                    f"2. 模型暂时不可用\n\n"
                    f"请稍后重试或更换 API 提供商。"
                )
                self._finish_flow()
                return
            
            QTimer.singleShot(retry_delay * 1000, lambda: self._retry_current_question())
            return
        
        # 重置空答案计数器
        if hasattr(self, '_empty_answer_retries'):
            self._empty_answer_retries = 0
        
        if is_429:
            dialog = CountdownDialog(
                self, "API 限流（429）",
                f"由于 API 的多并发限制，导致模型拒绝工作。\n\n"
                f"程序将在 {retry_delay} 秒后自动重试。\n"
                f"您也可以：\n"
                f"• 点击「立即重试」立即重试\n"
                f"• 点击「取消答题」停止答题",
                retry_delay
            )
            dialog.retry_clicked.connect(self._retry_current_question)
            dialog.cancel_clicked.connect(self._finish_flow)
            dialog.show()
            return
        else:
            r = QMessageBox.question(
                self, "LLM 出错",
                f"LLM 调用失败：{msg}\n\n是否重试当前题目？\n（选择「否」将停止答题）",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if r == QMessageBox.Yes:
                logging.info("用户选择重试...")
                QTimer.singleShot(1000, lambda: self._retry_current_question())
            else:
                self._finish_flow()

    def _retry_current_question(self):
        """重试当前题目（LLM 调用失败后）"""
        if self._current_ocr_text:
            self._step_llm_ocr(self._current_ocr_text)
        else:
            self._step_screenshot()

    def _step_click_answer(self, answer_str: str):
        logging.info(f"【步骤4】执行答题动作，答案：{answer_str}")
        if not answer_str or not answer_str.strip():
            logging.warning("LLM 返回空答案，跳过当前题目")
            QTimer.singleShot(500, self._step_screenshot)
            return
        
        self.lbl_status.setText("执行答题动作...")
        
        opt_count = self.spin_opt_count.value()
        dynamic_found = len(self._dynamic_options) if hasattr(self, '_dynamic_options') else 0
        
        if self.config.get_dynamic_click() and dynamic_found >= max(1, opt_count * 0.6):
            # 使用动态坐标，缺失的用固定坐标补
            option_positions = []
            all_names = [chr(ord("A") + i) for i in range(opt_count)]
            fixed_positions = {opt["name"]: opt for opt in self.config.get_option_positions()}
            cal = self.config.get_dynamic_offset()
            for name in all_names:
                if name in self._dynamic_options and self._dynamic_options[name]:
                    option_positions.append({"name": name, "x": self._dynamic_options[name][0], "y": self._dynamic_options[name][1]})
                elif name in fixed_positions:
                    opt = fixed_positions[name]
                    x, y = int(opt.get("x",0)), int(opt.get("y",0))
                    if cal: x += cal.get("dx", 0); y += cal.get("dy", 0)
                    option_positions.append({"name": name, "x": x, "y": y})
                else:
                    option_positions.append({"name": name, "x": 0, "y": 0})  # 兜底
            logging.info(f"使用动态坐标：{dynamic_found}/{opt_count} 个选项")
        elif self.config.get_dynamic_click():
            # 动态坐标不足，根据回退开关决定
            if self.config.get_dynamic_fallback():
                option_positions = list(self.config.get_option_positions())
                cal = self.config.get_dynamic_offset()
                if cal:
                    for opt in option_positions:
                        opt["x"] = int(opt["x"]) + cal.get("dx", 0)
                        opt["y"] = int(opt["y"]) + cal.get("dy", 0)
                    logging.info(f"动态坐标不足（{dynamic_found}/{opt_count}），回退固定坐标+校准")
                else:
                    logging.info(f"动态坐标不足（{dynamic_found}/{opt_count}），回退固定坐标")
            else:
                QMessageBox.warning(self, "动态定位失败",
                    f"只找到 {dynamic_found}/{opt_count} 个选项坐标，动态定位不完整。\n"
                    "已停止答题。\n"
                    "提示：可勾选「动态定位不足时回退到固定坐标」后重试。")
                self._finish_flow()
                return
        else:
            # 动态坐标不够 → 回退固定坐标（可叠加校准偏移）
            option_positions = list(self.config.get_option_positions())
            if self.config.get_dynamic_click():
                cal = self.config.get_dynamic_offset()
                if cal:
                    for opt in option_positions:
                        opt["x"] = int(opt["x"]) + cal.get("dx", 0)
                        opt["y"] = int(opt["y"]) + cal.get("dy", 0)
                    logging.info(f"使用固定坐标+校准偏移({cal['dx']},{cal['dy']})：{len(option_positions)} 个选项")
                else:
                    logging.info(f"动态坐标不足（{dynamic_found}/{opt_count}），回退固定坐标（无校准）")
            else:
                logging.info(f"使用固定坐标：{len(option_positions)} 个选项")
        
        # 校准模式：显示红色圆点预览，不实际点击
        if self.chk_calibration.isChecked():
            from gui.calibration_overlay import CalibrationOverlay
            target_name = None
            target_pos = (0, 0)
            targets = MouseController.parse_answer_labels(answer_str, self.spin_opt_count.value())
            if targets:
                target_name = targets[0]
                for opt in option_positions:
                    if opt.get("name") == target_name:
                        target_pos = (int(opt.get("x", 0)), int(opt.get("y", 0)))
                        break
            # 基准位置 = 选项最终坐标 - 当前偏移（让浮层自己加偏移）
            dx = self.spin_offset_x.value()
            dy = self.spin_offset_y.value()
            base_pos = (target_pos[0] - dx, target_pos[1] - dy) if target_name else (0, 0)
            # 网格锚点 = 选项A的位置（行列0,0），不是当前答案的位置
            grid_anchor = None
            for opt in option_positions:
                if opt.get("name") == "A":
                    grid_anchor = (int(opt.get("x", 0)) - dx, int(opt.get("y", 0)) - dy)
                    break
            self._cal_overlay = CalibrationOverlay(
                None, offset_x=dx, offset_y=dy,
                grid_rows=max(1, self.config.get_option_grid_rows()),
                grid_cols=max(1, self.config.get_option_grid_cols()),
                spacing_x=self.config.get_grid_spacing_x(),
                spacing_y=self.config.get_grid_spacing_y(),
            )
            self._cal_overlay.set_target_and_grid(
                target_name or "?", base_pos[0], base_pos[1],
                grid_anchor[0] if grid_anchor else base_pos[0],
                grid_anchor[1] if grid_anchor else base_pos[1],
            )
            self._cal_overlay.closed.connect(self._on_calibration_closed)
            self._cal_overlay.offset_changed.connect(self._on_cal_offset_from_overlay)
            self._cal_overlay.spacing_changed.connect(self._on_cal_spacing_from_overlay)
            return

        next_pos = self.config.get_next_button_pos()
        self._answer_worker = AnswerWorker(
            self.mouse_ctrl, answer_str, option_positions, next_pos,
            max_options=self.spin_opt_count.value(),
        )
        self._answer_worker.finished.connect(self._on_answer_finished)
        self._answer_worker.error.connect(self._on_answer_error)
        self._answer_worker.log.connect(lambda m: logging.info(m))
        self._answer_worker.start()

    def _on_calibration_closed(self):
        """校准浮层关闭后，停止答题流程"""
        self._cal_overlay = None
        self._finish_flow()  # 完全停止，不自动下一题

    def _on_cal_offset_from_overlay(self, dx, dy):
        """校准浮层点了保存后，同步偏移到主窗口并保存配置"""
        self.spin_offset_x.blockSignals(True)
        self.spin_offset_x.setValue(dx)
        self.spin_offset_x.blockSignals(False)
        self.spin_offset_y.blockSignals(True)
        self.spin_offset_y.setValue(dy)
        self.spin_offset_y.blockSignals(False)
        self.config.set_dynamic_offset({"dx": dx, "dy": dy})
        self.config._save_category_config(self.config.get_current_category())
        self.lbl_offset.setText(f"已校准：dx={dx}, dy={dy}")
        self.lbl_offset.setStyleSheet("color:#4a4;")

    def _on_cal_spacing_from_overlay(self, sx, sy):
        """校准浮层保存间距后，同步到主窗口"""
        self.spin_spacing_x.blockSignals(True)
        self.spin_spacing_x.setValue(sx)
        self.spin_spacing_x.blockSignals(False)
        self.spin_spacing_y.blockSignals(True)
        self.spin_spacing_y.setValue(sy)
        self.spin_spacing_y.blockSignals(False)
        self.config.set_grid_spacing_x(sx)
        self.config.set_grid_spacing_y(sy)
        self.config._save_category_config(self.config.get_current_category())

    def _step_click_next_only(self):
        """仅点击下一题（主观题使用）"""
        next_pos = self.config.get_next_button_pos()
        if next_pos:
            self.mouse_ctrl.click_next(next_pos)
            logging.info("主观题处理完毕，已点击下一题")
        QTimer.singleShot(1000, self._step_screenshot)

    def _on_answer_finished(self, success: bool):
        if success:
            logging.info("答题动作执行成功")
        else:
            logging.warning("答题动作执行失败")
        
        if not self._running:  # 用户已停止
            return
        
        # 动态检测显存（仅 GPU 模式）：剩余显存越少，检测越频繁
        try:
            ocr_cfg = self.config.get_ocr_settings()
            if ocr_cfg.get("device", "cpu") in ("auto", "gpu"):
                from core.ocr_module import get_gpu_memory_info, clear_ocr_cache
                if not hasattr(self, '_gpu_answer_count'):
                    self._gpu_answer_count = 0
                    self._gpu_next_check = 5  # 首次检测在第 5 题
                
                self._gpu_answer_count += 1
                if self._gpu_answer_count >= self._gpu_next_check:
                    mem = get_gpu_memory_info()
                    if mem["total_mb"] > 0:
                        remaining_mb = mem["total_mb"] - mem["used_mb"]
                        # 触发阈值：剩余显存 < 总显存的 20%，且至少需要预留 300MB
                        threshold_mb = max(300, mem["total_mb"] * 0.2)
                        
                        if remaining_mb < threshold_mb:
                            logging.info(
                                f"GPU 显存不足：剩余 {remaining_mb:.0f}MB/{mem['total_mb']:.0f}MB "
                                f"({mem['usage_pct']:.1f}%)，触发清理..."
                            )
                            clear_ocr_cache()
                            import gc
                            gc.collect()
                            try:
                                import paddle
                                if paddle.is_compiled_with_cuda():
                                    paddle.device.cuda.empty_cache()
                            except Exception:
                                pass
                            logging.info(f"GPU 显存清理完成")
                            self._gpu_next_check = self._gpu_answer_count + 3  # 清理后密集检测
                        else:
                            # 根据剩余显存比例动态计算下次检测间隔
                            remaining_ratio = remaining_mb / mem["total_mb"]
                            if remaining_ratio > 0.6:
                                next_interval = 15
                            elif remaining_ratio > 0.4:
                                next_interval = 10
                            elif remaining_ratio > 0.2:
                                next_interval = 5
                            else:
                                next_interval = 3
                            self._gpu_next_check = self._gpu_answer_count + next_interval
        except Exception as e:
            logging.debug(f"GPU 显存检测跳过: {e}")
        
        # 自动停止检查
        mode = self.config.get_stop_mode()
        if mode == "count":
            self._question_counter += 1
            total = self.config.get_total_questions()
            self.lbl_stop_progress.setText(f"已答：{self._question_counter} / {total}")
            if self._question_counter >= total:
                self._show_completion_dialog()
                return
        
        # 继续下一题
        QTimer.singleShot(500, self._step_screenshot)

    def _show_completion_dialog(self):
        self._completion_dialog_shown = True
        self._running = False
        self.lbl_stop_progress.setText("答题完成！")
        r = QMessageBox.question(
            self, "答题完成",
            f"答题已完成（共 {self._question_counter} 题）。\n"
            "如实际未完成答题，请按「是」继续，按「否」结束。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if r == QMessageBox.Yes:
            self._running = True
            self._completion_dialog_shown = False  # 重置标记
            QTimer.singleShot(500, self._step_screenshot)
        else:
            self._finish_flow()

    def _check_ocr_stop(self, ocr_text: str):
        """OCR 模式下检查题号是否到达最后一题"""
        mode = self.config.get_stop_mode()
        if mode != "ocr":
            return False
        
        region = self.config.get_progress_region()
        if not region or not self._current_image:
            return False
        
        # 裁切题号区域做二次 OCR
        from PIL import Image
        try:
            r = region
            cropped = self._current_image.crop((r["x"], r["y"], r["x"]+r["w"], r["y"]+r["h"]))
            from core.ocr_module import recognize_image
            sub_result = recognize_image(img=cropped)
            if sub_result["success"]:
                progress_text = sub_result["text"]
                current, total = self._parse_progress(progress_text)
                if current and total and current >= total:
                    self._question_counter = total
                    self.lbl_stop_progress.setText(f"已答：{current} / {total}")
                    return True
                if current and total:
                    self.lbl_stop_progress.setText(f"进度：{current} / {total}")
        except Exception as e:
            logging.warning(f"OCR 进度识别失败: {e}")
        return False

    @staticmethod
    def _parse_progress(text: str):
        """从 OCR 文字中解析 当前题号/总题数"""
        import re
        # 支持格式: "1:100", "1/100", "1/100题", "1 OF 100", "第1题/共100题"
        patterns = [
            r'(\d+)\s*[:：/]\s*(\d+)',
            r'(\d+)\s*OF\s*(\d+)',
            r'第?\s*(\d+)\s*题?\s*/\s*共?\s*(\d+)\s*题?',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return int(m.group(1)), int(m.group(2))
        return None, None

    def _is_duplicate_question(self, ocr_text: str) -> bool:
        """检查是否为重复扫描的相同题目（LLM 不稳定时重扫）"""
        if not hasattr(self, '_last_ocr_texts'):
            self._last_ocr_texts = []
        simplified = ocr_text[:80].strip()
        for prev in self._last_ocr_texts[-3:]:
            if prev and len(prev) > 20:
                short_len = min(len(prev), len(simplified))
                same = sum(1 for i in range(min(short_len, 50)) if i < len(prev) and i < len(simplified) and prev[i] == simplified[i])
                if short_len > 0 and same / min(short_len, 50) > 0.85:
                    return True
        self._last_ocr_texts.append(simplified)
        if len(self._last_ocr_texts) > 3:
            self._last_ocr_texts.pop(0)
        return False

    def _on_answer_error(self, msg: str):
        logging.error(f"答题动作异常：{msg}")
        self._finish_flow()

    # ========================================================
    # 关闭事件
    # ========================================================
    def closeEvent(self, ev):
        if self._running:
            QMessageBox.warning(self, "正在运行", "请先停止自动答题，再关闭窗口！")
            ev.ignore()
            return
        # 静默保存配置，不弹窗
        self._save_llm_config(show_message=False)
        # 卸载快捷键
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass
        logging.info("程序退出")
        ev.accept()
