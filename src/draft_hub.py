# -*- coding: utf-8 -*-
"""在 HuggingFace 上找「与某个主模型配套的投机解码草稿文件」的纯逻辑。

界面（src/ui/draft_download.py）负责线程和控件，这里只做可以离线单测的事：
把仓库/文件列表变成「推荐下载清单」，并说明每一项能不能直接下载。

要点（都来自实测）：
- 官方 GGUF 仓库（ggml-org，以及 unsloth 等把草稿放在同一仓库 MTP/、DFLASH/ 子目录里的）
  能直接下 .gguf 用；第三方（z-lab / incoai / RadicArk 等）多数只放 safetensors 权重，
  要自己 `convert_hf_to_gguf.py --target-model-dir` 转，这类文件不在列表接口里
  （列表接口只收 GGUF 仓库），所以这里给的是提示文案而不是假下载项。
- 草稿必须和主模型放在**同一个目录**才会被扫描器配对（见 model_scanner.drafts_for
  的 a.dir == model.dir），所以下载目标固定为主模型所在目录。
"""

import os
import re

from .i18n import t
from .spec_decode import SPEC_IDS, _norm_tokens

# 这些组织的仓库是「直接下就能用」的 GGUF 发布方
OFFICIAL_ORGS = ("ggml-org", "ggml", "unsloth", "bartowski", "cjpgr87")

# 路径里的关键词 → 投机方式 id。顺序重要：dflash2 要在 dflash 之前判
DRAFT_KEYWORDS = (
    ("dflash2", "dflash2"),
    ("dflash", "dflash"),
    ("dspark", "dspark"),
    ("lilicorr", "lilicorr"),
    ("eagle3", "eagle3"),
    ("eagle", "eagle3"),
    ("mtp", "mtp"),
)

# 明显是完整模型（不是草稿头）的名字特征：带量化后缀的一般是主模型
QUANT_SUFFIX_RE = re.compile(r"\bq[0-8][_0-9a-z]*\b|f16|bf16|f32|iq[0-9]", re.IGNORECASE)


def guess_spec_kind(path):
    """从仓库内路径猜草稿类型（返回 SPEC_IDS 里的 id，猜不到返回 ""）。

    只看路径字符串，所以是「提示」级别；下载完由扫描器读 GGUF 内容重新定性。
    """
    low = str(path or "").lower()
    for kw, sid in DRAFT_KEYWORDS:
        if kw in low and sid in SPEC_IDS:
            return sid
    return ""


def is_draft_like(path):
    """这个 .gguf 像不像草稿头：命中关键词，且不是「xx-Q4_K_M.gguf」这种主模型命名。"""
    sid = guess_spec_kind(path)
    if not sid:
        return False
    base = os.path.basename(str(path or ""))
    # MTP 目录里的 Q4_K_M 也可能是草稿（官方就把草稿量化后放 MTP/ 下），
    # 所以只在「没有目录线索、文件名又带量化后缀」时才排除
    if QUANT_SUFFIX_RE.search(base) and "/" not in str(path or ""):
        return False
    return True


def base_query(model_path, gguf_info=None):
    """拿主模型的基础名去搜仓库：优先 GGUF 元数据里的 general.base_model.name。"""
    info = gguf_info if gguf_info is not None else {}
    for key in ("base_model_name", "general.name", "name"):
        val = str(info.get(key) or "").strip()
        if val:
            return val
    fn = os.path.basename(str(model_path or ""))
    if fn.lower().endswith(".gguf"):
        fn = fn[:-5]
    return re.sub(r"[-_.](Q\d[0-9A-Za-z_]*|BF16|F16|F32)$", "", fn, flags=re.IGNORECASE)


def org_of(repo_id):
    return str(repo_id or "").split("/")[0].lower()


def is_official(repo_id):
    return org_of(repo_id) in OFFICIAL_ORGS


def score_repo(repo_id, base_tokens):
    """仓库排序分：官方 > 名字和主模型对得上 > 下载量。"""
    low = str(repo_id or "").lower()
    toks = _norm_tokens(low)
    overlap = len(toks & base_tokens) if base_tokens else 0
    score = 1000 if is_official(repo_id) else 0
    score += 30 * overlap
    return score


def rank_repos(repos, base_name):
    """给仓库列表打分排序（repos: [{id, downloads, ...}]）。"""
    base_tokens = _norm_tokens(base_name)
    out = []
    for r in repos or []:
        rid = str((r or {}).get("id") or "").strip()
        if not rid:
            continue
        dl = int(r.get("downloads") or 0)
        out.append(dict(r, id=rid,
                        score=score_repo(rid, base_tokens) + min(dl // 1000, 50),
                        official=is_official(rid)))
    out.sort(key=lambda x: (-x["score"], -int(x.get("downloads") or 0), x["id"]))
    return out


def pick_files(repo_id, files, base_name, limit=8):
    """从一个仓库的文件列表里挑草稿候选，返回排好序的 [{repo,path,size,kind,official,note}]。"""
    base_tokens = _norm_tokens(base_name)
    official = is_official(repo_id)
    rows = []
    for f in files or []:
        path = str((f or {}).get("path") or "").strip()
        if not path or not path.lower().endswith(".gguf") or not is_draft_like(path):
            continue
        kind = guess_spec_kind(path)
        toks = _norm_tokens(path)
        score = 100 if official else 0
        score += 10 * len(toks & base_tokens) if base_tokens else 0
        rows.append({
            "repo": repo_id,
            "path": path,
            "size": int((f or {}).get("size") or 0),
            "kind": kind,
            "official": official,
            "score": score,
            "note": t('官方 GGUF，直接下载可用') if official
                    else t('第三方仓库：一般是已转好的 GGUF，个别需自行转换'),
        })
    rows.sort(key=lambda r: (-r["score"], -r["size"]))
    return rows[:limit]


def dest_path(model_dir, repo_id, path, taken=()):
    """下载落盘位置：主模型同目录（扫描器只在这里配对草稿）。

    不同仓库可能有同名文件，重名时把仓库名拼进去，避免两个草稿互相覆盖。
    """
    name = os.path.basename(str(path or "model.gguf")) or "model.gguf"
    existing = {str(p).lower() for p in taken}
    cand = os.path.join(model_dir, name)
    if cand.lower() not in existing:
        return cand
    stem, ext = os.path.splitext(name)
    slug = org_of(repo_id).replace("-", "_") or "hf"
    return os.path.join(model_dir, f"{stem}_{slug}{ext}")


def conversion_hint(kind):
    """第三方草稿只有 safetensors 时怎么办（这类仓库不在 GGUF 列表接口里，给文字指引）。"""
    label = (kind or "").upper() or "DFlash"
    return t(
        '如果这里搜不到你要的 {0} 草稿：z-lab / incoai / RadixArk 这些原作者仓库通常只放 '
        'safetensors 权重，需要自己转一次\n'
        '    python convert_hf_to_gguf.py <权重目录> --target-model-dir <主模型.gguf> '
        '--outfile 草稿.gguf\n'
        '转完把 草稿.gguf 放到主模型同一个目录，回到本界面点「刷新」就能看到。'
    ).format(label)
