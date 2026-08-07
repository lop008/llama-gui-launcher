import os
import re


def get_llama_server(llama_dir):
    return os.path.join(llama_dir, "llama-server.exe")


def model_alias(path):
    base = os.path.basename(path)
    if base.lower().endswith(".gguf"):
        base = base[:-5]
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base


def build_args(model_path, mmproj_path, s, llama_dir):
    args = [get_llama_server(llama_dir)]
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

    kvc = str(s.get("kv_cache_type", "f16"))
    args += ["-ctk", kvc, "-ctv", kvc]

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
    return args


def quote_arg(a):
    if not a:
        return '""'
    if all(c.isalnum() or c in "._-:/\\@" for c in a):
        return a
    return '"' + a.replace('"', '\\"') + '"'


def build_command(args):
    return " ".join(quote_arg(a) for a in args)
