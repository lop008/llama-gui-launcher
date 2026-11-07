"""托盘悬浮小窗（悬浮胶囊 + 悬停展开卡片）。

主窗口点 X 缩到托盘后，屏幕右下角常驻一个小胶囊：状态圆点 + 实时 tok/s + API 圆点。
鼠标停留（或单击）展开数据卡片：输出速度 / CPU / 内存 / GPU 负载 / 显存 / API 接入数 / 模型名，
鼠标移开自动收回；双击返回主界面；可拖动（位置记忆到配置）；「✕」隐藏（可在高级参数重新开启）。

控件本身不采集数据：由 MainWindow 把 SystemMonitor 的信号转发到 set_* 方法。
配色跟随 themes.py 当前主题（apply_theme 传入主题色字典）。
"""
from PyQt6.QtCore import QPoint, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .themes import THEMES
from .i18n import t

_IDLE_TEXT = "—"
_COLLAPSE_MS = 5000   # 未点击（未钉住）时，鼠标离开后 5 秒收起
_DRAG_PX = 4          # 超过该位移按拖动处理（不再视为单击）


def _c(theme, key, fallback):
    try:
        QColor(theme.get(key, fallback))
        return theme.get(key, fallback)
    except Exception:
        return fallback


class HoverPill(QWidget):
    """托盘悬浮胶囊：收起=迷你胶囊，展开=数据卡片。"""

    open_main = pyqtSignal()        # 双击 / 菜单「打开主界面」
    start_requested = pyqtSignal()  # 菜单「启动模型」
    stop_requested = pyqtSignal()   # 菜单「停止模型」
    quit_requested = pyqtSignal()   # 菜单「退出」
    hide_requested = pyqtSignal()   # 菜单「隐藏图标」（本次最小化内不再显示）

    def __init__(self, cfg, theme_key="dark", icon=None, save_pos=None,
                 on_hidden=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._theme_key = theme_key if theme_key in THEMES else "dark"
        self._save_pos_cb = save_pos
        self._on_hidden_cb = on_hidden
        self._expanded = False
        self._pinned = False
        self._drag_pos = None
        self._moved = False
        self._running = False
        self._speed = 0.0
        self._api_busy = 0
        self._model = ""

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self._logo = QLabel()
        self._logo.setObjectName("ppLogo")
        self._logo.setFixedSize(18, 18)
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if icon is not None:
            try:
                pm = icon.pixmap(18, 18) if hasattr(icon, "pixmap") else icon
                if pm is not None and not pm.isNull():
                    self._logo.setPixmap(pm)
            except Exception:
                pass

        self._name_lbl = QLabel("LLama.cpp")
        self._name_lbl.setObjectName("ppName")

        self._dot = QLabel()
        self._dot.setObjectName("ppDot")
        self._dot.setFixedSize(10, 10)
        self._speed_lbl = QLabel("0.0 tok/s")
        self._speed_lbl.setObjectName("ppSpeed")
        self._api_lbl = QLabel()
        self._api_lbl.setObjectName("ppApi")
        self._api_lbl.setVisible(False)
        self._model_lbl = QLabel(t('未运行'))
        self._model_lbl.setObjectName("ppModel")
        self._model_lbl.setVisible(False)
        self._chev = QLabel("▴")
        self._chev.setObjectName("ppChev")
        self._btn_close = QPushButton("✕")
        self._btn_close.setObjectName("ppClose")
        self._btn_close.setFixedSize(18, 18)
        self._btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_close.setToolTip(t('隐藏悬浮窗（可在「高级参数 → 缩到托盘时显示悬浮小窗」重新开启）'))
        self._btn_close.setVisible(False)
        self._btn_close.clicked.connect(self._on_close_clicked)

        self._pill = QFrame()
        self._pill.setObjectName("ppPill")
        self._pill.setFixedHeight(30)
        ph = QHBoxLayout(self._pill)
        ph.setContentsMargins(8, 0, 8, 0)
        ph.setSpacing(6)
        ph.addWidget(self._logo)
        ph.addWidget(self._name_lbl)
        ph.addWidget(self._speed_lbl)
        ph.addStretch(1)
        ph.addWidget(self._api_lbl)
        ph.addWidget(self._dot)
        ph.addWidget(self._chev)
        ph.addWidget(self._btn_close)

        # 展开卡片：6 个数据块（2 列 × 3 行）+ 模型名行
        # 展开卡片：独立面板控件（整体显隐，避免逐子控件显隐被重设父级清除）
        self._card_w = QWidget()
        self._card_w.setObjectName("ppCard")
        self._card_w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._card = QGridLayout(self._card_w)
        self._card.setContentsMargins(10, 8, 10, 8)
        self._card.setHorizontalSpacing(12)
        self._card.setVerticalSpacing(6)
        self._v_speed, self._row_speed = self._mk_tile(t('速度 tok/s'), t('生成输出速度（/slots n_decoded 差分，或 /metrics / 日志推算）'))
        self._v_cpu, self._row_cpu = self._mk_tile(t('CPU 负载%'), t('系统整体 CPU 负载：所有核心平均占用率（不是单核，也不会超过 100%）'))
        self._v_mem, self._row_mem = self._mk_tile(t('内存 GB'), t('系统内存 已用/总量'))
        self._v_gpu, self._row_gpu = self._mk_tile(t('GPU 负载 %'), t('GPU 计算核心利用率（nvidia-smi utilization.gpu，多卡取最大，约每 2 秒刷新；与显存占用是两个不同指标）'))
        self._v_vram, self._row_vram = self._mk_tile(t('显存 GB'), t('显存 已用/总量（nvidia-smi）'))
        self._v_api, self._row_api = self._mk_tile(t('API 接入'), t('正在请求模型的客户端数量'))
        self._model_full = QLabel(_IDLE_TEXT)
        self._model_full.setObjectName("ppModelFull")
        self._model_full.setWordWrap(False)
        self._model_full.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._place_card()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.addWidget(self._pill)
        root.addWidget(self._card_w)

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(_COLLAPSE_MS)
        self._collapse_timer.timeout.connect(self._on_collapse_timeout)

        self.apply_theme(self._theme_key)
        self._collapse()
        self.setMouseTracking(True)

    # ------------------------------------------------------------- 主题
    def apply_theme(self, theme_key):
        if theme_key in THEMES:
            self._theme_key = theme_key
        t = THEMES[self._theme_key]["colors"]
        bg = _c(t, "field_bg", "#0c1730")
        border = _c(t, "field_border", "#1d4f7a")
        text = _c(t, "text", "#bfe6ff")
        fg = _c(t, "field_fg", "#d9f4ff")
        accent = _c(t, "sb_fg", "#7df9ff")
        self._col_speed = accent
        self._col_idle = text
        self.setStyleSheet(f"""
            QFrame#ppPill {{ background:{bg}; border:1px solid {border};
                border-radius:11px; }}
            QWidget#ppCard {{ background:{bg}; border:1px solid {border};
                border-radius:10px; }}
            QLabel {{ background:transparent; border:none; }}
            QLabel#ppLogo {{ background:transparent; border:none; }}
            QLabel#ppName {{ color:{fg}; font-size:12px; font-weight:bold; }}
            QLabel#ppSpeed {{ color:{fg}; font-size:11px; font-weight:bold; }}
            QLabel#ppModel, QLabel#ppChev, QLabel#ppApi,
            QLabel#ppModelFull {{ color:{text}; font-size:10px; }}
            QLabel#ppModelFull {{ font-size:11px; font-weight:bold; color:{fg}; }}
            QLabel#ppCap {{ color:{text}; font-size:9px; }}
            QLabel#ppVal {{ color:{fg}; font-size:13px; font-weight:bold; }}
            QPushButton#ppClose {{ color:{text}; background:transparent;
                border:none; font-size:10px; }}
            QPushButton#ppClose:hover {{ color:#ff7b72; }}
        """)
        self._repaint_dot()

    # ------------------------------------------------------------- 数据入口
    def set_running(self, running):
        self._running = bool(running)
        if not self._running:
            self._speed = 0.0
            self._api_busy = 0
            self.set_model("")
        self._refresh_text()
        self._repaint_dot()

    def set_speed(self, v):
        self._speed = max(0.0, float(v))
        self._refresh_text()

    def set_api_busy(self, n):
        n = max(0, int(n))
        if n == self._api_busy:
            return
        self._api_busy = n
        self._refresh_text()

    def set_model(self, name):
        name = (name or "").strip()
        self._model = "" if name in (t('未运行'), t('加载中…')) else name
        self._model_lbl.setText(self._elide(self._model or _IDLE_TEXT, self._model_lbl, 170))
        full = self._model or _IDLE_TEXT
        self._model_full.setText(t('模型：{0}').format(full))
        tip = (t('当前运行的模型：') + full) if self._model else t('当前没有模型在运行')
        self._model_lbl.setToolTip(tip)
        self._model_full.setToolTip(tip)

    def set_cpu(self, pct):
        try:
            self._set_value(self._v_cpu, f"{float(pct):.0f}")
        except (TypeError, ValueError):
            self._set_value(self._v_cpu, _IDLE_TEXT)

    def set_mem(self, used_gb, total_gb):
        if total_gb:
            self._set_value(self._v_mem, f"{used_gb:.1f}/{total_gb:.0f}")
        else:
            self._set_value(self._v_mem, _IDLE_TEXT)

    def set_vram(self, used_mb, total_mb):
        if total_mb:
            self._set_value(self._v_vram,
                            f"{used_mb / 1024:.1f}/{total_mb / 1024:.0f}")
        else:
            self._set_value(self._v_vram, _IDLE_TEXT)

    def set_gpu(self, pct):
        try:
            self._set_value(self._v_gpu, f"{float(pct):.0f}")
        except (TypeError, ValueError):
            self._set_value(self._v_gpu, _IDLE_TEXT)

    # ------------------------------------------------------------- 内部刷新
    def _refresh_text(self):
        # 速度始终显示具体数值（未运行时为 0.0），不再显示占位横线
        self._speed_lbl.setText(f"{self._speed:.1f} tok/s")
        col = getattr(self, "_col_speed", "#7df9ff") if self._running \
            else getattr(self, "_col_idle", "#8899aa")
        self._speed_lbl.setStyleSheet(f"color:{col};")
        if self._api_busy > 0:
            self._api_lbl.setText(f"●{self._api_busy}")
            self._api_lbl.setVisible(not self._expanded)
        else:
            self._api_lbl.setVisible(False)
        self._set_value(self._v_speed, f"{self._speed:.1f}")
        self._set_value(self._v_api,
                        t('{0} 个接入').format(self._api_busy) if self._api_busy else t('空闲'))
        self._repaint_dot()

    def _repaint_dot(self):
        color = "#3fd07f" if self._running else "#5c7080"
        self._dot.setStyleSheet(
            f"background:{color}; border-radius:5px; min-width:10px; min-height:10px;")
        self._dot.setToolTip(t('模型服务运行中') if self._running else t('模型服务未运行'))

    def _set_value(self, lbl, text):
        lbl.setText(str(text))

    def _elide(self, text, widget, width):
        fm = widget.fontMetrics()
        return fm.elidedText(text, Qt.TextElideMode.ElideMiddle, width)

    def _mk_tile(self, caption, tip):
        row = QWidget()
        lay = QVBoxLayout(row)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(0)
        cap = QLabel(caption)
        cap.setObjectName("ppCap")
        val = QLabel(_IDLE_TEXT)
        val.setObjectName("ppVal")
        lay.addWidget(cap)
        lay.addWidget(val)
        row.setToolTip(tip)
        return val, row

    def _place_card(self):
        cells = [
            (0, 0, self._row_speed), (0, 1, self._row_cpu),
            (1, 0, self._row_mem), (1, 1, self._row_gpu),
            (2, 0, self._row_vram), (2, 1, self._row_api),
        ]
        for r, c, w in cells:
            w.setSizePolicy(QSizePolicy.Policy.Expanding,
                            QSizePolicy.Policy.Preferred)
            self._card.addWidget(w, r, c)
        # 左右两列等宽
        self._card.setColumnStretch(0, 1)
        self._card.setColumnStretch(1, 1)
        # 模型名单独一行，横跨两列显示（不再拆成「模型 | 名称」两格）
        self._card.addWidget(self._model_full, 3, 0, 1, 2)
        self._card_w.setVisible(False)

    # ------------------------------------------------------------- 展开/收起
    def expand(self):
        if self._expanded:
            return
        self._expanded = True
        self._collapse_timer.stop()
        self._card_w.setVisible(True)
        self._model_lbl.setVisible(False)
        self._api_lbl.setVisible(False)
        self._chev.setText("▾")
        self._btn_close.setVisible(True)
        self._relayout()

    def collapse(self):
        if not self._expanded:
            return
        self._collapse()
        self._relayout()

    def _relayout(self):
        self.layout().activate()
        self.adjustSize()
        self._clamp_bottom()
        self._save_default_pos()

    def _collapse(self):
        self._expanded = False
        self._pinned = False
        self._collapse_timer.stop()
        self._card_w.setVisible(False)
        self._model_lbl.setVisible(False)
        self._chev.setText("▴")
        self._btn_close.setVisible(False)
        self._refresh_text()

    def _on_collapse_timeout(self):
        """未钉住时鼠标离开 5 秒后收起；钉住或鼠标仍在窗口内则不收。"""
        if self._pinned or self.underMouse():
            return
        self.collapse()

    # ------------------------------------------------------------- 位置
    def show_at_default(self):
        pos = self.cfg.data.get("hover_pill_pos") if self.cfg else None
        self._default_pos = None
        self.move(self._default_geometry())
        self.show()
        self.raise_()
        if isinstance(pos, (list, tuple)) and len(pos) == 2:
            try:
                self._move_to(int(pos[0]), int(pos[1]))
                return
            except (TypeError, ValueError):
                pass
        self._save_default_pos()

    def _default_geometry(self):
        if getattr(self, "_default_pos", None):
            return QPoint(*self._default_pos)
        scr = self._screen_geo()
        self.ensurePolished()
        self.adjustSize()
        w, _h = max(self.sizeHint().width(), 150), self.sizeHint().height()
        return QPoint(scr.x() + scr.width() - w - 16, scr.y() + 8)

    def _save_default_pos(self):
        # 收起态时记录默认位置（供展开/收起切换时回到同一锚点）
        if not self._expanded:
            self._default_pos = (self.x(), self.y())

    def _screen_geo(self):
        scr = QGuiApplication.screenAt(self.frameGeometry().center()) \
            or QGuiApplication.primaryScreen()
        avail = scr.availableGeometry()
        full = scr.geometry()
        # 任务栏在底部时，availableGeometry 上沿不变、下沿收缩；贴住其上方
        return avail

    def _clamp_bottom(self):
        scr = self._screen_geo()
        x, y = self.x(), self.y()
        y = max(scr.y() + 4, min(y, scr.bottom() - self.height() + 1))
        x = max(scr.x() + 4, min(x, scr.right() - self.width() + 1))
        self.move(x, y)

    def _move_to(self, x, y):
        scr = self._screen_geo()
        x = max(scr.x() + 4, min(x, scr.right() - self.width() + 1))
        y = max(scr.y() + 4, min(y, scr.bottom() - self.height() + 1))
        self.move(x, y)

    # ------------------------------------------------------------- 交互
    def enterEvent(self, event):
        # 鼠标进入整个悬浮窗区域：立即取消收起，并展开卡片
        self._collapse_timer.stop()
        if not self._expanded:
            self.expand()
        super().enterEvent(event)

    def leaveEvent(self, event):
        # 未钉住：鼠标离开后 5 秒收起；已钉住：保持展开
        if self._expanded and not self._pinned:
            self._collapse_timer.start()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._drag_pos is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            new_tl = event.globalPosition().toPoint() - self._drag_pos
            if not self._moved and (new_tl - self.pos()).manhattanLength() >= _DRAG_PX:
                self._moved = True
            if self._moved:
                self._move_to(new_tl.x(), new_tl.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            moved, self._moved = self._moved, False
            self._drag_pos = None
            if moved:
                if self._save_pos_cb:
                    try:
                        self._save_pos_cb(self.x(), self.y())
                    except Exception:
                        pass
            else:
                self._collapse_timer.stop()
                if self._expanded:
                    if self._pinned:
                        # 已钉住：再次点击 → 取消钉住并立即收起
                        self._pinned = False
                        self.collapse()
                    else:
                        # 悬停展开状态：点击 → 钉住，移开鼠标也不收起
                        self._pinned = True
                else:
                    # 收起状态：点击 → 展开并钉住
                    self._pinned = True
                    self.expand()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
            self._moved = False
            self.open_main.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _build_menu(self):
        """右键菜单：打开主界面 / 启动模型 / 停止模型 / 隐藏图标 / 退出。"""
        menu = QMenu(self)
        act_show = menu.addAction(t('打开主界面'))
        act_show.triggered.connect(self.open_main.emit)
        act_start = menu.addAction(t('启动模型'))
        act_start.setEnabled(not self._running)
        act_start.triggered.connect(self.start_requested.emit)
        act_stop = menu.addAction(t('停止模型'))
        act_stop.setEnabled(self._running)
        act_stop.triggered.connect(self.stop_requested.emit)
        menu.addSeparator()
        act_hide = menu.addAction(t('隐藏图标'))
        act_hide.setToolTip(t('本次最小化期间不再显示悬浮窗；下次点 X 收起时会自动恢复显示'))
        act_hide.triggered.connect(self._on_hide_requested)
        act_quit = menu.addAction(t('退出'))
        act_quit.triggered.connect(self.quit_requested.emit)
        return menu

    def contextMenuEvent(self, event):
        menu = self._build_menu()
        menu.popup(event.globalPos())
        event.accept()

    def _on_hide_requested(self):
        self.hide()
        self.hide_requested.emit()

    def _on_close_clicked(self):
        if self.cfg is not None:
            try:
                self.cfg.data["hover_pill"] = False
                self.cfg.save()
            except Exception:
                pass
        self.hide()
        if self._on_hidden_cb:
            try:
                self._on_hidden_cb()
            except Exception:
                pass
