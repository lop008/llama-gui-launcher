import json
import os
import sys
import threading
import time
import webbrowser
from collections import Counter

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
    QSystemTrayIcon, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QToolButton, QVBoxLayout, QWidget, QMenu,
)

from . import __version__
from .about_dialog import AboutDialog
from .cmd_builder import build_args, build_command, model_alias
from .config import Config
from .gguf_reader import format_gguf_info, read_gguf_info
from . import hf_info
from .model_scanner import find_mmproj_for, human_size, scan_models
from .presets import PRESETS, SAMPLING_PRESETS
from .server import (
    ServerManager, find_llama_server_processes, kill_all_llama_server, port_in_use,
)
from .system_monitor import SystemMonitor

try:
    from . import tools as tools_mod
    from . import opencode_launcher
except Exception:
    tools_mod = None
    opencode_launcher = None


DARK_QSS = """
QMainWindow, QDialog { background-color: #2b2b2b; }
QWidget { background-color: #2b2b2b; color: #e6e6e6; font-size: 13px; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTableWidget {
    background-color: #3c3f41; color: #e6e6e6; border: 1px solid #555; border-radius: 3px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #7a8; }
QPushButton { background-color: #3c3f41; color: #e6e6e6; border: 1px solid #555; border-radius: 3px; padding: 4px 10px; }
QPushButton:hover { background-color: #4a4d4f; }
QPushButton:pressed { background-color: #5a5d5f; }
QPushButton:disabled { color: #777; background-color: #333; }
QComboBox QAbstractItemView { background-color: #3c3f41; color: #e6e6e6; selection-background-color: #4a4d4f; }
QHeaderView::section { background-color: #3c3f41; color: #e6e6e6; border: 1px solid #555; padding: 3px; }
QMenuBar { background-color: #2b2b2b; color: #e6e6e6; }
QMenuBar::item:selected { background-color: #4a4d4f; }
QMenu { background-color: #2b2b2b; color: #e6e6e6; border: 1px solid #555; }
QMenu::item:selected { background-color: #4a4d4f; }
QToolButton { color: #e6e6e6; }
QStatusBar { background-color: #262626; color: #aaa; }
QStatusBar::item { border: none; }
QTabWidget::pane { border: 1px solid #555; }
QTabBar::tab { background-color: #3c3f41; color: #e6e6e6; padding: 4px 10px; border: 1px solid #555; }
QTabBar::tab:selected { background-color: #4a4d4f; }
QScrollBar:vertical { background: #3c3f41; width: 12px; }
QScrollBar::handle:vertical { background: #666; min-height: 24px; border-radius: 4px; }
QScrollBar:horizontal { background: #3c3f41; height: 12px; }
QScrollBar::handle:horizontal { background: #666; min-width: 24px; border-radius: 4px; }
QScrollArea { border: none; }
QToolTip { background-color: #3c3f41; color: #e6e6e6; border: 1px solid #555; }
QMessageBox { background-color: #2b2b2b; }
QGroupBox { border: 1px solid #555; border-radius: 4px; margin-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
"""


class CollapsibleBox(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self._toggle = QToolButton(text=title, checkable=True, checked=True)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(Qt.ArrowType.DownArrow)
        self._toggle.setStyleSheet("QToolButton { border: none; font-weight: bold; font-size: 14px; }")
        self._toggle.clicked.connect(self._on_toggle)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(4, 4, 4, 4)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._toggle)
        outer.addWidget(self._content)

    def _on_toggle(self, checked):
        self._content.setVisible(checked)
        self._toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.toggled.emit(checked)

    def layout(self):
        return self._content_layout

    def set_collapsed(self, collapsed):
        self._toggle.setChecked(not collapsed)
        self._content.setVisible(not collapsed)
        self._toggle.setArrowType(Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.DownArrow)


class MainWindow(QMainWindow):
    tool_scan_done = pyqtSignal()
    model_scan_done = pyqtSignal()
    model_info = pyqtSignal(str)
    hf_info_done = pyqtSignal(str)

    def __init__(self, base_dir):
        super().__init__()
        if getattr(sys, "frozen", False):
            # 打包后：可写数据放在 exe 所在目录；只读资源在 _MEIPASS 解压目录
            self.base_dir = os.path.dirname(sys.executable)
            self.resource_dir = getattr(sys, "_MEIPASS", self.base_dir)
        else:
            self.base_dir = base_dir
            self.resource_dir = base_dir
        self.cfg = Config(self.base_dir)
        self.server = ServerManager()
        self.monitor = SystemMonitor(self)
        self._loading = False
        self._quitting = False
        self._models = []
        self._mmprojs = []
        self._tools_found = {}
        self._tool_rows = []
        self._last_selected_tool = None
        self._tray = None

        self._build_menu()
        self._build_ui()
        self.setWindowIcon(self._load_icon())
        self._connect()
        self._apply_config()
        self._apply_theme()
        self._setup_tray()
        self.monitor.start()
        self.refresh_models(keep_selection=True)
        self._set_running_state(False)
        self.scan_tools()
        self._log_file("程序启动")
        self.statusBar().showMessage("就绪")
        QTimer.singleShot(1500, self._check_residual)

    # ------------------------------------------------------------------ UI
    def _build_menu(self):
        m = self.menuBar()
        menu_start = m.addMenu("开始(&S)")
        self.act_start = QAction("启动服务(&R)", self)
        self.act_start.setShortcut("Ctrl+R")
        self.act_stop = QAction("停止服务(&T)", self)
        self.act_quit = QAction("退出(&X)", self)
        self.act_quit.setShortcut("Ctrl+Q")
        menu_start.addAction(self.act_start)
        menu_start.addAction(self.act_stop)
        menu_start.addSeparator()
        menu_start.addAction(self.act_quit)

        menu_tools = m.addMenu("工具(&T)")
        self.act_refresh = QAction("刷新模型", self)
        self.act_open_dir = QAction("打开模型目录", self)
        self.act_web = QAction("打开管理页面", self)
        self.act_api = QAction("查看 API 模型列表", self)
        self.act_open_agent = QAction("打开 Agent 工具", self)
        self.act_clear_log = QAction("清空日志", self)
        self.act_open_log = QAction("打开日志目录", self)
        self.act_export = QAction("导出配置 (.aic)", self)
        self.act_import = QAction("导入配置 (.aic)", self)
        menu_tools.addAction(self.act_refresh)
        menu_tools.addAction(self.act_open_dir)
        menu_tools.addSeparator()
        menu_tools.addAction(self.act_web)
        menu_tools.addAction(self.act_api)
        menu_tools.addSeparator()
        menu_tools.addAction(self.act_open_agent)
        menu_tools.addSeparator()
        menu_tools.addAction(self.act_export)
        menu_tools.addAction(self.act_import)
        menu_tools.addSeparator()
        menu_tools.addAction(self.act_clear_log)
        menu_tools.addAction(self.act_open_log)

        menu_help = m.addMenu("关于(&H)")
        self.act_about = QAction("开发者信息", self)
        self.act_docs = QAction("参数说明", self)
        menu_help.addAction(self.act_docs)
        menu_help.addAction(self.act_about)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        splitter_widget = QWidget()
        splitter_layout = QVBoxLayout(splitter_widget)
        splitter_layout.setContentsMargins(0, 0, 0, 0)
        splitter_layout.setSpacing(2)

        # ---- 顶部参数区（自然高度，折叠/展开随内容伸缩）----
        self.params_panel = QWidget()
        pw = QVBoxLayout(self.params_panel)
        pw.setContentsMargins(0, 0, 0, 0)

        self.box_basic = CollapsibleBox("基本参数")
        self._build_basic(self.box_basic.layout())
        self.box_advanced = CollapsibleBox("高级参数")
        self.box_advanced.set_collapsed(True)
        self._build_advanced(self.box_advanced.layout())
        pw.addWidget(self.box_basic)
        pw.addWidget(self.box_advanced)
        pw.addStretch(1)

        self.box_basic.toggled.connect(self._reflow_window)
        self.box_advanced.toggled.connect(self._reflow_window)

        splitter_layout.addWidget(self.params_panel, 0)

        # ---- 底部 Tab 区 ----
        tabs = QTabWidget()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.preview_view = QPlainTextEdit()
        self.preview_view.setReadOnly(True)
        self.info_view = QTextEdit()
        self.info_view.setReadOnly(True)

        tool_tab = QWidget()
        tt = QVBoxLayout(tool_tab)
        tt.setContentsMargins(0, 0, 0, 0)
        tool_bar = QHBoxLayout()
        tip = QLabel("双击行 = 打开；选中行后点底部「打开 Agent 工具」；未找到的工具双击可手动指定路径")
        tip.setStyleSheet("color: #888;")
        tool_bar.addWidget(tip)
        tool_bar.addStretch(1)
        tt.addLayout(tool_bar)
        self.tool_table = QTableWidget(0, 5)
        self.tool_table.setHorizontalHeaderLabels(["工具", "类型", "描述", "状态", "打开"])
        self.tool_table.horizontalHeader().setStretchLastSection(True)
        self.tool_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tool_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tool_table.doubleClicked.connect(self._tool_table_double)
        self.tool_table.currentCellChanged.connect(self._on_tool_cell_changed)
        tt.addWidget(self.tool_table)

        # ---- 模型信息 Tab（带联网查询按钮）----
        info_tab = QWidget()
        it = QVBoxLayout(info_tab)
        it.setContentsMargins(0, 0, 0, 0)
        info_bar = QHBoxLayout()
        self.btn_hf = QPushButton("联网查询该模型")
        self.btn_hf.setToolTip("用模型名联网搜索 HuggingFace，拉取简介/下载量/点赞等公开信息（本地缓存 7 天）")
        info_bar.addWidget(self.btn_hf)
        info_bar.addStretch(1)
        it.addLayout(info_bar)
        it.addWidget(self.info_view)

        tabs.addTab(self.log_view, "运行日志")
        tabs.addTab(self.preview_view, "命令预览")
        tabs.addTab(tool_tab, "Agent 工具")
        tabs.addTab(info_tab, "模型信息")
        self.tabs = tabs
        self.tabs.setMinimumHeight(280)
        splitter_layout.addWidget(self.tabs, 1)
        root.addWidget(splitter_widget)

        # ---- 主按钮行 ----
        btns = QHBoxLayout()
        self.btn_start = QPushButton("启动服务")
        self.btn_start.setToolTip("启动 llama-server（隐藏窗口后台运行），就绪后自动打开浏览器")
        self.btn_stop = QPushButton("停止服务")
        self.btn_stop.setToolTip("停止服务并清理进程树（模型跑飞/幻觉时一键终止）")
        self.btn_web = QPushButton("打开网页")
        self.btn_web.setToolTip("在浏览器中打开 llama.cpp Web 聊天界面")
        self.btn_agent = QPushButton("打开 Agent 工具")
        self.btn_agent.setToolTip("打开「Agent 工具」列表中当前选中（高亮）的工具")
        self.btn_save = QPushButton("保存配置")
        self.btn_save.setToolTip("将当前所有设置保存到 config.json（服务器参数、所选模型、视觉模型、工具路径、主题等），下次启动自动恢复")
        btns.addWidget(self.btn_start)
        btns.addWidget(self.btn_stop)
        btns.addWidget(self.btn_web)
        btns.addWidget(self.btn_agent)
        btns.addWidget(self.btn_save)

        # ---- 广告位占位符（430×40，右侧紧挨保存配置）----
        self.label_ad = QLabel()
        self.label_ad.setFixedSize(430, 40)
        self.label_ad.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_ad.setToolTip("广告位（430×40）。放入 assets/ad.png 即可替换为你的图片。")
        ad_path = os.path.join(self.resource_dir, "assets", "ad.png")
        if os.path.isfile(ad_path):
            pm = QPixmap(ad_path)
            if not pm.isNull():
                self.label_ad.setPixmap(pm.scaled(430, 40, Qt.AspectRatioMode.KeepAspectRatio,
                                                  Qt.TransformationMode.SmoothTransformation))
        else:
            self.label_ad.setText("广告位 430×40")
            self.label_ad.setStyleSheet(
                "background:#e8e8e8; color:#999; border:1px dashed #bbb; font-size:12px;")
        btns.addWidget(self.label_ad)

        btns.addStretch(1)
        root.addLayout(btns)

        # ---- 状态栏（右侧：监控指标 + 主题切换灯泡）----
        sb = self.statusBar()

        def _mk_label():
            lab = QLabel("")
            lab.setStyleSheet("color: #777; padding: 0 6px;")
            return lab

        self.btn_theme = QPushButton("💡 浅色")
        self.btn_theme.setFixedWidth(86)
        self.btn_theme.setToolTip("切换深色 / 浅色模式")
        sb.addPermanentWidget(self.btn_theme)          # 最右

        self.label_api = _mk_label()
        self.label_api.setText("API 未运行")
        self.label_api.setToolTip("外部工具（opencode 等）是否正在通过 API 请求模型")
        sb.addPermanentWidget(self.label_api)

        self.label_model = _mk_label()
        self.label_model.setText("模型 未运行")
        self.label_model.setToolTip("当前加载运行的模型")
        sb.addPermanentWidget(self.label_model)

        self.label_vram = _mk_label()
        self.label_vram.setToolTip("显卡显存占用（已用/总，nvidia-smi）")
        sb.addPermanentWidget(self.label_vram)

        self.label_mem = _mk_label()
        self.label_mem.setToolTip("系统内存占用")
        sb.addPermanentWidget(self.label_mem)

        self.label_cpu = _mk_label()
        self.label_cpu.setToolTip("服务运行时显示 llama-server 进程 CPU 占用；未运行时显示系统 CPU")
        sb.addPermanentWidget(self.label_cpu)          # 最左（靠近普通消息）

        self.setWindowTitle(f"LLama 启动器 v{__version__}")
        self.resize(880, 860)

    def _build_basic(self, lay):
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        grid.addWidget(QLabel("llama目录:"), 0, 0)
        self.edit_dir = QLineEdit()
        self.edit_dir.setPlaceholderText("llama.cpp 所在目录（含 llama-server.exe）")
        self.edit_dir.setToolTip("llama.cpp 的安装目录，目录下应有 llama-server.exe 及配套 DLL 文件。")
        btn_dir = QPushButton("浏览…")
        btn_dir.clicked.connect(self._browse_dir)
        btn_dir.setToolTip("选择 llama.cpp 目录")
        self.btn_refresh = QPushButton("刷新模型")
        self.btn_refresh.clicked.connect(lambda: self.refresh_models())
        self.btn_refresh.setToolTip("重新扫描目录下的所有 GGUF 模型文件")
        grid.addWidget(self.edit_dir, 0, 1)
        grid.addWidget(btn_dir, 0, 2)
        grid.addWidget(self.btn_refresh, 0, 3)

        grid.addWidget(QLabel("主模型:"), 1, 0)
        self.combo_model = QComboBox()
        self.combo_model.setToolTip("选择要加载的 GGUF 主模型（自动扫描目录得到）")
        grid.addWidget(self.combo_model, 1, 1, 1, 3)

        grid.addWidget(QLabel("视觉模型:"), 2, 0)
        self.combo_mmproj = QComboBox()
        self.combo_mmproj.setToolTip("视觉模型（mmproj）文件，负责把图像编码成模型能理解的向量。\n自动按目录配对：只使用与主模型同一目录下的 mmproj，保证主模型与视觉模型配套一致。\n也可手动选择其他 mmproj，或选择「（不使用）」以纯文本模式运行。\n鼠标悬停可查看完整路径。")
        self.combo_mmproj.addItem("（不使用）", None)
        grid.addWidget(self.combo_mmproj, 2, 1, 1, 2)
        self.label_mmproj_warn = QLabel("")
        self.label_mmproj_warn.setStyleSheet("color: #d33;")
        self.label_mmproj_warn.setWordWrap(True)
        grid.addWidget(self.label_mmproj_warn, 2, 3)

        grid.addWidget(QLabel("监听地址:"), 3, 0)
        self.edit_host = QLineEdit()
        self.edit_host.setToolTip("服务监听的地址（Host）。\n127.0.0.1 = 仅本机访问；0.0.0.0 = 局域网内其他设备也能访问。")
        grid.addWidget(self.edit_host, 3, 1)

        grid.addWidget(QLabel("端口:"), 3, 2)
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(8080)
        self.spin_port.setToolTip("服务监听的端口（默认 8080）。\nOpenAI 兼容接口地址为 http://监听地址:端口/v1")
        grid.addWidget(self.spin_port, 3, 3)

        grid.addWidget(QLabel("上下文预设:"), 4, 0)
        self.combo_preset = QComboBox()
        for name, _ctx in PRESETS:
            self.combo_preset.addItem(name)
        self.combo_preset.setToolTip("根据显卡显存大小，一键应用推荐的「上下文长度」（只修改「上下文长度」参数）。\n点选后「上下文长度」会同步更新为该档位；手动修改「上下文长度」后此下拉会自动回显对应档位或「自定义」。\n例：24GB 显存推荐 512K 上下文。")
        grid.addWidget(self.combo_preset, 4, 1)

        grid.addWidget(QLabel("GPU层数:"), 4, 2)
        self.combo_ngl = QComboBox()
        self.combo_ngl.setEditable(True)
        self.combo_ngl.addItems(["all", "auto", "0", "1", "10", "20", "32", "40", "64"])
        self.combo_ngl.setToolTip("卸载到 GPU 显存中的层数（-ngl）。\nall = 尽可能全部放入显存；auto = 自动判断；0 = 纯 CPU 运行；也可填具体层数。")
        grid.addWidget(self.combo_ngl, 4, 3)

        grid.addWidget(QLabel("上下文长度:"), 5, 0)
        self.spin_ctx = QSpinBox()
        self.spin_ctx.setRange(256, 1048576)
        self.spin_ctx.setSingleStep(1024)
        self.spin_ctx.setValue(32768)
        self.spin_ctx.setToolTip("上下文长度（token），即模型一次会话最多能「记住」的对话量。\n这是真正传给 llama-server 的参数（-c），可自由设为任意值。\n越大越占显存/内存，也越慢。建议 ≤ 模型的训练上下文。\n可参考「模型信息」页显示的模型训练上下文。")
        grid.addWidget(self.spin_ctx, 5, 1)

        grid.addWidget(QLabel("预测Token:"), 5, 2)
        self.spin_np = QSpinBox()
        self.spin_np.setRange(-1, 1000000)
        self.spin_np.setValue(8192)
        self.spin_np.setSpecialValueText("-1 = 无限")
        self.spin_np.setToolTip("每次回答最多生成的 token 数（-n）。\n-1 = 不限制，直到模型输出结束符为止；\n若模型「停不下来/无限复读」，可调小此值限制回答长度。")
        grid.addWidget(self.spin_np, 5, 3)

        lay.addLayout(grid)

    def _build_advanced(self, lay):
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        grid.addWidget(QLabel("CPU线程:"), 0, 0)
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(-1, 256)
        self.spin_threads.setValue(-1)
        self.spin_threads.setSpecialValueText("-1 = 自动")
        self.spin_threads.setToolTip("用于计算的 CPU 线程数（-t）。\n-1 = 自动（使用全部逻辑核心）。")
        grid.addWidget(self.spin_threads, 0, 1)

        grid.addWidget(QLabel("批大小:"), 0, 2)
        self.spin_batch = QSpinBox()
        self.spin_batch.setRange(1, 16384)
        self.spin_batch.setValue(2048)
        self.spin_batch.setToolTip("逻辑批大小（-b），影响 prompt 处理速度。默认 2048 即可。")
        grid.addWidget(self.spin_batch, 0, 3)

        grid.addWidget(QLabel("并行slots:"), 0, 4)
        self.spin_slots = QSpinBox()
        self.spin_slots.setRange(-1, 64)
        self.spin_slots.setValue(-1)
        self.spin_slots.setSpecialValueText("-1 = 自动")
        self.spin_slots.setToolTip("同时处理的并发请求数（-np）。\n多个客户端同时使用时建议 ≥2；每个 slot 会额外占用上下文内存。\n-1 = 自动。")
        grid.addWidget(self.spin_slots, 0, 5)

        grid.addWidget(QLabel("闪存注意力:"), 1, 0)
        self.combo_fa = QComboBox()
        self.combo_fa.addItems(["on", "off", "auto"])
        self.combo_fa.setToolTip("Flash Attention 闪存注意力（-fa）。\non = 开启，省显存且更快（N 卡 / 新架构推荐）；\noff = 关闭，兼容性更好。")
        grid.addWidget(self.combo_fa, 1, 1)

        grid.addWidget(QLabel("KV缓存类型:"), 1, 2)
        self.combo_kvc = QComboBox()
        self.combo_kvc.addItems(["f16", "q8_0", "q4_0", "bf16", "f32"])
        self.combo_kvc.setToolTip("KV 缓存的量化类型（-ctk/-ctv）。\nf16 = 默认，质量好；\nq8_0 / q4_0 = 更省显存（换更长上下文）但精度略降；\nf32 = 精度最高但最占显存。")
        grid.addWidget(self.combo_kvc, 1, 3)

        self.check_cont = QCheckBox("连续批处理")
        self.check_cont.setChecked(True)
        self.check_cont.setToolTip("连续批处理（--cont-batching）。\n开启后并发请求能更高效地共享算力，多客户端场景推荐开启。")
        grid.addWidget(self.check_cont, 1, 4, 1, 2)

        grid.addWidget(QLabel("温度:"), 2, 0)
        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(0.0, 2.0)
        self.spin_temp.setSingleStep(0.05)
        self.spin_temp.setValue(0.8)
        self.spin_temp.setToolTip("温度（--temp）：控制随机性/创造力。\n越低越保守严谨（0 = 每次都选最可能的词，趋于复读）；\n越高越发散创意（可能胡言乱语）。\n建议 0.3~1.2。")
        grid.addWidget(self.spin_temp, 2, 1)

        grid.addWidget(QLabel("Top-P:"), 2, 2)
        self.spin_topp = QDoubleSpinBox()
        self.spin_topp.setRange(0.0, 1.0)
        self.spin_topp.setSingleStep(0.05)
        self.spin_topp.setValue(0.95)
        self.spin_topp.setToolTip("核采样（--top-p）：只从累计概率达到该值的候选词中选。\n0.95 = 默认；1.0 = 关闭；越小越保守。")
        grid.addWidget(self.spin_topp, 2, 3)

        grid.addWidget(QLabel("Top-K:"), 2, 4)
        self.spin_topk = QSpinBox()
        self.spin_topk.setRange(0, 200)
        self.spin_topk.setValue(40)
        self.spin_topk.setSpecialValueText("0 = 默认")
        self.spin_topk.setToolTip("（--top-k）：只从概率最高的前 K 个候选词中选。\n40 = 默认；0 = 关闭；越小越保守。")
        grid.addWidget(self.spin_topk, 2, 5)

        grid.addWidget(QLabel("重复惩罚:"), 3, 0)
        self.spin_rp = QDoubleSpinBox()
        self.spin_rp.setRange(0.0, 2.0)
        self.spin_rp.setSingleStep(0.1)
        self.spin_rp.setValue(1.0)
        self.spin_rp.setSpecialValueText("0 = 默认")
        self.spin_rp.setToolTip("重复惩罚（--repeat-penalty）。\n>1 抑制重复输出，有助于缓解「无限复读/幻觉循环」；\n1.0 = 关闭；建议 1.0~1.3。")
        grid.addWidget(self.spin_rp, 3, 1)

        grid.addWidget(QLabel("API Key:"), 3, 2)
        self.edit_apikey = QLineEdit()
        self.edit_apikey.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_apikey.setToolTip("API 密钥（--api-key）。\n设置后客户端调用接口必须携带此 Key，否则会被拒绝。\n留空 = 不设密钥，任何人都能访问。")
        grid.addWidget(self.edit_apikey, 3, 3)

        grid.addWidget(QLabel("超时(秒):"), 3, 4)
        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(30, 86400)
        self.spin_timeout.setValue(3600)
        self.spin_timeout.setToolTip("服务读写超时（--timeout）。\n单个请求超过该秒数会被强制断开，默认 3600。")
        grid.addWidget(self.spin_timeout, 3, 5)

        self.check_mlock = QCheckBox("mlock 锁定内存")
        self.check_mlock.setToolTip("--mlock：把模型锁定在内存中，防止被系统换出到磁盘。\n占内存更多，但推理更稳定。")
        self.check_mmap = QCheckBox("禁用 mmap")
        self.check_mmap.setToolTip("--no-mmap：关闭内存映射加载。\n加载更慢但内存占用更可控，个别磁盘/内存环境可改善稳定性。")
        self.check_browser = QCheckBox("启动成功后自动打开浏览器")
        self.check_browser.setChecked(True)
        self.check_browser.setToolTip("服务就绪后自动用默认浏览器打开 Web 界面。")
        grid.addWidget(self.check_mlock, 4, 0, 1, 2)
        grid.addWidget(self.check_mmap, 4, 2, 1, 2)
        grid.addWidget(self.check_browser, 4, 4, 1, 2)

        grid.addWidget(QLabel("采样预设:"), 5, 0)
        self.combo_sampling = QComboBox()
        for name, _v in SAMPLING_PRESETS:
            self.combo_sampling.addItem(name)
        self.combo_sampling.setToolTip(
            "一键应用一组采样参数（温度/Top-P/Top-K/重复惩罚）。\n"
            "严谨=低温度适合写代码/翻译；均衡=日常对话；创意=高温度适合写作/脑洞。\n"
            "手动修改任一采样参数后会自动回到「自定义」。")
        grid.addWidget(self.combo_sampling, 5, 1, 1, 3)

        lay.addLayout(grid)

    # ------------------------------------------------------------ helpers
    def _connect(self):
        self.server.log.connect(self._on_server_log)
        self.server.state.connect(self._on_server_state)
        self.server.healthy.connect(self._on_healthy)
        self.server.exited.connect(self._on_exited)
        self.model_scan_done.connect(self._on_model_scan_done)
        self.tool_scan_done.connect(self._on_tool_scan_done)
        self.model_info.connect(self.info_view.setPlainText)
        self.hf_info_done.connect(self._on_hf_info)

        self.monitor.cpu_changed.connect(lambda v: self.label_cpu.setText(f"CPU {v:.0f}%"))
        self.monitor.mem_changed.connect(self._on_mem)
        self.monitor.vram_changed.connect(self._on_vram)
        self.monitor.model_changed.connect(lambda n: self.label_model.setText(f"模型 {n}"))
        self.monitor.api_changed.connect(lambda t: self.label_api.setText(t))

        self.btn_start.clicked.connect(self.start_server)
        self.btn_stop.clicked.connect(self.stop_server)
        self.btn_web.clicked.connect(self.open_web)
        self.btn_agent.clicked.connect(self.open_selected_agent_tool)
        self.btn_save.clicked.connect(self.save_config)
        self.btn_theme.clicked.connect(self.toggle_theme)
        self.btn_hf.clicked.connect(self._query_hf_info)

        self.act_start.triggered.connect(self.start_server)
        self.act_stop.triggered.connect(self.stop_server)
        self.act_quit.triggered.connect(self.quit_app)
        self.act_refresh.triggered.connect(lambda: self.refresh_models())
        self.act_open_dir.triggered.connect(self.open_model_dir)
        self.act_web.triggered.connect(self.open_web)
        self.act_api.triggered.connect(self.open_api)
        self.act_open_agent.triggered.connect(self.open_selected_agent_tool)
        self.act_clear_log.triggered.connect(self.log_view.clear)
        self.act_open_log.triggered.connect(self.open_log_dir)
        self.act_export.triggered.connect(self.export_config)
        self.act_import.triggered.connect(self.import_config)
        self.act_about.triggered.connect(self.show_about)
        self.act_docs.triggered.connect(self.open_docs)

        self.combo_model.currentIndexChanged.connect(self._on_model_changed)
        self.combo_mmproj.currentIndexChanged.connect(self._on_mmproj_changed)
        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        self.spin_ctx.valueChanged.connect(self._on_ctx_manual)
        self.combo_sampling.currentIndexChanged.connect(self._on_sampling_preset)
        for w in (self.spin_temp, self.spin_topp, self.spin_topk, self.spin_rp):
            w.valueChanged.connect(self._on_sampling_manual)

        for w in self._param_widgets():
            for sig in ("currentIndexChanged", "valueChanged", "textChanged", "toggled"):
                if hasattr(w, sig):
                    try:
                        getattr(w, sig).connect(self.update_preview)
                    except Exception:
                        pass

    def _param_widgets(self):
        return [
            self.combo_ngl, self.spin_ctx, self.spin_np, self.spin_threads,
            self.spin_batch, self.spin_slots, self.combo_fa, self.combo_kvc,
            self.check_cont, self.spin_temp, self.spin_topp, self.spin_topk,
            self.spin_rp, self.edit_apikey, self.check_mlock, self.check_mmap,
            self.check_browser, self.spin_timeout, self.edit_host, self.spin_port,
        ]

    def _gather_server_cfg(self):
        return {
            "host": self.edit_host.text().strip() or "127.0.0.1",
            "port": self.spin_port.value(),
            "ngl": self.combo_ngl.currentText().strip() or "all",
            "ctx": self.spin_ctx.value(),
            "n_predict": self.spin_np.value(),
            "threads": self.spin_threads.value(),
            "batch": self.spin_batch.value(),
            "flash_attn": self.combo_fa.currentText(),
            "cont_batching": self.check_cont.isChecked(),
            "kv_cache_type": self.combo_kvc.currentText(),
            "slots": self.spin_slots.value(),
            "temp": self.spin_temp.value(),
            "top_p": self.spin_topp.value(),
            "top_k": self.spin_topk.value(),
            "repeat_penalty": self.spin_rp.value(),
            "api_key": self.edit_apikey.text(),
            "mlock": self.check_mlock.isChecked(),
            "no_mmap": self.check_mmap.isChecked(),
            "timeout": self.spin_timeout.value(),
            "auto_open_browser": self.check_browser.isChecked(),
        }

    def _apply_config(self):
        self._loading = True
        d = self.cfg.data
        self.edit_dir.setText(d.get("llama_dir", ""))
        s = d.get("server", {})
        self.edit_host.setText(s.get("host", "127.0.0.1"))
        self.spin_port.setValue(int(s.get("port", 8080)))
        ngl = str(s.get("ngl", "all"))
        idx = self.combo_ngl.findText(ngl)
        if idx >= 0:
            self.combo_ngl.setCurrentIndex(idx)
        else:
            self.combo_ngl.setEditText(ngl)
        self.spin_ctx.setValue(int(s.get("ctx", 32768)))
        self.spin_np.setValue(int(s.get("n_predict", 8192)))
        self.spin_threads.setValue(int(s.get("threads", -1)))
        self.spin_batch.setValue(int(s.get("batch", 2048)))
        self.spin_slots.setValue(int(s.get("slots", -1)))
        self.combo_fa.setCurrentText(s.get("flash_attn", "on"))
        self.combo_kvc.setCurrentText(s.get("kv_cache_type", "f16"))
        self.check_cont.setChecked(bool(s.get("cont_batching", True)))
        self.spin_temp.setValue(float(s.get("temp", 0.8)))
        self.spin_topp.setValue(float(s.get("top_p", 0.95)))
        self.spin_topk.setValue(int(s.get("top_k", 40)))
        self.spin_rp.setValue(float(s.get("repeat_penalty", 1.0)))
        self.edit_apikey.setText(s.get("api_key", ""))
        self.check_mlock.setChecked(bool(s.get("mlock", False)))
        self.check_mmap.setChecked(bool(s.get("no_mmap", False)))
        self.check_browser.setChecked(bool(s.get("auto_open_browser", True)))
        self.spin_timeout.setValue(int(s.get("timeout", 3600)))
        self._loading = False
        self._sync_preset_combo()

    def save_config(self):
        d = self.cfg.data
        d["llama_dir"] = self.edit_dir.text().strip()
        d["server"] = self._gather_server_cfg()
        d["model"] = self.combo_model.currentData() or ""
        d["mmproj"] = self.combo_mmproj.currentData() or ""
        d["window_geometry"] = list(self.geometry().getRect())
        ok = self.cfg.save()
        self.statusBar().showMessage("配置已保存" if ok else "配置保存失败", 3000)

    def export_config(self):
        """导出完整配置为 .aic 文件（内容即 JSON，仅扩展名不同）。"""
        default = os.path.join(self.base_dir, "LLama启动器配置.aic")
        path, _ = QFileDialog.getSaveFileName(self, "导出配置", default, "LLama 启动器配置 (*.aic);;JSON (*.json)")
        if not path:
            return
        self.save_config()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.cfg.data, f, ensure_ascii=False, indent=2)
            self.statusBar().showMessage(f"配置已导出: {path}", 5000)
            self._on_server_log(f"[配置] 已导出到 {path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {e}")

    def import_config(self):
        """从 .aic / .json 文件导入完整配置并应用到界面。"""
        path, _ = QFileDialog.getOpenFileName(self, "导入配置", self.base_dir,
                                              "LLama 启动器配置 (*.aic *.json);;所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("文件内容不是有效的配置")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败: {e}")
            return
        from .config import DEFAULTS, _merge
        self.cfg.data = _merge(DEFAULTS, loaded)
        self._apply_config()
        self._apply_theme()
        self.refresh_models(keep_selection=True)
        self.statusBar().showMessage(f"配置已导入: {path}", 5000)
        self._on_server_log(f"[配置] 已从 {path} 导入")

    # ---------------------------------------------------------- 模型相关
    def refresh_models(self, keep_selection=False):
        llama_dir = self.edit_dir.text().strip()
        if not llama_dir or not os.path.isdir(llama_dir):
            self._models, self._mmprojs = [], []
            self._rebuild_model_combos(None)
            return

        self._scan_gen = getattr(self, "_scan_gen", 0) + 1
        gen = self._scan_gen
        self._pending_keep = keep_selection

        def work():
            ms, mps = scan_models(llama_dir)
            if gen != getattr(self, "_scan_gen", 0):
                return  # 过期扫描，丢弃
            self._models, self._mmprojs = ms, mps
            self.model_scan_done.emit()

        threading.Thread(target=work, daemon=True).start()
        self.statusBar().showMessage("正在扫描模型目录…", 2000)

    def _on_model_scan_done(self):
        keep_path = self.cfg.data.get("model", "") if self._pending_keep else None
        self._pending_keep = False
        self._rebuild_model_combos(keep_path)
        self.statusBar().showMessage(f"发现 {len(self._models)} 个模型, {len(self._mmprojs)} 个视觉模型", 4000)
        self.update_preview()

    def _rebuild_model_combos(self, keep_path):
        self._loading = True
        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        for m in self._models:
            label = f"{m.name}  ({human_size(m.size)})"
            self.combo_model.addItem(label, m.path)
        self.combo_model.blockSignals(False)
        if keep_path and keep_path in [m.path for m in self._models]:
            idx = [m.path for m in self._models].index(keep_path)
            self.combo_model.setCurrentIndex(idx)
        elif self._models:
            self.combo_model.setCurrentIndex(0)
        self._loading = False
        self._on_model_changed()

    def _on_model_changed(self):
        path = self.combo_model.currentData()
        if not path:
            self._clear_info()
            self._update_mmproj_warn()
            return
        if not self._loading:
            self.cfg.data["model"] = path
        model = next((m for m in self._models if m.path == path), None)
        auto = find_mmproj_for(model, self._mmprojs)
        dup = {n for n, c in Counter(m.name for m in self._mmprojs).items() if c > 1}
        self._loading = True
        self.combo_mmproj.blockSignals(True)
        self.combo_mmproj.clear()
        self.combo_mmproj.addItem("（不使用）", None)
        sel = 0
        for m in self._mmprojs:
            label = m.name
            if m.name in dup:
                label = f"{m.name} ({os.path.basename(m.dir)})"
            idx = self.combo_mmproj.count()
            self.combo_mmproj.addItem(f"{label}  ({human_size(m.size)})", m.path)
            self.combo_mmproj.setItemData(idx, m.path, Qt.ItemDataRole.ToolTipRole)
            if auto and m.path == auto.path:
                sel = idx
        self.combo_mmproj.setCurrentIndex(sel)
        self.cfg.data["mmproj"] = auto.path if auto else None
        self.combo_mmproj.blockSignals(False)
        self._loading = False
        self._update_mmproj_warn()
        self.update_preview()
        self._load_model_info(path)

    def _on_mmproj_changed(self):
        self.cfg.data["mmproj"] = self.combo_mmproj.currentData() or None
        self._update_mmproj_warn()
        self.update_preview()

    def _embedding_length(self, path):
        """读取模型的文本嵌入维度（mmproj 用 projection_dim，主模型用 embedding_length）。"""
        if not path:
            return None
        if not hasattr(self, "_emb_cache"):
            self._emb_cache = {}
        if path not in self._emb_cache:
            try:
                info = read_gguf_info(path) or {}
                self._emb_cache[path] = info.get("projection_dim") or info.get("embedding_length")
            except Exception:
                self._emb_cache[path] = None
        return self._emb_cache[path]

    def _mmproj_mismatch(self, model_path, mmproj_path):
        """返回 (模型维度, 视觉模型维度)；不匹配返回元组，匹配/未知返回 None。"""
        if not mmproj_path:
            return None
        me = self._embedding_length(model_path)
        pe = self._embedding_length(mmproj_path)
        if me is not None and pe is not None and me != pe:
            return (me, pe)
        return None

    def _update_mmproj_warn(self):
        if not hasattr(self, "label_mmproj_warn"):
            return
        model_path = self.combo_model.currentData()
        mmproj_path = self.combo_mmproj.currentData()
        mm = self._mmproj_mismatch(model_path, mmproj_path)
        if mm:
            self.label_mmproj_warn.setText(
                f"⚠ 主模型与视觉模型维度不匹配 ({mm[0]} vs {mm[1]})，可能无法加载，请更换视觉模型")
            self.label_mmproj_warn.setToolTip(
                "llama.cpp 要求主模型与 mmproj 的嵌入维度（embedding_length）一致。")
        else:
            self.label_mmproj_warn.setText("")
            self.label_mmproj_warn.setToolTip("")

    def _load_model_info(self, path):
        def work():
            text = format_gguf_info(path)
            try:
                self.model_info.emit(text)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _clear_info(self):
        self.info_view.setPlainText("未选择模型")

    def _on_preset_changed(self):
        idx = self.combo_preset.currentIndex()
        if idx <= 0:
            return
        _name, ctx = PRESETS[idx]
        if ctx:
            self._loading = True
            self.spin_ctx.setValue(ctx)
            self._loading = False
            self._sync_preset_combo()
        self.statusBar().showMessage(f"已应用上下文预设: {PRESETS[idx][0]}", 3000)

    def _sync_preset_combo(self):
        """上下文长度变化时，让「上下文预设」下拉自动回显对应档位；非预设值显示「自定义」。"""
        if self._loading or not hasattr(self, "combo_preset"):
            return
        ctx = self.spin_ctx.value()
        target = 0
        for i, (_name, v) in enumerate(PRESETS):
            if i > 0 and v is not None and v == ctx:
                target = i
                break
        if self.combo_preset.currentIndex() != target:
            self.combo_preset.blockSignals(True)
            self.combo_preset.setCurrentIndex(target)
            self.combo_preset.blockSignals(False)

    def _on_ctx_manual(self, _v):
        self._sync_preset_combo()

    # ------------------------------------------------------------- 预览
    def update_preview(self):
        if self._loading:
            return
        model = self.combo_model.currentData()
        if not model:
            self.preview_view.setPlainText("请选择模型")
            return
        llama_dir = self.edit_dir.text().strip()
        s = self._gather_server_cfg()
        try:
            args = build_args(model, self.combo_mmproj.currentData(), s, llama_dir)
            self.preview_view.setPlainText(build_command(args))
        except Exception as e:
            self.preview_view.setPlainText(f"生成命令失败: {e}")

    # ------------------------------------------------------------- 服务
    def start_server(self):
        model = self.combo_model.currentData()
        if not model:
            QMessageBox.information(self, "提示", "请先选择模型")
            return
        llama_dir = self.edit_dir.text().strip()
        if not os.path.isfile(os.path.join(llama_dir, "llama-server.exe")):
            QMessageBox.warning(self, "提示", "未找到 llama-server.exe，请检查 llama 目录")
            return
        host = self.edit_host.text().strip() or "127.0.0.1"
        port = self.spin_port.value()
        if port_in_use(host, port):
            ret = QMessageBox.question(
                self, "端口占用", f"端口 {port} 已被占用，可能已有服务在运行。\n仍然尝试启动？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return

        self.save_config()
        s = self._gather_server_cfg()
        mmproj_path = self.combo_mmproj.currentData()
        mm = self._mmproj_mismatch(model, mmproj_path)
        if mm:
            ret = QMessageBox.warning(
                self, "视觉模型不匹配",
                f"主模型与视觉模型的嵌入维度不一致：主模型 {mm[0]} vs 视觉模型 {mm[1]}。\n"
                "llama.cpp 会因此加载失败（error: mismatch between text model and mmproj）。\n\n"
                "建议：切换一个配套的视觉模型，或选择「（不使用）」以纯文本模式运行。\n\n"
                "仍要尝试启动吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return
        try:
            args = build_args(model, mmproj_path, s, llama_dir)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"构建命令失败: {e}")
            return

        self._log_file(">>> " + build_command(args))
        ok = self.server.start(args, llama_dir, host, port)
        if ok:
            self._set_running_state(True)
            self.monitor.set_server(self.server.proc, self.server.url, os.path.basename(model))
            self.statusBar().showMessage("服务启动中…", 0)

    def stop_server(self):
        self.server.stop()
        self.monitor.set_server(None)
        self._set_running_state(False)

    def _set_running_state(self, running):
        self.btn_start.setEnabled(not running)
        self.act_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.act_stop.setEnabled(running)
        self.btn_web.setEnabled(running)

    def _on_server_state(self, msg):
        self.statusBar().showMessage(msg, 0)
        self._log_file(msg)

    def _on_healthy(self, url):
        self._set_running_state(True)
        self._log_file(f"服务已就绪: {url}")
        self.monitor.fetch_model_now()
        if self.check_browser.isChecked():
            webbrowser.open(url)
        self.statusBar().showMessage(f"服务已就绪: {url}", 0)

    def _on_exited(self, code):
        self._set_running_state(False)
        self.monitor.set_server(None)
        if not self.server.manual_stop and code != 0:
            self.statusBar().showMessage(f"服务已退出（退出码 {code}）", 0)

    def open_web(self):
        url = f"http://{self.edit_host.text().strip() or '127.0.0.1'}:{self.spin_port.value()}"
        webbrowser.open(url)

    def open_api(self):
        url = f"http://{self.edit_host.text().strip() or '127.0.0.1'}:{self.spin_port.value()}/v1/models"
        webbrowser.open(url)

    def open_model_dir(self):
        d = self.edit_dir.text().strip()
        if os.path.isdir(d):
            os.startfile(d)  # noqa: S606
        else:
            QMessageBox.information(self, "提示", "模型目录无效")

    # ------------------------------------------------------ Agent 工具
    def scan_tools(self):
        overrides = self.cfg.data.get("tools", {})
        llama_dir = self.edit_dir.text().strip()

        def work():
            self._tools_found = tools_mod.scan_all(overrides, llama_dir)
            self.tool_scan_done.emit()

        threading.Thread(target=work, daemon=True).start()
        self.statusBar().showMessage("正在检测工具…", 2000)

    def _on_tool_scan_done(self):
        self._fill_tool_table()
        self.statusBar().showMessage("工具检测完成", 3000)

    def _fill_tool_table(self):
        rows = []
        for t in tools_mod.ALL:
            rows.append((t, self._tools_found.get(t["id"])))
        self._tool_rows = [r[0] for r in rows]
        self.tool_table.setRowCount(len(rows))
        for r, (tool, path) in enumerate(rows):
            name_item = QTableWidgetItem(tool.get("name", tool["id"]))
            name_item.setData(Qt.ItemDataRole.UserRole, tool.get("id"))
            cat = "终端" if tool.get("category") == "terminal" else "应用"
            desc_item = QTableWidgetItem(tool.get("desc", ""))
            type_item = QTableWidgetItem(cat)
            status_item = QTableWidgetItem(path or "未找到")
            self.tool_table.setItem(r, 0, name_item)
            self.tool_table.setItem(r, 1, type_item)
            self.tool_table.setItem(r, 2, desc_item)
            self.tool_table.setItem(r, 3, status_item)
            btn = QPushButton("打开" if path else "添加路径")
            btn.clicked.connect(lambda _=False, tid=tool["id"]: self._tool_open(tid))
            self.tool_table.setCellWidget(r, 4, btn)
        self._preserve_tool_selection()

    def _preserve_tool_selection(self):
        """保持上次选中的工具高亮；没有则默认高亮第一行。"""
        if not self._tool_rows:
            return
        row = 0
        last = getattr(self, "_last_selected_tool", None) or self.cfg.data.get("last_agent_tool", "")
        if last:
            for i, t in enumerate(self._tool_rows):
                if t.get("id") == last:
                    row = i
                    break
        self.tool_table.selectRow(row)
        self.tool_table.setCurrentCell(row, 0)

    def _on_tool_cell_changed(self, row, _col, _pr, _pc):
        if 0 <= row < len(self._tool_rows):
            self._last_selected_tool = self._tool_rows[row]["id"]
            self.cfg.data["last_agent_tool"] = self._tool_rows[row]["id"]

    def _tool_table_double(self, index):
        if index.row() < len(self._tool_rows):
            self._tool_open(self._tool_rows[index.row()]["id"])

    def _tool_open(self, tid):
        if tools_mod is None:
            return
        tool = next((t for t in tools_mod.ALL if t["id"] == tid), None)
        if tool is None:
            return
        self._last_selected_tool = tid
        self.cfg.data["last_agent_tool"] = tid
        path = self._tools_found.get(tid)
        override = self.cfg.data.get("tools", {}).get(tid)
        if override and override.get("path"):
            path = override["path"]
        if not path:
            self._prompt_add_path(tool)
            return
        workdir = self.edit_dir.text().strip() or None
        args = override.get("args", "") if override else ""
        env, conn_info, extra_args = self._agent_connect(tool, workdir)
        if extra_args:
            args = (args + " " + extra_args).strip()
        ok = tools_mod.launch(path, tool, args, workdir, env)
        if ok:
            msg = f"已打开 {tool['name']}"
            if conn_info:
                msg += f"　·　{conn_info}"
            self.statusBar().showMessage(msg, 6000)
            self._on_server_log(msg)
        else:
            QMessageBox.warning(self, "提示", "启动失败，请检查路径")

    def _agent_connect(self, tool, workdir=None):
        """打开 Agent 工具时自动配置其连接当前 llama 服务。
        返回 (env, 连接说明文本, 附加启动参数)；服务未运行返回 (None, '服务未运行，无法自动连接', '')。"""
        if not self.server.running:
            return None, "服务未运行，无法自动连接", ""
        s = self._gather_server_cfg()
        base = f"http://{s['host']}:{s['port']}"
        base_v1 = base + "/v1"
        alias = model_alias(self.combo_model.currentData() or "")
        api_key = s.get("api_key", "")
        key = api_key or "llama"
        tid = tool.get("id")
        model_path = self.combo_model.currentData()

        if tid == "opencode" and opencode_launcher is not None:
            cfg = opencode_launcher.build_config(
                s["host"], s["port"], alias, s["ctx"], s["n_predict"], s["api_key"])
            wd = workdir or self.edit_dir.text().strip()
            try:
                opencode_launcher.write_config(wd, cfg)
                return None, f"已自动配置 opencode 连接 {base_v1}（模型 {alias}）", ""
            except Exception as e:
                return None, f"opencode 配置写入失败: {e}", ""
        if tid == "claude":
            return None, "Claude Code 未自动连接（llama.cpp 的 Anthropic 接口兼容性有限），如需连接请手动配置 ANTHROPIC_BASE_URL", ""
        if tid in ("codex", "aichat"):
            return {"OPENAI_BASE_URL": base_v1, "OPENAI_API_KEY": key,
                    "OPENAI_MODEL": alias}, f"已连接 {base_v1}（OpenAI 接口，模型 {alias}）", ""

        # 其他工具（含 GUI 应用）：复制连接信息到剪贴板
        try:
            text = f"模型: {alias}\nAPI: {base_v1}\n"
            if model_path:
                text += f"文件: {model_path}\n"
            QApplication.clipboard().setText(text)
            return None, f"已复制连接信息到剪贴板（{base_v1}，模型 {alias}）", ""
        except Exception:
            return None, f"服务地址 {base_v1}（模型 {alias}）", ""

    def open_selected_agent_tool(self):
        """打开 Agent 工具列表中当前高亮的工具（始终高亮选中行）。"""
        if not self._tool_rows:
            QMessageBox.information(self, "提示", "Agent 工具列表为空")
            return
        row = self.tool_table.currentRow()
        if row < 0 or row >= len(self._tool_rows):
            row = 0
        self._tool_open(self._tool_rows[row]["id"])

    def _prompt_add_path(self, tool):
        ret = QMessageBox.question(
            self, "未找到", f"未找到「{tool.get('name', tool['id'])}」，是否手动指定可执行文件路径？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return
        start = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, f"选择 {tool.get('name')} 可执行文件", start,
                                              "可执行文件 (*.exe *.cmd *.bat *.ps1);;所有文件 (*.*)")
        if not path:
            return
        self.cfg.data.setdefault("tools", {})[tool["id"]] = {"path": path, "args": ""}
        self._tools_found[tool["id"]] = path
        self.cfg.save()
        self._fill_tool_table()
        self.statusBar().showMessage(f"已记录 {tool['name']} 路径", 3000)

    # ---------------------------------------------------------- 其他
    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择 llama.cpp 目录", self.edit_dir.text() or os.path.expanduser("~"))
        if d:
            self.edit_dir.setText(d)
            self.cfg.data["llama_dir"] = d
            self.refresh_models()

    def show_about(self):
        AboutDialog(self.resource_dir, self).exec()

    def open_docs(self):
        doc = os.path.join(self.resource_dir, "参数说明.md")
        if os.path.isfile(doc):
            try:
                os.startfile(doc)  # noqa: S606
            except Exception:
                webbrowser.open(doc)
        else:
            QMessageBox.information(self, "提示", "未找到参数说明文档")

    # ---------------------------------------------------------- 主题
    def toggle_theme(self):
        dark = self.cfg.data.get("theme", "light") != "dark"
        self.cfg.data["theme"] = "dark" if dark else "light"
        self._apply_theme()
        self.cfg.save()

    def _apply_theme(self):
        dark = self.cfg.data.get("theme", "light") == "dark"
        QApplication.instance().setStyleSheet(DARK_QSS if dark else "")
        self.btn_theme.setText("🌙 深色" if not dark else "💡 浅色")

    def _reflow_window(self, checked=None):
        """折叠/展开参数区后，让窗口高度随内容伸缩（双向自适应）。
        checked=True 展开（只长大）；checked=False 折叠（缩短）。
        延迟一小段事件循环，等布局稳定后再执行，避免陈旧的最小尺寸。"""
        QTimer.singleShot(30, lambda: self._apply_reflow(checked))

    def _apply_reflow(self, checked=None):
        if not hasattr(self, "params_panel"):
            return
        QApplication.processEvents()  # 让可见性变化先完成布局
        self.updateGeometry()
        self.params_panel.layout().activate()
        self.params_panel.setMinimumHeight(0)
        ph = self.params_panel.sizeHint().height()
        self.params_panel.setMinimumHeight(ph)
        lm = self.centralWidget().layout().contentsMargins()
        needed = (ph + self.tabs.minimumHeight()
                  + self.menuBar().height() + self.statusBar().height()
                  + lm.top() + lm.bottom() + 4)
        self.setMinimumSize(0, 0)  # 允许收缩（清除陈旧最小尺寸）
        if checked:
            self.resize(self.width(), max(self.height(), needed))
        else:
            self.resize(self.width(), needed)
        QApplication.processEvents()
        self.setMinimumSize(self.minimumSizeHint())  # 恢复为内容实际最小尺寸

    # ---------------------------------------------------------- 日志落盘
    def _log_file(self, text):
        try:
            logdir = os.path.join(self.base_dir, "logs")
            os.makedirs(logdir, exist_ok=True)
            date = time.strftime("%Y%m%d")
            with open(os.path.join(logdir, f"运行日志-{date}.log"), "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
        except Exception:
            pass

    def _on_server_log(self, text):
        self.log_view.appendPlainText(text)
        self._log_file(text)

    def open_log_dir(self):
        logdir = os.path.join(self.base_dir, "logs")
        try:
            os.makedirs(logdir, exist_ok=True)
            os.startfile(logdir)  # noqa: S606
        except Exception as e:
            QMessageBox.information(self, "提示", f"无法打开日志目录: {e}")

    # ---------------------------------------------------------- 状态栏监控
    def _on_mem(self, percent, tip):
        self.label_mem.setText(f"内存 {percent:.0f}%")
        self.label_mem.setToolTip(tip)

    def _on_vram(self, text):
        if text:
            self.label_vram.setText(f"显存 {text}")
            self.label_vram.setVisible(True)
        else:
            self.label_vram.setText("")
            self.label_vram.setVisible(False)

    # ---------------------------------------------------------- 联网查询
    def _query_hf_info(self):
        model = self.combo_model.currentData()
        if not model:
            QMessageBox.information(self, "提示", "请先选择模型")
            return
        query = os.path.basename(model)
        if query.lower().endswith(".gguf"):
            query = query[:-5]
        self.statusBar().showMessage(f"正在联网查询 {query} …", 3000)

        def work():
            text = hf_info.format_info(self.base_dir, query)
            try:
                self.hf_info_done.emit(text)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_hf_info(self, text):
        self.info_view.append("\n\n" + text)

    # ---------------------------------------------------------- 采样预设
    def _on_sampling_preset(self, idx):
        if self._loading or idx <= 0:
            return
        _name, vals = SAMPLING_PRESETS[idx]
        self._loading = True
        self.spin_temp.setValue(vals["temp"])
        self.spin_topp.setValue(vals["top_p"])
        self.spin_topk.setValue(vals["top_k"])
        self.spin_rp.setValue(vals["repeat_penalty"])
        self._loading = False
        self.update_preview()
        self.statusBar().showMessage(f"已应用采样预设: {SAMPLING_PRESETS[idx][0]}", 3000)

    def _on_sampling_manual(self, _v):
        if self._loading:
            return
        if self.combo_sampling.currentIndex() > 0:
            self.combo_sampling.setCurrentIndex(0)

    # ---------------------------------------------------------- 残留检测
    def _check_residual(self):
        if self.server.running:
            return
        procs = find_llama_server_processes()
        if not procs:
            return
        ret = QMessageBox.question(
            self, "检测到残留进程",
            f"检测到 {len(procs)} 个可能残留的 llama-server 进程\n"
            "（上次未正常退出，可能仍在占用显存/内存）。\n是否强制结束它们？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            kill_all_llama_server()
            self._log_file("已强制清理残留的 llama-server 进程")
            self.statusBar().showMessage("已清理残留进程，显存已释放", 4000)

    # ---------------------------------------------------------- 托盘
    def _load_icon(self):
        """窗口/托盘图标：优先使用 assets/icon.ico，否则用程序生成的图标。"""
        ico = os.path.join(self.resource_dir, "assets", "icon.ico")
        if os.path.isfile(ico):
            ic = QIcon(ico)
            if not ic.isNull():
                return ic
        return self._make_icon()

    def _make_icon(self):
        pm = QPixmap(64, 64)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#4a7fdb"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        p.setPen(QColor("white"))
        f = QFont()
        f.setBold(True)
        f.setPointSize(28)
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "L")
        p.end()
        return QIcon(pm)

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        self._tray = QSystemTrayIcon(self._load_icon(), self)
        self._tray.setToolTip("LLama 启动器")
        menu = QMenu()
        act_show = menu.addAction("显示主窗口")
        act_show.triggered.connect(self._show_from_tray)
        act_start = menu.addAction("启动服务")
        act_start.triggered.connect(self.start_server)
        act_stop = menu.addAction("停止服务")
        act_stop.triggered.connect(self.stop_server)
        menu.addSeparator()
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self.quit_app)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def quit_app(self):
        self._quitting = True
        closed = self.close()
        if closed:
            # 隐藏到托盘后 close() 不会触发 lastWindowClosed，需显式退出事件循环
            QApplication.instance().quit()

    def closeEvent(self, event: QCloseEvent):
        if (not self._quitting and self._tray is not None
                and self.cfg.data.get("minimize_to_tray", True)):
            self.hide()
            self._tray.showMessage(
                "LLama 启动器", "已最小化到托盘，点击图标恢复窗口。服务仍在后台运行。",
                QSystemTrayIcon.MessageIcon.Information, 2000)
            event.ignore()
            return
        self.save_config()
        self._log_file("程序退出")
        if self.server.running:
            ret = QMessageBox.question(
                self, "退出", "服务正在运行，退出时是否同时停止服务？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Cancel)
            if ret == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if ret == QMessageBox.StandardButton.Yes:
                self.server.stop()
                self.monitor.set_server(None)
        super().closeEvent(event)
