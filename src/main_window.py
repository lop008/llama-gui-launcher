import json
import os
import sys
import webbrowser

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QCloseEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QMessageBox, QPlainTextEdit, QPushButton, QSystemTrayIcon, QTabWidget, QTableWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from . import __version__
from .about_dialog import AboutDialog
from .cmd_builder import KV_CACHE_TYPES, SPLIT_MODES
from .config import Config
from .hf_download_tab import HFDownloadTab
from .server import ServerManager
from .system_monitor import SystemMonitor
from .themes import THEMES
from .updater_tab import UpdaterTab
from .i18n import LANGUAGES, t
from . import i18n
from .ui.widgets import CollapsibleBox, _AspectImageLabel
from .ui.workers import _LlamaVersionWorker
from .ui.gpu_probe import GpuMixin
from .ui.layout_basic import LayoutBasicMixin
from .ui.model_probe import ModelProbeMixin
from .ui.launch_flow import LaunchFlowMixin
from .ui.bat_io import BatIOMixin
from .ui.agent_tools import AgentToolsMixin
from .ui.tray_pill import TrayPillMixin
from .ui.app_prefs import AppPrefsMixin

try:
    from . import tools as tools_mod
    from . import opencode_launcher
except Exception:
    tools_mod = None
    opencode_launcher = None


# 主题/配色方案已抽离到 src/themes.py，切换主题不改变布局尺寸。


CREATE_NO_WINDOW = 0x08000000


class MainWindow(AppPrefsMixin, TrayPillMixin, AgentToolsMixin, BatIOMixin, LaunchFlowMixin,
                 ModelProbeMixin, LayoutBasicMixin, GpuMixin, QMainWindow):
    tool_scan_done = pyqtSignal()
    model_scan_done = pyqtSignal()
    model_info = pyqtSignal(str)
    hf_info_done = pyqtSignal(str)
    gpu_detected = pyqtSignal()
    mtp_detected = pyqtSignal()
    chat_detected = pyqtSignal()
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
        self.monitor.log_dir = os.path.join(self.cfg.data_dir(), "logs")
        self._loading = False
        self._quitting = False
        self._models = []
        self._aux = []          # 视觉投影 / 投机草稿头 / 标定文件（不进主模型下拉框）
        self._scan_hint = ""    # 扫描后要提示的用户问题，优先于计数文案显示
        self._tools_found = {}
        self._tool_rows = []
        self._last_selected_tool = None
        self._tray = None
        self._tray_act_pill = None
        self._tray_act_start = None
        self._tray_act_stop = None
        self._pill = None
        self._pill_session_hidden = False
        self._pill_cache = {}            # 悬浮窗最近一次数据（未创建时缓存，创建后回填）

        # ---- 数据统计（功能 9）----
        self._stats_store = None
        self._stats_path = None
        self._running_model_name = ""    # 当前服务运行的模型名（统计归属）
        self._usage_pending = 0.0        # 本次运行累计时长（统计已在 tick 中逐笔计入，此值仅用于重置）
        self._mtp_cache = {}             # path -> (bool|None, [names])
        self._chat_cache = {}            # path -> (has_template|None, has_reasoning)
        self._chat_has_template = None   # 当前模型的模板能力（None=未检测/无法检测）
        self._chat_has_reasoning = False
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
        self._restore_geometry()
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
        self._log_file(t('程序启动'))
        self.statusBar().showMessage(t('就绪'))
        if not os.environ.get("LLAMA_LAUNCHER_NO_GPU_DETECT"):
            QTimer.singleShot(2000, self.detect_gpus)   # 启动时自动检测多显卡（功能 3）


    # ------------------------------------------------------------------ UI
    def _build_menu(self):
        m = self.menuBar()
        menu_start = m.addMenu(t('开始(&S)'))
        self.act_start = QAction(t('启动服务(&R)'), self)
        self.act_start.setShortcut("Ctrl+R")
        self.act_stop = QAction(t('停止服务(&T)'), self)
        self.act_quit = QAction(t('退出(&X)'), self)
        self.act_quit.setShortcut("Ctrl+Q")
        menu_start.addAction(self.act_start)
        menu_start.addAction(self.act_stop)
        menu_start.addSeparator()
        menu_start.addAction(self.act_quit)

        menu_tools = m.addMenu(t('工具(&T)'))
        self.act_refresh = QAction(t('刷新模型'), self)
        self.act_open_dir = QAction(t('打开模型目录'), self)
        self.act_web = QAction(t('打开管理页面'), self)
        self.act_api = QAction(t('查看 API 模型列表'), self)
        self.act_open_agent = QAction(t('打开 Agent 工具'), self)
        self.act_clear_log = QAction(t('清空日志'), self)
        self.act_open_log = QAction(t('打开日志目录'), self)
        self.act_export = QAction(t('导出配置 (.aic)'), self)
        self.act_import = QAction(t('导入配置 (.aic)'), self)
        self.act_export_bat = QAction(t('导出一键启动 (.bat)'), self)
        self.act_export_bat.setToolTip(
            t('将当前模型与参数生成可双击直接启动 llama-server 的批处理，并在桌面创建带软件图标的快捷方式'))
        self.act_import_bat = QAction(t('导入启动文件 (.bat)…'), self)
        self.act_import_bat.setToolTip(
            t('选择一个已有的 .bat/.cmd/.ps1/.sh/文本启动文件，解析其中的 llama-server 参数并应用到当前界面（模型、上下文、采样、对话模板等）'))
        self.act_export_preview_bat = QAction(t('导出命令预览 (.bat)…'), self)
        self.act_export_preview_bat.setToolTip(
            t('把「命令预览」页里的完整命令行原样保存为 .bat 文件，可自选存储路径（功能 6）'))
        self.act_stats = QAction(t('数据统计…'), self)
        self.act_stats.setToolTip(
            t('打开独立的数据统计界面：打开次数、使用时长、输入/输出 token，支持按小时 / 日 / 月查看（功能 9）'))
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
        menu_tools.addAction(self.act_import_bat)
        menu_tools.addAction(self.act_export_bat)
        menu_tools.addAction(self.act_export_preview_bat)
        menu_tools.addAction(self.act_stats)
        menu_tools.addSeparator()
        menu_tools.addAction(self.act_clear_log)
        menu_tools.addAction(self.act_open_log)

        menu_lang = m.addMenu(t('语言(&L)'))
        _lang_group = QActionGroup(self)
        _lang_group.setExclusive(True)
        for _code, _native in LANGUAGES:
            _act = QAction(_native, self)
            _act.setCheckable(True)
            _act.setChecked(i18n.lang() == _code)
            _act.triggered.connect(lambda _chk=False, c=_code: self._switch_language(c))
            _lang_group.addAction(_act)
            menu_lang.addAction(_act)
        menu_lang.addSeparator()
        _act_auto = QAction(t('跟随系统语言'), self)
        _act_auto.setCheckable(True)
        _act_auto.setChecked((self.cfg.data.get("language") or "auto") == "auto")
        _act_auto.triggered.connect(lambda _chk=False: self._switch_language("auto"))
        _lang_group.addAction(_act_auto)
        menu_lang.addAction(_act_auto)

        menu_help = m.addMenu(t('关于(&H)'))
        self.act_about = QAction(t('开发者信息'), self)
        self.act_docs = QAction(t('参数说明'), self)
        menu_help.addAction(self.act_docs)
        menu_help.addAction(self.act_about)
        self.act_update_now = QAction(t('立即更新'), self)
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

        self.box_basic = CollapsibleBox(t('基本参数'))
        self._build_basic(self.box_basic.layout())
        self.box_advanced = CollapsibleBox(t('高级参数'))
        self.box_advanced.set_collapsed(True)
        self._build_advanced(self.box_advanced.layout())
        self.box_gpu = CollapsibleBox(t('多显卡 (Multi-GPU)'))
        self.box_gpu.set_collapsed(True)
        self._build_gpu(self.box_gpu.layout())
        pw.addWidget(self.box_basic)
        pw.addWidget(self.box_advanced)
        pw.addWidget(self.box_gpu)
        pw.addStretch(1)

        self.box_basic.toggled.connect(self._reflow_window)
        self.box_gpu.toggled.connect(self._reflow_window)
        self.box_advanced.toggled.connect(self._reflow_window)

        splitter_layout.addWidget(self.params_panel, 0)

        # ---- 底部 Tab 区 ----
        tabs = QTabWidget()
        tabs.setMovable(True)   # 标签可拖动调整顺序
        self.tabs = tabs
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
        tip = QLabel(t('双击行 = 打开；选中行后点底部「打开 Agent 工具」；未找到的工具双击可手动指定路径'))
        tip.setStyleSheet("color: #888;")
        tool_bar.addWidget(tip)
        tool_bar.addStretch(1)
        tt.addLayout(tool_bar)
        self.tool_table = QTableWidget(0, 5)
        self.tool_table.setHorizontalHeaderLabels([t('工具'), t('类型'), t('描述'), t('状态'), t('打开')])
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
        self.check_hf_query = QCheckBox(t('联网查询'))
        self.check_hf_query.setToolTip(
            t('勾选后，每次选择模型都会自动联网查询 HuggingFace 补充信息（简介 / 下载量 / 点赞 / 标签等，结果本地缓存 7 天）。\n不勾选则只显示从本地 GGUF 头部解析的信息。'))
        info_bar.addWidget(self.check_hf_query)
        self.btn_hf = QPushButton(t('联网查询该模型'))
        self.btn_hf.setToolTip(t('用模型名联网搜索 HuggingFace，拉取简介/下载量/点赞等公开信息（本地缓存 7 天）'))
        info_bar.addWidget(self.btn_hf)
        info_bar.addStretch(1)
        it.addLayout(info_bar)
        it.addWidget(self.info_view)

        # ---- 模型下载 Tab（功能 5：HF unsloth 检索 + 断点续传下载）----
        self.download_tab = HFDownloadTab(self)

        # ---- 更新 llama.cpp Tab（功能 10）----
        self.updater_tab = UpdaterTab(self)

        self._tab_widgets = {}

        def _add_tab(widget, title, key):
            tabs.addTab(widget, title)
            self._tab_widgets[key] = widget

        _add_tab(self.log_view, t('运行日志'), "log")
        _add_tab(self.preview_view, t('命令预览'), "preview")
        _add_tab(tool_tab, t('Agent 工具'), "tools")
        _add_tab(info_tab, t('模型信息'), "info")
        _add_tab(self.download_tab, t('模型下载'), "download")
        _add_tab(self.updater_tab, t('更新 llama.cpp'), "updater")
        self.tabs = tabs
        self.tabs.setMinimumHeight(280)
        # 恢复上次的标签顺序，并在拖动后持久化
        self._restore_tab_order()
        tabs.tabBar().tabMoved.connect(self._on_tab_moved)
        splitter_layout.addWidget(self.tabs, 1)
        root.addWidget(splitter_widget)

        # ---- 主按钮区（C1: 双排 × 5 列共 10 个；广告位在网格右侧）----
        self.btn_start = QPushButton(t('启动服务'))
        self.btn_start.setToolTip(t('启动 llama-server（隐藏窗口后台运行），就绪后自动打开浏览器'))
        self.btn_stop = QPushButton(t('停止服务'))
        self.btn_stop.setToolTip(t('停止服务并清理进程树（模型跑飞/幻觉时一键终止）'))
        self.btn_web = QPushButton(t('打开网页'))
        self.btn_web.setToolTip(t('在浏览器中打开 llama.cpp Web 聊天界面'))
        self.btn_agent = QPushButton(t('打开 Agent 工具'))
        self.btn_agent.setToolTip(t('打开「Agent 工具」列表中当前选中（高亮）的工具'))
        self.btn_save = QPushButton(t('保存配置'))
        self.btn_save.setToolTip(t('将当前所有设置保存到 config.json（服务器参数、所选模型、视觉模型、工具路径、主题等），下次启动自动恢复'))
        # C1: 第 2 排 —— 校验启动文件 + 导入启动文件（7 号位）+ 导出启动文件 + 2 个占位按钮
        self.btn_validate_bat = QPushButton(t('校验启动文件'))
        self.btn_validate_bat.setToolTip(
            t('选择 .bat/.cmd/.ps1/.sh/文本脚本，静态校验启动项能否正常运行并生成参数报告。\n支持 bat 变量（set VAR=… / %VAR%）、^ 续行合并、REM/:: 注释跳过。'))
        self.btn_import_file = QPushButton(t('导入启动文件'))
        self.btn_import_file.setToolTip(
            t('选择一个已有的 .bat/.cmd/.ps1/.sh/文本启动文件，解析其中的 llama-server 参数并应用到当前界面\n（模型、视觉模型、上下文、采样参数、对话模板等），等同「工具 → 导入启动文件 (.bat)…」。'))
        self.btn_export_file = QPushButton(t('导出启动文件'))
        self.btn_export_file.setToolTip(
            t('把当前模型与全部参数导出为可双击直接启动 llama-server 的 .bat 一键启动脚本，并在桌面创建带软件图标的快捷方式（等同「工具 → 导出一键启动 (.bat)」）'))
        # C1: 第 2 排 —— 校验启动文件 + 导入启动文件 + 导出启动文件 + 数据统计 + 1 个预留
        self.btn_stats = QPushButton(t('数据统计'))
        self.btn_stats.setToolTip(
            t('打开数据统计窗口：打开次数、使用时长、输入/输出 token，支持按小时 / 日 / 月查看（等同「工具 → 数据统计…」）'))
        _b = QPushButton(t('预留功能'))
        _b.setEnabled(False)
        _b.setToolTip(t('预留功能（暂未开放）'))
        self.btn_ph_3 = _b

        btn_grid = QGridLayout()
        btn_grid.setHorizontalSpacing(8)
        btn_grid.setVerticalSpacing(8)
        _row0 = [self.btn_start, self.btn_stop, self.btn_web, self.btn_agent, self.btn_save]
        _row1 = [self.btn_validate_bat, self.btn_import_file, self.btn_export_file,
                 self.btn_stats, self.btn_ph_3]
        for _r, _row in enumerate((_row0, _row1)):
            for _c, _b in enumerate(_row):
                # 中文 120px 够用；其他语言按内容自动加宽，避免裁字
                _b.setMinimumWidth(120)
                _b.setFixedHeight(36)
                btn_grid.addWidget(_b, _r, _c)

        # ---- 广告位占位符（按钮网格右侧，横向铺满、纵向等比不拉伸）----
        self.label_ad = _AspectImageLabel()
        self.label_ad.setMinimumWidth(160)
        self.label_ad.setMinimumHeight(40)
        self.label_ad.setToolTip(t('广告位。放入 assets/ad.png 即可替换为你的图片（按宽度等比缩放，不会纵向拉伸）。'))
        ad_path = os.path.join(self.resource_dir, "assets", "ad.png")
        pm = QPixmap(ad_path) if os.path.isfile(ad_path) else QPixmap()
        if not pm.isNull():
            self.label_ad.set_source_pixmap(pm)
        else:
            self.label_ad.setText(t('广告位'))
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
        self.label_model_path = QLabel(t('未选择模型'))
        self.label_model_path.setMaximumWidth(460)
        self.label_model_path.setToolTip(t('当前选中主模型的完整路径'))
        sb.addWidget(self.label_model_path)

        def _mk_label():
            lab = QLabel("")
            lab.setStyleSheet("color: #777; padding: 0 6px;")
            return lab

        self.btn_theme = QPushButton(t('🎨 主题'))
        self.btn_theme.setMinimumWidth(96)
        self.btn_theme.setToolTip(t('选择配色方案：深色 / 浅色 / 橙色 / 绿色 / 灰色 / 棕色'))
        theme_menu = QMenu(self)
        for _key, _th in THEMES.items():
            _act = theme_menu.addAction(f"{_th['icon']} {_th['name']}")
            _act.triggered.connect(lambda _=False, k=_key: self.set_theme(k))
        self.btn_theme.setMenu(theme_menu)
        sb.addPermanentWidget(self.btn_theme)          # 最右

        self.label_api = _mk_label()
        self.label_api.setText(t('API 未运行'))
        self.label_api.setToolTip(t('外部工具（opencode 等）是否正在通过 API 请求模型'))
        sb.addPermanentWidget(self.label_api)

        self.label_model = _mk_label()
        self.label_model.setText(t('模型 未运行'))
        self.label_model.setToolTip(t('当前加载运行的模型'))
        sb.addPermanentWidget(self.label_model)

        self.label_vram = _mk_label()
        self.label_vram.setToolTip(t('显卡显存占用（已用/总，nvidia-smi）'))
        sb.addPermanentWidget(self.label_vram)

        self.label_mem = _mk_label()
        self.label_mem.setToolTip(t('系统内存占用'))
        sb.addPermanentWidget(self.label_mem)

        self.label_cpu = _mk_label()
        self.label_cpu.setToolTip(t('服务运行时显示 llama-server 进程 CPU 占用；未运行时显示系统 CPU'))
        sb.addPermanentWidget(self.label_cpu)          # 最左（靠近普通消息）

        self.setWindowTitle(t('LLama 启动器 v{0}').format(__version__))
        # 双排按钮网格 + 广告位需要较宽窗口，直接以目标尺寸初始化
        self.resize(1280, 1280)


    # ------------------------------------------------------------ helpers
    def _connect(self):
        self.server.log.connect(self._on_server_log)
        self.server.state.connect(self._on_server_state)
        self.server.healthy.connect(self._on_healthy)
        self.server.exited.connect(self._on_exited)
        self.model_scan_done.connect(self._on_model_scan_done)
        self.tool_scan_done.connect(self._on_tool_scan_done)
        self.model_info.connect(self._on_model_info)
        self.hf_info_done.connect(self._on_hf_info)

        self.monitor.cpu_changed.connect(lambda v: self.label_cpu.setText(f"CPU {v:.0f}%"))
        # 悬浮窗 CPU：系统整体负载（所有核心平均占用率）
        self.monitor.cpu_load_changed.connect(
            lambda v: self._update_pill("cpu", v))
        self.monitor.mem_changed.connect(self._on_mem)
        self.monitor.vram_changed.connect(self._on_vram)
        self.monitor.model_changed.connect(
            lambda n: (self.label_model.setText(t('模型 {0}').format(n)),
                       self._update_pill("model", n)))
        self.monitor.api_changed.connect(lambda t: self.label_api.setText(t))

        # 悬浮小窗：把监控信号缓存并转发到小窗（小窗尚未创建时先缓存，创建后回填）
        self.monitor.mem_raw_changed.connect(
            lambda u, t: self._update_pill("mem", u, t))
        self.monitor.vram_raw_changed.connect(
            lambda u, t: self._update_pill("vram", u, t))
        self.monitor.gpu_util_changed.connect(
            lambda v: self._update_pill("gpu", v))
        self.monitor.speed_changed.connect(
            lambda v: self._update_pill("speed", v))
        self.monitor.api_busy_changed.connect(
            lambda n: self._update_pill("api_busy", n))

        self.btn_start.clicked.connect(self.start_server)
        self.btn_stop.clicked.connect(self.stop_server)
        self.btn_web.clicked.connect(self.open_web)
        self.btn_agent.clicked.connect(self.open_selected_agent_tool)
        self.btn_save.clicked.connect(self.save_config)
        self.btn_validate_bat.clicked.connect(self.open_bat_validator)   # C3
        self.btn_import_file.clicked.connect(self.import_bat)            # 7 号位：导入启动文件
        self.btn_export_file.clicked.connect(self.export_bat)            # 8 号位：导出启动文件
        self.btn_stats.clicked.connect(self.show_stats)                  # 9 号位：数据统计
        # 主题按钮改为弹出菜单（见 _build_ui 的 setMenu），无需 clicked 连接
        self.btn_hf.clicked.connect(self._query_hf_info)
        self.check_hf_query.toggled.connect(self._on_hf_query_toggled)

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
        self.act_import_bat.triggered.connect(self.import_bat)
        self.act_export_preview_bat.triggered.connect(self.export_preview_bat)
        self.act_stats.triggered.connect(self.show_stats)
        self.act_about.triggered.connect(self.show_about)
        self.act_docs.triggered.connect(self.open_docs)
        self.act_update_now.triggered.connect(self._goto_updater)

        # 多显卡 / MTP / 排序（功能 1/3/4）+ A5 显存权重
        self.gpu_detected.connect(self._on_gpus_detected)
        self.mtp_detected.connect(self._on_mtp_detected)
        self.chat_detected.connect(self._on_chat_detected)
        self.check_jinja.toggled.connect(self._update_chat_controls)
        self.check_residual.toggled.connect(self._save_startup_prefs)
        self.check_port_hint.toggled.connect(self._save_startup_prefs)
        self.check_hover_pill.toggled.connect(self._on_pill_hover_toggled)
        # 局域网共享 / HTTPS / 本机 IP 提示
        self.check_lan.toggled.connect(self._on_lan_toggled)
        self.check_ssl.toggled.connect(self._on_ssl_toggled)
        self.edit_host.textChanged.connect(self._on_host_edited)
        self.spin_port.valueChanged.connect(self._update_local_ip_label)
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
            self.check_lan, self.check_ssl,
            self.combo_split_mode, self.edit_tensor_split, self.spin_main_gpu,
            self.check_mtp,
            self.check_jinja, self.combo_reasoning, self.spin_reasoning_budget,
        ]

    def _gather_server_cfg(self):
        ssl_on = self.check_ssl.isChecked()
        ssl_key, ssl_cert = self._ssl_paths() if ssl_on else ("", "")
        return {
            "host": self.edit_host.text().strip() or "127.0.0.1",
            "port": self.spin_port.value(),
            "lan_share": self.check_lan.isChecked(),
            "ssl_enabled": ssl_on,
            "ssl_key_file": ssl_key,
            "ssl_cert_file": ssl_cert,
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
            # 对话模板（功能 8）
            "jinja": self.check_jinja.isChecked(),
            "reasoning_effort": self.combo_reasoning.currentData() or "",
            "reasoning_budget": self.spin_reasoning_budget.value(),
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
        self.check_lan.setChecked(bool(
            s.get("lan_share", str(s.get("host", "")).strip() == "0.0.0.0")))
        self.check_ssl.setChecked(bool(s.get("ssl_enabled", False)))
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

        # 对话模板（功能 8）
        self.check_jinja.setChecked(bool(s.get("jinja", False)))
        _effort = str(s.get("reasoning_effort") or "")
        _idx = self.combo_reasoning.findData(_effort)
        self.combo_reasoning.setCurrentIndex(_idx if _idx >= 0 else 0)
        try:
            self.spin_reasoning_budget.setValue(int(s.get("reasoning_budget", -1)))
        except (TypeError, ValueError):
            self.spin_reasoning_budget.setValue(-1)

        # 启动时行为：残留进程检测 / 端口占用建议
        self.check_residual.setChecked(bool(d.get("check_residual", True)))
        self.check_port_hint.setChecked(bool(d.get("port_hint", True)))
        self.check_hover_pill.setChecked(bool(d.get("hover_pill", True)))
        self.check_hf_query.setChecked(bool(d.get("hf_query_enabled", False)))

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
        self._update_local_ip_label()

    def save_config(self):
        d = self.cfg.data
        d["llama_dir"] = self.edit_dir.text().strip()
        d["launcher_exe"] = self.edit_launcher.text().strip()
        new_data_dir = self.edit_data_dir.text().strip()
        if new_data_dir != (d.get("data_dir", "") or ""):
            self.cfg.redirect_data_dir(new_data_dir)
            d = self.cfg.data
            self.monitor.log_dir = os.path.join(self.cfg.data_dir(), "logs")
        d["server"] = self._gather_server_cfg()
        d["model"] = self.combo_model.currentData() or ""
        d["mmproj"] = self.combo_mmproj.currentData() or ""
        d["check_residual"] = self.check_residual.isChecked()
        d["port_hint"] = self.check_port_hint.isChecked()
        d["hover_pill"] = self.check_hover_pill.isChecked()
        d["hf_query_enabled"] = self.check_hf_query.isChecked()
        d["window_geometry"] = list(self.geometry().getRect())
        ok = self.cfg.save()
        self.statusBar().showMessage(t('配置已保存') if ok else t('配置保存失败'), 3000)

    def _save_startup_prefs(self, _checked=None):
        """残留检测 / 端口建议 两个开关立即落盘（无需点「保存配置」）。"""
        if self._loading:
            return
        self.cfg.data["check_residual"] = self.check_residual.isChecked()
        self.cfg.data["port_hint"] = self.check_port_hint.isChecked()
        self.cfg.save()
    def export_config(self):
        """导出完整配置为 .aic 文件（内容即 JSON，仅扩展名不同）。"""
        default = os.path.join(self.base_dir, t('LLama启动器配置.aic'))
        path, _ = QFileDialog.getSaveFileName(self, t('导出配置'), default, t('LLama 启动器配置 (*.aic);;JSON (*.json)'))
        if not path:
            return
        self.save_config()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.cfg.data, f, ensure_ascii=False, indent=2)
            self.statusBar().showMessage(t('配置已导出: {0}').format(path), 5000)
            self._on_server_log(t('[配置] 已导出到 {0}').format(path))
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('导出失败: {0}').format(e))

    def import_config(self):
        """从 .aic / .json 文件导入完整配置并应用到界面。"""
        path, _ = QFileDialog.getOpenFileName(self, t('导入配置'), self.base_dir,
                                              t('LLama 启动器配置 (*.aic *.json);;所有文件 (*.*)'))
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError(t('文件内容不是有效的配置'))
            self.cfg.apply_loaded(loaded)   # 含旧键迁移（kv_cache_type → k/v）
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('导入失败: {0}').format(e))
            return
        self._apply_config()
        self._apply_theme()
        self.refresh_models(keep_selection=True)
        self.statusBar().showMessage(t('配置已导入: {0}').format(path), 5000)
        self._on_server_log(t('[配置] 已从 {0} 导入').format(path))


    # ---------------------------------------------------------- 其他
    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, t('选择模型扫描目录'), self.edit_dir.text() or os.path.expanduser("~"))
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
        path, _ = QFileDialog.getOpenFileName(self, t('选择启动器可执行文件'), start,
                                              t('可执行文件 (*.exe);;所有文件 (*.*)'))
        if path:
            self.edit_launcher.setText(path)
            self.cfg.data["launcher_exe"] = path
            self.cfg.save()
            self.update_preview()
            self.scan_tools()
            self.statusBar().showMessage(t('启动器文件: {0}').format(path), 4000)

    def _clear_launcher(self):
        self.edit_launcher.setText("")
        self.cfg.data["launcher_exe"] = ""
        self.cfg.save()
        self.update_preview()
        self.scan_tools()
        self.statusBar().showMessage(t('已恢复自动查找 llama-server.exe'), 3000)

    def _data_dir(self):
        """返回数据存储目录（config.json/日志/缓存），空则程序目录。"""
        return self.cfg.ensure_data_dir()

    def _browse_data_dir(self):
        d = QFileDialog.getExistingDirectory(self, t('选择数据存储目录'), self._data_dir())
        if not d:
            return
        self.edit_data_dir.setText(d)
        if self.cfg.redirect_data_dir(d):
            self.statusBar().showMessage(t('数据目录已切换到: {0}').format(d), 5000)
            self._log_file(t('[配置] 数据目录切换到 {0}').format(d))
        else:
            self.statusBar().showMessage(t('数据目录切换失败'), 4000)

    def _reset_data_dir(self):
        self.edit_data_dir.setText("")
        if self.cfg.redirect_data_dir(""):
            self.statusBar().showMessage(t('数据目录已恢复为程序所在目录'), 4000)
            self._log_file(t('[配置] 数据目录恢复为程序目录'))

    def _ensure_valid_llama_dir(self):
        """启动时校验模型目录；无效则弹窗让用户选择（浏览选择 / 使用默认上级目录）。"""
        llama_dir = self.edit_dir.text().strip()
        if llama_dir and os.path.isdir(llama_dir):
            return
        ret = QMessageBox.question(
            self, t('模型目录无效'),
            t('当前模型目录不存在或不可访问：\n{0}\n\n是否立即重新选择模型目录？\n（选「否」将使用启动器所在目录的上级目录）').format(llama_dir or t('（空）')),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            self._browse_dir()
        else:
            parent = os.path.dirname(os.path.abspath(self.base_dir))
            if os.path.isdir(parent):
                self.edit_dir.setText(parent)
                self.cfg.data["llama_dir"] = parent
                self.cfg.save()
                self.statusBar().showMessage(t('模型目录已设为: {0}').format(parent), 4000)

    def _on_llama_version(self, ver):
        base = t('LLama 启动器 v{0}').format(__version__)
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
        doc = os.path.join(self.resource_dir, t('参数说明.md'))
        if os.path.isfile(doc):
            try:
                os.startfile(doc)  # noqa: S606
            except Exception:
                webbrowser.open(doc)
        else:
            QMessageBox.information(self, t('提示'), t('未找到参数说明文档'))


    def showEvent(self, event):
        # 主窗口任何时候重新可见：清除悬浮窗「本次隐藏」状态
        self._pill_session_hidden = False
        super().showEvent(event)


    def quit_app(self):
        self._quitting = True
        if self._pill is not None:
            self._pill.hide()
        closed = self.close()
        if closed:
            # 隐藏到托盘后 close() 不会触发 lastWindowClosed，需显式退出事件循环
            QApplication.instance().quit()

    def closeEvent(self, event: QCloseEvent):
        if (not self._quitting and self._tray is not None
                and self.cfg.data.get("minimize_to_tray", True)):
            self.hide()
            self._update_tray_hover()
            self._tray.showMessage(
                t('LLama 启动器'), t('已最小化到托盘，双击图标或小窗返回主界面。服务仍在后台运行。'),
                QSystemTrayIcon.MessageIcon.Information, 2000)
            event.ignore()
            return
        self._flush_usage()
        self.save_config()
        self._log_file(t('程序退出'))
        if self.server.running:
            ret = QMessageBox.question(
                self, t('退出'), t('服务正在运行，退出时是否同时停止服务？'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No |
                QMessageBox.StandardButton.Cancel)
            if ret == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
            if ret == QMessageBox.StandardButton.Yes:
                self.server.stop()
                self.monitor.set_server(None)
        super().closeEvent(event)
