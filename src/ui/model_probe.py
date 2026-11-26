# -*- coding: utf-8 -*-
"""模型目录列表与能力检测：MTP / 对话模板 / 视觉投影配对 / 模型信息与 HF 查询。"""

import os
import threading

from collections import Counter
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMessageBox
from .. import hf_info
from ..gguf_reader import classify_gguf, detect_chat_features, detect_mtp, format_gguf_info, read_gguf_info
from ..i18n import t
from ..model_scanner import (
    ROLE_DRAFT, ROLE_IMATRIX, ROLE_MMPROJ, ROLE_MODEL, find_mmproj_for, human_size, role_label,
    scan_models, sort_models,
)


CREATE_NO_WINDOW = 0x08000000


class ModelProbeMixin:
    # ---------------------------------------------------------- 模型相关

    def _on_sort_changed(self, _idx):
        """切换排序方式（功能 1）：保存设置并对当前列表重新排序。"""
        if self._loading or not hasattr(self, "combo_model"):
            return
        mode = ("dir_name", "size_desc", "name")[self.combo_sort.currentIndex()]
        self.cfg.data["model_sort"] = mode
        keep = self.combo_model.currentData()
        self._rebuild_model_combos(keep)

    def refresh_models(self, keep_selection=False):
        llama_dir = self.edit_dir.text().strip()
        if not llama_dir or not os.path.isdir(llama_dir):
            self._models, self._aux = [], []
            self._scan_error = t('模型目录无效')
            self._rebuild_model_combos(None)
            return

        self._scan_gen = getattr(self, "_scan_gen", 0) + 1
        gen = self._scan_gen
        self._pending_keep = keep_selection
        self._scan_error = None

        def work():
            ms, aux = [], []
            err = None
            try:
                ms, aux = scan_models(llama_dir)
            except Exception as e:
                err = str(e)
            if gen != getattr(self, "_scan_gen", 0):
                return  # 过期扫描，丢弃
            if err is not None:
                self._scan_error = err
            else:
                self._models, self._aux = ms, aux
            self.model_scan_done.emit()

        threading.Thread(target=work, daemon=True).start()
        self.statusBar().showMessage(t('正在扫描模型目录…'), 2000)

    def _aux_summary(self):
        """辅助文件计数摘要（视觉投影 / 投机草稿头 / 标定文件），用于状态栏与按钮提示。"""
        mm = sum(1 for a in self._aux if a.role == ROLE_MMPROJ)
        dr = sum(1 for a in self._aux if a.role == ROLE_DRAFT)
        im = sum(1 for a in self._aux if a.role == ROLE_IMATRIX)
        return mm, dr, im

    def _on_model_scan_done(self):
        keep_path = self.cfg.data.get("model", "") if self._pending_keep else None
        self._pending_keep = False
        err = getattr(self, "_scan_error", None)
        self._scan_error = None
        self._rebuild_model_combos(keep_path)
        if err:
            self.statusBar().showMessage(t('扫描出错: {0}').format(err), 5000)
            self._log_file(t('[扫描] 出错: {0}').format(err))
        else:
            hint = getattr(self, "_scan_hint", "")
            self._scan_hint = ""
            if hint:      # 主模型指向辅助文件之类的提醒优先显示，不被计数文案盖掉
                self._status_tip(hint, 10000, hold=True)
            else:
                mm, dr, im = self._aux_summary()
                if dr or im:
                    self._status_tip(
                        t('发现 {0} 个模型, {1} 个视觉模型, {2} 个草稿头, {3} 个标定文件').format(
                            len(self._models), mm, dr, im), 4000)
                else:
                    self._status_tip(
                        t('发现 {0} 个模型, {1} 个视觉模型').format(len(self._models), mm), 4000)
        self.update_preview()

    def _rebuild_model_combos(self, keep_path):
        self._loading = True
        # 排序（功能 1）：目录+文件名 / 大小降序 / 名称
        sort_models(self._models, self.cfg.data.get("model_sort", "dir_name"))
        self.combo_model.blockSignals(True)
        self.combo_model.clear()
        for m in self._models:
            # 多文件分片模型（功能 8）：只显示第一个启动文件，大小显示整组总和
            size = getattr(m, "group_size", None) or m.size
            label = f"{m.name}  ({human_size(size)})"
            if getattr(m, "shard_idx", None):
                label += t('\u3000[多文件 {0} 片]').format(m.shard_total)
            self.combo_model.addItem(label, m.path)
        self.combo_model.blockSignals(False)
        # 规范化路径匹配（兼容配置里 / 与 \ 混用），并保留下载页加入的外部模型
        norm = {os.path.normcase(os.path.abspath(m.path)): i
                for i, m in enumerate(self._models)}
        target = None
        if keep_path:
            target = norm.get(os.path.normcase(os.path.abspath(keep_path)))
        if target is None and keep_path and os.path.isfile(keep_path):
            role, kind, _why = classify_gguf(keep_path)
            if role != ROLE_MODEL:
                # 老配置可能把视觉投影 / MTP 头存成了主模型：不再放回下拉框，提示重选。
                # 提示先存着，由 _on_model_scan_done 决定何时显示（否则会被计数文案盖掉）
                self._scan_hint = t('{0} 是{1}，已自动从主模型列表隐藏，请重新选择主模型').format(
                    os.path.basename(keep_path), role_label(role, kind))
                self._log_file(t('[扫描] 主模型指向辅助文件: {0}').format(keep_path))
                self._loading = False
                self._on_model_changed()
                return
        if target is not None:
            self.combo_model.setCurrentIndex(target)
        elif keep_path and os.path.isfile(keep_path):
            try:
                size = os.path.getsize(keep_path)
            except OSError:
                size = 0
            self.combo_model.addItem(
                t('{0}  ({1})\u3000[已下载]').format(os.path.basename(keep_path), human_size(size)),
                keep_path)
            self.combo_model.setCurrentIndex(self.combo_model.count() - 1)
        elif self._models:
            self.combo_model.setCurrentIndex(0)
        self._loading = False
        self._on_model_changed()

    def select_model_path(self, path):
        """供下载页调用：把已下载的模型设为主模型（不在扫描列表时临时加入下拉框）。"""
        if not path:
            return
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            QMessageBox.information(self, t('提示'), t('模型文件不存在：\n{0}').format(path))
            return
        for i in range(self.combo_model.count()):
            data = self.combo_model.itemData(i)
            if data and os.path.abspath(data) == path:
                self.combo_model.setCurrentIndex(i)
                self.statusBar().showMessage(t('已切换主模型：{0}').format(os.path.basename(path)), 5000)
                return
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        label = t('{0}  ({1})\u3000[已下载]').format(os.path.basename(path), human_size(size))
        self._loading = True
        self.combo_model.addItem(label, path)
        self._loading = False
        self.combo_model.setCurrentIndex(self.combo_model.count() - 1)
        self.statusBar().showMessage(t('已切换主模型：{0}').format(os.path.basename(path)), 5000)

    def _on_model_changed(self):
        path = self.combo_model.currentData()
        # A6: 显示当前选中模型的完整绝对路径（未选时显示「未选择模型」）
        if hasattr(self, "label_model_path"):
            self.label_model_path.setText(os.path.abspath(path) if path else t('未选择模型'))
        if not path:
            self._clear_info()
            self._update_mmproj_warn()
            return
        if not self._loading:
            self.cfg.data["model"] = path
        model = next((m for m in self._models if m.path == path), None)
        # 功能 7：只显示与主模型同一目录下的视觉模型，保证配套一致
        # （扫描已按 GGUF 内容分流，这里再按 role 兜一层，避免不叫 mmproj 的投影文件混入）
        same_dir = [m for m in self._aux
                    if model is not None and m.dir == model.dir and m.role == ROLE_MMPROJ]
        auto = find_mmproj_for(model, same_dir)
        dup = {n for n, c in Counter(m.name for m in same_dir).items() if c > 1}
        self._loading = True
        self.combo_mmproj.blockSignals(True)
        self.combo_mmproj.clear()
        self.combo_mmproj.addItem(t('（不使用）'), None)
        sel = 0
        for m in same_dir:
            label = m.name
            if m.name in dup:
                label = f"{m.name} ({os.path.basename(m.dir)})"
            idx = self.combo_mmproj.count()
            self.combo_mmproj.addItem(f"{label}  ({human_size(m.size)})", m.path)
            self.combo_mmproj.setItemData(idx, m.path, Qt.ItemDataRole.ToolTipRole)
            if auto and m.path == auto.path:
                sel = idx
        self.combo_mmproj.setCurrentIndex(sel)
        self.cfg.data["mmproj"] = auto.path if auto else None
        self.combo_mmproj.blockSignals(False)
        self._loading = False
        self._update_mmproj_warn()
        self.update_preview()
        self._load_model_info(path)
        # 功能 4：后台检测该模型是否含 MTP 张量
        self._detect_mtp_async(path)
        # 功能 8：后台检测该模型的对话模板能力（Jinja / 思考强度）
        self._detect_chat_async(path)
    # ---------------------------------------------------------- MTP（功能 4）

    def _mtp_status_label(self, text, color="#8fd0ff"):
        """MTP 状态提示：颜色标识 + 下划线（富文本），绿=可启用，橙=不支持/无法检测。"""
        if hasattr(self, "label_mtp_status"):
            self.label_mtp_status.setText(
                f'<span style="color:{color};"><u>{text}</u></span>')

    def _detect_mtp_async(self, path):
        """后台扫描 GGUF 张量名，检测 MTP 支持并更新开关状态。"""
        if not path or not hasattr(self, "check_mtp"):
            return
        if self._mtp_cache.get(path) is None:
            self._mtp_status_label(t('MTP 检测中…'))

            def work():
                try:
                    ok, hits = detect_mtp(path)
                except Exception:
                    ok, hits = None, []
                self._mtp_cache[path] = (ok, hits)
                try:
                    self.mtp_detected.emit()
                except RuntimeError:
                    pass

            threading.Thread(target=work, daemon=True).start()
        else:
            self._apply_mtp_result(path)

    def _on_mtp_detected(self):
        try:
            path = self.combo_model.currentData()
            if path and path in self._mtp_cache:
                self._apply_mtp_result(path)
        except Exception:
            pass  # 槽函数内异常不外抛

    def _apply_mtp_result(self, path):
        ok, hits = self._mtp_cache.get(path, (None, []))
        if not hasattr(self, "check_mtp"):
            return
        if ok is None:
            # 无法检测：保持可用，允许用户手动决定
            self._mtp_status_label(t('MTP 无法检测（文件不可读），可手动勾选'), "#ff9f6a")
            self.check_mtp.setEnabled(True)
            return
        if ok:
            # 支持 MTP：开放点选
            self._mtp_status_label(t('✔ 检测到 MTP（{0} 个特征），可启用').format(len(hits)), "#7dffa8")
            self.check_mtp.setEnabled(True)
        else:
            # 未检测到 MTP：给出提示但不强制禁用，避免误判导致支持 MTP 的模型无法启用
            self._mtp_status_label(t('未检测到 MTP 张量，如确认支持可手动勾选'), "#ff9f6a")
            self._loading = True
            self.check_mtp.setChecked(False)
            self.check_mtp.setEnabled(True)
            self._loading = False
    # ---------------------------------------------------------- 对话模板（功能 8）

    def _chat_status_label(self, text, color="#8fd0ff"):
        if hasattr(self, "label_chat_status"):
            self.label_chat_status.setText(
                f'<span style="color:{color};"><u>{text}</u></span>')

    def _detect_chat_async(self, path):
        """后台读取 GGUF 的 tokenizer.chat_template，检测 Jinja / 思考强度支持。"""
        if not path or not hasattr(self, "check_jinja"):
            return
        if self._chat_cache.get(path) is None:
            self._chat_status_label(t('模板检测中…'))

            def work():
                try:
                    tpl, reason = detect_chat_features(path)
                except Exception:
                    tpl, reason = None, False
                self._chat_cache[path] = (tpl, reason)
                try:
                    self.chat_detected.emit()
                except RuntimeError:
                    pass

            threading.Thread(target=work, daemon=True).start()
        else:
            self._apply_chat_result(path)

    def _on_chat_detected(self):
        try:
            path = self.combo_model.currentData()
            if path and path in self._chat_cache:
                self._apply_chat_result(path)
        except Exception:
            pass  # 槽函数内异常不外抛

    def _apply_chat_result(self, path):
        tpl, reason = self._chat_cache.get(path, (None, False))
        if not hasattr(self, "check_jinja"):
            return
        self._chat_has_template = tpl
        self._chat_has_reasoning = bool(reason)
        self._loading = True
        if tpl is None:
            # 无法检测：保持可用，允许用户手动决定
            self._chat_status_label(t('模板无法检测（文件不可读），可手动勾选'), "#ff9f6a")
            self.check_jinja.setEnabled(True)
        elif tpl is False:
            # 模型没有内置对话模板：不支持 --jinja，强制禁用
            self._chat_status_label(t('该模型无对话模板，不支持 --jinja'), "#ff9f6a")
            self.check_jinja.setChecked(False)
            self.check_jinja.setEnabled(False)
        else:
            if self._chat_has_reasoning:
                self._chat_status_label(t('✔ 支持 Jinja 模板与思考强度'), "#7dffa8")
            else:
                self._chat_status_label(t('✔ 支持 Jinja 模板（未检测到思考强度）'), "#7dffa8")
            self.check_jinja.setEnabled(True)
        self._loading = False
        self._update_chat_controls()

    def _update_chat_controls(self):
        """按「模型能力 + 是否启用 Jinja」联动思考强度/推理预算的可选状态。

        强绑定：思考强度(--chat-template-kwargs) 依赖 --jinja；
        只有模型模板支持思考时，思考强度与推理预算才可用。
        """
        if not hasattr(self, "combo_reasoning"):
            return
        has_tpl = getattr(self, "_chat_has_template", None)
        has_reason = getattr(self, "_chat_has_reasoning", False)
        jinja_on = self.check_jinja.isChecked()
        # 模板无法检测(None)时按「可能支持」处理，允许手动使用
        tpl_ok = has_tpl is not False
        reasoning_ok = tpl_ok and (has_reason or has_tpl is None)
        self.combo_reasoning.setEnabled(jinja_on and reasoning_ok)
        self.spin_reasoning_budget.setEnabled(reasoning_ok)
        if not jinja_on:
            self.combo_reasoning.setToolTip(
                t('思考强度需要先勾选「启用 Jinja 模板」才会生效。'))
        elif not reasoning_ok:
            self.combo_reasoning.setToolTip(
                t('当前模型的对话模板未检测到思考强度（reasoning_effort）支持，暂不可用。'))
        else:
            self.combo_reasoning.setToolTip(
                t('传给对话模板的 reasoning_effort 变量（--chat-template-kwargs）。\nQwen3 等支持思考的模型用它控制「思考深度」：low/medium/high。\n「不设置」= 不传该参数（使用模板默认）。'))

    def _on_mmproj_changed(self):
        self.cfg.data["mmproj"] = self.combo_mmproj.currentData() or None
        self._update_mmproj_warn()
        self.update_preview()

    def _embedding_length(self, path):
        """读取模型的文本嵌入维度（mmproj 用 projection_dim，主模型用 embedding_length）。"""
        if not path:
            return None
        if not hasattr(self, "_emb_cache"):
            self._emb_cache = {}
        if path not in self._emb_cache:
            try:
                info = read_gguf_info(path) or {}
                self._emb_cache[path] = info.get("projection_dim") or info.get("embedding_length")
            except Exception:
                self._emb_cache[path] = None
        return self._emb_cache[path]

    def _mmproj_mismatch(self, model_path, mmproj_path):
        """返回 (模型维度, 视觉模型维度)；不匹配返回元组，匹配/未知返回 None。"""
        if not mmproj_path:
            return None
        me = self._embedding_length(model_path)
        pe = self._embedding_length(mmproj_path)
        if me is not None and pe is not None and me != pe:
            return (me, pe)
        return None

    def _update_mmproj_warn(self):
        if not hasattr(self, "label_mmproj_warn"):
            return
        model_path = self.combo_model.currentData()
        mmproj_path = self.combo_mmproj.currentData()
        mm = self._mmproj_mismatch(model_path, mmproj_path)
        if mm:
            self.label_mmproj_warn.setText(
                t('⚠ 主模型与视觉模型维度不匹配 ({0} vs {1})，可能无法加载，请更换视觉模型').format(mm[0], mm[1]))
            self.label_mmproj_warn.setToolTip(
                t('llama.cpp 要求主模型与 mmproj 的嵌入维度（embedding_length）一致。'))
        else:
            self.label_mmproj_warn.setText("")
            self.label_mmproj_warn.setToolTip("")

    def _load_model_info(self, path):
        def work():
            text = format_gguf_info(path)
            try:
                self.model_info.emit(text)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    def _clear_info(self):
        self.info_view.setPlainText(t('未选择模型'))
    # ---------------------------------------------------------- 联网查询

    def _on_model_info(self, text):
        """本地 GGUF 信息就绪：先显示，若勾选了「联网查询」再自动补充 HF 信息。"""
        self.info_view.setPlainText(text)
        if getattr(self, "check_hf_query", None) is not None and self.check_hf_query.isChecked():
            self._query_hf_info()

    def _on_hf_query_toggled(self, checked):
        if self._loading:
            return
        self.cfg.data["hf_query_enabled"] = bool(checked)
        self.cfg.save()
        if checked and self.combo_model.currentData():
            self._query_hf_info()

    def _query_hf_info(self):
        model = self.combo_model.currentData()
        if not model:
            QMessageBox.information(self, t('提示'), t('请先选择模型'))
            return
        # 查询词优先用 GGUF 里的基础模型名（更贴近 HF 仓库名），否则退回文件名去量化后缀
        query = ""
        try:
            info = read_gguf_info(model) or {}
            query = info.get("base_model_name") or info.get("general.name") or ""
        except Exception:
            query = ""
        if not query:
            query = os.path.basename(model)
            if query.lower().endswith(".gguf"):
                query = query[:-5]
        self.statusBar().showMessage(t('正在联网查询 {0} …').format(query), 3000)

        def work():
            text = hf_info.format_info(self._data_dir(), query)
            try:
                self.hf_info_done.emit(text)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_hf_info(self, text):
        self.info_view.append("\n\n" + text)
