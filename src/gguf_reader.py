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

INTERESTING_KEYS = {
    "general.architecture",
    "general.name",
    "general.file_type",
    "tokenizer.ggml.model",
}

QUANT_RE = re.compile(
    r"(?i)(F32|F16|BF16|Q2_K|Q3_K_S|Q3_K_M|Q3_K_L|Q4_K_S|Q4_K_M|Q5_K_S|Q5_K_M"
    r"|Q6_K|Q8_K|Q8_0|Q4_0|Q4_1|Q5_0|Q5_1|IQ2_XXS|IQ2_XS|IQ3_XXS|IQ1_S|IQ4_NL"
    r"|IQ3_S|IQ3_M|IQ2_S|IQ2_M|IQ4_XS|IQ1_M|TQ1_0|TQ2_0|Q4_0_4_4|Q4_0_4_8|Q4_0_8_8)"
)


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
                value = _read_value(f, vtype)
                if key in INTERESTING_KEYS:
                    info[key] = value
                elif "context_length" in key and "context_length" not in info:
                    info["context_length"] = value
                elif "parameter_count" in key and "parameter_count" not in info:
                    info["parameter_count"] = value
                elif "embedding_length" in key and "embedding_length" not in info:
                    info["embedding_length"] = value
                elif "projection_dim" in key and "projection_dim" not in info:
                    info["projection_dim"] = value
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


def format_gguf_info(path):
    info = read_gguf_info(path)
    size = os.path.getsize(path) if os.path.exists(path) else 0
    name = os.path.basename(path)
    abs_path = os.path.abspath(path)   # A6: 首行包含绝对路径，保留原「模型文件」行
    if info is None:
        return (f"文件路径: {abs_path}\n模型文件: {name}\n"
                f"无法解析 GGUF 头部（可能不是有效的 GGUF 文件）。\n文件大小: {human_size(size)}")
    lines = [f"文件路径: {abs_path}", f"模型文件: {name}"]
    lines.append(f"文件大小: {human_size(size)}")
    arch = info.get("general.architecture")
    if arch:
        lines.append(f"架构: {arch}")
    gname = info.get("general.name")
    if gname:
        lines.append(f"模型名称: {gname}")
    ctx = info.get("context_length")
    if ctx is not None:
        lines.append(f"模型训练上下文(token): {ctx}")
        lines.append("（即模型本身原生支持的最大上下文长度，供参考）")
    ft = info.get("general.file_type")
    qname = FILE_TYPE_NAMES.get(ft) if ft is not None else None
    m = QUANT_RE.search(name)
    if m:
        qname = m.group(1).upper()
    lines.append(f"量化格式: {qname or '未知'}")
    pc = info.get("parameter_count")
    if pc:
        lines.append(f"参数量: {human_params(pc)}")
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
