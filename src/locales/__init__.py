# -*- coding: utf-8 -*-
"""语言表包：显式导入保证 PyInstaller 静态分析可打包。

每个语言模块暴露 STRINGS = {中文原文: 译文}，缺失的 key 自动回退中文。
单个语言表坏了不能影响启动，但不再静默吞掉：原因记入 FAILED 并打到 stderr，
上层可用 i18n.failed_languages() 查询。否则打包漏文件时只会「莫名显示中文」，无从排查。
"""
import sys

TABLES = {}

# 语言码 -> 失败原因（模块缺失、语法错误、表为空或类型不对）
FAILED = {}


def _warn(code):
    try:
        print("[i18n] {0} 语言表加载失败，界面回退简体中文：{1}".format(code, FAILED[code]),
              file=sys.stderr)
    except Exception:
        pass


def _register(code, strings):
    if isinstance(strings, dict) and strings:
        TABLES[code] = strings
    else:
        FAILED[code] = "语言表应为非空 dict，实际为 {0}".format(type(strings).__name__)
        _warn(code)


def _fail(code, exc):
    FAILED[code] = repr(exc)
    _warn(code)


try:
    from . import zh_tw
    _register("zh-TW", zh_tw.STRINGS)
except Exception as e:
    _fail("zh-TW", e)
try:
    from . import en
    _register("en", en.STRINGS)
except Exception as e:
    _fail("en", e)
try:
    from . import ja
    _register("ja", ja.STRINGS)
except Exception as e:
    _fail("ja", e)
try:
    from . import ko
    _register("ko", ko.STRINGS)
except Exception as e:
    _fail("ko", e)
try:
    from . import ru
    _register("ru", ru.STRINGS)
except Exception as e:
    _fail("ru", e)
try:
    from . import es
    _register("es", es.STRINGS)
except Exception as e:
    _fail("es", e)
try:
    from . import fr
    _register("fr", fr.STRINGS)
except Exception as e:
    _fail("fr", e)
