# -*- coding: utf-8 -*-
"""启动/停止服务、健康检查与退出回调、局域网与 HTTPS、端口占用与残留进程检测。"""

import os
import webbrowser

from PyQt6.QtWidgets import QCheckBox, QMessageBox
from ..bat_validator import ValidateBatDialog
from ..cmd_builder import build_args, build_command
from ..i18n import t
from ..net_utils import default_cert_paths, ensure_self_signed_cert, local_ipv4
from ..server import find_llama_server_processes, kill_all_llama_server, port_in_use


CREATE_NO_WINDOW = 0x08000000


class LaunchFlowMixin:
    # ------------------------------------------------------------- 预览

    def update_preview(self):
        if self._loading:
            return
        model = self.combo_model.currentData()
        if not model:
            self.preview_view.setPlainText(t('请选择模型'))
            return
        llama_dir = self.edit_dir.text().strip()
        s = self._gather_server_cfg()
        try:
            args = build_args(model, self.combo_mmproj.currentData(), s, llama_dir,
                              launcher_exe=self._launcher_exe())
            self.preview_view.setPlainText(build_command(args))
        except Exception as e:
            self.preview_view.setPlainText(t('生成命令失败: {0}').format(e))
    # ------------------------------------------------------------- 服务

    def start_server(self):
        model = self.combo_model.currentData()
        if not model:
            QMessageBox.information(self, t('提示'), t('请先选择模型'))
            return
        llama_dir = self.edit_dir.text().strip()
        launcher_exe = self._launcher_exe()
        if not os.path.isfile(launcher_exe):
            QMessageBox.warning(self, t('提示'),
                                t('未找到启动器可执行文件（llama-server.exe）。\n请检查模型目录，或在「启动器文件」中用文件选择器指定。'))
            return
        host = self.edit_host.text().strip() or "127.0.0.1"
        port = self.spin_port.value()
        if port_in_use(host, port):
            free = self._find_free_port(host, port) if self.check_port_hint.isChecked() else None
            if free:
                ret = QMessageBox.question(
                    self, t('端口占用'),
                    t('端口 {0} 已被占用，可能已有服务在运行。\n是否改用可用端口 {1}？\n\n选择「No」= 不更换端口，仍按原端口尝试启动。').format(port, free),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if ret == QMessageBox.StandardButton.Yes:
                    self.spin_port.setValue(free)
                    port = free
            else:
                ret = QMessageBox.question(
                    self, t('端口占用'), t('端口 {0} 已被占用，可能已有服务在运行。\n仍然尝试启动？').format(port),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if ret != QMessageBox.StandardButton.Yes:
                    return

        self.save_config()
        s = self._gather_server_cfg()
        try:
            use_ssl = self._resolve_ssl(s)
        except Exception as e:
            QMessageBox.critical(self, t('HTTPS 证书生成失败'), str(e))
            return
        mmproj_path = self.combo_mmproj.currentData()
        mm = self._mmproj_mismatch(model, mmproj_path)
        if mm:
            ret = QMessageBox.warning(
                self, t('视觉模型不匹配'),
                t('主模型与视觉模型的嵌入维度不一致：主模型 {0} vs 视觉模型 {1}。\nllama.cpp 会因此加载失败（error: mismatch between text model and mmproj）。\n\n建议：切换一个配套的视觉模型，或选择「（不使用）」以纯文本模式运行。\n\n仍要尝试启动吗？').format(mm[0], mm[1]),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return
        try:
            args = build_args(model, mmproj_path, s, llama_dir, launcher_exe=self._launcher_exe())
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('构建命令失败: {0}').format(e))
            return

        self._log_file(">>> " + build_command(args))
        ok = self.server.start(args, llama_dir, host, port,
                               scheme="https" if use_ssl else "http",
                               verify=not use_ssl)
        if ok:
            self._set_running_state(True)
            self.monitor.set_server(self.server.proc, self.server.url,
                                    os.path.basename(model), verify=not use_ssl)
            # 统计：一次启动计为一次「打开」（功能 9）
            self._running_model_name = os.path.basename(model)
            self._usage_pending = 0.0
            try:
                self._stats().record_open(self._running_model_name)
            except Exception:
                pass
            self.statusBar().showMessage(t('服务启动中…'), 0)

    def stop_server(self):
        self.server.stop()
        self.monitor.set_server(None)
        self._set_running_state(False)
        self._flush_usage()

    def _set_running_state(self, running):
        self.btn_start.setEnabled(not running)
        self.act_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.act_stop.setEnabled(running)
        self.btn_web.setEnabled(running)
        if hasattr(self, "badge_service"):
            self.badge_service.set_status(
                t('服务运行中') if running else t('服务未运行'),
                "ok" if running else "neutral")
        self._set_tray_menu_state()
        self._sync_pill_running()

    def _on_server_state(self, msg):
        self.statusBar().showMessage(msg, 0)
        self._log_file(msg)

    def _on_healthy(self, url):
        self._set_running_state(True)
        self._log_file(t('服务已就绪: {0}').format(url))
        self.monitor.fetch_model_now()
        if self.check_browser.isChecked():
            webbrowser.open(url)
        self.statusBar().showMessage(t('服务已就绪: {0}').format(url), 0)

    def _on_exited(self, code):
        self._set_running_state(False)
        self.monitor.set_server(None)
        self._flush_usage()
        if not self.server.manual_stop and code != 0:
            self.statusBar().showMessage(t('服务已退出（退出码 {0}）').format(code), 0)

    def open_web(self):
        scheme = "https" if self.check_ssl.isChecked() else "http"
        url = f"{scheme}://{self.edit_host.text().strip() or '127.0.0.1'}:{self.spin_port.value()}"
        webbrowser.open(url)

    def open_api(self):
        scheme = "https" if self.check_ssl.isChecked() else "http"
        url = f"{scheme}://{self.edit_host.text().strip() or '127.0.0.1'}:{self.spin_port.value()}/v1/models"
        webbrowser.open(url)

    def open_model_dir(self):
        d = self.edit_dir.text().strip()
        if os.path.isdir(d):
            os.startfile(d)  # noqa: S606
        else:
            QMessageBox.information(self, t('提示'), t('模型目录无效'))

    def open_bat_validator(self):
        """C3: 打开启动文件校验报告对话框（bat_validator.ValidateBatDialog）。"""
        try:
            ValidateBatDialog(self).exec()
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('打开校验器失败：{0}').format(e))
    # ------------------------------------------------- 局域网共享 / HTTPS

    def _ssl_paths(self):
        """返回自签名证书的 (私钥, 证书) 路径（数据目录 certs/，非英文路径自动回退）。"""
        return default_cert_paths(self.cfg.data_dir())

    def _on_lan_toggled(self, checked):
        """勾选「局域网共享」→ host 填 0.0.0.0；取消 → 回 127.0.0.1。"""
        if not self._loading:
            host = self.edit_host.text().strip().lower()
            if checked and host in ("", "127.0.0.1", "localhost", "::1"):
                self.edit_host.setText("0.0.0.0")
            elif not checked and host in ("0.0.0.0", "::"):
                self.edit_host.setText("127.0.0.1")
        self._update_local_ip_label()

    def _on_ssl_toggled(self, _checked):
        self._update_local_ip_label()

    def _on_host_edited(self, _text):
        """手动改监听地址时反向同步「局域网共享」勾选状态。"""
        if not self._loading:
            is_lan = self.edit_host.text().strip() in ("0.0.0.0", "::")
            if self.check_lan.isChecked() != is_lan:
                self.check_lan.blockSignals(True)
                self.check_lan.setChecked(is_lan)
                self.check_lan.blockSignals(False)
        self._update_local_ip_label()

    def _update_local_ip_label(self):
        if not hasattr(self, "label_local_ip"):
            return
        ip = local_ipv4()
        scheme = "https" if self.check_ssl.isChecked() else "http"
        port = self.spin_port.value()
        if self.check_lan.isChecked():
            self.label_local_ip.setText(t('局域网访问：{0}://{1}:{2}').format(scheme, ip, port))
        else:
            self.label_local_ip.setText(t('本机 IP：{0}').format(ip))

    def _resolve_ssl(self, s):
        """按配置确保 HTTPS 证书存在并写回 ssl_key_file/ssl_cert_file。

        成功返回 True（scheme 用 https）；未启用 HTTPS 返回 False；
        生成失败抛出 RuntimeError 由调用方提示。"""
        if not s.get("ssl_enabled"):
            s["ssl_key_file"] = ""
            s["ssl_cert_file"] = ""
            return False
        key_path, cert_path = self._ssl_paths()
        ensure_self_signed_cert(key_path, cert_path)
        s["ssl_key_file"] = key_path
        s["ssl_cert_file"] = cert_path
        return True
    # ---------------------------------------------------------- 残留检测

    def _find_free_port(self, host, start, limit=50):
        """从 start+1 起找一个可用端口；找不到返回 None。"""
        for p in range(int(start) + 1, int(start) + 1 + int(limit)):
            if p > 65535:
                break
            if not port_in_use(host, p):
                return p
        return None

    def _suggest_free_port(self, host, port):
        """端口被占用时建议一个可用端口，确认后更新主界面端口号。"""
        free = self._find_free_port(host, port)
        if not free:
            self.statusBar().showMessage(t('端口 {0} 被占用，且未找到可用端口').format(port), 6000)
            return
        ret = QMessageBox.question(
            self, t('端口被占用'),
            t('端口 {0} 已被占用，可能已有服务在运行。\n是否改用可用端口 {1}？').format(port, free),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            self.spin_port.setValue(free)
            self.save_config()
            self._log_file(t('[端口] {0} 被占用，已改用 {1}').format(port, free))
            self.statusBar().showMessage(t('已改用端口 {0}').format(free), 5000)

    def _check_residual(self):
        if self.server.running:
            return
        if not self.check_residual.isChecked():
            return
        # 排除本程序自己发起的探测进程（--version / --list-devices）：
        # 否则每次启动都会把版本检测进程误判为「上次残留」。
        exclude = set()
        worker = getattr(self, "_llama_ver_worker", None)
        pid = getattr(worker, "probe_pid", None)
        if pid:
            exclude.add(pid)
        gpu_pid = getattr(self, "_gpu_probe_pid", None)
        if gpu_pid:
            exclude.add(gpu_pid)
        procs = find_llama_server_processes(exclude_pids=exclude)
        host = self.edit_host.text().strip() or "127.0.0.1"
        port = self.spin_port.value()
        if procs:
            box = QMessageBox(self)
            box.setWindowTitle(t('检测到残留进程'))
            box.setIcon(QMessageBox.Icon.Question)
            box.setText(
                t('检测到 {0} 个可能残留的 llama-server 进程\n（上次未正常退出，可能仍在占用显存/内存）。\n是否强制结束它们？').format(len(procs)))
            box.setStandardButtons(
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            cb = QCheckBox(t('不再提示（可在「高级参数」中重新开启）'))
            box.setCheckBox(cb)
            ret = box.exec()
            if cb.isChecked():
                self.cfg.data["check_residual"] = False
                self._loading = True
                self.check_residual.setChecked(False)
                self._loading = False
                self.cfg.save()
            if ret == QMessageBox.StandardButton.Yes:
                kill_all_llama_server()
                self._log_file(t('已强制清理残留的 llama-server 进程'))
                self.statusBar().showMessage(t('已清理残留进程，显存已释放'), 4000)
        # 端口占用 → 建议更换端口（与残留进程分开处理）
        if self.check_port_hint.isChecked() and port_in_use(host, port):
            self._suggest_free_port(host, port)
