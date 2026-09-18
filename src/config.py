import json
import os

CONFIG_FILE = "config.json"

DEFAULTS = {
    "llama_dir": "",
    "launcher_exe": "",
    "data_dir": "",
    "model": "",
    "mmproj": "",
    # 模型列表排序：dir_name=目录+文件名升序 / size_desc=大小降序 / name=名称升序
    "model_sort": "dir_name",
    # HF 下载默认保存目录（空 = 使用模型目录）
    "hf_download_dir": "",
    # llama.cpp 更新目标目录（空 = 使用启动器 exe 所在目录/模型目录）
    "updater_target": "",
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
        # KV 缓存 K / V 独立类型（-ctk / -ctv）
        "kv_cache_k": "f16",
        "kv_cache_v": "f16",
        # 多显卡：选中设备列表、拆分模式、tensor-split 权重、主 GPU 索引
        "devices": [],
        "split_mode": "layer",
        "tensor_split": "",
        "main_gpu": 0,
        # MTP（多 token 预测，--spec-type draft-mtp）
        "mtp": False,
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
    "theme": "dark",
    "window_geometry": None,
    # 以下为历史版本出现过、或供扩展使用的键，统一补齐避免 JSON 缺项
    "custom_tools": [],
    "opencode_workdir": "",
    "last_download_dir": "",
}


def _migrate(data):
    """旧配置兼容：单键 kv_cache_type 迁移为 kv_cache_k / kv_cache_v。

    规则：旧键存在且用户改过（非默认 f16）时，覆盖仍处于默认值的 k/v；
    若 k/v 已有用户自定义值则保留。
    """
    s = data.get("server")
    if isinstance(s, dict) and "kv_cache_type" in s:
        legacy = str(s.pop("kv_cache_type") or "").strip()
        dflt_k = DEFAULTS["server"]["kv_cache_k"]
        dflt_v = DEFAULTS["server"]["kv_cache_v"]
        for key, dflt in (("kv_cache_k", dflt_k), ("kv_cache_v", dflt_v)):
            if legacy and s.get(key) in (None, "", dflt):
                s[key] = legacy
    return data


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

    def _read(self, path):
        self.data = _migrate(_merge(DEFAULTS, {}))
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.data = _migrate(_merge(DEFAULTS, loaded))
            except Exception:
                pass

    def apply_loaded(self, loaded):
        """导入外部配置（.aic/.json）时使用：合并默认值并做旧键迁移。"""
        if isinstance(loaded, dict):
            self.data = _migrate(_merge(DEFAULTS, loaded))
        else:
            raise ValueError("文件内容不是有效的配置")

    def load(self):
        # 先读程序目录的引导配置
        self._read(os.path.join(self.base_dir, CONFIG_FILE))
        # 若引导配置指定了数据目录，则重定向到数据目录读取权威配置
        dd = self.data.get("data_dir")
        if dd and os.path.isdir(dd):
            alt = os.path.join(dd, CONFIG_FILE)
            if os.path.abspath(alt) != os.path.abspath(self.path):
                self.path = alt
                self._read(alt)
        if not self.data.get("llama_dir"):
            parent = os.path.dirname(os.path.abspath(self.base_dir))
            self.data["llama_dir"] = parent if os.path.isdir(parent) else ""

    def data_dir(self):
        """返回数据存储目录；未设置或无效时回退到程序目录。"""
        dd = self.data.get("data_dir")
        if dd and os.path.isdir(dd):
            return dd
        return self.base_dir

    def ensure_data_dir(self):
        """确保数据目录存在并返回；失败回退程序目录。"""
        dd = self.data.get("data_dir")
        if dd:
            try:
                os.makedirs(dd, exist_ok=True)
                return dd
            except Exception:
                pass
        return self.base_dir

    def redirect_data_dir(self, new_dir):
        """把数据存储位置切换到 new_dir（空串 = 恢复为程序目录）。
        更新 self.path、在程序目录写入引导指针，并立即保存。"""
        new_dir = (new_dir or "").strip()
        if new_dir:
            new_dir = os.path.abspath(new_dir)
            self.data["data_dir"] = new_dir
            self.path = os.path.join(new_dir, CONFIG_FILE)
            try:
                os.makedirs(new_dir, exist_ok=True)
            except Exception:
                pass
            pointer = {"data_dir": new_dir}
        else:
            self.data["data_dir"] = ""
            self.path = os.path.join(self.base_dir, CONFIG_FILE)
            pointer = {"data_dir": ""}
        try:
            same = bool(new_dir) and os.path.abspath(new_dir) == os.path.abspath(self.base_dir)
            if not same:
                with open(os.path.join(self.base_dir, CONFIG_FILE), "w", encoding="utf-8") as f:
                    json.dump(pointer, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return self.save()

    def save(self):
        try:
            parent = os.path.dirname(self.path) or self.base_dir
            os.makedirs(parent, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False
