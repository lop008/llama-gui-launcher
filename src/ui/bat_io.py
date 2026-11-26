# -*- coding: utf-8 -*-
"""启动脚本导入/导出：解析已有 .bat 回填参数、导出一键启动与命令预览、建桌面快捷方式。"""

import json
import os
import sys

from PyQt6.QtWidgets import QFileDialog, QMessageBox
from ..bat_validator import parse_script
from ..cmd_builder import KV_CACHE_TYPES, SPLIT_MODES, build_bat_content, build_preview_bat, model_alias
from ..i18n import t


CREATE_NO_WINDOW = 0x08000000


class BatIOMixin:
    # ---------------------------------------------------------- 启动文件导入

    @staticmethod
    def _select_combo_by_path(combo, target):
        """按绝对路径或文件名在 combo 中选中匹配项；成功返回 True。"""
        if not target:
            return False
        tgt = os.path.normcase(os.path.abspath(str(target)))
        tbase = os.path.normcase(os.path.basename(str(target)))
        for i in range(combo.count()):
            data = combo.itemData(i)
            if not data:
                continue
            d = os.path.normcase(os.path.abspath(str(data)))
            if d == tgt or os.path.basename(d) == tbase:
                combo.setCurrentIndex(i)
                return True
        return False

    def import_bat(self):
        """解析已有的启动文件（.bat/.cmd/.ps1/.sh/文本），把参数应用到当前界面。"""
        start_dir = self.edit_dir.text().strip() or self.base_dir
        path, _ = QFileDialog.getOpenFileName(
            self, t('导入启动文件'), start_dir,
            t('启动文件 (*.bat *.cmd *.ps1 *.sh *.txt);;所有文件 (*.*)'))
        if not path:
            return
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('读取失败: {0}').format(e))
            return
        text = None
        for enc in ("utf-8-sig", "gbk"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            QMessageBox.critical(self, t('错误'), t('无法识别文件编码（UTF-8 / GBK 均失败）'))
            return
        try:
            params = parse_script(text, path)
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('解析失败: {0}').format(e))
            return
        if not params:
            QMessageBox.information(self, t('提示'), t('未在文件中识别到任何 llama-server 参数'))
            return
        applied, warns = self._apply_imported_params(params)
        self.update_preview()
        base = os.path.basename(path)
        if applied == 0:
            QMessageBox.warning(self, t('导入完成（未应用任何参数）'),
                                t('已解析 {0}，但没有可应用的参数。\n\n').format(base) + "\n".join(warns))
            return
        msg = t('已从 {0} 导入 {1} 项参数').format(base, applied)
        self._on_server_log(t('[导入] {0}').format(msg))
        if warns:
            QMessageBox.warning(self, t('导入完成（部分项未应用）'),
                                msg + t('\n\n注意：\n') + "\n".join(warns))
        else:
            self.statusBar().showMessage(msg, 5000)

    def _apply_imported_params(self, params):
        """把 parse_script 的结果应用到界面控件。返回 (应用项数, 警告列表)。"""
        kv = {}
        for _frag, name, value in params:
            if name:
                kv[name] = value
        applied = 0
        warns = []

        def _int(value, label, lo=None, hi=None):
            nonlocal applied
            try:
                v = int(float(str(value).strip()))
            except (TypeError, ValueError):
                warns.append(t('{0}：无法解析“{1}”').format(label, value))
                return None
            if lo is not None and v < lo:
                v = lo
            if hi is not None and v > hi:
                v = hi
            applied += 1
            return v

        def _float(value, label, lo=None, hi=None):
            nonlocal applied
            try:
                v = float(str(value).strip())
            except (TypeError, ValueError):
                warns.append(t('{0}：无法解析“{1}”').format(label, value))
                return None
            if lo is not None and v < lo:
                v = lo
            if hi is not None and v > hi:
                v = hi
            applied += 1
            return v

        # 模型优先（会触发视觉模型列表重建）
        if "model" in kv:
            if self._select_combo_by_path(self.combo_model, kv["model"]):
                applied += 1
            else:
                warns.append(t('主模型：列表中未找到“{0}”').format(os.path.basename(str(kv['model']))))
        if "mmproj" in kv:
            if self._select_combo_by_path(self.combo_mmproj, kv["mmproj"]):
                applied += 1
            else:
                warns.append(t('视觉模型：未找到“{0}”').format(os.path.basename(str(kv['mmproj']))))

        self._loading = True
        try:
            if "ctx" in kv:
                v = _int(kv["ctx"], t('上下文长度'), 256, 1048576)
                if v is not None:
                    self.spin_ctx.setValue(v)
            if "predict" in kv:
                v = _int(kv["predict"], t('预测Token'), -1, 1000000)
                if v is not None:
                    self.spin_np.setValue(v)
            if "batch" in kv:
                v = _int(kv["batch"], t('批大小'), 1, 16384)
                if v is not None:
                    self.spin_batch.setValue(v)
            if "threads" in kv:
                v = _int(kv["threads"], t('CPU线程'), -1, 256)
                if v is not None:
                    self.spin_threads.setValue(v)
            if "slots" in kv:
                v = _int(kv["slots"], t('并行slots'), -1, 64)
                if v is not None:
                    self.spin_slots.setValue(v)
            if "ngl" in kv:
                self.combo_ngl.setEditText(str(kv["ngl"]))
                applied += 1
            if "flash_attn" in kv and kv["flash_attn"] in ("on", "off", "auto"):
                self.combo_fa.setCurrentText(kv["flash_attn"])
                applied += 1
            if "kv_k" in kv and kv["kv_k"] in KV_CACHE_TYPES:
                self.combo_kvc_k.setCurrentText(kv["kv_k"])
                applied += 1
            if "kv_v" in kv and kv["kv_v"] in KV_CACHE_TYPES:
                self.combo_kvc_v.setCurrentText(kv["kv_v"])
                applied += 1
            if "temp" in kv:
                v = _float(kv["temp"], t('温度'), 0.0, 2.0)
                if v is not None:
                    self.spin_temp.setValue(v)
            if "top_p" in kv:
                v = _float(kv["top_p"], "Top-P", 0.0, 1.0)
                if v is not None:
                    self.spin_topp.setValue(v)
            if "top_k" in kv:
                v = _int(kv["top_k"], "Top-K", 0, 200)
                if v is not None:
                    self.spin_topk.setValue(v)
            if "repeat_penalty" in kv:
                v = _float(kv["repeat_penalty"], t('重复惩罚'), 0.0, 2.0)
                if v is not None:
                    self.spin_rp.setValue(v)
            if "timeout" in kv:
                v = _int(kv["timeout"], t('超时(秒)'), 30, 86400)
                if v is not None:
                    self.spin_timeout.setValue(v)
            if "host" in kv:
                self.edit_host.setText(str(kv["host"]))
                applied += 1
            if "port" in kv:
                v = _int(kv["port"], t('端口'), 1, 65535)
                if v is not None:
                    self.spin_port.setValue(v)
            if "split_mode" in kv and kv["split_mode"] in SPLIT_MODES:
                self.combo_split_mode.setCurrentText(kv["split_mode"])
                applied += 1
            if "main_gpu" in kv:
                v = _int(kv["main_gpu"], t('主GPU'), 0, 63)
                if v is not None:
                    self.spin_main_gpu.setValue(v)
            if "tensor_split" in kv:
                self.edit_tensor_split.setText(str(kv["tensor_split"]))
                applied += 1
            if "cont_batching" in kv:
                self.check_cont.setChecked(True)
                applied += 1
            if "mlock" in kv:
                self.check_mlock.setChecked(True)
                applied += 1
            if "no_mmap" in kv:
                self.check_mmap.setChecked(True)
                applied += 1
            if "spec_type" in kv and "mtp" in str(kv["spec_type"]).lower():
                self.check_mtp.setChecked(True)
                applied += 1
            if "jinja" in kv:
                self.check_jinja.setChecked(True)
                applied += 1
            if "chat_template_kwargs" in kv:
                raw = str(kv["chat_template_kwargs"]).strip()
                if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
                    raw = raw[1:-1]
                raw = raw.replace('\\"', '"').replace("\\'", "'")
                try:
                    obj = json.loads(raw)
                    effort = str(obj.get("reasoning_effort") or "").strip()
                    idx = self.combo_reasoning.findData(effort)
                    if effort and idx >= 0:
                        self.combo_reasoning.setCurrentIndex(idx)
                        self.check_jinja.setChecked(True)
                        applied += 1
                except Exception:
                    warns.append(t('模板参数：JSON 解析失败，已跳过'))
            if "reasoning_budget" in kv:
                v = _int(kv["reasoning_budget"], t('推理预算'), -1, 1000000)
                if v is not None:
                    self.spin_reasoning_budget.setValue(v)
            if "api_key" in kv:
                warns.append(t('API Key：出于安全考虑不导入（文件中为打码值）'))
            if "ssl_key_file" in kv or "ssl_cert_file" in kv:
                self.check_ssl.setChecked(True)
                applied += 1
        finally:
            self._loading = False
        return applied, warns
    # ---------------------------------------------------------- 一键启动导出

    def export_bat(self):
        """将当前配置导出为可双击启动的 .bat，并在桌面创建带软件图标的快捷方式。"""
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
        self.save_config()
        s = self._gather_server_cfg()
        mmproj = self.combo_mmproj.currentData()
        try:
            content = build_bat_content(model, mmproj, s, llama_dir, launcher_exe=launcher_exe)
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('生成批处理失败: {0}').format(e))
            return
        default = os.path.join(self.base_dir, t('{0}-一键启动.bat').format(model_alias(model)))
        path, _ = QFileDialog.getSaveFileName(self, t('导出一键启动批处理'), default, t('批处理文件 (*.bat)'))
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write(content)
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('导出失败: {0}').format(e))
            return
        self.statusBar().showMessage(t('已导出: {0}').format(path), 5000)
        self._on_server_log(t('[导出] 已生成一键启动脚本 {0}').format(path))
        self._create_desktop_shortcut(path)

    def export_preview_bat(self):
        """把「命令预览」页的完整命令行原样导出为 .bat，自选存储路径（功能 6）。"""
        preview = (self.preview_view.toPlainText() or "").strip()
        if not preview:
            QMessageBox.information(self, t('提示'), t('命令预览为空：请先选择模型并配置参数'))
            return
        alias = model_alias(self.combo_model.currentData() or "") or "llama-server"
        default = os.path.join(
            self._data_dir(), t("{0}-命令预览.bat").format(alias).replace("\\", "_"))
        path, _ = QFileDialog.getSaveFileName(
            self, t('导出命令预览为 .bat（可选择存储路径）'), default,
            t('批处理文件 (*.bat);;所有文件 (*.*)'))
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write(build_preview_bat(preview, title=f"LLama Server - {alias}"))
        except Exception as e:
            QMessageBox.critical(self, t('错误'), t('导出失败: {0}').format(e))
            return
        self.statusBar().showMessage(t('命令预览已导出: {0}').format(path), 5000)
        self._on_server_log(t('[导出] 命令预览已保存为 {0}').format(path))

    def _create_desktop_shortcut(self, bat_path):
        """用 WScript.Shell 在桌面创建指向 bat 的快捷方式，图标取程序图标。"""
        desktop = self._desktop_dir()
        if not desktop:
            QMessageBox.information(self, t('提示'), t('导出成功，但无法定位桌面目录，跳过快捷方式'))
            return
        import subprocess
        import base64
        name = os.path.splitext(os.path.basename(bat_path))[0]
        lnk_path = os.path.join(desktop, name + ".lnk")
        # 直接用程序自带图标作为快捷方式图标，不再往导出目录里写额外的 .ico 文件
        icon_path = self._shortcut_icon()

        def _q(v):
            return str(v).replace("'", "''")

        script = [
            "$ws = New-Object -ComObject WScript.Shell",
            f"$s = $ws.CreateShortcut('{_q(lnk_path)}')",
            f"$s.TargetPath = '{_q(bat_path)}'",
            f"$s.WorkingDirectory = '{_q(os.path.dirname(bat_path))}'",
            f"$s.IconLocation = '{_q(icon_path)},0'" if icon_path else "",
            t("$s.Description = 'LLama 启动器一键启动'"),
            "$s.Save()",
        ]
        script = [line for line in script if line]
        try:
            encoded = base64.b64encode("\n".join(script).encode("utf-16-le")).decode()
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
                check=True, capture_output=True, timeout=60)
        except Exception as e:
            QMessageBox.warning(self, t('提示'), t('创建桌面快捷方式失败: {0}').format(e))
            return
        QMessageBox.information(
            self, t('完成'),
            t('已导出：{0}\n\n已在桌面创建快捷方式：\n{1}').format(bat_path, lnk_path))
        self.statusBar().showMessage(t('桌面快捷方式已创建: {0}').format(lnk_path), 6000)

    def _shortcut_icon(self):
        """快捷方式图标路径：优先使用启动器 exe 内嵌图标（不产生额外文件，且长期有效）。

        打包运行时直接用 sys.executable；源码运行时用 assets/icon.ico；
        都没有时才在系统临时目录生成 ico 回退，绝不写入用户的导出目录。
        """
        if getattr(sys, "frozen", False):
            exe = sys.executable
            if exe and os.path.isfile(exe):
                return exe
        src = os.path.join(self.resource_dir, "assets", "icon.ico")
        if os.path.isfile(src):
            return src
        try:
            import tempfile
            dst = os.path.join(tempfile.gettempdir(), "llama_launcher_icon.ico")
            if not os.path.isfile(dst):
                pm = self.windowIcon().pixmap(64, 64)
                if pm.isNull():
                    return ""
                pm.save(dst, "ICO")
            return dst if os.path.isfile(dst) else ""
        except Exception:
            return ""

    def _desktop_dir(self):
        """返回真实桌面目录（兼容 OneDrive/系统盘），找不到返回 None。"""
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if os.path.isdir(desktop):
            return desktop
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 16, None, 0, buf) == 0:
                d = buf.value
                if os.path.isdir(d):
                    return d
        except Exception:
            pass
        return None
