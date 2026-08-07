import json
import os
import shutil
import time

from . import tools


def build_config(host, port, alias, ctx, n_predict, api_key=""):
    base = f"http://{host}:{port}/v1"
    model_cfg = {"name": alias}
    limit = {}
    if ctx and int(ctx) > 0:
        limit["context"] = int(ctx)
    n = int(n_predict) if n_predict else 8192
    if n > 0:
        limit["output"] = n
    if limit:
        model_cfg["limit"] = limit
    provider = {
        "npm": "@ai-sdk/openai-compatible",
        "name": f"llama-server (local :{port})",
        "options": {"baseURL": base},
        "models": {alias: model_cfg},
    }
    if api_key:
        provider["options"]["apiKey"] = api_key
    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {"llama.cpp": provider},
    }


def write_config(workdir, config):
    path = os.path.join(workdir, "opencode.json")
    data = config
    if os.path.exists(path):
        bak = path + f".bak-{time.strftime('%Y%m%d%H%M%S')}"
        try:
            shutil.copy(path, bak)
        except Exception:
            pass
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if isinstance(existing, dict):
                providers = existing.setdefault("provider", {})
                providers["llama.cpp"] = config["provider"]["llama.cpp"]
                existing.setdefault("$schema", config.get("$schema"))
                data = existing
        except Exception:
            data = config
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def launch_tui(workdir):
    found = tools.find_executable("opencode")
    if not found:
        found = tools.find_executable("opencode.cmd")
    if not found:
        return False, "未找到 opencode，请在「Agent工具」中添加路径"
    ok = tools.open_terminal(f'"{found}"', workdir)
    return ok, ("已启动 opencode" if ok else "启动终端失败")
