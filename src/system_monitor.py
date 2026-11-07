"""系统状态监控：CPU / 内存 / 显存 / GPU 负载 / 输出速度 / 运行模型 / API 活动。

优先使用 psutil；若未安装则用 Windows API（ctypes）兜底，保证任何环境可运行。

输出速度（tok/s）：llama-server 没有现成实时接口，按以下策略推算——
1. 新版服务端 /slots 提供 n_decoded 时，按计数增量实时计算（每秒，不依赖
   is_processing 字段）；
2. 否则轮询 /metrics（需服务端以 --metrics 启动，计数器 tokens_predicted_total
   等两次采样差分；连续失败 30 秒后自动重试）；
3. /metrics 不可用时退回解析运行日志：解码取 eval time 行均速，预填充取
   prompt processing 行的实时速度。
"""
import ctypes
import os
import re
import subprocess
import threading
import time
from ctypes import wintypes

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from .i18n import t

CREATE_NO_WINDOW = 0x08000000

try:
    import psutil
    HAS_PSUTIL = True
except Exception:
    HAS_PSUTIL = False

# ---------------------------------------------------------------- ctypes 兜底
_kernel32 = ctypes.windll.kernel32
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    def as_int(self):
        return (self.dwHighDateTime << 32) | self.dwLowDateTime


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _mem_status():
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if _kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return m.dwMemoryLoad, m.ullTotalPhys, m.ullTotalPhys - m.ullAvailPhys
    return 0.0, 0, 0


def _proc_working_set(pid):
    h = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return 0
    try:
        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        if _kernel32.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
            return int(pmc.WorkingSetSize)
        return 0
    finally:
        _kernel32.CloseHandle(h)


def _proc_cpu_ticks(pid):
    h = _kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return None
    try:
        c, e, k, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        if _kernel32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(k), ctypes.byref(u)):
            return k.as_int() + u.as_int()
        return None
    finally:
        _kernel32.CloseHandle(h)


def _system_cpu_ticks():
    idle, k, u = FILETIME(), FILETIME(), FILETIME()
    if _kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(k), ctypes.byref(u)):
        return idle.as_int(), k.as_int(), u.as_int()
    return None


# ---------------------------------------------------------------- 输出速度推算
# 日志回退：eval time = 407.32 ms / 24 tokens（排除 prompt eval time 行）
RE_EVAL_LINE = re.compile(
    r'(?<!prompt )eval time\s*=\s*([\d.]+)\s*ms\s*/\s*(\d+)\s*(?:runs?|tokens?)',
    re.IGNORECASE)
# 预填充进度行：prompt processing, n_tokens = 322, ... / 55.86 tokens per second
RE_PROMPT_PROG = re.compile(
    r'prompt processing.*?([\d.]+)\s*tokens per second', re.IGNORECASE)
RE_LOG_TS = re.compile(r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]')


def parse_metrics_generated(text):
    """从 /metrics 文本提取「已生成 token」计数器总和（含多标签系列）。

    兼容不同版本命名：llama:generated_tokens_total / llama:ngenerated_tokens_total /
    llama:predicted_total 等；按名称含 generated 或 predicted 且不含秒/毫秒类单位筛选。
    无匹配返回 None。"""
    total = None
    for line in text.splitlines():
        if not line or line[0] == "#" or " " not in line:
            continue
        name, _, val = line.rpartition(" ")
        low = name.lower()
        hit_gen = "generated" in low and "second" not in low and "_ms" not in low
        hit_pred = "predicted" in low and "second" not in low and "_ms" not in low
        if not (hit_gen or hit_pred):
            continue
        try:
            v = float(val)
        except ValueError:
            continue
        total = v if total is None else total + v
    return total


def parse_log_tail_speed(data):
    """从运行日志尾部字节推算当前输出速度（tok/s）。

    倒序扫描最近日志行，取第一条有效速度行：
    - eval time 行：整段生成的均速 = tokens / (ms/1000)；
    - prompt processing 行：预填充实时速度（该构建只在解码结束时打印 eval 行，
      生成过程中只能靠这类行显示速度）。
    命中行时间戳距今超过 8 秒视为生成已结束，返回 0。无有效行返回 None。"""
    try:
        text = data.decode("utf-8", "ignore")
    except Exception:
        return None
    lines = text.splitlines()
    for line in reversed(lines[-200:]):
        m = RE_EVAL_LINE.search(line)
        speed = None
        if m:
            try:
                ms, n = float(m.group(1)), int(m.group(2))
            except ValueError:
                continue
            if ms > 0 and n > 0:
                speed = n / (ms / 1000.0)
        else:
            m = RE_PROMPT_PROG.search(line)
            if m:
                try:
                    speed = float(m.group(1))
                except ValueError:
                    continue
        if speed is None:
            continue
        ts = RE_LOG_TS.search(line)
        if ts:
            try:
                t = time.mktime(time.strptime(ts.group(1), "%Y-%m-%d %H:%M:%S"))
                if time.time() - t > 8:
                    return 0.0
            except (ValueError, OverflowError):
                pass
        return speed
    return None


# ---------------------------------------------------------------- 监控器
class SystemMonitor(QObject):
    cpu_changed = pyqtSignal(float)                 # 进程/系统 CPU（状态栏用）
    cpu_load_changed = pyqtSignal(float)            # 系统整体负载：所有核心平均占用率 %
    mem_changed = pyqtSignal(float, str)
    mem_raw_changed = pyqtSignal(float, float)      # 已用GB, 总GB
    vram_changed = pyqtSignal(str)
    vram_raw_changed = pyqtSignal(float, float)     # 已用MB, 总MB
    gpu_util_changed = pyqtSignal(int)              # GPU 核心利用率 %
    speed_changed = pyqtSignal(float)               # 输出 token 速度 tok/s
    api_busy_changed = pyqtSignal(int)              # 正在处理请求的槽位数
    model_changed = pyqtSignal(str)
    api_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._pid = None
        self._pproc = None
        self._proc_url = ""
        self._running = False
        self._verify = True
        self._vram_skip = 0
        self._model_fetched = False
        self._last_vram = ""
        self._prev_sys = None
        self._prev_proc = None
        self.log_dir = None                  # 运行日志目录（日志回退用，MainWindow 注入）
        self._tok_prev = None                # /metrics 计数器差分基准
        self._tok_prev_t = 0.0
        self._metrics_fail = 0               # 连续失败次数（≥2 切日志回退）
        self._speed_busy = False
        self._last_gpu = None
        self._slots_decoded = None           # /slots n_decoded 差分基准（实时 tok/s）
        self._slots_t = 0.0
        self._slots_has_dec = False          # /slots 是否提供 n_decoded（可用时优先）
        self._slots_flat = 0                 # n_decoded 连续无增量次数（≥2 判空闲）
        self._slots_speed_t = 0.0            # slots 路径最近一次给出速度值的时间
        self._metrics_retry_t = 0.0          # metrics 连续失败后的下次重试时间
        self._vram_busy = False
        self._api_probe_busy = False

    def reset_speed_base(self):
        self._tok_prev = None
        self._tok_prev_t = 0.0
        self._metrics_fail = 0
        self._slots_decoded = None
        self._slots_t = 0.0
        self._slots_has_dec = False
        self._slots_flat = 0
        self._slots_speed_t = 0.0
        self._metrics_retry_t = 0.0

    def start(self):
        self._timer.start(1000)

    def stop(self):
        self._timer.stop()

    def set_server(self, proc, url="", model_hint="", verify=True):
        """服务进程变化时调用。proc 为 None 表示服务已停止。
        model_hint: 启动时已知的模型文件名（立即显示，权威准确）。
        verify: HTTPS 请求是否校验证书（自签名证书需传 False）。"""
        self._proc_url = url if proc else ""
        self._verify = bool(verify)
        self._running = proc is not None
        self._pid = proc.pid if proc is not None else None
        self._pproc = None
        self._prev_sys = None
        self._prev_proc = None
        self._model_fetched = False
        self.reset_speed_base()
        self._speed_changed_emit(0.0)
        if proc is not None:
            if HAS_PSUTIL:
                try:
                    self._pproc = psutil.Process(proc.pid)
                    self._pproc.cpu_percent(None)  # 基准采样
                except Exception:
                    self._pproc = None
            self.model_changed.emit(model_hint or t('加载中…'))
        else:
            self.api_changed.emit(t('API 未运行'))
            self.model_changed.emit(t('未运行'))

    def fetch_model_now(self):
        """服务就绪时主动拉取一次运行模型名（加载完成后立即显示）。"""
        self._model_fetched = False
        if self._running and self._proc_url:
            self._query_model()

    def _tick(self):
        # CPU：状态栏显示「运行中=进程占用%，否则=系统占用%」；
        # 悬浮窗固定显示系统整体负载（所有核心平均占用率）。
        sys_cpu = self._system_cpu()
        proc_cpu = self._process_cpu() if self._pid is not None else None
        self.cpu_changed.emit(proc_cpu if proc_cpu is not None else sys_cpu)
        self.cpu_load_changed.emit(sys_cpu)

        # 内存
        self.mem_changed.emit(*self._memory())

        # 显存 / GPU 负载 / 输出速度：每 2 秒查询一次
        self._vram_skip += 1
        if self._vram_skip % 2 == 0:
            self._query_vram()
            if self._running and self._proc_url:
                self._tick_speed()

        # API / 模型
        if self._running and self._proc_url:
            self._query_api()
            if not self._model_fetched:
                self._query_model()
        else:
            self.api_changed.emit(t('API 未运行'))

    def _system_cpu(self):
        if HAS_PSUTIL:
            return psutil.cpu_percent(None)
        now = _system_cpu_ticks()
        if now is None:
            return 0.0
        if self._prev_sys:
            idle_d = now[0] - self._prev_sys[0]
            kern_d = now[1] - self._prev_sys[1]
            user_d = now[2] - self._prev_sys[2]
            total = kern_d + user_d
            self._prev_sys = now
            if total > 0:
                return max(0.0, (total - idle_d) / total * 100)
            return 0.0
        self._prev_sys = now
        return 0.0

    def _process_cpu(self):
        if HAS_PSUTIL and self._pproc is not None:
            try:
                return self._pproc.cpu_percent(None)
            except Exception:
                return 0.0
        now = _proc_cpu_ticks(self._pid)
        if now is None:
            return 0.0
        cur = time.monotonic()
        if self._prev_proc:
            dt = now - self._prev_proc[0]
            wall = cur - self._prev_proc[1]
            self._prev_proc = (now, cur)
            if wall > 0:
                return max(0.0, dt / wall * 100)
            return 0.0
        self._prev_proc = (now, cur)
        return 0.0

    def _memory(self):
        tip = ""
        if HAS_PSUTIL:
            try:
                vm = psutil.virtual_memory()
                self.mem_raw_changed.emit(vm.used / 2**30, vm.total / 2**30)
                tip = t('系统内存: {0:.1f} / {1:.1f} GB').format(vm.used / 2 ** 30, vm.total / 2 ** 30)
                if self._pid:
                    try:
                        rss = psutil.Process(self._pid).memory_info().rss / 2**30
                        tip += f"\nllama-server: {rss:.1f} GB"
                    except Exception:
                        pass
                return vm.percent, tip
            except Exception:
                pass
        load, total, used = _mem_status()
        self.mem_raw_changed.emit(used / 2**30, total / 2**30)
        tip = t('系统内存: {0:.1f} / {1:.1f} GB').format(used / 2 ** 30, total / 2 ** 30)
        if self._pid:
            ws = _proc_working_set(self._pid)
            if ws:
                tip += f"\nllama-server: {ws / 2**30:.1f} GB"
        return float(load), tip

    def _query_vram(self):
        # 防止 nvidia-smi 调用重叠（超时 5s 时上一次可能还没结束）
        if self._vram_busy:
            return
        self._vram_busy = True

        def work():
            text, used, total, util = "", 0, 0, None
            try:
                r = subprocess.run(
                    ["nvidia-smi",
                     "--query-gpu=memory.used,memory.total,utilization.gpu",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5, creationflags=CREATE_NO_WINDOW,
                )
                if r.returncode == 0 and r.stdout.strip():
                    # 多卡：显存求和、利用率取最大
                    for line in r.stdout.strip().splitlines():
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) < 2:
                            continue
                        try:
                            used += int(float(parts[0]))
                            total += int(float(parts[1]))
                        except ValueError:
                            continue
                        if len(parts) >= 3:
                            try:
                                u = int(float(parts[2]))
                                util = u if util is None else max(util, u)
                            except ValueError:
                                pass
                    if total:
                        text = f"{used / 1024:.1f}/{total / 1024:.1f} GB"
            except Exception:
                text, used, total, util = "", 0, 0, None
            finally:
                self._vram_busy = False
            try:
                if total:
                    self.vram_raw_changed.emit(float(used), float(total))
                if util is not None and util != self._last_gpu:
                    self._last_gpu = util
                    self.gpu_util_changed.emit(int(util))
            except RuntimeError:
                pass
            if text != self._last_vram:
                self._last_vram = text
                try:
                    self.vram_changed.emit(text)
                except RuntimeError:
                    pass

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------ 输出速度
    def _speed_changed_emit(self, v):
        try:
            self.speed_changed.emit(float(v))
        except RuntimeError:
            pass

    def _tick_speed(self):
        if self._speed_busy:
            return
        self._speed_busy = True

        def work():
            try:
                self._query_speed()
            finally:
                self._speed_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _query_speed(self):
        now = time.monotonic()
        # /slots 增量路径活跃（5 秒内给过速度）时以它为准；静默超 5 秒自动放行兜底，
        # 避免 n_decoded 接口异常（如缺 is_processing 导致恒 0）时永久屏蔽 metrics/日志
        if self._slots_has_dec and now - self._slots_speed_t < 5:
            return
        # 连续失败满 2 次进入冷却，每 30 秒重试一次（不再永久禁用，
        # 防止模型加载期连接被拒把可用通道误杀）
        if self._metrics_fail >= 2:
            if now >= self._metrics_retry_t:
                self._metrics_fail = 0
        # 1) /metrics 计数器差分
        if self._metrics_fail < 2:
            try:
                import requests
                r = requests.get(self._proc_url + "/metrics", timeout=2,
                                 verify=self._verify)
                if r.ok:
                    total = parse_metrics_generated(r.text)
                    if total is not None:
                        self._metrics_fail = 0
                        now = time.monotonic()
                        if self._tok_prev is not None and now > self._tok_prev_t:
                            d = total - self._tok_prev
                            rate = max(0.0, d / (now - self._tok_prev_t))
                            self._speed_changed_emit(rate)
                        self._tok_prev, self._tok_prev_t = total, now
                        return
                self._metrics_fail += 1
            except Exception:
                self._metrics_fail += 1
            if self._metrics_fail >= 2:
                self._metrics_retry_t = time.monotonic() + 30
        # 2) 日志回退：最近一条 eval / prompt processing 行的速度
        speed = self._speed_from_log()
        if speed is not None:
            self._speed_changed_emit(speed)

    def _speed_from_log(self):
        try:
            if not self.log_dir:
                return None
            path = os.path.join(self.log_dir, t('运行日志-{0}.log').format(time.strftime('%Y%m%d')))
            if not os.path.isfile(path):
                return None
            size = os.path.getsize(path)
            with open(path, "rb") as f:
                if size > 65536:
                    f.seek(-65536, os.SEEK_END)
                data = f.read()
            return parse_log_tail_speed(data)
        except Exception:
            return None

    def _slots_speed_update(self, slots, now):
        """按 /slots 的 n_decoded 计数增量算实时速度。

        以「计数是否增长」判断是否在生成，不依赖 is_processing 字段
        （不同版本该字段命名/存在性不一致）。规则：
        - 首次 / 计数回退（新请求重置）/ 基准过期 → 静默重建基准；
        - 计数增长 → 出实时速率；
        - 无增量连续 2 次 → 归零并重置基准（避免空闲期摊进恢复后的速率窗口）。"""
        dec, has_dec = 0, False
        for s in slots:
            if isinstance(s, dict) and "n_decoded" in s:
                has_dec = True
                try:
                    dec += int(s.get("n_decoded") or 0)
                except (TypeError, ValueError):
                    pass
        if not has_dec:
            self._slots_has_dec = False
            return
        self._slots_has_dec = True
        prev, pt = self._slots_decoded, self._slots_t
        if prev is None or dec < prev or (now - pt) > 5:
            self._slots_decoded, self._slots_t = dec, now
            self._slots_flat = 0
        elif dec > prev:
            rate = max(0.0, (dec - prev) / max(now - pt, 1e-6))
            self._slots_decoded, self._slots_t = dec, now
            self._slots_flat = 0
            self._slots_speed_t = now
            self._speed_changed_emit(rate)
        else:
            self._slots_speed_t = now
            self._slots_flat += 1
            if self._slots_flat >= 2:
                self._slots_decoded, self._slots_t = dec, now
                self._slots_flat = 0
                self._speed_changed_emit(0.0)

    def _query_api(self):
        # 防止 /slots 请求重叠（超时 2s 时可能叠加）
        if self._api_probe_busy:
            return
        self._api_probe_busy = True

        def work():
            text = t('API 空闲')
            busy = 0
            slots = None
            try:
                import requests
                r = requests.get(self._proc_url + "/slots", timeout=2, verify=self._verify)
                if r.ok:
                    slots = r.json()
                    busy = sum(1 for s in slots if s.get("is_processing"))
                    text = t('API 使用中({0})').format(busy) if busy else t('API 空闲')
            except Exception:
                slots = None
                text = t('API 空闲')

            # 实时输出速度：/slots 的 n_decoded 计数器增量（详见 _slots_speed_update）
            if isinstance(slots, list):
                self._slots_speed_update(slots, time.monotonic())

            try:
                self.api_busy_changed.emit(int(busy))
            except RuntimeError:
                pass
            try:
                self.api_changed.emit(text)
            except RuntimeError:
                pass
            self._api_probe_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _query_model(self):
        def work():
            name = ""
            try:
                import requests
                r = requests.get(self._proc_url + "/props", timeout=2, verify=self._verify)
                if r.ok:
                    name = os.path.basename(r.json().get("model_path", "") or "")
            except Exception:
                name = ""
            if name:
                self._model_fetched = True
            try:
                self.model_changed.emit(name or t('加载中…'))
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()
