# -*- coding: utf-8 -*-
"""MoE 专家卸载计算：把「本机有多少显存 / 内存 + 这个模型每层专家多大」换算成具体的 N 和缓存。

为什么不做成「显存档位 × 内存档位」的静态预设
----------------------------------------------
决定该卸载多少专家的不是显存的绝对大小，而是
**「这个模型的专家权重总量 − 你能给它的显存」**。同样 24 GiB 显存：

- Inkling-2-Mini（专家 14.7 GiB / 24 层）全放得下 → N 应该是 0；
- Qwen3.8-Flash-Next（专家 46.8 GiB / 48 层）连一半都放不下 → N 至少 20 层。

所以硬件档位是**算法的输入**，不是 42 个等着用户挑的选项。

三条硬事实（都是本机实测，不是估的）
------------------------------------
1. 专家权重能在 GGUF 张量表里逐层精确量出来（``gguf_reader.expert_weight_map``），
   多分片模型必须逐分片读；
2. UD 动态量化**每层专家大小不一样**（Inkling-2-Mini：前 21 层 547 MiB，后 3 层 1033 MiB），
   所以「总量 ÷ 层数」会算错，必须按层累加；
3. ``--n-cpu-moe N`` 卸载的是**前 N 层**，因此能留在显存里的是最靠上的连续若干层——
   而恰恰是靠上的层更大，贪心方向只能从上往下装。
"""
import os

from .gguf_reader import expert_weight_map
from .i18n import t

GIB = 1024 ** 3
MIB = 1024 ** 2

# 与「合理性体检」同一套估算口径，避免两处说法不一
from .launch_advisor import kv_cache_gib, model_profile          # noqa: E402
from .launch_advisor import _COMPUTE_BUFFER_RATIO as COMPUTE_BUFFER_RATIO

# 水位 = 只动用显存总量的这个比例（剩下给桌面、显卡输出、显存碎片与其它程序）；
# kv_x = 除了当前 -c 算出的 KV，再额外按几倍预留（长上下文会边聊边涨）。
PRESETS = (
    {"key": "auto",     "level": 0.95, "kv_x": 1.0, "cache_share": 0.50,
     "label": t('自动（按本机显存推荐）'),
     "note": t('先看全放显存够不够，不够再按余量决定卸载层数')},
    {"key": "gpu",      "level": 0.95, "kv_x": 1.0, "cache_share": 0.00,
     "label": t('全放显存（最快）'),
     "note": t('专家全部进显存，速度最快；放不下会 OOM 或掉速')},
    {"key": "balanced", "level": 0.85, "kv_x": 1.0, "cache_share": 0.50,
     "label": t('平衡（速度优先，留点余量）'),
     "note": t('尽量多留专家在显存，同时给系统留 15% 显存')},
    {"key": "save",     "level": 0.70, "kv_x": 1.0, "cache_share": 0.50,
     "label": t('省显存（边玩游戏边跑）'),
     "note": t('只把约七成的显存给模型，剩下的留给别的程序')},
    {"key": "extreme",  "level": 0.60, "kv_x": 1.0, "cache_share": 0.75,
     "label": t('极限省显存（专家全放 CPU）'),
     "note": t('--cpu-moe：专家全部留在内存，显存只放注意力等权重')},
    {"key": "context",  "level": 0.85, "kv_x": 2.5, "cache_share": 0.50,
     "label": t('长上下文优先（给 KV 留足空间）'),
     "note": t('按 2.5 倍 KV 预留，边聊长文边涨的上下文不会把显存挤爆')},
)

_PRESET_BY_KEY = {p["key"]: p for p in PRESETS}

# 张量扫描有成本（一次 ~70 ms），按 (路径, mtime, 大小) 缓存
_SCAN_CACHE = {}


def scan(model_path, refresh=False):
    """取专家分布（带缓存）。读不出返回 None。"""
    path = str(model_path or "")
    if not path or not os.path.exists(path):
        return None
    try:
        st = os.stat(path)
        key = (path, int(st.st_mtime), st.st_size)
    except OSError:
        key = (path, 0, 0)
    if not refresh and key in _SCAN_CACHE:
        return _SCAN_CACHE[key]
    data = expert_weight_map(path)
    _SCAN_CACHE[key] = data
    return data


def is_moe(model_path):
    """当前模型是不是 MoE。返回 True / False；读不出文件返回 None（=不知道）。

    判据是专家权重**实际字节**（张量表），比只看元数据 expert_count 更硬：
    有的转换件不写 expert_count，但专家张量明明在。
    """
    data = scan(model_path)
    if data is None:
        return None
    return int(data.get("expert") or 0) > 0


def preset_label(key):
    p = _PRESET_BY_KEY.get(str(key or ""))
    return p["label"] if p else ""


def _layer_list(per_layer):
    """{层号: 字节} → [(层号, 字节)] 按层号升序，只保留有专家的层。"""
    return sorted(((int(k), int(v)) for k, v in (per_layer or {}).items()),
                  key=lambda x: x[0])


def _cut(layers, budget_bytes):
    """从最上层往下连续装：返回 (该卸载几层 N, 留在显存的专家字节)。

    ``--n-cpu-moe N`` 把**前 N 层**的专家放 CPU，所以留在显存的必须是层号最大的一段
    连续层；从上往下贪心，装不下就停（再往下的层只会更多，不会更少）。
    一层都装不下时 N = 最大层号 + 1，等价于「专家全部放 CPU」。
    """
    if not layers:
        return 0, 0
    kept = 0
    keep_from = None
    for idx, size in reversed(layers):
        if kept + size > budget_bytes:
            break
        kept += size
        keep_from = idx
    if keep_from is None:
        return layers[-1][0] + 1, 0
    return keep_from, kept


def _fit(layers, level, vram, other_gib, kv_gib):
    """在给定水位下，专家能留多少、要卸载几层。返回 (预算 GiB, N, 保留 GiB)。"""
    # 计算缓存随 GPU 上的权重大小线性增长，所以预算要把这个系数一起解掉：
    #   other + keep + compute*(other+keep) + kv ≤ level*vram
    denom = 1.0 + COMPUTE_BUFFER_RATIO
    room = level * vram - other_gib - kv_gib
    budget_gib = room / denom if room > 0 else 0.0
    n, keep = _cut(layers, budget_gib * GIB)
    return budget_gib, n, keep / GIB


def plan(preset_key, model_path, machine=None, ctx=0, kv_type="f16", slots=1):
    """算出一份可直接套用的 MoE 卸载方案。

    参数
      preset_key  PRESETS 里的 key；"auto" 会自己选档
      model_path  主模型（分片模型给第 1 片即可，内部会自动读全组）
      machine     launch_advisor.machine_profile() 的结果（要 vram_total_gb / ram_avail_gb）
      ctx, kv_type, slots  当前 -c / KV 缓存类型 / 并行 slots，用来估 KV
    返回 dict：
      ok        False = 套不上（稠密模型 / 读不出文件 / 没有显存信息）
      reason    一段中文说明，把关键数字摆出来（界面上直接显示给用户看）
      mode      "off" / "cpu" / "n"（对应界面「MoE 专家」下拉）
      layers    mode=="n" 时要填的 N
      cache     --moe-cache-mib 的值（0 = 不传）
      preset    实际采用的预设 key（auto 会给出它选中的那一档）
      facts     计算过程用到的数字，便于界面/日志复核
    """
    machine = machine or {}
    out = {"ok": False, "reason": "", "mode": "off", "layers": 0, "cache": 0,
           "preset": str(preset_key or "auto"), "facts": {}, "warn": ""}
    path = str(model_path or "")
    data = scan(path)
    if data is None:
        out["reason"] = t('读不出模型文件里的专家权重分布，无法计算（请先在界面上选好主模型）')
        return out
    expert_bytes = int(data.get("expert") or 0)
    if expert_bytes <= 0:
        out["reason"] = t('当前模型没有专家权重（稠密模型），MoE 专家卸载不适用')
        out["dense"] = True
        return out
    vram = float(machine.get("vram_total_gb") or 0)
    if vram <= 0:
        out["reason"] = t('未取到显存总量（点「检测 GPU」或先启动一次服务），'
                          '不能凭空给卸载层数')
        return out

    layers = _layer_list(data.get("per_layer"))
    weights_gib = float(data.get("weights") or 0) / GIB
    expert_gib = expert_bytes / GIB
    other_gib = max(0.0, weights_gib - expert_gib)
    prof = model_profile(path)
    ctx = int(ctx or 0)
    kv1 = kv_cache_gib(prof, ctx, kv_type, slots)

    key = str(preset_key or "auto")
    top = layers[-1][0] + 1 if layers else 0        # 层号空间里的总层数（混合 MoE 会稀疏）

    # 「一层里真正被激活的那些专家」有多大：CPU 专家缓存至少要装得下它才有意义
    sizes = [v for _k, v in layers] or [0]
    avg_layer = (sum(sizes) / len(sizes)) if sizes else 0
    n_exp = int(prof.get("experts") or 0)
    n_used = int(prof.get("experts_used") or 0)
    active_gib = ((avg_layer * (float(n_used) / n_exp)) if (n_exp and n_used)
                  else avg_layer * 0.10) / GIB

    chosen = key
    if key == "auto":
        # 逐级试探，**只用来选档**：全放得下 → 85% 水位能留一半以上专家 →
        # 只能留一小半 → 一个都进不去
        _b, n_all, keep_all = _fit(layers, 0.95, vram, other_gib, kv1)
        if n_all <= 0 and keep_all >= expert_gib - 1e-9:
            chosen = "gpu"
        else:
            _b, _n, keep_bal = _fit(layers, 0.85, vram, other_gib, kv1)
            chosen = ("balanced" if keep_bal >= 0.5 * expert_gib
                      else "save" if keep_bal > 0 else "extreme")
    p = _PRESET_BY_KEY.get(chosen) or _PRESET_BY_KEY["balanced"]
    kv_gib = kv1 * p["kv_x"]
    # 数字一律按**最终选中的那一档**重算。以前 auto 选到「省显存」却沿用试探时的
    # 85% 水位数字，说明写 70%、算的是 85%，自相矛盾。
    budget_gib, n, keep_gib = _fit(layers, p["level"], vram, other_gib, kv_gib)

    # 要把专家放 CPU 时，先从显存预算里匀出一块给「专家缓存」再重算：
    # 少装一层专家，换 CPU 专家的热数据常驻显存，通常比全裸着更划算。
    reserve = 0.0
    if chosen != "gpu" and active_gib > 0:
        reserve = min(max(8.0 * active_gib, 64.0 / 1024.0), 1.0)
        b2, n2, keep2 = _fit(layers, p["level"], vram, other_gib, kv_gib + reserve)
        if n2 > 0:
            budget_gib, n, keep_gib = b2, n2, keep2

    if chosen == "extreme":
        mode, n, keep_gib = "cpu", top, 0.0
    elif n >= top:
        mode, keep_gib = "cpu", 0.0
    elif n <= 0:
        mode, n, keep_gib = "off", 0, expert_gib
    else:
        mode = "n"

    off_gib = max(0.0, expert_gib - keep_gib)
    compute_gib = (other_gib + keep_gib) * COMPUTE_BUFFER_RATIO
    used_gib = other_gib + keep_gib + kv_gib + compute_gib
    headroom = max(0.0, p["level"] * vram - used_gib)
    cache = 0
    if mode != "off" and reserve > 0:
        cache_gib = min(reserve, headroom)
        if cache_gib * GIB >= active_gib * GIB:      # 至少装得下一层激活的专家
            cache = int(cache_gib * 1024 // 64 * 64)
            cache = max(64, min(cache, 4096))
    ram_avail = float(machine.get("ram_avail_gb") or 0)
    warn = ""
    if mode != "off" and ram_avail and off_gib + kv_gib > ram_avail:
        warn = t('可用内存只有 {0:.1f} GiB，卸载到 CPU 的专家要 {1:.1f} GiB：'
                 '可能不够（会换页变慢，勾 mlock 更吃紧）').format(ram_avail, off_gib)
    if other_gib + kv_gib > p["level"] * vram:
        warn = (warn + "\n" if warn else "") + t(
            '注意：不含专家的权重（注意力 / 词表等）就有 {0:.1f} GiB，加上 KV {1:.1f} GiB '
            '已超过 {2:.1f} GiB 的水位线：光调 MoE 卸载救不回来，'
            '需要把 -ngl 调小（部分层放内存）或换更小量化或减小 -c').format(
                other_gib, kv_gib, p["level"] * vram)

    out.update({
        "ok": True,
        "mode": mode,
        "layers": n if mode == "n" else 0,
        "cache": cache,
        "preset": chosen,
        "warn": warn,
        "facts": {
            "vram_gb": vram, "level": p["level"], "model": os.path.basename(path),
            "expert_gib": expert_gib, "other_gib": other_gib, "kv_gib": kv_gib,
            "budget_gib": budget_gib, "keep_gib": keep_gib, "off_gib": off_gib,
            "compute_gib": compute_gib, "used_gib": used_gib, "cache_mib": cache,
            "layers_total": top, "layers_with_experts": len(layers), "layers_off": n,
            "shards": int(data.get("shards") or 1),
            "experts": int(prof.get("experts") or 0),
            "experts_used": int(prof.get("experts_used") or 0),
        },
    })
    out["reason"] = _reason(out, p, key == "auto")
    return out


def _reason(res, preset, auto_note):
    """把 facts 拼成人话：数字都要摆出来，用户能自己复核。"""
    f = res["facts"]
    head = t('显存 {0:.1f} GiB × 水位 {1:.0f}% = {2:.1f} GiB').format(
        f["vram_gb"], f["level"] * 100, f["vram_gb"] * f["level"])
    line = t('{0}；非专家权重 {1:.2f} + KV {2:.2f} + 计算缓存约 {3:.2f} '
             '→ 专家可用约 {4:.2f} GiB').format(
                 head, f["other_gib"], f["kv_gib"], f["compute_gib"], f["budget_gib"])
    body = t('模型专家共 {0:.2f} GiB（{1} / {2} 层有专家，专家 {3} 个 / 每 token 激活 {4} 个）').format(
        f["expert_gib"], f["layers_with_experts"], f["layers_total"],
        f["experts"] or t('未知'), f["experts_used"] or t('未知'))
    mode = res["mode"]
    if mode == "off":
        tail = t('→ 全放得下：不卸载（N=0），速度最快')
    elif mode == "cpu":
        tail = t('→ 全部放 CPU（--cpu-moe）：显存里不放专家，卸载 {0:.2f} GiB').format(f["off_gib"])
    else:
        tail = t('→ 前 {0} 层放 CPU（--n-cpu-moe {0}），后 {1} 层留在显存'
                 '（约 {2:.2f} GiB）').format(res["layers"], f["layers_total"] - res["layers"],
                                             f["keep_gib"])
    if res["cache"]:
        tail += t('；专家缓存 --moe-cache-mib {0}（用掉剩余显存约 {1:.2f} GiB）').format(
            res["cache"], res["cache"] / 1024.0)
    elif mode == "off":
        # 别写成「剩余显存不够装一层激活的专家」：专家一个都没卸，本来就不需要缓存
        tail += t('；专家全在显存里，不需要 --moe-cache-mib')
    else:
        tail += t('；不设专家缓存（剩余显存装不下一层激活的专家，设了也白设）')
    if res["warn"]:
        tail += "\n" + res["warn"]
    if auto_note and preset["key"] != "auto":
        tail += "\n" + t('自动选档：{0} —— {1}').format(preset["label"], preset["note"])
    return line + "\n" + body + "\n" + tail
