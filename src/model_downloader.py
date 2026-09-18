"""带断点续传的模型文件下载器（功能 5）。

- HTTP Range 断点续传：已下载的 .part 文件保留，重连时从上次位置继续；
- 队列模式：多个任务顺序执行；
- 所有网络操作都在后台线程中完成，通过 Qt 信号回报进度。
"""
import os
import threading
import time
from collections import deque

import requests

from PyQt6.QtCore import QObject, pyqtSignal

CHUNK = 1024 * 1024          # 每次读取 1MB
PROGRESS_INTERVAL = 0.5      # 进度信号最小间隔（秒）
MAX_RETRY = 3                # 单任务网络错误重试次数


class ModelDownloader(QObject):
    task_started = pyqtSignal(str)                    # label
    progress = pyqtSignal(str, int, int, float)       # label, done_bytes, total_bytes, speed_Bps
    task_done = pyqtSignal(str, str)                  # label, final_path（成功）
    task_failed = pyqtSignal(str, str)                # label, error
    queue_empty = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._queue = deque()          # [(url, dest, label)]
        self._active = False
        self._cancel_current = False
        self._lock = threading.Lock()
        self._thread = None

    # ------------------------------------------------------------- 队列控制
    def enqueue(self, url, dest_path, label=None):
        """加入下载任务；若当前空闲则立即开始。"""
        with self._lock:
            if not self._active:
                self._queue.append((url, dest_path, label or os.path.basename(dest_path)))
                self._start_worker()

    def cancel_current(self):
        """取消当前下载（保留 .part，可再次续传）；队列继续。"""
        self._cancel_current = True

    def clear_queue(self):
        """清空等待中的任务并停止当前下载。"""
        with self._lock:
            self._queue.clear()
        self._cancel_current = True

    @property
    def pending_count(self):
        return len(self._queue)

    @property
    def is_active(self):
        """下载工作线程是否仍在运行（取消/结束后为 False）。"""
        t = self._thread
        return bool(self._active and t is not None and t.is_alive())

    # ------------------------------------------------------------- 工作线程
    def _start_worker(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._active = True
        self._cancel_current = False
        t = threading.Thread(target=self._worker, daemon=True)
        self._thread = t
        t.start()

    def _worker(self):
        while True:
            with self._lock:
                if not self._queue:
                    self._active = False
                    break
                url, dest, label = self._queue.popleft()
            try:
                self.task_started.emit(label)
                final = self._download_one(url, dest, label)
                self.task_done.emit(label, final)
            except _Cancelled:
                continue  # 被取消：跳过该任务，继续队列下一个
            except Exception as e:
                try:
                    self.task_failed.emit(label, str(e))
                except RuntimeError:
                    pass
        try:
            self.queue_empty.emit()
        except RuntimeError:
            pass

    # ------------------------------------------------------------- 单文件下载
    def _download_one(self, url, dest, label):
        part = dest + ".part"
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)

        # 已完成则直接跳过
        if os.path.isfile(dest):
            try:
                local = os.path.getsize(dest)
                r = requests.head(url, headers=HEADERS(), timeout=20)
                remote = int(r.headers.get("Content-Length") or 0)
                if remote and local == remote:
                    self.progress.emit(label, local, remote, 0.0)
                    return dest
            except Exception:
                pass

        pos = os.path.getsize(part) if os.path.isfile(part) else 0
        last_err = None
        for attempt in range(MAX_RETRY + 1):
            try:
                self._download_once(url, part, dest, label, pos)
                return dest
            except _Cancelled:
                raise
            except Exception as e:
                last_err = e
                if attempt < MAX_RETRY:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"下载失败（已重试 {MAX_RETRY} 次）: {last_err}")

    def _download_once(self, url, part, dest, label, pos):
        headers = HEADERS()
        if pos > 0:
            headers["Range"] = f"bytes={pos}-"
        r = requests.get(url, headers=headers, stream=True, timeout=30)

        mode = "ab"
        done = pos
        total = 0
        if r.status_code == 206:
            # 断点续传成功
            cr = r.headers.get("Content-Range") or ""
            if "/" in cr:
                try:
                    total = int(cr.rsplit("/", 1)[1])
                except ValueError:
                    total = 0
        elif r.status_code == 200:
            # 服务器不支持 Range：从头开始
            done = 0
            mode = "wb"
            if pos > 0 and os.path.isfile(part):
                try:
                    os.remove(part)
                except OSError:
                    pass
        else:
            r.close()
            raise RuntimeError(f"HTTP {r.status_code}")

        cl = int(r.headers.get("Content-Length") or 0)
        if total == 0:
            total = done + cl if (r.status_code == 206 and cl) else cl

        last_emit = 0.0
        t0 = time.time()
        b0 = done
        with open(part, mode) as f:
            for chunk in r.iter_content(CHUNK):
                if self._cancel_current:
                    r.close()
                    raise _Cancelled()
                if not chunk:
                    continue
                f.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last_emit >= PROGRESS_INTERVAL or (total and done >= total):
                    speed = max(0.0, (done - b0)) / max(1e-6, now - t0)
                    self.progress.emit(label, done, total, speed)
                    last_emit = now

        r.close()
        if self._cancel_current:
            raise _Cancelled()

        # 校验并落盘
        final_size = os.path.getsize(part)
        if total and final_size != total:
            raise RuntimeError(f"文件大小不符（{final_size} / {total}），已保留 .part 可重试")
        tmp = dest + ".done.tmp"
        os.replace(part, tmp)      # 先改名避免与旧文件混淆
        os.replace(tmp, dest)
        self.progress.emit(label, final_size, total or final_size, 0.0)
        return dest


class _Cancelled(Exception):
    pass


def HEADERS():
    return {"User-Agent": "LLamaLauncher/0.2"}
