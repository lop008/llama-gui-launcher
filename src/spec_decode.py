"""投机解码（speculative decoding）能力检测：引擎支持哪些方式、主模型配不配、草稿头对不对得上。

三层事实，全部实测本机文件，不做猜测：
1. 引擎层 `engine_spec_types()`：跑一次 `llama-server --help`，解析它真正认得的
   `--spec-type` 取值。老 build 没有 draft-dflash / draft-dspark，界面据此置灰并提示更新。
2. 模型层 `model_spec_support()`：读主模型 GGUF（是否内嵌 nextn/MTP 头、有没有配套草稿文件），
   给出每种方式「可用 / 需要下载草稿 / 本机不支持 / 不适用」。
3. 文件层 `draft_matches_model()`：草稿头与主模型是否同一套（比词表 / 嵌入维度 / 架构族 /
   基础模型名），对不上时标记 `valid=False`，自动挑选会跳过它，而不是直接让服务起不来。

本模块不碰 Qt、不写配置，纯函数 + 结果缓存，便于单测。
"""
import os
import re
import subprocess

from .gguf_reader import (ROLE_DRAFT, QUANT_RE, _name_role, probe_gguf, probe_model_gguf)
from .i18n import t

CREATE_NO_WINDOW = 0x08000000

# 下拉框候选顺序（默认值；界面可拖动改，作为「自动」的优先级）。
# 顺序按「收益高且更容易可用」在前：内嵌 MTP → 各类草稿头 → 小模型草稿 → n-gram。
# 取值以本机 llama-server --help 的 --spec-type 列表为准（build 12780 实测 13 项，
# none 由界面上的「不启用」承担）。
SPEC_IDS = ("mtp", "dflash2", "dflash", "dspark", "lilicorr", "eagle3", "simple",
            "ngram-mod", "ngram-map-k", "ngram-map-k4v", "ngram-cache", "ngram-simple")

# id → (llama.cpp --spec-type 取值, 是否必须外部草稿文件)
SPEC_CLI = {
    "mtp": ("draft-mtp", False),          # 模型自带 nextn 头时无需外部文件
    "dflash2": ("draft-dflash2", True),
    "dflash": ("draft-dflash", True),     # 官方注：dflash2/dspark/lilicorr 也能被它自动识别
    "dspark": ("draft-dspark", True),
    "lilicorr": ("draft-lilicorr", True),
    "eagle3": ("draft-eagle3", True),
    "simple": ("draft-simple", True),
    "ngram-mod": ("ngram-mod", False),
    "ngram-map-k": ("ngram-map-k", False),
    "ngram-map-k4v": ("ngram-map-k4v", False),
    "ngram-cache": ("ngram-cache", False),
    "ngram-simple": ("ngram-simple", False),
}

# 免草稿方式（这些不需要任何额外文件，白捡的加速）
NO_DRAFT_IDS = frozenset(("mtp", "ngram-mod", "ngram-map-k", "ngram-map-k4v",
                          "ngram-cache", "ngram-simple"))

# 草稿架构族：这些是草稿头自己的架构名，允许与主模型架构不同。
# 例如 DSpark 草稿的 general.architecture 是 dflash，主模型是 inkling2_loop。
DRAFT_ARCHES = ("dflash", "dflash2", "dspark", "lilicorr", "eagle", "eagle3")

# 免草稿方式的说明（这些不需要任何额外文件，白捡的加速）
_SPEC_LABELS = {
    "mtp": "MTP",
    "dflash2": "DFlash 2",
    "dflash": "DFlash",
    "dspark": "DSpark",
    "lilicorr": "LiliCorr",
    "eagle3": "EAGLE-3",
    "simple": "",            # 「小模型草稿」，见 spec_label
    "ngram-mod": "n-gram-mod",
    "ngram-map-k": "n-gram-map-k",
    "ngram-map-k4v": "n-gram-map-k4v",
    "ngram-cache": "n-gram-cache",
    "ngram-simple": "n-gram-simple",
}

# 状态常量
ST_OK = "ok"                  # 现在就能用
ST_NEED_DRAFT = "need_draft"   # 引擎和模型都行，但缺草稿文件（可下载）
ST_NO_ENGINE = "no_engine"     # 本机 llama-server 不认这个值
ST_NO = "no"                  # 主模型没有相应结构、也找不到草稿

# 下拉里不许选中的状态：选了也必然不生效。
# 「缺草稿」故意不在其中——点「下载草稿」补齐就能用，堵死反而挡住正常路径。
UNSELECTABLE_STATES = (ST_NO_ENGINE, ST_NO)


def spec_selectable(row):
    """这个投机解码方式当前能不能被用户选中（row=None 表示还没检测完，先放行）。"""
    return row is None or row.get("state") not in UNSELECTABLE_STATES


def spec_label(spec_id):
    """下拉框显示名。"""
    if spec_id == "simple":
        return t('小模型草稿')
    return _SPEC_LABELS.get(spec_id, spec_id)


# ---------------------------------------------------------------- 1. 引擎层
def engine_spec_types(exe_path, timeout=15):
    """解析本机 llama-server 支持的 --spec-type 取值集合；拿不到返回 None（界面按“未知”处理）。"""
    if not exe_path or not os.path.isfile(exe_path):
        return None
    cache = globals().setdefault("_ENGINE_CACHE", {})
    try:
        st = os.stat(exe_path)
        stamp = (int(st.st_mtime), st.st_size)
    except OSError:
        return None
    key = os.path.abspath(exe_path)
    if key in cache and cache[key][0] == stamp:
        return cache[key][1]
    types = None
    try:
        r = subprocess.run([exe_path, "--help"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=CREATE_NO_WINDOW)
        text = (r.stdout or "") + "\n" + (r.stderr or "")
        types = _parse_spec_types(text)
    except Exception:
        types = None
    if len(cache) > 64:
        cache.clear()
    cache[key] = (stamp, types)
    return types


def _parse_spec_types(help_text):
    """从 --help 文本里抠出 --spec-type 的取值集合。

    llama.cpp 的帮助按列宽折行，实测会把 "ngram-cache" 劈成同行的 "n" 加
    **顶格**续行的 "gram-cache"（说明文字是缩进的，不会误吃），所以要带顶格续行再切分。
    """
    if not help_text:
        return None
    lines = help_text.splitlines()
    for i, line in enumerate(lines):
        if "--spec-type" not in line:
            continue
        m = re.search(r"--spec-type\s+([A-Za-z0-9,\-\s]+)", line)
        if not m:
            continue
        blob = m.group(1)
        j = i + 1
        while (j < len(lines) and lines[j].strip() and not lines[j][:1].isspace()
               and re.fullmatch(r"[A-Za-z0-9,\-\s]+", lines[j])):
            blob += re.sub(r"\s+", "", lines[j])
            j += 1
        vals = {v.strip().lower() for v in re.sub(r"\s+", "", blob).split(",") if v.strip()}
        if vals:
            return vals
    return None


# ---------------------------------------------------------------- 2/3. 模型与草稿层
def _norm_tokens(text):
    """把模型名切成可比的词集（去量化标记、忽略大小写与符号）。"""
    s = re.sub(r"\.gguf$", "", str(text), flags=re.IGNORECASE)
    s = QUANT_RE.sub(" ", s)
    return {tk for tk in re.split(r"[^0-9a-z]+", s.lower()) if len(tk) > 1}


def _is_draft_arch(arch):
    """草稿头自己的架构名（dflash/dspark/...）或外挂 MTP 架构（xxx-mtp）。"""
    al = str(arch or "").lower()
    if not al:
        return False
    if al.startswith(DRAFT_ARCHES):
        return True
    return al == "mtp" or al.endswith("-mtp") or al.endswith("_mtp")


def _name_match(a, b):
    """文件名/基础模型名的词集是否有交集；判不出时返回 True（不拦人）。"""
    names_a = " ".join([a.get("base") or "", a.get("base_model") or "", a.get("name") or ""])
    names_b = " ".join([b.get("base") or "", b.get("base_model") or "", b.get("name") or ""])
    ta, tb = _norm_tokens(names_a), _norm_tokens(names_b)
    if not ta or not tb:
        return True, ""
    core = {tk for tk in tb if re.search(r"\d", tk)} or tb
    if core & ta:
        return True, ""
    return False, t('命名看不出与 {0} 的对应关系').format(
        b.get("base") or b.get("base_model") or "")


def draft_matches_model(draft_path, model_path):
    """草稿头与主模型是否配套，返回 (是否配套, 原因)。

    判定顺序：
    1. 词表大小（vocab_size）必须一致——草稿和主模型必须共享同一套 tokenizer；
    2. 嵌入维度（embedding_length）必须一致；
    3. 架构：允许草稿架构族（dflash/dspark/...）或外挂 MTP（xxx-mtp）与主模型不同；
    4. 词表/维度都读不出时，才退回按命名判断，避免误杀。

    判不出时 (True, "")——不拦人；能确认不匹配时才返回 False。
    """
    a = probe_gguf(draft_path)
    b = probe_model_gguf(model_path)
    if not a or not b:
        return True, ""
    va, vb = int(a.get("vocab_size") or 0), int(b.get("vocab_size") or 0)
    ea, eb = int(a.get("embedding_length") or 0), int(b.get("embedding_length") or 0)
    if va and vb and va != vb:
        return False, t('词表大小不一致（{0} vs {1}）').format(va, vb)
    if ea and eb and ea != eb:
        return False, t('嵌入维度不一致（{0} vs {1}）').format(ea, eb)

    aa, ab = str(a.get("arch") or "").lower(), str(b.get("arch") or "").lower()
    if aa and ab and aa != ab and not _is_draft_arch(aa):
        return False, t('架构不一致（{0} vs {1}）').format(aa, ab)

    # 词表和维度都已经确认一致时，命名不再作为硬条件（外挂 MTP 常叫 mtp-q2_0）。
    if va and vb and ea and eb:
        return True, ""
    ok, why = _name_match(a, b)
    return ok, why


def model_spec_support(model_path, drafts=(), engine_types=None):
    """给出每个投机方式对该主模型的状态。

    drafts: 同目录可用的草稿文件（model_scanner.ModelInfo 或路径字符串）。
    engine_types: engine_spec_types() 的结果，None 表示未知（不因引擎置灰）。
    返回 [{"id","cli","label","state","reason","draft","valid","match_reason","embedded"}]
    顺序同 SPEC_IDS。

    注意：`state=ok` 只表示「引擎认、文件在」；草稿是否真的配套看 `valid`。
    自动挑选和启动前校验都会同时检查 state 与 valid。
    """
    facts = probe_model_gguf(model_path)
    embedded = bool(facts and (facts["nextn_layers"] > 0 or
                   any("nextn" in n.lower() or "eh_proj" in n.lower()
                       for n in facts["names"][:4000])))
    by_kind = {}
    for d in drafts or ():
        path = getattr(d, "path", d)
        kind = getattr(d, "kind", "") or ""
        if not kind:          # 只有路径时按文件名猜
            role, kind = _name_role(path)
            if role != ROLE_DRAFT:
                kind = "mtp" if "mtp" in os.path.basename(str(path)).lower() else ""
        if not kind:
            continue
        try:
            valid, why = draft_matches_model(path, model_path)
        except Exception:
            valid, why = True, ""
        by_kind.setdefault(kind, []).append({"path": path, "valid": valid, "why": why})

    def _pick(kind):
        items = by_kind.get(kind) or []
        for it in items:
            if it["valid"]:
                return it
        return items[0] if items else None

    out = []
    for sid in SPEC_IDS:
        cli, needs = SPEC_CLI[sid]
        state, reason, draft, valid, match_reason = ST_OK, "", None, True, ""
        if sid == "mtp":
            hit = _pick("mtp")
            if embedded:
                state = ST_OK
                reason = t('模型已内嵌 MTP 头')
            elif hit:
                state = ST_OK
                reason = t('使用外部 MTP 头')
                draft, valid, match_reason = hit["path"], hit["valid"], hit["why"]
            else:
                state = ST_NEED_DRAFT
                reason = t('模型未内嵌 MTP，需下载对应草稿头')
        elif sid in NO_DRAFT_IDS:
            state = ST_OK
            reason = t('无需草稿文件')
        else:
            hit = _pick(sid)
            if not hit and sid == "dflash":
                # 官方注释：draft-dflash 也能自动识别 dflash2 / dspark / lilicorr 草稿
                for alt in ("dflash2", "dspark", "lilicorr"):
                    hit = _pick(alt)
                    if hit:
                        break
            if hit:
                draft, valid, match_reason = hit["path"], hit["valid"], hit["why"]
                state = ST_OK
                reason = t('已找到配套草稿')
            else:
                state = ST_NEED_DRAFT
                reason = t('需下载 {0} 草稿模型').format(spec_label(sid))
        if engine_types is not None and cli not in engine_types:
            state, reason = ST_NO_ENGINE, t('本机 llama-server 不支持，请更新 llama.cpp')
        out.append({"id": sid, "cli": cli, "label": spec_label(sid),
                    "state": state, "reason": reason, "draft": draft,
                    "valid": bool(valid), "match_reason": match_reason,
                    "embedded": bool(embedded and sid == "mtp")})
    return out


def pick_auto(rows, order=None):
    """按优先级顺序挑第一个「引擎支持 + 草稿配套」的方式，返回 (id, cli, draft)。"""
    by_id = {r["id"]: r for r in rows}
    for sid in (order or SPEC_IDS):
        r = by_id.get(sid)
        if r and r["state"] == ST_OK and r.get("valid", True):
            return r["id"], r["cli"], r.get("draft")
    return None, None, None
