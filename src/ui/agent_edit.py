# -*- coding: utf-8 -*-
"""Agent 工具添加/编辑对话框。"""
import os

from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from ..i18n import t
from ..tools import describe_executable


class AgentEditDialog(QDialog):
    """名称 / 类型 / 路径 / 启动参数 / 描述。"""

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        data = data or {}
        self.setWindowTitle(t('编辑 Agent 工具') if data.get("_edit") else t('添加 Agent 工具'))
        self.resize(560, 320)

        root = QVBoxLayout(self)
        tip = QLabel(t('填写可执行文件路径；描述留空时可点「自动读取描述」从 exe 版本信息里取。'))
        tip.setWordWrap(True)
        tip.setObjectName("Muted")
        root.addWidget(tip)

        form = QFormLayout()
        form.setSpacing(8)
        self.edit_name = QLineEdit(str(data.get("name") or ""))
        form.addRow(t('名称:'), self.edit_name)

        self.combo_cat = QComboBox()
        self.combo_cat.addItem(t('终端'), "terminal")
        self.combo_cat.addItem(t('应用'), "app")
        idx = self.combo_cat.findData(str(data.get("category") or "app"))
        self.combo_cat.setCurrentIndex(idx if idx >= 0 else 1)
        form.addRow(t('类型:'), self.combo_cat)

        path_row = QHBoxLayout()
        self.edit_path = QLineEdit(str(data.get("path") or ""))
        self.edit_path.setPlaceholderText(t('例如 C:\\Tools\\agent.exe'))
        btn_browse = QPushButton(t('浏览…'))
        btn_browse.clicked.connect(self._browse)
        path_row.addWidget(self.edit_path, 1)
        path_row.addWidget(btn_browse)
        form.addRow(t('路径:'), path_row)

        self.edit_args = QLineEdit(str(data.get("args") or ""))
        self.edit_args.setPlaceholderText(t('可选，例如 --model xxx'))
        form.addRow(t('启动参数:'), self.edit_args)

        desc_row = QHBoxLayout()
        self.edit_desc = QLineEdit(str(data.get("desc") or ""))
        btn_desc = QPushButton(t('自动读取描述'))
        btn_desc.clicked.connect(self._auto_desc)
        desc_row.addWidget(self.edit_desc, 1)
        desc_row.addWidget(btn_desc)
        form.addRow(t('描述:'), desc_row)
        root.addLayout(form)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._ok)
        box.rejected.connect(self.reject)
        root.addWidget(box)

    def _browse(self):
        start = self.edit_path.text().strip() or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, t('选择 Agent 可执行文件'), start,
            t('可执行文件 (*.exe *.cmd *.bat *.ps1);;所有文件 (*.*)'))
        if path:
            self.edit_path.setText(path)
            if not self.edit_name.text().strip():
                self.edit_name.setText(os.path.splitext(os.path.basename(path))[0])

    def _auto_desc(self):
        path = self.edit_path.text().strip()
        if not path or not os.path.isfile(path):
            QMessageBox.information(self, t('提示'), t('请先选择一个存在的可执行文件。'))
            return
        desc = describe_executable(path)
        if desc:
            self.edit_desc.setText(desc)
        else:
            QMessageBox.information(self, t('提示'), t('这个文件没有可读取的版本描述。'))

    def _ok(self):
        if not self.edit_name.text().strip():
            QMessageBox.warning(self, t('提示'), t('名称不能为空。'))
            return
        if not self.edit_path.text().strip():
            QMessageBox.warning(self, t('提示'), t('路径不能为空。'))
            return
        self.accept()

    def values(self):
        return {
            "name": self.edit_name.text().strip(),
            "category": self.combo_cat.currentData() or "app",
            "path": self.edit_path.text().strip(),
            "args": self.edit_args.text().strip(),
            "desc": self.edit_desc.text().strip(),
        }
