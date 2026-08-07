import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication

from src.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("LLama 启动器")
    app.setQuitOnLastWindowClosed(True)
    base = os.path.dirname(os.path.abspath(__file__))
    win = MainWindow(base)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
