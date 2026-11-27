import os
import sys

# 打包后 __file__ 指向只读的 _MEIPASS/_internal，而用户配置写在 exe 同级目录：
# 按 __file__ 找会读不到 config.json，语言偏好被无声忽略、永远跟随系统语言。
# 与 MainWindow.base_dir 保持同一规则：冻结态取 exe 所在目录。
if getattr(sys, "frozen", False):
    _BASE = os.path.dirname(os.path.abspath(sys.executable))
else:
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
