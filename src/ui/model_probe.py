# -*- coding: utf-8 -*-
"""模型目录列表与能力检测：投机解码（MTP/DFlash/n-gram）/ 对话模板 / 视觉投影配对 / 模型信息 / HF 查询。"""

import os
import re
import threading

from collections import Counter
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from .. import hf_info
from ..gguf_reader import classify_gguf, detect_chat_features, format_gguf_info, read_gguf_info
from ..i18n import t
from ..model_scanner import (
    ROLE_DRAFT, ROLE_IMATRIX, ROLE_MMPROJ, ROLE_MODEL, drafts_for, find_mmproj_for, human_size,
    role_label, scan_models, sort_models,
)
from ..spec_decode import (
    SPEC_CLI, SPEC_IDS, ST_NEED_DRAFT, ST_NO, ST_NO_ENGINE, ST_OK, draft_matches_model,
    engine_spec_types, model_spec_support, pick_auto, spec_label,
)
from .widgets import SpecOrderDialog


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
    # ---------------------------------------------------------- 投机解码（v0.5.15）

    def _spec_status(self, text, color="#8fd0ff"):
        """投机解码状态提示：颜色 + 下划线（富文本），与对话模板那行同一套视觉。"""
        if hasattr(self, "label_spec_status"):
            self.label_spec_status.setText(
                f'<span style="color:{color};"><u>{text}</u></span>')

    def _spec_cache_map(self):
        if getattr(self, "_spec_cache", None) is None:
            self._spec_cache = {}
        return self._spec_cache

    def _spec_order(self):
        """「自动」的优先级顺序 = 用户在下拉里拖出来的顺序；没列出的补在后面。"""
        out = []
        for sid in (self.cfg.data.get("spec_order") or []):
            sid = str(sid)
            if sid in SPEC_CLI and sid not in out:
                out.append(sid)
        return out + [s for s in SPEC_IDS if s not in out]

    def _drafts_for_path(self, path):
        """同目录、与该主模型命名配套的草稿头（按配套度+类型优先级排好序）。"""
        if not path:
            return []
        info = next((m for m in (getattr(self, "_models", []) or [])
                     if getattr(m, "path", None) == path), None)
        return drafts_for(info, getattr(self, "_aux", []) or []) if info else []

    def _rebuild_spec_combo(self):
        """填「投机解码」下拉：不启用 / 自动 + 各方式（顺序 = 自动优先级）。"""
        if not hasattr(self, "combo_spec"):
            return
        want = self.combo_spec.currentData() or self._spec_mode()
        self.combo_spec.blockSignals(True)
        self.combo_spec.clear()
        self.combo_spec.addItem(t('不启用'), "off")
        self.combo_spec.addItem(t('自动（推荐）'), "auto")
        for sid in self._spec_order():
            self.combo_spec.addItem(spec_label(sid) or sid, sid)
        idx = self.combo_spec.findData(want)
        self.combo_spec.setCurrentIndex(idx if idx >= 0 else 1)
        self.combo_spec.blockSignals(False)

    def _spec_mode(self):
        """配置里的模式；老配置已由 config._migrate 把 mtp 勾选迁成 spec_mode。"""
        mode = str(self.cfg.data.get("server", {}).get("spec_mode") or "off")
        return mode if mode in ("off", "auto") or mode in SPEC_CLI else "off"

    def _save_spec_order(self, ids):
        """保存「自动」的优先级顺序并让界面同步。"""
        self.cfg.data["spec_order"] = list(ids)
        self.cfg.save()
        self._rebuild_spec_combo()
        self._update_spec_ui()
        self._status_tip(t('「自动」的优先级已保存'), 4000)

    def _edit_spec_order(self):
        """「排序」按钮：在弹窗里拖动或用 ▲▼ 调整「自动」的优先级。"""
        order = self._spec_order()
        rows = [(spec_label(sid) or sid, sid) for sid in order]
        dlg = SpecOrderDialog(self, rows, current_order=order, default_order=list(SPEC_IDS))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new = dlg.ordered_values()
        if new and new != order:
            self._save_spec_order(new)

    def _spec_item_tip(self, sid, r):
        """下拉里每一项的悬停说明（含可用状态与原因）。"""
        if sid == "off":
            return t('不下发 --spec-type，纯自回归生成。')
        if sid == "auto":
            return t('按你在本下拉里的顺序（按住条目上下拖动即可改），挑第一个当前可用的方式。')
        if r is None:
            return ""
        mark = {ST_OK: '✔', ST_NEED_DRAFT: '⚠', ST_NO_ENGINE: '✖', ST_NO: '—'}.get(r["state"], "")
        line = " ".join(x for x in (mark, r["label"], r["reason"]) if x)
        if r.get("draft"):
            line += "\n" + t('草稿文件: {0}').format(r["draft"])
        return line

    def _spec_status_text(self, mode, by_id):
        """状态标签文案与颜色：绿=可用，橙=缺草稿/没检测到，红=本机不支持。"""
        if mode in (None, "off"):
            return t('未启用（选「自动」通常能白捡一段加速）'), "#8a8a8a"
        if mode == "auto":
            sid, _cli, _draft = pick_auto(self._spec_rows(), self._spec_order())
            if not sid:
                return t('当前模型没有可用的投机方式（可下载草稿，或改用 n-gram）'), "#ff9f6a"
            row = {r["id"]: r for r in self._spec_rows()}.get(sid) or {}
            return t('自动 → {0}：{1}').format(spec_label(sid) or sid,
                                               row.get("reason", "")), "#7dffa8"
        r = by_id.get(mode)
        if r is None:
            return t('检测中…'), "#8fd0ff"
        label = r["label"] or spec_label(mode)
        color = {ST_OK: "#7dffa8", ST_NEED_DRAFT: "#ff9f6a",
                 ST_NO_ENGINE: "#ff6a6a", ST_NO: "#ff9f6a"}.get(r["state"], "#8fd0ff")
        mark = {ST_OK: '✔', ST_NEED_DRAFT: '⚠', ST_NO_ENGINE: '✖', ST_NO: '—'}.get(r["state"], "")
        return t('{0} {1}：{2}').format(mark, label, r["reason"]), color

    def _rebuild_draft_combo(self, mode):
        """草稿下拉：只列与该方式对应、且与主模型同目录的草稿文件。"""
        if not hasattr(self, "combo_draft"):
            return
        sid = mode if mode in SPEC_CLI else None
        needs = bool(sid) and SPEC_CLI[sid][1]
        model_path = self.combo_model.currentData() if hasattr(self, "combo_model") else None
        cur = self.combo_draft.currentData()
        self.combo_draft.blockSignals(True)
        self.combo_draft.clear()
        if mode in (None, "off", "auto"):
            self.combo_draft.addItem(t('（由所选方式决定）'), None)
        elif not needs:
            self.combo_draft.addItem(t('（无需草稿文件）'), None)
        else:
            items = []
            for d in self._drafts_for_path(model_path):
                if (d.kind or "") not in (sid, ""):
                    continue
                warn = ""
                try:
                    ok_match, why = draft_matches_model(d.path, model_path)
                    if not ok_match:
                        warn = " " + t('（{0}）').format(why)
                except Exception:
                    pass
                items.append((f"{d.name}  ({human_size(d.size)}){warn}", d.path))
            if sid == "simple":
                # 「小模型草稿」是拿一个正常的小模型当草稿（例如给 27B 配 0.6B），
                # 这种文件本身是真模型、不会被归类成草稿头，所以把更小的模型也列出来。
                main_size = next((m.size for m in (getattr(self, "_models", []) or [])
                                  if getattr(m, "path", None) == model_path), 0)
                small = sorted((m for m in (getattr(self, "_models", []) or [])
                                if getattr(m, "path", None) != model_path
                                and main_size and m.size and m.size < main_size / 4),
                               key=lambda m: m.size)
                for m in small[:12]:
                    items.append((f"{m.name}  ({human_size(m.size)})", m.path))
            for label, path in items:
                self.combo_draft.addItem(label, path)
                self.combo_draft.setItemData(self.combo_draft.count() - 1, path,
                                             Qt.ItemDataRole.ToolTipRole)
            if items:
                self.combo_draft.insertItem(0, t('（自动配对）'), None)
            else:
                self.combo_draft.addItem(t('（未找到配套草稿，可点「下载草稿」）'), None)
        idx = self.combo_draft.findData(cur)
        self.combo_draft.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_draft.blockSignals(False)

    def _update_spec_ui(self):
        """按「下拉选择 + 检测结果」刷新：每项置灰与说明、状态标签、草稿下拉、长度框。"""
        if not hasattr(self, "combo_spec"):
            return
        rows = self._spec_rows()
        by_id = {r["id"]: r for r in rows}
        self.combo_spec.blockSignals(True)
        for i in range(self.combo_spec.count()):
            sid = self.combo_spec.itemData(i)
            r = by_id.get(sid)
            self.combo_spec.setItemData(i, self._spec_item_tip(sid, r), Qt.ItemDataRole.ToolTipRole)
            it = self.combo_spec.model().item(i)
            if it is None:
                continue
            flags = it.flags()
            # 本机 llama-server 不认这种方式 → 置灰（更新 llama.cpp 后即可用）
            it.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled if r is not None
                        and r["state"] == ST_NO_ENGINE else flags | Qt.ItemFlag.ItemIsEnabled)
        self.combo_spec.blockSignals(False)

        mode = self.combo_spec.currentData() or "off"
        self._rebuild_draft_combo(mode)
        self._spec_status(*self._spec_status_text(mode, by_id))
        sid = mode if mode in SPEC_CLI else None
        needs = bool(sid) and SPEC_CLI[sid][1]
        self.combo_draft.setEnabled(bool(needs))
        self.btn_spec_download.setEnabled(bool(needs))
        # --spec-draft-n-max 只对「有草稿」的方式有意义，n-gram 用不上
        self.spin_spec_n.setEnabled(bool(sid) and not str(sid).startswith("ngram"))

    def _spec_rows(self):
        """当前模型的各方式支持表（检测结果缓存；没检测完返回空表）。"""
        path = self.combo_model.currentData() if hasattr(self, "combo_model") else None
        return self._spec_cache_map().get(path) or [] if path else []

    def _detect_mtp_async(self, path):
        """后台一次算完三件事：本机认哪些 --spec-type、这模型能用哪几种、草稿配没配。

        要读 GGUF 文件头并跑一次 llama-server --help，放线程里做；完成后经
        mtp_detected 信号回主线程刷新（信号名沿用 MTP 时期，现代表「投机解码检测完成」）。
        """
        if not path or not hasattr(self, "combo_spec"):
            return
        cache = self._spec_cache_map()
        if cache.get(path) is not None:
            self._update_spec_ui()
            return
        self._spec_status(t('投机解码检测中…'), "#8fd0ff")
        drafts = self._drafts_for_path(path)        # 主线程取好，避免后台读列表竞态
        exe = self._launcher_exe()

        def work():
            try:
                rows = model_spec_support(path, drafts, engine_spec_types(exe))
            except Exception:
                rows = []
            cache[path] = rows
            try:
                self.mtp_detected.emit()
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_mtp_detected(self):
        try:
            if self.combo_model.currentData() in self._spec_cache_map():
                self._update_spec_ui()
        except Exception:
            pass  # 槽函数内异常不外抛

    def _on_spec_changed(self):
        if getattr(self, "_loading", False):
            return
        self._update_spec_ui()

    def _on_draft_changed(self):
        if getattr(self, "_loading", False):
            return
        self.update_preview()

    def _spec_resolve(self):
        """把界面选择解析成命令行参数：(spec_mode, spec_cli, spec_draft, spec_draft_n)。

        spec_cli 为空 = 不下发 --spec-type：包括「不启用」，以及「自动」但当前模型
        一种可用方式都没有的情况（此时照常启动，只在状态栏提示，不弹窗拦人）。
        """
        mode = (self.combo_spec.currentData() or "off") if hasattr(self, "combo_spec") else "off"
        n = self.spin_spec_n.value() if hasattr(self, "spin_spec_n") else 0
        if mode in (None, "off"):
            return "off", "", "", 0
        by_id = {r["id"]: r for r in self._spec_rows()}
        if mode == "auto":
            sid, cli, draft = pick_auto(self._spec_rows(), self._spec_order())
            if not sid:
                return "auto", "", "", 0
        else:
            r = by_id.get(mode)
            sid, cli, draft = mode, (r["cli"] if r else ""), (r.get("draft") if r else None)
        if sid not in SPEC_CLI:
            return mode, "", "", 0
        manual = self.combo_draft.currentData() if hasattr(self, "combo_draft") else None
        draft = manual or draft or ""
        if SPEC_CLI[sid][1] and not (draft and os.path.isfile(draft)):
            return mode, "", "", 0        # 缺草稿：宁可不加速，也不让服务起不来
        return mode, cli, draft, int(n or 0)
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

    # ---------------------------------------------------------- 辅助文件清单
    def _update_aux_summary(self):
        """模型区下方那行「辅助文件: …（查看）」的文案。"""
        if not hasattr(self, "btn_aux"):
            return
        mm, dr, im = self._aux_summary()
        parts = []
        if mm:
            parts.append(f"{role_label(ROLE_MMPROJ)} {mm}")
        if dr:
            parts.append(f"{role_label(ROLE_DRAFT)} {dr}")
        if im:
            parts.append(f"{role_label(ROLE_IMATRIX)} {im}")
        self.btn_aux.setText(t('辅助文件: 无') if not parts
                             else t('辅助文件: {0}（查看）').format(" · ".join(parts)))

    def _show_aux_files(self):
        """辅助文件清单：类型 / 文件名 / 大小 / 所在目录（给哪个主模型用）。"""
        aux = sorted(getattr(self, "_aux", []) or [], key=lambda a: (a.role, a.dir, a.name))
        if not aux:
            QMessageBox.information(self, t('辅助文件'), t('当前模型目录下没有辅助文件。'))
            return
        by_dir = {}
        for m in getattr(self, "_models", []) or []:
            by_dir.setdefault(m.dir, []).append(m.name)

        dlg = QDialog(self)
        dlg.setWindowTitle(t('辅助文件（{0} 个）').format(len(aux)))
        dlg.resize(1000, 520)
        lay = QVBoxLayout(dlg)
        tip = QLabel(t('这些文件不是独立模型，所以不出现在主模型列表里：'
                       '视觉投影负责看图，投机草稿头用于加速，量化标定文件只在制作量化模型时用。'))
        tip.setWordWrap(True)
        lay.addWidget(tip)

        table = QTableWidget(len(aux), 4)
        table.setHorizontalHeaderLabels(
            [t('类型'), t('文件名'), t('大小'), t('所在目录（对应主模型）')])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        head = table.horizontalHeader()
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.setColumnWidth(0, 160)
        table.setColumnWidth(2, 90)
        for row, a in enumerate(aux):
            names = by_dir.get(a.dir) or []
            who = "、".join(names[:2]) + ("…" if len(names) > 2 else "") or t('（同目录没有主模型）')
            cells = (role_label(a.role, a.kind), a.name, human_size(a.size),
                     f"{a.dir}  [{who}]" if names else a.dir)
            for col, text in enumerate(cells):
                it = QTableWidgetItem(text)
                it.setData(Qt.ItemDataRole.UserRole, a.path)
                it.setToolTip(a.path)
                table.setItem(row, col, it)
        table.setCurrentCell(0, 0)

        btns = QHBoxLayout()
        btns.addStretch(1)
        open_btn = QPushButton(t('打开所在目录'))

        def open_dir():
            it = table.currentItem()
            path = it.data(Qt.ItemDataRole.UserRole) if it is not None else ""
            d = os.path.dirname(str(path or ""))
            if d and os.path.isdir(d):
                os.startfile(d)  # noqa: S606
            else:
                QMessageBox.information(self, t('提示'), t('目录无效'))

        open_btn.clicked.connect(open_dir)
        close_btn = QPushButton(t('关闭'))
        close_btn.clicked.connect(dlg.accept)
        btns.addWidget(open_btn)
        btns.addWidget(close_btn)
        lay.addLayout(btns)
        dlg.exec()

    def _download_spec_draft(self):
        """「下载草稿」：切到「模型下载」页，按当前模型预填检索条件。

        草稿头基本与主模型同名（官方 GGUF 仓库里的 MTP/、DFLASH/ 目录，或独立的
        草稿仓库），所以用 GGUF 元数据里的基础模型名去搜最准；下载页自己按下载量排序，
        官方仓库会排在前面。
        """
        model = self.combo_model.currentData() if hasattr(self, "combo_model") else None
        if not model:
            QMessageBox.information(self, t('提示'), t('请先选择模型'))
            return
        query = ""
        try:
            info = read_gguf_info(model) or {}
            query = info.get("base_model_name") or info.get("general.name") or ""
        except Exception:
            query = ""
        if not query:
            query = re.sub(r"\.gguf$", "", os.path.basename(model), flags=re.IGNORECASE)
        tab = getattr(self, "download_tab", None)
        if tab is None:
            return
        tab.edit_name.setText(query)
        tab.edit_kw.setText("GGUF")
        self.tabs.setCurrentWidget(tab)
        self._status_tip(t('已在「模型下载」页按 {0} 预填检索，选带 MTP/DFlash 等目录的仓库').format(query),
                         6000)

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
