#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 Release 首图（版本功能说明 banner）。

用法示例:
    python make_cover.py --version 0.4.25 --out docs/cover-v0.4.25.png \
      --heading "本次更新 / What's New" \
      --bullet "对话模板：Jinja / 思考强度 / 推理预算" \
      --bullet "导入启动文件：解析 .bat 回填参数" \
      --bullet "残留进程提示：不再提示 + 端口占用建议" \
      --bullet "广告位图片按比例缩放" \
      --bullet "启动文件校验器识别新参数"

也可用 --bullets-file bullets.txt（每行一条）。
输出 1280x640 PNG，配色与启动器深色主题一致。
"""
import argparse
import os
import sys

from PyQt6.QtCore import QRectF, Qt  # noqa: E402
from PyQt6.QtGui import (  # noqa: E402
    QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QPen,
)
from PyQt6.QtWidgets import QApplication  # noqa: E402

W, H = 1280, 640
BG_TOP = QColor("#241a12")
BG_BOTTOM = QColor("#3a2a1c")
ACCENT = QColor("#e0a35c")
ACCENT2 = QColor("#7fd6a8")
TEXT = QColor("#f4ece2")
MUTED = QColor("#b39b83")

_FONT_FAMILY = None


def _family():
    """选一个系统可用的字体（优先中文字体，保证中英文都不缺字）。"""
    global _FONT_FAMILY
    if _FONT_FAMILY is None:
        families = set(QFontDatabase.families())
        for cand in ("Microsoft YaHei", "Microsoft YaHei UI", "SimHei",
                     "Microsoft JhengHei", "Segoe UI", "Arial"):
            if cand in families:
                _FONT_FAMILY = cand
                break
        else:
            _FONT_FAMILY = ""
    return _FONT_FAMILY


def pick_font(size, bold=False):
    f = QFont(_family(), size) if _family() else QFont()
    f.setPointSize(size)
    f.setBold(bold)
    return f


def render(version, heading, bullets, out, footer):
    app = QApplication.instance() or QApplication(sys.argv)
    img = QImage(W, H, QImage.Format.Format_ARGB32)
    img.fill(QColor("#000000"))

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # 背景渐变
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0.0, BG_TOP)
    g.setColorAt(1.0, BG_BOTTOM)
    p.fillRect(0, 0, W, H, g)

    # 左侧强调竖条
    p.fillRect(0, 0, 12, H, ACCENT)

    # 顶部产品名
    p.setPen(MUTED)
    p.setFont(pick_font(20, bold=False))
    p.drawText(70, 70, "LLama 万能启动器  /  LLama Launcher")

    # 版本徽章
    badge = QRectF(70, 100, 190, 62)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ACCENT)
    p.drawRoundedRect(badge, 14, 14)
    p.setPen(QColor("#241a12"))
    p.setFont(pick_font(34, bold=True))
    p.drawText(badge, Qt.AlignmentFlag.AlignCenter, f"v{version}")

    # 标题
    p.setPen(TEXT)
    p.setFont(pick_font(34, bold=True))
    p.drawText(290, 148, heading)

    # 分隔线
    p.setPen(QPen(QColor(255, 255, 255, 40), 2))
    p.drawLine(70, 200, W - 70, 200)

    # 功能条目
    y = 270
    p.setFont(pick_font(26, bold=False))
    for b in bullets:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ACCENT2)
        p.drawEllipse(78, y - 16, 14, 14)
        p.setPen(TEXT)
        p.drawText(112, y, b)
        y += 62

    # 底部
    p.setPen(MUTED)
    p.setFont(pick_font(18, bold=False))
    p.drawText(70, H - 40, footer)
    p.end()

    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    if not img.save(out):
        print(f"[ERROR] 保存失败: {out}", file=sys.stderr)
        return 1
    print(f"cover saved: {out}  ({W}x{H})")
    app.quit()
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--heading", default="本次更新 / What's New")
    ap.add_argument("--bullet", action="append", default=[])
    ap.add_argument("--bullets-file", default=None)
    ap.add_argument("--footer", default="github.com/lop008/llama-gui-launcher")
    args = ap.parse_args()

    bullets = list(args.bullet)
    if args.bullets_file:
        with open(args.bullets_file, "r", encoding="utf-8") as f:
            bullets += [ln.strip() for ln in f if ln.strip()]
    if not bullets:
        print("[ERROR] 至少提供一条 --bullet 或 --bullets-file", file=sys.stderr)
        return 2
    bullets = bullets[:6]
    return render(args.version.lstrip("vV"), args.heading, bullets, args.out, args.footer)


if __name__ == "__main__":
    sys.exit(main())
