"""系统状态监控：CPU / 内存 / 显存 / 运行模型 / API 活动。

优先使用 psutil；若未安装则用 Windows API（ctypes）兜底，保证任何环境可运行。
"""
import ctypes
import os
import subprocess
import threading
import time
from ctypes import wintypes

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

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


# ---------------------------------------------------------------- 监控器
class SystemMonitor(QObject):
    cpu_changed = pyqtSignal(float)
    mem_changed = pyqtSignal(float, str)
    vram_changed = pyqtSignal(str)
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
        self._vram_skip = 0
        self._model_fetched = False
        self._last_vram = ""
        self._prev_sys = None
        self._prev_proc = None

    def start(self):
        self._timer.start(1000)

    def stop(self):
        self._timer.stop()

    def set_server(self, proc, url="", model_hint=""):
        """服务进程变化时调用。proc 为 None 表示服务已停止。
        model_hint: 启动时已知的模型文件名（立即显示，权威准确）。"""
        self._proc_url = url if proc else ""
        self._running = proc is not None
        self._pid = proc.pid if proc is not None else None
        self._pproc = None
        self._prev_sys = None
        self._prev_proc = None
        self._model_fetched = False
        if proc is not None:
            if HAS_PSUTIL:
                try:
                    self._pproc = psutil.Process(proc.pid)
                    self._pproc.cpu_percent(None)  # 基准采样
                except Exception:
                    self._pproc = None
            self.model_changed.emit(model_hint or "加载中…")
        else:
            self.api_changed.emit("API 未运行")
            self.model_changed.emit("未运行")

    def fetch_model_now(self):
        """服务就绪时主动拉取一次运行模型名（加载完成后立即显示）。"""
        self._model_fetched = False
        if self._running and self._proc_url:
            self._query_model()

    def _tick(self):
        # CPU：运行中显示进程占用%，否则显示系统占用%
        if self._pid is not None:
            self.cpu_changed.emit(self._process_cpu())
        else:
            self.cpu_changed.emit(self._system_cpu())

        # 内存
        self.mem_changed.emit(*self._memory())

        # 显存：每 2 秒查询一次 nvidia-smi
        self._vram_skip += 1
        if self._vram_skip % 2 == 0:
            self._query_vram()

        # API / 模型
        if self._running and self._proc_url:
            self._query_api()
            if not self._model_fetched:
                self._query_model()
        else:
            self.api_changed.emit("API 未运行")

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
                tip = f"系统内存: {vm.used / 2**30:.1f} / {vm.total / 2**30:.1f} GB"
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
        tip = f"系统内存: {used / 2**30:.1f} / {total / 2**30:.1f} GB"
        if self._pid:
            ws = _proc_working_set(self._pid)
            if ws:
                tip += f"\nllama-server: {ws / 2**30:.1f} GB"
        return float(load), tip

    def _query_vram(self):
        def work():
            text = ""
            try:
                r = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used,memory.total",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5, creationflags=CREATE_NO_WINDOW,
                )
                if r.returncode == 0 and r.stdout.strip():
                    parts = r.stdout.strip().split(",")
                    used, total = int(parts[0]), int(parts[1])
                    text = f"{used / 1024:.1f}/{total / 1024:.1f} GB"
            except Exception:
                text = ""
            if text != self._last_vram:
                self._last_vram = text
                try:
                    self.vram_changed.emit(text)
                except RuntimeError:
                    pass

        threading.Thread(target=work, daemon=True).start()

    def _query_api(self):
        def work():
            text = "API 空闲"
            try:
                import requests
                r = requests.get(self._proc_url + "/slots", timeout=2)
                if r.ok:
                    slots = r.json()
                    busy = sum(1 for s in slots if s.get("is_processing"))
                    text = f"API 使用中({busy})" if busy else "API 空闲"
            except Exception:
                text = "API 空闲"
            try:
                self.api_changed.emit(text)
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _query_model(self):
        def work():
            name = ""
            try:
                import requests
                r = requests.get(self._proc_url + "/props", timeout=2)
                if r.ok:
                    name = os.path.basename(r.json().get("model_path", "") or "")
            except Exception:
                name = ""
            if name:
                self._model_fetched = True
            try:
                self.model_changed.emit(name or "加载中…")
            except RuntimeError:
                pass

        threading.Thread(target=work, daemon=True).start()
