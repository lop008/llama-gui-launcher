#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抓取启动器界面截图（用于 README / Release）。

用法:
    python capture_screenshots.py --out docs/screenshots
    python capture_screenshots.py --out docs/screenshots --only advanced

说明:
  - 用默认 Windows 平台渲染（**不要** offscreen，否则没有字体、中文变方块）。
  - 自动屏蔽「残留进程检测」与托盘，避免交互弹窗。
  - 输出 1280x1040 的 PNG。
"""
import argparse
import os
import sys
import time

BASE = None


def _root(start):
    d = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.abspath(start)
        d = parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/screenshots")
    ap.add_argument("--only", default=None,
                    help="只抓某个视图: main / advanced / preview")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=1040)
    args = ap.parse_args()

    root = _root(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)

    # 屏蔽交互弹窗/托盘
    import src.main_window as mw
    mw.find_llama_server_processes = lambda *a, **k: []

    from PyQt6.QtWidgets import QApplication, QSystemTrayIcon
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)

    app = QApplication(sys.argv)
    win = mw.MainWindow(root)

    # 等模型扫描
    t0 = time.time()
    while time.time() - t0 < 20 and win.combo_model.count() == 0:
        app.processEvents(); time.sleep(0.05)

    out_dir = os.path.join(root, *args.out.split("/"))
    os.makedirs(out_dir, exist_ok=True)

    def shot(name, advanced=False):
        win.box_advanced.set_collapsed(not advanced)
        win.resize(args.width, args.height)
        win.show()
        for _ in range(30):
            app.processEvents(); time.sleep(0.02)
        path = os.path.join(out_dir, f"{name}.png")
        win.grab().save(path)
        print(f"saved {path}")

    if args.only in (None, "main"):
        shot("main", advanced=False)
    if args.only in (None, "advanced"):
        shot("advanced", advanced=True)

    win._usage_timer.stop()
    try:
        win.monitor.stop()
    except Exception:
        pass
    app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
