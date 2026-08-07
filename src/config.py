import json
import os

CONFIG_FILE = "config.json"

DEFAULTS = {
    "llama_dir": "",
    "model": "",
    "mmproj": "",
    "server": {
        "host": "127.0.0.1",
        "port": 8080,
        "ngl": "all",
        "ctx": 32768,
        "n_predict": 8192,
        "threads": -1,
        "batch": 2048,
        "flash_attn": "on",
        "cont_batching": True,
        "kv_cache_type": "f16",
        "slots": -1,
        "temp": 0.8,
        "top_p": 0.95,
        "top_k": 40,
        "repeat_penalty": 1.0,
        "api_key": "",
        "mlock": False,
        "no_mmap": False,
        "timeout": 3600,
        "auto_open_browser": True,
    },
    "tools": {},
    "last_agent_tool": "",
    "minimize_to_tray": True,
    "theme": "light",
    "window_geometry": None,
}


def _merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            if k in base:
                out[k] = _merge(base[k], v)
            else:
                out[k] = v
        return out
    return override


class Config:
    def __init__(self, base_dir):
        self.base_dir = base_dir
        self.path = os.path.join(base_dir, CONFIG_FILE)
        self.data = _merge(DEFAULTS, {})
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.data = _merge(DEFAULTS, loaded)
            except Exception:
                pass
        if not self.data.get("llama_dir"):
            parent = os.path.dirname(os.path.abspath(self.base_dir))
            self.data["llama_dir"] = parent if os.path.isdir(parent) else ""

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False
