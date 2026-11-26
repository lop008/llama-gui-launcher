# -*- coding: utf-8 -*-
"""系统托盘、悬浮小窗、应用图标、语言切换与重启。"""

import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QMessageBox, QSystemTrayIcon
from .. import i18n
from ..i18n import t
from ..pill import HoverPill


class TrayPillMixin:
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
