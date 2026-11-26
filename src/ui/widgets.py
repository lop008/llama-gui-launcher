# -*- coding: utf-8 -*-
"""主窗口用到的自定义控件（折叠盒、等比图片标签）。"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QSizePolicy, QToolButton, QVBoxLayout, QWidget


class CollapsibleBox(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self._toggle = QToolButton(text=title, checkable=True, checked=True)
        self._toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle.setArrowType(Qt.ArrowType.DownArrow)
        self._toggle.setStyleSheet("QToolButton { border: none; }")
        _f = self._toggle.font()
        _f.setPointSize(_f.pointSize() + 3)   # 分组标题加粗加大（基本参数/多显卡/高级参数）
        _f.setBold(True)
        self._toggle.setFont(_f)
        self._toggle.clicked.connect(self._on_toggle)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(4, 4, 4, 4)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._toggle)
        outer.addWidget(self._content)

    def _on_toggle(self, checked):
        self._content.setVisible(checked)
        self._toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.toggled.emit(checked)

    def layout(self):
        return self._content_layout

    def set_collapsed(self, collapsed):
        self._toggle.setChecked(not collapsed)
        self._content.setVisible(not collapsed)
        self._toggle.setArrowType(Qt.ArrowType.RightArrow if collapsed else Qt.ArrowType.DownArrow)

class _AspectImageLabel(QLabel):
    """按宽度等比缩放图片的标签：横向铺满可用宽度，纵向保持原始宽高比（不拉伸变形）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._src = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sp = self.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Policy.Expanding)
        sp.setVerticalPolicy(QSizePolicy.Policy.Fixed)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        if self._src is not None and not self._src.isNull() and self._src.width() > 0:
            return max(1, int(round(w * self._src.height() / self._src.width())))
        return super().heightForWidth(w)

    def set_source_pixmap(self, pm):
        self._src = pm
        self._rescale()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._rescale()

    def _rescale(self):
        if self._src is None or self._src.isNull():
            return
        w = self.width()
        if w <= 0:
            return
        scaled = self._src.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
        super().setPixmap(scaled)
