# -*- coding: utf-8 -*-
"""参数采集与配置读写、启动文件导入/导出、路径浏览与数据目录、llama 目录校验。"""

import json
import os

from PyQt6.QtWidgets import QFileDialog, QMessageBox
from ..cmd_builder import KV_CACHE_TYPES, SPLIT_MODES
from ..i18n import t


CREATE_NO_WINDOW = 0x08000000


class ConfigIOMixin:

    def _param_widgets(self):
        return [
            self.combo_ngl, self.spin_ctx, self.spin_np, self.spin_threads,
            self.spin_batch, self.spin_ub, self.spin_slots, self.combo_fa,
            self.combo_kvc_k, self.combo_kvc_v,
            self.check_cont, self.spin_temp, self.spin_topp, self.spin_topk,
            self.spin_rp, self.edit_apikey, self.check_mlock, self.check_mmap,
            self.check_browser, self.spin_timeout, self.edit_host, self.spin_port,
            self.check_lan, self.check_ssl, self.check_launcher_update,
            self.combo_split_mode, self.edit_tensor_split, self.spin_main_gpu,
            self.combo_moe, self.combo_moe_preset,
            self.spin_moe_layers, self.spin_moe_cache,
            self.combo_spec, self.combo_draft, self.spin_spec_n,
            self.check_jinja, self.combo_thinking, self.combo_reasoning,
            self.spin_reasoning_budget,
        ]

    def _on_moe_changed(self):
        """MoE 模式联动：只有「前 N 层」才需要 N；稠密模型整套置灰（v0.6.2）。

        `_moe_dense` 由 `ui/moe_flow.py` 后台扫描专家权重后写回（None = 还没判出来，
        先按可用处理，不因为探测慢就把控件锁死）。
        """
        if not hasattr(self, "combo_moe"):
            return
        dense = bool(getattr(self, "_moe_dense", False))
        mode = self.combo_moe.currentData() or "off"
        self.combo_moe.setEnabled(not dense)
        self.combo_moe_preset.setEnabled(not dense)
        self.spin_moe_layers.setEnabled((not dense) and mode == "n")
        self.spin_moe_cache.setEnabled((not dense) and mode != "off")

    def _gather_server_cfg(self):
        ssl_on = self.check_ssl.isChecked()
        ssl_key, ssl_cert = self._ssl_paths() if ssl_on else ("", "")
        spec_mode, spec_cli, spec_draft, spec_draft_n = self._spec_resolve()
        return {
            "host": self.edit_host.text().strip() or "127.0.0.1",
            "port": self.spin_port.value(),
            "lan_share": self.check_lan.isChecked(),
            "ssl_enabled": ssl_on,
            "ssl_key_file": ssl_key,
            "ssl_cert_file": ssl_cert,
            "ngl": self.combo_ngl.currentText().strip() or "all",
            "ctx": self.spin_ctx.value(),
            "n_predict": self.spin_np.value(),
            "threads": self.spin_threads.value(),
            "batch": self.spin_batch.value(),
            "ubatch": self.spin_ub.value(),
            "flash_attn": self.combo_fa.currentText(),
            "cont_batching": self.check_cont.isChecked(),
            # KV 缓存 K / V 独立类型（功能 2）
            "kv_cache_k": self.combo_kvc_k.currentText(),
            "kv_cache_v": self.combo_kvc_v.currentText(),
            # MoE 专家卸载
            "moe_mode": self.combo_moe.currentData() or "off",
            "moe_layers": self.spin_moe_layers.value(),
            "moe_cache_mib": self.spin_moe_cache.value(),
            "moe_preset": str(self.combo_moe_preset.currentData() or ""),
            # 多显卡（功能 3）
            "devices": [c.property("dev_name") for c in getattr(self, "gpu_checks", [])
                        if c.isChecked() and c.property("dev_name")],
            "split_mode": self.combo_split_mode.currentText(),
            "tensor_split": self.edit_tensor_split.text().strip(),
            "main_gpu": self.spin_main_gpu.value(),
            # 投机解码（v0.5.15）：spec_mode 是用户选的方式（off/auto/具体方式），
            # spec_cli 是解析后真正下发给 --spec-type 的值，空 = 不下发
            "spec_mode": spec_mode,
            "spec_cli": spec_cli,
            "spec_draft": spec_draft,
            "spec_draft_n": spec_draft_n,
            # 对话模板（功能 8）
            "jinja": self.check_jinja.isChecked(),
            "reasoning_mode": (self.combo_thinking.currentData() or "auto")
                              if (getattr(self, "_chat_caps", {}) or {}).get("thinking")
                              or (getattr(self, "_chat_caps", {}) or {}).get("effort")
                              else "",
            "reasoning_effort": (self.combo_reasoning.currentData() or "")
                                if (self.combo_reasoning.isEnabled()
                                    and (getattr(self, "_chat_caps", {}) or {}).get("effort"))
                                else "",
            "reasoning_budget": self.spin_reasoning_budget.value(),
            "slots": self.spin_slots.value(),
            "temp": self.spin_temp.value(),
            "top_p": self.spin_topp.value(),
            "top_k": self.spin_topk.value(),
            "repeat_penalty": self.spin_rp.value(),
            "api_key": self.edit_apikey.text(),
            "mlock": self.check_mlock.isChecked(),
            "no_mmap": self.check_mmap.isChecked(),
            "timeout": self.spin_timeout.value(),
            "auto_open_browser": self.check_browser.isChecked(),
        }

    def _apply_config(self):
        self._loading = True
        d = self.cfg.data
        self.edit_dir.setText(d.get("llama_dir", ""))
        self.edit_launcher.setText(d.get("launcher_exe", ""))
        self.edit_data_dir.setText(d.get("data_dir", ""))
        s = d.get("server", {})
        self.edit_host.setText(s.get("host", "127.0.0.1"))
        self.spin_port.setValue(int(s.get("port", 8080)))
        self.check_lan.setChecked(bool(
            s.get("lan_share", str(s.get("host", "")).strip() == "0.0.0.0")))
        self.check_ssl.setChecked(bool(s.get("ssl_enabled", False)))
        ngl = str(s.get("ngl", "all"))
        idx = self.combo_ngl.findText(ngl)
        if idx >= 0:
            self.combo_ngl.setCurrentIndex(idx)
        else:
            self.combo_ngl.setEditText(ngl)
        self.spin_ctx.setValue(int(s.get("ctx", 32768)))
        self.spin_np.setValue(int(s.get("n_predict", 8192)))
        self.spin_threads.setValue(int(s.get("threads", -1)))
        self.spin_batch.setValue(int(s.get("batch", 2048)))
        self.spin_ub.setValue(int(s.get("ubatch", 512) or 512))
        self.spin_slots.setValue(int(s.get("slots", -1)))
        self.combo_fa.setCurrentText(s.get("flash_attn", "on"))
        # KV K/V 独立类型（兼容旧配置 kv_cache_type）
        legacy_kvc = s.get("kv_cache_type") or ""
        k = str(s.get("kv_cache_k") or legacy_kvc or "f16")
        v = str(s.get("kv_cache_v") or legacy_kvc or "f16")
        self.combo_kvc_k.setCurrentText(k if k in KV_CACHE_TYPES else "f16")
        self.combo_kvc_v.setCurrentText(v if v in KV_CACHE_TYPES else "f16")
        self.check_cont.setChecked(bool(s.get("cont_batching", True)))
        self.spin_temp.setValue(float(s.get("temp", 0.8)))
        self.spin_topp.setValue(float(s.get("top_p", 0.95)))
        self.spin_topk.setValue(int(s.get("top_k", 40)))
        self.spin_rp.setValue(float(s.get("repeat_penalty", 1.0)))
        self.edit_apikey.setText(s.get("api_key", ""))
        self.check_mlock.setChecked(bool(s.get("mlock", False)))
        self.check_mmap.setChecked(bool(s.get("no_mmap", False)))
        self.check_browser.setChecked(bool(s.get("auto_open_browser", True)))
        self.spin_timeout.setValue(int(s.get("timeout", 3600)))

        # 多显卡 / MTP（功能 3/4）
        sm = str(s.get("split_mode") or "layer")
        if sm in SPLIT_MODES:
            self.combo_split_mode.setCurrentText(sm)
        self.edit_tensor_split.setText(str(s.get("tensor_split") or ""))
        try:
            self.spin_main_gpu.setValue(int(s.get("main_gpu", 0)))
        except (TypeError, ValueError):
            pass
        # MoE 专家卸载
        mi = self.combo_moe.findData(str(s.get("moe_mode") or "off"))
        self.combo_moe.setCurrentIndex(mi if mi >= 0 else 0)
        try:
            self.spin_moe_layers.setValue(int(s.get("moe_layers", 0) or 0))
            self.spin_moe_cache.setValue(int(s.get("moe_cache_mib", 0) or 0))
        except (TypeError, ValueError):
            pass
        pi = self.combo_moe_preset.findData(str(s.get("moe_preset") or ""))
        self.combo_moe_preset.setCurrentIndex(pi if pi >= 0 else 0)
        self._on_moe_changed()
        # 投机解码：老配置的「启用 MTP」已由 config._migrate 迁成 spec_mode，
        # 这里只负责把下拉/数字框回显成配置里的样子
        mode = self._spec_mode()
        idx = self.combo_spec.findData(mode)
        self.combo_spec.setCurrentIndex(idx if idx >= 0 else 1)
        try:
            self.spin_spec_n.setValue(int(s.get("spec_draft_n", 0) or 0))
        except (TypeError, ValueError):
            self.spin_spec_n.setValue(0)
        self._update_spec_ui()
        want_draft = str(s.get("spec_draft") or "")
        if want_draft:
            di = self.combo_draft.findData(want_draft)
            self.combo_draft.setCurrentIndex(di if di >= 0 else 0)

        # 对话模板（功能 8）
        self.check_jinja.setChecked(bool(s.get("jinja", False)))
        _rmode = str(s.get("reasoning_mode") or "auto")
        _ri = self.combo_thinking.findData(_rmode)
        self.combo_thinking.setCurrentIndex(_ri if _ri >= 0 else 0)
        _effort = str(s.get("reasoning_effort") or "")
        _idx = self.combo_reasoning.findData(_effort)
        self.combo_reasoning.setCurrentIndex(_idx if _idx >= 0 else 0)
        try:
            self.spin_reasoning_budget.setValue(int(s.get("reasoning_budget", -1)))
        except (TypeError, ValueError):
            self.spin_reasoning_budget.setValue(-1)

        # 启动时行为：残留进程检测 / 端口占用建议
        self.check_residual.setChecked(bool(d.get("check_residual", True)))
        self.check_port_hint.setChecked(bool(d.get("port_hint", True)))
        self.check_hover_pill.setChecked(bool(d.get("hover_pill", True)))
        self.check_launcher_update.setChecked(bool(d.get("check_launcher_update", True)))
        self.check_hf_query.setChecked(bool(d.get("hf_query_enabled", False)))

        # 模型排序（功能 1）
        sort_mode = d.get("model_sort", "dir_name")
        idx = {"dir_name": 0, "size_desc": 1, "name": 2}.get(sort_mode, 0)
        self.combo_sort.setCurrentIndex(idx)

        # HF 下载目录回显（功能 5）：有自定义则回显，否则默认跟随主页「模型目录」
        if d.get("hf_download_dir"):
            self.download_tab.edit_save_dir.setText(d["hf_download_dir"])
            self.download_tab._auto_save_dir = False
        else:
            self.download_tab.sync_default_dir()
        self._loading = False
        self._sync_preset_combo()
        self._update_local_ip_label()

    def save_config(self):
        d = self.cfg.data
        d["llama_dir"] = self.edit_dir.text().strip()
        d["launcher_exe"] = self.edit_launcher.text().strip()
        new_data_dir = self.edit_data_dir.text().strip()
        if new_data_dir != (d.get("data_dir", "") or ""):
            self.cfg.redirect_data_dir(new_data_dir)
            d = self.cfg.data
            self.monitor.log_dir = os.path.join(self.cfg.data_dir(), "logs")
        d["server"] = self._gather_server_cfg()
        d["model"] = self.combo_model.currentData() or ""
        d["mmproj"] = self.combo_mmproj.currentData() or ""
        d["check_residual"] = self.check_residual.isChecked()
        d["port_hint"] = self.check_port_hint.isChecked()
        d["hover_pill"] = self.check_hover_pill.isChecked()
        d["hf_query_enabled"] = self.check_hf_query.isChecked()
        d["window_geometry"] = list(self.geometry().getRect())
        ok = self.cfg.save()
        self.statusBar().showMessage(t('配置已保存') if ok else t('配置保存失败'), 3000)

    def _save_startup_prefs(self, _checked=None):
        """残留检测 / 端口建议 两个开关立即落盘（无需点「保存配置」）。"""
        if self._loading:
            return
        self.cfg.data["check_residual"] = self.check_residual.isChecked()
        self.cfg.data["port_hint"] = self.check_port_hint.isChecked()
        self.cfg.data["check_launcher_update"] = self.check_launcher_update.isChecked()
        self.cfg.save()

    def export_config(self):
        """导出完整配置为 .aic 文件（内容即 JSON，仅扩展名不同）。"""
        default = os.path.join(self.base_dir, t('LLama启动器配置.aic'))
        path, _ = QFileDialog.getSaveFileName(self, t('导出配置'), default, t('LLama 启动器配置 (*.aic);;JSON (*.json)'))
        if not path:
            return
        self.save_config()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.cfg.data, f, ensure_ascii=False, indent=2)
            self.statusBar().showMessage(t('配置已导出: {0}').format(path), 5000)
            self._on_server_log(t('[配置] 已导出到 {0}').format(path))
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('导出失败: {0}').format(e))

    def import_config(self):
        """从 .aic / .json 文件导入完整配置并应用到界面。"""
        path, _ = QFileDialog.getOpenFileName(self, t('导入配置'), self.base_dir,
                                              t('LLama 启动器配置 (*.aic *.json);;所有文件 (*.*)'))
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError(t('文件内容不是有效的配置'))
            self.cfg.apply_loaded(loaded)   # 含旧键迁移（kv_cache_type → k/v）
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('导入失败: {0}').format(e))
            return
        self._apply_config()
        self._apply_theme()
        self.refresh_models(keep_selection=True)
        self.statusBar().showMessage(t('配置已导入: {0}').format(path), 5000)
        self._on_server_log(t('[配置] 已从 {0} 导入').format(path))
    # ---------------------------------------------------------- 其他

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, t('选择模型扫描目录'), self.edit_dir.text() or os.path.expanduser("~"))
        if d:
            self.edit_dir.setText(d)
            self.cfg.data["llama_dir"] = d
            self.cfg.save()
            self.refresh_models()

    def _launcher_exe(self):
        """返回启动服务用的可执行文件；自定义项无效/空时回退 模型目录\\llama-server.exe。"""
        exe = self.edit_launcher.text().strip()
        if exe and os.path.isfile(exe):
            return exe
        return os.path.join(self.edit_dir.text().strip() or self.base_dir, "llama-server.exe")

    def _browse_launcher(self):
        start = os.path.join(self.edit_dir.text().strip() or self.base_dir, "llama-server.exe")
        path, _ = QFileDialog.getOpenFileName(self, t('选择启动器可执行文件'), start,
                                              t('可执行文件 (*.exe);;所有文件 (*.*)'))
        if path:
            self.edit_launcher.setText(path)
            self.cfg.data["launcher_exe"] = path
            self.cfg.save()
            self.update_preview()
            self.scan_tools()
            self.statusBar().showMessage(t('启动器文件: {0}').format(path), 4000)

    def _clear_launcher(self):
        self.edit_launcher.setText("")
        self.cfg.data["launcher_exe"] = ""
        self.cfg.save()
        self.update_preview()
        self.scan_tools()
        self.statusBar().showMessage(t('已恢复自动查找 llama-server.exe'), 3000)

    def _data_dir(self):
        """返回数据存储目录（config.json/日志/缓存），空则程序目录。"""
        return self.cfg.ensure_data_dir()

    def _browse_data_dir(self):
        d = QFileDialog.getExistingDirectory(self, t('选择数据存储目录'), self._data_dir())
        if not d:
            return
        self.edit_data_dir.setText(d)
        if self.cfg.redirect_data_dir(d):
            self.statusBar().showMessage(t('数据目录已切换到: {0}').format(d), 5000)
            self._log_file(t('[配置] 数据目录切换到 {0}').format(d))
        else:
            self.statusBar().showMessage(t('数据目录切换失败'), 4000)

    def _reset_data_dir(self):
        self.edit_data_dir.setText("")
        if self.cfg.redirect_data_dir(""):
            self.statusBar().showMessage(t('数据目录已恢复为程序所在目录'), 4000)
            self._log_file(t('[配置] 数据目录恢复为程序目录'))

    def _ensure_valid_llama_dir(self):
        """启动时校验模型目录；无效则弹窗让用户选择（浏览选择 / 使用默认上级目录）。"""
        llama_dir = self.edit_dir.text().strip()
        if llama_dir and os.path.isdir(llama_dir):
            return
        ret = QMessageBox.question(
            self, t('模型目录无效'),
            t('当前模型目录不存在或不可访问：\n{0}\n\n是否立即重新选择模型目录？\n（选「否」将使用启动器所在目录的上级目录）').format(llama_dir or t('（空）')),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret == QMessageBox.StandardButton.Yes:
            self._browse_dir()
        else:
            parent = os.path.dirname(os.path.abspath(self.base_dir))
            if os.path.isdir(parent):
                self.edit_dir.setText(parent)
                self.cfg.data["llama_dir"] = parent
                self.cfg.save()
                self.statusBar().showMessage(t('模型目录已设为: {0}').format(parent), 4000)
