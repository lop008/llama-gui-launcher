import json
import os
import re

from .spec_decode import SPEC_CLI


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


_SPEC_BY_CLI = {v[0]: (k, v[1]) for k, v in SPEC_CLI.items()}


def _spec_args(s):
    """投机解码参数（--spec-type / --spec-draft-model / --spec-draft-n-max）。

    界面负责把「自动」解析成具体方式并写进 spec_cli（模型/引擎检测在 UI 层做，
    这里只负责拼参数，保持可单测）；同时兼容 v0.5.14 及以前只有「启用 MTP」
    勾选框的配置。

    需要外部草稿的方式，如果草稿文件缺失或已被删除，就整体不传：宁可不加速，
    也不要让 llama-server 因为缺 -md 直接起不来。
    草稿层数 -ngld 交给引擎默认（auto），不传。
    """
    cli = str(s.get("spec_cli") or "").strip().lower()
    if not cli and s.get("mtp"):
        cli = "draft-mtp"
    if not cli or cli == "none" or cli not in _SPEC_BY_CLI:
        return []
    _sid, needs_draft = _SPEC_BY_CLI[cli]
    draft = str(s.get("spec_draft") or "").strip()
    draft_ok = bool(draft) and os.path.isfile(draft)
    if needs_draft and not draft_ok:
        return []
    args = ["--spec-type", cli]
    if draft_ok:
        args += ["--spec-draft-model", draft]
    try:
        n = int(s.get("spec_draft_n", 0) or 0)
    except (TypeError, ValueError):
        n = 0
    if n > 0:
        args += ["--spec-draft-n-max", str(n)]
    return args


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


def _moe_args(s):
    """MoE 专家卸载参数。

    - moe_mode = "cpu"  ：--cpu-moe，全部专家权重放 CPU（最省显存）；
    - moe_mode = "n"    ：--n-cpu-moe N，前 N 层专家放 CPU（MoE 最常用）；
    - moe_cache_mib > 0 ：--moe-cache-mib N，CPU 专家缓存（llama.cpp 新参数）。
    """
    args = []
    mode = str(s.get("moe_mode") or "off").strip().lower()
    if mode == "cpu":
        args.append("--cpu-moe")
    elif mode == "n":
        try:
            n = int(s.get("moe_layers", 0) or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            args += ["--n-cpu-moe", str(n)]
    try:
        cache = int(s.get("moe_cache_mib", 0) or 0)
    except (TypeError, ValueError):
        cache = 0
    if cache > 0:
        args += ["--moe-cache-mib", str(cache)]
    return args


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

    # ---- MoE 专家卸载（-cmoe / -ncmoe / --moe-cache-mib）----
    args += _moe_args(s)

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

    # ---- 投机解码（--spec-type / 外部草稿 / 草稿长度；兼容旧配置的 mtp 开关）----
    args += _spec_args(s)

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

    # ---- HTTPS（自签名证书）：私钥与证书成对存在时才启用 ----
    ssl_key = str(s.get("ssl_key_file", "") or "").strip()
    ssl_cert = str(s.get("ssl_cert_file", "") or "").strip()
    if ssl_key and ssl_cert:
        args += ["--ssl-key-file", ssl_key, "--ssl-cert-file", ssl_cert]

    if s.get("mlock") or s.get("no_mmap"):
        # 内存加载模式：llama.cpp 0.4.1（2026-09）删掉了 --mlock / --mmap / --no-mmap
        # / --direct-io，合并成 -lm/--load-mode。照旧写会直接 `error: invalid argument`
        # 启动失败，所以必须按本机版本翻译（本机 llama-server --help 是唯一依据）。
        args += load_mode_args(bool(s.get("mlock")), bool(s.get("no_mmap")), args[0])

    args += ["--timeout", str(int(s.get("timeout", 3600) or 3600))]
    args += ["-a", model_alias(model_path)]
    # Prometheus 指标（/metrics）：悬浮窗实时 tok/s 依赖 tokens_predicted_total 计数器差分
    args += ["--metrics"]

    # ---- 对话模板（功能 8）：Jinja 模板 / 思考开关 / 思考强度 / 推理预算 ----
    if s.get("jinja"):
        args += ["--jinja"]
    rmode = str(s.get("reasoning_mode") or "").strip().lower()
    if rmode in ("on", "off", "auto") and s.get("jinja"):
        args += ["--reasoning", rmode]
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


def load_mode_args(mlock, no_mmap, exe):
    """把「锁定内存 / 禁用 mmap」翻译成本机 llama.cpp 认得的加载模式写法。

    llama.cpp 0.4.1（2026-09）删掉了 `--mlock` / `--mmap` / `--no-mmap` / `--direct-io`，
    合并成 `-lm/--load-mode`（可选值 auto / none / mmap / mlock / mmap+mlock / dio）。
    旧写法在新版本上是 `error: invalid argument` 直接启动失败，所以不能照旧硬写；
    判断依据只有本机 `llama-server --help`（结果按 exe 缓存，不会每次都开子进程）。

      勾了锁定内存            新版 → -lm mmap+mlock     旧版 → --mlock
      勾了禁用 mmap           新版 → -lm none           旧版 → --no-mmap
      两个都勾                新版 → -lm mlock          旧版 → 两个都写
    """
    if not (mlock or no_mmap):
        return []
    try:
        # 用带缓存的 engine_flags：只有用户真勾了这两项才会走到这里，
        # 第一次 ~0.4s（启动时会后台预热），之后是纯查表。缓存必须命中，
        # 否则猜错写法就是 `error: invalid argument` 启动失败。
        from .launch_advisor import engine_flags
        engine = engine_flags(exe)
    except Exception:
        engine = None
    new = bool(engine) and "--load-mode" in engine
    if new:
        if mlock and no_mmap:
            return ["-lm", "mlock"]          # 锁内存且不 mmap
        if mlock:
            return ["-lm", "mmap+mlock"]     # 等价于老版 --mlock（仍然 mmap + 锁定）
        return ["-lm", "none"]               # 等价于老版 --no-mmap
    out = []
    if mlock:
        out.append("--mlock")
    if no_mmap:
        out.append("--no-mmap")
    return out


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
    scheme = "https" if (s.get("ssl_key_file") and s.get("ssl_cert_file")) else "http"

    L = ["@echo off", "chcp 65001 >nul", f"title LLama Server - {alias}", "echo."]
    L.append("echo ============================================================")
    L.append("echo   LLama Server 一键启动")
    L.append("echo   模型 : " + model_alias(model_path) + ".gguf")
    if mmproj_path:
        L.append("echo   视觉 : " + model_alias(mmproj_path))
    L.append(f"echo   API  : {scheme}://{host}:{port}/v1")
    L.append("echo   Ctrl+C 可停止服务")
    L.append("echo ============================================================")
    L.append("echo.")

    if s.get("auto_open_browser", True):
        L.append(f'start "" "{scheme}://{host}:{port}/"')

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
