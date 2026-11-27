"""模型下载 Tab（v0.6）：HuggingFace 仓库检索 + 左右双列 + 目录树 + 批量下载。

布局：
- 顶部搜索卡：组织/作者（可输入 + 常用下拉）/ 模型名称 / 辅助关键词 / 匹配方式；
- 工具栏：加载更多、打开下载目录、取消、清空、每页数量、排序；
- 中部：左列 = 模型仓库；右列 = 目录树（按文件夹分组，支持勾选整个文件夹）；
- 底部：保存目录、仓库信息（含目录文本 + 可点击 HF 链接）、操作日志。
"""
import os
import threading

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import hf_browse
from .model_downloader import ModelDownloader
from .model_scanner import human_size, natural_key
from .i18n import t
from .ui.kit import Badge, Card, SectionHeader

# 常用的 GGUF 发布组织/作者（仍允许手动输入任意值）
COMMON_AUTHORS = [
    "unsloth", "ggml-org", "bartowski", "Qwen", "google", "meta-llama",
    "mistralai", "deepseek-ai", "microsoft", "nvidia", "TheBloke",
]


class HFDownloadTab(QWidget):
    """嵌入主窗口底部 Tab 区的下载面板。"""

    models_changed = pyqtSignal()   # 有文件下载完成，提示主窗口刷新模型列表
    _search_done = pyqtSignal()     # 后台检索完成（回主线程）
    _files_done = pyqtSignal()      # 后台取仓库文件列表完成（回主线程）

    # 仓库表列 → 排序键
    _REPO_COLS = {0: "id", 1: "downloads", 2: "likes", 3: "last_modified"}

    def __init__(self, main_win, parent=None):
        super().__init__(parent)
        self.mw = main_win
        self.downloader = ModelDownloader()
        self._repo_files_cache = {}
        self._repos_all = []
        self._limit = 50
        self._building = False
        self._cur_repo_id = ""
        self._file_state = {}          # key -> {item, progress, status, dest, path, installed}
        self._cur_files = []           # 当前仓库文件（排序后重绘用）
        self._sort_key = "downloads"   # 仓库排序键
        self._sort_desc = True
        self._file_sort_key = "name"   # 文件排序键
        self._file_sort_desc = False
        self._auto_save_dir = True     # 保存目录是否跟随主页模型目录

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ---- 搜索卡 ----
        search_card = Card(padding=10, spacing=6)
        search_head = SectionHeader(t('模型下载'),
                                    t('在 HuggingFace 上检索 GGUF 仓库；右侧按目录分组，可整组下载。'))
        search_card.add(search_head)
        search = QHBoxLayout()
        search.setSpacing(6)
        search.addWidget(QLabel(t('组织/作者:')))
        self.edit_org = QComboBox()
        self.edit_org.setEditable(True)
        self.edit_org.addItems(COMMON_AUTHORS)
        self.edit_org.setCurrentText("unsloth")
        self.edit_org.setMinimumWidth(120)
        self.edit_org.setToolTip(
            t('按发布者/组织过滤仓库（对应 HF author 参数）。可直接输入任意作者，\n'
              '也可从常用作者下拉中选择；默认 unsloth。'))
        search.addWidget(self.edit_org, 1)

        search.addWidget(QLabel(t('模型名称/版本:')))
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText(t('B 模型名称/版本，如 Qwen3-8B'))
        self.edit_name.setToolTip(t('按仓库名称/版本关键词检索（对应 HF search 参数），例如 Qwen3-8B、GLM-4.5。'))
        search.addWidget(self.edit_name, 1)

        search.addWidget(QLabel(t('辅助关键词:')))
        self.edit_kw = QLineEdit()
        self.edit_kw.setPlaceholderText(t('C 辅助关键词，如 GGUF'))
        self.edit_kw.setToolTip(t('辅助过滤词：在返回的仓库名中再做一次本地过滤，用于收窄结果。'))
        search.addWidget(self.edit_kw, 1)

        search.addWidget(QLabel(t('匹配:')))
        self.combo_match = QComboBox()
        self.combo_match.addItems([t('并（同时满足）'), t('或（任一满足）')])
        self.combo_match.setToolTip(t('A/B/C 三个条件的组合方式：并=全部满足；或=任一满足。'))
        search.addWidget(self.combo_match)

        self.btn_search = QPushButton(t('检索仓库'))
        self.btn_search.setProperty("variant", "primary")
        self.btn_search.setToolTip(t('在 HuggingFace 上按 A/B/C 条件检索 GGUF 模型仓库（联网）'))
        self.btn_search.clicked.connect(self.do_search)
        search.addWidget(self.btn_search)
        search_card.add_layout(search)
        root.addWidget(search_card)

        # ---- 工具栏 ----
        bar_card = Card(padding=8, spacing=4)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.btn_more = QPushButton(t('↓ 加载更多'))
        self.btn_more.setProperty("variant", "ghost")
        self.btn_more.setToolTip(t('增大每页数量，追加更多仓库结果（最多 1000 条）'))
        self.btn_open_dir = QPushButton(t('打开下载目录'))
        self.btn_open_dir.setProperty("variant", "ghost")
        self.btn_open_dir.setToolTip(t('打开模型下载目录（已选仓库时打开其子目录）'))
        self.btn_cancel = QPushButton(t('取消当前'))
        self.btn_cancel.setProperty("variant", "ghost")
        self.btn_cancel.setToolTip(t('停止当前下载（保留已下载的 .part，下次可续传）'))
        self.btn_clearq = QPushButton(t('清空队列'))
        self.btn_clearq.setProperty("variant", "ghost")
        for b in (self.btn_more, self.btn_open_dir, self.btn_cancel, self.btn_clearq):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(QLabel(t('每页:')))
        self.combo_page = QComboBox()
        for n in (20, 50, 100, 200, 500):
            self.combo_page.addItem(str(n), n)
        self.combo_page.setCurrentText("50")
        self.combo_page.setToolTip(t('每次检索显示的仓库数量（点击「检索仓库」后生效；「加载更多」按此数量累加）'))
        bar.addWidget(self.combo_page)
        bar.addWidget(QLabel(t('排序:')))
        self.combo_sort = QComboBox()
        for name in (t('下载量 ↓'), t('点赞 ↓'), t('名称 ↑'), t('最近更新')):
            self.combo_sort.addItem(name)
        self.combo_sort.setCurrentText(t('下载量 ↓'))
        self.combo_sort.setToolTip(t('与点击仓库表表头排序等效'))
        bar.addWidget(self.combo_sort)
        self.label_status = Badge(t('就绪'), "info")
        bar.addWidget(self.label_status)
        bar_card.add_layout(bar)
        root.addWidget(bar_card)

        # ---- 上下可拖动分栏：上=左右双列，下=保存目录/仓库信息/操作日志 ----
        vsplit = QSplitter(Qt.Orientation.Vertical)
        vsplit.setChildrenCollapsible(False)

        hsplit = QSplitter(Qt.Orientation.Horizontal)
        hsplit.setChildrenCollapsible(False)

        left = Card(padding=8, spacing=4)
        left.add(SectionHeader(t('模型仓库'), t('点击表头可排序；选中一行查看右侧文件。')))
        self.table_repo = QTableWidget(0, 4)
        self.table_repo.setHorizontalHeaderLabels([t('模型仓库'), t('下载量'), t('点赞'), t('最近更新')])
        self._setup_table(self.table_repo, [190, 84, 56, 86])
        self.table_repo.horizontalHeader().setSectionsClickable(True)
        self.table_repo.horizontalHeader().sectionClicked.connect(self._on_repo_header_clicked)
        self.table_repo.horizontalHeader().sectionDoubleClicked.connect(
            lambda c: self.table_repo.resizeColumnToContents(c))
        self.table_repo.horizontalHeaderItem(3).setToolTip(
            t('仓库在 HuggingFace 上最近一次提交更新的日期（lastModified）'))
        left.add(self.table_repo, 1)
        hsplit.addWidget(left)

        right = Card(padding=8, spacing=4)
        right_head = SectionHeader(t('仓库目录'), t('勾选文件夹 = 整组下载；勾选单个文件 = 只下该分片。'))
        self.btn_download_sel = QPushButton(t('下载选中'))
        self.btn_download_sel.setProperty("variant", "primary")
        self.btn_download_sel.clicked.connect(self._download_checked)
        self.chk_all_files = QCheckBox(t('全选'))
        self.chk_all_files.toggled.connect(self._toggle_all_files)
        self.btn_expand = QPushButton(t('展开/折叠'))
        self.btn_expand.setProperty("variant", "ghost")
        self.btn_expand.clicked.connect(self._toggle_expand)
        right_head.add_action(self.chk_all_files)
        right_head.add_action(self.btn_download_sel)
        right_head.add_action(self.btn_expand)
        right.add(right_head)

        self.label_repo_files = QLabel(t('未选择仓库'))
        self.label_repo_files.setObjectName("Muted")
        right.add(self.label_repo_files)

        self.tree_files = QTreeWidget()
        self.tree_files.setColumnCount(4)
        self.tree_files.setHeaderLabels([t('名称'), t('大小'), t('状态'), t('进度')])
        self.tree_files.setAlternatingRowColors(True)
        self.tree_files.setRootIsDecorated(True)
        self.tree_files.setUniformRowHeights(True)
        hh = self.tree_files.header()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree_files.setColumnWidth(1, 90)
        self.tree_files.setColumnWidth(2, 90)
        self.tree_files.setColumnWidth(3, 150)
        self.tree_files.itemChanged.connect(self._on_tree_item_changed)
        self.tree_files.itemDoubleClicked.connect(self._on_file_double)
        right.add(self.tree_files, 1)
        hsplit.addWidget(right)

        hsplit.setStretchFactor(0, 1)
        hsplit.setStretchFactor(1, 1)
        hsplit.setSizes([420, 620])
        vsplit.addWidget(hsplit)

        # ---- 下半部分：保存目录 + 仓库信息 + 操作日志 ----
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel(t('保存到:')))
        self.edit_save_dir = QLineEdit()
        self.edit_save_dir.setPlaceholderText(t('默认 = 主页的模型目录；下载时按仓库名建子文件夹'))
        self.edit_save_dir.setToolTip(
            t('模型下载根目录。默认显示主页「模型目录」；下载时会在其下按「仓库名」建立子文件夹。'))
        btn_browse = QPushButton(t('浏览…'))
        btn_browse.setProperty("variant", "ghost")
        dir_row.addWidget(self.edit_save_dir, 1)
        dir_row.addWidget(btn_browse)
        bl.addLayout(dir_row)

        info_log = QHBoxLayout()
        info_log.setSpacing(6)
        self.group_repo_info = QGroupBox(t('仓库信息'))
        gv = QVBoxLayout(self.group_repo_info)
        gv.setContentsMargins(6, 4, 6, 4)
        self.repo_info_view = QTextBrowser()
        self.repo_info_view.setOpenExternalLinks(True)
        self.repo_info_view.setPlaceholderText(t('点击左侧仓库查看信息'))
        gv.addWidget(self.repo_info_view)
        info_log.addWidget(self.group_repo_info, 1)

        self.group_log = QGroupBox(t('操作日志'))
        gl = QVBoxLayout(self.group_log)
        gl.setContentsMargins(6, 4, 6, 4)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        gl.addWidget(self.log_view)
        info_log.addWidget(self.group_log, 1)
        bl.addLayout(info_log)

        bottom.setMinimumHeight(130)
        vsplit.addWidget(bottom)
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 1)
        vsplit.setSizes([380, 170])
        root.addWidget(vsplit, 1)

        # ---- 连接 ----
        self.btn_more.clicked.connect(self.load_more)
        self.btn_open_dir.clicked.connect(self._open_download_dir)
        self.combo_page.currentIndexChanged.connect(self._on_page_size_changed)
        self.btn_cancel.clicked.connect(
            lambda: (self.downloader.cancel_current(), self._log(t('已请求取消当前下载'))))
        self.btn_clearq.clicked.connect(
            lambda: (self.downloader.clear_queue(), self._log(t('队列已清空'))))
        self.combo_sort.currentIndexChanged.connect(self._on_sort_combo)
        self.table_repo.currentItemChanged.connect(self._on_repo_selected)
        btn_browse.clicked.connect(self._browse_dir)
        self.edit_save_dir.textEdited.connect(self._on_save_dir_edited)

        d = self.downloader
        d.task_started.connect(self._on_task_started)
        d.progress.connect(self._on_progress)
        d.task_done.connect(self._on_task_done)
        d.task_failed.connect(self._on_task_failed)
        d.queue_empty.connect(self._on_queue_empty)

        self._search_done.connect(self._on_search_done)
        self._files_done.connect(self._on_files_done)

        # 保存目录默认跟随主页「模型目录」
        if hasattr(self.mw, "edit_dir"):
            self.mw.edit_dir.textChanged.connect(lambda _t: self.sync_default_dir())
        self.sync_default_dir()

    @staticmethod
    def _setup_table(tbl, widths):
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        tbl.verticalHeader().setVisible(False)
        tbl.setAlternatingRowColors(True)
        hh = tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setMinimumSectionSize(40)
        for i, w in enumerate(widths):
            tbl.setColumnWidth(i, w)

    # ------------------------------------------------------------- 保存目录
    def sync_default_dir(self):
        """保存目录留空时，默认显示主页的模型目录路径。"""
        if not getattr(self, "_auto_save_dir", True):
            return
        d = (self.mw.edit_dir.text().strip() if hasattr(self.mw, "edit_dir") else "")
        self.edit_save_dir.setText(d)

    def _on_save_dir_edited(self, _text):
        self._auto_save_dir = False
        self.mw.cfg.data["hf_download_dir"] = self.edit_save_dir.text().strip()

    def _save_dir(self):
        d = self.edit_save_dir.text().strip()
        if not d:
            d = (self.mw.cfg.data.get("hf_download_dir", "") or "").strip()
        if not d and hasattr(self.mw, "edit_dir"):
            d = self.mw.edit_dir.text().strip()
        if not d:
            d = getattr(self.mw, "base_dir", "") or os.getcwd()
        return d

    # ------------------------------------------------------------- 检索
    def _org_text(self):
        return (self.edit_org.currentText() or "").strip()

    def _match_repo(self, repo, org, name, kw, mode):
        rid = (repo.get("id") or "").lower()
        author = rid.split("/", 1)[0] if "/" in rid else rid
        checks = []
        if org:
            checks.append(org.lower() in author or org.lower() in rid)
        if name:
            checks.append(name.lower() in rid)
        if kw:
            checks.append(kw.lower() in rid)
        if not checks:
            return True
        return all(checks) if mode == 0 else any(checks)

    def do_search(self):
        org = self._org_text()
        name = self.edit_name.text().strip()
        kw = self.edit_kw.text().strip()
        if not org and not name and not kw:
            org = "unsloth"   # 保持原有默认检索组织
        mode = self.combo_match.currentIndex()   # 0=并, 1=或
        self._limit = int(self.combo_page.currentData() or 50)
        self.btn_search.setEnabled(False)
        self.label_status.set_status(t('检索中…'), "info")
        self._log(t("正在检索 组织='{0}' 名称='{1}' 关键词='{2}'（{3}）…").format(
            org, name, kw, t('并') if mode == 0 else t('或')))

        def work():
            author = org
            search = ""
            if mode == 0:
                search = name or kw
            else:
                if not author:
                    search = name or kw
            try:
                repos = hf_browse.list_repos(author=author, search=search,
                                             limit=self._limit)
            except Exception as e:
                self._repos_error = str(e)
                try:
                    self._search_done.emit()
                except RuntimeError:
                    pass
                return
            repos = [r for r in repos if self._match_repo(r, org, name, kw, mode)]
            self._repos_result = repos
            self._repos_error = None
            try:
                self._search_done.emit()
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def load_more(self):
        if self._limit >= 1000:
            self._log(t('已到加载上限（1000 条）'))
            return
        step = int(self.combo_page.currentData() or 50)
        self._limit = min(1000, self._limit + step)
        self.do_search()

    def _on_page_size_changed(self, _idx):
        self._limit = int(self.combo_page.currentData() or 50)
        if getattr(self, "_repos_all", None):
            self.do_search()

    def _on_search_done(self):
        self.btn_search.setEnabled(True)
        err = getattr(self, "_repos_error", None)
        if err:
            self.label_status.set_status(t('检索失败'), "err")
            self._log(t('检索失败: {0}').format(err))
            return
        repos = getattr(self, "_repos_result", None) or []
        self._repos_all = list(repos)
        self._fill_repo_table()
        self.label_status.set_status(t('共 {0} 个仓库（每页 {1}）').format(len(repos), self._limit), "ok")
        self._log(t('找到 {0} 个仓库').format(len(repos)))

    # ------------------------------------------------------------- 仓库排序
    def _on_sort_combo(self, idx):
        self._sort_key = {0: "downloads", 1: "likes", 2: "id", 3: "last_modified"}.get(idx, "downloads")
        self._sort_desc = idx != 2
        self._fill_repo_table()

    def _sync_sort_combo(self):
        idx = {"downloads": 0, "likes": 1, "id": 2, "last_modified": 3}.get(self._sort_key, 0)
        self.combo_sort.blockSignals(True)
        self.combo_sort.setCurrentIndex(idx)
        self.combo_sort.blockSignals(False)

    def _on_repo_header_clicked(self, col):
        key = self._REPO_COLS.get(col)
        if not key:
            return
        if key == self._sort_key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key = key
            self._sort_desc = key != "id"
        self._sync_sort_combo()
        self._fill_repo_table()

    def _sort_repos(self, repos):
        key, rev = self._sort_key, self._sort_desc
        if key == "id":
            repos.sort(key=lambda r: r["id"].lower(), reverse=rev)
        elif key == "likes":
            repos.sort(key=lambda r: (r["likes"], r["downloads"]), reverse=rev)
        elif key == "last_modified":
            repos.sort(key=lambda r: (r.get("last_modified") or ""), reverse=rev)
        else:
            repos.sort(key=lambda r: r["downloads"], reverse=rev)

    def _fill_repo_table(self):
        repos = list(getattr(self, "_repos_all", None) or [])
        self._sort_repos(repos)
        self.table_repo.setRowCount(len(repos))
        for r, repo in enumerate(repos):
            it = QTableWidgetItem(repo["id"])
            it.setData(Qt.ItemDataRole.UserRole, repo)
            it.setToolTip(repo["id"])
            self.table_repo.setItem(r, 0, it)
            self.table_repo.setItem(r, 1, QTableWidgetItem(f"{repo['downloads']:,}"))
            self.table_repo.setItem(r, 2, QTableWidgetItem(str(repo["likes"])))
            self.table_repo.setItem(r, 3, QTableWidgetItem(repo.get("last_modified", "")))

    # ------------------------------------------------------------- 仓库文件
    def _on_repo_selected(self, cur, _prev):
        if self._building or cur is None:
            return
        repo = cur.data(Qt.ItemDataRole.UserRole)
        if not repo:
            return
        rid = repo["id"]
        self._cur_repo_id = rid
        cached = self._repo_files_cache.get(rid)
        if cached is not None:
            self._show_files(rid, cached)
            return
        self.label_repo_files.setText(t('仓库 {0} 的文件（加载中…）').format(rid))

        def work():
            try:
                info = hf_browse.repo_files(rid)
            except Exception as e:
                self._files_error = (rid, str(e))
                try:
                    self._files_done.emit()
                except RuntimeError:
                    pass
                return
            self._repo_files_cache[rid] = info
            self._files_result = (rid, info)
            self._files_error = None
            try:
                self._files_done.emit()
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_files_done(self):
        err = getattr(self, "_files_error", None)
        if err:
            rid, msg = err
            self.label_repo_files.setText(t('仓库 {0} 加载失败').format(rid))
            self._log(t('获取文件列表失败: {0}').format(msg))
            return
        rid, info = getattr(self, "_files_result", (None, None))
        if info is not None:
            self._show_files(rid, info)

    def _show_files(self, rid, info):
        self._building = True
        self._cur_repo_id = rid
        try:
            self._cur_files = list(info["files"])
            self._render_files()
            if self._cur_files:
                folders = {self._folder_of(f["path"]) for f in self._cur_files}
                self.label_repo_files.setText(
                    t('仓库 {0}：{1} 个文件 / {2} 个目录（下载量 {3:,}）').format(
                        rid, len(self._cur_files), len(folders), info['downloads']))
            else:
                self.label_repo_files.setText(
                    t('仓库 {0}：未找到 .gguf 文件（该仓库可能不是 GGUF 仓库）').format(rid))
                self._log(t('{0} 内没有 .gguf 文件').format(rid))
            self._show_repo_info(rid, info)
        finally:
            self._building = False

    @staticmethod
    def _folder_of(path):
        d = os.path.dirname(str(path).replace("\\", "/"))
        return d or "."

    def _render_files(self):
        files = list(self._cur_files)
        key, rev = self._file_sort_key, self._file_sort_desc
        if key == "size":
            files.sort(key=lambda f: f["size"], reverse=rev)
        else:
            files.sort(key=lambda f: natural_key(f["path"]), reverse=rev)
        self._building = True
        self.tree_files.clear()
        self._file_state.clear()
        groups = {}
        for f in files:
            groups.setdefault(self._folder_of(f["path"]), []).append(f)
        for folder in sorted(groups, key=natural_key):
            items = groups[folder]
            total = sum(int(f.get("size") or 0) for f in items)
            top = QTreeWidgetItem(self.tree_files)
            top.setText(0, ("📁 " + folder) if folder != "." else t('📁 根目录'))
            top.setText(1, human_size(total))
            top.setText(2, t('{0} 个文件').format(len(items)))
            top.setData(0, Qt.ItemDataRole.UserRole, {"kind": "folder", "folder": folder})
            top.setFlags(top.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            top.setCheckState(0, Qt.CheckState.Unchecked)
            for f in items:
                self._append_file_item(top, self._cur_repo_id, f)
            top.setExpanded(True)
        self._building = False

    def _append_file_item(self, parent, rid, f):
        it = QTreeWidgetItem(parent)
        it.setText(0, f["path"])
        it.setText(1, human_size(f["size"]))
        key = f"{rid}::{f['path']}"
        dest = self._dest_for(rid, f["path"])
        installed = os.path.isfile(dest) and os.path.getsize(dest) > 0
        it.setText(2, t('已安装') if installed else t('未安装'))
        it.setForeground(2, QBrush(QColor("#43d17a" if installed else "#8a8a8a")))
        it.setText(3, "")
        it.setData(0, Qt.ItemDataRole.UserRole, {"kind": "file", "path": f["path"], "size": f["size"]})
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(0, Qt.CheckState.Unchecked)
        it.setToolTip(0, f["path"])
        self._file_state[key] = {
            "item": it, "dest": dest, "path": f["path"], "installed": installed,
        }

    def _on_tree_item_changed(self, item, column):
        if self._building or column != 0:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("kind") == "folder":
            state = item.checkState(0)
            if state != Qt.CheckState.PartiallyChecked:
                self._building = True
                for i in range(item.childCount()):
                    item.child(i).setCheckState(0, state)
                self._building = False

    def _toggle_all_files(self, checked):
        self._building = True
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.tree_files.topLevelItemCount()):
            top = self.tree_files.topLevelItem(i)
            top.setCheckState(0, state)
            for j in range(top.childCount()):
                top.child(j).setCheckState(0, state)
        self._building = False

    def _toggle_expand(self):
        expanded = any(self.tree_files.topLevelItem(i).isExpanded()
                       for i in range(self.tree_files.topLevelItemCount()))
        for i in range(self.tree_files.topLevelItemCount()):
            self.tree_files.topLevelItem(i).setExpanded(not expanded)

    def _checked_files(self):
        out = []
        for i in range(self.tree_files.topLevelItemCount()):
            top = self.tree_files.topLevelItem(i)
            for j in range(top.childCount()):
                child = top.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    out.append(child)
        return out

    def _download_checked(self):
        items = self._checked_files()
        if not items:
            QMessageBox.information(self, t('提示'), t('请先勾选要下载的文件或文件夹。'))
            return
        for it in items:
            data = it.data(0, Qt.ItemDataRole.UserRole) or {}
            self._enqueue_path(self._cur_repo_id, data.get("path", ""), it)

    def _on_file_double(self, item, _col):
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("kind") != "file":
            return
        rid = self._cur_repo_id
        dest = self._dest_for(rid, data["path"])
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            self.mw.select_model_path(dest)
        else:
            self._enqueue_path(rid, data["path"], item)

    def _show_repo_info(self, rid, info):
        tags = info.get("tags") or []
        tag_txt = "、".join(tags[:12]) if tags else "—"
        files = info.get("files") or []
        tree_lines = []
        groups = {}
        for f in files:
            groups.setdefault(self._folder_of(f["path"]), []).append(f)
        for folder in sorted(groups, key=natural_key):
            tree_lines.append(("📁 " + folder) if folder != "." else t("📁 根目录"))
            for f in groups[folder]:
                tree_lines.append("    {0}    {1}".format(f["path"], human_size(f.get("size") or 0)))
        tree_txt = html_escape("\n".join(tree_lines)) if tree_lines else t('（没有 .gguf 文件）')
        url = f"https://huggingface.co/{rid}"
        body = (
            t('<b>{0}</b><br>下载量: {1:,}　|　点赞: {2}　|　最近更新: {3}<br>流水线: {4}<br>标签: {5}')
            .format(rid, info.get('downloads', 0), info.get('likes', 0),
                    info.get('last_modified') or '—', info.get('pipeline_tag') or '—', tag_txt)
        )
        body += ("<hr><b>" + t('目录结构') + "</b>"
                 "<pre style='white-space:pre-wrap;font-family:Consolas,monospace;'>" + tree_txt + "</pre>"
                 "<p><a href='{0}'>".format(html_escape(url, quote=True)) + t('打开 HuggingFace 仓库页面') + "</a></p>")
        self.repo_info_view.setHtml(body)
    # ------------------------------------------------------------- 下载队列
    def _repo_dir(self, repo_id=None):
        rid = repo_id or self._cur_repo_id
        name = (rid.split("/")[-1] if rid else "hf").strip() or "hf"
        return os.path.join(self._save_dir(), name)

    def _dest_for(self, repo_id, path):
        rel = str(path).replace("\\", "/").split("/")
        return os.path.join(self._repo_dir(repo_id), *rel)

    def _enqueue_path(self, rid, path, item=None):
        if not path:
            return
        dest = self._dest_for(rid, path)
        try:
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self.mw, t('提示'), t('无法创建目录：\n{0}').format(e))
            return
        key = f"{rid}::{path}"
        st = self._file_state.get(key)
        if st and item is not None:
            st["item"] = item
        if st:
            st["item"].setText(3, t('排队中…'))
        url = hf_browse.file_url(rid, path)
        self._log(t('加入下载: {0} → {1}').format(path, dest))
        self.downloader.enqueue(url, dest, label=key)

    # ------------------------------------------------------------- 进度回调
    def _on_task_started(self, label):
        st = self._file_state.get(label)
        if st:
            try:
                st["item"].setText(3, "0%")
            except RuntimeError:
                pass
        self._log(t('开始下载: ') + label)

    def _on_progress(self, label, done, total, speed):
        st = self._file_state.get(label)
        if not st:
            return
        if total > 0:
            pct = int(done * 100 // max(1, total))
            txt = f"{human_size(done)} / {human_size(total)}  ({pct}%)"
        else:
            txt = human_size(done)
        if speed > 0:
            txt += f"  {human_size(speed)}/s"
        try:
            st["item"].setText(3, txt)
        except RuntimeError:
            pass

    def _on_task_done(self, label, path):
        st = self._file_state.get(label)
        if st:
            st["installed"] = True
            try:
                st["item"].setText(2, t('已安装'))
                st["item"].setForeground(2, QBrush(QColor("#43d17a")))
                st["item"].setText(3, t('已安装'))
                st["item"].setCheckState(0, Qt.CheckState.Unchecked)
            except RuntimeError:
                pass
        self._log(t('✔ 下载完成: {0}').format(path))
        self.models_changed.emit()

    def _on_task_failed(self, label, err):
        st = self._file_state.get(label)
        if st:
            try:
                st["item"].setText(3, t('失败'))
            except RuntimeError:
                pass
        self._log(t('✘ 下载失败: {0} — {1}').format(label, err))

    def _on_queue_empty(self):
        self.btn_search.setEnabled(True)
        self._log(t('队列已全部完成'))

    # ------------------------------------------------------------- 其他
    def _open_download_dir(self):
        d = self._repo_dir() if self._cur_repo_id else self._save_dir()
        try:
            os.makedirs(d, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))
        except OSError as e:
            QMessageBox.critical(self.mw, t('错误'), t('无法打开下载目录：\n{0}').format(e))

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(
            self.mw, t('选择模型保存目录'), self._save_dir() or os.path.expanduser("~"))
        if d:
            self._auto_save_dir = False
            self.edit_save_dir.setText(d)
            self.mw.cfg.data["hf_download_dir"] = d

    def _log(self, text):
        try:
            from datetime import datetime
            self.log_view.appendPlainText(f"[{datetime.now():%H:%M:%S}] {text}")
        except RuntimeError:
            pass


def html_escape(text, quote=False):
    import html
    return html.escape(str(text), quote=quote)
