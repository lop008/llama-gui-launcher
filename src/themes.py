"""配色方案（主题）集中定义。

所有主题共用同一套尺寸度量（边框宽度、内边距、圆角、字号），仅颜色不同，
因此切换主题不会改变窗口的布局大小。

用法：
    from .themes import THEMES, build_qss
    app.setStyleSheet(build_qss("dark"))
"""
from string import Template

# 深色（默认）
_DARK = {
    "win_bg": "#070d1a", "text": "#bfe6ff",
    "field_bg": "#0c1730", "field_fg": "#d9f4ff", "field_border": "#1d4f7a", "sel_bg": "#0e5a7d",
    "focus_border": "#35e0ff", "hover_border": "#2b7fb0",
    "btn_bg1": "#12264a", "btn_bg2": "#0b1a33", "btn_fg": "#9fe8ff", "btn_border": "#1d6f9e",
    "btn_hover_bg1": "#173a66", "btn_hover_bg2": "#10244a", "btn_hover_fg": "#e8fbff",
    "btn_pressed": "#0f2f58",
    "btn_dis_fg": "#3f5f78", "btn_dis_border": "#1a354a", "btn_dis_bg": "#0c1322",
    "pop_bg": "#0c1730", "pop_sel": "#10537a",
    "head_bg": "#0e2040", "head_fg": "#4fd8ff", "head_border": "#1a4a70",
    "mb_bg": "#070d1a", "mb_fg": "#bfe6ff", "mb_border": "#142c4a",
    "mb_sel_bg": "#12264a", "mb_sel_fg": "#7df9ff",
    "menu_bg": "#0c1730", "menu_fg": "#d9f4ff", "menu_border": "#1d4f7a",
    "menu_sel_bg": "#10537a", "menu_sel_fg": "#ffffff",
    "sb_bg": "#050a14", "sb_fg": "#7df9ff", "sb_border": "#16325a",
    "tab_pane_border": "#16325a", "tab_bg": "#0c1730", "tab_fg": "#6fa8c8",
    "tab_border": "#16325a", "tab_sel_bg": "#10304f", "tab_sel_fg": "#7df9ff",
    "tab_hover_fg": "#c8f4ff",
    "scroll_bg": "#070d1a", "scroll_handle": "#1d4f7a", "scroll_handle_hover": "#2b7fb0",
    "tip_bg": "#0c1730", "tip_fg": "#e8fbff", "tip_border": "#35e0ff",
    "msg_bg": "#0a1220",
    "gb_border": "#16325a", "gb_bg1": "#0a1322", "gb_bg2": "#070d1a", "gb_title": "#4fd8ff",
    "cb_border": "#1d6f9e", "cb_bg": "#0c1730", "cb_checked_bg": "#0e7fa8", "cb_checked_border": "#35e0ff",
    "table_sel_bg": "#0e5a7d", "table_sel_fg": "#ffffff",
    "spin_btn_bg": "#12264a", "spin_btn_border": "#1d6f9e",
    "spin_arrow": "#9fe8ff", "spin_arrow_dis": "#3f5f78",
}

# 浅色：边框刻意加深，保证分隔线清晰可辨
_LIGHT = {
    "win_bg": "#f4f6f9", "text": "#1f2d3d",
    "field_bg": "#ffffff", "field_fg": "#1f2d3d", "field_border": "#9fb0c0", "sel_bg": "#cfe3ff",
    "focus_border": "#2f7fd6", "hover_border": "#6f9fd0",
    "btn_bg1": "#ffffff", "btn_bg2": "#e6edf5", "btn_fg": "#1f4e79", "btn_border": "#9fb0c0",
    "btn_hover_bg1": "#eaf3ff", "btn_hover_bg2": "#d3e4f7", "btn_hover_fg": "#0b3d66",
    "btn_pressed": "#c6d9ee",
    "btn_dis_fg": "#9aa6b2", "btn_dis_border": "#ccd5de", "btn_dis_bg": "#eef1f4",
    "pop_bg": "#ffffff", "pop_sel": "#d6e6f7",
    "head_bg": "#d7e2ee", "head_fg": "#1f4e79", "head_border": "#9fb0c0",
    "mb_bg": "#eaeff5", "mb_fg": "#1f2d3d", "mb_border": "#b6c2ce",
    "mb_sel_bg": "#d6e6f7", "mb_sel_fg": "#0b3d66",
    "menu_bg": "#ffffff", "menu_fg": "#1f2d3d", "menu_border": "#9fb0c0",
    "menu_sel_bg": "#d6e6f7", "menu_sel_fg": "#0b3d66",
    "sb_bg": "#e2e8ef", "sb_fg": "#1f4e79", "sb_border": "#b6c2ce",
    "tab_pane_border": "#9fb0c0", "tab_bg": "#e6edf5", "tab_fg": "#52606d",
    "tab_border": "#9fb0c0", "tab_sel_bg": "#ffffff", "tab_sel_fg": "#1f4e79",
    "tab_hover_fg": "#0b3d66",
    "scroll_bg": "#eef1f4", "scroll_handle": "#9fb0c0", "scroll_handle_hover": "#6f8aa6",
    "tip_bg": "#ffffe0", "tip_fg": "#1f2d3d", "tip_border": "#9fb0c0",
    "msg_bg": "#ffffff",
    "gb_border": "#9fb0c0", "gb_bg1": "#ffffff", "gb_bg2": "#f4f6f9", "gb_title": "#1f4e79",
    "cb_border": "#9fb0c0", "cb_bg": "#ffffff", "cb_checked_bg": "#2f7fd6", "cb_checked_border": "#1f6fbf",
    "table_sel_bg": "#cfe3ff", "table_sel_fg": "#10335a",
    "spin_btn_bg": "#e6edf5", "spin_btn_border": "#9fb0c0",
    "spin_arrow": "#1f4e79", "spin_arrow_dis": "#9aa6b2",
}

# 橙色（暖色深底）
_ORANGE = {
    "win_bg": "#1a1008", "text": "#ffd9b0",
    "field_bg": "#2a1a0c", "field_fg": "#ffe8cf", "field_border": "#7a4a1d", "sel_bg": "#a05a12",
    "focus_border": "#ff9f40", "hover_border": "#c47a2b",
    "btn_bg1": "#3a2410", "btn_bg2": "#241407", "btn_fg": "#ffcf9a", "btn_border": "#a05a12",
    "btn_hover_bg1": "#5a3616", "btn_hover_bg2": "#3a2410", "btn_hover_fg": "#fff0dd",
    "btn_pressed": "#7a4a1d",
    "btn_dis_fg": "#7a5a3a", "btn_dis_border": "#3a2a1a", "btn_dis_bg": "#1e1208",
    "pop_bg": "#2a1a0c", "pop_sel": "#a05a12",
    "head_bg": "#3a2410", "head_fg": "#ffb066", "head_border": "#7a4a1d",
    "mb_bg": "#1a1008", "mb_fg": "#ffd9b0", "mb_border": "#4a2e12",
    "mb_sel_bg": "#3a2410", "mb_sel_fg": "#ffcf9a",
    "menu_bg": "#2a1a0c", "menu_fg": "#ffe8cf", "menu_border": "#7a4a1d",
    "menu_sel_bg": "#a05a12", "menu_sel_fg": "#ffffff",
    "sb_bg": "#120a04", "sb_fg": "#ffb066", "sb_border": "#4a2e12",
    "tab_pane_border": "#4a2e12", "tab_bg": "#2a1a0c", "tab_fg": "#c89a6a",
    "tab_border": "#4a2e12", "tab_sel_bg": "#5a3616", "tab_sel_fg": "#ffcf9a",
    "tab_hover_fg": "#ffe0b8",
    "scroll_bg": "#1a1008", "scroll_handle": "#7a4a1d", "scroll_handle_hover": "#a05a12",
    "tip_bg": "#2a1a0c", "tip_fg": "#ffe8cf", "tip_border": "#ff9f40",
    "msg_bg": "#241407",
    "gb_border": "#4a2e12", "gb_bg1": "#241407", "gb_bg2": "#1a1008", "gb_title": "#ffb066",
    "cb_border": "#7a4a1d", "cb_bg": "#2a1a0c", "cb_checked_bg": "#d97a1a", "cb_checked_border": "#ff9f40",
    "table_sel_bg": "#a05a12", "table_sel_fg": "#ffffff",
    "spin_btn_bg": "#3a2410", "spin_btn_border": "#7a4a1d",
    "spin_arrow": "#ffcf9a", "spin_arrow_dis": "#7a5a3a",
}

# 绿色（深绿底）
_GREEN = {
    "win_bg": "#07160f", "text": "#bdf0d2",
    "field_bg": "#0c2418", "field_fg": "#d8ffe8", "field_border": "#1d6b45", "sel_bg": "#128a56",
    "focus_border": "#35e08a", "hover_border": "#2ba06a",
    "btn_bg1": "#123a28", "btn_bg2": "#0b2418", "btn_fg": "#9fe8c0", "btn_border": "#1d8a5a",
    "btn_hover_bg1": "#175a3a", "btn_hover_bg2": "#102a1e", "btn_hover_fg": "#e8fff2",
    "btn_pressed": "#0f4a30",
    "btn_dis_fg": "#3f7a5a", "btn_dis_border": "#1a4a35", "btn_dis_bg": "#0c1a12",
    "pop_bg": "#0c2418", "pop_sel": "#128a56",
    "head_bg": "#0e3a26", "head_fg": "#4fffa0", "head_border": "#1a6b45",
    "mb_bg": "#07160f", "mb_fg": "#bdf0d2", "mb_border": "#143a28",
    "mb_sel_bg": "#123a28", "mb_sel_fg": "#7dffb0",
    "menu_bg": "#0c2418", "menu_fg": "#d8ffe8", "menu_border": "#1d6b45",
    "menu_sel_bg": "#128a56", "menu_sel_fg": "#ffffff",
    "sb_bg": "#04120b", "sb_fg": "#4fffa0", "sb_border": "#143a28",
    "tab_pane_border": "#143a28", "tab_bg": "#0c2418", "tab_fg": "#6fa88a",
    "tab_border": "#143a28", "tab_sel_bg": "#103a28", "tab_sel_fg": "#7dffb0",
    "tab_hover_fg": "#c8ffe0",
    "scroll_bg": "#07160f", "scroll_handle": "#1d6b45", "scroll_handle_hover": "#2ba06a",
    "tip_bg": "#0c2418", "tip_fg": "#e8fff2", "tip_border": "#35e08a",
    "msg_bg": "#0b1a12",
    "gb_border": "#143a28", "gb_bg1": "#0b1a12", "gb_bg2": "#07160f", "gb_title": "#4fffa0",
    "cb_border": "#1d6b45", "cb_bg": "#0c2418", "cb_checked_bg": "#0e9a5a", "cb_checked_border": "#35e08a",
    "table_sel_bg": "#128a56", "table_sel_fg": "#ffffff",
    "spin_btn_bg": "#123a28", "spin_btn_border": "#1d6b45",
    "spin_arrow": "#9fe8c0", "spin_arrow_dis": "#3f7a5a",
}

# 灰色（中性深灰）
_GRAY = {
    "win_bg": "#12151a", "text": "#d0d6de",
    "field_bg": "#1c2128", "field_fg": "#e6ebf1", "field_border": "#3a4450", "sel_bg": "#4a5a6d",
    "focus_border": "#8fb0d0", "hover_border": "#5a6a7d",
    "btn_bg1": "#2a313a", "btn_bg2": "#1a1f26", "btn_fg": "#c8d2de", "btn_border": "#4a5563",
    "btn_hover_bg1": "#3a4450", "btn_hover_bg2": "#232a33", "btn_hover_fg": "#f0f4f8",
    "btn_pressed": "#333c47",
    "btn_dis_fg": "#5a6470", "btn_dis_border": "#2a3038", "btn_dis_bg": "#171b21",
    "pop_bg": "#1c2128", "pop_sel": "#4a5a6d",
    "head_bg": "#262d36", "head_fg": "#a8c4e0", "head_border": "#3a4450",
    "mb_bg": "#12151a", "mb_fg": "#d0d6de", "mb_border": "#2a313a",
    "mb_sel_bg": "#2a313a", "mb_sel_fg": "#c8d2de",
    "menu_bg": "#1c2128", "menu_fg": "#e6ebf1", "menu_border": "#3a4450",
    "menu_sel_bg": "#4a5a6d", "menu_sel_fg": "#ffffff",
    "sb_bg": "#0d1013", "sb_fg": "#a8c4e0", "sb_border": "#2a313a",
    "tab_pane_border": "#2a313a", "tab_bg": "#1c2128", "tab_fg": "#7a8896",
    "tab_border": "#2a313a", "tab_sel_bg": "#2f3742", "tab_sel_fg": "#c8d2de",
    "tab_hover_fg": "#e6ebf1",
    "scroll_bg": "#12151a", "scroll_handle": "#3a4450", "scroll_handle_hover": "#5a6a7d",
    "tip_bg": "#1c2128", "tip_fg": "#f0f4f8", "tip_border": "#8fb0d0",
    "msg_bg": "#171b21",
    "gb_border": "#2a313a", "gb_bg1": "#171b21", "gb_bg2": "#12151a", "gb_title": "#a8c4e0",
    "cb_border": "#3a4450", "cb_bg": "#1c2128", "cb_checked_bg": "#4a6a8a", "cb_checked_border": "#8fb0d0",
    "table_sel_bg": "#4a5a6d", "table_sel_fg": "#ffffff",
    "spin_btn_bg": "#2a313a", "spin_btn_border": "#3a4450",
    "spin_arrow": "#c8d2de", "spin_arrow_dis": "#5a6470",
}

# 棕色（深棕底）
_BROWN = {
    "win_bg": "#17110b", "text": "#e0cdb8",
    "field_bg": "#241a12", "field_fg": "#f0e2d2", "field_border": "#5a4030", "sel_bg": "#7a5238",
    "focus_border": "#c89a6a", "hover_border": "#8a6a4a",
    "btn_bg1": "#33251a", "btn_bg2": "#1f160f", "btn_fg": "#d8c0a0", "btn_border": "#6a4a34",
    "btn_hover_bg1": "#4a3624", "btn_hover_bg2": "#2a1e14", "btn_hover_fg": "#f5ead8",
    "btn_pressed": "#3f2e1f",
    "btn_dis_fg": "#6a5642", "btn_dis_border": "#33251a", "btn_dis_bg": "#1a130c",
    "pop_bg": "#241a12", "pop_sel": "#7a5238",
    "head_bg": "#2e2116", "head_fg": "#d8b088", "head_border": "#5a4030",
    "mb_bg": "#17110b", "mb_fg": "#e0cdb8", "mb_border": "#33251a",
    "mb_sel_bg": "#33251a", "mb_sel_fg": "#d8c0a0",
    "menu_bg": "#241a12", "menu_fg": "#f0e2d2", "menu_border": "#5a4030",
    "menu_sel_bg": "#7a5238", "menu_sel_fg": "#ffffff",
    "sb_bg": "#0f0a06", "sb_fg": "#d8b088", "sb_border": "#33251a",
    "tab_pane_border": "#33251a", "tab_bg": "#241a12", "tab_fg": "#8a7560",
    "tab_border": "#33251a", "tab_sel_bg": "#3a2a1c", "tab_sel_fg": "#d8c0a0",
    "tab_hover_fg": "#f0e2d2",
    "scroll_bg": "#17110b", "scroll_handle": "#5a4030", "scroll_handle_hover": "#8a6a4a",
    "tip_bg": "#241a12", "tip_fg": "#f5ead8", "tip_border": "#c89a6a",
    "msg_bg": "#1a130c",
    "gb_border": "#33251a", "gb_bg1": "#1a130c", "gb_bg2": "#17110b", "gb_title": "#d8b088",
    "cb_border": "#5a4030", "cb_bg": "#241a12", "cb_checked_bg": "#8a5a34", "cb_checked_border": "#c89a6a",
    "table_sel_bg": "#7a5238", "table_sel_fg": "#ffffff",
    "spin_btn_bg": "#33251a", "spin_btn_border": "#5a4030",
    "spin_arrow": "#d8c0a0", "spin_arrow_dis": "#6a5642",
}

# 顺序即菜单顺序；键名用于 config.json 的 "theme" 字段
THEMES = {
    "dark": {"name": "深色", "icon": "🌙", "colors": _DARK},
    "light": {"name": "浅色", "icon": "☀️", "colors": _LIGHT},
    "orange": {"name": "橙色", "icon": "🟠", "colors": _ORANGE},
    "green": {"name": "绿色", "icon": "🟢", "colors": _GREEN},
    "gray": {"name": "灰色", "icon": "⚪", "colors": _GRAY},
    "brown": {"name": "棕色", "icon": "🟤", "colors": _BROWN},
}

# 所有主题共用同一模板：仅 $颜色 变化，尺寸/字号完全一致 → 切换不改布局
_QSS_TEMPLATE = Template("""
QMainWindow, QDialog { background-color: $win_bg; }
QWidget { background-color: $win_bg; color: $text; font-size: 13px; }
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTableWidget {
    background-color: $field_bg; color: $field_fg;
    border: 1px solid $field_border; border-radius: 4px;
    selection-background-color: $sel_bg; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid $focus_border; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: $hover_border; }
QPushButton {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $btn_bg1, stop:1 $btn_bg2);
    color: $btn_fg; border: 1px solid $btn_border; border-radius: 4px; padding: 5px 12px; }
QPushButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $btn_hover_bg1, stop:1 $btn_hover_bg2);
    border-color: $focus_border; color: $btn_hover_fg; }
QPushButton:pressed { background-color: $btn_pressed; }
QPushButton:disabled { color: $btn_dis_fg; border-color: $btn_dis_border; background-color: $btn_dis_bg; }
QComboBox QAbstractItemView {
    background-color: $pop_bg; color: $field_fg; border: 1px solid $btn_border;
    selection-background-color: $pop_sel; }
QHeaderView::section {
    background-color: $head_bg; color: $head_fg;
    border: 1px solid $head_border; padding: 4px 6px; }
QMenuBar { background-color: $mb_bg; color: $mb_fg; border-bottom: 1px solid $mb_border; }
QMenuBar::item:selected { background-color: $mb_sel_bg; color: $mb_sel_fg; }
QMenu { background-color: $menu_bg; color: $menu_fg; border: 1px solid $menu_border; }
QMenu::item:selected { background-color: $menu_sel_bg; color: $menu_sel_fg; }
QToolButton { color: $text; }
QStatusBar { background-color: $sb_bg; color: $sb_fg; border-top: 1px solid $sb_border; }
QStatusBar::item { border: none; }
QTabWidget::pane { border: 1px solid $tab_pane_border; }
QTabBar::tab {
    background-color: $tab_bg; color: $tab_fg; padding: 8px 18px;
    font-size: 15px; font-weight: bold;
    border: 1px solid $tab_border; border-bottom: none;
    border-top-left-radius: 4px; border-top-right-radius: 4px; }
QTabBar::tab:selected { background-color: $tab_sel_bg; color: $tab_sel_fg; }
QTabBar::tab:hover { color: $tab_hover_fg; }
QScrollBar:vertical { background: $scroll_bg; width: 12px; }
QScrollBar::handle:vertical { background: $scroll_handle; min-height: 24px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: $scroll_handle_hover; }
QScrollBar:horizontal { background: $scroll_bg; height: 12px; }
QScrollBar::handle:horizontal { background: $scroll_handle; min-width: 24px; border-radius: 4px; }
QScrollBar::handle:horizontal:hover { background: $scroll_handle_hover; }
QScrollArea { border: none; }
QToolTip { background-color: $tip_bg; color: $tip_fg; border: 1px solid $tip_border; padding: 4px; }
QMessageBox { background-color: $msg_bg; }
QGroupBox {
    border: 1px solid $gb_border; border-radius: 6px; margin-top: 12px;
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $gb_bg1, stop:1 $gb_bg2); }
QGroupBox::title {
    color: $gb_title; subcontrol-origin: margin; left: 10px; padding: 0 6px;
    font-size: 15px; font-weight: bold; }
QLabel { color: $text; }
QCheckBox { color: $text; spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid $cb_border; border-radius: 3px; background-color: $cb_bg; }
QCheckBox::indicator:checked { background-color: $cb_checked_bg; border-color: $cb_checked_border; }
QTableWidget::item:selected, QTableView::item:selected {
    background-color: $table_sel_bg; color: $table_sel_fg; }
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    width: 16px; background-color: $spin_btn_bg; border: 1px solid $spin_btn_border; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-bottom: 5px solid $spin_arrow; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid $spin_arrow; }
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled { border-bottom-color: $spin_arrow_dis; }
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled { border-top-color: $spin_arrow_dis; }
""")


def build_qss(key):
    """按主题键生成完整样式表；未知键回退到深色。"""
    theme = THEMES.get(key) or THEMES["dark"]
    return _QSS_TEMPLATE.substitute(**theme["colors"])
