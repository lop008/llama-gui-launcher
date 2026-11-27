# -*- coding: utf-8 -*-
"""后台线程：读取 llama.cpp 版本（避免卡界面）。"""

from ..llama_updater import get_local_version_info
from PyQt6.QtCore import QThread, pyqtSignal


CREATE_NO_WINDOW = 0x08000000


class _LlamaVersionWorker(QThread):
    """后台运行 llama-server --version，避免阻塞 UI。"""
    done = pyqtSignal(str)

    def __init__(self, exe_path, parent=None):
        super().__init__(parent)
        self._exe = exe_path
        self.probe_pid = None   # 正在运行的 --version 探测进程 PID（残留检测需排除）

    def run(self):
        def _record(pid):
            self.probe_pid = pid
        try:
            info = get_local_version_info(self._exe, pid_cb=_record)
            ver = info.get("build") or info.get("version") or ""
            if info.get("version") and info.get("build"):
                ver = f"{info['version']} ({info['build']})"
        except Exception:
            ver = ""
        finally:
            self.probe_pid = None
        self.done.emit(ver)
