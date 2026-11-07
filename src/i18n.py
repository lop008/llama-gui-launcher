# -*- coding: utf-8 -*-
"""轻量国际化：以中文原文为 key 查表翻译，未命中回退中文。

用法：
    from .i18n import t
    label.setText(t("启动服务"))
    label.setText(t("已选中 {0} 个模型").format(n))

语言在应用启动时由 init() 决定（config["language"]，"auto" = 跟随系统）；
切换语言写回 config 后重启应用生效。翻译表为 src/locales 下的纯 Python 模块，
不引入任何运行时第三方依赖（PyInstaller 自动打包）。
"""
import sys

# (代码, 本地名称) —— 顺序即菜单顺序
LANGUAGES = [
    ("zh-CN", "简体中文"),
    ("zh-TW", "繁體中文"),
    ("en", "English"),
    ("ja", "日本語"),
    ("ko", "한국어"),
    ("ru", "Русский"),
    ("es", "Español"),
    ("fr", "Français"),
]

_CODE_SET = {c for c, _ in LANGUAGES}

_state = {"lang": "zh-CN", "dict": {}, "tables": None}


def _tables():
    if _state["tables"] is None:
        try:
            from . import locales
            _state["tables"] = locales.TABLES
        except Exception:
            _state["tables"] = {}
    return _state["tables"]


def _map_system_code(name):
    """把 QLocale/locale 名（如 zh_TW、en_US）映射到支持的语言代码。"""
    if not name:
        return "zh-CN"
    name = name.replace("-", "_")
    lang, _, region = name.partition("_")
    lang = lang.lower()
    region = region.upper()
    if lang == "zh":
        return "zh-TW" if region in ("TW", "HK", "MO") else "zh-CN"
    if lang in _CODE_SET:
        return lang
    return "en" if lang else "zh-CN"


def system_language():
    name = ""
    try:
        from PyQt6.QtCore import QLocale
        name = QLocale.system().name()
    except Exception:
        pass
    if not name:
        try:
            import locale
            name = locale.getlocale()[0] or ""
        except Exception:
            name = ""
    if not name and sys.platform == "win32":
        try:
            import ctypes
            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            iso = {0x04: "zh", 0x0c: "fr", 0x0a: "es", 0x19: "ru",
                   0x11: "ja", 0x12: "ko", 0x09: "en"}
            primary = langid & 0x3FF
            sub = langid >> 10
            lang = iso.get(primary, "")
            if lang == "zh":
                return "zh-TW" if sub in (0x01, 0x02, 0x14) else "zh-CN"
            if lang:
                return lang if lang in _CODE_SET else "en"
        except Exception:
            pass
    return _map_system_code(name)


def bootstrap(base_dir):
    """在任何 src 模块导入前调用：直接读 config.json 的 language 键并应用语言。

    这样模块级被包裹的文案（如 THEMES/PRESETS 名称）在 import 时就是正确语言。
    """
    import json
    import os
    pref = "auto"
    seen = set()
    for name in ("config.json",):
        path = os.path.join(base_dir, name)
        real = os.path.abspath(path)
        if real in seen or not os.path.exists(path):
            continue
        seen.add(real)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            pref = data.get("language") or pref
            dd = data.get("data_dir")
            if dd and os.path.isdir(dd):
                alt = os.path.abspath(os.path.join(dd, name))
                if alt not in seen and os.path.exists(alt):
                    seen.add(alt)
                    try:
                        with open(alt, "r", encoding="utf-8") as f2:
                            data2 = json.load(f2)
                        if isinstance(data2, dict) and data2.get("language"):
                            pref = data2["language"]
                    except Exception:
                        pass
        except Exception:
            pass
    return init(pref)


def resolve(preference):
    """把配置值解析为具体语言代码。"auto"/空/未知 → 跟随系统。"""
    pref = (preference or "auto").strip()
    if pref.lower() in ("", "auto", "system"):
        return system_language()
    if pref in _CODE_SET:
        return pref
    base = pref.replace("-", "_").split("_")[0].lower()
    if base == "zh" or base in {c.split("-")[0] for c, _ in LANGUAGES}:
        return _map_system_code(pref)
    return system_language()


def set_language(code):
    code = code if code in _CODE_SET else "zh-CN"
    _state["lang"] = code
    _state["dict"] = dict(_tables().get(code) or {}) if code != "zh-CN" else {}
    return code


def init(preference="auto"):
    return set_language(resolve(preference))


def lang():
    return _state["lang"]


def is_chinese():
    return _state["lang"].startswith("zh")


def t(text):
    """按当前语言翻译；key 缺失或已是 zh-CN 时原样返回。"""
    if not text or _state["lang"] == "zh-CN":
        return text
    out = _state["dict"].get(text)
    return text if out is None or out == "" else out


def tr(text, *args, **kwargs):
    """t() + format 一步到位：tr("共 {0} 项", n)。"""
    out = t(text)
    if args or kwargs:
        try:
            out = out.format(*args, **kwargs)
        except Exception:
            pass
    return out
