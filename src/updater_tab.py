"""更新 llama.cpp（功能 10）：表格化版本浏览 + 逐行下载/安装。

- 从 GitHub Release 拉取 Windows x64 预编译包，每个 .zip 一行；
- 分支过滤（全部 / 仅稳定 / 仅预发布）、服务端翻页（↓ 追加下一页）；
- 断点续传下载（复用 ModelDownloader），下载到 <llama-server.exe 目录>\\temp；
- 「安全安装」：先按「当前版本号」把目标目录顶层文件备份到 bak\\<当前版本>.zip，
  再写入安装包内的新文件（不按大小跳过）；被占用的文件写成 .new 并安排进程退出后
  延迟替换。
"""
import os
import sys
import tempfile

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (QCheckBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                              QProgressBar, QPushButton, QRadioButton, QTableWidget,
                              QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from .llama_updater import (MODE_ALL, MODE_SERVER, UpdaterError, backup_launcher_dir,
                            get_local_version, install_from_zip, list_releases,
                            schedule_self_update, win_assets)
from .model_downloader import ModelDownloader
from .model_scanner import human_size

PER_PAGE = 30


class _ListWorker(QThread):
    ok = pyqtSignal(list)
    err = pyqtSignal(str)

    def __init__(self, page):
        super().__init__()
        self._page = page

    def run(self):
        try:
            rels = list_releases(per_page=PER_PAGE, include_prerelease=True, page=self._page)
            self.ok.emit(rels)
        except Exception as e:
            self.err.emit(str(e))


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
            cur_ver = get_local_version(
                os.path.join(self._dir, "llama-server.exe")) or "未知版本"
            self.log.emit(f"备份 {self._dir} 顶层文件（当前版本 {cur_ver}）→ bak\\{cur_ver}.zip")
            backup_cb = lambda d, t: self.backup_progress.emit(int(d * 100 // max(1, t)))
            backup_path = backup_launcher_dir(self._dir, cur_ver, progress_cb=backup_cb)
            if backup_path:
                self.log.emit("备份完成: " + os.path.basename(backup_path))
            else:
                self.log.emit("跳过备份（无可备份文件）")

            self.log.emit("开始安装…")
            install_cb = lambda d, t: self.install_progress.emit(int(d * 100 // max(1, t)))
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

    lines = [f"已安装到：{target_dir}"]
    if exe_path and os.path.isfile(exe_path):
        try:
            ver = get_local_version(exe_path) or "未知"
        except Exception:
            ver = "未知"
        lines.append(f"当前 llama 版本：{ver}")

    parts = []
    if counts.get("installed"):
        parts.append(f"新装 {counts['installed']}")
    if counts.get("replaced"):
        parts.append(f"替换 {counts['replaced']}")
    if counts.get("removed"):
        parts.append(f"删除旧文件 {counts['removed']}")
    if res.get("skipped"):
        parts.append(f"未选中 {res['skipped']}")
    lines.append("，".join(parts) + "。" if parts else "无文件变更。")
    if res.get("backup_path"):
        lines.append(f"备份：{os.path.basename(res['backup_path'])}")

    pending = res.get("pending", [])
    if pending:
        lines.append("")
        lines.append(f"⚠ {len(pending)} 个文件正被占用，已写成 .new，关闭本程序后自动替换。")
    QMessageBox.information(parent, "更新完成", "\n".join(lines))


class UpdaterTab(QWidget):
    def __init__(self, main_win=None):
        super().__init__()
        self.mw = main_win
        self._releases = []
        self._page = 0
        self._row_meta = {}
        self._state = {}
        self._downloader = ModelDownloader()
        self._list_worker = None
        self._install_worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        bar = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(self.btn_refresh)
        bar.addSpacing(12)

        bar.addWidget(QLabel("分支:"))
        self.radio_all = QRadioButton("全部")
        self.radio_stable = QRadioButton("仅稳定")
        self.radio_pre = QRadioButton("仅预发布")
        self.radio_all.setChecked(True)
        for r in (self.radio_all, self.radio_stable, self.radio_pre):
            r.toggled.connect(self._apply_filter)
            bar.addWidget(r)

        bar.addStretch(1)
        self.btn_more = QPushButton("↓ 加载更多")
        self.btn_more.clicked.connect(self.load_more)
        bar.addWidget(self.btn_more)
        self.btn_open_dl = QPushButton("打开下载目录")
        self.btn_open_dl.setToolTip("打开更新包下载目录")
        self.btn_open_dl.clicked.connect(self._open_dl_dir)
        bar.addWidget(self.btn_open_dl)
        self.label_status = QLabel("")
        bar.addWidget(self.label_status)
        root.addLayout(bar)

        self.chk_all_files = QCheckBox("安装 zip 内全部文件（含工具/示例，默认仅 server+DLL）")
        root.addWidget(self.chk_all_files)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["文件名", "版本", "日期", "分支", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 340)
        self.table.setColumnWidth(1, 120)
        self.table.setColumnWidth(2, 96)
        self.table.setColumnWidth(3, 96)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.itemClicked.connect(self._on_row_clicked)
        root.addWidget(self.table, 1)

        self.detail_view = QTextEdit()
        self.detail_view.setReadOnly(True)
        self.detail_view.setMaximumHeight(96)
        self.detail_view.setPlaceholderText("点击某一行查看该版本信息")
        root.addWidget(self.detail_view)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(120)
        self.log_view.setPlaceholderText("操作日志…")
        root.addWidget(self.log_view, 0)

        self._downloader.task_started.connect(self._on_task_started)
        self._downloader.progress.connect(self._on_progress)
        self._downloader.task_done.connect(self._on_task_done)
        self._downloader.task_failed.connect(self._on_task_failed)

    # ------------------------------------------------------------- 列表加载
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
        self._set_loading(True, "正在加载版本列表…")
        self._list_worker = _ListWorker(self._page)
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
        self._set_loading(True, f"正在加载第 {self._page} 页…")
        self._list_worker = _ListWorker(self._page)
        self._list_worker.ok.connect(self._on_list_ok)
        self._list_worker.err.connect(self._on_list_err)
        self._list_worker.start()

    def _set_loading(self, loading, text=""):
        self.btn_refresh.setEnabled(not loading)
        self.btn_more.setEnabled(not loading)
        if text:
            self.label_status.setText(text)

    def _on_list_ok(self, rels):
        for rel in rels:
            assets = win_assets(rel)
            if not assets:
                continue
            self._releases.append({"release": rel, "assets": assets})
            self._append_release_rows(rel, assets)
        self._apply_filter()
        n = sum(len(x["assets"]) for x in self._releases)
        dl = sum(1 for s in self._state.values() if s.get("downloaded"))
        text = f"共 {len(self._releases)} 个版本 / {n} 个 Windows 包"
        if dl:
            text += f"（{dl} 已下载）"
        self.label_status.setText(text)
        self._set_loading(False)

    def _on_list_err(self, msg):
        self._set_loading(False)
        if self._page == 1:
            self.label_status.setText("加载失败")
        QMessageBox.critical(self, "加载失败", f"获取版本列表失败：\n{msg}")

    def _append_release_rows(self, rel, assets):
        base = self.table.rowCount()
        for a in assets:
            r = base
            base += 1
            self.table.insertRow(r)
            name = a["name"]
            key = f"{rel['tag']}::{name}"

            it_name = QTableWidgetItem(name)
            it_name.setToolTip(f"大小: {human_size(a['size'])}\n{a['url']}")
            self.table.setItem(r, 0, it_name)
            self.table.setItem(r, 1, QTableWidgetItem(rel["tag"]))
            self.table.setItem(r, 2, QTableWidgetItem(rel["published_at"]))
            branch = "预发布" if rel["prerelease"] else "主分支(稳定)"
            self.table.setItem(r, 3, QTableWidgetItem(branch))

            op = self._make_op_widget(key, name, a)
            self.table.setCellWidget(r, 4, op)

            self._row_meta[r] = {"release": rel, "asset": a, "key": key}

    def _make_op_widget(self, key, name, asset):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(4)
        dl = QPushButton("下载")
        pb = QProgressBar()
        pb.setRange(0, 100)
        pb.setValue(0)
        pb.setMinimumWidth(96)
        inst = QPushButton("安装")
        inst.setEnabled(False)
        lay.addWidget(dl)
        lay.addWidget(pb, 1)
        lay.addWidget(inst)

        rel_tag = key.split("::", 1)[0]
        self._state[key] = {
            "dl_btn": dl, "install_btn": inst, "progress": pb,
            "downloaded": False, "dest": "", "name": name,
            "url": asset["url"], "tag": rel_tag,
            "size": asset.get("size", 0),
        }
        dest = self._tmp_path(rel_tag, name)
        if os.path.isfile(dest):
            st = self._state[key]
            st["downloaded"] = True
            st["dest"] = dest
            pb.setValue(100)
            pb.setFormat("已下载")
            inst.setEnabled(True)

        dl.clicked.connect(lambda *_: self._on_download(key))
        inst.clicked.connect(lambda *_: self._on_install(key))
        return w

    # ------------------------------------------------------------- 过滤
    def _apply_filter(self):
        if self.radio_stable.isChecked():
            want = lambda pre: not pre
        elif self.radio_pre.isChecked():
            want = lambda pre: pre
        else:
            want = lambda pre: True
        for r, meta in self._row_meta.items():
            self.table.setRowHidden(r, not want(meta["release"]["prerelease"]))

    def _on_row_clicked(self, item):
        meta = self._row_meta.get(item.row())
        if not meta:
            return
        rel = meta["release"]
        a = meta["asset"]
        branch = "预发布" if rel["prerelease"] else "主分支(稳定)"
        text = (f"<b>{rel['tag']}</b>　{rel.get('name','')}<br>"
                f"发布日期: {rel['published_at']}　|　分支: {branch}<br>"
                f"文件: {a['name']}（{human_size(a.get('size',0))}）")
        self.detail_view.setHtml(text)

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

    def _open_dl_dir(self):
        d = self._dl_root()
        try:
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            os.startfile(d)  # type: ignore[attr-defined]
        except OSError as e:
            QMessageBox.critical(self, "错误", str(e))

    def _on_download(self, key):
        st = self._state[key]
        dest = self._tmp_path(st["tag"], st["name"])
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "错误", f"无法创建临时目录：\n{e}")
            return
        st["dest"] = dest
        st["dl_btn"].setEnabled(False)
        st["progress"].setValue(0)
        st["progress"].setFormat("排队中…")
        self.log(f"开始下载 {st['name']}（{human_size(st['size'])}）→ {dest}")
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
        st["progress"].setFormat("已下载")
        st["install_btn"].setEnabled(True)
        st["dl_btn"].setEnabled(True)
        self.log(f"下载完成 {st['name']}")

    def _on_task_failed(self, key, err):
        st = self._state.get(key)
        if not st:
            return
        st["progress"].setFormat("失败")
        st["dl_btn"].setEnabled(True)
        self.log(f"下载失败 {st['name']}: {err}")
        QMessageBox.critical(self, "下载失败", f"{st['name']}：\n{err}\n\n可点击「下载」重试（支持断点续传）。")

    # ------------------------------------------------------------- 安装
    def _target_dir(self):
        exe = self.mw._launcher_exe() if self.mw else ""
        d = os.path.dirname(exe) if exe else ""
        return d or (self.mw.base_dir if self.mw else "")

    def _on_install(self, key):
        st = self._state[key]
        if not st["downloaded"] or not os.path.isfile(st["dest"]):
            QMessageBox.information(self, "提示", "请先下载该文件再安装。")
            return
        if self._install_worker and self._install_worker.isRunning():
            QMessageBox.information(self, "提示", "已有安装任务进行中，请稍候。")
            return
        target_dir = self._target_dir()
        if not target_dir or not os.path.isdir(target_dir):
            QMessageBox.critical(self, "错误", f"目标目录无效：\n{target_dir}")
            return
        mode = MODE_ALL if self.chk_all_files.isChecked() else MODE_SERVER

        ret = QMessageBox.question(
            self, "确认安装",
            f"将把 {st['name']} 安装到：\n{target_dir}\n\n"
            "会先备份该目录顶层文件，删除旧版本二进制/DLL，再解压安装所有选中文件。\n"
            "模型与配置不受影响。继续？")
        if ret != QMessageBox.StandardButton.Yes:
            return

        st["dl_btn"].setEnabled(False)
        st["install_btn"].setEnabled(False)
        self.log(f"开始安装 {st['name']} → {target_dir}")
        self._install_worker = _InstallWorker(st["dest"], target_dir, mode)
        self._install_worker.log.connect(self.log)
        self._install_worker.backup_progress.connect(
            lambda p: (self.log(f"备份进度 {p}%"), st["progress"].setValue(p)))
        self._install_worker.install_progress.connect(
            lambda p: (self.log(f"安装进度 {p}%"), st["progress"].setFormat(f"安装 {p}%")))
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

        lines = ["安装完成："]
        counts = {}
        for _name, status in actions:
            counts[status] = counts.get(status, 0) + 1
        if counts.get("installed"):
            lines.append(f"  新装 {counts['installed']} 个")
        if counts.get("replaced"):
            lines.append(f"  替换 {counts['replaced']} 个")
        if counts.get("removed"):
            lines.append(f"  删除旧文件 {counts['removed']} 个")
        if res["skipped"]:
            lines.append(f"  未选中 {res['skipped']} 个")
        if pending:
            lines.append("")
            lines.append(f"⚠ {len(pending)} 个文件正被占用，已写成 .new：")
            lines.extend("    " + p for p in pending)
            lines.append("已安排延迟替换——请关闭本程序后自动完成。")

        self.log("\n".join(lines))
        if st:
            st["progress"].setValue(100)
            st["progress"].setFormat("已安装")
            st["dl_btn"].setEnabled(True)
            st["install_btn"].setEnabled(True)

        _show_result(self, res, target_dir, exe_path=os.path.join(target_dir, "llama-server.exe"))

        if self.mw and hasattr(self.mw, "recheck_llama_version"):
            self.mw.recheck_llama_version()

    def _on_install_err(self, msg):
        self.log(f"安装失败：{msg}")
        QMessageBox.critical(self, "安装失败", f"{msg}")

    # ------------------------------------------------------------- 日志
    def log(self, text):
        self.log_view.append(str(text))
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)
