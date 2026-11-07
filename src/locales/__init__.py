# -*- coding: utf-8 -*-
"""语言表包：显式导入保证 PyInstaller 静态分析可打包。

每个语言模块暴露 STRINGS = {中文原文: 译文}，缺失的 key 自动回退中文。
"""

TABLES = {}

try:
    from . import zh_tw
    TABLES["zh-TW"] = zh_tw.STRINGS
except Exception:
    pass
try:
    from . import en
    TABLES["en"] = en.STRINGS
except Exception:
    pass
try:
    from . import ja
    TABLES["ja"] = ja.STRINGS
except Exception:
    pass
try:
    from . import ko
    TABLES["ko"] = ko.STRINGS
except Exception:
    pass
try:
    from . import ru
    TABLES["ru"] = ru.STRINGS
except Exception:
    pass
try:
    from . import es
    TABLES["es"] = es.STRINGS
except Exception:
    pass
try:
    from . import fr
    TABLES["fr"] = fr.STRINGS
except Exception:
    pass
