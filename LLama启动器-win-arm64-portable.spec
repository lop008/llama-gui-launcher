# -*- mode: python ; coding: utf-8 -*-
# ARM64 产物（与 x64 两份 spec 参数保持一致，只把产物名里的 x64 换成 arm64）。
# 注意：PyInstaller 不能交叉编译，这两份只能在 ARM64 Windows 上跑（GitHub Actions
# runs-on: windows-11-arm）。构建后必须过三验：PE Machine==0xAA64 / 版本资源==__version__
# / PYZ 内含 7 张语言表 + offscreen 冒烟 15 秒不崩。
import os as _os
import re as _re

# 版本号唯一来源：src/__init__.py 的 __version__（发版只改那一处）
with open(_os.path.join(SPECPATH, 'src', '__init__.py'), encoding='utf-8') as _f:
    _ver = _re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', _f.read()).group(1)
_quad = tuple(int(x) for x in (_ver.split('.') + ['0', '0', '0'])[:4])
_dir = globals().get('workpath') or _os.path.join(SPECPATH, 'build')
_os.makedirs(_dir, exist_ok=True)
_vinfo = _os.path.join(_dir, 'version_info_gen.txt')
with open(_vinfo, 'w', encoding='utf-8') as _f:
    _f.write("""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=%(quad)s,
    prodvers=%(quad)s,
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'AI创客师'),
         StringStruct(u'FileDescription', u'LLama 万能启动器 - llama.cpp 本地大模型图形化启动器'),
         StringStruct(u'FileVersion', u'%(ver)s'),
         StringStruct(u'InternalName', u'LLama启动器'),
         StringStruct(u'LegalCopyright', u'Copyright (c) 2026 AI创客师'),
         StringStruct(u'OriginalFilename', u'%(exe)s'),
         StringStruct(u'ProductName', u'LLama 万能启动器'),
         StringStruct(u'ProductVersion', u'%(ver)s')])
    ]),
    VarFileInfo([VarStruct(u'Translation', [2052, 1200])])
  ]
)
""" % {'quad': _quad, 'ver': _ver, 'exe': 'LLama启动器-win-arm64-portable.exe'})


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('参数说明.md', '.')],
    hiddenimports=['cryptography'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LLama启动器-win-arm64-portable',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_vinfo,
    icon=['assets\\icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LLama启动器-win-arm64-portable',
)
