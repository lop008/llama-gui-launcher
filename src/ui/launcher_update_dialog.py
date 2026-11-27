# -*- coding: utf-8 -*-
"""启动器自升级对话框：检查 GitHub 最新 Release、下载、退出后替换并重启。"""
import os
import sys
import tempfile

from PyQt6.QtCore import QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QTextBrowser, QVBoxLayout,
)

from .. import __version__
from .. import launcher_updater as up
from ..i18n import t
from .kit import Badge, Card, SectionHeader


class _CheckWorker(QThread):
    ok = pyqtSignal(object)
    err = pyqtSignal(str)

    def run(self):
        try:
            self.ok.emit(up.latest_release())
        except Exception as e:
            self.err.emit(str(e))


class _DownloadWorker(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(str)
    err = pyqtSignal(str)

    def __init__(self, url, dest):
        super().__init__()
        self._url = url
        self._dest = dest
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            path = up.download(self._url, self._dest,
                               progress_cb=lambda d, t2: self.progress.emit(d, t2),
                               cancel=lambda: self._cancel)
            self.done.emit(path)
        except Exception as e:
            self.err.emit(str(e))


class LauncherUpdateDialog(QDialog):
    def __init__(self, parent=None, auto_check=True):
        super().__init__(parent)
        self.setWindowTitle(t('检查启动器更新'))
        self.resize(720, 520)
        self._release = None
        self._asset = None
        self._check_worker = None
        self._download_worker = None

        root = QVBoxLayout(self)
        root.setSpacing(8)
        hero = Card()
        head = SectionHeader(t('启动器自升级'),
                             t('从 GitHub 获取最新版本；下载完成后退出本程序，自动替换并重启。'))
        self.badge = Badge(t('检查中…'), "info")
        head.add_action(self.badge)
        hero.add(head)

        info = QHBoxLayout()
        self.label_current = QLabel(t('当前版本: v{0}').format(__version__))
        self.label_latest = QLabel(t('最新版本: 检查中…'))
        info.addWidget(self.label_current)
        info.addSpacing(16)
        info.addWidget(self.label_latest)
        info.addStretch(1)
        hero.add_layout(info)

        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setPlaceholderText(t('版本说明…'))
        self.notes.setMinimumHeight(180)
        hero.add(self.notes, 1)

        row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        row.addWidget(self.progress, 1)
        self.btn_page = QPushButton(t('打开发布页面'))
        self.btn_page.setProperty("variant", "ghost")
        self.btn_page.clicked.connect(self._open_page)
        self.btn_check = QPushButton(t('重新检查'))
        self.btn_check.setProperty("variant", "ghost")
        self.btn_check.clicked.connect(self.check)
        self.btn_install = QPushButton(t('下载并安装'))
        self.btn_install.setProperty("variant", "primary")
        self.btn_install.setEnabled(False)
        self.btn_install.clicked.connect(self._install)
        self.btn_close = QPushButton(t('关闭'))
        self.btn_close.clicked.connect(self.reject)
        for b in (self.btn_page, self.btn_check, self.btn_install, self.btn_close):
            row.addWidget(b)
        hero.add_layout(row)
        root.addWidget(hero, 1)

        if auto_check:
            self.check()

    def check(self):
        if self._check_worker and self._check_worker.isRunning():
            return
        self.badge.set_status(t('检查中…'), "info")
        self.btn_install.setEnabled(False)
        self.btn_check.setEnabled(False)
        self._check_worker = _CheckWorker()
        self._check_worker.ok.connect(self._on_check_ok)
        self._check_worker.err.connect(self._on_check_err)
        self._check_worker.start()

    def _on_check_ok(self, rel):
        self.btn_check.setEnabled(True)
        self._release = rel
        tag = rel.get("tag") or ""
        self.label_latest.setText(t('最新版本: {0}（{1}）').format(tag, rel.get("published_at") or "—"))
        if up.is_newer(__version__, tag):
            self.badge.set_status(t('发现新版本'), "ok")
        else:
            self.badge.set_status(t('已是最新'), "info")
        self._asset = up.pick_asset(rel)
        if up.is_newer(__version__, tag):
            if self._asset:
                self.badge.set_status(
                    t('发现新版本 · {0}').format(self._asset.get("name")), "ok")
            else:
                self.badge.set_status(t('新版本没有可用安装包'), "warn")
        else:
            self.badge.set_status(t('已是最新'), "info")
        body = (rel.get("body") or "")[:6000]
        html = ("<h3>" + tag + "　" + (rel.get("name") or "") + "</h3>"
                "<pre style='white-space:pre-wrap;font-family:Consolas,monospace;'>"
                + _esc(body) + "</pre>")
        if rel.get("html_url"):
            html += "<p><a href='{0}'>{1}</a></p>".format(
                _esc(rel["html_url"], quote=True), t('打开发布页面'))
        self.notes.setHtml(html)
        can = up.is_newer(__version__, tag) and self._asset is not None
        self.btn_install.setEnabled(bool(can))
        if up.is_newer(__version__, tag) and not self._asset:
            self.badge.set_status(t('新版本没有可用安装包'), "warn")

    def _on_check_err(self, msg):
        self.btn_check.setEnabled(True)
        self.badge.set_status(t('检查失败'), "err")
        QMessageBox.critical(self, t('检查失败'), msg)

    def _open_page(self):
        url = (self._release or {}).get("html_url") or "https://github.com/lop008/llama-gui-launcher/releases"
        QDesktopServices.openUrl(QUrl(url))

    def _install(self):
        if not self._release or not self._asset:
            return
        if not up.can_self_update():
            QMessageBox.information(
                self, t('源码运行模式'),
                t('当前是源码运行（python main.py），不能自动替换自身。\n已为你打开 Release 页面，请下载新版 exe。'))
            self._open_page()
            return
        url = self._asset.get("url") or ""
        name = self._asset.get("name") or "launcher.exe"
        if not name.lower().endswith(".exe"):
            QMessageBox.information(
                self, t('需要手动解压'),
                t('最新版只提供了 portable zip，无法自动替换。\n已为你打开 Release 页面。'))
            self._open_page()
            return
        tag = str(self._release.get("tag") or "latest").replace("/", "_")
        dest = os.path.join(tempfile.gettempdir(), f"LLama-Launcher-{tag}-new.exe")
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_install.setEnabled(False)
        self.btn_check.setEnabled(False)
        self._download_worker = _DownloadWorker(url, dest)
        self._download_worker.progress.connect(self._on_progress)
        self._download_worker.done.connect(self._on_download_done)
        self._download_worker.err.connect(self._on_download_err)
        self._download_worker.start()

    def _on_progress(self, done, total):
        if total > 0:
            self.progress.setValue(int(done * 100 // total))
            self.progress.setFormat(f"{done / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB")
        else:
            self.progress.setFormat(f"{done / 1024 / 1024:.1f} MB")

    def _on_download_done(self, path):
        self.progress.setValue(100)
        try:
            up.schedule_replace(path, sys.executable, pid=os.getpid(), restart=True)
        except Exception as e:
            QMessageBox.critical(self, t('安装失败'), str(e))
            self.btn_install.setEnabled(True)
            self.btn_check.setEnabled(True)
            return
        QMessageBox.information(
            self, t('准备重启'),
            t('新版本已下载。点击「确定」后本程序会退出，替换文件并自动重启。'))
        QApplication.instance().quit()

    def _on_download_err(self, msg):
        self.progress.setVisible(False)
        self.btn_install.setEnabled(True)
        self.btn_check.setEnabled(True)
        QMessageBox.critical(self, t('下载失败'), msg)


def _esc(text, quote=False):
    import html
    return html.escape(str(text), quote=quote)
