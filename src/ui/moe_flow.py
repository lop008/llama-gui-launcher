# -*- coding: utf-8 -*-
"""MoE 专家卸载的界面接线：稠密模型整套置灰 + 「卸载预设」一键算 N 与缓存（v0.6.5）。

两条硬规定
----------
1. **稠密模型整套 MoE 设置置灰并说明原因**。专家权重为 0 的模型上，
   `--cpu-moe / --n-cpu-moe / --moe-cache-mib` 没有作用对象；配置又是跨模型留存的，
   真出过事：跑完 Inkling-2 切到稠密的 Qwen3.8-27B，命令行还带着 `--n-cpu-moe`。
   命令行侧同一条判据在 `cmd_builder._moe_args()`，界面与下发不会说法不一。
2. **预设只负责算，不负责猜**。显存或模型信息取不到就直说取不到（并把正在补探测
   这件事写在提示里），绝不编一个 N 给用户。
"""
import os
import threading
from html import escape

from PyQt6.QtCore import pyqtSignal

from ..i18n import t
from ..moe_advisor import is_moe, plan, preset_label


def _moe_summary(res):
    """把方案压成一句状态栏文案：下发什么参数、缓存多大。"""
    mode = res.get("mode")
    if mode == "off":
        return t('不卸载（专家全部留在显存）')
    if mode == "cpu":
        return t('--cpu-moe（专家全部放 CPU）')
    return t('--n-cpu-moe {0}（前 {0} 层专家放 CPU）').format(int(res.get("layers") or 0))


class MoeFlowMixin:
    """挂在 MainWindow 上的 MoE 槽与状态（`self` 即主窗口）。"""

    moe_facts_ready = pyqtSignal(str, int)     # 模型路径, -1 读不出 / 0 稠密 / 1 MoE
    moe_vram_ready = pyqtSignal(float)         # 后台 nvidia-smi 查到的显存总量 MiB

    def init_moe_flow(self):
        """MainWindow.__init__ 里调一次：接信号 + 建状态字段。"""
        self._moe_vram_mb = 0.0
        self._moe_dense = False         # 当前模型是否稠密（None 判定前按可用处理）
        self.moe_facts_ready.connect(self._apply_moe_facts)
        self.moe_vram_ready.connect(self._on_moe_vram_ready)

    # ------------------------------------------------------------ 适用性判定
    def refresh_moe_for_model(self, path=None):
        """换模型后判断 MoE 设置该不该开放（张量表扫描放后台，别卡界面）。"""
        if path is None:
            path = self.combo_model.currentData()
        if not path:
            self._apply_moe_facts("", -1)
            return
        target = str(path)

        def work():
            try:
                state = is_moe(target)
            except Exception:
                state = None
            try:
                self.moe_facts_ready.emit(target, -1 if state is None else int(state))
            except RuntimeError:
                pass                    # 窗口已销毁

        threading.Thread(target=work, daemon=True).start()

    def _apply_moe_facts(self, path, state):
        """后台判定的结果回到 GUI 线程后落地。"""
        if path and str(self.combo_model.currentData() or "") != path:
            return                      # 用户切得飞快：过期的判定结果直接丢
        dense = state == 0
        # 置灰靠 config_io._on_moe_changed 统一处理（它还管 N / 缓存的可用性）。
        # 注意**不改**用户选的 mode/N：切回 MoE 模型时他原来的设置还要在，
        # 稠密模型上这几个参数由 cmd_builder 那侧的同一判据挡住不下发。
        self._moe_dense = dense
        self._on_moe_changed()
        if dense:
            self._moe_hint("warn", t(
                '当前模型是稠密模型（专家权重 0），MoE 专家设置不生效：'
                '这几个参数不会再下发给 llama-server（切回 MoE 模型时你原来的设置还在）'))
        elif state == -1:
            self._moe_hint("", t(
                '未取到该模型的专家分布（还没选模型，或文件读不出）；'
                'MoE 设置按你填的原样下发'))
        elif str(self.combo_moe_preset.currentData() or ""):
            # 换模型后按当前预设重算：同一档在不同模型上算出的 N 完全不同
            self._apply_moe_plan(self.combo_moe_preset.currentData(), announce=False)
        else:
            self._moe_hint("", t(
                'MoE 模型：可用「卸载预设」按本机显存一键算 N，或直接手动填'))

    # ------------------------------------------------------------ 预设套用
    def on_moe_preset_changed(self, _idx=None):
        key = str(self.combo_moe_preset.currentData() or "")
        if self._loading or not key:
            return
        self._apply_moe_plan(key)

    def on_moe_manual(self, *_args):
        """用户手动改了模式 / 层数 / 缓存 → 预设回到「不套用」（与采样预设同一套行为）。"""
        if self._loading or not hasattr(self, "combo_moe_preset"):
            return
        if self.combo_moe_preset.currentIndex() != 0:
            self.combo_moe_preset.blockSignals(True)
            self.combo_moe_preset.setCurrentIndex(0)
            self.combo_moe_preset.blockSignals(False)

    def _apply_moe_plan(self, key, announce=True):
        path = str(self.combo_model.currentData() or "")
        machine, vram_mb = self._moe_machine()
        if vram_mb <= 0:
            self._moe_hint("warn", t(
                '还没取到显存总量，正在后台用 nvidia-smi 查询，'
                '查好后会自动重算这一次预设'))
            threading.Thread(target=self._probe_vram_worker, daemon=True).start()
            return
        slots = int(self.spin_slots.value() or 1)
        res = plan(key, path, machine,
                   ctx=int(self.spin_ctx.value() or 0),
                   kv_type=str(self.combo_kvc_k.currentText() or "f16"),
                   slots=max(1, slots))
        if not res.get("ok"):
            # 算不出来就把预设退回「不套用」，绝不让界面上留着一个没生效的档位
            self.combo_moe_preset.blockSignals(True)
            self.combo_moe_preset.setCurrentIndex(0)
            self.combo_moe_preset.blockSignals(False)
            self._moe_hint("warn", res.get("reason") or t('无法计算'))
            return
        mode = res["mode"]
        idx = self.combo_moe.findData(mode)
        self._loading = True
        if idx >= 0:
            self.combo_moe.setCurrentIndex(idx)
        self.spin_moe_layers.setValue(int(res["layers"] or 0))
        self.spin_moe_cache.setValue(int(res["cache"] or 0))
        self._loading = False
        self._on_moe_changed()
        self._moe_hint("warn" if res.get("warn") else "ok", res["reason"])
        self.update_preview()
        if announce:
            self._status_tip(t('已按「{0}」设置 MoE 卸载：{1}，专家缓存 {2} MiB').format(
                preset_label(res["preset"]), _moe_summary(res), int(res["cache"] or 0)), 6000)

    # ------------------------------------------------------------ 本机资源
    def _moe_machine(self):
        """machine_profile + 显存总量（MiB）。显存优先用状态栏监控的最新采样。"""
        from ..launch_advisor import machine_profile
        model_dir = os.path.dirname(str(self.combo_model.currentData() or ""))
        mb = float(self._moe_vram_mb or 0)
        return machine_profile(vram_total_mb=mb, model_dir=model_dir), mb

    def on_vram_sample(self, _used_mb, total_mb):
        """状态栏显存监控的原始值（vram_raw_changed）顺手记一份总量给 MoE 计算用。"""
        try:
            total = float(total_mb or 0)
        except (TypeError, ValueError):
            return
        if total > 0:
            self._moe_vram_mb = total

    def _probe_vram_worker(self):
        from ..launch_advisor import probe_vram_mb
        try:
            mb = float(probe_vram_mb() or 0)
        except Exception:
            mb = 0.0
        try:
            self.moe_vram_ready.emit(mb)
        except RuntimeError:
            pass

    def _on_moe_vram_ready(self, mb):
        if mb > 0:
            self._moe_vram_mb = mb
        key = str(self.combo_moe_preset.currentData() or "")
        if key and mb > 0:
            self._apply_moe_plan(key)     # 补到显存信息了，重算刚才那次

    # ------------------------------------------------------------ 提示
    def _moe_hint(self, kind, text):
        """把计算过程 / 不适用原因写在 MoE 行下面（纯文本 + 颜色，不装 Markdown）。

        包一层 `<span>` 就变成富文本，里面的 `\\n` 会被 Qt 折成空格 → 必须换成 `<br>`；
        正文里出现的 `<` `>`（例如参数比较）要先转义，否则整段被当成标签吃掉。
        """
        label = getattr(self, "label_moe_hint", None)
        if label is None:
            return
        color = {"ok": "#4caf50", "warn": "#d08770"}.get(kind, "#8a8a8a")
        safe = escape(str(text)).replace("\n", "<br>")
        label.setText('<span style="color:%s;">%s</span>' % (color, safe))
        label.setToolTip(escape(str(text)))
