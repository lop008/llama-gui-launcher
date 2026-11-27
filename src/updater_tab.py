"""更新 llama.cpp（v0.6）：卡片式版本浏览 + 可见筛选 + 批量下载 + 已下载扫描。

- 从 GitHub Release 拉取 Windows 预编译包；没有 Windows 资产的版本（如 v1.1.0）
  也会保留一行，明确标注原因并给 Release 链接，不再整条消失；
- 「全部 / 仅稳定 / 仅预发布」用分段控件，选中态清晰可见；
- 每行复选框 + 全选 + 下载选中；表格状态列直接显示「当前版本 / 已下载 / 可下载 / 无包」；
- 递归扫描下载目录，统计已下载版本数与包数；
- 断点续传下载、安全安装、占用文件延迟替换沿用原逻辑。
"""
import html
import os
import tempfile

from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QDesktopServices, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QGridLayout, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QTextBrowser, QVBoxLayout, QWidget,
)

from .llama_updater import (BACKENDS, MODE_ALL, MODE_SERVER, UpdaterError, all_assets,
                            asset_backend, asset_platform, backup_launcher_dir, backends_in,
                            get_local_version_info, install_from_zip, latest_stable_release,
                            list_releases, release_web_url, schedule_self_update)
from .model_downloader import ModelDownloader
from .model_scanner import human_size
from .i18n import t
from .ui.kit import (Badge, Card, CheckComboBox, ColumnResizer, SectionHeader,
                     SegmentedControl, StatCard)

PER_PAGE = 30
#: 官方发布页（⑫：说明文字旁给一个一键打开的入口）
RELEASES_URL = "https://github.com/ggml-org/llama.cpp/releases"


class _ListWorker(QThread):
    ok = pyqtSignal(list, object)
    err = pyqtSignal(str)

    def __init__(self, page, exe_path):
        super().__init__()
        self._page = page
        self._exe = exe_path

    def run(self):
        try:
            rels = list_releases(per_page=PER_PAGE, include_prerelease=True, page=self._page)
            try:
                latest = latest_stable_release()
                if latest and latest.get("tag") and all(r.get("tag") != latest["tag"] for r in rels):
                    rels.insert(0, latest)
            except Exception:
                pass
            local = get_local_version_info(self._exe) if self._exe else {}
            self.ok.emit(rels, local)
        except Exception as e:
            self.err.emit(str(e))


class _VersionWorker(QThread):
    done = pyqtSignal(object)

    def __init__(self, exe_path):
        super().__init__()
        self._exe = exe_path

    def run(self):
        try:
            self.done.emit(get_local_version_info(self._exe) if self._exe else {})
        except Exception:
            self.done.emit({})


class _InstallWorker(QThread):
    log = pyqtSignal(str)
    backup_progress = pyqtSignal(int)
    install_progress = pyqtSignal(int)
    done = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, zip_path, target_dir, mode):
        super().__init__()
        self._zip = zip_path
        self._dir = target_dir
        self._mode = mode

    def run(self):
        try:
            cur = get_local_version_info(os.path.join(self._dir, "llama-server.exe"))
            cur_ver = cur.get("build") or cur.get("version") or t('未知版本')
            self.log.emit(t('备份 {0} 顶层文件（当前版本 {1}）→ bak\\{2}.zip').format(self._dir, cur_ver, cur_ver))
            backup_cb = lambda d, t2: self.backup_progress.emit(int(d * 100 // max(1, t2)))
            backup_path = backup_launcher_dir(self._dir, cur_ver, progress_cb=backup_cb)
            if backup_path:
                self.log.emit(t('备份完成: ') + os.path.basename(backup_path))
            else:
                self.log.emit(t('跳过备份（无可备份文件）'))

            self.log.emit(t('开始安装…'))
            install_cb = lambda d, t2: self.install_progress.emit(int(d * 100 // max(1, t2)))
            actions, skipped, pending = install_from_zip(
                self._zip, self._dir, mode=self._mode, progress_cb=install_cb)
            self.done.emit({"actions": actions, "skipped": skipped,
                            "pending": pending, "backup_path": backup_path})
        except Exception as e:
            self.error.emit(str(e))


def _show_result(parent, res, target_dir, exe_path=""):
    """简洁的更新结果报告：目标目录 + 版本 + 计数汇总，不逐文件列明细。"""
    counts = {}
    for _n, s in res["actions"]:
        counts[s] = counts.get(s, 0) + 1

    lines = [t('已安装到：{0}').format(target_dir)]
    if exe_path and os.path.isfile(exe_path):
        try:
            info = get_local_version_info(exe_path)
            ver = info.get("build") or info.get("version") or t('未知')
            if info.get("version") and info.get("build"):
                ver = f"{info['version']} ({info['build']})"
        except Exception:
            ver = t('未知')
        lines.append(t('当前 llama 版本：{0}').format(ver))

    parts = []
    if counts.get("installed"):
        parts.append(t('新装 {0}').format(counts['installed']))
    if counts.get("replaced"):
        parts.append(t('替换 {0}').format(counts['replaced']))
    if counts.get("removed"):
        parts.append(t('删除旧文件 {0}').format(counts['removed']))
    if res.get("skipped"):
        parts.append(t('未选中 {0}').format(res['skipped']))
    lines.append("，".join(parts) + "。" if parts else t('无文件变更。'))
    if res.get("backup_path"):
        lines.append(t('备份：{0}').format(os.path.basename(res['backup_path'])))

    pending = res.get("pending", [])
    if pending:
        lines.append("")
        lines.append(t('⚠ {0} 个文件正被占用，已写成 .new，关闭本程序后自动替换。').format(len(pending)))
    QMessageBox.information(parent, t('更新完成'), "\n".join(lines))


class UpdaterTab(QWidget):
    def __init__(self, main_win=None):
        super().__init__()
        self.mw = main_win
        self._releases = []
        self._page = 0
        self._row_meta = {}
        self._state = {}
        self._download_index = {}
        self._current_version = {}
        self._downloader = ModelDownloader()
        self._list_worker = None
        self._install_worker = None
        self._version_worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ---------------- 顶部概览卡 ----------------
        hero = Card()
        head = SectionHeader(t('更新 llama.cpp'),
                             t('从官方 GitHub Release 下载预编译包（CUDA / Vulkan / ROCm 等都有）；'
                               '模型、配置不受影响。'))
        self.btn_refresh = QPushButton(t('刷新'))
        self.btn_refresh.setProperty("variant", "primary")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_releases = QPushButton(t('打开 llama.cpp 下载页'))
        self.btn_releases.setProperty("variant", "ghost")
        self.btn_releases.setToolTip(t('在浏览器打开官方 Releases 页面：{0}').format(RELEASES_URL))
        self.btn_releases.clicked.connect(
            lambda *_: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        self.btn_open_dl = QPushButton(t('打开下载目录'))
        self.btn_open_dl.setProperty("variant", "ghost")
        self.btn_open_dl.setToolTip(t('打开更新包下载目录'))
        self.btn_open_dl.clicked.connect(self._open_dl_dir)
        head.add_action(self.btn_refresh)
        head.add_action(self.btn_releases)
        head.add_action(self.btn_open_dl)
        hero.add(head)

        stats = QGridLayout()
        stats.setHorizontalSpacing(8)
        stats.setVerticalSpacing(8)
        self.card_current = StatCard(t('当前 llama.cpp'), '—', t('本地 llama-server'))
        self.card_latest = StatCard(t('最新稳定版'), '—', t('GitHub 最新非预发布'))
        self.card_downloaded = StatCard(t('已下载'), '0', t('下载目录里的版本 / 包'))
        stats.addWidget(self.card_current, 0, 0)
        stats.addWidget(self.card_latest, 0, 1)
        stats.addWidget(self.card_downloaded, 0, 2)
        for c in range(3):
            stats.setColumnStretch(c, 1)
        hero.add_layout(stats)
        root.addWidget(hero)

        # ---------------- 筛选卡 ----------------
        filt = Card(padding=10, spacing=6)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel(t('发布通道:')))
        self.seg_channel = SegmentedControl([
            ("all", t('全部')), ("stable", t('仅稳定')), ("pre", t('仅预发布'))])
        self.seg_channel.changed.connect(lambda _v: self._apply_filter())
        row.addWidget(self.seg_channel)
        self.chk_downloaded = QCheckBox(t('仅显示已下载'))
        self.chk_downloaded.toggled.connect(lambda _=False: self._filter_changed(save=True))
        row.addWidget(self.chk_downloaded)
        self.chk_win = QCheckBox(t('仅显示有 Windows 包'))
        # 官方每个版本同时发 win / ubuntu / macos / android 好几套包，默认只看 Windows；
        # 想看别的平台就把这里的勾去掉（数据本来就全部取回，只是界面先筛掉）。
        self.chk_win.setChecked(bool(self._pref("upd_only_win", True)))
        self.chk_win.toggled.connect(lambda _=False: self._filter_changed(save=True))
        row.addWidget(self.chk_win)
        row.addSpacing(6)
        row.addWidget(QLabel(t('后端:')))
        self.combo_backend = CheckComboBox(t('全部后端'))
        self.combo_backend.setToolTip(
            t('按推理后端筛选（可多选，多选之间是「或」）：取自官方包名里的 '
              'cuda / cpu / vulkan / rocm / sycl / openvino 等。\n'
              '与上面的「仅显示有 Windows 包」同时生效；一个都不勾 = 不限后端。'))
        self.combo_backend.setMinimumWidth(118)
        self.combo_backend.set_options(list(BACKENDS))
        self.combo_backend.set_checked(list(self._pref("upd_backends", []) or []))
        self.combo_backend.changed.connect(lambda: self._filter_changed(save=True))
        row.addWidget(self.combo_backend)
        row.addSpacing(8)
        self.chk_all_rows = QCheckBox(t('全选'))
        self.chk_all_rows.toggled.connect(self._toggle_all_rows)
        row.addWidget(self.chk_all_rows)
        self.btn_download_sel = QPushButton(t('下载选中'))
        self.btn_download_sel.setProperty("variant", "primary")
        self.btn_download_sel.clicked.connect(self.download_selected)
        row.addWidget(self.btn_download_sel)
        row.addStretch(1)
        self.label_status = QLabel("")
        self.label_status.setObjectName("Muted")
        row.addWidget(self.label_status)
        self.btn_more = QPushButton(t('↓ 加载更多'))
        self.btn_more.setProperty("variant", "ghost")
        self.btn_more.clicked.connect(self.load_more)
        row.addWidget(self.btn_more)
        filt.add_layout(row)

        opt = QHBoxLayout()
        opt.setSpacing(8)
        self.chk_all_files = QCheckBox(t('安装 zip 内全部文件（含工具/示例，默认仅 server+DLL）'))
        opt.addWidget(self.chk_all_files)
        opt.addStretch(1)
        self.badge_local = Badge(t('就绪'), "info")
        opt.addWidget(self.badge_local)
        filt.add_layout(opt)
        root.addWidget(filt)

        # ---------------- 版本表 ----------------
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [t('选择'), t('文件名'), t('版本'), t('日期'), t('通道'), t('状态'), t('操作')])
        # 列宽策略：全部可手动拖动；多余宽度补给文件名列。
        # 文件名不再给到 340px（官方包名长但看开头就够辨认后端），把宽度让给操作列，
        # 「下载 / 进度 / 安装」才不会被裁；操作列实际宽度由 _fit_op_column 按按钮实测值定。
        self._col_resizer = ColumnResizer(
            self.table, [42, 240, 96, 96, 88, 104, 320], fill_col=1, min_width=56)
        self.table.verticalHeader().setVisible(False)
        # 行高要装得下「下载 / 进度条 / 安装」这一排控件（默认行高会把按钮文字裁掉）
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setMinimumHeight(260)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemClicked.connect(self._on_row_clicked)
        # ---------------- 版本表 / 版本信息 / 操作日志：三块之间可拖动分隔 ----------------
        # 原来详情区写死 maximumHeight，拖不动也长不大；改成竖向分栏后
        # 「看版本说明」「看日志」「看列表」各自能占到需要的高度。
        self.split = QSplitter(Qt.Orientation.Vertical, self)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(6)
        self.split.addWidget(self.table)
        root.addWidget(self.split, 1)

        # ---------------- 详情 / 日志 ----------------
        self.detail_view = QTextBrowser()
        self.detail_view.setOpenExternalLinks(True)
        self.detail_view.setPlaceholderText(t('点击某一行查看该版本信息'))
        self.split.addWidget(self.detail_view)

        self.log_view = QTextBrowser()
        self.log_view.setPlaceholderText(t('操作日志…'))
        self.split.addWidget(self.log_view)
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)
        self.split.setStretchFactor(2, 0)
        self.split.setSizes([520, 96, 112])

        self._downloader.task_started.connect(self._on_task_started)
        self._downloader.progress.connect(self._on_progress)
        self._downloader.task_done.connect(self._on_task_done)
        self._downloader.task_failed.connect(self._on_task_failed)

        self._download_index = self._scan_downloaded()

    # ------------------------------------------------------------- 列表加载
    def _set_loading(self, loading, text=""):
        self.btn_refresh.setEnabled(not loading)
        self.btn_more.setEnabled(not loading)
        if text:
            self.label_status.setText(text)
            self.badge_local.set_status(text, "info")

    def refresh(self):
        if self._list_worker and self._list_worker.isRunning():
            return
        try:
            self.btn_open_dl.setToolTip(self._dl_root())
        except Exception:
            pass
        self.table.setRowCount(0)
        self._releases = []
        self._row_meta.clear()
        self._state.clear()
        self._page = 1
        self._set_loading(True, t('正在加载版本列表…'))
        self._list_worker = _ListWorker(self._page, self._launcher_exe())
        self._list_worker.ok.connect(self._on_list_ok)
        self._list_worker.err.connect(self._on_list_err)
        self._list_worker.start()

    def load_more(self):
        if self._list_worker and self._list_worker.isRunning():
            return
        if not self._releases:
            self.refresh()
            return
        self._page += 1
        self._set_loading(True, t('正在加载第 {0} 页…').format(self._page))
        self._list_worker = _ListWorker(self._page, self._launcher_exe())
        self._list_worker.ok.connect(self._on_list_ok)
        self._list_worker.err.connect(self._on_list_err)
        self._list_worker.start()

    def _on_list_ok(self, rels, local):
        self._current_version = local or {}
        self._download_index = self._scan_downloaded()
        seen = {x["release"].get("tag") for x in self._releases}
        for rel in rels:
            tag = rel.get("tag") or rel.get("tag_name")
            if tag and tag in seen:
                continue
            seen.add(tag)
            assets = all_assets(rel)
            self._releases.append({"release": rel, "assets": assets})
            self._append_release_rows(rel, assets)
        self._refresh_backend_options()
        self._apply_filter()
        self._fit_op_column()
        self._refresh_version_cards()
        self._update_stats()
        self._set_loading(False)

    def _on_list_err(self, msg):
        self._set_loading(False)
        if self._page == 1:
            self.label_status.setText(t('加载失败'))
        QMessageBox.critical(self, t('加载失败'), t('获取版本列表失败：\n{0}').format(msg))

    def _append_release_rows(self, rel, assets):
        if not assets:
            self._append_placeholder_row(rel)
            return
        for a in assets:
            self._append_asset_row(rel, a)

    def _append_asset_row(self, rel, asset):
        r = self.table.rowCount()
        self.table.insertRow(r)
        key = f"{rel['tag']}::{asset['name']}"
        self._row_meta[r] = {"release": rel, "asset": asset, "key": key, "kind": "asset"}

        cb = QCheckBox()
        cb.setStyleSheet("margin-left: 8px;")
        cb.setProperty("row_key", key)
        self.table.setCellWidget(r, 0, cb)

        it_name = QTableWidgetItem(asset["name"])
        plat, backend = asset_platform(asset["name"]), asset_backend(asset["name"])
        it_name.setToolTip(t('平台: {0}    后端: {1}\n大小: {2}\n{3}').format(
            plat, backend, human_size(asset['size']), asset['url']))
        self.table.setItem(r, 1, it_name)
        self.table.setItem(r, 2, QTableWidgetItem(rel["tag"]))
        self.table.setItem(r, 3, QTableWidgetItem(rel["published_at"]))
        channel = t('预发布') if rel["prerelease"] else t('稳定')
        self.table.setItem(r, 4, QTableWidgetItem(channel))

        status, tone = self._row_status(rel, asset)
        st_item = QTableWidgetItem(status)
        if tone == "muted":
            st_item.setForeground(QBrush(QColor("#8a8a8a")))
        self.table.setItem(r, 5, st_item)

        op = self._make_op_widget(key, asset)
        self.table.setCellWidget(r, 6, op[0])
        self._state[key] = {
            "dl_btn": op[1], "install_btn": op[3],
            "progress": op[2], "downloaded": False, "dest": "",
            "name": asset["name"], "url": asset["url"], "tag": rel["tag"],
            "size": asset.get("size", 0), "rel": rel,
        }
        dest = self._tmp_path(rel["tag"], asset["name"])
        if plat != "win":
            # 非 Windows 的包（Ubuntu / macOS / Android / s390x）：允许下载备用，
            # 但装进本机只会得到一个跑不起来的 llama-server，所以「安装」直接不给点。
            op[3].setEnabled(False)
            op[3].setToolTip(t('非 Windows 包：可以下载备用，不能安装到本机'))
        if self._file_ok(dest):
            st = self._state[key]
            st["downloaded"] = True
            st["dest"] = dest
            st["progress"].setValue(100)
            st["progress"].setFormat(t('已下载'))
            st["install_btn"].setEnabled(plat == "win")

    def _append_placeholder_row(self, rel):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self._row_meta[r] = {"release": rel, "asset": None, "key": "", "kind": "release"}
        cb = QCheckBox()
        cb.setEnabled(False)
        cb.setStyleSheet("margin-left: 8px;")
        self.table.setCellWidget(r, 0, cb)
        item = QTableWidgetItem(t('（该版本未提供预编译包）'))
        item.setToolTip(t('GitHub Release「{0}」只有源码/说明文件，没有 llama-*-bin-* 的预编译包。')
                        .format(rel['tag']))
        self.table.setItem(r, 1, item)
        self.table.setItem(r, 2, QTableWidgetItem(rel["tag"]))
        self.table.setItem(r, 3, QTableWidgetItem(rel["published_at"]))
        self.table.setItem(r, 4, QTableWidgetItem(t('稳定') if not rel["prerelease"] else t('预发布')))
        status = QTableWidgetItem(t('无预编译包'))
        status.setForeground(QBrush(QColor("#8a8a8a")))
        self.table.setItem(r, 5, status)
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)
        btn = QPushButton(t('打开 Release'))
        btn.setProperty("variant", "ghost")
        btn.clicked.connect(lambda _=False, tag=rel["tag"]: QDesktopServices.openUrl(QUrl(release_web_url(tag))))
        lay.addWidget(btn)
        lay.addStretch(1)
        self._note_op_width(w)
        self.table.setCellWidget(r, 6, w)

    def _make_op_widget(self, key, asset):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(5)
        dl = QPushButton(t('下载'))
        dl.setProperty("variant", "ghost")
        pb = QProgressBar()
        pb.setRange(0, 100)
        pb.setValue(0)
        pb.setMinimumWidth(84)
        inst = QPushButton(t('安装'))
        inst.setEnabled(False)
        lay.addWidget(dl)
        lay.addWidget(pb, 1)
        lay.addWidget(inst)
        dl.clicked.connect(lambda *_: self._on_download(key))
        inst.clicked.connect(lambda *_: self._on_install(key))
        self._note_op_width(w)
        return w, dl, pb, inst

    def _note_op_width(self, widget):
        """记下操作列实际需要多宽：固定列宽在大字号 / 其他语言下会把按钮文字裁掉。

        余量给到 28px（不是 16px）：进度条挤在「下载」和「安装」中间，
        余量小了会显示成「安…」，看着像按钮坏了。
        """
        need = widget.sizeHint().width() + 28
        self._op_need = max(getattr(self, "_op_need", 0), need)

    def _fit_op_column(self):
        """按实测按钮宽度定操作列（第 6 列），剩余空间仍归名称列。"""
        need = getattr(self, "_op_need", 0)
        if need:
            self._col_resizer.set_column_width(6, max(need, 330))

    # ------------------------------------------------------------- 筛选
    def _pref(self, key, default=None):
        """读界面偏好（没有主窗口时给默认值，独立测试也能构造这一页）。"""
        try:
            cfg = self.mw.cfg.data
        except AttributeError:
            return default
        return cfg.get(key, default)

    def _set_pref(self, key, value):
        try:
            self.mw.cfg.data[key] = value
        except AttributeError:
            pass

    def _filter_changed(self, save=False):
        """筛选控件变了：先记住偏好（列表可能还没加载，构造阶段也不能炸），再应用。"""
        if save:
            self._set_pref("upd_only_win", bool(self.chk_win.isChecked()))
            self._set_pref("upd_backends", list(self.combo_backend.checked_keys()))
        if self._row_meta:
            self._apply_filter()

    def _refresh_backend_options(self):
        """后端下拉只列当前列表里**真实出现过**的后端，不凭空列官方没发过的选项。"""
        opts = [(k, k) for k in backends_in([x["assets"] for x in self._releases])]
        if opts:
            labels = dict(BACKENDS)
            opts = [(k, labels.get(k, k)) for k, _ in opts]
        self.combo_backend.set_options(opts)

    def _is_downloaded(self, row):
        """「已下载」只认硬盘上真实存在的文件。

        以前还把状态「当前版本」也当成已下载，但那只代表本机装的 llama.cpp 正好是这个
        版本，不代表 zip 还留在下载目录里（装完被清理、或从别处装的都算），
        于是勾「仅显示已下载」会冒出一堆其实没下载的包。
        """
        meta = self._row_meta.get(row) or {}
        if meta.get("kind") != "asset":
            return False
        st = self._state.get(meta["key"]) or {}
        if st.get("downloaded") and self._file_ok(str(st.get("dest") or "")):
            return True
        return self._file_ok(self._tmp_path(meta["release"]["tag"], meta["asset"]["name"]))

    def _apply_filter(self):
        """显示哪些行：**维度之间是「且」，同一维度内多选是「或」**。

        例：勾「仅显示有 Windows 包」+ 后端选 CUDA、Vulkan → 显示 Windows 的 CUDA 包
        与 Vulkan 包；「仅显示已下载」「发布通道」照常生效。后端一个都不勾 = 不限后端。
        """
        channel = self.seg_channel.value() if hasattr(self, "seg_channel") else "all"
        only_dl = self.chk_downloaded.isChecked() if hasattr(self, "chk_downloaded") else False
        only_win = self.chk_win.isChecked() if hasattr(self, "chk_win") else False
        backends = set(self.combo_backend.checked_keys()) if hasattr(self, "combo_backend") else set()
        for r, meta in self._row_meta.items():
            rel = meta["release"]
            show = True
            if channel == "stable" and rel["prerelease"]:
                show = False
            elif channel == "pre" and not rel["prerelease"]:
                show = False
            if show and only_dl and not self._is_downloaded(r):
                show = False
            if show and meta["kind"] != "asset":
                # 「该版本没发预编译包」的占位行：只看 Windows 时它没有任何意义
                if only_win:
                    show = False
            elif show:
                name = meta["asset"]["name"]
                plat_ok = (not only_win) or asset_platform(name) == "win"
                backend_ok = (not backends) or asset_backend(name) in backends
                if not (plat_ok and backend_ok):
                    show = False
            self.table.setRowHidden(r, not show)

    def _toggle_all_rows(self, checked):
        for r, meta in self._row_meta.items():
            if self.table.isRowHidden(r) or meta["kind"] != "asset":
                continue
            w = self.table.cellWidget(r, 0)
            if isinstance(w, QCheckBox):
                w.setChecked(bool(checked))

    def _checked_keys(self):
        keys = []
        for r, meta in self._row_meta.items():
            if self.table.isRowHidden(r) or meta["kind"] != "asset":
                continue
            w = self.table.cellWidget(r, 0)
            if isinstance(w, QCheckBox) and w.isChecked():
                keys.append(meta["key"])
        return keys

    # ------------------------------------------------------------- 状态
    def _row_status(self, rel, asset):
        tag = rel["tag"]
        cur = self._current_version or {}
        build = cur.get("build") or ""
        version = cur.get("version") or ""
        if build and tag == build:
            return t('当前版本'), "ok"
        if version and tag.lstrip("v") == version.lstrip("v"):
            return t('当前版本'), "ok"
        dest = self._tmp_path(tag, asset["name"])
        if self._file_ok(dest):
            return t('已下载'), "ok"
        if tag.startswith("v") and not all_assets(rel):
            return t('无预编译包'), "muted"
        return t('可下载'), "muted"

    def _file_ok(self, path):
        try:
            return os.path.isfile(path) and os.path.getsize(path) > 0
        except OSError:
            return False

    def _refresh_version_cards(self):
        cur = self._current_version or {}
        ver = cur.get("build") or t('未检测到')
        if cur.get("version"):
            ver = f"{cur['version']} ({ver})" if cur.get("build") else cur["version"]
        self.card_current.set_value(ver)
        stable = next((r["release"] for r in self._releases if not r["release"]["prerelease"]), None)
        if stable:
            self.card_latest.set_value(stable["tag"])
            self.card_latest.set_hint(stable.get("published_at") or "")
        else:
            self.card_latest.set_value("—")

    def _update_stats(self):
        n_rel = len(self._releases)
        n_assets = sum(len(x["assets"]) for x in self._releases)
        dl_tags = set(self._download_index.keys())
        dl_pkgs = sum(len(v) for v in self._download_index.values())
        self.card_downloaded.set_value(f"{len(dl_tags)} / {dl_pkgs}")
        self.card_downloaded.set_hint(t('已下载 {0} 个版本，共 {1} 个包').format(len(dl_tags), dl_pkgs))
        text = t('共 {0} 个版本 / {1} 个预编译包').format(n_rel, n_assets)
        if dl_pkgs:
            text += t(' · 已下载 {0} 个包').format(dl_pkgs)
        self.label_status.setText(text)
        self.badge_local.set_status(t('数据已就绪'), "ok")

    # ------------------------------------------------------------- 下载
    def _dl_root(self):
        """更新包下载根目录：<llama-server.exe 所在目录>\\temp（无目标时回退系统临时目录）。"""
        d = self._target_dir()
        if d:
            return os.path.join(d, "temp")
        return os.path.join(tempfile.gettempdir(), "llama_upd")

    def _tmp_path(self, tag, name):
        safe_tag = os.path.basename(str(tag).strip()) or "release"
        return os.path.join(self._dl_root(), safe_tag, name)

    def _scan_downloaded(self):
        idx = {}
        root = self._dl_root()
        if not os.path.isdir(root):
            return idx
        try:
            for tag in os.listdir(root):
                d = os.path.join(root, tag)
                if not os.path.isdir(d):
                    continue
                for fn in os.listdir(d):
                    p = os.path.join(d, fn)
                    if os.path.isfile(p) and fn.lower().endswith(".zip"):
                        idx.setdefault(tag, []).append(p)
        except OSError:
            pass
        return idx

    def _open_dl_dir(self):
        d = self._dl_root()
        try:
            os.makedirs(d, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))
        except OSError as e:
            QMessageBox.critical(self, t('错误'), str(e))

    def download_selected(self):
        keys = self._checked_keys()
        if not keys:
            QMessageBox.information(self, t('提示'), t('请先勾选要下载的包。'))
            return
        for key in keys:
            self._on_download(key)

    def _on_download(self, key):
        st = self._state.get(key)
        if not st:
            return
        dest = self._tmp_path(st["tag"], st["name"])
        if self._file_ok(dest):
            st["downloaded"] = True
            st["dest"] = dest
            st["progress"].setValue(100)
            st["progress"].setFormat(t('已下载'))
            st["install_btn"].setEnabled(True)
            self.log(t('{0} 已存在，可直接安装').format(st['name']))
            return
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
        except OSError as e:
            QMessageBox.critical(self, t('错误'), t('无法创建临时目录：\n{0}').format(e))
            return
        st["dest"] = dest
        st["dl_btn"].setEnabled(False)
        st["progress"].setValue(0)
        st["progress"].setFormat(t('排队中…'))
        self.log(t('开始下载 {0}（{1}）→ {2}').format(st['name'], human_size(st['size']), dest))
        self._downloader.enqueue(st["url"], dest, label=key)

    def _on_task_started(self, key):
        st = self._state.get(key)
        if st:
            st["progress"].setFormat("0%")

    def _on_progress(self, key, done, total, speed):
        st = self._state.get(key)
        if not st:
            return
        if total > 0:
            pct = int(done * 100 // total)
            st["progress"].setValue(pct)
            st["progress"].setFormat(
                f"{human_size(done)} / {human_size(total)}  ({pct}%)")
        else:
            st["progress"].setFormat(human_size(done))

    def _on_task_done(self, key, final):
        st = self._state.get(key)
        if not st:
            return
        st["downloaded"] = True
        st["dest"] = final
        st["progress"].setValue(100)
        st["progress"].setFormat(t('已下载'))
        st["install_btn"].setEnabled(True)
        st["dl_btn"].setEnabled(True)
        self.log(t('下载完成 {0}').format(st['name']))
        self._download_index = self._scan_downloaded()
        self._update_stats()
        self._apply_filter()

    def _on_task_failed(self, key, err):
        st = self._state.get(key)
        if not st:
            return
        st["progress"].setFormat(t('失败'))
        st["dl_btn"].setEnabled(True)
        self.log(t('下载失败 {0}: {1}').format(st['name'], err))
        QMessageBox.critical(self, t('下载失败'), t('{0}：\n{1}\n\n可点击「下载」重试（支持断点续传）。').format(st['name'], err))

    # ------------------------------------------------------------- 安装
    def _target_dir(self):
        if self.mw:
            tgt = str(self.mw.cfg.data.get("updater_target") or "").strip()
            if tgt and os.path.isdir(tgt):
                return tgt
        exe = self.mw._launcher_exe() if self.mw else ""
        d = os.path.dirname(exe) if exe else ""
        return d or (self.mw.base_dir if self.mw else "")

    def _launcher_exe(self):
        try:
            return self.mw._launcher_exe() if self.mw else ""
        except Exception:
            return ""

    def _on_install(self, key):
        st = self._state.get(key)
        if not st:
            return
        if asset_platform(st["name"]) != "win":
            QMessageBox.information(
                self, t('提示'),
                t('「{0}」不是 Windows 包，不能安装到本机（下载备用可以）。').format(st["name"]))
            return
        if not st["downloaded"] or not os.path.isfile(st["dest"]):
            QMessageBox.information(self, t('提示'), t('请先下载该文件再安装。'))
            return
        if self._install_worker and self._install_worker.isRunning():
            QMessageBox.information(self, t('提示'), t('已有安装任务进行中，请稍候。'))
            return
        target_dir = self._target_dir()
        if not target_dir or not os.path.isdir(target_dir):
            QMessageBox.critical(self, t('错误'), t('目标目录无效：\n{0}').format(target_dir))
            return
        mode = MODE_ALL if self.chk_all_files.isChecked() else MODE_SERVER

        ret = QMessageBox.question(
            self, t('确认安装'),
            t('将把 {0} 安装到：\n{1}\n\n会先备份该目录顶层文件，删除旧版本二进制/DLL，再解压安装所有选中文件。\n模型与配置不受影响。继续？').format(st['name'], target_dir))
        if ret != QMessageBox.StandardButton.Yes:
            return

        st["dl_btn"].setEnabled(False)
        st["install_btn"].setEnabled(False)
        self.log(t('开始安装 {0} → {1}').format(st['name'], target_dir))
        self._install_worker = _InstallWorker(st["dest"], target_dir, mode)
        self._install_worker.log.connect(self.log)
        self._install_worker.backup_progress.connect(
            lambda p: (self.log(t('备份进度 {0}%').format(p)), st["progress"].setValue(p)))
        self._install_worker.install_progress.connect(
            lambda p: (self.log(t('安装进度 {0}%').format(p)),
                       st["progress"].setFormat(t('安装 {0}%').format(p))))
        self._install_worker.done.connect(lambda res, k=key: self._on_install_done(k, res))
        self._install_worker.error.connect(self._on_install_err)
        self._install_worker.start()

    def _on_install_done(self, key, res):
        st = self._state.get(key)
        actions = res["actions"]
        pending = res["pending"]

        target_dir = self._target_dir()
        if pending:
            schedule_self_update(pending, target_dir, pid=os.getpid())

        lines = [t('安装完成：')]
        counts = {}
        for _name, status in actions:
            counts[status] = counts.get(status, 0) + 1
        if counts.get("installed"):
            lines.append(t('  新装 {0} 个').format(counts['installed']))
        if counts.get("replaced"):
            lines.append(t('  替换 {0} 个').format(counts['replaced']))
        if counts.get("removed"):
            lines.append(t('  删除旧文件 {0} 个').format(counts['removed']))
        if res["skipped"]:
            lines.append(t('  未选中 {0} 个').format(res['skipped']))
        if pending:
            lines.append("")
            lines.append(t('⚠ {0} 个文件正被占用，已写成 .new：').format(len(pending)))
            lines.extend("    " + p for p in pending)
            lines.append(t('已安排延迟替换——请关闭本程序后自动完成。'))

        self.log("\n".join(lines))
        if st:
            st["progress"].setValue(100)
            st["progress"].setFormat(t('已安装'))
            st["dl_btn"].setEnabled(True)
            st["install_btn"].setEnabled(True)

        _show_result(self, res, target_dir, exe_path=os.path.join(target_dir, "llama-server.exe"))

        if self.mw and hasattr(self.mw, "recheck_llama_version"):
            self.mw.recheck_llama_version()
        self._version_worker = _VersionWorker(self._launcher_exe())
        self._version_worker.done.connect(self._on_version_refreshed)
        self._version_worker.start()

    def _on_version_refreshed(self, info):
        self._current_version = info or {}
        self._refresh_version_cards()
        self._apply_filter()

    def _on_install_err(self, msg):
        self.log(t('安装失败：{0}').format(msg))
        QMessageBox.critical(self, t('安装失败'), f"{msg}")

    # ------------------------------------------------------------- 详情
    def _on_row_clicked(self, item):
        meta = self._row_meta.get(item.row())
        if not meta:
            return
        rel = meta["release"]
        a = meta.get("asset")
        channel = t('预发布') if rel["prerelease"] else t('稳定')
        link = release_web_url(rel["tag"])
        if a:
            head = t('<b>{0}</b>　{1}<br>发布日期: {2}　|　通道: {3}<br>文件: {4}（{5}）').format(
                rel['tag'], rel.get('name', ''), rel['published_at'], channel,
                a['name'], human_size(a.get('size', 0)))
        else:
            head = t('<b>{0}</b>　{1}<br>发布日期: {2}　|　通道: {3}<br>此版本没有 Windows 预编译包。').format(
                rel['tag'], rel.get('name', ''), rel['published_at'], channel)
        body = html.escape((rel.get("body") or "")[:1800])
        text = (head + "<hr><pre style='white-space:pre-wrap;font-family:Consolas,monospace;'>"
                + body + "</pre><p><a href='{0}'>打开 Release 页面</a></p>".format(html.escape(link, quote=True)))
        self.detail_view.setHtml(text)

    def log(self, text):
        self.log_view.append(str(text))
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)
