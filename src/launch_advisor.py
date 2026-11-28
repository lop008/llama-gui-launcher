# -*- coding: utf-8 -*-
"""启动文件「合理性评估」：静态参数体检 + 硬件/模型资源估算（+ 可选的本机模型深度分析）。

为什么单独一个模块：`bat_validator` 按白名单认参数，白名单之外的 token 会被**静默丢掉**
（例如旧版 llama.cpp 的参数名、或 `--cpu-moe` 这类新增项），用户完全看不到
「这个选项本机根本不认识」。本模块反过来做：

1. `iter_script_flags()` 先把脚本里所有像参数的 token **全量**抓出来（不做白名单过滤）；
2. `engine_flags()` 跑本机 `llama-server --help`，得到「本机这一版到底认识哪些参数」；
3. `check_param_names()` 逐个核对：不认识 / 疑似改名 / 重复出现 / 取值可疑；
4. `machine_profile()` + `model_profile()` + `assess()` 结合 CPU、内存、显存、磁盘与
   模型元数据（GGUF）估算吃不吃得住，给出可执行的调整建议；
5. `request_ai_report()` 是**可选**增强：只有服务已经在跑、且用户手动点「让模型分析」
   时，才把上面这些结构化数据发给本机模型要一份报告。没有任何模型时，
   上面 1~4 步就是完整可用的内置机制。

估算口径都写在返回文案里（权重体积 + KV 缓存 + 计算缓存经验值），不假装精确。
"""

import difflib
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request

from .bat_validator import (_FLAG_FLAGS, _PARAM_FLAGS, _resolve, _tokenize,
                            normalize_script, parse_script)
from .gguf_reader import _quant_label, human_params, read_gguf_info
from .i18n import t

CREATE_NO_WINDOW = 0x08000000

#: 别名归一表：`-c` 与 `--ctx-size` 是同一个参数，重复检查必须按归一后的名字算
_CANON = {}
for _k, _v in _PARAM_FLAGS.items():
    _CANON[_k] = _v
for _k, _v in _FLAG_FLAGS.items():
    _CANON[_k] = _v


def canon(flag):
    """参数别名归一（不在表里的原样返回，未知参数按字面判重）。"""
    return _CANON.get(str(flag).lower(), str(flag).lower())

#: 看起来像命令行参数的 token（-m / --cpu-moe / --port=8080）
_FLAG_RE = re.compile(r"^-{1,2}[A-Za-z][\w-]*$")
#: 数值型参数：值不是整数/`all` 就是写错了
_NUM_FLAGS = ("-c", "--ctx-size", "-ngl", "--n-gpu-layers", "--gpu-layers",
              "-b", "--batch-size", "-ub", "--ubatch-size", "-t", "--threads",
              "--port", "-np", "--parallel", "-n", "--predict", "--n-predict",
              "--timeout", "-ctk", "-ctv")
#: KV 缓存每元素字节数（q8_0 / q4_0 是含 super-block 缩放开销的近似值，文案里如实说明）
_KV_BYTES = {"f16": 2.0, "bf16": 2.0, "q8_0": 1.06, "q4_0": 0.56, "q4_1": 0.56,
             "iq4_nl": 0.55, "f32": 4.0}
#: 计算缓存（激活值、CUDA 上下文等）相对权重体积的经验占比（仅在拿不到 KV 头数时兜底）
_COMPUTE_BUFFER_RATIO = 0.12
#: 非 FA 路径物化两份：KQ 分数 + softmax 结果，每元素 4 字节（fp32）
_ATTN_BYTES_PER_TOKEN_CTX = 8.0
#: 实测倍率（Qwen3-0.6B Q8_0；ctx 8192 -ub 128…4096、ctx 2048…32768 共 13 个点，
#: 理论式与实测的比值稳定在 1.06）
_ATTN_OVERHEAD = 1.06
#: 每个「微批 token」的固定开销（MiB）：实测 ctx→0 时 0.5703 MiB/ub 的截距
_ATTN_PER_TOKEN_MIB = 0.04
#: Flash Attention 下 ctx 相关项只剩约 3%（实测 32K/ub512：1108→58.5 MiB），
#: 但每 token 的固定开销还在（约 0.05 MiB/ub），因为 FA 仍按块处理整批 token
_FA_CTX_RATIO = 0.031
_FA_PER_TOKEN_MIB = 0.053


# ------------------------------------------------------------------ 脚本侧扫描
def iter_script_flags(text, path=""):
    """抓出脚本里**所有**像参数的 token（不做白名单过滤，废弃/改名项靠这里暴露）。

    返回 `[{"flag": "--cpu-moe", "value": "8", "attached": True, "line": 12}, …]`；
    `attached=False` 表示值是「下一个独立 token」，对布尔开关来说它其实不是值，
    所以取值合法性判定只信 `attached=True` 与已知取值参数（见 check_param_values）。
    """
    _vars, phys = normalize_script(text, path)
    out = []
    for kind, eff in phys:
        if kind != "head" or not eff.strip():
            continue
        line_no = eff[1] if isinstance(eff, tuple) else 0
        toks = _tokenize(eff[0] if isinstance(eff, tuple) else eff)
        for i, tok in enumerate(toks):
            head, sep, tail = tok.partition("=")
            if sep and _FLAG_RE.match(head):
                out.append({"flag": head.lower(), "value": tail.strip('"'),
                            "attached": True, "line": line_no})
                continue
            if not _FLAG_RE.match(tok):
                continue
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            nxt_is_flag = bool(_FLAG_RE.match(nxt)) or nxt.startswith('"-')
            out.append({"flag": tok.lower(),
                        "value": "" if nxt_is_flag else nxt.strip('"'),
                        "attached": False, "line": line_no})
    return out


def engine_flags(exe, refresh=False):
    """本机 `llama-server --help` 认识的参数名集合；拿不到返回 None（此时不做未知判定）。

    缓存键含文件修改时间与大小：更新过 llama.cpp 后缓存自动失效，
    不会拿旧版本的参数表去判新二进制「不认识」。
    """
    if not exe or not os.path.isfile(exe):
        return None
    try:
        st = os.stat(exe)
        key = (os.path.abspath(exe), int(st.st_mtime), st.st_size)
    except OSError:
        return None
    cache = getattr(engine_flags, "_cache", None)
    if cache is None:
        cache = engine_flags._cache = {}
    if not refresh and key in cache:
        return cache[key]
    flags = None
    try:
        proc = subprocess.run([exe, "--help"], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=20,
                              creationflags=CREATE_NO_WINDOW)
        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        found = set()
        for raw in re.findall(r"-{1,2}[A-Za-z][\w-]*", text):
            name = raw.rstrip(".,:;)][=")
            if len(name) >= 2:
                found.add(name.lower())
        flags = found or None
    except (OSError, subprocess.SubprocessError):
        flags = None
    cache[key] = flags
    return flags


def engine_flags_cached(exe):
    """只读缓存版 `engine_flags`：给「生成命令行」这种界面路径调用，绝不子进程阻塞。

    缓存还没预热好时返回 None，调用方按旧写法处理即可（不是错误）。
    """
    if not exe or not os.path.isfile(exe):
        return None
    try:
        st = os.stat(exe)
        key = (os.path.abspath(exe), int(st.st_mtime), st.st_size)
    except OSError:
        return None
    return (getattr(engine_flags, "_cache", None) or {}).get(key)


def prefetch_engine_flags(exe):
    """后台线程预热 `--help` 参数表（启动时调用一次），界面生成命令时就不用等。"""
    if not exe or not os.path.isfile(exe):
        return

    def work():
        try:
            engine_flags(exe)
        except Exception:
            pass

    threading.Thread(target=work, daemon=True).start()


def supports_flag(exe, flag):
    """本机版本是否认识某个参数；缓存未就绪返回 None（未知，按支持处理）。"""
    engine = engine_flags_cached(exe)
    if engine is None:
        return None
    return flag.lower() in engine


#: 官方已删除的参数 → 新版写法。llama.cpp 0.4.1（2026-09）把
#: `--mmap/--no-mmap/--mlock/--direct-io` 合并成 `-lm/--load-mode`
#: （取值 auto / none / mmap / mlock / mmap+mlock / dio），
#: 老参数在新版本上是 `error: invalid argument`，所以必须明确告诉用户怎么改。
REMOVED = {
    "--mlock": "-lm mmap+mlock",
    "--mmap": "-lm mmap",
    "--no-mmap": "-lm none",
    "-dio": "-lm dio",
    "--direct-io": "-lm dio",
}


def _suggest(flag, engine):
    """在本机认识的参数里找「最可能是写错了」的名字；不可信就返回空。

    只认「长度包含关系」的近似：`--ctx-sizee` → `--ctx-size` 这种是打错字；
    而 `--no-mmap` 与 `--no-mmproj` 相似度也很高，却完全是两个功能，
    这种宁可不说，也不要给用户一条把方向带偏的建议。
    """
    if not engine:
        return ""
    hits = difflib.get_close_matches(flag, sorted(engine), n=3, cutoff=0.7)
    best = ""
    for cand in hits:
        if cand == flag:
            continue
        if cand.startswith(flag) or flag.startswith(cand):
            if abs(len(cand) - len(flag)) <= 3 and len(cand) > len(best):
                best = cand
    return best


def replacement(flag, engine):
    """官方已删除参数的新写法。

    `engine` 为 None（没取到本机参数表）时按新版给建议；本机没有
    `-lm/--load-mode`（旧版 llama.cpp）时返回空——旧版本来认 `--mlock`，
    不能建议一个本机同样不认的参数。
    """
    new = REMOVED.get(str(flag).lower())
    if not new:
        return ""
    if engine is None:
        return new
    return new if "--load-mode" in engine else ""


def check_param_names(raw_flags, engine):
    """参数有效性检查：本机不认识 / 疑似改名 / 重复设置。

    返回 [(检查项, 状态, 说明)]。`engine` 为 None（拿不到 --help）时只查重，
    绝不因为「我没查到参数表」就判用户的脚本有问题。
    """
    items = []
    uniq_flags = list(dict.fromkeys(r["flag"] for r in raw_flags))
    unknown = [f for f in uniq_flags if engine is not None and f not in engine]
    if unknown:
        lines = []
        for flag in unknown:
            new = replacement(flag, engine)
            if new:
                # 官方删掉的参数（如 --mlock → -lm mmap+mlock）：直接给新写法，
                # 比只说「不认识」有用得多，也免得用户去搜到过时的答案
                lines.append(t('{0} 已被新版 llama.cpp 删除，请改用 {1}').format(flag, new))
            else:
                hint = _suggest(flag, engine)
                lines.append(t('{0} → 本机不认识（是不是想写 {1}？）').format(flag, hint)
                             if hint else t('{0} → 本机不认识').format(flag))
        items.append((t('废弃/未知参数'), "warn", "\n".join(lines)))
    elif engine is None:
        items.append((t('废弃/未知参数'), "ok",
                      t('未取到本机参数表（llama-server --help），跳过未知项检查')))
    else:
        items.append((t('废弃/未知参数'), "ok",
                      t('脚本里的 {0} 个参数本机 llama-server 都认识').format(len(uniq_flags))))

    # 重复设置：按归一后的参数名算（-c 4096 与 --ctx-size 8192 是同一个参数），
    # llama-server 是「后面出现的覆盖前面」，所以直接把最终值告诉用户。
    order, groups = [], {}
    for rec in raw_flags:
        key = canon(rec["flag"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(rec)
    dups = []
    for key in order:
        recs = groups[key]
        if len(recs) > 1:
            spell = "、".join(sorted({r["flag"] for r in recs}))
            final = next((r["value"] for r in reversed(recs) if r["value"]), "")
            dups.append(t('{0}（{1}）设置了 {2} 次，最终生效值 {3}').format(
                spell, key, len(recs), final or t('(无值)')))
    if dups:
        items.append((t('重复参数'), "warn", "\n".join(dups)))
    else:
        items.append((t('重复参数'), "ok", t('没有重复设置的参数')))
    return items


def check_param_values(params):
    """取值合法性与互相矛盾的检查（只查能确定口径的几项，不做猜测式批评）。

    `params` 用 `parse_script` 的规范参数名（ctx / batch / ubatch / threads / port…）。
    返回 (items, 解析出的数字)，后者交给资源评估复用，避免同一个值解析两遍口径不一。
    """
    items = []
    bad = []

    def _num(key, flag):
        raw = str(params.get(key, "") or "").strip()
        if not raw:
            return None
        if raw.lower() == "all":
            return -1                       # -ngl all = 全部层进显存
        try:
            return int(float(raw))
        except ValueError:
            bad.append(t('{0} 的取值不是数字：{1}').format(flag, raw))
            return None

    ctx = _num("ctx", "-c/--ctx-size")
    batch = _num("batch", "-b/--batch-size")
    ubatch = _num("ubatch", "-ub")
    ngl = _num("ngl", "-ngl")
    threads = _num("threads", "-t/--threads")
    slots = _num("slots", "-np/--parallel")
    port = _num("port", "--port")
    if port is not None and not (1 <= port <= 65535):
        bad.append(t('--port 超出 1-65535：{0}').format(port))
    if ubatch and batch and ubatch > batch:
        bad.append(t('-ub（{0}）大于 -b（{1}）：微批不应超过批大小').format(ubatch, batch))
    cores = os.cpu_count() or 0
    if threads and cores and threads > cores:
        bad.append(t('-t {0} 超过本机逻辑核心数 {1}，只会增加线程切换开销').format(threads, cores))
    if ctx is not None and ctx < 0:
        bad.append(t('-c 不能是负数：{0}').format(params.get("ctx")))
    if slots is not None and slots > 8:
        bad.append(t('-np {0} 会让 KV 缓存按倍数增长，个人机器建议 ≤ 8').format(slots))
    if bad:
        items.append((t('参数取值'), "warn", "\n".join(bad)))
    else:
        items.append((t('参数取值'), "ok", t('上下文/批大小/线程/端口等取值范围正常')))
    return items, {"ctx": ctx, "batch": batch, "ubatch": ubatch, "ngl": ngl,
                   "threads": threads, "slots": slots, "port": port}


# ------------------------------------------------------------------ 本机画像
def machine_profile(gpus=None, vram_total_mb=0.0, model_dir=""):
    """CPU / 内存 / 显存 / 磁盘余量。显存与 GPU 名单由界面传入（启动器已经探测过）。"""
    prof = {"cpu": "", "cores_logical": os.cpu_count() or 0,
            "ram_total_gb": 0.0, "ram_avail_gb": 0.0,
            "disk_free_gb": 0.0, "gpus": list(gpus or []),
            "vram_total_gb": (float(vram_total_mb or 0) / 1024.0)}
    try:
        import psutil
        prof["cpu"] = (platform_processor() or "").strip()
        vm = psutil.virtual_memory()
        prof["ram_total_gb"] = vm.total / 2 ** 30
        prof["ram_avail_gb"] = vm.available / 2 ** 30
        try:
            prof["cores_physical"] = psutil.cpu_count(logical=False) or 0
        except Exception:
            prof["cores_physical"] = 0
    except ImportError:
        pass
    probe = model_dir or os.path.abspath(".")
    probe = probe if os.path.isdir(probe) else os.path.dirname(probe)
    try:
        prof["disk_free_gb"] = shutil.disk_usage(probe or ".").free / 2 ** 30
    except OSError:
        pass
    return prof


def platform_processor():
    """CPU 型号名（Windows 上读环境变量，比 platform.processor() 更实）。"""
    for key in ("PROCESSOR_IDENTIFIER",):
        val = os.environ.get(key)
        if val:
            return val
    try:
        import platform
        return platform.processor()
    except Exception:
        return ""


# ------------------------------------------------------------------ 模型画像
def model_profile(path):
    """读 GGUF 元数据：体积、参数量、层数、KV 头、训练上限、MoE、视觉塔、草稿头。"""
    prof = {"path": path, "exists": bool(path) and os.path.isfile(str(path))}
    if not prof["exists"]:
        return prof
    try:
        st = os.stat(path)
        prof["size_bytes"] = st.st_size
    except OSError:
        prof["size_bytes"] = 0
    try:
        info = read_gguf_info(path) or {}
    except Exception:
        info = {}
    arch = str(info.get("general.architecture") or "")
    prof["arch"] = arch
    prof["params"] = info.get("parameter_count") or 0
    prof["layers"] = int(info.get("block_count") or 0)
    prof["ctx_train"] = int(info.get("context_length") or 0)
    heads = int(info.get("head_count") or 0)
    emb = int(info.get("embedding_length") or 0)
    prof["head_kv"] = int(info.get("head_count_kv") or 0)
    prof["head_dim"] = int(info.get("key_length") or 0) or (
        emb // heads if heads and emb else 0)
    prof["experts"] = int(info.get("expert_count") or 0)
    prof["experts_used"] = int(info.get("expert_used_count") or 0)
    prof["nextn"] = int(info.get("nextn_layers") or 0)
    # 量化格式优先看文件名（UD 动态量化的 general.file_type 常写成统一名义值，不准）
    try:
        # _quant_label 返回 (标签, 是否来自文件名)
        prof["quant"] = (_quant_label(os.path.basename(str(path)), info) or ("",))[0]
    except Exception:
        prof["quant"] = str(info.get("general.file_type") or "")
    prof["mtp_hint"] = prof["nextn"] > 0
    prof["mmproj"] = _find_mmproj(path)
    return prof


def _find_mmproj(model_path):
    """同目录里有没有视觉投影文件（有却没在脚本里用 --mmproj，等于放弃看图）。"""
    d = os.path.dirname(str(model_path))
    try:
        for fn in sorted(os.listdir(d)):
            low = fn.lower()
            if low.startswith("mmproj") and low.endswith(".gguf"):
                return os.path.join(d, fn)
    except OSError:
        pass
    return ""


# ------------------------------------------------------------------ 资源评估
def kv_cache_gib(model, ctx, cache_type="f16", slots=1):
    """KV 缓存占用（GiB）估算：2(K 和 V) × 层数 × KV 头 × 头维度 × 上下文 × 字节数。

    q8_0 / q4_0 用含 super-block 缩放开销的近似系数，实际会略有出入，
    所以对外一律说「估算」。
    """
    layers = int(model.get("layers") or 0)
    head_kv = int(model.get("head_kv") or 0)
    head_dim = int(model.get("head_dim") or 0)
    if not (layers and head_kv and head_dim and ctx):
        return 0.0
    per = _KV_BYTES.get(str(cache_type or "f16").lower(), 2.0)
    total = 2.0 * layers * head_kv * head_dim * ctx * per * max(1, int(slots or 1))
    return total / 2 ** 30


def attn_scratch_gib(model, ctx, ubatch, fa_on=True, slots=1):
    """批处理激活缓冲（GiB）——「大微批 × 长上下文」顶爆显存的真正来源。

    关掉 Flash Attention 时，llama.cpp 会把 KQ 分数矩阵和 softmax 结果按
    [KV 头数, 微批, 上下文] 物化成 fp32，所以大小 ∝ **KV 头 × 微批 × 上下文**：

        MiB ≈ 微批 × (8 × KV头 × 上下文 / 2²⁰ × 1.06 + 0.04)

    开 FA 时按块计算，上下文相关项只剩约 3%，但每个 token 的固定开销仍在：

        MiB ≈ 微批 × (8 × KV头 × 上下文 / 2²⁰ × 0.03 + 0.05)

    系数全部来自本机实测（Qwen3-0.6B Q8_0，读的是 llama-server 自己打印的
    `CUDA0 compute buffer size`，与外机进程无关）：
    ctx 8192 时 -ub 128/256/512/1024/2048/4096 → 73/146/292/584/1168/2336 MiB；
    ctx 2048/4096/8192/16384/32768（-ub 512）→ 88/156/292/564/1108 MiB；
    -fa on 时 32K/ub512 → 58.5 MiB、32K/ub2048 → 232.6 MiB。
    公式对 13 个点全部落在 ±4% 内。

    注意它**与权重体积无关**：小模型照样能耗掉几个 GB。
    `-np`（并行 slot）会把微批再按 slot 切分，实测 np=2/4 时降到约 53% / 30%，
    这里不折算（按最坏情况算，宁可提示偏保守）。
    """
    hkv = int(model.get("head_kv") or 0)
    ub = int(ubatch or 512)
    ctx = int(ctx or 0)
    if not (hkv and ub and ctx):
        return 0.0
    base = _ATTN_BYTES_PER_TOKEN_CTX * hkv * ctx / float(2 ** 20)   # MiB / 微批token
    if fa_on:
        per_token = base * _FA_CTX_RATIO + _FA_PER_TOKEN_MIB
    else:
        per_token = base * _ATTN_OVERHEAD + _ATTN_PER_TOKEN_MIB
    return ub * per_token / 1024.0


def memory_budget(model, ctx, batch=2048, ubatch=512, slots=1, kv_type="f16", fa="auto"):
    """权重 + KV + 批处理激活缓冲 → 一份可核对的显存预算（GiB）。

    不拿「权重 × 12%」顶替激活缓冲：实测同一个 0.6B 模型，-ub 从 128 调到 2048，
    计算缓冲从 73 MiB 涨到 1168 MiB（16 倍），权重一点没变。旧口径对
    「小模型 + 大微批 + 长上下文」必然低估，而这种组合恰恰是最常见的翻车场景。
    """
    size = float(model.get("size_bytes") or 0) / 2 ** 30
    fa_on = str(fa or "auto").strip().lower() != "off"
    ub = int(ubatch or 512)
    b = int(batch or 0)
    if b > 0:
        ub = min(ub, b)                      # 引擎侧硬约束：微批不得大于批大小
    kv = kv_cache_gib(model, ctx, kv_type, slots)
    attn = attn_scratch_gib(model, ctx, ub, fa_on)
    compute = max(attn, size * _COMPUTE_BUFFER_RATIO)
    return {"weights": size, "kv": kv, "attn": attn, "compute": compute,
            "total": size + kv + compute, "ubatch": ub, "fa_on": fa_on}


def assess(machine, model, params, nums, spec_on=False):
    """把「模型要多大 + 本机有多少」摆在一起，给出可执行的调整建议。"""
    items = []
    size_gib = float(model.get("size_bytes") or 0) / 2 ** 30
    ctx = nums.get("ctx") or int(params.get("ctx") or params.get("-c") or 0)
    slots = nums.get("slots") or 1
    kv = kv_cache_gib(model, ctx, params.get("kv_k") or "f16", slots)
    ubatch = int(nums.get("ubatch") or params.get("ubatch") or 512)
    batch = int(nums.get("batch") or params.get("batch") or 2048)
    fa_mode = str(params.get("flash_attn") or params.get("-fa") or "auto")
    budget = memory_budget(model, ctx, batch=batch, ubatch=ubatch, slots=slots,
                           kv_type=params.get("kv_k") or "f16", fa=fa_mode)
    compute = budget["compute"]
    attn = budget["attn"]
    need = budget["total"]

    # 1) 上下文是否超过模型训练上限
    train = int(model.get("ctx_train") or 0)
    if ctx and train and ctx > train:
        items.append((t('上下文长度'), "warn",
                      t('-c {0} 超过模型训练上限 {1}：长度外质量会下降，'
                        '需要外推请配 RoPE 缩放').format(ctx, train)))
    elif ctx and train:
        items.append((t('上下文长度'), "ok",
                      t('-c {0}（模型训练上限 {1}）').format(ctx, train)))
    else:
        items.append((t('上下文长度'), "warn", t('未指定 -c，且模型元数据没有训练上限')))

    # 2) 显存吃不吃得住
    vram = float(machine.get("vram_total_gb") or 0)
    ub = budget["ubatch"]
    if not model.get("exists"):
        items.append((t('显存需求'), "fail", t('模型文件不存在，无法估算')))
    elif vram <= 0:
        items.append((t('显存需求'), "warn",
                      t('未取到显存总量（点基础页的「检测 GPU」或先启动一次服务）；'
                        '估算：权重 {0:.1f} GiB + KV {1:.1f} GiB + 批处理/计算 {2:.1f} GiB '
                        '≈ {3:.1f} GiB').format(size_gib, kv, compute, need)))
    elif need > vram:
        over = need - vram
        # 顺序按「见效快、代价小」排：先动微批/FA，再动上下文，最后才是 ngl/量化
        tips = []
        if attn >= 0.2:
            tips.append(t('把微批 -ub 降到 256~512（现在 {0}，这是批处理峰值的主要来源）').format(ub))
        if not budget["fa_on"]:
            tips.append(t('把闪存注意力 -fa 设为 on（关掉时注意力分数矩阵要整个物化）'))
        tips += [t('减小 -c 或 -np'), t('把 -ngl 调小（部分层放内存）'), t('换更小的量化')]
        if int(model.get("experts") or 0) > 0:
            tips.insert(0, t('MoE 模型：用「高级参数 → MoE 专家」的 --n-cpu-moe N 把部分专家放 CPU'))
        items.append((t('显存需求'), "warn",
                      t('估算需要 {0:.1f} GiB（权重 {1:.1f} + KV {2:.1f} + 批处理/计算 {3:.1f}），'
                        '超过显存 {4:.1f} GiB 约 {5:.1f} GiB。建议：{6}').format(
                          need, size_gib, kv, compute, vram, over, t('、').join(tips))))
    else:
        items.append((t('显存需求'), "ok",
                      t('估算需要 {0:.1f} GiB（权重 {1:.1f} + KV {2:.1f} + 批处理/计算 {3:.1f}），'
                        '显存 {4:.1f} GiB 够用').format(need, size_gib, kv, compute, vram)))

    # 2b) 批处理峰值：与权重无关，只由「微批 × 上下文」决定，单独指出来才看得懂
    if model.get("exists") and ctx and attn >= 0.2:
        head_kv = int(model.get("head_kv") or 0)
        detail = t('批处理激活约 {0:.2f} GiB：微批 -ub {1} × 上下文 {2}（KV 头 {3}，'
                   '闪存注意力 {4}）。').format(
                       attn, ub, ctx, head_kv or t('未知'),
                       t('开') if budget["fa_on"] else t('关'))
        if not budget["fa_on"] and ctx >= 8192:
            detail += t('关掉 -fa 时这份矩阵要整个物化；改 -fa on 通常能把它压到零头，'
                        '否则把 -ub 降到 256~512。')
        elif attn >= 1.0:
            detail += t('若启动时报显存分配失败（CUDA graph / buffer alloc），先降 -ub。')
        items.append((t('批处理峰值'), "warn" if attn >= 1.0 else "ok", detail))

    # 3) 内存：--mlock 会强制把权重钉在物理内存里
    ram = float(machine.get("ram_avail_gb") or 0)
    if "mlock" in params and ram and size_gib + kv > ram:
        items.append((t('内存'), "warn",
                      t('勾了 --mlock 但可用内存只有 {0:.1f} GiB，装不下权重 {1:.1f} GiB + '
                        'KV {2:.1f} GiB；去掉 --mlock 或减小上下文').format(ram, size_gib, kv)))
    elif ram:
        items.append((t('内存'), "ok",
                      t('可用内存 {0:.1f} GiB / 共 {1:.1f} GiB').format(
                          ram, float(machine.get("ram_total_gb") or 0))))

    # 4) MoE 专家：全放显存 vs 部分放 CPU
    experts = int(model.get("experts") or 0)
    if experts:
        used = int(model.get("experts_used") or 0)
        base = t('MoE 模型：{0} 个专家，每 token 激活 {1} 个').format(experts, used or 0)
        if vram and need > vram:
            items.append((t('MoE 专家卸载'), "warn",
                          base + t('；显存紧张，建议 --n-cpu-moe 从 1/4 层起逐步加大')))
        else:
            items.append((t('MoE 专家卸载'), "ok", base + t('；当前估算不需要把专家卸载到 CPU')))

    # 5) 带视觉塔却没写 --mmproj
    if model.get("mmproj") and not params.get("mmproj"):
        items.append((t('视觉投影'), "warn",
                      t('同目录有 {0}，但脚本没有 --mmproj：'
                        '这样只能纯对话，看不到图片').format(
                          os.path.basename(model["mmproj"]))))
    elif params.get("mmproj"):
        items.append((t('视觉投影'), "ok", t('脚本已指定 --mmproj')))

    # 6) 有 MTP/草稿头却没开投机解码
    if model.get("mtp_hint") and not spec_on:
        items.append((t('投机解码'), "warn",
                      t('模型自带 MTP/NextN 预测层（{0} 层），但脚本没有 --spec-type：'
                        '开投机解码可明显提速').format(model.get("nextn"))))
    elif spec_on:
        items.append((t('投机解码'), "ok", t('脚本已指定 --spec-type')))

    # 7) 磁盘余量（更新 / 下载 / mmap 换入换出都要空间）
    free = float(machine.get("disk_free_gb") or 0)
    if free and free < 5:
        items.append((t('磁盘余量'), "warn",
                      t('模型所在盘只剩 {0:.1f} GiB，更新 llama.cpp 或下载新模型可能失败').format(free)))
    elif free:
        items.append((t('磁盘余量'), "ok", t('模型所在盘剩余 {0:.1f} GiB').format(free)))
    return items


def probe_vram_free_mb(timeout=4):
    """当前**可用**显存（MB，多卡求和）。取不到返回 0，调用方如实说明未取到。"""
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return 0.0
    if proc.returncode != 0:
        return 0.0
    free = 0.0
    for line in (proc.stdout or "").strip().splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            free += max(0.0, float(parts[0]) - float(parts[1]))
        except ValueError:
            continue
    return free


def suggest_ubatch(model, ctx, batch=2048, slots=1, kv_type="f16", fa="auto", vram_gib=0.0):
    """在给定显存下能装下的最大微批（从 2048 往下试），返回 (ub, budget)。

    只降到 64 仍装不下就返回 (None, budget)，由界面如实说「光调微批救不回来」。
    """
    for ub in (2048, 1024, 512, 256, 128, 64):
        b = memory_budget(model, ctx, batch=batch, ubatch=ub, slots=slots,
                          kv_type=kv_type, fa=fa)
        if b["total"] <= vram_gib or ub == 64:
            return (ub if b["total"] <= vram_gib else None), b
    return None, memory_budget(model, ctx, batch=batch, ubatch=512, slots=slots,
                               kv_type=kv_type, fa=fa)


def probe_vram_mb(timeout=4):
    """nvidia-smi 求显存总量（MB，多卡求和）；拿不到返回 0（调用方如实说明未取到）。"""
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return 0.0
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return 0.0
    total = 0.0
    for line in proc.stdout.strip().splitlines():
        try:
            total += float(line.strip())
        except ValueError:
            continue
    return total


def local_endpoint(win):
    """主窗口的服务在跑 → (base_url, api_key, model_id)；没跑 → None。

    「让模型分析」只在手动点击时走这里，地址永远是启动器自己拉起的本机服务。
    """
    if win is None:
        return None
    srv = getattr(win, "server", None)
    try:
        if srv is None or not srv.running:
            return None
        url = str(getattr(srv, "url", "") or "")
    except Exception:
        return None
    if not url:
        return None
    api_key, model_id = "", ""
    try:
        cfg = win._gather_server_cfg()
        api_key = str(cfg.get("api_key", "") or "")
        # llama-server 的 /v1/chat/completions 用 --alias 作为模型名
        model_id = str(cfg.get("alias", "") or "")
    except Exception:
        pass
    return url, api_key, model_id


def guess_launcher_exe(script_path="", model_dir=""):
    """找不到 llama-server 时按常见摆放顺序猜：脚本同目录 → 模型目录 → 软件目录。

    用户的 .bat 通常和 llama-server.exe 放在一起，所以脚本目录排在最前。
    实在找不到返回空串：此时跳过「未知参数」判定，绝不拿别的版本的参数表冤枉用户。
    """
    names = ("llama-server.exe", "llama_server.exe")
    dirs = [os.path.dirname(os.path.abspath(script_path)) if script_path else "",
            str(model_dir or "")]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        from .config import Config
        cfg = Config(root)
        cfg_exe = str(cfg.data.get("launcher_exe") or "")
        if cfg_exe and os.path.isfile(cfg_exe):
            return cfg_exe
        dirs.append(str(cfg.data.get("llama_dir") or ""))
    except Exception:
        pass
    dirs += [root, os.path.dirname(root)]
    for d in dirs:
        for name in names:
            cand = os.path.join(d, name) if d else ""
            if cand and os.path.isfile(cand):
                return cand
    return ""


def context_from_window(win):
    """体检需要的环境信息（GPU 名单 / 显存 / 模型目录 / llama-server 路径 / 本机服务）。

    `win` 为 None（独立调用或单测）时给出能给的，缺的留空，评估文案会如实说明。
    """
    ctx = {"exe": "", "gpus": [], "vram_total_mb": 0.0, "model_dir": "", "win": win}
    if win is None:
        return ctx
    try:
        ctx["exe"] = win._launcher_exe()
    except Exception:
        pass
    devs, _err = getattr(win, "_gpu_result", ([], None)) or ([], None)
    ctx["gpus"] = ["%s %s" % (n, (d or "").split(" (")[0]) for n, d in (devs or [])]
    ctx["model_dir"] = str(getattr(win, "edit_dir", None).text().strip()
                           if getattr(win, "edit_dir", None) is not None else "")
    return ctx


def build_report(script_path, text, ctx=None, engine=None):
    """跑完整内置体检：参数有效性 + 取值 + 硬件/模型资源评估。

    返回 (检查项列表, 结构化上下文)；上下文交给 `build_payload` 生成 AI 分析输入。
    """
    ctx = ctx or {}
    items = []
    raw = iter_script_flags(text, script_path)
    params = {}
    for _flag, name, value in parse_script(text, script_path):
        if name:
            params[name] = value
    model_path = _resolve(script_path, params.get("model", "")) if params.get("model") else ""

    machine = ctx.get("machine") or machine_profile(
        gpus=ctx.get("gpus"), vram_total_mb=ctx.get("vram_total_mb") or probe_vram_mb(),
        model_dir=ctx.get("model_dir") or os.path.dirname(script_path or ""))
    model = model_profile(model_path)
    vals, nums = check_param_values(params)
    spec_on = bool(params.get("spec_type"))

    eng = engine if engine is not None else engine_flags(
        ctx.get("exe") or guess_launcher_exe(script_path, ctx.get("model_dir")))
    items.extend(check_param_names(raw, eng))
    items.extend(vals)
    items.extend(assess(machine, model, params, nums, spec_on))
    unknown = sorted({r["flag"] for r in raw if eng is not None and r["flag"] not in eng})
    info = {"machine": machine, "model": model, "params": params, "nums": nums,
            "unknown": unknown}
    return items, info


# ------------------------------------------------------------------ 汇总与 AI 分析
def build_payload(script_path, machine, model, params, checks):
    """送给模型的结构化摘要（**不含 API Key**：解析阶段就已打码）。"""
    return {
        "用途": t('评估这个 llama-server 启动文件是否合理，并给出可执行的调整建议'),
        "启动文件": script_path or "",
        "本机": {
            "CPU": machine.get("cpu") or "",
            "逻辑核心": machine.get("cores_logical"),
            "内存总量_GiB": round(float(machine.get("ram_total_gb") or 0), 1),
            "内存可用_GiB": round(float(machine.get("ram_avail_gb") or 0), 1),
            "显存总量_GiB": round(float(machine.get("vram_total_gb") or 0), 1),
            "GPU": machine.get("gpus") or [],
            "磁盘剩余_GiB": round(float(machine.get("disk_free_gb") or 0), 1),
        },
        "模型": {
            "文件": os.path.basename(str(model.get("path") or "")),
            "体积_GiB": round(float(model.get("size_bytes") or 0) / 2 ** 30, 2),
            "架构": model.get("arch") or "",
            "参数量": human_params(model["params"]) if model.get("params") else "",
            "层数": model.get("layers") or 0,
            "KV头": model.get("head_kv") or 0,
            "头维度": model.get("head_dim") or 0,
            "训练上下文上限": model.get("ctx_train") or 0,
            "专家数": model.get("experts") or 0,
            "每token激活专家": model.get("experts_used") or 0,
            "量化": model.get("quant") or "",
            "自带MTP层": model.get("nextn") or 0,
        },
        "启动参数": {k: v for k, v in (params or {}).items()},
        "启动器已做的静态检查": [
            f"{_ICON.get(st, '?')} {name}：{desc}" for name, st, desc in (checks or [])],
    }


_ICON = {"ok": "✔", "warn": "⚠", "fail": "✘"}

_SYSTEM_PROMPT = (
    "你是 llama.cpp 部署工程师。用户会给你一份本机启动文件的结构化体检数据"
    "（CPU/内存/显存/磁盘 + 模型元数据 + 启动参数 + 已做的静态检查）。"
    "请输出：\n"
    "1) 结论：这份启动文件能不能正常跑，一句话；\n"
    "2) 风险：按严重程度列出最多 4 条，每条说明依据的数字；\n"
    "3) 建议改动：逐条给出「参数：改成什么 → 预期效果」，只提对本机确实有效的改动；\n"
    "4) 如果数据不足以判断，直接说不足，不要编造硬件型号、显存数字或 llama.cpp 参数名。\n"
    "用简体中文，总字数控制在 450 字以内，不要复述用户给的数据。")


def request_ai_report(base_url, payload, api_key="", model_id="", timeout=180,
                      max_tokens=800):
    """把体检数据交给**本机**正在运行的模型分析，返回 (报告文本, 错误)。

    只在用户手动点「让模型分析」时调用；地址永远是本机 127.0.0.1 的
    llama-server（由启动器管理），不外发。
    `max_tokens` 是硬上限：小模型容易一路写到上下文耗尽，卡几分钟。
    """
    # 传进来的可能是 http://127.0.0.1:8080，也可能已经带 /v1：两种都接，避免拼成 /v1/v1
    base = str(base_url or "").rstrip("/")
    url = (base + "/chat/completions") if base.endswith("/v1") else (base + "/v1/chat/completions")
    body = {
        "temperature": 0.2,
        "max_tokens": int(max_tokens),
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)},
        ],
    }
    if model_id:
        body["model"] = model_id
    req = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    if api_key:
        req.add_header("Authorization", "Bearer " + str(api_key))
    # 强制直连：目标是本机服务，走系统代理（例如 127.0.0.1:7897）反而连不上
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        if not text:
            return "", t('模型没有返回内容（可能上下文不够长或已达长度上限）')
        return text, ""
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return "", t('模型返回 HTTP {0}{1}').format(exc.code, ('：' + detail) if detail else "")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return "", t('连不上本机服务（{0}）：请先启动服务再分析').format(exc)
    except Exception as exc:                       # 解析异常也不该让整个对话框挂掉
        return "", t('分析失败：{0}').format(exc)


class AiReportWorker(threading.Thread):
    """后台跑 AI 分析：模型可能要几十秒，不能让对话框假死。"""

    def __init__(self, base_url, payload, api_key="", model_id="", timeout=180):
        super().__init__(daemon=True)
        self.args_ = (base_url, payload, api_key, model_id, timeout)
        self.result = ("", "")
        self.callback = None

    def run(self):
        try:
            self.result = request_ai_report(*self.args_)
        except Exception as exc:                    # 线程内异常必须吃掉
            self.result = ("", t('分析线程出错：{0}').format(exc))
        if self.callback:
            try:
                self.callback(*self.result)
            except Exception:
                pass
