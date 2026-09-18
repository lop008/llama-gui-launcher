"""模型下载 Tab（功能 5）：检索 HuggingFace 仓库 + 左右双列浏览 + 断点续传下载。

布局：
- 顶部：三个搜索框（组织/作者 / 模型名称/版本 / 辅助关键词）+ 匹配方式（并/或）+ 检索；
- 工具栏：加载更多、打开下载目录、取消当前、清空队列、排序；
- 中部：左列 = 模型仓库（点表头排序），右列 = 选中仓库内的 GGUF 文件（文件名/大小/已安装/下载/进度）；
- 底部（可上下拖动调整比例）：保存目录、仓库信息、操作日志。
"""
import os
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from . import hf_browse
from .model_downloader import ModelDownloader
from .model_scanner import human_size, natural_key


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
        self._file_state = {}          # key -> {btn, progress, status, dest, path}
        self._cur_files = []           # 当前仓库文件（排序后重绘用）
        self._sort_key = "downloads"   # 仓库排序键
        self._sort_desc = True
        self._file_sort_key = "name"   # 文件排序键
        self._file_sort_desc = False
        self._auto_save_dir = True     # 保存目录是否跟随主页模型目录

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        # ---- 搜索行：A 组织 / B 模型名称 / C 关键词 + 匹配方式 ----
        search = QHBoxLayout()
        search.addWidget(QLabel("组织/作者:"))
        self.edit_org = QLineEdit("unsloth")
        self.edit_org.setPlaceholderText("A 组织/作者，如 unsloth")
        self.edit_org.setToolTip("按发布者/组织过滤仓库（对应 HF author 参数），例如 unsloth、Qwen。")
        search.addWidget(self.edit_org, 1)

        search.addWidget(QLabel("模型名称/版本:"))
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("B 模型名称/版本，如 Qwen3-8B")
        self.edit_name.setToolTip("按仓库名称/版本关键词检索（对应 HF search 参数），例如 Qwen3-8B、GLM-4.5。")
        search.addWidget(self.edit_name, 1)

        search.addWidget(QLabel("辅助关键词:"))
        self.edit_kw = QLineEdit()
        self.edit_kw.setPlaceholderText("C 辅助关键词，如 GGUF")
        self.edit_kw.setToolTip("辅助过滤词：在返回的仓库名中再做一次本地过滤，用于收窄结果。")
        search.addWidget(self.edit_kw, 1)

        search.addWidget(QLabel("匹配:"))
        self.combo_match = QComboBox()
        self.combo_match.addItems(["并（同时满足）", "或（任一满足）"])
        self.combo_match.setToolTip("A/B/C 三个条件的组合方式：并=全部满足；或=任一满足。")
        search.addWidget(self.combo_match)

        self.btn_search = QPushButton("检索仓库")
        self.btn_search.setToolTip("在 HuggingFace 上按 A/B/C 条件检索 GGUF 模型仓库（联网）")
        search.addWidget(self.btn_search)
        root.addLayout(search)

        # ---- 工具栏行 ----
        bar = QHBoxLayout()
        self.btn_more = QPushButton("↓ 加载更多")
        self.btn_more.setToolTip("增大每页数量，追加更多仓库结果（最多 500 条）")
        self.btn_open_dir = QPushButton("打开下载目录")
        self.btn_open_dir.setToolTip("打开模型下载目录（已选仓库时打开其子目录）")
        self.btn_cancel = QPushButton("取消当前")
        self.btn_cancel.setToolTip("停止当前下载（保留已下载的 .part，下次可续传）")
        self.btn_clearq = QPushButton("清空队列")
        bar.addWidget(self.btn_more)
        bar.addWidget(self.btn_open_dir)
        bar.addWidget(self.btn_cancel)
        bar.addWidget(self.btn_clearq)
        bar.addStretch(1)
        bar.addWidget(QLabel("每页:"))
        self.combo_page = QComboBox()
        for n in (20, 50, 100, 200, 500):
            self.combo_page.addItem(str(n), n)
        self.combo_page.setCurrentText("50")
        self.combo_page.setToolTip("每次检索显示的仓库数量（点击「检索仓库」后生效；「加载更多」按此数量累加）")
        bar.addWidget(self.combo_page)
        bar.addWidget(QLabel("排序:"))
        self.combo_sort = QComboBox()
        for name in ("下载量 ↓", "点赞 ↓", "名称 ↑", "最近更新"):
            self.combo_sort.addItem(name)
        self.combo_sort.setCurrentText("下载量 ↓")
        self.combo_sort.setToolTip("与点击仓库表表头排序等效")
        bar.addWidget(self.combo_sort)
        self.label_status = QLabel("")
        self.label_status.setStyleSheet("color: #8fd0ff;")
        bar.addWidget(self.label_status)
        root.addLayout(bar)

        # ---- 上下可拖动分栏：上=左右双列，下=保存目录/仓库信息/操作日志 ----
        vsplit = QSplitter(Qt.Orientation.Vertical)
        vsplit.setChildrenCollapsible(False)

        hsplit = QSplitter(Qt.Orientation.Horizontal)
        hsplit.setChildrenCollapsible(False)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("模型仓库"))
        self.table_repo = QTableWidget(0, 4)
        self.table_repo.setHorizontalHeaderLabels(["模型仓库", "下载量", "点赞", "最近更新"])
        self._setup_table(self.table_repo, [190, 84, 56, 86])
        self.table_repo.horizontalHeader().setSectionsClickable(True)
        self.table_repo.horizontalHeader().sectionClicked.connect(self._on_repo_header_clicked)
        self.table_repo.horizontalHeader().sectionDoubleClicked.connect(
            lambda c: self.table_repo.resizeColumnToContents(c))
        self.table_repo.horizontalHeaderItem(3).setToolTip(
            "仓库在 HuggingFace 上最近一次提交更新的日期（lastModified）")
        lv.addWidget(self.table_repo)
        hsplit.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        file_bar = QHBoxLayout()
        self.label_repo_files = QLabel("未选择仓库")
        self.label_repo_files.setStyleSheet("color: #8fd0ff;")
        file_bar.addWidget(self.label_repo_files, 1)
        rv.addLayout(file_bar)
        self.table_files = QTableWidget(0, 5)
        self.table_files.setHorizontalHeaderLabels(
            ["文件名", "大小", "已安装", "下载", "进度"])
        self._setup_table(self.table_files, [320, 90, 70, 64, 150])
        self.table_files.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_files.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table_files.horizontalHeader().setSectionsClickable(True)
        self.table_files.horizontalHeader().sectionClicked.connect(self._on_file_header_clicked)
        self.table_files.horizontalHeader().sectionDoubleClicked.connect(
            lambda c: self.table_files.resizeColumnToContents(c))
        rv.addWidget(self.table_files)
        hsplit.addWidget(right)

        hsplit.setStretchFactor(0, 1)
        hsplit.setStretchFactor(1, 1)
        hsplit.setSizes([500, 500])
        vsplit.addWidget(hsplit)

        # ---- 下半部分：保存目录 + 全局进度 + 仓库信息 + 操作日志 ----
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("保存到:"))
        self.edit_save_dir = QLineEdit()
        self.edit_save_dir.setPlaceholderText("默认 = 主页的模型目录；下载时按仓库名建子文件夹")
        self.edit_save_dir.setToolTip(
            "模型下载根目录。默认显示主页「模型目录」；下载时会在其下按「仓库名」建立子文件夹。")
        btn_browse = QPushButton("浏览…")
        dir_row.addWidget(self.edit_save_dir, 1)
        dir_row.addWidget(btn_browse)
        bl.addLayout(dir_row)

        info_log = QHBoxLayout()
        self.group_repo_info = QGroupBox("仓库信息")
        gv = QVBoxLayout(self.group_repo_info)
        gv.setContentsMargins(6, 4, 6, 4)
        self.repo_info_view = QTextEdit()
        self.repo_info_view.setReadOnly(True)
        self.repo_info_view.setPlaceholderText("点击左侧仓库查看信息")
        gv.addWidget(self.repo_info_view)
        info_log.addWidget(self.group_repo_info, 1)

        self.group_log = QGroupBox("操作日志")
        gl = QVBoxLayout(self.group_log)
        gl.setContentsMargins(6, 4, 6, 4)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        gl.addWidget(self.log_view)
        info_log.addWidget(self.group_log, 1)
        bl.addLayout(info_log)

        bottom.setMinimumHeight(120)
        vsplit.addWidget(bottom)
        vsplit.setStretchFactor(0, 3)
        vsplit.setStretchFactor(1, 1)
        vsplit.setSizes([360, 160])
        root.addWidget(vsplit, 1)

        # ---- 连接 ----
        self.btn_search.clicked.connect(self.do_search)
        self.btn_more.clicked.connect(self.load_more)
        self.btn_open_dir.clicked.connect(self._open_download_dir)
        self.combo_page.currentIndexChanged.connect(self._on_page_size_changed)
        self.btn_cancel.clicked.connect(
            lambda: (self.downloader.cancel_current(), self._log("已请求取消当前下载")))
        self.btn_clearq.clicked.connect(
            lambda: (self.downloader.clear_queue(), self._log("队列已清空")))
        self.combo_sort.currentIndexChanged.connect(self._on_sort_combo)
        self.table_repo.currentItemChanged.connect(self._on_repo_selected)
        self.table_files.itemClicked.connect(self._on_file_clicked)
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
    def _setup_table(t, widths):
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.verticalHeader().setVisible(False)
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hh.setMinimumSectionSize(40)
        for i, w in enumerate(widths):
            t.setColumnWidth(i, w)

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
        org = self.edit_org.text().strip()
        name = self.edit_name.text().strip()
        kw = self.edit_kw.text().strip()
        if not org and not name and not kw:
            org = "unsloth"   # 保持原有默认检索组织
        mode = self.combo_match.currentIndex()   # 0=并, 1=或
        self._limit = int(self.combo_page.currentData() or 50)
        self.btn_search.setEnabled(False)
        self.label_status.setText("检索中…")
        self._log(f"正在检索 组织='{org}' 名称='{name}' 关键词='{kw}'（{'并' if mode == 0 else '或'}）…")

        def work():
            # 服务器端只用一个「种子」条件，A/B/C 的并/或语义统一在本地过滤
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
            self._log("已到加载上限（1000 条）")
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
            self.label_status.setText("检索失败")
            self._log(f"检索失败: {err}")
            return
        repos = getattr(self, "_repos_result", None) or []
        self._repos_all = list(repos)
        self._fill_repo_table()
        self.label_status.setText(f"共 {len(repos)} 个仓库（每页 {self._limit}）")
        self._log(f"找到 {len(repos)} 个仓库")

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
        self.label_repo_files.setText(f"仓库 {rid} 的文件（加载中…）")

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
            self.label_repo_files.setText(f"仓库 {rid} 加载失败")
            self._log(f"获取文件列表失败: {msg}")
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
                self.label_repo_files.setText(
                    f"仓库 {rid}：{len(self._cur_files)} 个 GGUF 文件（下载量 {info['downloads']:,}）")
            else:
                self.label_repo_files.setText(
                    f"仓库 {rid}：未找到 .gguf 文件（该仓库可能不是 GGUF 仓库）")
                self._log(f"{rid} 内没有 .gguf 文件")
            self._show_repo_info(rid, info)
        finally:
            self._building = False

    def _on_file_header_clicked(self, col):
        key = {0: "name", 1: "size"}.get(col)
        if not key:
            return
        if key == self._file_sort_key:
            self._file_sort_desc = not self._file_sort_desc
        else:
            self._file_sort_key = key
            self._file_sort_desc = (key == "size")
        self._render_files()

    def _render_files(self):
        files = list(self._cur_files)
        key, rev = self._file_sort_key, self._file_sort_desc
        if key == "size":
            files.sort(key=lambda f: f["size"], reverse=rev)
        else:
            files.sort(key=lambda f: natural_key(f["path"]), reverse=rev)
        self.table_files.setRowCount(0)
        self._file_state.clear()
        for f in files:
            self._append_file_row(self._cur_repo_id, f)

    def _append_file_row(self, rid, f):
        r = self.table_files.rowCount()
        self.table_files.insertRow(r)

        it = QTableWidgetItem(f["path"])
        it.setData(Qt.ItemDataRole.UserRole, f)
        it.setToolTip(f["path"])
        self.table_files.setItem(r, 0, it)
        self.table_files.setItem(r, 1, QTableWidgetItem(human_size(f["size"])))

        key = f"{rid}::{f['path']}"
        dest = self._dest_for(rid, f["path"])
        installed = os.path.isfile(dest) and os.path.getsize(dest) > 0
        status = QTableWidgetItem("已安装" if installed else "未安装")
        status.setForeground(Qt.GlobalColor.green if installed
                             else Qt.GlobalColor.gray)
        self.table_files.setItem(r, 2, status)

        btn = QPushButton("下载")
        btn.setToolTip("下载该文件（支持断点续传）；已安装的模型点击文件名可直接设为主模型")
        btn.clicked.connect(lambda _=False, r_=rid, f_=f: self._enqueue_file(r_, f_))
        self.table_files.setCellWidget(r, 3, btn)

        pb = QProgressBar()
        pb.setRange(0, 100)
        pb.setValue(100 if installed else 0)
        pb.setFormat("已安装" if installed else "")
        self.table_files.setCellWidget(r, 4, pb)

        self._file_state[key] = {
            "btn": btn, "progress": pb, "status": status, "dest": dest,
            "path": f["path"], "installed": installed,
        }

    def _show_repo_info(self, rid, info):
        tags = info.get("tags") or []
        tag_txt = "、".join(tags[:12]) if tags else "—"
        html = (
            f"<b>{rid}</b><br>"
            f"下载量: {info.get('downloads', 0):,}　|　点赞: {info.get('likes', 0)}　|　"
            f"最近更新: {info.get('last_modified') or '—'}<br>"
            f"流水线: {info.get('pipeline_tag') or '—'}<br>"
            f"标签: {tag_txt}")
        self.repo_info_view.setHtml(html)

    # ------------------------------------------------------------- 下载队列
    def _repo_dir(self, repo_id=None):
        rid = repo_id or self._cur_repo_id
        name = (rid.split("/")[-1] if rid else "hf").strip() or "hf"
        return os.path.join(self._save_dir(), name)

    def _dest_for(self, repo_id, path):
        rel = str(path).replace("\\", "/").split("/")
        return os.path.join(self._repo_dir(repo_id), *rel)

    def _enqueue_file(self, rid, f):
        dest = self._dest_for(rid, f["path"])
        try:
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self.mw, "提示", f"无法创建目录：\n{e}")
            return
        key = f"{rid}::{f['path']}"
        st = self._file_state.get(key)
        if st:
            st["progress"].setRange(0, 100)
            st["progress"].setValue(0)
            st["progress"].setFormat("排队中…")
        url = hf_browse.file_url(rid, f["path"])
        self._log(f"加入下载: {f['path']} → {dest}")
        self.downloader.enqueue(url, dest, label=key)

    # ------------------------------------------------------------- 进度回调
    def _on_task_started(self, label):
        st = self._file_state.get(label)
        if st:
            st["progress"].setRange(0, 100)
            st["progress"].setValue(0)
            st["progress"].setFormat("0%")
        self._log("开始下载: " + label)

    def _on_progress(self, label, done, total, speed):
        st = self._file_state.get(label)
        if not st:
            return
        if total > 0:
            pct = int(done * 100 // max(1, total))
            st["progress"].setRange(0, 100)
            st["progress"].setValue(pct)
            txt = f"{human_size(done)} / {human_size(total)}  ({pct}%)"
        else:
            st["progress"].setRange(0, 0)
            txt = human_size(done)
        if speed > 0:
            txt += f"  {human_size(speed)}/s"
        st["progress"].setFormat(txt)

    def _on_task_done(self, label, path):
        st = self._file_state.get(label)
        if st:
            st["installed"] = True
            st["progress"].setRange(0, 100)
            st["progress"].setValue(100)
            st["progress"].setFormat("已安装")
            st["status"].setText("已安装")
            st["status"].setForeground(Qt.GlobalColor.green)
        self._log(f"✔ 下载完成: {path}")
        self.models_changed.emit()

    def _on_task_failed(self, label, err):
        st = self._file_state.get(label)
        if st:
            st["progress"].setRange(0, 100)
            st["progress"].setValue(0)
            st["progress"].setFormat("失败")
        self._log(f"✘ 下载失败: {label} — {err}")

    def _on_queue_empty(self):
        self.btn_search.setEnabled(True)
        self._log("队列已全部完成")

    # ------------------------------------------------------------- 其他
    def _on_file_clicked(self, item):
        """点击文件行：若该文件已下载，则自动替换上方主模型。"""
        if item is None:
            return
        row = item.row()
        cell = self.table_files.item(row, 0)
        f = cell.data(Qt.ItemDataRole.UserRole) if cell else None
        if not f:
            return
        dest = self._dest_for(self._cur_repo_id, f["path"])
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            self.mw.select_model_path(dest)

    def _open_download_dir(self):
        d = self._repo_dir() if self._cur_repo_id else self._save_dir()
        try:
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            os.startfile(d)  # type: ignore[attr-defined]
        except OSError as e:
            QMessageBox.critical(self.mw, "错误", f"无法打开下载目录：\n{e}")

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(
            self.mw, "选择模型保存目录", self._save_dir() or os.path.expanduser("~"))
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
