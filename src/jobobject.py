"""Windows 作业对象（Job Object）：让服务进程随本程序退出而被系统自动杀死。

核心思想：把 llama-server 进程放进一个设置了 KILL_ON_JOB_CLOSE 标志的 Job 里。
本程序（启动器）一旦退出（包括崩溃、被强杀），系统会自动终止整个 Job 内的
进程树，从而立即释放 GPU 显存与内存，避免留下"僵尸"llama-server。
"""
import ctypes
from ctypes import wintypes

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_kernel32 = ctypes.windll.kernel32


def create_kill_on_close_job():
    """创建一个 '关闭即杀' 的作业对象，返回句柄；失败返回 None。"""
    try:
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _kernel32.SetInformationJobObject(
            job,
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            _kernel32.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


def assign_process_to_job(job, pid):
    """把指定 PID 的进程放进 Job。绑定失败返回 False（调用方应退化为看门狗）。"""
    try:
        ph = _kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pid))
        if not ph:
            return False
        try:
            ok = _kernel32.AssignProcessToJobObject(job, ph)
        finally:
            _kernel32.CloseHandle(ph)
        return bool(ok)
    except Exception:
        return False


def close_job(job):
    """关闭 Job 句柄。若进程仍在其中且设置了 KILL_ON_JOB_CLOSE，进程将被终止。"""
    try:
        if job:
            _kernel32.CloseHandle(job)
    except Exception:
        pass
