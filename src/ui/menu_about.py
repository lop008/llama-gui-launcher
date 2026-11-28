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
        self.menu_tools = menu_tools
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
        self.act_validate_bat = QAction(t('校验启动文件…'), self)
        self.act_validate_bat.setToolTip(
            t('检查启动文件里的参数是否还有效、有没有被 llama.cpp 废弃或改名，并评估显存/内存是否吃得住'))
        self.act_export_preview_bat = QAction(t('导出命令预览 (.bat)…'), self)
        self.act_export_preview_bat.setToolTip(
            t('把「命令预览」页里的完整命令行原样保存为 .bat 文件，可自选存储路径（功能 6）'))
        self.act_stats = QAction(t('数据统计…'), self)
        self.act_stats.setToolTip(
            t('打开独立的数据统计界面：打开次数、使用时长、输入/输出 token，支持按小时 / 日 / 月查看（功能 9）'))
        # 原来 13 项平铺一屏列不完，也看不出哪些是同类；按用途收成二级菜单，
        # 「语言」也从顶栏挪进来（顶栏只留 开始 / 工具 / 关于，宽度更宽松）。
        sub_model = menu_tools.addMenu(t('模型'))
        sub_model.addAction(self.act_refresh)
        sub_model.addAction(self.act_open_dir)
        sub_net = menu_tools.addMenu(t('服务与网页'))
        sub_net.addAction(self.act_web)
        sub_net.addAction(self.act_api)
        sub_net.addAction(self.act_open_agent)
        sub_bat = menu_tools.addMenu(t('启动文件'))
        sub_bat.addAction(self.act_import_bat)
        sub_bat.addAction(self.act_validate_bat)
        sub_bat.addAction(self.act_export_bat)
        sub_bat.addAction(self.act_export_preview_bat)
        sub_cfg = menu_tools.addMenu(t('配置'))
        sub_cfg.addAction(self.act_export)
        sub_cfg.addAction(self.act_import)
        sub_log = menu_tools.addMenu(t('日志与统计'))
        sub_log.addAction(self.act_clear_log)
        sub_log.addAction(self.act_open_log)
        sub_log.addSeparator()
        sub_log.addAction(self.act_stats)

        # 字号：Ctrl+滚轮能调，但光靠快捷键没人知道；这里给出可见入口与说明。
        sub_font = menu_tools.addMenu(t('字号'))
        self.act_font_in = QAction(t('放大字号'), self)
        self.act_font_in.setShortcuts(["Ctrl++", "Ctrl+="])
        self.act_font_in.setToolTip(t('Ctrl+鼠标滚轮上滚也可以；缩放倍数会被记住，Ctrl+0 恢复默认'))
        self.act_font_out = QAction(t('缩小字号'), self)
        self.act_font_out.setShortcuts(["Ctrl+-"])
        self.act_font_out.setToolTip(t('Ctrl+鼠标滚轮下滚也可以'))
        self.act_font_reset = QAction(t('恢复默认字号'), self)
        self.act_font_reset.setShortcuts(["Ctrl+0"])
        self.act_font_reset.setToolTip(t('回到主题出厂字号（100%）'))
        sub_font.addAction(self.act_font_in)
        sub_font.addAction(self.act_font_out)
        sub_font.addSeparator()
        sub_font.addAction(self.act_font_reset)

        menu_tools.addSeparator()
        menu_lang = menu_tools.addMenu(t('语言(&L)'))
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

    def report_last_self_update(self):
        """上次自升级的收尾提示：替换脚本只能写标记文件，弹框得靠这里。

        重点是失败场景——脚本会自动把 .bak 改回去，但如果没人告诉用户「刚才那次
        升级失败了、现在跑的还是原版本」，用户只会觉得「点了升级没反应」。
        """
        try:
            from .. import launcher_updater
            code = launcher_updater.read_last_result()
        except Exception:
            return
        if not code or code == launcher_updater.RESULT_OK:
            return
        msg = launcher_updater.result_text(code)
        try:
            self._status_tip(t('启动器升级：{0}').format(msg), 15000)
            self._log_file(t('启动器升级结果：{0}（标记 {1}）').format(msg, code))
        except Exception:
            pass

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
