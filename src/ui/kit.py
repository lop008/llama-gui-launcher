# -*- coding: utf-8 -*-
"""轻量 UI 组件库：卡片、分段控件、状态徽章、统计块。

只依赖 PyQt6，不引入第三方主题框架。所有颜色都走 QSS 的 objectName / 动态属性，
切换主题时无需重建控件。
"""
from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QSizePolicy, QTreeView, QVBoxLayout, QWidget,
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


class ColumnResizer(QObject):
    """让表格 / 文件树的每一列都能手动拖动，同时默认不留白。

    Qt 原生两选一：`QHeaderView.Stretch` 会自动填满但那一列拖不动，
    `Interactive` 能拖但列宽总和小于视口时右侧留白。这里取两者好处：
    全部列用 Interactive，视口变化时把多余宽度补给指定列；
    用户一旦真的拖过某一列就停止自动补宽，避免「刚拖宽就被弹回去」。

    用法（QTableWidget / QTreeWidget 通用）：
        ColumnResizer(self.table, [42, 320, 100, 96, 92, 110, 300], fill_col=1)
    """

    def __init__(self, view, widths, fill_col=0, min_width=60):
        super().__init__(view)          # 随父控件销毁，无需手动清理
        self.view = view
        self.fill_col = fill_col
        self.min_width = min_width
        self._filling = False
        self._touched_cols = set()
        # QTableWidget 用 horizontalHeader()，QTreeWidget 只有 header()
        self.hdr = view.header() if isinstance(view, QTreeView) else view.horizontalHeader()
        hdr = self.hdr
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setSectionsMovable(True)
        hdr.setStretchLastSection(False)
        hdr.setMinimumSectionSize(min_width)
        for col, w in enumerate(widths):
            view.setColumnWidth(col, w)
        hdr.sectionResized.connect(self._on_resized)
        view.installEventFilter(self)

    # -- 内部 ---------------------------------------------------------
    def _on_resized(self, col, _old, new):
        # 只有用户拖了「补宽那一列」才锁定自动补宽。
        # 之前是拖任意一列就永久停止补宽：那样窗口最大化 / 拉宽后右侧会留一大块空白，
        # 用户以为表格不能铺满（把文件名拉宽 ≠ 不想要表格铺满）。
        if not self._filling and new > 0 and col == self.fill_col:
            self._touched_cols.add(col)

    def eventFilter(self, obj, event):
        if (obj is self.view and event.type() == QEvent.Type.Resize
                and self.fill_col not in self._touched_cols):
            self.refill()
        return False

    def refill(self):
        """把视口剩余宽度补给 fill_col（列数不够 / 已被用户拖动时什么都不做）。"""
        if self._filling:          # 防重入：补宽过程中若再收到 Resize 事件直接忽略
            return
        hdr = self.hdr
        cols = hdr.count()
        if cols <= self.fill_col:
            return
        # viewport() 已排除滚动条，再减左右边框，避免补宽后反而冒出横向滚动条
        avail = self.view.viewport().width() - 2 * self.view.frameWidth() - 1
        used = sum(hdr.sectionSize(c) for c in range(cols) if c != self.fill_col)
        want = avail - used
        if want < self.min_width:      # 窗口太窄：让横向滚动条接手，不压缩其他列
            return
        if hdr.sectionSize(self.fill_col) == want:
            return
        self._filling = True
        try:
            hdr.resizeSection(self.fill_col, want)
        finally:
            self._filling = False

    def set_column_width(self, col, width):
        """程序调整某列宽度（例如按按钮 sizeHint 加宽操作列），补宽用当前 fill_col。"""
        hdr = self.hdr
        if 0 <= col < hdr.count():
            self._filling = True
            try:
                hdr.resizeSection(col, max(self.min_width, width))
            finally:
                self._filling = False
            self.refill()


class CheckComboBox(QComboBox):
    """多选下拉框：下拉里每行一个复选框，勾选后下拉不收起，可以一口气勾好几个。

    为什么不用原生 QComboBox：它只能单选。更新页要按「推理后端」筛（CUDA / Vulkan /
    ROCm / SYCL / OpenVINO…），而官方一个版本同时发 6~7 种包，单选表达不了
    「CUDA 和 Vulkan 都想看」。这里同维度内是「或」，勾选集合对外用 `checked_keys()`。
    """

    changed = pyqtSignal()                     # 勾选集合变了（用户操作才会发）

    def __init__(self, all_text=None, parent=None):
        super().__init__(parent)
        self._all_text = all_text or t('全部')
        self._keys = []
        # 用「只读的可编辑框」显示当前选择：不可编辑的下拉框只能显示被选中那一项的文字，
        # 而多选框没有「选中项」的概念（也不能靠 setItemText 改文案，会踩 Qt 的坑）。
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setCursor(Qt.CursorShape.PointingHandCursor)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.view().pressed.connect(self._on_pressed)

    # -- 对外 ---------------------------------------------------------
    def set_options(self, options, keep=None):
        """重填选项 `[(key, 显示名), …]`；`keep` 为 None 时自动保留仍存在的旧勾选。"""
        chosen = set(self.checked_keys() if keep is None else keep)
        self.blockSignals(True)
        self.clear()
        self._keys = []
        for key, label in options:
            self.addItem(label, key)
            self._keys.append(key)
            item = self.model().item(self.count() - 1)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in chosen
                               else Qt.CheckState.Unchecked)
        self.blockSignals(False)
        self._sync_text()

    def checked_keys(self):
        """当前勾选的 key 列表（顺序与选项顺序一致，空列表 = 一个都没勾 = 不限）。"""
        model = self.model()
        return [k for i, k in enumerate(self._keys)
                if model is not None and model.item(i) is not None
                and model.item(i).checkState() == Qt.CheckState.Checked]

    def set_checked(self, keys):
        chosen = set(keys)
        model = self.model()
        for i, key in enumerate(self._keys):
            item = model.item(i) if model else None
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked if key in chosen
                                   else Qt.CheckState.Unchecked)
        self._sync_text()

    # -- 内部 ---------------------------------------------------------
    def _on_pressed(self, index):
        """点一行 = 切换它的勾选（原生行为是选中并收起下拉，多选必须自己接管）。"""
        if not index.isValid():
            return
        item = self.model().item(index.row()) if self.model() else None
        if item is None:
            return
        item.setCheckState(Qt.CheckState.Unchecked
                           if item.checkState() == Qt.CheckState.Checked
                           else Qt.CheckState.Checked)
        self._sync_text()
        self.changed.emit()
        self.showPopup()          # 保持展开，方便连续勾选

    def _sync_text(self):
        sel = self.checked_keys()
        if not sel or len(sel) == len(self._keys):
            text = self._all_text
        elif len(sel) == 1:
            text = self.itemText(self._keys.index(sel[0]))
        else:
            text = '{} {} {}'.format(self.itemText(self._keys.index(sel[0])), t('等'),
                                     len(sel))
        self.lineEdit().setText(text)
