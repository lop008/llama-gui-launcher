# -*- coding: utf-8 -*-
"""主题、窗口几何、Tab 顺序与窗口自适应、日志区、使用统计、采样预设等周边行为。"""

import os
import time

from PyQt6.QtCore import QEvent, QPoint, QTimer
from PyQt6.QtWidgets import QAbstractSpinBox, QApplication, QMessageBox
from ..i18n import t
from ..presets import PRESETS, SAMPLING_PRESETS
from ..stats_dialog import StatsDialog
from ..themes import THEMES, build_qss
from ..usage_stats import StatsStore, parse_log_line

CREATE_NO_WINDOW = 0x08000000


class AppPrefsMixin:
    # ---------------------------------------------------------- 数据统计（功能 9）
    def _stats(self):
        """惰性创建 StatsStore；数据目录变化时自动重建。"""
        path = os.path.join(self._data_dir(), "stats.json")
        if self._stats_store is None or self._stats_path != path:
            self._stats_path = path
            self._stats_store = StatsStore(os.path.dirname(path))
        return self._stats_store
    def _stats_model_name(self):
        """统计归属的模型名：优先当前选中模型，其次监控到的运行模型。"""
        p = self.combo_model.currentData() if hasattr(self, "combo_model") else None
        if p:
            return os.path.basename(p)
        return ""
    def _tick_usage(self):
        if not (hasattr(self, "server") and self.server.running):
            return
        name = self._stats_model_name() or self._running_model_name
        if not name:
            return
        # 时长在运行期间逐笔累计（每 5 秒一笔并立即计入统计），停止/退出时只落盘，
        # 切勿再次累加 pending，否则总时长会翻倍。
        self._usage_pending += 5.0
        self._stats().add_usage(name, seconds=5.0)
    def _flush_usage(self):
        """停止/退出：保存统计文件（时长已在运行期间逐笔累计，这里不再重复累加）。"""
        try:
            self._usage_pending = 0.0
            self._stats().save()
        except Exception:
            pass
    def show_stats(self):
        """打开独立的数据统计界面（功能 9）。"""
        if getattr(self, "_stats_dlg", None) is None:
            self._stats_dlg = StatsDialog(self._stats(), self)
        else:
            self._stats_dlg.refresh()
        self._stats_dlg.show()
        self._stats_dlg.raise_()
        self._stats_dlg.activateWindow()
    # ------------------------------------------------------------------ 事件过滤
    def eventFilter(self, obj, ev):
        """吞掉所有数字框（QSpinBox/QDoubleSpinBox）的滚轮事件。

        否则滚动窗口时鼠标掠过任意一个数值框，值就会被顺带改小/改大
        （表现为「数字只能往下调」）。上下箭头与直接键入不受影响。"""
        if ev.type() == QEvent.Type.Wheel and isinstance(obj, QAbstractSpinBox):
            return True
        return super().eventFilter(obj, ev)
    def _on_preset_changed(self):
        idx = self.combo_preset.currentIndex()
        if idx <= 0:
            return
        _name, ctx = PRESETS[idx]
        if ctx:
            self._loading = True
            self.spin_ctx.setValue(ctx)
            self._loading = False
            self._sync_preset_combo()
        self.statusBar().showMessage(t('已应用上下文预设: {0}').format(PRESETS[idx][0]), 3000)
    def _sync_preset_combo(self):
        """上下文长度变化时，让「上下文预设」下拉自动回显对应档位；非预设值显示「自定义」。"""
        if self._loading or not hasattr(self, "combo_preset"):
            return
        ctx = self.spin_ctx.value()
        target = 0
        for i, (_name, v) in enumerate(PRESETS):
            if i > 0 and v is not None and v == ctx:
                target = i
                break
        if self.combo_preset.currentIndex() != target:
            self.combo_preset.blockSignals(True)
            self.combo_preset.setCurrentIndex(target)
            self.combo_preset.blockSignals(False)
    def _on_ctx_manual(self, _v):
        self._sync_preset_combo()
    # ---------------------------------------------------------- 主题
    def set_theme(self, key):
        """切换配色方案（深色/浅色/橙色/绿色/灰色/棕色）。"""
        if key not in THEMES:
            return
        self.cfg.data["theme"] = key
        self._apply_theme()
        self.cfg.save()
    def _apply_theme(self):
        key = self.cfg.data.get("theme", "dark")
        if key not in THEMES:
            key = "dark"
        # 所有主题共用同一套尺寸度量，切换不会改变窗口布局大小
        QApplication.instance().setStyleSheet(build_qss(key))
        self.btn_theme.setText(f"{THEMES[key]['icon']} {THEMES[key]['name']}")
        if self._pill is not None:
            self._pill.apply_theme(key)
    def _restore_geometry(self):
        """启动时恢复上次的窗口位置/大小（配置里存的是 [x, y, w, h]）。

        若保存的窗口中心已不在任何屏幕上（换显示器/分辨率变化），则忽略，
        避免窗口出现在屏幕外无法操作。"""
        geo = self.cfg.data.get("window_geometry")
        if not (isinstance(geo, (list, tuple)) and len(geo) == 4):
            return
        try:
            x, y, w, h = (int(v) for v in geo)
        except (TypeError, ValueError):
            return
        if w < 640 or h < 480:
            return
        if QApplication.screenAt(QPoint(x + w // 2, y + h // 2)) is None:
            return
        self.setGeometry(x, y, w, h)
    def _current_tab_order(self):
        order = []
        for i in range(self.tabs.count()):
            wdg = self.tabs.widget(i)
            for key, w in self._tab_widgets.items():
                if w is wdg:
                    order.append(key)
                    break
        return order
    def _restore_tab_order(self):
        """按配置里的 tab_order 恢复底部标签顺序（缺项/新标签自动追加到末尾）。"""
        order = self.cfg.data.get("tab_order")
        if not isinstance(order, list):
            return
        order = [k for k in order if k in self._tab_widgets]
        for target, key in enumerate(order):
            cur = self.tabs.indexOf(self._tab_widgets[key])
            if cur >= 0 and cur != target:
                self.tabs.tabBar().moveTab(cur, target)
    def _on_tab_moved(self, _from, _to):
        self.cfg.data["tab_order"] = self._current_tab_order()
        self.cfg.save()
    def _reflow_window(self, checked=None):
        """折叠/展开参数区后，让窗口高度随内容伸缩（双向自适应）。
        checked=True 展开（只长大）；checked=False 折叠（缩短）。
        延迟一小段事件循环，等布局稳定后再执行，避免陈旧的最小尺寸。"""
        QTimer.singleShot(30, lambda: self._apply_reflow(checked))
    def _apply_reflow(self, checked=None):
        if not hasattr(self, "params_panel"):
            return
        QApplication.processEvents()  # 让可见性变化先完成布局
        self.updateGeometry()
        self.params_panel.layout().activate()
        self.params_panel.setMinimumHeight(0)
        ph = self.params_panel.sizeHint().height()
        self.params_panel.setMinimumHeight(ph)
        lm = self.centralWidget().layout().contentsMargins()
        needed = (ph + self.tabs.minimumHeight()
                  + self.menuBar().height() + self.statusBar().height()
                  + lm.top() + lm.bottom() + 4)
        self.setMinimumSize(0, 0)  # 允许收缩（清除陈旧最小尺寸）
        if checked:
            self.resize(self.width(), max(self.height(), needed))
        else:
            self.resize(self.width(), needed)
        QApplication.processEvents()
        self.setMinimumSize(self.minimumSizeHint())  # 恢复为内容实际最小尺寸
    # ---------------------------------------------------------- 日志落盘
    def _status_tip(self, text, ms=4000, hold=False):
        """状态栏提示。hold=True 的消息在 ms 内不被普通消息抢掉
        （启动时多个后台检测并行完成，谁最后写谁说话，用户会看不到关键提醒）。"""
        now = time.time()
        if not hold and getattr(self, "_hint_until", 0.0) > now:
            return
        if hold:
            self._hint_until = now + ms / 1000.0
        try:
            self.statusBar().showMessage(text, ms)
        except Exception:
            pass
    def _log_file(self, text):
        try:
            logdir = os.path.join(self._data_dir(), "logs")
            os.makedirs(logdir, exist_ok=True)
            date = time.strftime("%Y%m%d")
            with open(os.path.join(logdir, t('运行日志-{0}.log').format(date)), "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
        except Exception:
            pass
    def _on_server_log(self, text):
        self.log_view.appendPlainText(text)
        self._log_file(text)
        # 统计：从服务端日志解析输入/输出 token（功能 9）
        parsed = parse_log_line(text)
        if parsed:
            kind, n = parsed
            name = self._running_model_name or self._stats_model_name()
            if name and n > 0:
                try:
                    self._stats().add_usage(
                        name,
                        in_tokens=n if kind == "prompt" else 0,
                        out_tokens=n if kind == "gen" else 0)
                except Exception:
                    pass
    def open_log_dir(self):
        logdir = os.path.join(self._data_dir(), "logs")
        try:
            os.makedirs(logdir, exist_ok=True)
            os.startfile(logdir)  # noqa: S606
        except Exception as e:
            QMessageBox.information(self, t('提示'), t('无法打开日志目录: {0}').format(e))
    # ---------------------------------------------------------- 状态栏监控
    def _on_mem(self, percent, tip):
        self.label_mem.setText(t('内存 {0:.0f}%').format(percent))
        self.label_mem.setToolTip(tip)
    def _on_vram(self, text):
        if text:
            self.label_vram.setText(t('显存 {0}').format(text))
            self.label_vram.setVisible(True)
        else:
            self.label_vram.setText("")
            self.label_vram.setVisible(False)
    # ---------------------------------------------------------- 采样预设
    def _on_sampling_preset(self, idx):
        if self._loading or idx <= 0:
            return
        _name, vals = SAMPLING_PRESETS[idx]
        self._loading = True
        self.spin_temp.setValue(vals["temp"])
        self.spin_topp.setValue(vals["top_p"])
        self.spin_topk.setValue(vals["top_k"])
        self.spin_rp.setValue(vals["repeat_penalty"])
        self._loading = False
        self.update_preview()
        self.statusBar().showMessage(t('已应用采样预设: {0}').format(SAMPLING_PRESETS[idx][0]), 3000)
    def _on_sampling_manual(self, _v):
        if self._loading:
            return
        if self.combo_sampling.currentIndex() > 0:
            self.combo_sampling.setCurrentIndex(0)
