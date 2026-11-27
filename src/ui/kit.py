# -*- coding: utf-8 -*-
"""轻量 UI 组件库：卡片、分段控件、状态徽章、统计块。

只依赖 PyQt6，不引入第三方主题框架。所有颜色都走 QSS 的 objectName / 动态属性，
切换主题时无需重建控件。
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from ..i18n import t


def repolish(widget):
    """动态属性变化后让 QSS 立即重新生效。"""
    try:
        st = widget.style()
        st.unpolish(widget)
        st.polish(widget)
        widget.update()
    except Exception:
        pass


class Card(QFrame):
    """带圆角、细边框、轻微渐变的容器卡片。"""

    def __init__(self, parent=None, *, padding=12, spacing=8):
        super().__init__(parent)
        self.setObjectName("Card")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(padding, padding, padding, padding)
        self._lay.setSpacing(spacing)

    def layout(self):
        return self._lay

    def add(self, widget, stretch=0):
        self._lay.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout, stretch=0):
        self._lay.addLayout(layout, stretch)
        return layout


class SectionHeader(QWidget):
    """标题 + 副标题 + 右侧操作区。"""

    def __init__(self, title="", subtitle="", parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(1)
        self.title = QLabel(title)
        self.title.setObjectName("SectionTitle")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("Muted")
        self.subtitle.setWordWrap(True)
        col.addWidget(self.title)
        if subtitle:
            col.addWidget(self.subtitle)
        row.addLayout(col, 1)
        self.actions = QWidget()
        self._act = QHBoxLayout(self.actions)
        self._act.setContentsMargins(0, 0, 0, 0)
        self._act.setSpacing(6)
        row.addWidget(self.actions, 0)

    def set_title(self, text):
        self.title.setText(text)

    def set_subtitle(self, text):
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))

    def add_action(self, widget):
        self._act.addWidget(widget)
        return widget

    def add_stretch(self):
        self._act.addStretch(1)


class Badge(QLabel):
    """状态徽章：ok / warn / err / info / neutral。"""

    def __init__(self, text="", tone="neutral", parent=None):
        super().__init__(text, parent)
        self.setObjectName("Badge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.set_tone(tone)

    def set_tone(self, tone):
        self.setProperty("tone", str(tone or "neutral"))
        repolish(self)

    def set_status(self, text, tone="neutral"):
        self.setText(text)
        self.set_tone(tone)


class SegmentedControl(QWidget):
    """分段控件：一排可复选按钮，选中项有明确高亮，替代不可见的 QRadioButton。"""

    changed = pyqtSignal(str)

    def __init__(self, options=(), parent=None):
        """options: [(value, label)]"""
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        self._current = ""
        for value, label in options:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("variant", "segment")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, v=value: self.set_value(v, emit=True))
            self._group.addButton(btn)
            self._buttons[value] = btn
            row.addWidget(btn)
        if options:
            self.set_value(options[0][0])

    def set_value(self, value, emit=False):
        if value not in self._buttons:
            return
        self._current = value
        for v, b in self._buttons.items():
            b.setChecked(v == value)
        if emit:
            self.changed.emit(value)

    def value(self):
        return self._current

    def button(self, value):
        return self._buttons.get(value)


class StatCard(Card):
    """小统计块：标题 / 大数字 / 说明。"""

    def __init__(self, label="", value="—", hint="", parent=None):
        super().__init__(parent, padding=10, spacing=2)
        self._label = QLabel(label)
        self._label.setObjectName("Muted")
        self._value = QLabel(value)
        self._value.setObjectName("StatValue")
        self._hint = QLabel(hint)
        self._hint.setObjectName("Muted")
        self._hint.setWordWrap(True)
        self.add(self._label)
        self.add(self._value)
        self.add(self._hint)

    def set_value(self, value):
        self._value.setText(str(value))

    def set_hint(self, hint):
        self._hint.setText(hint)

    def set_label(self, text):
        self._label.setText(text)


class EmptyState(QWidget):
    """空状态：居中图标 + 标题 + 说明。"""

    def __init__(self, title="", subtitle="", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(6)
        self._icon = QLabel("◇")
        self._icon.setObjectName("EmptyIcon")
        self._icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title = QLabel(title)
        self._title.setObjectName("EmptyTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle = QLabel(subtitle)
        self._subtitle.setObjectName("Muted")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setWordWrap(True)
        lay.addStretch(1)
        lay.addWidget(self._icon)
        lay.addWidget(self._title)
        lay.addWidget(self._subtitle)
        lay.addStretch(1)


def hline():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setObjectName("HLine")
    return line
