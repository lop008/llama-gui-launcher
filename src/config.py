import json
import os
from .i18n import t

CONFIG_FILE = "config.json"

DEFAULTS = {
    # 界面语言：auto=跟随系统；或 zh-CN / zh-TW / en / ja / ko / ru / es / fr
    "language": "auto",
    "llama_dir": "",
    "launcher_exe": "",
    "data_dir": "",
    "model": "",
    "mmproj": "",
    # 模型列表排序：dir_name=目录+文件名升序 / size_desc=大小降序 / name=名称升序
    "model_sort": "dir_name",
    # 投机方式「自动」的优先级顺序（下拉框里拖动后保存；空 = spec_decode.SPEC_IDS 默认顺序）
    "spec_order": [],
    # HF 下载默认保存目录（空 = 使用模型目录）
    "hf_download_dir": "",
    # llama.cpp 更新目标目录（空 = 使用启动器 exe 所在目录/模型目录）
    "updater_target": "",
    "server": {
        "host": "127.0.0.1",
        "port": 8080,
        "ngl": "all",
        # MoE 专家卸载：off=不额外处理；cpu=--cpu-moe（全部专家放 CPU）；
        # n=--n-cpu-moe N（前 N 层专家放 CPU）；moe_cache_mib>0 时加 --moe-cache-mib
        "moe_mode": "off",
        "moe_layers": 0,
        "moe_cache_mib": 0,
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
        # 投机解码：off=不启用；auto=按「自动优先级」挑第一个可用的；
        # 其余取值见 spec_decode.SPEC_IDS（mtp / dflash2 / dflash / dspark /
        # lilicorr / eagle3 / simple / ngram-*）
        "spec_mode": "off",
        # 外部草稿文件（MTP 头 / DFlash / EAGLE-3 …）；空 = 用同目录自动配对的结果
        "spec_draft": "",
        # 一次草稿多少 token（--spec-draft-n-max）；0 = 用引擎默认(3)，不下发该参数
        "spec_draft_n": 0,
        # 对话模板：Jinja 模板开关 / 模板参数(reasoning_effort) / 推理预算
        "jinja": False,
        # on/off/auto = 下发给 llama-server 的 --reasoning；只对支持思考的模板有效
        "reasoning_mode": "auto",
        "reasoning_effort": "",
        "reasoning_budget": -1,
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
        # 局域网共享开关（勾选时 host 用 0.0.0.0，供界面回显）
        "lan_share": False,
        # HTTPS（自签名证书）：开启后拼入 --ssl-key-file/--ssl-cert-file
        "ssl_enabled": False,
    },
    "tools": {},
    "last_agent_tool": "",
    "minimize_to_tray": True,
    # 启动时检测残留 llama-server 进程并提示（可在「高级参数」中重新开启）
    "check_residual": True,
    # 端口被占用时建议更换端口（可在「高级参数」中关闭）
    "port_hint": True,
    "theme": "dark",
    "window_geometry": None,
    # 底部标签顺序（拖动后保存，为空 = 默认顺序）
    "tab_order": [],
    # 选择模型时自动联网查询 HuggingFace 补充信息
    "hf_query_enabled": False,
    # 缩到托盘后显示悬浮小窗（胶囊 + 悬停展开数据卡片）
    "hover_pill": True,
    # 悬浮小窗位置 [x, y]（null = 自动贴屏幕右下角）
    "hover_pill_pos": None,
    # 以下为历史版本出现过、或供扩展使用的键，统一补齐避免 JSON 缺项
    "custom_tools": [],
    # 用户隐藏的内置 Agent 工具 id（删除内置工具时写入）
    "tools_hidden": [],
    # 启动时检查启动器自身是否有新版本（GitHub Release）
    "check_launcher_update": True,
    "opencode_workdir": "",
    "last_download_dir": "",
}


def _migrate(data):
    """旧配置兼容：单键 kv_cache_type 迁移为 kv_cache_k / kv_cache_v；
    v0.5.14 及以前的「启用 MTP」勾选框迁移为「投机方式」下拉的具体取值。

    规则：旧键存在且用户改过（非默认 f16）时，覆盖仍处于默认值的 k/v；
    若 k/v 已有用户自定义值则保留。
    投机解码同理：旧配置勾过 MTP 就等价于选 "mtp"，没勾过等价于 "off"，
    保证升级后启动参数与升级前完全一致，不擅自给用户打开新的加速方式。
    """
    s = data.get("server")
    if isinstance(s, dict) and "kv_cache_type" in s:
        legacy = str(s.pop("kv_cache_type") or "").strip()
        dflt_k = DEFAULTS["server"]["kv_cache_k"]
        dflt_v = DEFAULTS["server"]["kv_cache_v"]
        for key, dflt in (("kv_cache_k", dflt_k), ("kv_cache_v", dflt_v)):
            if legacy and s.get(key) in (None, "", dflt):
                s[key] = legacy
    if isinstance(s, dict) and "mtp" in s:
        legacy_mtp = bool(s.pop("mtp"))
        if not str(s.get("spec_mode") or "").strip():
            s["spec_mode"] = "mtp" if legacy_mtp else "off"
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
            raise ValueError(t('文件内容不是有效的配置'))

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
