#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""发版前自检（隐私 + 版本一致性 + 必填文件）。

用法:
    python preflight.py            # 仅自检
    python preflight.py 0.4.25     # 额外校验所有版本号 == 0.4.25
    python preflight.py --root "H:\\llama-cpp\\LLama启动器"

检查项:
  1. src/__init__.py / version_info.txt / version_info_portable.txt 版本号是否一致（并等于给定版本）
  2. git 已跟踪文件中是否混入隐私/体积文件（黑名单）
  3. 本次发版必填文件是否存在：docs/cover-vX.Y.Z.png、docs/release_body_vX.Y.Z.md
  4. 打印 git status 摘要，提示将提交哪些文件

退出码 0 = 通过；1 = 有告警；2 = 参数错误。
"""
import argparse
import os
import re
import subprocess
import sys

PRIVATE_BASENAMES = {
    "config.json", "hf_model_cache.json", "stats.json",
    "_layout_screenshot.png", "_probe.tar", "_probe_remote.tar.gz",
    "_push_probe.py", "_push_commit.py", "_publish_release.ps1",
    "后续版本功能开发.txt", "新建 文本文档.txt",
}
PRIVATE_SUFFIXES = (".aic", ".pyc", ".pyo", ".gguf", ".xltd")
PRIVATE_DIRS = (
    "dist/", "build/", "logs/", "release/", ".venv/", "venv/",
    "__pycache__/", ".idea/", ".vscode/", "Qwen3.8-27B-GGUF/",
)
PRIVATE_PATHS = {
    "assets/icon.ico", "assets/donate_qr.png", "assets/donate_qr.jpg",
    "assets/ad.png", "assets/原始图标.png", "assets/原始图片.png",
    "docs/参数说明.html",
}
EXE_ZIP_RE = re.compile(r"^LLama.*-win-x64(-portable)?\.(exe|zip)$", re.IGNORECASE)


def find_root(start):
    d = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.abspath(start)
        d = parent


def run(root, args):
    r = subprocess.run(["git", "-c", "core.quotepath=false", *args],
                       cwd=root, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "")


def read_version(root):
    p = os.path.join(root, "src", "__init__.py")
    with open(p, "r", encoding="utf-8") as f:
        m = re.search(r'__version__\s*=\s*"([^"]+)"', f.read())
    return m.group(1) if m else None


def read_vi_versions(root):
    out = {}
    for name in ("version_info.txt", "version_info_portable.txt"):
        p = os.path.join(root, name)
        if not os.path.exists(p):
            out[name] = None
            continue
        with open(p, "r", encoding="utf-8") as f:
            text = f.read()
        m = re.search(r"u'ProductVersion',\s*u'([^']+)'", text)
        out[name] = m.group(1) if m else None
    return out


def is_private(path):
    p = path.replace("\\", "/")
    base = p.rsplit("/", 1)[-1]
    if base in PRIVATE_BASENAMES:
        return True
    if base.startswith("_test_") and base.endswith(".py"):
        return True
    if base.lower().endswith(PRIVATE_SUFFIXES):
        return True
    if EXE_ZIP_RE.match(base):
        return True
    if p in PRIVATE_PATHS:
        return True
    for d in PRIVATE_DIRS:
        if p.startswith(d) or f"/{d}" in f"/{p}":
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("version", nargs="?", default=None)
    ap.add_argument("--root", default=os.path.dirname(os.path.abspath(__file__)))
    args = ap.parse_args()

    root = find_root(args.root)
    print(f"repo root: {root}\n")
    problems = []

    # --- 1. 版本一致性 ---
    v_init = read_version(root)
    vi = read_vi_versions(root)
    print("== 版本号 ==")
    print(f"  src/__init__.py           : {v_init}")
    for k, v in vi.items():
        print(f"  {k:<25}: {v}")
    versions = {v for v in [v_init, *vi.values()] if v}
    if len(versions) != 1 or None in (v_init, *vi.values()):
        problems.append("版本号在 3 个文件中不一致或缺失")
    if args.version:
        want = args.version.lstrip("vV")
        if versions != {want}:
            problems.append(f"版本号与期望 {want} 不一致（当前 {sorted(versions)}）")
    print()

    # --- 2. 隐私黑名单（已跟踪文件）---
    code, tracked = run(root, ["ls-files"])
    tracked = [x for x in tracked.splitlines() if x.strip()]
    leaked = sorted(x for x in tracked if is_private(x))
    print(f"== 已跟踪文件 {len(tracked)} 个，隐私检查 ==")
    if leaked:
        problems.append(f"发现 {len(leaked)} 个隐私/体积文件已被跟踪")
        for x in leaked:
            print(f"  [LEAK] {x}")
    else:
        print("  未发现隐私文件，OK")
    print()

    # --- 3. 必填发版文件 ---
    ver = args.version.lstrip("vV") if args.version else v_init
    print("== 发版必填文件 ==")
    for rel in (f"docs/cover-v{ver}.png", f"docs/release_body_v{ver}.md"):
        ok = os.path.exists(os.path.join(root, *rel.split("/")))
        print(f"  {'OK ' if ok else 'MISS'} {rel}")
        if not ok:
            problems.append(f"缺少 {rel}")
    for rel in ("README.md", "README.zh-CN.md", "CHANGELOG.md", "RELEASE_NOTES.md"):
        if not os.path.exists(os.path.join(root, rel)):
            problems.append(f"缺少 {rel}")
    print()

    # --- 4. git status 摘要 ---
    _, status = run(root, ["status", "--short"])
    lines = [x for x in status.splitlines() if x.strip()]
    print(f"== git status（{len(lines)} 项变更）==")
    for x in lines[:40]:
        print("  " + x)
    if len(lines) > 40:
        print(f"  ... 其余 {len(lines) - 40} 项")
    print()

    if problems:
        print("PREFLIGHT FAILED:")
        for p in problems:
            print("  -", p)
        return 1
    print("PREFLIGHT OK — 可以提交/打包/发布")
    return 0


if __name__ == "__main__":
    sys.exit(main())
