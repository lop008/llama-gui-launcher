# -*- coding: utf-8 -*-
"""Agent 工具页：本机工具扫描、表格渲染、生成连接命令。"""

import os
import threading

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton, QTableWidgetItem
from ..cmd_builder import model_alias
from ..i18n import t

try:
    from .. import tools as tools_mod
    from .. import opencode_launcher
except Exception:
    tools_mod = None
    opencode_launcher = None


class AgentToolsMixin:
    # ------------------------------------------------------ Agent 工具
    def scan_tools(self):
        overrides = self.cfg.data.get("tools", {})
        llama_dir = self.edit_dir.text().strip()
        launcher_exe = self.edit_launcher.text().strip()

        def work():
            try:
                self._tools_found = tools_mod.scan_all(overrides, llama_dir, launcher_exe)
            except Exception:
                self._tools_found = {}
            self.tool_scan_done.emit()

        threading.Thread(target=work, daemon=True).start()
        self.statusBar().showMessage(t('正在检测工具…'), 2000)
    def _on_tool_scan_done(self):
        self._fill_tool_table()
        self._status_tip(t('工具检测完成'), 3000)
    def _fill_tool_table(self):
        rows = []
        for tool_def in tools_mod.ALL:
            rows.append((tool_def, self._tools_found.get(tool_def["id"])))
        self._tool_rows = [r[0] for r in rows]
        self.tool_table.setRowCount(len(rows))
        for r, (tool, path) in enumerate(rows):
            name_item = QTableWidgetItem(tool.get("name", tool["id"]))
            name_item.setData(Qt.ItemDataRole.UserRole, tool.get("id"))
            cat = t('终端') if tool.get("category") == "terminal" else t('应用')
            desc_item = QTableWidgetItem(tool.get("desc", ""))
            type_item = QTableWidgetItem(cat)
            status_item = QTableWidgetItem(path or t('未找到'))
            self.tool_table.setItem(r, 0, name_item)
            self.tool_table.setItem(r, 1, type_item)
            self.tool_table.setItem(r, 2, desc_item)
            self.tool_table.setItem(r, 3, status_item)
            btn = QPushButton(t('打开') if path else t('添加路径'))
            btn.clicked.connect(lambda _=False, tid=tool["id"]: self._tool_open(tid))
            self.tool_table.setCellWidget(r, 4, btn)
        self._preserve_tool_selection()
    def _preserve_tool_selection(self):
        """保持上次选中的工具高亮；没有则默认高亮第一行。"""
        if not self._tool_rows:
            return
        row = 0
        last = getattr(self, "_last_selected_tool", None) or self.cfg.data.get("last_agent_tool", "")
        if last:
            for i, t in enumerate(self._tool_rows):
                if t.get("id") == last:
                    row = i
                    break
        self.tool_table.selectRow(row)
        self.tool_table.setCurrentCell(row, 0)
    def _on_tool_cell_changed(self, row, _col, _pr, _pc):
        if 0 <= row < len(self._tool_rows):
            self._last_selected_tool = self._tool_rows[row]["id"]
            self.cfg.data["last_agent_tool"] = self._tool_rows[row]["id"]
    def _tool_table_double(self, index):
        if index.row() < len(self._tool_rows):
            self._tool_open(self._tool_rows[index.row()]["id"])
    def _tool_open(self, tid):
        if tools_mod is None:
            return
        tool = next((td for td in tools_mod.ALL if td["id"] == tid), None)
        if tool is None:
            return
        self._last_selected_tool = tid
        self.cfg.data["last_agent_tool"] = tid
        path = self._tools_found.get(tid)
        override = self.cfg.data.get("tools", {}).get(tid)
        if override and override.get("path"):
            path = override["path"]
        if not path:
            self._prompt_add_path(tool)
            return
        workdir = self.edit_dir.text().strip() or None
        args = override.get("args", "") if override else ""
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

        # 其他工具（含 GUI 应用）：复制连接信息到剪贴板
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
            self, t('未找到'), t('未找到「{0}」，是否手动指定可执行文件路径？').format(tool.get('name', tool['id'])),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return
        start = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, t('选择 {0} 可执行文件').format(tool.get('name')), start,
                                              t('可执行文件 (*.exe *.cmd *.bat *.ps1);;所有文件 (*.*)'))
        if not path:
            return
        self.cfg.data.setdefault("tools", {})[tool["id"]] = {"path": path, "args": ""}
        self._tools_found[tool["id"]] = path
        self.cfg.save()
        self._fill_tool_table()
        self.statusBar().showMessage(t('已记录 {0} 路径').format(tool['name']), 3000)
