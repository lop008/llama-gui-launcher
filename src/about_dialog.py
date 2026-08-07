import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QFrame)

from . import __version__, APP_NAME

BILIBILI_URL = "https://space.bilibili.com/3493265957456549"
DEVELOPER_NAME = "AI创客师"


class AboutDialog(QDialog):
    def __init__(self, base_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("开发者信息")
        self.setMinimumWidth(360)
        ico = os.path.join(base_dir, "assets", "icon.ico")
        if os.path.isfile(ico):
            ic = QIcon(ico)
            if not ic.isNull():
                self.setWindowIcon(ic)
        lay = QVBoxLayout(self)

        title = QLabel(f"{APP_NAME}  v{__version__}")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin: 8px;")
        lay.addWidget(title)

        info = QLabel(
            f"开发者: {DEVELOPER_NAME}<br/>"
            f"哔哩入口: <a href='{BILIBILI_URL}' style='color:#4a7fdb;'>{BILIBILI_URL}</a><br/>"
            f"版本: v{__version__}<br/><br/>"
            "本地大模型启动器<br/>"
            "基于 llama.cpp 构建"
        )
        info.setTextFormat(Qt.TextFormat.RichText)
        info.setOpenExternalLinks(True)
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        info.setWordWrap(True)
        info.setToolTip("点击哔哩哔哩链接即可打开主页")
        lay.addWidget(info)

        qr_path = None
        for name in ("donate_qr.png", "donate_qr.jpg"):
            cand = os.path.join(base_dir, "assets", name)
            if os.path.isfile(cand):
                qr_path = cand
                break
        if qr_path:
            qr = QLabel()
            pm = QPixmap(qr_path)
            if not pm.isNull():
                pm = pm.scaled(280, 280, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
                qr.setPixmap(pm)
                qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
                qr.setToolTip("谢谢支持")
                lay.addWidget(qr)
                tip = QLabel("如有帮助，欢迎打赏支持")
                tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lay.addWidget(tip)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        lay.addWidget(sep)

        btn_row = QHBoxLayout()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_close)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)
