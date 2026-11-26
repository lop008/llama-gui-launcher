# -*- coding: utf-8 -*-
"""主窗口用到的自定义控件（折叠盒、等比图片标签、优先级排序对话框）。"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)
from ..i18n import t


class _ReorderList(QListWidget):
    """按住条目上下移动就能改顺序的列表（自己处理鼠标，不走 Qt 的 QDrag）。

    两个坑，都是实测踩出来的：
    1. 不用 setDragDropMode(InternalMove)：Qt 在 Windows 上启动拖拽会调
       QDrag::exec() 进 OLE 原生模态循环，脚本注入的合成鼠标事件进不去，
       这个功能就永远测不到（offscreen 和 windows 两个平台都拖不动）。
    2. 拖拽过程中不能 takeItem()/insertItem()：视图正拿着被删条目的内部索引，
       删掉直接让进程 fastfail（0xC0000409）。所以顺序变了只「原地改写每行的
       文本和 data」，条目对象从头到尾不增不减，视觉效果同样是列表在跟着手重排。
    """

    reordered = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_row = -1
        self._press_pos = None
        self._texts = {}
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    # ---- 数据 ----
    def add_row(self, text, data):
        """加一行；text 会存起来，之后原地重排时按 data 找回显示文字。"""
        self._texts[data] = text
        it = QListWidgetItem(text)
        it.setData(Qt.ItemDataRole.UserRole, data)
        it.setToolTip(t('按住可上下拖动，或用下方 ▲▼（Alt+↑ / Alt+↓）调整位置'))
        self.addItem(it)

    def ordered_values(self):
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

    def apply_order(self, order):
        """按给定的 data 顺序原地改写各行内容（条目数不变）。"""
        if sorted(order) != sorted(self.ordered_values()):
            return False
        for row, data in enumerate(order):
            it = self.item(row)
            it.setText(self._texts.get(data, str(data)))
            it.setData(Qt.ItemDataRole.UserRole, data)
        return True

    # ---- 拖动 ----
    def _row_at(self, y):
        """事件派发过程中不能调 self.rowAt()（实测会让整个进程 fastfail 0xC0000409），
        所以用「行高 + 滚动量」自己算；行高用 sizeHintForRow(0)，实测在事件里调用是安全的。
        """
        rh = self.sizeHintForRow(0)
        if rh <= 0:
            rh = self.fontMetrics().height() + 4
        row = (int(y) + self.verticalScrollBar().value()) // rh
        return max(0, min(self.count() - 1, row))

    def mousePressEvent(self, ev):
        super().mousePressEvent(ev)
        if ev.button() == Qt.MouseButton.LeftButton:
            row = self._row_at(ev.position().y())
            if 0 <= row < self.count():
                self._drag_row = row
                self._press_pos = ev.position().toPoint()

    def mouseMoveEvent(self, ev):
        if self._drag_row < 0 or not (ev.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(ev)
            return
        pos = ev.position().toPoint()
        if (pos - self._press_pos).manhattanLength() <= 6:
            return          # 没拖出阈值：可能是普通点击，先别动顺序
        target = self._row_at(pos.y())
        if target != self._drag_row:
            order = self.ordered_values()
            order.insert(target, order.pop(self._drag_row))
            if self.apply_order(order):
                self._drag_row = target
                self.setCurrentRow(target)
                self.reordered.emit()
        ev.accept()

    def mouseReleaseEvent(self, ev):
        if self._drag_row >= 0:
            self._drag_row = -1
            self._press_pos = None
            ev.accept()
            return
        super().mouseReleaseEvent(ev)


class SpecOrderDialog(QDialog):
    """「自动」优先级排序对话框：按住条目上下拖动，或用 ▲▼ / Alt+↑↓ 微调。"""

    def __init__(self, parent, rows, current_order=(), default_order=()):
        """rows: [(显示文本, data)]；current_order: data 的当前顺序；default_order: 恢复默认用。"""
        super().__init__(parent)
        self.setWindowTitle(t('「自动」的优先级'))
        self.resize(460, 520)
        self._default = list(default_order or [d for _txt, d in rows])
        by_data = {d: txt for txt, d in rows}
        order = [d for d in (current_order or self._default) if d in by_data]
        order += [d for d in self._default if d not in order]

        lay = QVBoxLayout(self)
        tip = QLabel(t('选「自动」时从上往下依次尝试，用第一个当前可用的方式。\n'
                       '按住条目上下拖动，或选中后用 ▲▼（Alt+↑ / Alt+↓）移动。'))
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.list = _ReorderList()
        for d in order:
            self.list.add_row(by_data[d], d)
        self.list.setCurrentRow(0)
        lay.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.btn_up = QPushButton("▲")
        self.btn_down = QPushButton("▼")
        self.btn_reset = QPushButton(t('恢复默认顺序'))
        self.btn_up.setToolTip(t('上移（Alt+↑）'))
        self.btn_down.setToolTip(t('下移（Alt+↓）'))
        for b in (self.btn_up, self.btn_down, self.btn_reset):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down.clicked.connect(lambda: self._move(1))
        self.btn_reset.clicked.connect(self._reset)
        # 键盘也能调：Alt+↑ / Alt+↓（单按 ↑↓ 留给列表自己的光标）
        self._sc_up = QShortcut(QKeySequence("Alt+Up"), self)
        self._sc_up.activated.connect(lambda: self._move(-1))
        self._sc_down = QShortcut(QKeySequence("Alt+Down"), self)
        self._sc_down.activated.connect(lambda: self._move(1))

    def _move(self, delta):
        row = self.list.currentRow()
        dst = row + delta
        if row < 0 or dst < 0 or dst >= self.list.count():
            return
        order = self.list.ordered_values()
        order.insert(dst, order.pop(row))
        self.list.apply_order(order)
        self.list.setCurrentRow(dst)

    def _reset(self):
        self.list.apply_order(list(self._default))
        self.list.setCurrentRow(0)

    def ordered_values(self):
        return self.list.ordered_values()


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
