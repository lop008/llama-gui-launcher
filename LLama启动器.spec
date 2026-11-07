# -*- mode: python ; coding: utf-8 -*-
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
""" % {'quad': _quad, 'ver': _ver, 'exe': 'LLama启动器.exe'})


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets', 'assets'), ('参数说明.md', '.')],
    hiddenimports=['cryptography'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['huggingface_hub', 'modelscope', 'modelscope_hub', 'tqdm', 'hf_transfer'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LLama启动器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_vinfo,
    icon=['assets\\icon.ico'],
)
