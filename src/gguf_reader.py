import os
import re
import struct
from .i18n import t

GGUF_MAGIC = b"GGUF"

UINT8, INT8, UINT16, INT16, UINT32, INT32, FLOAT32, BOOL = 0, 1, 2, 3, 4, 5, 6, 7
STRING, ARRAY, UINT64, INT64, FLOAT64 = 8, 9, 10, 11, 12

FILE_TYPE_NAMES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 4: "Q4_1_SOME_F16", 5: "Q8_0",
    6: "Q5_0", 7: "Q5_1", 8: "Q2_K", 9: "Q3_K_S", 10: "Q3_K_M", 11: "Q3_K_L",
    12: "Q4_K_S", 13: "Q4_K_M", 14: "Q5_K_S", 15: "Q5_K_M", 16: "Q6_K",
    17: "Q8_K", 18: "IQ2_XXS", 19: "IQ2_XS", 20: "IQ3_XXS", 21: "IQ1_S",
    22: "IQ4_NL", 23: "IQ3_S", 24: "IQ3_M", 25: "IQ2_S", 26: "IQ2_M",
    27: "IQ4_XS", 28: "IQ1_M", 29: "BF16", 30: "Q4_0_4_4", 31: "Q4_0_4_8",
    32: "Q4_0_8_8", 33: "TQ1_0", 34: "TQ2_0",
}

# 量化标识：覆盖 llama.cpp 标准名、Unsloth 动态量化（UD-*，常带 _XL/_XXL）等。
# 注意：通用 K 量化用 `Q\d+_K(?:_[A-Z0-9]+)*` 以便匹配 Q4_K_XL/Q5_K_XXL 这类后缀。
QUANT_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])"
    r"(MXFP4"
    r"|IQ\d+(?:_[A-Z0-9]+)+"
    r"|Q\d+_K(?:_[A-Z0-9]+)*"
    r"|Q\d+_\d+(?:_\d+)*"
    r"|TQ\d+_\d+"
    r"|BF16|F16|F32)"
)

# 超大数组键：解析信息时直接跳过（不读入几十万条词表/合并表，明显加快速度）
_SKIP_ARRAY_KEYS = {
    "tokenizer.ggml.tokens",
    "tokenizer.ggml.token_type",
    "tokenizer.ggml.merges",
    "tokenizer.ggml.scores",
}

_ARRAY_ELEM_SIZE = {
    UINT8: 1, INT8: 1, UINT16: 2, INT16: 2, UINT32: 4, INT32: 4,
    FLOAT32: 4, BOOL: 1, UINT64: 8, INT64: 8, FLOAT64: 8,
}

# 固定键 → info 短名
_SIMPLE_KEYS = {
    "general.architecture": "general.architecture",
    "general.name": "general.name",
    "general.file_type": "general.file_type",
    "general.description": "general.description",
    "general.license": "general.license",
    "general.quantized_by": "general.quantized_by",
    "general.size_label": "general.size_label",
    "general.repo_url": "general.repo_url",
    "general.base_model.0.name": "base_model_name",
    "general.base_model.0.organization": "base_model_org",
    "general.base_model.0.repo_url": "base_model_url",
    "tokenizer.ggml.model": "tokenizer.ggml.model",
}

# 架构前缀键（如 qwen35.xxx / llama.xxx）按后缀匹配 → info 短名
_SUFFIX_MAP = (
    ("attention.head_count_kv", "head_count_kv"),
    ("attention.head_count", "head_count"),
    ("attention.key_length", "key_length"),
    ("attention.value_length", "value_length"),
    ("context_length", "context_length"),
    ("embedding_length", "embedding_length"),
    ("feed_forward_length", "feed_forward_length"),
    ("block_count", "block_count"),
    ("rope.freq_base", "rope_freq_base"),
    ("rope.dimension_count", "rope_dim"),
    ("nextn_predict_layers", "nextn_layers"),
    ("ssm.state_size", "ssm_state"),
    ("parameter_count", "parameter_count"),
    ("expert_count", "expert_count"),
    ("expert_used_count", "expert_used_count"),
    ("expert_feed_forward_length", "expert_feed_forward_length"),
    ("expert_shared_count", "expert_shared_count"),
    ("projection_dim", "projection_dim"),
)


def _scalarize(value):
    """把 KV 值收成标量；收不出来返回 None。

    有的架构把**逐层参数**写成数组（实测 Inkling-2：
    `inkling2_loop.attention.head_count = [24]×24`、`head_count_kv = [8]×24`），
    原样塞进 info 会让每个 `int(info[...])` 的调用方当场 `TypeError`
    ——「合理性体检」在 Inkling-2 上就是这么崩的。归约规则：
      - 元素全相同 → 就是那个值；
      - 不全相同 → 取最大值（KV / 显存估算宁可高估，不要装作不需要）。
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        nums = [v for v in value
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return max(nums) if nums else None
    return None


def _capture(info, key, value):
    """把解析到的 KV 归入 info 的短名键（只取首个匹配，架构前缀不敏感）。"""
    if key in _SIMPLE_KEYS:
        info[_SIMPLE_KEYS[key]] = value
        return
    lk = key.lower()
    for suffix, name in _SUFFIX_MAP:
        if lk.endswith(suffix) and name not in info:
            val = _scalarize(value)
            if val is not None:
                info[name] = val
            return



def _u32(f):
    return struct.unpack("<I", f.read(4))[0]


def _u64(f):
    return struct.unpack("<Q", f.read(8))[0]


def _read_string(f):
    (length,) = struct.unpack("<Q", f.read(8))
    raw = f.read(length)
    return raw.decode("utf-8", errors="replace")


def _read_scalar(f, vtype):
    if vtype == UINT8:
        return struct.unpack("<B", f.read(1))[0]
    if vtype == INT8:
        return struct.unpack("<b", f.read(1))[0]
    if vtype == UINT16:
        return struct.unpack("<H", f.read(2))[0]
    if vtype == INT16:
        return struct.unpack("<h", f.read(2))[0]
    if vtype == UINT32:
        return struct.unpack("<I", f.read(4))[0]
    if vtype == INT32:
        return struct.unpack("<i", f.read(4))[0]
    if vtype == FLOAT32:
        return struct.unpack("<f", f.read(4))[0]
    if vtype == BOOL:
        return bool(struct.unpack("<B", f.read(1))[0])
    if vtype == UINT64:
        return struct.unpack("<Q", f.read(8))[0]
    if vtype == INT64:
        return struct.unpack("<q", f.read(8))[0]
    if vtype == FLOAT64:
        return struct.unpack("<d", f.read(8))[0]
    return None


def _read_value(f, vtype):
    if vtype == STRING:
        return _read_string(f)
    if vtype == ARRAY:
        elem_type = _u32(f)
        count = _u64(f)
        if elem_type == STRING:
            return [_read_string(f) for _ in range(count)]
        data = [_read_scalar(f, elem_type) for _ in range(count)]
        return data
    return _read_scalar(f, vtype)


def _skip_array(f):
    """跳过数组值并返回元素个数（字符串数组逐条跳过长度，不读入内容）。"""
    elem_type = _u32(f)
    count = _u64(f)
    if elem_type == STRING:
        for _ in range(count):
            (length,) = struct.unpack("<Q", f.read(8))
            f.seek(length, os.SEEK_CUR)
    else:
        size = _ARRAY_ELEM_SIZE.get(elem_type)
        if size is None:
            raise ValueError("unknown array element type")
        f.seek(size * count, os.SEEK_CUR)
    return count


def read_gguf_info(path):
    info = None
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != GGUF_MAGIC:
                return None
            version = _u32(f)
            tensor_count = _u64(f)
            kv_count = _u64(f)
            info = {"version": version, "tensor_count": tensor_count}
            for _ in range(kv_count):
                key = _read_string(f)
                vtype = _u32(f)
                if vtype == ARRAY and key in _SKIP_ARRAY_KEYS:
                    count = _skip_array(f)
                    if key == "tokenizer.ggml.tokens":
                        info["vocab_size"] = count
                    continue
                value = _read_value(f, vtype)
                _capture(info, key, value)
    except Exception:
        return None
    return info


def scan_tensor_names(path):
    """读取 GGUF 头部的全部张量名（不读权重数据，速度快）。

    返回 list[str]；文件无效/解析失败返回 None。
    多文件分片模型只需扫描第一个分片（其头部含完整张量表）。
    """
    try:
        with open(path, "rb") as f:
            if f.read(4) != GGUF_MAGIC:
                return None
            _u32(f)                      # version
            tensor_count = _u64(f)
            kv_count = _u64(f)
            for _ in range(kv_count):    # 跳过 KV 元数据
                _read_string(f)
                vtype = _u32(f)
                _read_value(f, vtype)
            names = []
            for _ in range(tensor_count):
                name = _read_string(f)
                n_dims = _u32(f)
                f.seek(n_dims * 8, os.SEEK_CUR)   # dims
                f.read(4)                          # ggml type
                f.read(8)                          # offset
                names.append(name)
            return names
    except Exception:
        return None


def _shard_group_files(path):
    """返回 path 所在分片组的全部文件（含自身）。

    新版 llama.cpp 分片中，第 1 个文件可能只含元数据（tensor_count=0），
    张量表分布在各分片中，因此必须扫描整组才能判断 MTP。
    """
    import glob as _glob
    base = os.path.basename(path)
    m = re.match(r'^(.+)-\d{5}-of-\d{5}\.gguf$', base, re.IGNORECASE)
    if not m:
        return [path]
    pattern = os.path.join(os.path.dirname(path), f"{m.group(1)}-*-*.gguf")
    files = sorted(_glob.glob(pattern))
    return files or [path]


# ------------------------------------------------------------ 专家权重按层统计
def _read_tensor_table(path):
    """读单个 GGUF 文件的张量表，返回 (对齐值, [(名字, 维度, 类型, 偏移)], 数据区起点)。

    偏移是**相对本文件数据区起点**的。多分片模型每个分片各有一份表，且每份表只列
    自己实际装的那些张量（实测 Qwen3.8-Flash-Next 四分片：第 1 片 72 条、第 2 片 768 条，
    互不重名），所以统计权重规模必须逐分片读——只看第 1 片会得出完全错误的结论。

    文件无效返回 (0, None, 0)。
    """
    try:
        with open(path, "rb") as f:
            if f.read(4) != GGUF_MAGIC:
                return 0, None, 0
            _u32(f)                      # version
            tensor_count = _u64(f)
            kv_count = _u64(f)
            alignment = 32               # GGUF 规范默认值
            for _ in range(kv_count):
                key = _read_string(f)
                vtype = _u32(f)
                if vtype == ARRAY:
                    _skip_array(f)       # 词表这类大数组直接跳过，不读进内存
                    continue
                value = _read_value(f, vtype)
                if key == "general.alignment" and isinstance(value, int) and value > 0:
                    alignment = value
            infos = []
            for _ in range(tensor_count):
                name = _read_string(f)
                n_dims = _u32(f)
                dims = [_u64(f) for _ in range(n_dims)]
                dtype = _u32(f)
                offset = _u64(f)
                infos.append((name, dims, dtype, offset))
            # 张量表之后先按 alignment 补齐，才是数据区起点
            align = max(1, alignment)
            data_start = -(-f.tell() // align) * align
            return alignment, infos, data_start
    except Exception:
        return 0, None, 0


# llama.cpp 的 MoE 专家权重张名都带 exps / experts（实测 Inkling-2 是
# ffn_gate_up_exps / ffn_down_exps，gpt-oss、qwen3moe 一族是 ffn_gate_exps /
# ffn_up_exps / ffn_down_exps，各自再带 .weight 与 .scale）。
_EXPERT_TENSOR_RX = re.compile(r"(?i)(?:ffn_[a-z0-9_]*exps\b|\.experts?\b|_experts?\b)")
# 名字里带 exp 但**不参与** --n-cpu-moe 卸载的东西：路由器与偏置，都很小
_NON_EXPERT_RX = re.compile(r"(?i)(gate_inp|exp_probs|router)")


def expert_weight_map(path):
    """按层统计「专家权重」字节数：MoE 该卸载几层、缓存给多大，全靠这个算。

    返回 dict：
      per_layer  {层号: 该层专家权重字节}，**只包含真的有专家张量的层**——混合 MoE
                 是稀疏的（实测 Inkling-2-Mini 24 层里只有 22 层带专家）；
      expert     专家权重合计字节；
      weights    全部权重合计字节（专家 + 注意力 / norm / 词表等非专家）；
      layers     张量表里出现过的最大层号 + 1；
      shards     实际读到的分片文件数。
    读不出返回 None。

    大小算法：同文件内按偏移排序，张量大小 = 后一个的偏移 − 自己的偏移；最后一个用
    「文件大小 − 数据区起点 − 偏移」收尾。偏移差含对齐填充，每个张量最多算多
    alignment−1 字节（默认 32 B），对 GB 级统计可忽略。
    **不能**用「文件总大小 ÷ 层数」代替：UD 动态量化每层专家大小差一倍以上
    （实测 Inkling-2-Mini：中位 547 MiB、最大 1033 MiB），那样算出来的 N 是错的。
    """
    files = _shard_group_files(str(path))
    per_layer, expert, weights, max_layer, shards = {}, 0, 0, 0, 0
    for fp in files:
        _align, infos, data_start = _read_tensor_table(fp)
        if not infos:
            continue
        shards += 1
        try:
            file_size = os.path.getsize(fp)
        except OSError:
            continue
        ordered = sorted(infos, key=lambda x: x[3])
        for i, item in enumerate(ordered):
            name, off = item[0], item[3]
            nxt = ordered[i + 1][3] if i + 1 < len(ordered) else max(0, file_size - data_start)
            size = max(0, nxt - off)
            weights += size
            if _EXPERT_TENSOR_RX.search(name) and not _NON_EXPERT_RX.search(name):
                m = re.match(r"blk\.(\d+)\.", name)
                if m:
                    li = int(m.group(1))
                    per_layer[li] = per_layer.get(li, 0) + size
                    if li + 1 > max_layer:
                        max_layer = li + 1
                expert += size
    if not weights:
        return None
    return {"per_layer": per_layer, "expert": expert, "weights": weights,
            "layers": max_layer, "shards": shards}


# MTP 张量名常见模式：不同模型架构命名不同
#   - mtp.*                      （部分 Qwen / 通用实现）
#   - nextn / next_n.*           （DeepSeek / GLM 等 NextN 预测层）
#   - eh_proj / shared_head      （DeepSeek MTP 层特有张量）
MTP_TENSOR_PATTERNS = ("mtp", "nextn", "next_n", "eh_proj", "shared_head")


def _scan_mtp_meta(path):
    """扫描 GGUF 元数据，判断是否声明了 MTP / NextN 预测层。

    兼容 `*.nextn_predict_layers > 0` 以及键名含 mtp 且取值为真 的情况。
    """
    try:
        with open(path, "rb") as f:
            if f.read(4) != GGUF_MAGIC:
                return False
            _u32(f)          # version
            _u64(f)          # tensor_count
            kv_count = _u64(f)
            for _ in range(kv_count):
                key = _read_string(f)
                vtype = _u32(f)
                value = _read_value(f, vtype)
                lk = key.lower()
                if "nextn_predict_layers" in lk or "mtp" in lk:
                    try:
                        if int(value) > 0:
                            return True
                    except (TypeError, ValueError):
                        if value:
                            return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------- 文件角色判定
# 模型目录里除了「真模型」还常混着三类 GGUF：视觉投影（mmproj）、投机解码的草稿头
# （MTP / DFlash / DSpark / EAGLE 等）、量化标定文件（imatrix）。它们都不能当 -m 用，
# 混进主模型列表只会让人点错，所以扫描时要按内容分流。
#
# 判定优先级：**文件内容 > 文件名**；两者都判不出时按「主模型」处理（宁可多显示，不误杀）。
# 实测依据（unsloth / ggml-org 的 Qwen3.8-27B 一包四件）：
#   真模型        general.type=model，blk.0..63 齐全 + 词表；内嵌 MTP 时再多一个 blk.64.nextn.*
#   视觉投影      general.type=mmproj，general.architecture=clip，张量前缀全是 v./mm.
#   MTP 外挂头    general.type 也是 model（不可信），但**没有 blk.0**，只有 blk.64.* 十几条
#   imatrix       general.type=imatrix，只有 4 条 KV、没有任何 blk.0 之外的模型结构
ROLE_MODEL, ROLE_MMPROJ, ROLE_DRAFT, ROLE_IMATRIX = "model", "mmproj", "draft", "imatrix"

# 视觉投影的张量名前缀（clip/mmproj 转换产物固定这几种）
_VISION_TENSOR_PREFIXES = ("v.", "mm.", "mmpc.", "vpm.")

# 只可能是「投机草稿头」的架构名：llama.cpp 的 convert_hf_to_gguf 给 DFlash/DSpark/EAGLE
# 草稿打的 general.architecture 就是这些。实测 DSpark 草稿同时带完整词表、blk.0..2 齐全，
# 所以「没有 blk.0」只能识破 MTP 外挂头，识破这类草稿必须靠架构名。
_DRAFT_ARCHES = ("dflash", "dflash2", "dspark", "lilicorr", "eagle", "eagle3")

# 草稿头专属张量（架构名缺失时的兜底特征）。注意**不能**放 nextn./eh_proj/shared_head：
# 这些张量在「内嵌 MTP 的真模型」里也有，误用会把 16GB 的主模型判成草稿。
_DRAFT_TENSOR_MARKS = ("joint_proj", "markov_", "dspark_", "eagle_", "lilicorr")

# 文件名兜底判据：读不到 GGUF 头时用（顺序敏感，draft 放最后避免吃掉 mtp- 之外的名字）
_NAME_ROLES = (
    (re.compile(r"(?i)imatrix"), ROLE_IMATRIX, ""),
    (re.compile(r"(?i)(^|[-_.])(mmproj|mmpc)([-_.]|$)"), ROLE_MMPROJ, ""),
    (re.compile(r"(?i)(?:^|[-_.])(?P<kind>mtp|dflash2|dflash|dspark|lilicorr|eagle3|eagle|draft)"
                r"(?:[-_.]|$)"), ROLE_DRAFT, "kind"),
)


def _name_role(path):
    """仅凭文件名猜角色，返回 (role, kind)；猜不出返回 (ROLE_MODEL, "")。"""
    base = os.path.basename(str(path))
    for rx, role, mode in _NAME_ROLES:
        m = rx.search(base)
        if m:
            kind = (m.group("kind") or "").lower() if mode == "kind" else ""
            return role, kind
    return ROLE_MODEL, ""


def probe_gguf(path):
    """一次读完整 GGUF 头部（KV + 张量名表），返回角色判定所需事实；文件无效返回 None。

    只读头部、不碰权重数据，几十毫秒内返回；词表等超大数组直接跳过。
    """
    facts = {"version": 0, "tensor_count": 0, "type": "", "arch": "", "block_count": 0,
             "nextn_layers": 0, "has_tokenizer": False, "has_clip": False,
             "base": "", "base_model": "", "names": [],
             "vocab_size": 0, "embedding_length": 0, "expert_count": 0,
             "expert_used_count": 0}
    try:
        with open(path, "rb") as f:
            if f.read(4) != GGUF_MAGIC:
                return None
            facts["version"] = _u32(f)
            facts["tensor_count"] = _u64(f)
            kv_count = _u64(f)
            for _ in range(kv_count):
                key = _read_string(f)
                vtype = _u32(f)
                if vtype == ARRAY and key in _SKIP_ARRAY_KEYS:
                    count = _skip_array(f)
                    facts["has_tokenizer"] = True     # 有词表 => 一定是能对话的模型本体
                    if key == "tokenizer.ggml.tokens":
                        facts["vocab_size"] = count
                    continue
                value = _read_value(f, vtype)
                lk = key.lower()
                if lk.startswith("tokenizer."):
                    facts["has_tokenizer"] = True
                elif lk == "general.type":
                    facts["type"] = str(value).strip().lower()
                elif lk == "general.architecture":
                    facts["arch"] = str(value).strip().lower()
                elif lk == "general.basename":
                    facts["base"] = str(value)
                elif lk == "general.base_model.0.name":
                    facts["base_model"] = str(value)
                elif lk.endswith(".block_count"):
                    try:
                        facts["block_count"] = int(value)
                    except (TypeError, ValueError):
                        pass
                elif lk.endswith(".embedding_length"):
                    try:
                        facts["embedding_length"] = int(value)
                    except (TypeError, ValueError):
                        pass
                elif lk.endswith(".expert_count"):
                    try:
                        facts["expert_count"] = int(value)
                    except (TypeError, ValueError):
                        pass
                elif lk.endswith(".expert_used_count"):
                    try:
                        facts["expert_used_count"] = int(value)
                    except (TypeError, ValueError):
                        pass
                elif "nextn" in lk or "mtp" in lk:
                    try:
                        facts["nextn_layers"] = max(facts["nextn_layers"], int(value or 0))
                    except (TypeError, ValueError):
                        pass
                elif lk.startswith("clip."):
                    facts["has_clip"] = True
            names = []
            for _ in range(facts["tensor_count"]):
                name = _read_string(f)
                n_dims = _u32(f)
                f.seek(n_dims * 8, os.SEEK_CUR)      # dims
                f.read(4)                            # ggml type
                f.read(8)                            # offset
                names.append(name)
            facts["names"] = names
    except Exception:
        return None
    return facts


def probe_model_gguf(path):
    """合并多文件分片模型的事实（架构/MTP/词表/专家数）。

    新版 llama.cpp 的分片模型第 1 个文件可能只有元数据、张量表分散在各分片，
    只看第一个文件会漏掉内嵌 MTP / 张量名。这里把同组所有分片合并：
    标量取第一个非空值，张量名与 nextn 计数取并集/最大值。
    """
    files = _shard_group_files(path)
    merged = None
    names = []
    for fp in files:
        facts = probe_gguf(fp)
        if facts is None:
            continue
        if merged is None:
            merged = dict(facts)
            merged["names"] = []
        for key in ("version", "tensor_count", "type", "arch", "block_count",
                    "has_tokenizer", "has_clip", "base", "base_model",
                    "vocab_size", "embedding_length", "expert_count", "expert_used_count"):
            if not merged.get(key) and facts.get(key):
                merged[key] = facts[key]
        merged["nextn_layers"] = max(int(merged.get("nextn_layers") or 0),
                                     int(facts.get("nextn_layers") or 0))
        for n in facts.get("names") or ():
            if n not in names:
                names.append(n)
    if merged is None:
        return None
    merged["names"] = names
    merged["tensor_count"] = max(int(merged.get("tensor_count") or 0), len(names))
    return merged


def _blk_indexes(names):
    """张量名里的 blk 层号集合（判定「是不是从第 0 层开始」用）。"""
    out = set()
    for n in names:
        if not n.startswith("blk."):
            continue
        tail = n[4:].split(".", 1)
        if tail and tail[0].isdigit():
            out.add(int(tail[0]))
    return out


def _draft_kind(names, name_kind, nextn_layers, arch=""):
    """草稿头是哪种：架构名 > 专属张量 > 文件名 > nextn 特征。"""
    al = (arch or "").lower()
    if any(n.startswith("markov_") or n.startswith("dspark_") for n in names):
        return "dspark"          # dflash 架构 + Markov 头 = DSpark（实测 ggml-org 草稿就这样）
    for a in ("dflash2", "dflash", "dspark", "lilicorr"):
        if al.startswith(a):
            return a
    if al.startswith("eagle"):
        return "eagle3"
    kind = (name_kind or "").lower()
    if kind == "eagle":
        kind = "eagle3"
    if kind:
        return kind
    low = [n.lower() for n in names]
    if any("nextn" in n or "eh_proj" in n or "shared_head" in n for n in low):
        return "mtp"
    if nextn_layers:
        return "mtp"
    return "simple"


def classify_gguf(path, use_cache=True):
    """判定一个 .gguf 的角色，返回 (role, kind, reason)。

    role: model / mmproj / draft / imatrix；kind 仅对 draft 有意义
    （mtp / dflash / dflash2 / dspark / lilicorr / eagle3 / simple）。
    """
    key = os.path.abspath(str(path))
    cache = globals().setdefault("_CLASSIFY_CACHE", {})
    try:
        st = os.stat(key)
        stamp = (int(st.st_mtime), st.st_size)
    except OSError:
        return _name_role(key) + ("文件不存在",)
    hit = cache.get(key)
    if use_cache and hit and hit[0] == stamp:
        return hit[1]

    nrole, nkind = _name_role(key)
    facts = probe_gguf(key)
    if facts is None:
        result = (nrole, nkind, "无法读取头部，按文件名判定")
    else:
        names = facts["names"]
        blocks = _blk_indexes(names)
        if facts["type"] == "imatrix":
            res = (ROLE_IMATRIX, "", "general.type=imatrix（量化标定文件）")
        elif facts["type"] == "mmproj" or facts["has_clip"]:
            res = (ROLE_MMPROJ, "", "视觉投影（general.type=mmproj / clip）")
        elif names and not blocks and all(
                n.startswith(_VISION_TENSOR_PREFIXES) for n in names):
            res = (ROLE_MMPROJ, "", "视觉投影（张量全为 v./mm. 编码器）")
        elif (facts["arch"] in _DRAFT_ARCHES
              or any(any(m in n.lower() for m in _DRAFT_TENSOR_MARKS) for n in names)):
            # DFlash/DSpark/EAGLE 草稿：层号从 0 开始、词表也齐全，只有架构名/专属张量能识破
            res = (ROLE_DRAFT, _draft_kind(names, nkind, facts["nextn_layers"], facts["arch"]),
                   "架构 %s 为投机草稿头" % (facts["arch"] or "draft"))
        elif blocks and 0 not in blocks:
            # 没有第 0 层：只可能是外挂的草稿头 / 残片，绝不当主模型
            res = (ROLE_DRAFT, _draft_kind(names, nkind, facts["nextn_layers"], facts["arch"]),
                   "缺少 blk.0 层，只是草稿头/碎片")
        elif nrole == ROLE_DRAFT and not blocks:
            res = (ROLE_DRAFT, _draft_kind(names, nkind, facts["nextn_layers"], facts["arch"]),
                   "文件名标记为投机草稿头")
        elif facts["nextn_layers"] and not names:
            res = (ROLE_MODEL, "", "元数据声明 MTP")
        else:
            res = (ROLE_MODEL, "", "")
        result = res
    if len(cache) > 4096:
        cache.clear()
    if use_cache:
        cache[key] = (stamp, result)
    return result


def detect_mtp(path):
    """检测模型是否包含 MTP（多 token 预测）能力。

    同时参考张量名与元数据（nextn_predict_layers / mtp），并自动处理多文件分片模型。
    返回 (支持与否, 匹配到的张量名列表)。全部无法解析时返回 (None, [])。
    """
    files = _shard_group_files(path)
    hits, any_ok, meta = [], False, False
    for f in files:
        facts = probe_gguf(f)
        if facts is None:
            continue
        any_ok = True
        for n in facts["names"]:
            ln = n.lower()
            if any(p in ln for p in MTP_TENSOR_PATTERNS) and n not in hits:
                hits.append(n)
        if facts["nextn_layers"] > 0:
            meta = True
    if not meta:      # 解析不了张量表的老文件，退回纯元数据扫描
        meta = any(_scan_mtp_meta(f) for f in files)
    if meta and "metadata:nextn_predict_layers" not in hits:
        hits.append("metadata:nextn_predict_layers")
    if not any_ok:
        return (True, hits) if meta else (None, [])
    return len(hits) > 0, hits[:8]


def read_chat_template(path):
    """读取 GGUF 元数据中的对话模板字符串（tokenizer.chat_template）。

    返回 (parsed_ok, template)：
    - parsed_ok=False 表示文件无法解析（读不到头部）；
    - parsed_ok=True 但 template 为空表示模型确实没有内置对话模板。
    自动处理多文件分片模型。
    """
    files = _shard_group_files(path)
    parsed = False
    for fp in files:
        try:
            with open(fp, "rb") as f:
                if f.read(4) != GGUF_MAGIC:
                    continue
                parsed = True
                _u32(f)          # version
                _u64(f)          # tensor_count
                kv_count = _u64(f)
                for _ in range(kv_count):
                    key = _read_string(f)
                    vtype = _u32(f)
                    value = _read_value(f, vtype)
                    if key == "tokenizer.chat_template" and isinstance(value, str):
                        return True, value
        except Exception:
            continue
    return parsed, ""


def detect_chat_features(path):
    """检测模型的对话模板能力。

    返回 (has_template, has_reasoning)：
    - has_template: True=含 chat_template（可启用 --jinja）；False=无；None=无法检测；
    - has_reasoning: 模板是否真的支持「思考强度档位」（reasoning_effort）。

    注意：enable_thinking / thinking 只代表支持「思考开/关」，不代表支持
    low/medium/high 档位。两者混为一谈会把 Qwen3、Gemma 等误判成支持档位。
    """
    caps = detect_chat_capabilities(path)
    if not caps.get("has_template"):
        return caps.get("has_template"), False
    return True, bool(caps.get("effort"))


_EFFORT_LEVELS = ("minimal", "low", "medium", "high", "xhigh", "max")


def detect_chat_capabilities(path):
    """读取模板并区分「思考开关」与「思考档位」。

    返回 dict:
      has_template: True/False/None
      thinking: 模板是否接受思考开关（enable_thinking / thinking / reasoning）
      effort: 模板是否接受 reasoning_effort 档位
      efforts: 从模板中能确认的档位列表（至少包含常用 6 档）
      toggle_var: 找到的开关变量名（用于提示）
    """
    parsed, tpl = read_chat_template(path)
    if not parsed:
        return {"has_template": None, "thinking": False, "effort": False,
                "efforts": [], "toggle_var": ""}
    if not tpl:
        return {"has_template": False, "thinking": False, "effort": False,
                "efforts": [], "toggle_var": ""}
    low = tpl.lower()
    toggle = ""
    for var in ("enable_thinking", "thinking", "reasoning"):
        if var in low:
            toggle = var
            break
    effort = "reasoning_effort" in low
    efforts = []
    if effort:
        # 模板里出现过的档位名；没写全时补常用档位，避免界面只剩 low/high
        for lv in _EFFORT_LEVELS:
            if lv in low:
                efforts.append(lv)
        for lv in _EFFORT_LEVELS:
            if lv not in efforts:
                efforts.append(lv)
    return {"has_template": True, "thinking": bool(toggle), "effort": effort,
            "efforts": efforts, "toggle_var": toggle}


def _quant_label(name, info):
    """量化格式：优先文件名，其次元数据 general.file_type。

    Unsloth UD 动态量化的 general.file_type 常写成统一的名义值（如把 Q4_K_XL
    标成 Q5_K_S），因此文件名更可靠。返回 (标签, 是否来自文件名)。"""
    m = QUANT_RE.search(name or "")
    if m:
        return m.group(1).upper(), True
    ft = info.get("general.file_type")
    if ft is not None:
        return FILE_TYPE_NAMES.get(ft, t('未知')), False
    return None, False


def format_gguf_info(path):
    info = read_gguf_info(path)
    size = os.path.getsize(path) if os.path.exists(path) else 0
    name = os.path.basename(path)
    abs_path = os.path.abspath(path)   # A6: 首行包含绝对路径，保留原「模型文件」行
    if info is None:
        return (t('文件路径: {0}\n模型文件: {1}\n无法解析 GGUF 头部（可能不是有效的 GGUF 文件）。\n文件大小: {2}').format(abs_path, name, human_size(size)))

    lines = [t('文件路径: {0}').format(abs_path), t('模型文件: {0}').format(name),
             t('文件大小: {0}').format(human_size(size))]

    arch = info.get("general.architecture")
    if arch:
        lines.append(t('架构: {0}').format(arch))
    gname = info.get("general.name")
    if gname:
        lines.append(t('模型名称: {0}').format(gname))

    qname, from_name = _quant_label(name, info)
    qt = t('量化格式: {0}').format(qname or t('未知'))
    if from_name:
        qt += t('（取自文件名）')
    elif info.get("general.file_type") is not None:
        qt += t('（取自元数据，动态量化可能不准）')
    lines.append(qt)

    if info.get("general.quantized_by"):
        lines.append(t('量化者: {0}').format(info['general.quantized_by']))

    if info.get("parameter_count"):
        lines.append(t('参数量: {0}').format(human_params(info['parameter_count'])))
    elif info.get("general.size_label"):
        lines.append(t('参数量: {0}').format(info['general.size_label']))

    if info.get("general.license"):
        lines.append(t('许可证: {0}').format(info['general.license']))

    bm = " / ".join(x for x in (info.get("base_model_org"), info.get("base_model_name")) if x)
    if bm:
        lines.append(t('基础模型: {0}').format(bm))

    ctx = info.get("context_length")
    if ctx is not None:
        lines.append(t('模型训练上下文(token): {0}').format(ctx))
        lines.append(t('（即模型本身原生支持的最大上下文长度，供参考）'))

    if info.get("block_count") is not None:
        lines.append(t('层数(block): {0}').format(info['block_count']))
    if info.get("embedding_length") is not None:
        lines.append(t('嵌入维度: {0}').format(info['embedding_length']))
    if info.get("feed_forward_length") is not None:
        lines.append(t('前馈维度: {0}').format(info['feed_forward_length']))
    experts = info.get("expert_count")
    if experts:
        used = info.get("expert_used_count")
        if used:
            lines.append(t('模型类型: MoE（{0} 个专家，每 token 激活 {1} 个）').format(experts, used))
        else:
            lines.append(t('模型类型: MoE（{0} 个专家）').format(experts))
        if info.get("expert_feed_forward_length") is not None:
            lines.append(t('专家前馈维度: {0}').format(info['expert_feed_forward_length']))
        lines.append(t('提示: -ngl all 会把全部专家权重放进显存；显存不足请在「高级参数 → MoE 专家」设为前 N 层放 CPU。'))
    else:
        lines.append(t('模型类型: 稠密（Dense）'))

    def _first_int(v):
        if isinstance(v, (list, tuple)):
            v = v[0] if v else None
        return v if isinstance(v, int) else None

    hc, hkv = _first_int(info.get("head_count")), _first_int(info.get("head_count_kv"))
    if hc is not None:
        extra = ""
        if hkv and hkv != hc:
            gqa = (hc // hkv) if hkv else 0
            extra = f"（KV {hkv}，GQA {gqa}x）"
        lines.append(t('注意力头: {0}{1}').format(hc, extra))
    if info.get("key_length") is not None and info.get("value_length") is not None:
        lines.append(t('头维度: K {0} / V {1}').format(info['key_length'], info['value_length']))
    if info.get("rope_freq_base") is not None:
        try:
            lines.append(t('RoPE 频率基数: {0}').format(int(info['rope_freq_base'])))
        except (TypeError, ValueError):
            pass

    if info.get("nextn_layers"):
        lines.append(t('MTP/NextN 预测层: {0}').format(info['nextn_layers']))
    if info.get("ssm_state") is not None:
        lines.append(t('状态空间(SSM) state: {0}').format(info['ssm_state']))
    if info.get("vocab_size"):
        lines.append(t('词表大小: {0}').format(info['vocab_size']))
    if info.get("tensor_count"):
        lines.append(t('张量数量: {0}').format(info['tensor_count']))
    if info.get("version") is not None:
        lines.append(t('GGUF 版本: {0}').format(info['version']))

    if info.get("general.description"):
        lines.append(t('模型简介: {0}').format(info['general.description']))

    repo = info.get("base_model_url") or info.get("general.repo_url")
    if repo:
        lines.append(t('模型主页: {0}').format(repo))

    return "\n".join(lines)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"


def human_params(n):
    for unit in ("", "K", "M", "B", "T"):
        if n < 1000:
            return f"{n:.2f}{unit}" if unit else f"{int(n)}"
        n /= 1000
    return f"{n:.2f}T"
