# -*- coding: utf-8 -*-
"""「下载草稿」对话框：在 HuggingFace 上找与当前主模型配套的投机解码草稿文件。

为什么要单独做一个界面而不是直接用「模型下载」页：那个页是按仓库翻主模型的，
而草稿要同时满足三个条件——是草稿（不是主模型）、和当前主模型同名配套、
必须落到主模型同一个目录（扫描器只在同目录配对，见 model_scanner.drafts_for）。
这里把这三件事固定下来，用户只需要点「下载」。

排序与判定都在 src/draft_hub.py（纯函数、可离线单测），本文件只管线程和控件。
"""

import os
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from .. import draft_hub, hf_browse
from ..i18n import t
from ..gguf_reader import read_gguf_info
from ..model_scanner import human_size
from ..model_downloader import ModelDownloader
from ..spec_decode import spec_label

# 最多翻几个仓库：再多就慢，而且排名靠后的基本没用
MAX_REPOS = 6


class DraftDownloadDialog(QDialog):
    """列出候选草稿文件，点一下就下到主模型目录；下完自动让主界面认出来。"""

    _found = pyqtSignal(list, list)        # rows, errors
    _progress = pyqtSignal(str)

    def __init__(self, main_win, model_path):
        super().__init__(main_win)
        self.mw = main_win
        self.model_path = model_path
        self.model_dir = os.path.dirname(str(model_path or ""))
        self.query = ""
        self._rows = []
        self._busy = False

        self.setWindowTitle(t('下载投机解码草稿'))
        self.resize(1080, 560)
        # 严格模态：避免打开/关闭时的鼠标释放或回车穿透到主窗口下面的下载按钮
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        lay = QVBoxLayout(self)
        head = QLabel(t('主模型: {0}\n草稿会下载到: {1}（必须和主模型同目录才会被认出来）')
                      .format(os.path.basename(str(model_path or "")), self.model_dir))
        head.setWordWrap(True)
        lay.addWidget(head)

        row = QHBoxLayout()
        row.addWidget(QLabel(t('搜索关键词:')))
        self.edit_query = QLineEdit()
        self.edit_query.setPlaceholderText(t('默认取模型元数据里的基础模型名，可改成 HF 上的仓库名'))
        self.edit_query.setToolTip(t('改完点「搜索」重新列。留空则用模型元数据里的名字。'))
        row.addWidget(self.edit_query, 1)
        self.btn_search = QPushButton(t('搜索'))
        row.addWidget(self.btn_search)
        self.btn_open_dir = QPushButton(t('打开草稿目录'))
        self.btn_open_dir.clicked.connect(self._open_dir)
        row.addWidget(self.btn_open_dir)
        self.btn_full_page = QPushButton(t('在「模型下载」页找'))
        self.btn_full_page.setToolTip(t('想看完整仓库列表（不只草稿）时用，会切到下载页并预填关键词。'))
        self.btn_full_page.clicked.connect(self._open_full_page)
        row.addWidget(self.btn_full_page)
        for _b in (self.btn_search, self.btn_open_dir, self.btn_full_page):
            _b.setAutoDefault(False)
        lay.addLayout(row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [t('方式'), t('文件'), t('仓库'), t('大小'), t('说明'), ""])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        head_view = self.table.horizontalHeader()
        head_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        head_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(2, 260)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(5, 90)
        lay.addWidget(self.table, 1)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.label_state = QLabel(t('说明：官方 GGUF 仓库（ggml-org / unsloth 等）里的 MTP/、DFLASH/ '
                                    '目录可直接下载；原作者仓库多半只有 safetensors，需要自己转换。'))
        self.label_state.setWordWrap(True)
        lay.addWidget(self.label_state)

        btns = QHBoxLayout()
        btns.addStretch(1)
        self.btn_close = QPushButton(t('关闭'))
        self.btn_close.clicked.connect(self.reject)
        self.btn_close.setAutoDefault(False)
        btns.addWidget(self.btn_close)
        lay.addLayout(btns)

        self.downloader = ModelDownloader()
        self.downloader.task_started.connect(self._on_started)
        self.downloader.progress.connect(self._on_progress)
        self.downloader.task_done.connect(self._on_done)
        self.downloader.task_failed.connect(self._on_failed)

        self._found.connect(self._show_results)
        self._progress.connect(lambda text: self.label_state.setText(text))
        self.btn_search.clicked.connect(self.search)
        try:
            info = read_gguf_info(self.model_path) or {}
        except Exception:
            info = {}
        self.query = draft_hub.base_query(self.model_path, info)
        self.edit_query.setText(self.query)
        self.search()

    # ------------------------------------------------------------- 查询
    def search(self):
        if self._busy:
            return
        self._busy = True
        self.query = (self.edit_query.text().strip() or draft_hub.base_query(self.model_path))
        self.table.setRowCount(0)
        self.label_state.setText(t('正在搜索 {0} …').format(self.query))
        self.btn_search.setEnabled(False)

        def work():
            rows, errors = [], []
            try:
                repos = hf_browse.list_repos(author="", search=self.query, limit=50)
            except Exception as e:
                self._found.emit([], [t('搜索失败: {0}').format(e)])
                return
            for r in draft_hub.rank_repos(repos, self.query)[:MAX_REPOS]:
                self._progress.emit(t('正在看 {0} …').format(r["id"]))
                try:
                    info = hf_browse.repo_files(r["id"])
                except Exception as e:
                    errors.append("{0}: {1}".format(r["id"], e))
                    continue
                rows.extend(draft_hub.pick_files(r["id"], info.get("files"), self.query))
            rows.sort(key=lambda x: (-x["score"],
                                     1 if "old" in str(x.get("path", "")).lower() else 0,
                                     x["size"]))
            self._found.emit(rows[:40], errors)

        threading.Thread(target=work, daemon=True).start()

    def _show_results(self, rows, errors):
        self._busy = False
        self.btn_search.setEnabled(True)
        self._rows = rows
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            cells = [spec_label(r["kind"]) or (r["kind"] or "?"),
                     os.path.basename(r["path"]), r["repo"],
                     human_size(r["size"]), r["note"]]
            for col, text in enumerate(cells):
                it = QTableWidgetItem(str(text))
                it.setToolTip(r["repo"] + "/" + r["path"])
                self.table.setItem(i, col, it)
            btn = QPushButton(t('下载'))
            btn.setAutoDefault(False)
            btn.clicked.connect(lambda _=False, row=r: self._download(row))
            self.table.setCellWidget(i, 5, btn)
        if not rows:
            kind = draft_hub.guess_spec_kind(self.query)
            self.label_state.setText(
                t('没找到与 {0} 配套的草稿文件。').format(self.query) + "\n"
                + draft_hub.conversion_hint(kind))
            if errors:
                self.label_state.setToolTip("\n".join(errors))
        else:
            self.label_state.setText(t('找到 {0} 个候选，点「下载」即可（下完会自动选中）。').format(len(rows)))

    # ------------------------------------------------------------- 下载
    def _download(self, row):
        if not self.model_dir or not os.path.isdir(self.model_dir):
            QMessageBox.warning(self, t('提示'), t('模型目录无效，请先在基础页选好模型目录。'))
            return
        taken = [os.path.join(self.model_dir, fn) for fn in os.listdir(self.model_dir)]
        dest = draft_hub.dest_path(self.model_dir, row["repo"], row["path"], taken)
        if os.path.exists(dest):
            ret = QMessageBox.question(
                self, t('文件已存在'),
                t('{0}\n已经存在，要覆盖重下吗？').format(dest),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return
        url = hf_browse.file_url(row["repo"], row["path"])
        self.bar.setRange(0, 0)
        self.bar.setVisible(True)
        self.label_state.setText(t('开始下载 {0} …').format(os.path.basename(dest)))
        self.downloader.enqueue(url, dest, label=os.path.basename(dest))

    def _on_started(self, label):
        self.label_state.setText(t('正在下载 {0} …').format(label))

    def _on_progress(self, label, done, total, speed):
        if total > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(done * 100 / total))
            self.label_state.setText(t('正在下载 {0}：{1}/{2}（{3}/s）')
                                     .format(label, human_size(done), human_size(total),
                                             human_size(int(speed))))

    def _on_done(self, label, path):
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.bar.setVisible(False)
        self.label_state.setText(t('已下载 {0}').format(path))
        self._pair_back(path)

    def _on_failed(self, label, err):
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.bar.setVisible(False)
        self.label_state.setText(t('下载失败 {0}: {1}').format(label, err))

    def _pair_back(self, path):
        """让主界面重新扫目录、丢掉该模型的投机缓存，并把新草稿选上。"""
        try:
            cache = getattr(self.mw, "_spec_cache", None)
            if isinstance(cache, dict):
                cache.pop(self.model_path, None)
            self.mw.refresh_models(keep_selection=True)
            self.mw._status_tip(t('草稿已放到模型目录，正在刷新并自动选中…'), 6000)

            # 扫描是异步的：稍后再把新文件选中；同时把方式切到对应类型
            from PyQt6.QtCore import QTimer

            def _select():
                try:
                    kind = draft_hub.guess_spec_kind(path)
                    if kind:
                        idx = self.mw.combo_spec.findData(kind)
                        if idx >= 0:
                            self.mw.combo_spec.setCurrentIndex(idx)
                    i = self.mw.combo_draft.findData(path)
                    if i >= 0:
                        self.mw.combo_draft.setCurrentIndex(i)
                        self.mw._status_tip(t('已自动选中新下载的草稿'), 5000)
                except Exception:
                    pass

            QTimer.singleShot(1200, _select)
        except Exception:
            pass    # 刷新失败不影响下载本身，用户手动点「刷新模型」也一样能认

    # ------------------------------------------------------------- 杂项
    def _open_dir(self):
        if self.model_dir and os.path.isdir(self.model_dir):
            os.startfile(self.model_dir)  # noqa: S606
        else:
            QMessageBox.information(self, t('提示'), t('模型目录无效'))

    def _open_full_page(self):
        try:
            self.mw._download_spec_draft(self.query)
        except Exception:
            pass
