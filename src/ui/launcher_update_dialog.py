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

_KIND_LABEL = {
    "single": t('单文件版'),
    "portable": t('便携目录版（exe + _internal）'),
    "source": t('源码运行'),
}


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

    def __init__(self, url, dest, expect_size=0):
        super().__init__()
        self._url = url
        self._dest = dest
        self._expect = expect_size
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            path = up.download(self._url, self._dest,
                               progress_cb=lambda d, t2: self.progress.emit(d, t2),
                               cancel=lambda: self._cancel,
                               expect_size=self._expect)
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
        self._kind = up.install_kind()

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
        # 安装形态：决定挑哪个包、能不能自动替换（便携版要连 _internal 一起换）
        self.label_kind = QLabel(t('安装形态: {0}').format(_KIND_LABEL.get(self._kind, self._kind)))
        self.label_kind.setToolTip(
            t('单文件版只换一个 exe；便携目录版旁边还有 _internal 依赖目录，\n'
              '升级时会连依赖一起换，你自己的 config.json、日志、统计都不会动。'))
        info.addWidget(self.label_current)
        info.addSpacing(16)
        info.addWidget(self.label_latest)
        info.addSpacing(16)
        info.addWidget(self.label_kind)
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
        self._check_worker.ok.connect(self._apply_release)
        self._check_worker.err.connect(self._on_check_err)
        self._check_worker.start()

    def _apply_release(self, rel):
        """把检查结果落到界面上：能不能升级、会拿到哪个包，都写明白。"""
        self.btn_check.setEnabled(True)
        self._release = rel
        tag = rel.get("tag") or ""
        self.label_latest.setText(t('最新版本: {0}（{1}）').format(tag, rel.get("published_at") or "—"))
        if not up.is_newer(__version__, tag):
            self.badge.set_status(t('已是最新'), "info")
            self.btn_install.setEnabled(False)
        else:
            self._asset = up.pick_asset(rel, kind=self._kind)
            if not self._asset:
                self.badge.set_status(t('新版本没有可用安装包'), "warn")
                self.btn_install.setEnabled(False)
            else:
                note = ""
                # 便携版没打到 zip 时会被换成单文件包：能跑，但要说清楚
                if self._kind == "portable" and str(self._asset.get("name", "")
                                                    ).lower().endswith(".exe"):
                    note = t(' · ') + t('便携包缺失，将改用单文件版')
                self.badge.set_status(
                    t('发现新版本 · {0}').format(self._asset.get("name")) + note, "ok")
                self.btn_install.setEnabled(True)
        body = (rel.get("body") or "")[:6000]
        html = ("<h3>" + tag + "　" + (rel.get("name") or "") + "</h3>"
                "<pre style='white-space:pre-wrap;font-family:Consolas,monospace;'>"
                + _esc(body) + "</pre>")
        if rel.get("html_url"):
            html += "<p><a href='{0}'>{1}</a></p>".format(
                _esc(rel["html_url"], quote=True), t('打开发布页面'))
        self.notes.setHtml(html)

    def _on_check_err(self, msg):
        self.btn_check.setEnabled(True)
        self.badge.set_status(t('检查失败'), "err")
        QMessageBox.critical(self, t('检查失败'), msg)

    def _open_page(self):
        url = (self._release or {}).get("html_url") or "https://github.com/lop008/llama-gui-launcher/releases"
        QDesktopServices.openUrl(QUrl(url))

    def _fail(self, msg, retry=True):
        """失败时统一收尾：状态栏/徽标说清楚，按钮恢复。"""
        self.progress.setVisible(False)
        self.badge.set_status(t('升级失败'), "err")
        self.btn_check.setEnabled(True)
        self.btn_install.setEnabled(bool(retry))
        QMessageBox.critical(self, t('升级失败'), msg)

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
        size = int(self._asset.get("size") or 0)
        # 磁盘不够就别开始了：便携包要同时容下 zip + 解压后的 _internal（约两倍）
        need = size * (3 if name.lower().endswith(".zip") else 2)
        enough, avail = up.disk_space_ok(sys.executable, need)
        if not enough:
            self._fail(t('磁盘余量不足：本次升级约需 {0:.1f} GiB，当前只剩 {1:.1f} GiB。'
                         '清理后重试。').format(need / 1024 ** 3, avail), retry=True)
            return
        tag = str(self._release.get("tag") or "latest").replace("/", "_")
        dest = os.path.join(tempfile.gettempdir(), f"LLama-Launcher-{tag}-new"
                            + (".zip" if name.lower().endswith(".zip") else ".exe"))
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.btn_install.setEnabled(False)
        self.btn_check.setEnabled(False)
        self._download_worker = _DownloadWorker(url, dest, expect_size=size)
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
        """下载完成 → 先验货，再准备替换；**验不过绝不碰用户现有的程序**。"""
        self.progress.setValue(100)
        ok, why = up.verify_download(path, self._asset)
        if not ok:
            try:
                os.remove(path)      # 坏文件留在临时目录只会被下次续传坑回来
            except OSError:
                pass
            self._fail(t('下载的文件没有通过校验：{0}。\n'
                         '可能是网络中断、代理改写或安全软件拦截，已删除该文件，请重试。').format(why))
            return
        internal_dir = None
        try:
            if path.lower().endswith(".zip"):
                # 便携版：先在临时目录解压备齐，替换脚本只做搬运，失败也能整段回滚
                stage = os.path.join(tempfile.gettempdir(), "llama_launcher_stage")
                got = up.extract_package(path, stage)
                new_exe, internal_dir = got["exe"], got["internal"]
            else:
                new_exe = path
            up.schedule_replace(new_exe, sys.executable, pid=os.getpid(), restart=True,
                                internal_dir=internal_dir)
        except Exception as e:
            self._fail(str(e))
            return
        QMessageBox.information(
            self, t('准备重启'),
            t('新版本已准备就绪。点击「确定」后本程序会退出，替换文件并自动重启。\n'
              '替换过程若有任何一步失败，会自动恢复当前版本，不会让程序打不开。'))
        QApplication.instance().quit()

    def _on_download_err(self, msg):
        self.progress.setVisible(False)
        self.btn_install.setEnabled(True)
        self.btn_check.setEnabled(True)
        QMessageBox.critical(self, t('下载失败'), msg)


def _esc(text, quote=False):
    import html
    return html.escape(str(text), quote=quote)
