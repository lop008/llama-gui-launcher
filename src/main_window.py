import json
import os
import sys
import threading
import time
import webbrowser
from collections import Counter

from PyQt6.QtCore import QEvent, QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCloseEvent, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QGroupBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox,
    QSystemTrayIcon, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QToolButton, QVBoxLayout, QWidget, QMenu,
)

from . import __version__
from .about_dialog import AboutDialog
from .bat_validator import ValidateBatDialog
from .cmd_builder import (
    KV_CACHE_TYPES, SPLIT_MODES, build_args, build_bat_content, build_command,
    build_preview_bat, model_alias,
)
from .config import Config
from .gguf_reader import detect_mtp, format_gguf_info, read_gguf_info
from . import hf_info
from .hf_download_tab import HFDownloadTab
from .llama_updater import get_local_version
from .model_scanner import find_mmproj_for, human_size, scan_models, sort_models
from .presets import PRESETS, SAMPLING_PRESETS
from .server import (
    ServerManager, find_llama_server_processes, kill_all_llama_server, port_in_use,
)
from .stats_dialog import StatsDialog
from .system_monitor import SystemMonitor
from .themes import THEMES, build_qss
from .updater_tab import UpdaterTab
from .usage_stats import StatsStore, parse_log_line

try:
    from . import tools as tools_mod
    from . import opencode_launcher
except Exception:
    tools_mod = None
    opencode_launcher = None


# 主题/配色方案已抽离到 src/themes.py，切换主题不改变布局尺寸。
class CollapsibleBox(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self._toggle = QToolButton(text=title, checkable=True, checked=True)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(Qt.ArrowType.DownArrow)
        self._toggle.setStyleSheet("QToolButton { border: none; }")
        _f = self._toggle.font()
        _f.setPointSize(_f.pointSize() + 3)   # 分组标题加粗加大（基本参数/多显卡/高级参数）
        _f.setBold(True)
        self._toggle.setFont(_f)
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


CREATE_NO_WINDOW = 0x08000000


class _LlamaVersionWorker(QThread):
    """后台运行 llama-server --version，避免阻塞 UI。"""
    done = pyqtSignal(str)

    def __init__(self, exe_path, parent=None):
        super().__init__(parent)
        self._exe = exe_path
        self.probe_pid = None   # 正在运行的 --version 探测进程 PID（残留检测需排除）

    def run(self):
        def _record(pid):
            self.probe_pid = pid
        try:
            ver = get_local_version(self._exe, pid_cb=_record)
        except Exception:
            ver = ""
        finally:
            self.probe_pid = None
        self.done.emit(ver)


class MainWindow(QMainWindow):
    tool_scan_done = pyqtSignal()
    model_scan_done = pyqtSignal()
    model_info = pyqtSignal(str)
    hf_info_done = pyqtSignal(str)
    gpu_detected = pyqtSignal()
    mtp_detected = pyqtSignal()
    vram_weights = pyqtSignal(list)   # A5: nvidia-smi 显存查询完成（整数权重列表）

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

        # ---- 模型统计（功能 9）----
        self._stats_store = None
        self._stats_path = None
        self._running_model_name = ""    # 当前服务运行的模型名（统计归属）
        self._usage_pending = 0.0        # 本次运行累计时长（统计已在 tick 中逐笔计入，此值仅用于重置）
        self._mtp_cache = {}             # path -> (bool|None, [names])
        self._gpu_probe_pid = None       # --list-devices 探测进程 PID（残留检测需排除）

        # 数字框不响应鼠标滚轮：滚动窗口/参数区经过 spinbox 时不再误改数值
        # （上下箭头与直接输入仍然可用；动态创建的 GPU 权重框也一并覆盖）
        _app = QApplication.instance()
        if _app is not None:
            _app.installEventFilter(self)

        self._build_menu()
        self._build_ui()
        self.setWindowIcon(self._load_icon())
        self._connect()
        self._apply_config()
        self._apply_theme()
        self._setup_tray()
        self.monitor.start()

        # 后台检测本地 llama-server 版本，完成后更新标题栏
        self._llama_ver_worker = _LlamaVersionWorker(self._launcher_exe(), self)
        self._llama_ver_worker.done.connect(self._on_llama_version)
        # 残留检测等版本探测结束后再做（探测进程本身也是 llama-server.exe，
        # 冷启动加载大 DLL 时可能 >1.5s，否则每次启动都会误报「残留进程」）。
        self._llama_ver_worker.done.connect(
            lambda _v: QTimer.singleShot(600, self._check_residual))
        self._llama_ver_worker.start()

        # 使用时长累计：服务运行期间每 5 秒记一笔（功能 9）
        self._usage_timer = QTimer(self)
        self._usage_timer.timeout.connect(self._tick_usage)
        self._usage_timer.start(5000)

        self._ensure_valid_llama_dir()
        self.refresh_models(keep_selection=True)
        self._set_running_state(False)
        self.scan_tools()
        self._log_file("程序启动")
        self.statusBar().showMessage("就绪")
        if not os.environ.get("LLAMA_LAUNCHER_NO_GPU_DETECT"):
            QTimer.singleShot(2000, self.detect_gpus)   # 启动时自动检测多显卡（功能 3）

    # ---------------------------------------------------------- 模型统计（功能 9）
    def _stats(self):
        """惰性创建 StatsStore；数据目录变化时自动重建。"""
        path = os.path.join(self._data_dir(), "stats.json")
        if self._stats_store is None or self._stats_path != path:
            self._stats_path = path
            self._stats_store = StatsStore(os.path.dirname(path))
        return self._stats_store

    def _stats_model_name(self):
        """统计归属的模型名：优先当前选中模型，其次监控到的运行模型。"""
        p = self.combo_model.currentData() if hasattr(self, "combo_model") else None
        if p:
            return os.path.basename(p)
        return ""

    def _tick_usage(self):
        if not (hasattr(self, "server") and self.server.running):
            return
        name = self._stats_model_name() or self._running_model_name
        if not name:
            return
        # 时长在运行期间逐笔累计（每 5 秒一笔并立即计入统计），停止/退出时只落盘，
        # 切勿再次累加 pending，否则总时长会翻倍。
        self._usage_pending += 5.0
        self._stats().add_usage(name, seconds=5.0)

    def _flush_usage(self):
        """停止/退出：保存统计文件（时长已在运行期间逐笔累计，这里不再重复累加）。"""
        try:
            self._usage_pending = 0.0
            self._stats().save()
        except Exception:
            pass

    def show_stats(self):
        """打开独立的模型统计界面（功能 9）。"""
        if getattr(self, "_stats_dlg", None) is None:
            self._stats_dlg = StatsDialog(self._stats(), self)
        else:
            self._stats_dlg.refresh()
        self._stats_dlg.show()
        self._stats_dlg.raise_()
        self._stats_dlg.activateWindow()

    # ------------------------------------------------------------------ 事件过滤
    def eventFilter(self, obj, ev):
        """吞掉所有数字框（QSpinBox/QDoubleSpinBox）的滚轮事件。

        否则滚动窗口时鼠标掠过任意一个数值框，值就会被顺带改小/改大
        （表现为「数字只能往下调」）。上下箭头与直接键入不受影响。"""
        if ev.type() == QEvent.Type.Wheel and isinstance(obj, QAbstractSpinBox):
            return True
        return super().eventFilter(obj, ev)

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
        self.act_export_bat = QAction("导出一键启动 (.bat)", self)
        self.act_export_bat.setToolTip(
            "将当前模型与参数生成可双击直接启动 llama-server 的批处理，"
            "并在桌面创建带软件图标的快捷方式")
        self.act_export_preview_bat = QAction("导出命令预览 (.bat)…", self)
        self.act_export_preview_bat.setToolTip(
            "把「命令预览」页里的完整命令行原样保存为 .bat 文件，可自选存储路径（功能 6）")
        self.act_stats = QAction("模型统计…", self)
        self.act_stats.setToolTip(
            "打开独立的模型统计界面：打开次数、使用时长、输入/输出 token，"
            "支持按小时 / 日 / 月查看（功能 9）")
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
        menu_tools.addAction(self.act_export_bat)
        menu_tools.addAction(self.act_export_preview_bat)
        menu_tools.addAction(self.act_stats)
        menu_tools.addSeparator()
        menu_tools.addAction(self.act_clear_log)
        menu_tools.addAction(self.act_open_log)

        menu_help = m.addMenu("关于(&H)")
        self.act_about = QAction("开发者信息", self)
        self.act_docs = QAction("参数说明", self)
        menu_help.addAction(self.act_docs)
        menu_help.addAction(self.act_about)
        self.act_update_now = QAction("立即更新", self)
        menu_help.addAction(self.act_update_now)

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
        self.box_gpu = CollapsibleBox("多显卡 (Multi-GPU)")
        self.box_gpu.set_collapsed(True)
        self._build_gpu(self.box_gpu.layout())
        self.box_advanced = CollapsibleBox("高级参数")
        self.box_advanced.set_collapsed(True)
        self._build_advanced(self.box_advanced.layout())
        pw.addWidget(self.box_basic)
        pw.addWidget(self.box_gpu)
        pw.addWidget(self.box_advanced)
        pw.addStretch(1)

        self.box_basic.toggled.connect(self._reflow_window)
        self.box_gpu.toggled.connect(self._reflow_window)
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

        # ---- 模型下载 Tab（功能 5：HF unsloth 检索 + 断点续传下载）----
        self.download_tab = HFDownloadTab(self)

        # ---- 更新 llama.cpp Tab（功能 10）----
        self.updater_tab = UpdaterTab(self)

        tabs.addTab(self.log_view, "运行日志")
        tabs.addTab(self.preview_view, "命令预览")
        tabs.addTab(tool_tab, "Agent 工具")
        tabs.addTab(info_tab, "模型信息")
        tabs.addTab(self.download_tab, "模型下载")
        tabs.addTab(self.updater_tab, "更新 llama.cpp")
        self.tabs = tabs
        self.tabs.setMinimumHeight(280)
        splitter_layout.addWidget(self.tabs, 1)
        root.addWidget(splitter_widget)

        # ---- 主按钮区（C1: 双排 × 5 列共 10 个；广告位在网格右侧）----
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
        # C1: 第 2 排 —— 校验启动文件 + 导出启动文件（7 号位）+ 3 个占位按钮
        self.btn_validate_bat = QPushButton("校验启动文件")
        self.btn_validate_bat.setToolTip(
            "选择 .bat/.cmd/.ps1/.sh/文本脚本，静态校验启动项能否正常运行并生成参数报告。\n"
            "支持 bat 变量（set VAR=… / %VAR%）、^ 续行合并、REM/:: 注释跳过。")
        self.btn_export_file = QPushButton("导出启动文件")
        self.btn_export_file.setToolTip(
            "把当前模型与全部参数导出为可双击直接启动 llama-server 的 .bat 一键启动脚本，"
            "并在桌面创建带软件图标的快捷方式（等同「工具 → 导出一键启动 (.bat)」）")
        for _i in range(2, 5):
            _b = QPushButton("预留功能")
            _b.setEnabled(False)
            _b.setToolTip("预留功能（暂未开放）")
            setattr(self, f"btn_ph_{_i}", _b)

        btn_grid = QGridLayout()
        btn_grid.setHorizontalSpacing(8)
        btn_grid.setVerticalSpacing(8)
        _row0 = [self.btn_start, self.btn_stop, self.btn_web, self.btn_agent, self.btn_save]
        _row1 = [self.btn_validate_bat, self.btn_export_file, self.btn_ph_2, self.btn_ph_3, self.btn_ph_4]
        for _r, _row in enumerate((_row0, _row1)):
            for _c, _b in enumerate(_row):
                _b.setFixedWidth(120)   # 压缩按钮宽度（原 150）
                _b.setFixedHeight(36)
                btn_grid.addWidget(_b, _r, _c)

        # ---- 广告位占位符（430×40，按钮网格右侧）----
        self.label_ad = QLabel()
        self.label_ad.setMinimumSize(160, 40)
        self.label_ad.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.label_ad.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_ad.setScaledContents(True)   # 图片随控件尺寸拉伸 → 横向填充
        self.label_ad.setToolTip("广告位。放入 assets/ad.png 即可替换为你的图片（横向自动填充）。")
        ad_path = os.path.join(self.resource_dir, "assets", "ad.png")
        if os.path.isfile(ad_path):
            pm = QPixmap(ad_path)
            if not pm.isNull():
                self.label_ad.setPixmap(pm)
        else:
            self.label_ad.setText("广告位")
            self.label_ad.setStyleSheet(
                "background:#0a1322; color:#2f5a75; border:1px dashed #1d4f7a; font-size:12px;")
        # C1: 广告位放在按钮网格右侧，横向填充剩余空间（不参与双排网格）
        btns = QHBoxLayout()
        btns.addLayout(btn_grid)
        btns.addSpacing(8)
        btns.addWidget(self.label_ad, 1)
        root.addLayout(btns)

        # ---- 状态栏（左侧：当前模型路径；右侧：监控指标 + 主题切换灯泡）----
        sb = self.statusBar()

        # ---- 功能 1：当前选中模型的完整绝对路径 → 状态栏左侧（_on_model_changed 中更新）----
        self.label_model_path = QLabel("未选择模型")
        self.label_model_path.setMaximumWidth(460)
        self.label_model_path.setToolTip("当前选中主模型的完整路径")
        sb.addWidget(self.label_model_path)

        def _mk_label():
            lab = QLabel("")
            lab.setStyleSheet("color: #777; padding: 0 6px;")
            return lab

        self.btn_theme = QPushButton("🎨 主题")
        self.btn_theme.setFixedWidth(96)
        self.btn_theme.setToolTip("选择配色方案：深色 / 浅色 / 橙色 / 绿色 / 灰色 / 棕色")
        theme_menu = QMenu(self)
        for _key, _th in THEMES.items():
            _act = theme_menu.addAction(f"{_th['icon']} {_th['name']}")
            _act.triggered.connect(lambda _=False, k=_key: self.set_theme(k))
        self.btn_theme.setMenu(theme_menu)
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
        # 双排按钮网格 + 广告位需要较宽窗口，直接以目标尺寸初始化
        self.resize(1280, 1280)

    def _build_basic(self, lay):
        # ---- A4: 「生成参数」分组（先创建；控件由 basic/advanced 两处添加进来）----
        self.group_gen = QGroupBox("生成参数")
        self._gen_grid = QGridLayout(self.group_gen)
        self._gen_grid.setContentsMargins(8, 2, 8, 6)
        self._gen_grid.setHorizontalSpacing(10)
        self._gen_grid.setVerticalSpacing(6)
        # 标签列不伸缩、控件列平均伸缩：三组「标签+控件」均匀铺满整行，标签完整可见
        for _c in (0, 2, 4):
            self._gen_grid.setColumnStretch(_c, 0)
        for _c in (1, 3, 5):
            self._gen_grid.setColumnStretch(_c, 1)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        grid.addWidget(QLabel("模型目录:"), 0, 0)
        self.edit_dir = QLineEdit()
        self.edit_dir.setPlaceholderText("扫描模型的根目录（2~3 级子目录内的 .gguf）")
        self.edit_dir.setToolTip("模型扫描根目录。程序会在此目录的 2~3 级子目录内扫描 .gguf 模型（自动跳过 .venv/.git 等无关目录）。")
        btn_dir = QPushButton("浏览…")
        btn_dir.clicked.connect(self._browse_dir)
        btn_dir.setToolTip("选择模型扫描目录")
        self.btn_refresh = QPushButton("刷新模型")
        self.btn_refresh.clicked.connect(lambda: self.refresh_models())
        self.btn_refresh.setToolTip("重新扫描模型目录下的所有 GGUF 模型文件")
        grid.addWidget(self.edit_dir, 0, 1)
        grid.addWidget(btn_dir, 0, 2)
        grid.addWidget(self.btn_refresh, 0, 3)

        # ---- A2: 排序方式移到「主模型」行末尾（功能 1）----
        self.combo_sort = QComboBox()
        for name in ("目录+文件名", "大小降序", "名称"):
            self.combo_sort.addItem(name)
        self.combo_sort.setToolTip(
            "模型列表排序方式：\n"
            "· 目录+文件名 = 先按所在目录、再按文件名从小到大（自然排序，默认）；\n"
            "· 大小降序 = 大文件在前；\n"
            "· 名称 = 仅按文件名从小到大。")

        grid.addWidget(QLabel("启动器文件:"), 1, 0)
        self.edit_launcher = QLineEdit()
        self.edit_launcher.setPlaceholderText("留空自动用 模型目录\\llama-server.exe")
        self.edit_launcher.setToolTip(
            "启动服务时使用的可执行文件（默认 llama-server.exe）。\n"
            "若将来 llama 改名字或路径不同，可在此直接用文件选择器指定新文件。\n"
            "留空 = 自动回退到 模型目录\\llama-server.exe")
        btn_launcher = QPushButton("浏览…")
        btn_launcher.clicked.connect(self._browse_launcher)
        btn_launcher.setToolTip("选择启动器可执行文件（*.exe）")
        btn_launcher_clear = QPushButton("清除")
        btn_launcher_clear.clicked.connect(self._clear_launcher)
        btn_launcher_clear.setToolTip("清除自定义启动器文件，恢复为自动查找")
        grid.addWidget(self.edit_launcher, 1, 1)
        grid.addWidget(btn_launcher, 1, 2)
        grid.addWidget(btn_launcher_clear, 1, 3)

        grid.addWidget(QLabel("数据目录:"), 2, 0)
        self.edit_data_dir = QLineEdit()
        self.edit_data_dir.setPlaceholderText("留空 = 程序所在目录")
        # A3: tooltip 按实际行为撰写（redirect_data_dir 只迁移 config.json，不复制旧统计/日志）
        self.edit_data_dir.setToolTip(
            "存放本地数据：config.json 权威副本、使用统计 stats.json、"
            "运行日志 logs/、联网查询缓存 hf_model_cache.json。\n"
            "留空 = 程序所在目录。切换后新产生的数据写入新目录，"
            "并在程序目录留下指向文件（已有的统计/日志文件不会自动迁移）。")
        btn_data_dir = QPushButton("浏览…")
        btn_data_dir.clicked.connect(self._browse_data_dir)
        btn_data_dir.setToolTip("选择数据存储目录")
        btn_data_reset = QPushButton("恢复默认")
        btn_data_reset.clicked.connect(self._reset_data_dir)
        btn_data_reset.setToolTip("恢复为程序所在目录")
        grid.addWidget(self.edit_data_dir, 2, 1)
        grid.addWidget(btn_data_dir, 2, 2)
        grid.addWidget(btn_data_reset, 2, 3)

        # ---- 功能 5：主模型与排序同一行，排序放在主模型右侧，保持原有功能 ----
        grid.addWidget(QLabel("主模型:"), 3, 0)
        self.combo_model = QComboBox()
        self.combo_model.setToolTip("选择要加载的 GGUF 主模型（自动扫描目录得到）")
        grid.addWidget(self.combo_model, 3, 1)
        grid.addWidget(QLabel("排序:"), 3, 2)
        self.combo_sort.setMinimumWidth(118)
        grid.addWidget(self.combo_sort, 3, 3)

        grid.addWidget(QLabel("视觉模型:"), 4, 0)
        self.combo_mmproj = QComboBox()
        self.combo_mmproj.setToolTip("视觉模型（mmproj）文件，负责把图像编码成模型能理解的向量。\n只列出与主模型同一目录下的 mmproj（保证配套一致），或选择「（不使用）」以纯文本模式运行。\n鼠标悬停可查看完整路径。")
        self.combo_mmproj.addItem("（不使用）", None)
        grid.addWidget(self.combo_mmproj, 4, 1, 1, 2)
        self.label_mmproj_warn = QLabel("")
        self.label_mmproj_warn.setStyleSheet("color: #ff6a6a;")
        self.label_mmproj_warn.setWordWrap(True)
        grid.addWidget(self.label_mmproj_warn, 4, 3)

        grid.addWidget(QLabel("监听地址:"), 5, 0)
        self.edit_host = QLineEdit()
        self.edit_host.setToolTip("服务监听的地址（Host）。\n127.0.0.1 = 仅本机访问；0.0.0.0 = 局域网内其他设备也能访问。")
        grid.addWidget(self.edit_host, 5, 1)

        grid.addWidget(QLabel("端口:"), 5, 2)
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(8080)
        self.spin_port.setToolTip("服务监听的端口（默认 8080）。\nOpenAI 兼容接口地址为 http://监听地址:端口/v1")
        grid.addWidget(self.spin_port, 5, 3)

        # GPU层数(-ngl) 已移入「生成参数」分组（见 _build_advanced）

        lay.addLayout(grid)

        # ---- A4: 上下文预设 / 上下文长度 / 预测Token → 「生成参数」分组 ----
        self._gen_grid.addWidget(QLabel("上下文预设:"), 0, 0)
        self.combo_preset = QComboBox()
        for name, _ctx in PRESETS:
            self.combo_preset.addItem(name)
        self.combo_preset.setToolTip("根据显卡显存大小，一键应用推荐的「上下文长度」（只修改「上下文长度」参数）。\n点选后「上下文长度」会同步更新为该档位；手动修改「上下文长度」后此下拉会自动回显对应档位或「自定义」。\n例：24GB 显存推荐 512K 上下文。")
        self._gen_grid.addWidget(self.combo_preset, 0, 1)

        self._gen_grid.addWidget(QLabel("上下文长度:"), 0, 2)
        self.spin_ctx = QSpinBox()
        self.spin_ctx.setRange(256, 1048576)
        self.spin_ctx.setSingleStep(1024)
        self.spin_ctx.setValue(32768)
        self.spin_ctx.setToolTip("上下文长度（token），即模型一次会话最多能「记住」的对话量。\n这是真正传给 llama-server 的参数（-c），可自由设为任意值。\n越大越占显存/内存，也越慢。建议 ≤ 模型的训练上下文。\n可参考「模型信息」页显示的模型训练上下文。")
        self._gen_grid.addWidget(self.spin_ctx, 0, 3)

        self._gen_grid.addWidget(QLabel("预测Token:"), 0, 4)
        self.spin_np = QSpinBox()
        self.spin_np.setRange(-1, 1000000)
        self.spin_np.setValue(8192)
        self.spin_np.setSpecialValueText("-1 = 无限")
        self.spin_np.setToolTip("每次回答最多生成的 token 数（-n）。\n-1 = 不限制，直到模型输出结束符为止；\n若模型「停不下来/无限复读」，可调小此值限制回答长度。")
        self._gen_grid.addWidget(self.spin_np, 0, 5)

        lay.addWidget(self.group_gen)

    def _build_advanced(self, lay):
        grid = QGridLayout()
        grid.setContentsMargins(8, 2, 8, 6)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        # 标签列不伸缩、控件列平均伸缩：CPU线程/API Key 不再独占宽度，
        # 右侧 KV 缓存 V(-ctv) 等控件同样获得均等宽度。
        for _c in (0, 2, 4, 6):
            grid.setColumnStretch(_c, 0)
        for _c in (1, 3, 5, 7):
            grid.setColumnStretch(_c, 1)

        # ---- 第 0 行：CPU线程 / 闪存注意力 / KV缓存K(-ctk) V(-ctv) 同一行 ----
        grid.addWidget(QLabel("CPU线程:"), 0, 0)
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(-1, 256)
        self.spin_threads.setValue(-1)
        self.spin_threads.setSpecialValueText("-1 = 自动")
        self.spin_threads.setToolTip("用于计算的 CPU 线程数（-t）。\n-1 = 自动（使用全部逻辑核心）。")
        grid.addWidget(self.spin_threads, 0, 1)

        grid.addWidget(QLabel("闪存注意力:"), 0, 2)
        self.combo_fa = QComboBox()
        self.combo_fa.addItems(["on", "off", "auto"])
        self.combo_fa.setToolTip("Flash Attention 闪存注意力（-fa）。\non = 开启，省显存且更快（N 卡 / 新架构推荐）；\noff = 关闭，兼容性更好。")
        grid.addWidget(self.combo_fa, 0, 3)

        # ---- A1: KV 缓存 K/V 同一行，标签直接标明 -ctk / -ctv（功能 2）----
        grid.addWidget(QLabel("KV缓存K(-ctk):"), 0, 4)
        self.combo_kvc_k = QComboBox()
        self.combo_kvc_k.addItems(KV_CACHE_TYPES)
        self.combo_kvc_k.setCurrentText("f16")
        self.combo_kvc_k.setToolTip(
            "KV 缓存 K（Key）部分的量化类型，对应参数 -ctk，可与 V 独立设置。\n"
            "f16 = 默认质量好；q8_0/q4_0 = 更省显存但精度略降；f32 = 最占显存。")
        grid.addWidget(self.combo_kvc_k, 0, 5)
        grid.addWidget(QLabel("V(-ctv):"), 0, 6)
        self.combo_kvc_v = QComboBox()
        self.combo_kvc_v.addItems(KV_CACHE_TYPES)
        self.combo_kvc_v.setCurrentText("f16")
        self.combo_kvc_v.setToolTip(
            "KV 缓存 V（Value）部分的量化类型，对应参数 -ctv，可与 K 独立设置。\n"
            "K/V 可分别选不同精度；常见做法：K 用 q8_0、V 用 f16，兼顾精度与显存。")
        grid.addWidget(self.combo_kvc_v, 0, 7)

        # ---- 功能 6/7：连续批处理 / mlock / mmap / MTP + MTP 说明压缩到同一行 ----
        self.check_cont = QCheckBox("连续批处理")
        self.check_cont.setChecked(True)
        self.check_cont.setToolTip(
            "连续批处理（--cont-batching）：\n"
            "多个客户端并发请求时，新请求可以在解码过程中随时插入当前批次，"
            "不必等整批全部生成完才处理下一个，显著提升总吞吐量、降低等待。\n"
            "多客户端场景推荐开启；单客户端使用时无影响。")
        self.check_mlock = QCheckBox("mlock 锁定内存")
        self.check_mlock.setToolTip("--mlock：把模型锁定在内存中，防止被系统换出到磁盘。\n占内存更多，但推理更稳定。")
        self.check_mmap = QCheckBox("禁用 mmap")
        self.check_mmap.setToolTip("--no-mmap：关闭内存映射加载。\n加载更慢但内存占用更可控，个别磁盘/内存环境可改善稳定性。")
        self.check_mtp = QCheckBox("启用 MTP")
        self.check_mtp.setToolTip(
            "MTP（Multi-Token Prediction）：让模型自带的 MTP 头参与投机解码，"
            "可显著提升生成速度（对应 --spec-type draft-mtp）。\n"
            "仅当所选模型的 GGUF 内含 MTP 张量时可用；选择模型后会自动检测，\n"
            "不支持的模型该选项会被自动禁用。")
        self.label_mtp_status = QLabel("")
        self.label_mtp_status.setStyleSheet("color: #8fd0ff;")
        self.label_mtp_status.setToolTip("MTP 检测结果（扫描模型 GGUF 张量名）：绿色=可启用，橙色=不支持/无法检测")
        grid.addWidget(self.check_cont, 1, 0, 1, 2)
        grid.addWidget(self.check_mlock, 1, 2)
        grid.addWidget(self.check_mmap, 1, 3)
        grid.addWidget(self.check_mtp, 1, 4)
        grid.addWidget(self.label_mtp_status, 1, 5, 1, 3)

        # ---- 第 2 行：API Key / 超时 / 自动打开浏览器（压缩高级区，功能不变）----
        grid.addWidget(QLabel("API Key:"), 2, 0)
        self.edit_apikey = QLineEdit()
        self.edit_apikey.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_apikey.setToolTip("API 密钥（--api-key）。\n设置后客户端调用接口必须携带此 Key，否则会被拒绝。\n留空 = 不设密钥，任何人都能访问。")
        grid.addWidget(self.edit_apikey, 2, 1)
        grid.addWidget(QLabel("超时(秒):"), 2, 2)
        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(30, 86400)
        self.spin_timeout.setValue(3600)
        self.spin_timeout.setToolTip("服务读写超时（--timeout）。\n单个请求超过该秒数会被强制断开，默认 3600。")
        grid.addWidget(self.spin_timeout, 2, 3)
        self.check_browser = QCheckBox("启动成功后自动打开浏览器")
        self.check_browser.setChecked(True)
        self.check_browser.setToolTip("服务就绪后自动用默认浏览器打开 Web 界面。")
        grid.addWidget(self.check_browser, 2, 4, 1, 4)

        # ---- A4: 批大小 / 并行slots → 「生成参数」分组 ----
        self._gen_grid.addWidget(QLabel("批大小:"), 1, 0)
        self.spin_batch = QSpinBox()
        self.spin_batch.setRange(1, 16384)
        self.spin_batch.setValue(2048)
        self.spin_batch.setToolTip("逻辑批大小（-b），影响 prompt 处理速度。默认 2048 即可。")
        self._gen_grid.addWidget(self.spin_batch, 1, 1)

        self._gen_grid.addWidget(QLabel("并行slots:"), 1, 2)
        self.spin_slots = QSpinBox()
        self.spin_slots.setRange(-1, 64)
        self.spin_slots.setValue(-1)
        self.spin_slots.setSpecialValueText("-1 = 自动")
        self.spin_slots.setToolTip("同时处理的并发请求数（-np）。\n多个客户端同时使用时建议 ≥2；每个 slot 会额外占用上下文内存。\n-1 = 自动。")
        self._gen_grid.addWidget(self.spin_slots, 1, 3)

        # ---- A4: 温度 / Top-P / Top-K → 「生成参数」分组 ----
        self._gen_grid.addWidget(QLabel("温度:"), 2, 0)
        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(0.0, 2.0)
        self.spin_temp.setSingleStep(0.05)
        self.spin_temp.setValue(0.8)
        self.spin_temp.setToolTip("温度（--temp）：控制随机性/创造力。\n越低越保守严谨（0 = 每次都选最可能的词，趋于复读）；\n越高越发散创意（可能胡言乱语）。\n建议 0.3~1.2。")
        self._gen_grid.addWidget(self.spin_temp, 2, 1)

        self._gen_grid.addWidget(QLabel("Top-P:"), 2, 2)
        self.spin_topp = QDoubleSpinBox()
        self.spin_topp.setRange(0.0, 1.0)
        self.spin_topp.setSingleStep(0.05)
        self.spin_topp.setValue(0.95)
        self.spin_topp.setToolTip("核采样（--top-p）：只从累计概率达到该值的候选词中选。\n0.95 = 默认；1.0 = 关闭；越小越保守。")
        self._gen_grid.addWidget(self.spin_topp, 2, 3)

        self._gen_grid.addWidget(QLabel("Top-K:"), 2, 4)
        self.spin_topk = QSpinBox()
        self.spin_topk.setRange(0, 200)
        self.spin_topk.setValue(40)
        self.spin_topk.setSpecialValueText("0 = 默认")
        self.spin_topk.setToolTip("（--top-k）：只从概率最高的前 K 个候选词中选。\n40 = 默认；0 = 关闭；越小越保守。")
        self._gen_grid.addWidget(self.spin_topk, 2, 5)

        # ---- A4: 重复惩罚 → 「生成参数」分组 ----
        self._gen_grid.addWidget(QLabel("重复惩罚:"), 3, 0)
        self.spin_rp = QDoubleSpinBox()
        self.spin_rp.setRange(0.0, 2.0)
        self.spin_rp.setSingleStep(0.1)
        self.spin_rp.setValue(1.0)
        self.spin_rp.setSpecialValueText("0 = 默认")
        self.spin_rp.setToolTip("重复惩罚（--repeat-penalty）。\n>1 抑制重复输出，有助于缓解「无限复读/幻觉循环」；\n1.0 = 关闭；建议 1.0~1.3。")
        self._gen_grid.addWidget(self.spin_rp, 3, 1)

        # ---- GPU层数(-ngl)：从基本参数移入「生成参数」分组（与重复惩罚同行）----
        self._gen_grid.addWidget(QLabel("GPU层数:"), 3, 2)
        self.combo_ngl = QComboBox()
        self.combo_ngl.setEditable(True)
        self.combo_ngl.addItems(["all", "auto", "0", "1", "10", "20", "32", "40", "64"])
        self.combo_ngl.setToolTip(
            "卸载到 GPU 显存中的层数（-ngl）。\n"
            "all = 尽可能全部放入显存；auto = 自动判断；0 = 纯 CPU 运行；也可填具体层数。\n"
            "与多显卡部署不冲突：ngl 决定总共卸载多少层，\n"
            "-ts/-sm（多显卡区）再决定这些层如何在多张卡之间分配。")
        self._gen_grid.addWidget(self.combo_ngl, 3, 3)

        # ---- A4: 采样预设 → 「生成参数」分组 ----
        self._gen_grid.addWidget(QLabel("采样预设:"), 1, 4)
        self.combo_sampling = QComboBox()
        for name, _v in SAMPLING_PRESETS:
            self.combo_sampling.addItem(name)
        self.combo_sampling.setToolTip(
            "一键应用一组采样参数（温度/Top-P/Top-K/重复惩罚）。\n"
            "严谨=低温度适合写代码/翻译；均衡=日常对话；创意=高温度适合写作/脑洞。\n"
            "手动修改任一采样参数后会自动回到「自定义」。")
        self._gen_grid.addWidget(self.combo_sampling, 1, 5)

        lay.addLayout(grid)

    def _build_gpu(self, lay):
        """多显卡设置面板（功能 3）。"""
        row0 = QHBoxLayout()
        self.btn_detect_gpus = QPushButton("检测 GPU")
        self.btn_detect_gpus.setToolTip(
            "运行 llama-server --list-devices 列出本机可用设备（CUDA0/CUDA1…），\n"
            "勾选要参与计算的显卡；只勾一张 = 指定只用该卡，多张 = 拆分到多卡。")
        row0.addWidget(self.btn_detect_gpus)
        self.label_gpus = QLabel("尚未检测")
        self.label_gpus.setStyleSheet("color: #8fd0ff;")
        row0.addWidget(self.label_gpus, 1)
        lay.addLayout(row0)

        # GPU 复选框容器（检测后动态填充）
        self.gpu_panel = QWidget()
        self.gpu_layout = QHBoxLayout(self.gpu_panel)
        self.gpu_layout.setContentsMargins(4, 2, 4, 2)
        self.gpu_checks = []   # [QCheckBox]，data = 设备名（如 CUDA0）
        lay.addWidget(self.gpu_panel)

        # ---- A5: 每卡权重分配（检测后动态生成；row 0 为自动分配按钮）----
        self.gpu_ratio_panel = QWidget()
        self.gpu_ratio_layout = QGridLayout(self.gpu_ratio_panel)
        self.gpu_ratio_layout.setHorizontalSpacing(8)
        self.gpu_ratio_layout.setVerticalSpacing(6)
        self.gpu_ratio_spins = []     # [QDoubleSpinBox]，每张检测到的卡一个
        self._gpu_ratio_labels = []   # 对应的 QLabel（重建时清理用）
        self.btn_auto_split = QPushButton("按显存自动分配")
        self.btn_auto_split.setEnabled(False)
        self.btn_auto_split.setToolTip(
            "检测 GPU（≥2 张且可用 nvidia-smi）后可用：\n"
            "查询每张卡总显存，按比例换算成整数权重填入 tensor-split。")
        self.btn_auto_split.clicked.connect(self._auto_split_by_vram)
        self.gpu_ratio_layout.addWidget(self.btn_auto_split, 0, 0)
        self.gpu_ratio_panel.setVisible(False)
        lay.addWidget(self.gpu_ratio_panel)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel("拆分模式:"), 0, 0)
        self.combo_split_mode = QComboBox()
        for m in SPLIT_MODES:
            self.combo_split_mode.addItem(m)
        self.combo_split_mode.setCurrentText("layer")
        self.combo_split_mode.setToolTip(
            "多卡拆分方式（-sm）：\n"
            "· layer = 按层切分（默认，KV 也跨卡）；\n"
            "· row = 按行并行切分权重；\n"
            "· tensor = 张量级切分（实验性）；\n"
            "· none = 只用单卡。")
        grid.addWidget(self.combo_split_mode, 0, 1)

        grid.addWidget(QLabel("tensor-split:"), 0, 2)
        self.edit_tensor_split = QLineEdit()
        self.edit_tensor_split.setPlaceholderText("如 3,1（留空=均分）")
        self.edit_tensor_split.setToolTip(
            "各 GPU 的算力权重比例（-ts），逗号分隔，例如两张卡写 3,1。\n"
            "显存差异大时建议按显存比例填写；留空 = llama.cpp 自动均分。")
        grid.addWidget(self.edit_tensor_split, 0, 3)

        grid.addWidget(QLabel("主GPU:"), 0, 4)
        self.spin_main_gpu = QSpinBox()
        self.spin_main_gpu.setRange(0, 63)
        self.spin_main_gpu.setValue(0)
        self.spin_main_gpu.setToolTip(
            "主 GPU 索引（-mg）：中间结果/KV 的归属卡，一般保持 0。")
        grid.addWidget(self.spin_main_gpu, 0, 5)

        tip = QLabel(
            "提示：勾选 ≥2 张显卡后才会添加 -dev/-sm/-ts 参数；单卡/不勾选 = 行为与原来一致（自动选卡）。\n"
            "GPU层数(-ngl)与多显卡部署不冲突：-ngl 决定总共卸载多少层到显存，\n"
            "-ts(tensor-split)/-sm(拆分模式) 再决定这些层如何在多张卡之间分配；-ngl all = 全部放卡上。")
        tip.setStyleSheet("color: #888;")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addLayout(grid)

    def _rebuild_gpu_checks(self, devices):
        """按检测到的设备列表重建复选框，并恢复已保存的勾选。"""
        saved = (self.cfg.data.get("server", {}) or {}).get("devices") or []
        for c in self.gpu_checks:
            self.gpu_layout.removeWidget(c)
            c.deleteLater()
        self.gpu_checks = []
        for dev in devices:
            name, desc = dev
            cb = QCheckBox(f"{name}  {desc}")
            # 注意：PyQt6 的 QWidget 没有 setData()，用动态属性保存设备名
            cb.setProperty("dev_name", name)
            if name in saved:
                cb.setChecked(True)
            cb.toggled.connect(self.update_preview)
            self.gpu_layout.addWidget(cb)
            self.gpu_checks.append(cb)
        self.gpu_panel.setVisible(bool(devices))

        # ---- A5: 重建每卡权重行（每张卡一行，默认 1）----
        self._gpu_ratio_syncing = True   # 程序化回填期间禁止回写 tensor-split
        try:
            for lab in getattr(self, "_gpu_ratio_labels", []) or []:
                self.gpu_ratio_layout.removeWidget(lab)
                lab.deleteLater()
            for sp in getattr(self, "gpu_ratio_spins", []) or []:
                self.gpu_ratio_layout.removeWidget(sp)
                sp.deleteLater()
            self._gpu_ratio_labels = []
            self.gpu_ratio_spins = []
            row = 1   # row 0 是「按显存自动分配」按钮
            for i, dev in enumerate(devices):
                name, desc = dev
                short = (desc or "").split(" (")[0].strip()
                lab = QLabel(f"GPU{i} {short}")
                self.gpu_ratio_layout.addWidget(lab, row, 0)
                sp = QDoubleSpinBox()
                sp.setRange(0.0, 16.0)
                sp.setSingleStep(1.0)
                sp.setValue(1.0)
                sp.setToolTip(f"{name}（{short}）在 tensor-split 中的权重；\n修改后自动同步到「tensor-split」输入框。")
                self.gpu_ratio_layout.addWidget(sp, row, 1)
                self._gpu_ratio_labels.append(lab)
                self.gpu_ratio_spins.append(sp)
                row += 1
            # 若已有 tensor-split 文本且数量匹配，回填到 spinbox（保持显示一致）
            txt = getattr(self, "edit_tensor_split", None)
            if txt is not None:
                parts = [p for p in str(txt.text()).replace("，", ",").split(",")
                         if p.strip()]
                if len(parts) == len(self.gpu_ratio_spins):
                    try:
                        vals = [float(p) for p in parts]
                        if all(0.0 <= v <= 16.0 for v in vals):
                            for sp, v in zip(self.gpu_ratio_spins, vals):
                                sp.setValue(v)
                    except ValueError:
                        pass
            # 回填完成后再连接信号，避免重建时覆盖已保存的 tensor-split
            for sp in self.gpu_ratio_spins:
                sp.valueChanged.connect(self._on_gpu_ratio_changed)
        finally:
            self._gpu_ratio_syncing = False

        # A5c: 按钮状态 —— 需 ≥2 张卡且 nvidia-smi 可用，否则置灰并提示原因
        import shutil as _shutil
        has_smi = _shutil.which("nvidia-smi") is not None
        if len(devices) >= 2 and has_smi:
            self.btn_auto_split.setEnabled(True)
            self.btn_auto_split.setToolTip(
                "用 nvidia-smi 查询每张卡总显存，按比例换算成整数权重\n"
                "（如 24G+8G → 3,1），并同步填入 tensor-split 输入框。")
        else:
            self.btn_auto_split.setEnabled(False)
            if not devices:
                tip = "尚未检测到 GPU；点「检测 GPU」后可用"
            elif len(devices) == 1:
                tip = "只检测到一张卡，无需分配（单卡不使用 tensor-split）"
            else:
                tip = "未找到 nvidia-smi，无法查询显存，请手动填写 tensor-split"
            self.btn_auto_split.setToolTip(tip)
        self.gpu_ratio_panel.setVisible(bool(devices))

    def detect_gpus(self):
        """调用 llama-server --list-devices 检测本机 GPU（后台线程）。"""
        import re as _re
        exe = self._launcher_exe()

        def work():
            devs, err = [], None
            if not os.path.isfile(exe):
                err = "未找到 llama-server.exe，无法检测设备"
            else:
                import subprocess
                proc = None
                try:
                    proc = subprocess.Popen(
                        [exe, "--list-devices"], stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                        errors="replace", creationflags=CREATE_NO_WINDOW)
                    self._gpu_probe_pid = proc.pid
                    try:
                        out, _ = proc.communicate(timeout=30)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        out = ""
                    for line in (out or "").splitlines():
                        s = line.strip()
                        low = s.lower()
                        if low.startswith(("available", "no ", "error")):
                            continue
                        m = _re.match(r'([A-Za-z][\w]*\d*):\s*(.+)$', s)
                        if m:
                            devs.append((m.group(1), m.group(2)))
                except Exception as e:
                    err = str(e)
                finally:
                    self._gpu_probe_pid = None
            self._gpu_result = (devs, err)
            try:
                self.gpu_detected.emit()
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_gpus_detected(self):
        # 注意：Qt 槽函数内异常不得外抛（会导致未定义行为），必须捕获
        try:
            devs, err = getattr(self, "_gpu_result", ([], None))
            if err:
                self.label_gpus.setText(f"检测失败：{err}")
                return
            if not devs:
                self.label_gpus.setText("未检测到可用 GPU 设备")
                self._rebuild_gpu_checks([])
                return
            self.label_gpus.setText(
                    "、".join(f"{n} {d.split(' (')[0]}" for n, d in devs))
            self._rebuild_gpu_checks(devs)
        except Exception as e:
            try:
                self.label_gpus.setText(f"GPU 处理出错：{e}")
            except RuntimeError:
                pass

    # ---------------------------------------------------------- A5: 多显卡权重分配
    def _on_gpu_ratio_changed(self):
        """任一权重 spinbox 变化 → 把 'w0,w1,...' 写回 tensor-split（手动覆盖仍可直接编辑该框）。"""
        if getattr(self, "_gpu_ratio_syncing", False):
            return
        spins = getattr(self, "gpu_ratio_spins", None) or []
        if not spins or not hasattr(self, "edit_tensor_split"):
            return
        parts = []
        for sp in spins:
            v = float(sp.value())
            parts.append(str(int(round(v))) if abs(v - round(v)) < 1e-9 else f"{v:g}")
        self.edit_tensor_split.setText(",".join(parts))

    def _auto_split_by_vram(self):
        """用 nvidia-smi 查询每张卡总显存（后台线程），按比例换算成整数权重填入。"""
        import subprocess

        def work():
            totals = []
            try:
                r = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.total",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10,
                    creationflags=CREATE_NO_WINDOW)
                if r.returncode == 0:
                    for line in (r.stdout or "").splitlines():
                        s = line.strip()
                        if s.isdigit():
                            totals.append(int(s))
            except Exception:
                totals = []
            weights = self._vram_to_weights(totals)
            try:
                self.vram_weights.emit(weights)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _vram_to_weights(totals):
        """显存(MiB)列表 → 整数权重比例（以最小卡为基准取整，如 24G+8G → [3, 1]）。"""
        totals = [int(t) for t in totals if int(t) > 0]
        if not totals:
            return []
        m = min(totals)
        weights = [max(1, int(round(t / m))) for t in totals]
        from math import gcd
        wg = 0
        for w in weights:
            wg = gcd(wg, w)
        if wg > 1:
            weights = [w // wg for w in weights]
        return weights

    def _on_vram_weights(self, weights):
        """nvidia-smi 查询完成 → 把整数权重填入各 spinbox（自动同步到 tensor-split）。"""
        try:
            spins = getattr(self, "gpu_ratio_spins", None) or []
            if not weights or len(weights) != len(spins):
                self.statusBar().showMessage(
                    "nvidia-smi 卡数与检测到的设备不一致，请手动填写 tensor-split", 5000)
                return
            for sp, w in zip(spins, weights):
                sp.setValue(float(w))   # 触发 _on_gpu_ratio_changed → 同步 edit_tensor_split
            self.statusBar().showMessage(
                f"已按显存分配: {','.join(str(int(round(w))) for w in weights)}", 4000)
        except Exception as e:
            try:
                self.statusBar().showMessage(f"自动分配失败: {e}", 5000)
            except RuntimeError:
                pass

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
        self.btn_validate_bat.clicked.connect(self.open_bat_validator)   # C3
        self.btn_export_file.clicked.connect(self.export_bat)            # 7 号位：导出启动文件
        # 主题按钮改为弹出菜单（见 _build_ui 的 setMenu），无需 clicked 连接
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
        self.act_export_bat.triggered.connect(self.export_bat)
        self.act_export_preview_bat.triggered.connect(self.export_preview_bat)
        self.act_stats.triggered.connect(self.show_stats)
        self.act_about.triggered.connect(self.show_about)
        self.act_docs.triggered.connect(self.open_docs)
        self.act_update_now.triggered.connect(self._goto_updater)

        # 多显卡 / MTP / 排序（功能 1/3/4）+ A5 显存权重
        self.gpu_detected.connect(self._on_gpus_detected)
        self.mtp_detected.connect(self._on_mtp_detected)
        self.btn_detect_gpus.clicked.connect(self.detect_gpus)
        self.vram_weights.connect(self._on_vram_weights)
        self.combo_sort.currentIndexChanged.connect(self._on_sort_changed)
        self.download_tab.models_changed.connect(
            lambda: self.refresh_models(keep_selection=True))

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
            self.spin_batch, self.spin_slots, self.combo_fa,
            self.combo_kvc_k, self.combo_kvc_v,
            self.check_cont, self.spin_temp, self.spin_topp, self.spin_topk,
            self.spin_rp, self.edit_apikey, self.check_mlock, self.check_mmap,
            self.check_browser, self.spin_timeout, self.edit_host, self.spin_port,
            self.combo_split_mode, self.edit_tensor_split, self.spin_main_gpu,
            self.check_mtp,
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
            # KV 缓存 K / V 独立类型（功能 2）
            "kv_cache_k": self.combo_kvc_k.currentText(),
            "kv_cache_v": self.combo_kvc_v.currentText(),
            # 多显卡（功能 3）
            "devices": [c.property("dev_name") for c in getattr(self, "gpu_checks", [])
                        if c.isChecked() and c.property("dev_name")],
            "split_mode": self.combo_split_mode.currentText(),
            "tensor_split": self.edit_tensor_split.text().strip(),
            "main_gpu": self.spin_main_gpu.value(),
            # MTP（功能 4）
            "mtp": self.check_mtp.isChecked(),
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
        self.edit_launcher.setText(d.get("launcher_exe", ""))
        self.edit_data_dir.setText(d.get("data_dir", ""))
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
        # KV K/V 独立类型（兼容旧配置 kv_cache_type）
        legacy_kvc = s.get("kv_cache_type") or ""
        k = str(s.get("kv_cache_k") or legacy_kvc or "f16")
        v = str(s.get("kv_cache_v") or legacy_kvc or "f16")
        self.combo_kvc_k.setCurrentText(k if k in KV_CACHE_TYPES else "f16")
        self.combo_kvc_v.setCurrentText(v if v in KV_CACHE_TYPES else "f16")
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

        # 多显卡 / MTP（功能 3/4）
        sm = str(s.get("split_mode") or "layer")
        if sm in SPLIT_MODES:
            self.combo_split_mode.setCurrentText(sm)
        self.edit_tensor_split.setText(str(s.get("tensor_split") or ""))
        try:
            self.spin_main_gpu.setValue(int(s.get("main_gpu", 0)))
        except (TypeError, ValueError):
            pass
        self.check_mtp.setChecked(bool(s.get("mtp", False)))

        # 模型排序（功能 1）
        sort_mode = d.get("model_sort", "dir_name")
        idx = {"dir_name": 0, "size_desc": 1, "name": 2}.get(sort_mode, 0)
        self.combo_sort.setCurrentIndex(idx)

        # HF 下载目录回显（功能 5）：有自定义则回显，否则默认跟随主页「模型目录」
        if d.get("hf_download_dir"):
            self.download_tab.edit_save_dir.setText(d["hf_download_dir"])
            self.download_tab._auto_save_dir = False
        else:
            self.download_tab.sync_default_dir()
        self._loading = False
        self._sync_preset_combo()

    def save_config(self):
        d = self.cfg.data
        d["llama_dir"] = self.edit_dir.text().strip()
        d["launcher_exe"] = self.edit_launcher.text().strip()
        new_data_dir = self.edit_data_dir.text().strip()
        if new_data_dir != (d.get("data_dir", "") or ""):
            self.cfg.redirect_data_dir(new_data_dir)
            d = self.cfg.data
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
            self.cfg.apply_loaded(loaded)   # 含旧键迁移（kv_cache_type → k/v）
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入失败: {e}")
            return
        self._apply_config()
        self._apply_theme()
        self.refresh_models(keep_selection=True)
        self.statusBar().showMessage(f"配置已导入: {path}", 5000)
        self._on_server_log(f"[配置] 已从 {path} 导入")

    # ---------------------------------------------------------- 一键启动导出
    def export_bat(self):
        """将当前配置导出为可双击启动的 .bat，并在桌面创建带软件图标的快捷方式。"""
        model = self.combo_model.currentData()
        if not model:
            QMessageBox.information(self, "提示", "请先选择模型")
            return
        llama_dir = self.edit_dir.text().strip()
        launcher_exe = self._launcher_exe()
        if not os.path.isfile(launcher_exe):
            QMessageBox.warning(self, "提示",
                                "未找到启动器可执行文件（llama-server.exe）。\n"
                                "请检查模型目录，或在「启动器文件」中用文件选择器指定。")
            return
        self.save_config()
        s = self._gather_server_cfg()
        mmproj = self.combo_mmproj.currentData()
        try:
            content = build_bat_content(model, mmproj, s, llama_dir, launcher_exe=launcher_exe)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"生成批处理失败: {e}")
            return
        default = os.path.join(self.base_dir, f"{model_alias(model)}-一键启动.bat")
        path, _ = QFileDialog.getSaveFileName(self, "导出一键启动批处理", default, "批处理文件 (*.bat)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write(content)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {e}")
            return
        self.statusBar().showMessage(f"已导出: {path}", 5000)
        self._on_server_log(f"[导出] 已生成一键启动脚本 {path}")
        self._create_desktop_shortcut(path)

    def export_preview_bat(self):
        """把「命令预览」页的完整命令行原样导出为 .bat，自选存储路径（功能 6）。"""
        preview = (self.preview_view.toPlainText() or "").strip()
        if not preview:
            QMessageBox.information(self, "提示", "命令预览为空：请先选择模型并配置参数")
            return
        alias = model_alias(self.combo_model.currentData() or "") or "llama-server"
        default = os.path.join(
            self._data_dir(), f"{alias}-命令预览.bat".replace("\\", "_"))
        path, _ = QFileDialog.getSaveFileName(
            self, "导出命令预览为 .bat（可选择存储路径）", default,
            "批处理文件 (*.bat);;所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write(build_preview_bat(preview, title=f"LLama Server - {alias}"))
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {e}")
            return
        self.statusBar().showMessage(f"命令预览已导出: {path}", 5000)
        self._on_server_log(f"[导出] 命令预览已保存为 {path}")

    def _create_desktop_shortcut(self, bat_path):
        """用 WScript.Shell 在桌面创建指向 bat 的快捷方式，图标取程序图标。"""
        desktop = self._desktop_dir()
        if not desktop:
            QMessageBox.information(self, "提示", "导出成功，但无法定位桌面目录，跳过快捷方式")
            return
        import subprocess
        import base64
        name = os.path.splitext(os.path.basename(bat_path))[0]
        lnk_path = os.path.join(desktop, name + ".lnk")
        # 直接用程序自带图标作为快捷方式图标，不再往导出目录里写额外的 .ico 文件
        icon_path = self._shortcut_icon()

        def _q(v):
            return str(v).replace("'", "''")

        script = [
            "$ws = New-Object -ComObject WScript.Shell",
            f"$s = $ws.CreateShortcut('{_q(lnk_path)}')",
            f"$s.TargetPath = '{_q(bat_path)}'",
            f"$s.WorkingDirectory = '{_q(os.path.dirname(bat_path))}'",
            f"$s.IconLocation = '{_q(icon_path)},0'" if icon_path else "",
            "$s.Description = 'LLama 启动器一键启动'",
            "$s.Save()",
        ]
        script = [line for line in script if line]
        try:
            encoded = base64.b64encode("\n".join(script).encode("utf-16-le")).decode()
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                check=True, capture_output=True, timeout=60)
        except Exception as e:
            QMessageBox.warning(self, "提示", f"创建桌面快捷方式失败: {e}")
            return
        QMessageBox.information(
            self, "完成",
            f"已导出：{bat_path}\n\n已在桌面创建快捷方式：\n{lnk_path}")
        self.statusBar().showMessage(f"桌面快捷方式已创建: {lnk_path}", 6000)

    def _shortcut_icon(self):
        """快捷方式图标路径：优先使用启动器 exe 内嵌图标（不产生额外文件，且长期有效）。

        打包运行时直接用 sys.executable；源码运行时用 assets/icon.ico；
        都没有时才在系统临时目录生成 ico 回退，绝不写入用户的导出目录。
        """
        if getattr(sys, "frozen", False):
            exe = sys.executable
            if exe and os.path.isfile(exe):
                return exe
        src = os.path.join(self.resource_dir, "assets", "icon.ico")
        if os.path.isfile(src):
            return src
        try:
            import tempfile
            dst = os.path.join(tempfile.gettempdir(), "llama_launcher_icon.ico")
            if not os.path.isfile(dst):
                pm = self.windowIcon().pixmap(64, 64)
                if pm.isNull():
                    return ""
                pm.save(dst, "ICO")
            return dst if os.path.isfile(dst) else ""
        except Exception:
            return ""

    def _desktop_dir(self):
        """返回真实桌面目录（兼容 OneDrive/系统盘），找不到返回 None。"""
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if os.path.isdir(desktop):
            return desktop
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 16, None, 0, buf) == 0:
                d = buf.value
                if os.path.isdir(d):
                    return d
        except Exception:
            pass
        return None

    # ---------------------------------------------------------- 模型相关
    def _on_sort_changed(self, _idx):
        """切换排序方式（功能 1）：保存设置并对当前列表重新排序。"""
        if self._loading or not hasattr(self, "combo_model"):
            return
        mode = ("dir_name", "size_desc", "name")[self.combo_sort.currentIndex()]
        self.cfg.data["model_sort"] = mode
        keep = self.combo_model.currentData()
        self._rebuild_model_combos(keep)

    def refresh_models(self, keep_selection=False):
        llama_dir = self.edit_dir.text().strip()
        if not llama_dir or not os.path.isdir(llama_dir):
            self._models, self._mmprojs = [], []
            self._scan_error = "模型目录无效"
            self._rebuild_model_combos(None)
            return

        self._scan_gen = getattr(self, "_scan_gen", 0) + 1
        gen = self._scan_gen
        self._pending_keep = keep_selection
        self._scan_error = None

        def work():
            ms, mps = [], []
            err = None
            try:
                ms, mps = scan_models(llama_dir)
            except Exception as e:
                err = str(e)
            if gen != getattr(self, "_scan_gen", 0):
                return  # 过期扫描，丢弃
            if err is not None:
                self._scan_error = err
            else:
                self._models, self._mmprojs = ms, mps
            self.model_scan_done.emit()

        threading.Thread(target=work, daemon=True).start()
        self.statusBar().showMessage("正在扫描模型目录…", 2000)

    def _on_model_scan_done(self):
        keep_path = self.cfg.data.get("model", "") if self._pending_keep else None
        self._pending_keep = False
        err = getattr(self, "_scan_error", None)
        self._scan_error = None
        self._rebuild_model_combos(keep_path)
        if err:
            self.statusBar().showMessage(f"扫描出错: {err}", 5000)
            self._log_file(f"[扫描] 出错: {err}")
        else:
            self.statusBar().showMessage(f"发现 {len(self._models)} 个模型, {len(self._mmprojs)} 个视觉模型", 4000)
        self.update_preview()

    def _rebuild_model_combos(self, keep_path):
        self._loading = True
        # 排序（功能 1）：目录+文件名 / 大小降序 / 名称
        sort_models(self._models, self.cfg.data.get("model_sort", "dir_name"))
        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        for m in self._models:
            # 多文件分片模型（功能 8）：只显示第一个启动文件，大小显示整组总和
            size = getattr(m, "group_size", None) or m.size
            label = f"{m.name}  ({human_size(size)})"
            if getattr(m, "shard_idx", None):
                label += f"　[多文件 {m.shard_total} 片]"
            self.combo_model.addItem(label, m.path)
        self.combo_model.blockSignals(False)
        # 规范化路径匹配（兼容配置里 / 与 \ 混用），并保留下载页加入的外部模型
        norm = {os.path.normcase(os.path.abspath(m.path)): i
                for i, m in enumerate(self._models)}
        target = None
        if keep_path:
            target = norm.get(os.path.normcase(os.path.abspath(keep_path)))
        if target is not None:
            self.combo_model.setCurrentIndex(target)
        elif keep_path and os.path.isfile(keep_path):
            try:
                size = os.path.getsize(keep_path)
            except OSError:
                size = 0
            self.combo_model.addItem(
                f"{os.path.basename(keep_path)}  ({human_size(size)})　[已下载]",
                keep_path)
            self.combo_model.setCurrentIndex(self.combo_model.count() - 1)
        elif self._models:
            self.combo_model.setCurrentIndex(0)
        self._loading = False
        self._on_model_changed()

    def select_model_path(self, path):
        """供下载页调用：把已下载的模型设为主模型（不在扫描列表时临时加入下拉框）。"""
        if not path:
            return
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            QMessageBox.information(self, "提示", f"模型文件不存在：\n{path}")
            return
        for i in range(self.combo_model.count()):
            data = self.combo_model.itemData(i)
            if data and os.path.abspath(data) == path:
                self.combo_model.setCurrentIndex(i)
                self.statusBar().showMessage(f"已切换主模型：{os.path.basename(path)}", 5000)
                return
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        label = f"{os.path.basename(path)}  ({human_size(size)})　[已下载]"
        self._loading = True
        self.combo_model.addItem(label, path)
        self._loading = False
        self.combo_model.setCurrentIndex(self.combo_model.count() - 1)
        self.statusBar().showMessage(f"已切换主模型：{os.path.basename(path)}", 5000)

    def _on_model_changed(self):
        path = self.combo_model.currentData()
        # A6: 显示当前选中模型的完整绝对路径（未选时显示「未选择模型」）
        if hasattr(self, "label_model_path"):
            self.label_model_path.setText(os.path.abspath(path) if path else "未选择模型")
        if not path:
            self._clear_info()
            self._update_mmproj_warn()
            return
        if not self._loading:
            self.cfg.data["model"] = path
        model = next((m for m in self._models if m.path == path), None)
        # 功能 7：只显示与主模型同一目录下的视觉模型，保证配套一致
        same_dir = [m for m in self._mmprojs if model is not None and m.dir == model.dir]
        auto = find_mmproj_for(model, same_dir)
        dup = {n for n, c in Counter(m.name for m in same_dir).items() if c > 1}
        self._loading = True
        self.combo_mmproj.blockSignals(True)
        self.combo_mmproj.clear()
        self.combo_mmproj.addItem("（不使用）", None)
        sel = 0
        for m in same_dir:
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
        # 功能 4：后台检测该模型是否含 MTP 张量
        self._detect_mtp_async(path)

    # ---------------------------------------------------------- MTP（功能 4）
    def _mtp_status_label(self, text, color="#8fd0ff"):
        """MTP 状态提示：颜色标识 + 下划线（富文本），绿=可启用，橙=不支持/无法检测。"""
        if hasattr(self, "label_mtp_status"):
            self.label_mtp_status.setText(
                f'<span style="color:{color};"><u>{text}</u></span>')

    def _detect_mtp_async(self, path):
        """后台扫描 GGUF 张量名，检测 MTP 支持并更新开关状态。"""
        if not path or not hasattr(self, "check_mtp"):
            return
        if self._mtp_cache.get(path) is None:
            self._mtp_status_label("MTP 检测中…")

            def work():
                try:
                    ok, hits = detect_mtp(path)
                except Exception:
                    ok, hits = None, []
                self._mtp_cache[path] = (ok, hits)
                try:
                    self.mtp_detected.emit()
                except RuntimeError:
                    pass

            threading.Thread(target=work, daemon=True).start()
        else:
            self._apply_mtp_result(path)

    def _on_mtp_detected(self):
        try:
            path = self.combo_model.currentData()
            if path and path in self._mtp_cache:
                self._apply_mtp_result(path)
        except Exception:
            pass  # 槽函数内异常不外抛

    def _apply_mtp_result(self, path):
        ok, hits = self._mtp_cache.get(path, (None, []))
        if not hasattr(self, "check_mtp"):
            return
        if ok is None:
            # 无法检测：保持可用，允许用户手动决定
            self._mtp_status_label("MTP 无法检测（文件不可读），可手动勾选", "#ff9f6a")
            self.check_mtp.setEnabled(True)
            return
        if ok:
            # 支持 MTP：开放点选
            self._mtp_status_label(f"✔ 检测到 MTP（{len(hits)} 个特征），可启用", "#7dffa8")
            self.check_mtp.setEnabled(True)
        else:
            # 未检测到 MTP：给出提示但不强制禁用，避免误判导致支持 MTP 的模型无法启用
            self._mtp_status_label("未检测到 MTP 张量，如确认支持可手动勾选", "#ff9f6a")
            self._loading = True
            self.check_mtp.setChecked(False)
            self.check_mtp.setEnabled(True)
            self._loading = False

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
            args = build_args(model, self.combo_mmproj.currentData(), s, llama_dir,
                              launcher_exe=self._launcher_exe())
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
        launcher_exe = self._launcher_exe()
        if not os.path.isfile(launcher_exe):
            QMessageBox.warning(self, "提示",
                                "未找到启动器可执行文件（llama-server.exe）。\n"
                                "请检查模型目录，或在「启动器文件」中用文件选择器指定。")
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
            args = build_args(model, mmproj_path, s, llama_dir, launcher_exe=self._launcher_exe())
        except Exception as e:
            QMessageBox.critical(self, "错误", f"构建命令失败: {e}")
            return

        self._log_file(">>> " + build_command(args))
        ok = self.server.start(args, llama_dir, host, port)
        if ok:
            self._set_running_state(True)
            self.monitor.set_server(self.server.proc, self.server.url, os.path.basename(model))
            # 统计：一次启动计为一次「打开」（功能 9）
            self._running_model_name = os.path.basename(model)
            self._usage_pending = 0.0
            try:
                self._stats().record_open(self._running_model_name)
            except Exception:
                pass
            self.statusBar().showMessage("服务启动中…", 0)

    def stop_server(self):
        self.server.stop()
        self.monitor.set_server(None)
        self._set_running_state(False)
        self._flush_usage()

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
        self._flush_usage()
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

    def open_bat_validator(self):
        """C3: 打开启动文件校验报告对话框（bat_validator.ValidateBatDialog）。"""
        try:
            ValidateBatDialog(self).exec()
        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开校验器失败：{e}")

    # ------------------------------------------------------ Agent 工具
    def scan_tools(self):
        overrides = self.cfg.data.get("tools", {})
        llama_dir = self.edit_dir.text().strip()
        launcher_exe = self.edit_launcher.text().strip()

        def work():
            try:
                self._tools_found = tools_mod.scan_all(overrides, llama_dir, launcher_exe)
            except Exception:
                self._tools_found = {}
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
        d = QFileDialog.getExistingDirectory(self, "选择模型扫描目录", self.edit_dir.text() or os.path.expanduser("~"))
        if d:
            self.edit_dir.setText(d)
            self.cfg.data["llama_dir"] = d
            self.cfg.save()
            self.refresh_models()

    def _launcher_exe(self):
        """返回启动服务用的可执行文件；自定义项无效/空时回退 模型目录\\llama-server.exe。"""
        exe = self.edit_launcher.text().strip()
        if exe and os.path.isfile(exe):
            return exe
        return os.path.join(self.edit_dir.text().strip() or self.base_dir, "llama-server.exe")

    def _browse_launcher(self):
        start = os.path.join(self.edit_dir.text().strip() or self.base_dir, "llama-server.exe")
        path, _ = QFileDialog.getOpenFileName(self, "选择启动器可执行文件", start,
                                              "可执行文件 (*.exe);;所有文件 (*.*)")
        if path:
            self.edit_launcher.setText(path)
            self.cfg.data["launcher_exe"] = path
            self.cfg.save()
            self.update_preview()
            self.scan_tools()
            self.statusBar().showMessage(f"启动器文件: {path}", 4000)

    def _clear_launcher(self):
        self.edit_launcher.setText("")
        self.cfg.data["launcher_exe"] = ""
        self.cfg.save()
        self.update_preview()
        self.scan_tools()
        self.statusBar().showMessage("已恢复自动查找 llama-server.exe", 3000)

    def _data_dir(self):
        """返回数据存储目录（config.json/日志/缓存），空则程序目录。"""
        return self.cfg.ensure_data_dir()

    def _browse_data_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择数据存储目录", self._data_dir())
        if not d:
            return
        self.edit_data_dir.setText(d)
        if self.cfg.redirect_data_dir(d):
            self.statusBar().showMessage(f"数据目录已切换到: {d}", 5000)
            self._log_file(f"[配置] 数据目录切换到 {d}")
        else:
            self.statusBar().showMessage("数据目录切换失败", 4000)

    def _reset_data_dir(self):
        self.edit_data_dir.setText("")
        if self.cfg.redirect_data_dir(""):
            self.statusBar().showMessage("数据目录已恢复为程序所在目录", 4000)
            self._log_file("[配置] 数据目录恢复为程序目录")

    def _ensure_valid_llama_dir(self):
        """启动时校验模型目录；无效则弹窗让用户选择（浏览选择 / 使用默认上级目录）。"""
        llama_dir = self.edit_dir.text().strip()
        if llama_dir and os.path.isdir(llama_dir):
            return
        ret = QMessageBox.question(
            self, "模型目录无效",
            f"当前模型目录不存在或不可访问：\n{llama_dir or '（空）'}\n\n"
            "是否立即重新选择模型目录？\n"
            "（选「否」将使用启动器所在目录的上级目录）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            self._browse_dir()
        else:
            parent = os.path.dirname(os.path.abspath(self.base_dir))
            if os.path.isdir(parent):
                self.edit_dir.setText(parent)
                self.cfg.data["llama_dir"] = parent
                self.cfg.save()
                self.statusBar().showMessage(f"模型目录已设为: {parent}", 4000)

    def _on_llama_version(self, ver):
        base = f"LLama 启动器 v{__version__}"
        self.setWindowTitle(f"{base} · llama {ver}" if ver else base)

    def recheck_llama_version(self):
        """更新安装后重新检测本地 llama-server 版本，刷新标题栏。"""
        if getattr(self, "_llama_ver_worker", None) and self._llama_ver_worker.isRunning():
            return
        self._llama_ver_worker = _LlamaVersionWorker(self._launcher_exe(), self)
        self._llama_ver_worker.done.connect(self._on_llama_version)
        self._llama_ver_worker.start()

    def _goto_updater(self):
        self.tabs.setCurrentIndex(5)
        self.updater_tab.refresh()

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
    def set_theme(self, key):
        """切换配色方案（深色/浅色/橙色/绿色/灰色/棕色）。"""
        if key not in THEMES:
            return
        self.cfg.data["theme"] = key
        self._apply_theme()
        self.cfg.save()

    def _apply_theme(self):
        key = self.cfg.data.get("theme", "dark")
        if key not in THEMES:
            key = "dark"
        # 所有主题共用同一套尺寸度量，切换不会改变窗口布局大小
        QApplication.instance().setStyleSheet(build_qss(key))
        self.btn_theme.setText(f"{THEMES[key]['icon']} {THEMES[key]['name']}")

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
            logdir = os.path.join(self._data_dir(), "logs")
            os.makedirs(logdir, exist_ok=True)
            date = time.strftime("%Y%m%d")
            with open(os.path.join(logdir, f"运行日志-{date}.log"), "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
        except Exception:
            pass

    def _on_server_log(self, text):
        self.log_view.appendPlainText(text)
        self._log_file(text)
        # 统计：从服务端日志解析输入/输出 token（功能 9）
        parsed = parse_log_line(text)
        if parsed:
            kind, n = parsed
            name = self._running_model_name or self._stats_model_name()
            if name and n > 0:
                try:
                    self._stats().add_usage(
                        name,
                        in_tokens=n if kind == "prompt" else 0,
                        out_tokens=n if kind == "gen" else 0)
                except Exception:
                    pass

    def open_log_dir(self):
        logdir = os.path.join(self._data_dir(), "logs")
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
            text = hf_info.format_info(self._data_dir(), query)
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
        # 排除本程序自己发起的探测进程（--version / --list-devices）：
        # 否则每次启动都会把版本检测进程误判为「上次残留」。
        exclude = set()
        worker = getattr(self, "_llama_ver_worker", None)
        pid = getattr(worker, "probe_pid", None)
        if pid:
            exclude.add(pid)
        gpu_pid = getattr(self, "_gpu_probe_pid", None)
        if gpu_pid:
            exclude.add(gpu_pid)
        procs = find_llama_server_processes(exclude_pids=exclude)
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
        self._flush_usage()
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
