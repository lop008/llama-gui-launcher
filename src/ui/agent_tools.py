# -*- coding: utf-8 -*-
"""Agent 工具页：本机工具扫描、表格渲染、添加/编辑/删除、自动描述。"""
import os
import threading
import uuid

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QMessageBox, QPushButton, QTableWidgetItem,
)
from ..cmd_builder import model_alias
from ..i18n import t
from .agent_edit import AgentEditDialog

try:
    from .. import tools as tools_mod
    from .. import opencode_launcher
except Exception:
    tools_mod = None
    opencode_launcher = None


class AgentToolsMixin:
    # ------------------------------------------------------ Agent 工具
    def _tool_defs(self):
        """内置工具（应用覆盖/隐藏）+ 用户自定义工具。"""
        if tools_mod is None:
            return []
        cfg = self.cfg.data
        hidden = set(cfg.get("tools_hidden") or [])
        overrides = cfg.get("tools") or {}
        out = []
        for td in tools_mod.ALL:
            if td.get("id") in hidden:
                continue
            d = dict(td)
            ov = overrides.get(td.get("id")) or {}
            for key in ("name", "desc", "category"):
                if ov.get(key):
                    d[key] = ov[key]
            if ov.get("path"):
                d["path"] = ov["path"]
            d["_custom"] = False
            out.append(d)
        for ct in (cfg.get("custom_tools") or []):
            if not isinstance(ct, dict) or not ct.get("id"):
                continue
            d = dict(ct)
            d["_custom"] = True
            d.setdefault("category", "app")
            d.setdefault("desc", "")
            out.append(d)
        return out

    def scan_tools(self):
        defs = self._tool_defs()
        llama_dir = self.edit_dir.text().strip()
        launcher_exe = self.edit_launcher.text().strip()
        overrides = self.cfg.data.get("tools", {})

        def work():
            found = {}
            for td in defs:
                tid = td.get("id")
                ov = overrides.get(tid) or {}
                if ov.get("path"):
                    found[tid] = ov["path"]
                elif td.get("path"):
                    found[tid] = td["path"]
                elif tools_mod is not None:
                    try:
                        found[tid] = tools_mod.find(td, llama_dir, launcher_exe)
                    except Exception:
                        found[tid] = None
                else:
                    found[tid] = None
            self._tools_found = found
            try:
                self.tool_scan_done.emit()
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()
        self.statusBar().showMessage(t('正在检测工具…'), 2000)

    def _on_tool_scan_done(self):
        self._fill_tool_table()
        self._status_tip(t('工具检测完成'), 3000)

    def _fill_tool_table(self):
        defs = self._tool_defs()
        self._tool_rows = defs
        self.tool_table.setRowCount(len(defs))
        for r, tool in enumerate(defs):
            tid = tool.get("id")
            path = self._tools_found.get(tid) or tool.get("path") or ""
            name_item = QTableWidgetItem(tool.get("name", tid or ""))
            name_item.setData(Qt.ItemDataRole.UserRole, tid)
            name_item.setToolTip(tool.get("desc", ""))
            cat = t('终端') if tool.get("category") == "terminal" else t('应用')
            type_item = QTableWidgetItem(cat)
            path_item = QTableWidgetItem(path or t('未找到（双击指定路径）'))
            path_item.setToolTip(path or t('未找到，双击行或点「编辑」指定可执行文件'))
            if not path:
                path_item.setForeground(QBrush(QColor("#ff9f6a")))
            desc_item = QTableWidgetItem(tool.get("desc", ""))
            desc_item.setToolTip(tool.get("desc", ""))
            self.tool_table.setItem(r, 0, name_item)
            self.tool_table.setItem(r, 1, type_item)
            self.tool_table.setItem(r, 2, path_item)
            self.tool_table.setItem(r, 3, desc_item)
            btn = QPushButton(t('打开') if path else t('指定路径'))
            btn.setProperty("variant", "ghost" if path else "primary")
            btn.setFixedWidth(76)
            btn.clicked.connect(lambda _=False, id_=tid: self._tool_open(id_))
            self.tool_table.setCellWidget(r, 4, btn)
        self._preserve_tool_selection()

    def _preserve_tool_selection(self):
        """保持上次选中的工具高亮；没有则默认高亮第一行。"""
        if not self._tool_rows:
            return
        row = 0
        last = getattr(self, "_last_selected_tool", None) or self.cfg.data.get("last_agent_tool", "")
        if last:
            for i, td in enumerate(self._tool_rows):
                if td.get("id") == last:
                    row = i
                    break
        self.tool_table.selectRow(row)
        self.tool_table.setCurrentCell(row, 0)

    def _current_tool(self):
        row = self.tool_table.currentRow()
        if 0 <= row < len(self._tool_rows):
            return self._tool_rows[row]
        return None

    def _on_tool_cell_changed(self, row, _col, _pr, _pc):
        if 0 <= row < len(self._tool_rows):
            self._last_selected_tool = self._tool_rows[row]["id"]
            self.cfg.data["last_agent_tool"] = self._last_selected_tool

    def _tool_table_double(self, index):
        if index.row() < len(self._tool_rows):
            self._tool_open(self._tool_rows[index.row()]["id"])

    def _tool_open(self, tid):
        if tools_mod is None:
            return
        tool = next((td for td in self._tool_rows if td.get("id") == tid), None)
        if tool is None:
            return
        self._last_selected_tool = tid
        self.cfg.data["last_agent_tool"] = tid
        path = self._tools_found.get(tid) or tool.get("path")
        override = self.cfg.data.get("tools", {}).get(tid)
        if override and override.get("path"):
            path = override["path"]
        if not path:
            self._prompt_add_path(tool)
            return
        workdir = self.edit_dir.text().strip() or None
        args = override.get("args", "") if override else tool.get("args", "")
        env, conn_info, extra_args = self._agent_connect(tool, workdir)
        if extra_args:
            args = (args + " " + extra_args).strip()
        ok = tools_mod.launch(path, tool, args, workdir, env)
        if ok:
            msg = t('已打开 {0}').format(tool['name'])
            if conn_info:
                msg += f"　·　{conn_info}"
            self.statusBar().showMessage(msg, 6000)
            self._on_server_log(msg)
        else:
            QMessageBox.warning(self, t('提示'), t('启动失败，请检查路径'))

    def _agent_connect(self, tool, workdir=None):
        """打开 Agent 工具时自动配置其连接当前 llama 服务。
        返回 (env, 连接说明文本, 附加启动参数)；服务未运行返回 (None, '服务未运行，无法自动连接', '')。"""
        if not self.server.running:
            return None, t('服务未运行，无法自动连接'), ""
        s = self._gather_server_cfg()
        scheme = "https" if s.get("ssl_enabled") else "http"
        base = f"{scheme}://{s['host']}:{s['port']}"
        base_v1 = base + "/v1"
        alias = model_alias(self.combo_model.currentData() or "")
        api_key = s.get("api_key", "")
        key = api_key or "llama"
        tid = tool.get("id")
        model_path = self.combo_model.currentData()

        if tid == "opencode" and opencode_launcher is not None:
            cfg = opencode_launcher.build_config(
                s["host"], s["port"], alias, s["ctx"], s["n_predict"], s["api_key"],
                scheme=scheme)
            wd = (workdir
                  or str(self.cfg.data.get("opencode_workdir") or "").strip()
                  or self.edit_dir.text().strip())
            try:
                opencode_launcher.write_config(wd, cfg)
                return None, t('已自动配置 opencode 连接 {0}（模型 {1}）').format(base_v1, alias), ""
            except Exception as e:
                return None, t('opencode 配置写入失败: {0}').format(e), ""
        if tid == "claude":
            return None, t('Claude Code 未自动连接（llama.cpp 的 Anthropic 接口兼容性有限），如需连接请手动配置 ANTHROPIC_BASE_URL'), ""
        if tid in ("codex", "aichat"):
            return {"OPENAI_BASE_URL": base_v1, "OPENAI_API_KEY": key,
                    "OPENAI_MODEL": alias}, t('已连接 {0}（OpenAI 接口，模型 {1}）').format(base_v1, alias), ""

        try:
            text = t('模型: {0}\nAPI: {1}\n').format(alias, base_v1)
            if model_path:
                text += t('文件: {0}\n').format(model_path)
            QApplication.clipboard().setText(text)
            return None, t('已复制连接信息到剪贴板（{0}，模型 {1}）').format(base_v1, alias), ""
        except Exception:
            return None, t('服务地址 {0}（模型 {1}）').format(base_v1, alias), ""

    def open_selected_agent_tool(self):
        """打开 Agent 工具列表中当前高亮的工具（始终高亮选中行）。"""
        if not self._tool_rows:
            QMessageBox.information(self, t('提示'), t('Agent 工具列表为空'))
            return
        row = self.tool_table.currentRow()
        if row < 0 or row >= len(self._tool_rows):
            row = 0
        self._tool_open(self._tool_rows[row]["id"])

    def _prompt_add_path(self, tool):
        ret = QMessageBox.question(
            self, t('未找到'), t('未找到「{0}」，是否手动指定可执行文件路径？').format(tool.get('name', tool.get('id'))),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return
        start = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, t('选择 {0} 可执行文件').format(tool.get('name')), start,
            t('可执行文件 (*.exe *.cmd *.bat *.ps1);;所有文件 (*.*)'))
        if not path:
            return
        if tool.get("_custom"):
            for ct in (self.cfg.data.get("custom_tools") or []):
                if ct.get("id") == tool.get("id"):
                    ct["path"] = path
        else:
            self.cfg.data.setdefault("tools", {})[tool["id"]] = {
                "path": path, "args": tool.get("args", "")}
        self.cfg.save()
        self.scan_tools()

    # ------------------------------------------------------ 添加 / 编辑 / 删除
    def _add_agent_tool(self):
        dlg = AgentEditDialog(self, {})
        if dlg.exec() != AgentEditDialog.DialogCode.Accepted:
            return
        data = dlg.values()
        data["id"] = "custom-" + uuid.uuid4().hex[:10]
        data["_custom"] = True
        self.cfg.data.setdefault("custom_tools", []).append(data)
        self.cfg.save()
        self._status_tip(t('已添加 Agent 工具：{0}').format(data.get('name')), 4000)
        self.scan_tools()

    def _edit_agent_tool(self):
        tool = self._current_tool()
        if not tool:
            QMessageBox.information(self, t('提示'), t('请先选中一个工具。'))
            return
        tid = tool.get("id")
        data = dict(tool)
        data["_edit"] = True
        dlg = AgentEditDialog(self, data)
        if dlg.exec() != AgentEditDialog.DialogCode.Accepted:
            return
        vals = dlg.values()
        if tool.get("_custom"):
            for ct in (self.cfg.data.get("custom_tools") or []):
                if ct.get("id") == tid:
                    ct.update(vals)
        else:
            ov = self.cfg.data.setdefault("tools", {}).setdefault(tid, {})
            ov.update(vals)
        self.cfg.save()
        self._status_tip(t('已更新 Agent 工具：{0}').format(vals.get('name')), 4000)
        self.scan_tools()

    def _delete_agent_tool(self):
        tool = self._current_tool()
        if not tool:
            QMessageBox.information(self, t('提示'), t('请先选中一个工具。'))
            return
        name = tool.get("name", tool.get("id"))
        ret = QMessageBox.question(
            self, t('删除 Agent 工具'),
            t('确定从列表中删除「{0}」吗？\n（不会删除磁盘上的程序文件）').format(name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return
        tid = tool.get("id")
        if tool.get("_custom"):
            self.cfg.data["custom_tools"] = [
                ct for ct in (self.cfg.data.get("custom_tools") or [])
                if ct.get("id") != tid]
        else:
            hidden = list(self.cfg.data.get("tools_hidden") or [])
            if tid not in hidden:
                hidden.append(tid)
            self.cfg.data["tools_hidden"] = hidden
        self.cfg.save()
        self._status_tip(t('已删除 Agent 工具：{0}').format(name), 4000)
        self.scan_tools()

    def _auto_describe_tools(self):
        """从可执行文件的版本信息自动更新描述。"""
        if tools_mod is None:
            return
        updated = 0
        for tool in self._tool_defs():
            tid = tool.get("id")
            path = self._tools_found.get(tid) or tool.get("path")
            if not path:
                continue
            desc = tools_mod.describe_executable(path)
            if not desc or desc == tool.get("desc"):
                continue
            if tool.get("_custom"):
                for ct in (self.cfg.data.get("custom_tools") or []):
                    if ct.get("id") == tid:
                        ct["desc"] = desc
                        updated += 1
            else:
                ov = self.cfg.data.setdefault("tools", {}).setdefault(tid, {})
                ov["desc"] = desc
                updated += 1
        self.cfg.save()
        self._fill_tool_table()
        self._status_tip(t('已自动更新 {0} 个工具描述').format(updated), 5000)
