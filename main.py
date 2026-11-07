import os
import sys

_BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _BASE)

from src import i18n

# 必须在导入任何界面模块之前应用语言（模块级被包裹的文案在 import 时求值）
i18n.bootstrap(_BASE)


def main():
    from PyQt6.QtWidgets import QApplication

    from src.i18n import t
    app = QApplication(sys.argv)
    app.setApplicationName(t("LLama 启动器"))
    app.setQuitOnLastWindowClosed(True)
    from src.main_window import MainWindow
    win = MainWindow(_BASE)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
