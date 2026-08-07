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


def format_gguf_info(path):
    info = read_gguf_info(path)
    size = os.path.getsize(path) if os.path.exists(path) else 0
    name = os.path.basename(path)
    if info is None:
        return f"模型文件: {name}\n无法解析 GGUF 头部（可能不是有效的 GGUF 文件）。\n文件大小: {human_size(size)}"
    lines = [f"模型文件: {name}"]
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
