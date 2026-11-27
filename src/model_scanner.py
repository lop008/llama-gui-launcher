import os
import re

from .gguf_reader import (ROLE_DRAFT, ROLE_IMATRIX, ROLE_MMPROJ, ROLE_MODEL,
                          QUANT_RE, classify_gguf)
from .i18n import t

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
                 "shard_idx", "shard_total", "group_size", "role", "kind", "why")

    def __init__(self, path, name, size, is_mmproj, dir_,
                 role=ROLE_MODEL, kind="", why=""):
        self.path = path
        self.name = name
        self.size = size
        self.is_mmproj = is_mmproj
        self.dir = dir_
        # 分片信息：shard_idx=1 表示这是「启动文件」（第一个分片）
        self.shard_idx = None
        self.shard_total = None
        self.group_size = size  # 多文件模型的总大小（单文件时=size）
        # 内容角色：model / mmproj / draft / imatrix；kind 仅 draft 有值（mtp/dflash/...）
        self.role = role
        self.kind = kind
        self.why = why           # 判定依据（判定与直觉不符时可拿这个查原因）


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


def scan_models(llama_dir, max_depth=MAX_SCAN_DEPTH, probe=True):
    """扫描模型目录，返回 (主模型列表, 辅助文件列表)。

    辅助文件 = 视觉投影(mmproj) + 投机草稿头(MTP/DFlash/DSpark/EAGLE…) + 量化标定(imatrix)，
    每项带 .role / .kind。分流**以 GGUF 文件内容为准**，文件名只作兜底；
    读不出内容又没可疑文件名的，一律当主模型显示（宁可多列，绝不误藏能用的模型）。
    """
    models, aux = [], []
    if not llama_dir or not os.path.isdir(llama_dir):
        return models, aux
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
            shard = SHARD_RE.match(fn)
            if probe and not (shard and int(shard.group("idx")) > 1):
                # 非首分片只含权重、没有完整张量表，判角色会误判成「碎片」，跳过读头
                role, kind, why = classify_gguf(path)
            else:
                role, kind, why = ROLE_MODEL, "", ""
            info = ModelInfo(path, fn, size, role == ROLE_MMPROJ, root, role, kind, why)
            (aux if role in (ROLE_MMPROJ, ROLE_DRAFT, ROLE_IMATRIX) else models).append(info)
    # 多文件分片模型：只保留第一个启动文件（功能 8）
    models = _apply_shard_filter(models)
    aux = _apply_shard_filter(aux)
    return models, aux


def find_mmproj_for(model, mmprojs):
    """严格按目录配对：只使用与主模型同一目录下的视觉投影，保证主模型与视觉模型一致。"""
    if not mmprojs:
        return None
    for m in mmprojs:
        if m.dir == model.dir and (m.is_mmproj or m.role == ROLE_MMPROJ):
            return m
    return None


# 草稿头类型：越靠前越优先（同目录多个头时挑这个顺序）
DRAFT_KIND_PREF = ("dflash2", "dflash", "dspark", "lilicorr", "mtp", "eagle3", "simple")


def _base_tokens(name):
    """文件名去掉量化标记后的词集合，用于判断「这个头是不是给这个模型配的」。"""
    stem = re.sub(r"\.gguf$", "", str(name), flags=re.IGNORECASE)
    stem = QUANT_RE.sub(" ", stem)
    return {tk for tk in re.split(r"[^0-9a-z]+", stem.lower()) if len(tk) > 1}


def drafts_for(model, aux):
    """返回与主模型配套的草稿头列表（同目录，按配套度 → 类型优先级排序）。"""
    if not aux or model is None:
        return []
    mtok = _base_tokens(model.name)
    out = []
    for a in aux:
        if a.role != ROLE_DRAFT or a.dir != model.dir:
            continue
        overlap = len(mtok & _base_tokens(a.name))
        pref = DRAFT_KIND_PREF.index(a.kind) if a.kind in DRAFT_KIND_PREF else 99
        # 同类型优先：非 Old > 体积小（Q8_0 比 BF16 更省显存）；Old 转换件排最后
        old_penalty = 1 if "old" in a.name.lower() else 0
        out.append((-overlap, pref, old_penalty, a.size, a))
    out.sort(key=lambda x: x[:4])
    return [x[4] for x in out]


def find_draft_for(model, aux):
    """同目录里最配套的草稿头，没有则 None。"""
    got = drafts_for(model, aux)
    return got[0] if got else None


def role_label(role, kind=""):
    """辅助文件角色的中文（多语言）说明，用于界面标注。"""
    if role == ROLE_MMPROJ:
        return t('视觉投影')
    if role == ROLE_IMATRIX:
        return t('量化标定文件')
    if role == ROLE_DRAFT:
        return t('投机草稿头（{0}）').format(str(kind).upper()) if kind else t('投机草稿头')
    return ""


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"
