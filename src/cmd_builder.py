import json
import os
import re


def get_llama_server(llama_dir, launcher_exe=None):
    if launcher_exe and os.path.isfile(launcher_exe):
        return launcher_exe
    return os.path.join(llama_dir, "llama-server.exe")


def model_alias(path):
    base = os.path.basename(path)
    if base.lower().endswith(".gguf"):
        base = base[:-5]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base


# KV 缓存量化类型（llama.cpp -ctk/-ctv 允许值）
KV_CACHE_TYPES = ["f16", "bf16", "f32", "q8_0", "q4_0", "q4_1", "iq4_nl", "q5_0", "q5_1"]

# GPU 拆分模式（llama.cpp -sm）
SPLIT_MODES = ["layer", "row", "tensor", "none"]


def _kv_types(s):
    """返回 (K类型, V类型)。兼容旧配置的单键 kv_cache_type。"""
    legacy = str(s.get("kv_cache_type") or "").strip()
    k = str(s.get("kv_cache_k") or "").strip() or legacy or "f16"
    v = str(s.get("kv_cache_v") or "").strip() or legacy or "f16"
    if k not in KV_CACHE_TYPES:
        k = "f16"
    if v not in KV_CACHE_TYPES:
        v = "f16"
    return k, v


def _selected_devices(s):
    """返回选中的 GPU 设备列表（字符串）。"""
    devs = s.get("devices") or []
    out = [str(d).strip() for d in devs if str(d).strip()]
    # 去重且保序
    seen, res = set(), []
    for d in out:
        if d not in seen:
            seen.add(d)
            res.append(d)
    return res


def build_args(model_path, mmproj_path, s, llama_dir, launcher_exe=None):
    args = [get_llama_server(llama_dir, launcher_exe)]
    args += ["-m", model_path]
    if mmproj_path:
        args += ["--mmproj", mmproj_path]

    ngl = str(s.get("ngl", "all")).strip()
    if ngl:
        args += ["-ngl", "all" if ngl.lower() == "all" else ngl]

    ctx = int(s.get("ctx", 0) or 0)
    if ctx > 0:
        args += ["-c", str(ctx)]

    n_predict = int(s.get("n_predict", -1) or -1)
    if n_predict >= -1:
        args += ["-n", str(n_predict)]

    fa = str(s.get("flash_attn", "auto"))
    if fa in ("on", "off", "auto"):
        args += ["-fa", fa]

    if s.get("cont_batching"):
        args += ["--cont-batching"]

    # ---- 多显卡（功能 3）：设备选择 / 拆分模式 / tensor-split / 主 GPU ----
    devices = _selected_devices(s)
    if devices:
        # 勾选 1 张 = 指定只用该卡；勾选 ≥2 张 = 多卡拆分
        args += ["-dev", ",".join(devices)]
        if len(devices) > 1:
            sm = str(s.get("split_mode") or "layer").strip()
            if sm in SPLIT_MODES and sm != "none":
                args += ["-sm", sm]
            ts = str(s.get("tensor_split") or "").strip().replace("，", ",")
            if ts:
                args += ["-ts", ts]
            try:
                mg = int(s.get("main_gpu", 0) or 0)
            except (TypeError, ValueError):
                mg = 0
            if mg > 0:
                args += ["-mg", str(mg)]

    # ---- MTP（功能 4）：多 token 预测，作为投机解码的 draft-mtp 类型启用 ----
    if s.get("mtp"):
        args += ["--spec-type", "draft-mtp"]

    args += ["--host", str(s.get("host", "127.0.0.1"))]
    args += ["--port", str(int(s.get("port", 8080)))]

    threads = int(s.get("threads", -1) or -1)
    if threads > 0:
        args += ["-t", str(threads)]

    batch = int(s.get("batch", 2048) or 0)
    if batch > 0:
        args += ["-b", str(batch)]

    slots = int(s.get("slots", -1) or -1)
    if slots > 0:
        args += ["-np", str(slots)]

    # ---- KV 缓存 K / V 独立类型（功能 2）----
    k_type, v_type = _kv_types(s)
    args += ["-ctk", k_type, "-ctv", v_type]

    temp = float(s.get("temp", 0.8) or 0.8)
    args += ["--temp", f"{temp:.2f}"]

    top_k = int(s.get("top_k", 40) or 0)
    if top_k > 0:
        args += ["--top-k", str(top_k)]

    top_p = float(s.get("top_p", 0.95) or 0.0)
    if top_p > 0:
        args += ["--top-p", f"{top_p:.2f}"]

    rp = float(s.get("repeat_penalty", 1.0) or 0.0)
    if rp > 0:
        args += ["--repeat-penalty", f"{rp:.2f}"]

    api_key = str(s.get("api_key", "") or "").strip()
    if api_key:
        args += ["--api-key", api_key]

    if s.get("mlock"):
        args += ["--mlock"]
    if s.get("no_mmap"):
        args += ["--no-mmap"]

    args += ["--timeout", str(int(s.get("timeout", 3600) or 3600))]
    args += ["-a", model_alias(model_path)]

    # ---- 对话模板（功能 8）：Jinja 模板 / 思考强度 / 推理预算 ----
    if s.get("jinja"):
        args += ["--jinja"]
    effort = str(s.get("reasoning_effort") or "").strip()
    # 思考强度是对话模板参数，必须配合 --jinja 才有效
    if effort and s.get("jinja"):
        kwargs = json.dumps({"reasoning_effort": effort}, ensure_ascii=False,
                            separators=(",", ":"))
        args += ["--chat-template-kwargs", kwargs]
    try:
        rbudget = int(s.get("reasoning_budget", -1) or -1)
    except (TypeError, ValueError):
        rbudget = -1
    if rbudget >= 0:
        args += ["--reasoning-budget", str(rbudget)]
    return args


def quote_arg(a):
    if not a:
        return '""'
    if all(c.isalnum() or c in "._-:/\\@" for c in a):
        return a
    return '"' + a.replace('"', '\\"') + '"'


def build_command(args):
    return " ".join(quote_arg(a) for a in args)


def quote_bat(a):
    """为 cmd.exe 批处理安全引用一个参数（% 需加倍，含空格的用引号包裹，内部引号转义为 \\"）。"""
    a = str(a).replace("%", "%%")
    if not a:
        return '""'
    if all(c.isalnum() or c in "._-:/\\@" for c in a):
        return a
    return '"' + a.replace('"', '\\"') + '"'


def build_bat_content(model_path, mmproj_path, s, llama_dir, launcher_exe=None):
    """根据配置生成可直接双击启动 llama-server 的 .bat 内容（UTF-8）。"""
    args = build_args(model_path, mmproj_path, s, llama_dir, launcher_exe=launcher_exe)
    alias = model_alias(model_path)
    host = str(s.get("host", "127.0.0.1"))
    port = str(int(s.get("port", 8080) or 8080))

    L = ["@echo off", "chcp 65001 >nul", f"title LLama Server - {alias}", "echo."]
    L.append("echo ============================================================")
    L.append("echo   LLama Server 一键启动")
    L.append("echo   模型 : " + model_alias(model_path) + ".gguf")
    if mmproj_path:
        L.append("echo   视觉 : " + model_alias(mmproj_path))
    L.append(f"echo   API  : http://{host}:{port}/v1")
    L.append("echo   Ctrl+C 可停止服务")
    L.append("echo ============================================================")
    L.append("echo.")

    if s.get("auto_open_browser", True):
        L.append(f'start "" "http://{host}:{port}/"')

    L.append(" ".join(quote_bat(a) for a in args))
    L.append("echo.")
    L.append("pause")
    return "\r\n".join(L) + "\r\n"


def build_preview_bat(preview_text, title="LLama Server"):
    """把「命令预览」里的完整命令行原样导出为 .bat 内容（功能 6）。"""
    cmd = (preview_text or "").strip()
    L = ["@echo off", "chcp 65001 >nul", f"title {title}", "echo."]
    if cmd:
        L.append("echo 正在启动 llama-server …")
        L.append(cmd)
    else:
        L.append("echo （预览为空，未生成命令）")
    L += ["echo.", "pause"]
    return "\r\n".join(L) + "\r\n"
