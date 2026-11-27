# -*- coding: utf-8 -*-
"""多显卡探测、显存权重分配、按显存自动拆分 layer。"""

import os
import threading

from PyQt6.QtWidgets import QCheckBox, QDoubleSpinBox, QLabel
from ..i18n import t


CREATE_NO_WINDOW = 0x08000000


class GpuMixin:

    def _rebuild_gpu_checks(self, devices):
        """按检测到的设备列表重建复选框，并恢复已保存的勾选。"""
        saved = (self.cfg.data.get("server", {}) or {}).get("devices") or []
        for c in self.gpu_checks:
            self.gpu_layout.removeWidget(c)
            c.deleteLater()
        self.gpu_checks = []
        for dev in devices:
            name, desc = dev
            cb = QCheckBox(f"{name}  {desc}")
            # 注意：PyQt6 的 QWidget 没有 setData()，用动态属性保存设备名
            cb.setProperty("dev_name", name)
            if name in saved:
                cb.setChecked(True)
            cb.toggled.connect(self.update_preview)
            self.gpu_layout.addWidget(cb)
            self.gpu_checks.append(cb)
        self.gpu_panel.setVisible(bool(devices))

        # ---- A5: 重建每卡权重行（每张卡一行，默认 1）----
        self._gpu_ratio_syncing = True   # 程序化回填期间禁止回写 tensor-split
        try:
            for lab in getattr(self, "_gpu_ratio_labels", []) or []:
                self.gpu_ratio_layout.removeWidget(lab)
                lab.deleteLater()
            for sp in getattr(self, "gpu_ratio_spins", []) or []:
                self.gpu_ratio_layout.removeWidget(sp)
                sp.deleteLater()
            self._gpu_ratio_labels = []
            self.gpu_ratio_spins = []
            row = 1   # row 0 是「按显存自动分配」按钮
            for i, dev in enumerate(devices):
                name, desc = dev
                short = (desc or "").split(" (")[0].strip()
                lab = QLabel(f"GPU{i} {short}")
                self.gpu_ratio_layout.addWidget(lab, row, 0)
                sp = QDoubleSpinBox()
                sp.setRange(0.0, 16.0)
                sp.setSingleStep(1.0)
                sp.setValue(1.0)
                sp.setToolTip(t('{0}（{1}）在 tensor-split 中的权重；\n修改后自动同步到「tensor-split」输入框。').format(name, short))
                self.gpu_ratio_layout.addWidget(sp, row, 1)
                self._gpu_ratio_labels.append(lab)
                self.gpu_ratio_spins.append(sp)
                row += 1
            # 若已有 tensor-split 文本且数量匹配，回填到 spinbox（保持显示一致）
            txt = getattr(self, "edit_tensor_split", None)
            if txt is not None:
                parts = [p for p in str(txt.text()).replace("，", ",").split(",")
                         if p.strip()]
                if len(parts) == len(self.gpu_ratio_spins):
                    try:
                        vals = [float(p) for p in parts]
                        if all(0.0 <= v <= 16.0 for v in vals):
                            for sp, v in zip(self.gpu_ratio_spins, vals):
                                sp.setValue(v)
                    except ValueError:
                        pass
            # 回填完成后再连接信号，避免重建时覆盖已保存的 tensor-split
            for sp in self.gpu_ratio_spins:
                sp.valueChanged.connect(self._on_gpu_ratio_changed)
        finally:
            self._gpu_ratio_syncing = False

        # A5c: 按钮状态 —— 需 ≥2 张卡且 nvidia-smi 可用，否则置灰并提示原因
        import shutil as _shutil
        has_smi = _shutil.which("nvidia-smi") is not None
        if len(devices) >= 2 and has_smi:
            self.btn_auto_split.setEnabled(True)
            self.btn_auto_split.setToolTip(
                t('用 nvidia-smi 查询每张卡总显存，按比例换算成整数权重\n（如 24G+8G → 3,1），并同步填入 tensor-split 输入框。'))
        else:
            self.btn_auto_split.setEnabled(False)
            if not devices:
                tip = t('尚未检测到 GPU；点「检测 GPU」后可用')
            elif len(devices) == 1:
                tip = t('只检测到一张卡，无需分配（单卡不使用 tensor-split）')
            else:
                tip = t('未找到 nvidia-smi，无法查询显存，请手动填写 tensor-split')
            self.btn_auto_split.setToolTip(tip)
        self.gpu_ratio_panel.setVisible(bool(devices))

    def prefetch_engine_flags(self):
        """后台预热本机 llama.cpp 参数表（`llama-server --help`）。

        生成命令时要靠它决定「锁定内存 / 禁用 mmap」写老参数还是新的 `-lm/--load-mode`；
        不预热的话第一次点启动会卡在 --help 子进程上（约 0.4s）。
        """
        if getattr(self, "_closing", False):
            return          # 由无父对象的 QTimer.singleShot 触发，关窗后仍会到点
        try:
            from ..launch_advisor import prefetch_engine_flags
            prefetch_engine_flags(self._launcher_exe())
        except Exception:
            pass            # 预热失败无所谓：真正用到时会自己查一次

    def detect_gpus(self):
        """调用 llama-server --list-devices 检测本机 GPU（后台线程）。"""
        if getattr(self, "_closing", False):
            return          # 由无父对象的 QTimer.singleShot 触发，关窗后仍会到点
        import re as _re
        exe = self._launcher_exe()

        def work():
            devs, err = [], None
            if not os.path.isfile(exe):
                err = t('未找到 llama-server.exe，无法检测设备')
            else:
                import subprocess
                proc = None
                try:
                    proc = subprocess.Popen(
                        [exe, "--list-devices"], stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                        errors="replace", creationflags=CREATE_NO_WINDOW)
                    self._gpu_probe_pid = proc.pid
                    try:
                        out, _ = proc.communicate(timeout=30)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        out = ""
                    for line in (out or "").splitlines():
                        s = line.strip()
                        low = s.lower()
                        if low.startswith(("available", "no ", "error")):
                            continue
                        m = _re.match(r'([A-Za-z][\w]*\d*):\s*(.+)$', s)
                        if m:
                            devs.append((m.group(1), m.group(2)))
                except Exception as e:
                    err = str(e)
                finally:
                    self._gpu_probe_pid = None
            self._gpu_result = (devs, err)
            try:
                self.gpu_detected.emit()
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_gpus_detected(self):
        # 注意：Qt 槽函数内异常不得外抛（会导致未定义行为），必须捕获
        try:
            devs, err = getattr(self, "_gpu_result", ([], None))
            if err:
                self.label_gpus.setText(t('检测失败：{0}').format(err))
                return
            if not devs:
                self.label_gpus.setText(t('未检测到可用 GPU 设备'))
                self._rebuild_gpu_checks([])
                return
            self.label_gpus.setText(
                    "、".join(f"{n} {d.split(' (')[0]}" for n, d in devs))
            self._rebuild_gpu_checks(devs)
        except Exception as e:
            try:
                self.label_gpus.setText(t('GPU 处理出错：{0}').format(e))
            except RuntimeError:
                pass
    # ---------------------------------------------------------- A5: 多显卡权重分配

    def _on_gpu_ratio_changed(self):
        """任一权重 spinbox 变化 → 把 'w0,w1,...' 写回 tensor-split（手动覆盖仍可直接编辑该框）。"""
        if getattr(self, "_gpu_ratio_syncing", False):
            return
        spins = getattr(self, "gpu_ratio_spins", None) or []
        if not spins or not hasattr(self, "edit_tensor_split"):
            return
        parts = []
        for sp in spins:
            v = float(sp.value())
            parts.append(str(int(round(v))) if abs(v - round(v)) < 1e-9 else f"{v:g}")
        self.edit_tensor_split.setText(",".join(parts))

    def _auto_split_by_vram(self):
        """用 nvidia-smi 查询每张卡总显存（后台线程），按比例换算成整数权重填入。"""
        import subprocess

        def work():
            totals = []
            try:
                r = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.total",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10,
                    encoding="utf-8", errors="replace",
                    creationflags=CREATE_NO_WINDOW)
                if r.returncode == 0:
                    for line in (r.stdout or "").splitlines():
                        s = line.strip()
                        if s.isdigit():
                            totals.append(int(s))
            except Exception:
                totals = []
            weights = self._vram_to_weights(totals)
            try:
                self.vram_weights.emit(weights)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _vram_to_weights(totals):
        """显存(MiB)列表 → 整数权重比例（以最小卡为基准取整，如 24G+8G → [3, 1]）。"""
        totals = [int(t) for t in totals if int(t) > 0]
        if not totals:
            return []
        m = min(totals)
        weights = [max(1, int(round(t / m))) for t in totals]
        from math import gcd
        wg = 0
        for w in weights:
            wg = gcd(wg, w)
        if wg > 1:
            weights = [w // wg for w in weights]
        return weights

    def _on_vram_weights(self, weights):
        """nvidia-smi 查询完成 → 把整数权重填入各 spinbox（自动同步到 tensor-split）。"""
        try:
            spins = getattr(self, "gpu_ratio_spins", None) or []
            if not weights or len(weights) != len(spins):
                self.statusBar().showMessage(
                    t('nvidia-smi 卡数与检测到的设备不一致，请手动填写 tensor-split'), 5000)
                return
            for sp, w in zip(spins, weights):
                sp.setValue(float(w))   # 触发 _on_gpu_ratio_changed → 同步 edit_tensor_split
            self.statusBar().showMessage(
                t('已按显存分配: {0}').format(','.join((str(int(round(w))) for w in weights))), 4000)
        except Exception as e:
            try:
                self.statusBar().showMessage(t('自动分配失败: {0}').format(e), 5000)
            except RuntimeError:
                pass
