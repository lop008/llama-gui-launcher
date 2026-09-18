import os
import re

MODEL_EXT = ".gguf"

# 只扫描 2~3 级子目录（从扫描根目录算起，含根目录自身为第 1 级）
MAX_SCAN_DEPTH = 3

# 无关/巨型目录一律跳过，避免把 .venv/.git/build 等拖入扫描导致非常慢
SKIP_DIRS = {
    ".git", ".svn", ".hg", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "build", "dist", ".idea", ".vscode", "logs", ".cache", ".gradle",
    ".next", ".turbo", ".serverless", "site-packages", "Lib", "Scripts",
}

# 多文件分片模型（llama.cpp split 命名）：xxx-00001-of-00003.gguf
SHARD_RE = re.compile(r'^(?P<base>.+)-(?P<idx>\d{5})-of-(?P<total>\d{5})\.gguf$', re.IGNORECASE)


class ModelInfo:
    __slots__ = ("path", "name", "size", "is_mmproj", "dir",
                 "shard_idx", "shard_total", "group_size")

    def __init__(self, path, name, size, is_mmproj, dir_):
        self.path = path
        self.name = name
        self.size = size
        self.is_mmproj = is_mmproj
        self.dir = dir_
        # 分片信息：shard_idx=1 表示这是「启动文件」（第一个分片）
        self.shard_idx = None
        self.shard_total = None
        self.group_size = size  # 多文件模型的总大小（单文件时=size）


def _is_partial(name):
    lower = name.lower()
    return any(lower.endswith(s) for s in (".xltd", ".xltd.cfg", ".partial", ".part", ".download", ".tmp"))


def natural_key(text):
    """自然排序键：数字按数值比较（2 < 10），其余忽略大小写。"""
    parts = re.split(r'(\d+)', str(text))
    key = []
    for p in parts:
        if not p:
            continue
        if p.isdigit():
            key.append((0, int(p)))
        else:
            key.append((1, p.lower()))
    return key


def sort_models(models, mode="dir_name"):
    """按指定方式排序模型列表（原地排序并返回）。

    - dir_name : 目录升序 + 文件名升序（自然排序，默认）
    - size_desc: 文件大小降序
    - name     : 仅按文件名升序（自然排序）
    """
    if mode == "size_desc":
        models.sort(key=lambda m: (-m.size, natural_key(m.name)))
    elif mode == "name":
        models.sort(key=lambda m: (natural_key(os.path.basename(m.name)), natural_key(m.dir)))
    else:  # dir_name（默认）：先目录、后文件名，均从小到大
        models.sort(key=lambda m: (natural_key(m.dir), natural_key(os.path.basename(m.name))))
    return models


def _apply_shard_filter(items):
    """多文件分片模型只保留「第一个启动文件」（-00001-of-）。

    - 属于同一组（同目录、同 base）的分片合并为一项，仅展示 idx=1；
    - 该项 group_size = 全部分片大小之和；
    - 若缺少第 1 个分片则整组不显示（无法启动）。
    """
    groups = {}   # (dir, base) -> {"first": ModelInfo|None, "total": int}
    plain = []
    for it in items:
        m = SHARD_RE.match(os.path.basename(it.name))
        if not m:
            plain.append(it)
            continue
        key = (it.dir, m.group("base").lower())
        g = groups.setdefault(key, {"first": None, "total": 0})
        g["total"] += it.size
        idx = int(m.group("idx"))
        total = int(m.group("total"))
        if idx == 1 and (g["first"] is None):
            it.shard_idx = 1
            it.shard_total = total
            g["first"] = it
    out = list(plain)
    for g in groups.values():
        first = g["first"]
        if first is not None:
            first.group_size = max(g["total"], first.size)
            out.append(first)
    return out


def scan_models(llama_dir, max_depth=MAX_SCAN_DEPTH):
    models, mmprojs = [], []
    if not llama_dir or not os.path.isdir(llama_dir):
        return models, mmprojs
    base = os.path.abspath(llama_dir)
    for root, dirs, files in os.walk(llama_dir):
        rel = os.path.relpath(root, base)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        # 跳过无关目录；超过最大深度则不再下钻
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if depth >= max_depth:
            dirs[:] = []
        for fn in files:
            lower = fn.lower()
            if not lower.endswith(MODEL_EXT):
                continue
            if _is_partial(fn):
                continue
            path = os.path.join(root, fn)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            is_mm = lower.startswith("mmproj") or "mmproj" in lower
            info = ModelInfo(path, fn, size, is_mm, root)
            (mmprojs if is_mm else models).append(info)
    # 多文件分片模型：只保留第一个启动文件（功能 8）
    models = _apply_shard_filter(models)
    mmprojs = _apply_shard_filter(mmprojs)
    return models, mmprojs


def find_mmproj_for(model, mmprojs):
    """严格按目录配对：只使用与主模型同一目录下的视觉投影，保证主模型与视觉模型一致。"""
    if not mmprojs:
        return None
    for m in mmprojs:
        if m.dir == model.dir:
            return m
    return None


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"
