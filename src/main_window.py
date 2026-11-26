import json
import os
import sys
import threading
import time
import webbrowser

from PyQt6.QtCore import QEvent, QPoint, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QCloseEvent, QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSystemTrayIcon, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from . import __version__
from .about_dialog import AboutDialog
from .bat_validator import ValidateBatDialog, parse_script
from .cmd_builder import (
    KV_CACHE_TYPES, SPLIT_MODES, build_args, build_bat_content, build_command,
    build_preview_bat, model_alias,
)
from .config import Config
from .hf_download_tab import HFDownloadTab
from .net_utils import default_cert_paths, ensure_self_signed_cert, local_ipv4
from .presets import PRESETS, SAMPLING_PRESETS
from .pill import HoverPill
from .server import (
    ServerManager, find_llama_server_processes, kill_all_llama_server, port_in_use,
)
from .stats_dialog import StatsDialog
from .system_monitor import SystemMonitor
from .themes import THEMES, build_qss
from .updater_tab import UpdaterTab
from .usage_stats import StatsStore, parse_log_line
from .i18n import LANGUAGES, t
from . import i18n
from .ui.widgets import CollapsibleBox, _AspectImageLabel
from .ui.workers import _LlamaVersionWorker
from .ui.gpu_probe import GpuMixin
from .ui.layout_basic import LayoutBasicMixin
from .ui.model_probe import ModelProbeMixin

try:
    from . import tools as tools_mod
    from . import opencode_launcher
except Exception:
    tools_mod = None
    opencode_launcher = None


# 主题/配色方案已抽离到 src/themes.py，切换主题不改变布局尺寸。


CREATE_NO_WINDOW = 0x08000000


class MainWindow(QMainWindow, GpuMixin, LayoutBasicMixin, ModelProbeMixin):
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

    # ---------------------------------------------------------- 数据统计（功能 9）
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
        """打开独立的数据统计界面（功能 9）。"""
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

    # ---------------------------------------------------------- 启动文件导入
    @staticmethod
    def _select_combo_by_path(combo, target):
        """按绝对路径或文件名在 combo 中选中匹配项；成功返回 True。"""
        if not target:
            return False
        tgt = os.path.normcase(os.path.abspath(str(target)))
        tbase = os.path.normcase(os.path.basename(str(target)))
        for i in range(combo.count()):
            data = combo.itemData(i)
            if not data:
                continue
            d = os.path.normcase(os.path.abspath(str(data)))
            if d == tgt or os.path.basename(d) == tbase:
                combo.setCurrentIndex(i)
                return True
        return False

    def import_bat(self):
        """解析已有的启动文件（.bat/.cmd/.ps1/.sh/文本），把参数应用到当前界面。"""
        start_dir = self.edit_dir.text().strip() or self.base_dir
        path, _ = QFileDialog.getOpenFileName(
            self, t('导入启动文件'), start_dir,
            t('启动文件 (*.bat *.cmd *.ps1 *.sh *.txt);;所有文件 (*.*)'))
        if not path:
            return
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('读取失败: {0}').format(e))
            return
        text = None
        for enc in ("utf-8-sig", "gbk"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            QMessageBox.critical(self, t('错误'), t('无法识别文件编码（UTF-8 / GBK 均失败）'))
            return
        try:
            params = parse_script(text, path)
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('解析失败: {0}').format(e))
            return
        if not params:
            QMessageBox.information(self, t('提示'), t('未在文件中识别到任何 llama-server 参数'))
            return
        applied, warns = self._apply_imported_params(params)
        self.update_preview()
        base = os.path.basename(path)
        if applied == 0:
            QMessageBox.warning(self, t('导入完成（未应用任何参数）'),
                                t('已解析 {0}，但没有可应用的参数。\n\n').format(base) + "\n".join(warns))
            return
        msg = t('已从 {0} 导入 {1} 项参数').format(base, applied)
        self._on_server_log(t('[导入] {0}').format(msg))
        if warns:
            QMessageBox.warning(self, t('导入完成（部分项未应用）'),
                                msg + t('\n\n注意：\n') + "\n".join(warns))
        else:
            self.statusBar().showMessage(msg, 5000)

    def _apply_imported_params(self, params):
        """把 parse_script 的结果应用到界面控件。返回 (应用项数, 警告列表)。"""
        kv = {}
        for _frag, name, value in params:
            if name:
                kv[name] = value
        applied = 0
        warns = []

        def _int(value, label, lo=None, hi=None):
            nonlocal applied
            try:
                v = int(float(str(value).strip()))
            except (TypeError, ValueError):
                warns.append(t('{0}：无法解析“{1}”').format(label, value))
                return None
            if lo is not None and v < lo:
                v = lo
            if hi is not None and v > hi:
                v = hi
            applied += 1
            return v

        def _float(value, label, lo=None, hi=None):
            nonlocal applied
            try:
                v = float(str(value).strip())
            except (TypeError, ValueError):
                warns.append(t('{0}：无法解析“{1}”').format(label, value))
                return None
            if lo is not None and v < lo:
                v = lo
            if hi is not None and v > hi:
                v = hi
            applied += 1
            return v

        # 模型优先（会触发视觉模型列表重建）
        if "model" in kv:
            if self._select_combo_by_path(self.combo_model, kv["model"]):
                applied += 1
            else:
                warns.append(t('主模型：列表中未找到“{0}”').format(os.path.basename(str(kv['model']))))
        if "mmproj" in kv:
            if self._select_combo_by_path(self.combo_mmproj, kv["mmproj"]):
                applied += 1
            else:
                warns.append(t('视觉模型：未找到“{0}”').format(os.path.basename(str(kv['mmproj']))))

        self._loading = True
        try:
            if "ctx" in kv:
                v = _int(kv["ctx"], t('上下文长度'), 256, 1048576)
                if v is not None:
                    self.spin_ctx.setValue(v)
            if "predict" in kv:
                v = _int(kv["predict"], t('预测Token'), -1, 1000000)
                if v is not None:
                    self.spin_np.setValue(v)
            if "batch" in kv:
                v = _int(kv["batch"], t('批大小'), 1, 16384)
                if v is not None:
                    self.spin_batch.setValue(v)
            if "threads" in kv:
                v = _int(kv["threads"], t('CPU线程'), -1, 256)
                if v is not None:
                    self.spin_threads.setValue(v)
            if "slots" in kv:
                v = _int(kv["slots"], t('并行slots'), -1, 64)
                if v is not None:
                    self.spin_slots.setValue(v)
            if "ngl" in kv:
                self.combo_ngl.setEditText(str(kv["ngl"]))
                applied += 1
            if "flash_attn" in kv and kv["flash_attn"] in ("on", "off", "auto"):
                self.combo_fa.setCurrentText(kv["flash_attn"])
                applied += 1
            if "kv_k" in kv and kv["kv_k"] in KV_CACHE_TYPES:
                self.combo_kvc_k.setCurrentText(kv["kv_k"])
                applied += 1
            if "kv_v" in kv and kv["kv_v"] in KV_CACHE_TYPES:
                self.combo_kvc_v.setCurrentText(kv["kv_v"])
                applied += 1
            if "temp" in kv:
                v = _float(kv["temp"], t('温度'), 0.0, 2.0)
                if v is not None:
                    self.spin_temp.setValue(v)
            if "top_p" in kv:
                v = _float(kv["top_p"], "Top-P", 0.0, 1.0)
                if v is not None:
                    self.spin_topp.setValue(v)
            if "top_k" in kv:
                v = _int(kv["top_k"], "Top-K", 0, 200)
                if v is not None:
                    self.spin_topk.setValue(v)
            if "repeat_penalty" in kv:
                v = _float(kv["repeat_penalty"], t('重复惩罚'), 0.0, 2.0)
                if v is not None:
                    self.spin_rp.setValue(v)
            if "timeout" in kv:
                v = _int(kv["timeout"], t('超时(秒)'), 30, 86400)
                if v is not None:
                    self.spin_timeout.setValue(v)
            if "host" in kv:
                self.edit_host.setText(str(kv["host"]))
                applied += 1
            if "port" in kv:
                v = _int(kv["port"], t('端口'), 1, 65535)
                if v is not None:
                    self.spin_port.setValue(v)
            if "split_mode" in kv and kv["split_mode"] in SPLIT_MODES:
                self.combo_split_mode.setCurrentText(kv["split_mode"])
                applied += 1
            if "main_gpu" in kv:
                v = _int(kv["main_gpu"], t('主GPU'), 0, 63)
                if v is not None:
                    self.spin_main_gpu.setValue(v)
            if "tensor_split" in kv:
                self.edit_tensor_split.setText(str(kv["tensor_split"]))
                applied += 1
            if "cont_batching" in kv:
                self.check_cont.setChecked(True)
                applied += 1
            if "mlock" in kv:
                self.check_mlock.setChecked(True)
                applied += 1
            if "no_mmap" in kv:
                self.check_mmap.setChecked(True)
                applied += 1
            if "spec_type" in kv and "mtp" in str(kv["spec_type"]).lower():
                self.check_mtp.setChecked(True)
                applied += 1
            if "jinja" in kv:
                self.check_jinja.setChecked(True)
                applied += 1
            if "chat_template_kwargs" in kv:
                raw = str(kv["chat_template_kwargs"]).strip()
                if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
                    raw = raw[1:-1]
                raw = raw.replace('\\"', '"').replace("\\'", "'")
                try:
                    obj = json.loads(raw)
                    effort = str(obj.get("reasoning_effort") or "").strip()
                    idx = self.combo_reasoning.findData(effort)
                    if effort and idx >= 0:
                        self.combo_reasoning.setCurrentIndex(idx)
                        self.check_jinja.setChecked(True)
                        applied += 1
                except Exception:
                    warns.append(t('模板参数：JSON 解析失败，已跳过'))
            if "reasoning_budget" in kv:
                v = _int(kv["reasoning_budget"], t('推理预算'), -1, 1000000)
                if v is not None:
                    self.spin_reasoning_budget.setValue(v)
            if "api_key" in kv:
                warns.append(t('API Key：出于安全考虑不导入（文件中为打码值）'))
            if "ssl_key_file" in kv or "ssl_cert_file" in kv:
                self.check_ssl.setChecked(True)
                applied += 1
        finally:
            self._loading = False
        return applied, warns

    # ---------------------------------------------------------- 一键启动导出
    def export_bat(self):
        """将当前配置导出为可双击启动的 .bat，并在桌面创建带软件图标的快捷方式。"""
        model = self.combo_model.currentData()
        if not model:
            QMessageBox.information(self, t('提示'), t('请先选择模型'))
            return
        llama_dir = self.edit_dir.text().strip()
        launcher_exe = self._launcher_exe()
        if not os.path.isfile(launcher_exe):
            QMessageBox.warning(self, t('提示'),
                                t('未找到启动器可执行文件（llama-server.exe）。\n请检查模型目录，或在「启动器文件」中用文件选择器指定。'))
            return
        self.save_config()
        s = self._gather_server_cfg()
        mmproj = self.combo_mmproj.currentData()
        try:
            content = build_bat_content(model, mmproj, s, llama_dir, launcher_exe=launcher_exe)
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('生成批处理失败: {0}').format(e))
            return
        default = os.path.join(self.base_dir, t('{0}-一键启动.bat').format(model_alias(model)))
        path, _ = QFileDialog.getSaveFileName(self, t('导出一键启动批处理'), default, t('批处理文件 (*.bat)'))
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write(content)
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('导出失败: {0}').format(e))
            return
        self.statusBar().showMessage(t('已导出: {0}').format(path), 5000)
        self._on_server_log(t('[导出] 已生成一键启动脚本 {0}').format(path))
        self._create_desktop_shortcut(path)

    def export_preview_bat(self):
        """把「命令预览」页的完整命令行原样导出为 .bat，自选存储路径（功能 6）。"""
        preview = (self.preview_view.toPlainText() or "").strip()
        if not preview:
            QMessageBox.information(self, t('提示'), t('命令预览为空：请先选择模型并配置参数'))
            return
        alias = model_alias(self.combo_model.currentData() or "") or "llama-server"
        default = os.path.join(
            self._data_dir(), t("{0}-命令预览.bat").format(alias).replace("\\", "_"))
        path, _ = QFileDialog.getSaveFileName(
            self, t('导出命令预览为 .bat（可选择存储路径）'), default,
            t('批处理文件 (*.bat);;所有文件 (*.*)'))
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write(build_preview_bat(preview, title=f"LLama Server - {alias}"))
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('导出失败: {0}').format(e))
            return
        self.statusBar().showMessage(t('命令预览已导出: {0}').format(path), 5000)
        self._on_server_log(t('[导出] 命令预览已保存为 {0}').format(path))

    def _create_desktop_shortcut(self, bat_path):
        """用 WScript.Shell 在桌面创建指向 bat 的快捷方式，图标取程序图标。"""
        desktop = self._desktop_dir()
        if not desktop:
            QMessageBox.information(self, t('提示'), t('导出成功，但无法定位桌面目录，跳过快捷方式'))
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
            t("$s.Description = 'LLama 启动器一键启动'"),
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
            QMessageBox.warning(self, t('提示'), t('创建桌面快捷方式失败: {0}').format(e))
            return
        QMessageBox.information(
            self, t('完成'),
            t('已导出：{0}\n\n已在桌面创建快捷方式：\n{1}').format(bat_path, lnk_path))
        self.statusBar().showMessage(t('桌面快捷方式已创建: {0}').format(lnk_path), 6000)

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
        self.statusBar().showMessage(t('已应用上下文预设: {0}').format(PRESETS[idx][0]), 3000)

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
            self.preview_view.setPlainText(t('请选择模型'))
            return
        llama_dir = self.edit_dir.text().strip()
        s = self._gather_server_cfg()
        try:
            args = build_args(model, self.combo_mmproj.currentData(), s, llama_dir,
                              launcher_exe=self._launcher_exe())
            self.preview_view.setPlainText(build_command(args))
        except Exception as e:
            self.preview_view.setPlainText(t('生成命令失败: {0}').format(e))

    # ------------------------------------------------------------- 服务
    def start_server(self):
        model = self.combo_model.currentData()
        if not model:
            QMessageBox.information(self, t('提示'), t('请先选择模型'))
            return
        llama_dir = self.edit_dir.text().strip()
        launcher_exe = self._launcher_exe()
        if not os.path.isfile(launcher_exe):
            QMessageBox.warning(self, t('提示'),
                                t('未找到启动器可执行文件（llama-server.exe）。\n请检查模型目录，或在「启动器文件」中用文件选择器指定。'))
            return
        host = self.edit_host.text().strip() or "127.0.0.1"
        port = self.spin_port.value()
        if port_in_use(host, port):
            free = self._find_free_port(host, port) if self.check_port_hint.isChecked() else None
            if free:
                ret = QMessageBox.question(
                    self, t('端口占用'),
                    t('端口 {0} 已被占用，可能已有服务在运行。\n是否改用可用端口 {1}？\n\n选择「No」= 不更换端口，仍按原端口尝试启动。').format(port, free),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if ret == QMessageBox.StandardButton.Yes:
                    self.spin_port.setValue(free)
                    port = free
            else:
                ret = QMessageBox.question(
                    self, t('端口占用'), t('端口 {0} 已被占用，可能已有服务在运行。\n仍然尝试启动？').format(port),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if ret != QMessageBox.StandardButton.Yes:
                    return

        self.save_config()
        s = self._gather_server_cfg()
        try:
            use_ssl = self._resolve_ssl(s)
        except Exception as e:
            QMessageBox.critical(self, t('HTTPS 证书生成失败'), str(e))
            return
        mmproj_path = self.combo_mmproj.currentData()
        mm = self._mmproj_mismatch(model, mmproj_path)
        if mm:
            ret = QMessageBox.warning(
                self, t('视觉模型不匹配'),
                t('主模型与视觉模型的嵌入维度不一致：主模型 {0} vs 视觉模型 {1}。\nllama.cpp 会因此加载失败（error: mismatch between text model and mmproj）。\n\n建议：切换一个配套的视觉模型，或选择「（不使用）」以纯文本模式运行。\n\n仍要尝试启动吗？').format(mm[0], mm[1]),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return
        try:
            args = build_args(model, mmproj_path, s, llama_dir, launcher_exe=self._launcher_exe())
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('构建命令失败: {0}').format(e))
            return

        self._log_file(">>> " + build_command(args))
        ok = self.server.start(args, llama_dir, host, port,
                               scheme="https" if use_ssl else "http",
                               verify=not use_ssl)
        if ok:
            self._set_running_state(True)
            self.monitor.set_server(self.server.proc, self.server.url,
                                    os.path.basename(model), verify=not use_ssl)
            # 统计：一次启动计为一次「打开」（功能 9）
            self._running_model_name = os.path.basename(model)
            self._usage_pending = 0.0
            try:
                self._stats().record_open(self._running_model_name)
            except Exception:
                pass
            self.statusBar().showMessage(t('服务启动中…'), 0)

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
        self._set_tray_menu_state()
        self._sync_pill_running()

    def _on_server_state(self, msg):
        self.statusBar().showMessage(msg, 0)
        self._log_file(msg)

    def _on_healthy(self, url):
        self._set_running_state(True)
        self._log_file(t('服务已就绪: {0}').format(url))
        self.monitor.fetch_model_now()
        if self.check_browser.isChecked():
            webbrowser.open(url)
        self.statusBar().showMessage(t('服务已就绪: {0}').format(url), 0)

    def _on_exited(self, code):
        self._set_running_state(False)
        self.monitor.set_server(None)
        self._flush_usage()
        if not self.server.manual_stop and code != 0:
            self.statusBar().showMessage(t('服务已退出（退出码 {0}）').format(code), 0)

    def open_web(self):
        scheme = "https" if self.check_ssl.isChecked() else "http"
        url = f"{scheme}://{self.edit_host.text().strip() or '127.0.0.1'}:{self.spin_port.value()}"
        webbrowser.open(url)

    def open_api(self):
        scheme = "https" if self.check_ssl.isChecked() else "http"
        url = f"{scheme}://{self.edit_host.text().strip() or '127.0.0.1'}:{self.spin_port.value()}/v1/models"
        webbrowser.open(url)

    def open_model_dir(self):
        d = self.edit_dir.text().strip()
        if os.path.isdir(d):
            os.startfile(d)  # noqa: S606
        else:
            QMessageBox.information(self, t('提示'), t('模型目录无效'))

    def open_bat_validator(self):
        """C3: 打开启动文件校验报告对话框（bat_validator.ValidateBatDialog）。"""
        try:
            ValidateBatDialog(self).exec()
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('打开校验器失败：{0}').format(e))

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
        self.statusBar().showMessage(t('正在检测工具…'), 2000)

    def _on_tool_scan_done(self):
        self._fill_tool_table()
        self._status_tip(t('工具检测完成'), 3000)

    def _fill_tool_table(self):
        rows = []
        for tool_def in tools_mod.ALL:
            rows.append((tool_def, self._tools_found.get(tool_def["id"])))
        self._tool_rows = [r[0] for r in rows]
        self.tool_table.setRowCount(len(rows))
        for r, (tool, path) in enumerate(rows):
            name_item = QTableWidgetItem(tool.get("name", tool["id"]))
            name_item.setData(Qt.ItemDataRole.UserRole, tool.get("id"))
            cat = t('终端') if tool.get("category") == "terminal" else t('应用')
            desc_item = QTableWidgetItem(tool.get("desc", ""))
            type_item = QTableWidgetItem(cat)
            status_item = QTableWidgetItem(path or t('未找到'))
            self.tool_table.setItem(r, 0, name_item)
            self.tool_table.setItem(r, 1, type_item)
            self.tool_table.setItem(r, 2, desc_item)
            self.tool_table.setItem(r, 3, status_item)
            btn = QPushButton(t('打开') if path else t('添加路径'))
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
        tool = next((td for td in tools_mod.ALL if td["id"] == tid), None)
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
            msg = t('已打开 {0}').format(tool['name'])
            if conn_info:
                msg += f"　·　{conn_info}"
            self.statusBar().showMessage(msg, 6000)
            self._on_server_log(msg)
        else:
            QMessageBox.warning(self, t('提示'), t('启动失败，请检查路径'))

    def _agent_connect(self, tool, workdir=None):
        """打开 Agent 工具时自动配置其连接当前 llama 服务。
        返回 (env, 连接说明文本, 附加启动参数)；服务未运行返回 (None, '服务未运行，无法自动连接', '')。"""
        if not self.server.running:
            return None, t('服务未运行，无法自动连接'), ""
        s = self._gather_server_cfg()
        scheme = "https" if s.get("ssl_enabled") else "http"
        base = f"{scheme}://{s['host']}:{s['port']}"
        base_v1 = base + "/v1"
        alias = model_alias(self.combo_model.currentData() or "")
        api_key = s.get("api_key", "")
        key = api_key or "llama"
        tid = tool.get("id")
        model_path = self.combo_model.currentData()

        if tid == "opencode" and opencode_launcher is not None:
            cfg = opencode_launcher.build_config(
                s["host"], s["port"], alias, s["ctx"], s["n_predict"], s["api_key"],
                scheme=scheme)
            wd = (workdir
                  or str(self.cfg.data.get("opencode_workdir") or "").strip()
                  or self.edit_dir.text().strip())
            try:
                opencode_launcher.write_config(wd, cfg)
                return None, t('已自动配置 opencode 连接 {0}（模型 {1}）').format(base_v1, alias), ""
            except Exception as e:
                return None, t('opencode 配置写入失败: {0}').format(e), ""
        if tid == "claude":
            return None, t('Claude Code 未自动连接（llama.cpp 的 Anthropic 接口兼容性有限），如需连接请手动配置 ANTHROPIC_BASE_URL'), ""
        if tid in ("codex", "aichat"):
            return {"OPENAI_BASE_URL": base_v1, "OPENAI_API_KEY": key,
                    "OPENAI_MODEL": alias}, t('已连接 {0}（OpenAI 接口，模型 {1}）').format(base_v1, alias), ""

        # 其他工具（含 GUI 应用）：复制连接信息到剪贴板
        try:
            text = t('模型: {0}\nAPI: {1}\n').format(alias, base_v1)
            if model_path:
                text += t('文件: {0}\n').format(model_path)
            QApplication.clipboard().setText(text)
            return None, t('已复制连接信息到剪贴板（{0}，模型 {1}）').format(base_v1, alias), ""
        except Exception:
            return None, t('服务地址 {0}（模型 {1}）').format(base_v1, alias), ""

    def open_selected_agent_tool(self):
        """打开 Agent 工具列表中当前高亮的工具（始终高亮选中行）。"""
        if not self._tool_rows:
            QMessageBox.information(self, t('提示'), t('Agent 工具列表为空'))
            return
        row = self.tool_table.currentRow()
        if row < 0 or row >= len(self._tool_rows):
            row = 0
        self._tool_open(self._tool_rows[row]["id"])

    def _prompt_add_path(self, tool):
        ret = QMessageBox.question(
            self, t('未找到'), t('未找到「{0}」，是否手动指定可执行文件路径？').format(tool.get('name', tool['id'])),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return
        start = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, t('选择 {0} 可执行文件').format(tool.get('name')), start,
                                              t('可执行文件 (*.exe *.cmd *.bat *.ps1);;所有文件 (*.*)'))
        if not path:
            return
        self.cfg.data.setdefault("tools", {})[tool["id"]] = {"path": path, "args": ""}
        self._tools_found[tool["id"]] = path
        self.cfg.save()
        self._fill_tool_table()
        self.statusBar().showMessage(t('已记录 {0} 路径').format(tool['name']), 3000)

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
        if self._pill is not None:
            self._pill.apply_theme(key)

    def _restore_geometry(self):
        """启动时恢复上次的窗口位置/大小（配置里存的是 [x, y, w, h]）。

        若保存的窗口中心已不在任何屏幕上（换显示器/分辨率变化），则忽略，
        避免窗口出现在屏幕外无法操作。"""
        geo = self.cfg.data.get("window_geometry")
        if not (isinstance(geo, (list, tuple)) and len(geo) == 4):
            return
        try:
            x, y, w, h = (int(v) for v in geo)
        except (TypeError, ValueError):
            return
        if w < 640 or h < 480:
            return
        if QApplication.screenAt(QPoint(x + w // 2, y + h // 2)) is None:
            return
        self.setGeometry(x, y, w, h)

    def _current_tab_order(self):
        order = []
        for i in range(self.tabs.count()):
            wdg = self.tabs.widget(i)
            for key, w in self._tab_widgets.items():
                if w is wdg:
                    order.append(key)
                    break
        return order

    def _restore_tab_order(self):
        """按配置里的 tab_order 恢复底部标签顺序（缺项/新标签自动追加到末尾）。"""
        order = self.cfg.data.get("tab_order")
        if not isinstance(order, list):
            return
        order = [k for k in order if k in self._tab_widgets]
        for target, key in enumerate(order):
            cur = self.tabs.indexOf(self._tab_widgets[key])
            if cur >= 0 and cur != target:
                self.tabs.tabBar().moveTab(cur, target)

    def _on_tab_moved(self, _from, _to):
        self.cfg.data["tab_order"] = self._current_tab_order()
        self.cfg.save()

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

    # ---------------------------------------------------------- 悬浮小窗（托盘胶囊）
    def _pill_set(self, updater):
        """把监控数据转发到悬浮窗（未创建时忽略）。"""
        if self._pill is not None:
            try:
                updater(self._pill)
            except Exception:
                pass

    def _update_pill(self, kind, *args):
        """缓存并转发悬浮窗数据（小窗未创建时先存起来，创建后回填）。"""
        self._pill_cache[kind] = args
        if self._pill is not None:
            try:
                getattr(self._pill, "set_" + kind)(*args)
            except Exception:
                pass

    def _seed_pill(self):
        """用缓存的最新数据初始化刚创建的悬浮窗（避免出现一片「—」）。"""
        if self._pill is None:
            return
        for kind, args in self._pill_cache.items():
            try:
                getattr(self._pill, "set_" + kind)(*args)
            except Exception:
                pass

    def _sync_pill_running(self):
        """悬浮窗运行状态 = 服务运行 且 主窗口不可见（可见时隐藏数据）。"""
        if self._pill is not None:
            running = self.server.running and not self.isVisible()
            self._pill.set_running(running)
            if running and self._running_model_name:
                self._pill.set_model(self._running_model_name)

    def _ensure_pill(self):
        """惰性创建悬浮窗并接好信号。"""
        if self._pill is None:
            self._pill = HoverPill(
                self.cfg, self.cfg.data.get("theme", "dark"),
                icon=self._load_icon(),
                save_pos=lambda x, y: self._save_pill_pos(x, y),
                on_hidden=self._on_pill_hidden)
            self._pill.open_main.connect(self._show_from_tray)
            self._pill.start_requested.connect(self.start_server)
            self._pill.stop_requested.connect(self.stop_server)
            self._pill.quit_requested.connect(self.quit_app)
            self._pill.hide_requested.connect(self._on_pill_session_hidden)
            self._seed_pill()
        return self._pill

    def _update_tray_hover(self):
        """按「配置开关 + 窗口是否隐藏」创建/显示/隐藏悬浮胶囊。"""
        if not self.cfg.data.get("hover_pill", True) or self._tray is None \
                or self.isVisible():
            if self._pill is not None:
                self._pill.hide()
            return
        pill = self._ensure_pill()
        if self._pill_session_hidden:
            return   # 右键「隐藏图标」后：本次最小化期间不再显示
        pill.apply_theme(self.cfg.data.get("theme", "dark"))
        pill.show_at_default()
        self._sync_pill_running()

    def _tray_show_pill(self):
        """托盘菜单「显示悬浮窗」：无视隐藏/停用状态，立即显示小窗。"""
        if not self.cfg.data.get("hover_pill", True):
            self.cfg.data["hover_pill"] = True
            self.cfg.save()
            self._loading = True
            self.check_hover_pill.setChecked(True)
            self._loading = False
        self._pill_session_hidden = False
        pill = self._ensure_pill()
        pill.apply_theme(self.cfg.data.get("theme", "dark"))
        pill.show_at_default()
        self._sync_pill_running()

    def _on_pill_session_hidden(self):
        """右键菜单「隐藏图标」：本次最小化期间不再显示，恢复主界面后清除。"""
        self._pill_session_hidden = True

    def _on_pill_hidden(self):
        """胶囊上点 ✕ 后：同步取消「高级参数」里的勾选（配置已被胶囊写为 False）。"""
        if self.check_hover_pill.isChecked():
            self._loading = True
            self.check_hover_pill.setChecked(False)
            self._loading = False

    def _save_pill_pos(self, x, y):
        self.cfg.data["hover_pill_pos"] = [int(x), int(y)]
        self.cfg.save()

    def _on_pill_hover_toggled(self, _checked=None):
        if self._loading:
            return
        self.cfg.data["hover_pill"] = self.check_hover_pill.isChecked()
        self.cfg.save()
        if self.check_hover_pill.isChecked():
            self._pill_session_hidden = False   # 重新勾选后忽略「隐藏图标」的临时状态
        self._update_tray_hover()

    def _set_tray_menu_state(self):
        """托盘右键菜单状态：启动/停止按服务状态置灰；小窗已显示时「显示悬浮窗」置灰。"""
        if self._tray is None or self._tray_act_start is None:
            return
        running = self.server.running
        self._tray_act_start.setEnabled(not running)
        self._tray_act_stop.setEnabled(running)
        visible = self._pill is not None and self._pill.isVisible()
        self._tray_act_pill.setEnabled(not visible)

    # ---------------------------------------------------------- 日志落盘
    def _status_tip(self, text, ms=4000, hold=False):
        """状态栏提示。hold=True 的消息在 ms 内不被普通消息抢掉
        （启动时多个后台检测并行完成，谁最后写谁说话，用户会看不到关键提醒）。"""
        now = time.time()
        if not hold and getattr(self, "_hint_until", 0.0) > now:
            return
        if hold:
            self._hint_until = now + ms / 1000.0
        try:
            self.statusBar().showMessage(text, ms)
        except Exception:
            pass

    def _log_file(self, text):
        try:
            logdir = os.path.join(self._data_dir(), "logs")
            os.makedirs(logdir, exist_ok=True)
            date = time.strftime("%Y%m%d")
            with open(os.path.join(logdir, t('运行日志-{0}.log').format(date)), "a", encoding="utf-8") as f:
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
            QMessageBox.information(self, t('提示'), t('无法打开日志目录: {0}').format(e))

    # ---------------------------------------------------------- 状态栏监控
    def _on_mem(self, percent, tip):
        self.label_mem.setText(t('内存 {0:.0f}%').format(percent))
        self.label_mem.setToolTip(tip)

    def _on_vram(self, text):
        if text:
            self.label_vram.setText(t('显存 {0}').format(text))
            self.label_vram.setVisible(True)
        else:
            self.label_vram.setText("")
            self.label_vram.setVisible(False)


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
        self.statusBar().showMessage(t('已应用采样预设: {0}').format(SAMPLING_PRESETS[idx][0]), 3000)

    def _on_sampling_manual(self, _v):
        if self._loading:
            return
        if self.combo_sampling.currentIndex() > 0:
            self.combo_sampling.setCurrentIndex(0)

    # ------------------------------------------------- 局域网共享 / HTTPS
    def _ssl_paths(self):
        """返回自签名证书的 (私钥, 证书) 路径（数据目录 certs/，非英文路径自动回退）。"""
        return default_cert_paths(self.cfg.data_dir())

    def _on_lan_toggled(self, checked):
        """勾选「局域网共享」→ host 填 0.0.0.0；取消 → 回 127.0.0.1。"""
        if not self._loading:
            host = self.edit_host.text().strip().lower()
            if checked and host in ("", "127.0.0.1", "localhost", "::1"):
                self.edit_host.setText("0.0.0.0")
            elif not checked and host in ("0.0.0.0", "::"):
                self.edit_host.setText("127.0.0.1")
        self._update_local_ip_label()

    def _on_ssl_toggled(self, _checked):
        self._update_local_ip_label()

    def _on_host_edited(self, _text):
        """手动改监听地址时反向同步「局域网共享」勾选状态。"""
        if not self._loading:
            is_lan = self.edit_host.text().strip() in ("0.0.0.0", "::")
            if self.check_lan.isChecked() != is_lan:
                self.check_lan.blockSignals(True)
                self.check_lan.setChecked(is_lan)
                self.check_lan.blockSignals(False)
        self._update_local_ip_label()

    def _update_local_ip_label(self):
        if not hasattr(self, "label_local_ip"):
            return
        ip = local_ipv4()
        scheme = "https" if self.check_ssl.isChecked() else "http"
        port = self.spin_port.value()
        if self.check_lan.isChecked():
            self.label_local_ip.setText(t('局域网访问：{0}://{1}:{2}').format(scheme, ip, port))
        else:
            self.label_local_ip.setText(t('本机 IP：{0}').format(ip))

    def _resolve_ssl(self, s):
        """按配置确保 HTTPS 证书存在并写回 ssl_key_file/ssl_cert_file。

        成功返回 True（scheme 用 https）；未启用 HTTPS 返回 False；
        生成失败抛出 RuntimeError 由调用方提示。"""
        if not s.get("ssl_enabled"):
            s["ssl_key_file"] = ""
            s["ssl_cert_file"] = ""
            return False
        key_path, cert_path = self._ssl_paths()
        ensure_self_signed_cert(key_path, cert_path)
        s["ssl_key_file"] = key_path
        s["ssl_cert_file"] = cert_path
        return True

    # ---------------------------------------------------------- 残留检测
    def _find_free_port(self, host, start, limit=50):
        """从 start+1 起找一个可用端口；找不到返回 None。"""
        for p in range(int(start) + 1, int(start) + 1 + int(limit)):
            if p > 65535:
                break
            if not port_in_use(host, p):
                return p
        return None

    def _suggest_free_port(self, host, port):
        """端口被占用时建议一个可用端口，确认后更新主界面端口号。"""
        free = self._find_free_port(host, port)
        if not free:
            self.statusBar().showMessage(t('端口 {0} 被占用，且未找到可用端口').format(port), 6000)
            return
        ret = QMessageBox.question(
            self, t('端口被占用'),
            t('端口 {0} 已被占用，可能已有服务在运行。\n是否改用可用端口 {1}？').format(port, free),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            self.spin_port.setValue(free)
            self.save_config()
            self._log_file(t('[端口] {0} 被占用，已改用 {1}').format(port, free))
            self.statusBar().showMessage(t('已改用端口 {0}').format(free), 5000)

    def _check_residual(self):
        if self.server.running:
            return
        if not self.check_residual.isChecked():
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
        host = self.edit_host.text().strip() or "127.0.0.1"
        port = self.spin_port.value()
        if procs:
            box = QMessageBox(self)
            box.setWindowTitle(t('检测到残留进程'))
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(
                t('检测到 {0} 个可能残留的 llama-server 进程\n（上次未正常退出，可能仍在占用显存/内存）。\n是否强制结束它们？').format(len(procs)))
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            cb = QCheckBox(t('不再提示（可在「高级参数」中重新开启）'))
            box.setCheckBox(cb)
            ret = box.exec()
            if cb.isChecked():
                self.cfg.data["check_residual"] = False
                self._loading = True
                self.check_residual.setChecked(False)
                self._loading = False
                self.cfg.save()
            if ret == QMessageBox.StandardButton.Yes:
                kill_all_llama_server()
                self._log_file(t('已强制清理残留的 llama-server 进程'))
                self.statusBar().showMessage(t('已清理残留进程，显存已释放'), 4000)
        # 端口占用 → 建议更换端口（与残留进程分开处理）
        if self.check_port_hint.isChecked() and port_in_use(host, port):
            self._suggest_free_port(host, port)

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
        self._tray.setToolTip(t('LLama 启动器'))
        menu = QMenu()
        act_show = menu.addAction(t('打开主界面'))
        act_show.triggered.connect(self._show_from_tray)
        self._tray_act_pill = menu.addAction(t('显示悬浮窗'))
        self._tray_act_pill.setToolTip(
            t('立即在屏幕右下角显示悬浮小窗（若之前被 ✕ 停用或右键隐藏，会一并恢复）'))
        self._tray_act_pill.triggered.connect(self._tray_show_pill)
        self._tray_act_start = menu.addAction(t('启动模型'))
        self._tray_act_start.triggered.connect(self.start_server)
        self._tray_act_stop = menu.addAction(t('停止模型'))
        self._tray_act_stop.triggered.connect(self.stop_server)
        menu.addSeparator()
        act_quit = menu.addAction(t('退出'))
        act_quit.triggered.connect(self.quit_app)
        menu.aboutToShow.connect(self._set_tray_menu_state)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()
        self._set_tray_menu_state()

    def _show_from_tray(self):
        if self._pill is not None:
            self._pill.hide()
        self._pill_session_hidden = False
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._sync_pill_running()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def showEvent(self, event):
        # 主窗口任何时候重新可见：清除悬浮窗「本次隐藏」状态
        self._pill_session_hidden = False
        super().showEvent(event)

    def _switch_language(self, code):
        """切换界面语言：写入配置并提示重启生效。"""
        cur = self.cfg.data.get("language") or "auto"
        if code == cur:
            return
        self.cfg.data["language"] = code
        self.cfg.save()
        if i18n.resolve(code) == i18n.lang():
            self.statusBar().showMessage(t('界面已是该语言，无需重启'), 5000)
            return
        ret = QMessageBox.question(
            self, t('切换语言'),
            t('语言设置已保存。\n切换语言需要重启启动器才能完全生效，是否立即重启？\n（正在运行的模型服务会被停止）'),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            self._restart_app()

    def _restart_app(self):
        import subprocess
        if getattr(sys, "frozen", False):
            cmd = [sys.executable]
        else:
            cmd = [sys.executable, os.path.join(self.base_dir, "main.py")]
        try:
            subprocess.Popen(cmd, cwd=self.base_dir)
        except Exception:
            return
        self.quit_app()

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
