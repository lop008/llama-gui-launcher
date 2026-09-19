#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""同步版本号到 3 个文件（src/__init__.py 与两个 version_info）。

用法:
    python bump_version.py 0.4.25
    python bump_version.py v0.4.25
    python bump_version.py 0.4.25 --root "H:\\llama-cpp\\LLama启动器"

退出码 0 成功；非 0 失败。
"""
import argparse
import os
import re
import sys


def find_root(start):
    d = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.abspath(start)
        d = parent


def norm_version(raw):
    v = str(raw).strip().lstrip("vV")
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        raise ValueError(f"版本号格式应为 X.Y.Z（如 0.4.25），收到：{raw!r}")
    return v


def bump_init(root, ver):
    path = os.path.join(root, "src", "__init__.py")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    new, n = re.subn(r'(__version__\s*=\s*")[^"]*(")',
                     lambda m: m.group(1) + ver + m.group(2), text)
    if n != 1:
        raise RuntimeError(f"未在 {path} 中找到唯一的 __version__")
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    return path


def bump_version_info(root, name, ver):
    path = os.path.join(root, name)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    major, minor, patch = ver.split(".")
    quad = f"({int(major)}, {int(minor)}, {int(patch)}, 0)"
    text, n1 = re.subn(r"filevers=\([^)]*\)", f"filevers={quad}", text)
    text, n2 = re.subn(r"prodvers=\([^)]*\)", f"prodvers={quad}", text)
    text, n3 = re.subn(r"(u'FileVersion',\s*u')[^']*(')",
                       lambda m: m.group(1) + ver + m.group(2), text)
    text, n4 = re.subn(r"(u'ProductVersion',\s*u')[^']*(')",
                       lambda m: m.group(1) + ver + m.group(2), text)
    if (n1, n2, n3, n4) != (1, 1, 1, 1):
        raise RuntimeError(f"{name} 版本字段替换异常: {n1},{n2},{n3},{n4}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version")
    ap.add_argument("--root", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()

    try:
        ver = norm_version(args.version)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    root = find_root(args.root)
    print(f"repo root : {root}")
    print(f"new version: {ver}")
    try:
        for p in (
            bump_init(root, ver),
            bump_version_info(root, "version_info.txt", ver),
            bump_version_info(root, "version_info_portable.txt", ver),
        ):
            print(f"  updated: {os.path.relpath(p, root)}")
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    print("OK — 版本号已同步（记得同步 CHANGELOG / README / RELEASE_NOTES）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
