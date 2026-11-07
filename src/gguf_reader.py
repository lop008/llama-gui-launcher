import os
import re
import struct

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
    ("projection_dim", "projection_dim"),
)


def _capture(info, key, value):
    """把解析到的 KV 归入 info 的短名键（只取首个匹配，架构前缀不敏感）。"""
    if key in _SIMPLE_KEYS:
        info[_SIMPLE_KEYS[key]] = value
        return
    lk = key.lower()
    for suffix, name in _SUFFIX_MAP:
        if lk.endswith(suffix) and name not in info:
            info[name] = value
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


def detect_mtp(path):
    """检测模型是否包含 MTP（多 token 预测）能力。

    同时参考张量名与元数据（nextn_predict_layers / mtp），并自动处理多文件分片模型。
    返回 (支持与否, 匹配到的张量名列表)。全部无法解析时返回 (None, [])。
    """
    files = _shard_group_files(path)
    hits, any_ok = [], False
    for f in files:
        names = scan_tensor_names(f)
        if names is None:
            continue
        any_ok = True
        for n in names:
            ln = n.lower()
            if any(p in ln for p in MTP_TENSOR_PATTERNS) and n not in hits:
                hits.append(n)
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
    - has_reasoning: 模板是否支持思考强度/思考开关（reasoning_effort / enable_thinking / thinking）。
    """
    parsed, tpl = read_chat_template(path)
    if not parsed:
        return None, False
    if not tpl:
        return False, False
    low = tpl.lower()
    has_reasoning = ("reasoning_effort" in low or "enable_thinking" in low
                     or "thinking" in low)
    return True, has_reasoning


def _quant_label(name, info):
    """量化格式：优先文件名，其次元数据 general.file_type。

    Unsloth UD 动态量化的 general.file_type 常写成统一的名义值（如把 Q4_K_XL
    标成 Q5_K_S），因此文件名更可靠。返回 (标签, 是否来自文件名)。"""
    m = QUANT_RE.search(name or "")
    if m:
        return m.group(1).upper(), True
    ft = info.get("general.file_type")
    if ft is not None:
        return FILE_TYPE_NAMES.get(ft, "未知"), False
    return None, False


def format_gguf_info(path):
    info = read_gguf_info(path)
    size = os.path.getsize(path) if os.path.exists(path) else 0
    name = os.path.basename(path)
    abs_path = os.path.abspath(path)   # A6: 首行包含绝对路径，保留原「模型文件」行
    if info is None:
        return (f"文件路径: {abs_path}\n模型文件: {name}\n"
                f"无法解析 GGUF 头部（可能不是有效的 GGUF 文件）。\n文件大小: {human_size(size)}")

    lines = [f"文件路径: {abs_path}", f"模型文件: {name}",
             f"文件大小: {human_size(size)}"]

    arch = info.get("general.architecture")
    if arch:
        lines.append(f"架构: {arch}")
    gname = info.get("general.name")
    if gname:
        lines.append(f"模型名称: {gname}")

    qname, from_name = _quant_label(name, info)
    qt = f"量化格式: {qname or '未知'}"
    if from_name:
        qt += "（取自文件名）"
    elif info.get("general.file_type") is not None:
        qt += "（取自元数据，动态量化可能不准）"
    lines.append(qt)

    if info.get("general.quantized_by"):
        lines.append(f"量化者: {info['general.quantized_by']}")

    if info.get("parameter_count"):
        lines.append(f"参数量: {human_params(info['parameter_count'])}")
    elif info.get("general.size_label"):
        lines.append(f"参数量: {info['general.size_label']}")

    if info.get("general.license"):
        lines.append(f"许可证: {info['general.license']}")

    bm = " / ".join(x for x in (info.get("base_model_org"), info.get("base_model_name")) if x)
    if bm:
        lines.append(f"基础模型: {bm}")

    ctx = info.get("context_length")
    if ctx is not None:
        lines.append(f"模型训练上下文(token): {ctx}")
        lines.append("（即模型本身原生支持的最大上下文长度，供参考）")

    if info.get("block_count") is not None:
        lines.append(f"层数(block): {info['block_count']}")
    if info.get("embedding_length") is not None:
        lines.append(f"嵌入维度: {info['embedding_length']}")
    if info.get("feed_forward_length") is not None:
        lines.append(f"前馈维度: {info['feed_forward_length']}")

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
        lines.append(f"注意力头: {hc}{extra}")
    if info.get("key_length") is not None and info.get("value_length") is not None:
        lines.append(f"头维度: K {info['key_length']} / V {info['value_length']}")
    if info.get("rope_freq_base") is not None:
        try:
            lines.append(f"RoPE 频率基数: {int(info['rope_freq_base'])}")
        except (TypeError, ValueError):
            pass

    if info.get("nextn_layers"):
        lines.append(f"MTP/NextN 预测层: {info['nextn_layers']}")
    if info.get("ssm_state") is not None:
        lines.append(f"状态空间(SSM) state: {info['ssm_state']}")
    if info.get("vocab_size"):
        lines.append(f"词表大小: {info['vocab_size']}")
    if info.get("tensor_count"):
        lines.append(f"张量数量: {info['tensor_count']}")
    if info.get("version") is not None:
        lines.append(f"GGUF 版本: {info['version']}")

    if info.get("general.description"):
        lines.append(f"模型简介: {info['general.description']}")

    repo = info.get("base_model_url") or info.get("general.repo_url")
    if repo:
        lines.append(f"模型主页: {repo}")

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
