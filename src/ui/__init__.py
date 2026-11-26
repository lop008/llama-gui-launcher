# -*- coding: utf-8 -*-
"""MainWindow 的分组实现（Mixin + 自定义控件 + 后台线程）。

规则（改这里之前先看一眼）：
1. 只允许依赖底层模块（server / model_scanner / spec_decode / i18n / themes …），
   禁止反向 import main_window，否则循环导入。
2. 每个 Mixin 只负责一块功能，方法之间不要跨文件互相调私有方法；
   需要共享的状态一律挂在 self 上（与搬走前写在 MainWindow 里等价）。
3. MainWindow 的基类顺序必须是「各 Mixin 在前，QMainWindow 在后」。
   Qt 的虚函数（eventFilter / showEvent / closeEvent …）要找得到 Mixin 的实现，
   并且 Mixin 里的 super().xxx() 要能沿 MRO 落到 QMainWindow；一旦 Mixin 排在
   QMainWindow 后面，覆盖会静默失效，super() 还会落到 object，异常发生在 Qt 的
   C++ 回调里会让进程直接 fastfail（0xC0000409，没有 Python 回溯）。
4. 模块顶层不要写 t("…") 这类求值常量：import 期求值会拿到旧语言，切语言不刷新。
   文案一律在方法里现取。
"""
