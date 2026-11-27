# -*- coding: utf-8 -*-
"""菜单栏与帮助：更新入口、关于、文档链接、llama 版本复检。"""

import os
import webbrowser

from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QMessageBox
from .. import __version__, i18n
from ..about_dialog import AboutDialog
from ..i18n import LANGUAGES, t
from ..ui.workers import _LlamaVersionWorker
from ..ui.launcher_update_dialog import LauncherUpdateDialog


class MenuAboutMixin:
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
        menu_help.addSeparator()
        self.act_update_now = QAction(t('更新 llama.cpp…'), self)
        self.act_update_now.setToolTip(t('打开「更新 llama.cpp」页，选择版本 / 分支并安装'))
        menu_help.addAction(self.act_update_now)
        self.act_launcher_update = QAction(t('检查启动器更新…'), self)
        self.act_launcher_update.setToolTip(t('从 GitHub 检查本程序新版本，下载后退出并自动替换重启'))
        menu_help.addAction(self.act_launcher_update)

    def _on_llama_version(self, ver):
        if getattr(self, "_closing", False):
            return
        base = t('LLama 启动器 v{0}').format(__version__)
        self.setWindowTitle(f"{base} · llama {ver}" if ver else base)
        if hasattr(self, "label_llama_ver"):
            self.label_llama_ver.setText(
                t('llama: {0}').format(ver) if ver else t('llama: 未检测到'))

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

    def show_launcher_update(self):
        LauncherUpdateDialog(self, auto_check=True).exec()

    def check_launcher_update_silent(self):
        """启动后静默检查一次；有新版本时只改标题/状态栏，不弹窗。"""
        if getattr(self, "_closing", False):
            return
        if not self.cfg.data.get("check_launcher_update", True):
            return

        def work():
            try:
                from .. import launcher_updater
                rel = launcher_updater.latest_release()
                if launcher_updater.is_newer(__version__, rel.get("tag") or ""):
                    try:
                        self.launcher_update_found.emit(rel.get("tag") or "")
                    except RuntimeError:
                        pass
            except Exception:
                pass

        import threading
        threading.Thread(target=work, daemon=True).start()

    def _apply_launcher_update_hint(self, tag):
        base = t('LLama 启动器 v{0}').format(__version__)
        self.setWindowTitle(f"{base} · ⬆ {tag}")
        self._status_tip(t('发现启动器新版本 {0}：菜单「关于 → 检查启动器更新…」可升级').format(tag), 12000)

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
