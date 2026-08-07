import subprocess
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from . import jobobject

CREATE_NO_WINDOW = 0x08000000


class ServerManager(QObject):
    log = pyqtSignal(str)
    state = pyqtSignal(str)
    healthy = pyqtSignal(str)
    exited = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.proc = None
        self.url = ""
        self._manual_stop = False
        self._job = None
        self._job_ok = False

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    @property
    def manual_stop(self):
        return self._manual_stop

    @property
    def protected(self):
        """服务是否处于 Job Object 保护下（启动器崩溃时会被系统自动清理）。"""
        return self._job_ok

    def start(self, args, workdir, host, port, health_timeout=180):
        self.stop()
        self.url = f"http://{host}:{port}"
        self._manual_stop = False
        try:
            self.proc = subprocess.Popen(
                args,
                cwd=workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as e:
            self.state.emit(f"启动失败: {e}")
            self.proc = None
            return False
        self._protect()
        self.state.emit("服务启动中...")
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._health, args=(health_timeout,), daemon=True).start()
        return True

    def _protect(self):
        """用 Windows Job Object 保护服务：启动器退出/崩溃时自动清理进程树。"""
        self._job = jobobject.create_kill_on_close_job()
        self._job_ok = False
        if self._job and jobobject.assign_process_to_job(self._job, self.proc.pid):
            self._job_ok = True
            self.log.emit("[防护] 已启用 Job Object：本程序退出/崩溃时，llama-server 将被系统自动清理，显存立即释放")
        else:
            if self._job:
                jobobject.close_job(self._job)
                self._job = None
            self.log.emit("[提示] Job Object 绑定失败，将退化为看门狗模式（进程异常时自动清理）")

    def _reader(self):
        for line in self.proc.stdout:
            self.log.emit(line.rstrip("\n"))
        code = self.proc.poll() if self.proc else -1
        if not self._manual_stop:
            pid = self.proc.pid if self.proc else None
            if pid:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        creationflags=CREATE_NO_WINDOW, timeout=10,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
            self.log.emit("[看门狗] 服务异常退出，已尝试清理残留进程")
        self.log.emit(f"[进程已退出，退出码 {code}]")
        self.exited.emit(code)

    def _health(self, timeout):
        import requests

        url = self.url + "/health"
        start = time.time()
        while time.time() - start < timeout and self.running:
            try:
                r = requests.get(url, timeout=2)
                if r.ok:
                    self.state.emit(f"服务已就绪: {self.url}")
                    self.healthy.emit(self.url)
                    return
            except Exception:
                pass
            time.sleep(1)
        if self.running:
            self.state.emit("健康检查超时（进程仍在运行，请查看日志或访问网页）")

    def stop(self):
        self._manual_stop = True
        if self.proc is not None and self.proc.poll() is None:
            pid = self.proc.pid
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    creationflags=CREATE_NO_WINDOW,
                    timeout=10,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                try:
                    self.proc.terminate()
                except Exception:
                    pass
            try:
                self.proc.wait(timeout=5)
            except Exception:
                pass
            self.state.emit("服务已停止")
        jobobject.close_job(self._job)
        self._job = None
        self._job_ok = False
        self.proc = None


def port_in_use(host, port):
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host, int(port)))
            return True
        except Exception:
            return False


def find_llama_server_processes():
    """查找系统中残留的 llama-server.exe 进程（不含本启动器管理的）。"""
    try:
        r = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10, creationflags=CREATE_NO_WINDOW,
        )
        return [line for line in r.stdout.strip().splitlines() if "llama-server.exe" in line.lower()]
    except Exception:
        return []


def kill_all_llama_server():
    """强制结束所有 llama-server.exe 进程（清理崩溃残留）。"""
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "llama-server.exe", "/T"],
            creationflags=CREATE_NO_WINDOW, timeout=15,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False
