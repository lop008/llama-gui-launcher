"""HuggingFace 模型联网评估：用本地模型名搜索 HF 仓库，拉取简介/下载量/点赞等。"""
import json
import os
import time

import requests

CACHE_FILE = "hf_model_cache.json"
CACHE_TTL = 7 * 24 * 3600  # 7 天


def _cache_path(base_dir):
    return os.path.join(base_dir, CACHE_FILE)


def _load_cache(base_dir):
    p = _cache_path(base_dir)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(base_dir, cache):
    try:
        with open(_cache_path(base_dir), "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _search_models(query, limit=5):
    r = requests.get(
        "https://huggingface.co/api/models",
        params={"search": query, "limit": limit, "sort": "downloads", "direction": -1},
        timeout=15,
    )
    r.raise_for_status()
    out = []
    for m in r.json():
        mid = m.get("id", "")
        out.append({
            "id": mid,
            "author": mid.split("/")[0] if mid else "",
            "downloads": m.get("downloads", 0),
            "likes": m.get("likes", 0),
            "last_modified": m.get("lastModified", ""),
            "tags": (m.get("tags", []) or [])[:6],
        })
    return out


def _fetch_readme_summary(model_id, max_chars=300):
    try:
        r = requests.get(f"https://huggingface.co/{model_id}/raw/main/README.md", timeout=15)
        if not r.ok:
            return ""
        text = r.text.strip()
        for para in text.split("\n\n"):
            p = para.strip()
            if p and not p.lstrip().startswith(("#", "|", "-", ">", "```")):
                return " ".join(p.split())[:max_chars]
        return ""
    except Exception:
        return ""


def get_model_info(base_dir, query):
    """按模型名查询 HF。返回 dict；失败返回 {'error': ...}。结果本地缓存 7 天。"""
    cache = _load_cache(base_dir)
    hit = cache.get(query)
    if hit and time.time() - hit.get("ts", 0) < CACHE_TTL:
        return hit.get("data")

    try:
        models = _search_models(query, limit=3)
        if not models:
            data = {"error": "未找到匹配的模型仓库"}
            cache[query] = {"ts": time.time(), "data": data}
            _save_cache(base_dir, cache)
            return data
        top = models[0]
        desc = _fetch_readme_summary(top["id"])
        data = {"models": models, "top": top, "desc": desc, "from_cache": False}
        cache[query] = {"ts": time.time(), "data": data}
        _save_cache(base_dir, cache)
        return data
    except requests.exceptions.RequestException as e:
        return {"error": f"网络请求失败: {e}"}
    except Exception as e:
        return {"error": f"查询失败: {e}"}


def format_info(base_dir, query):
    """把查询结果格式化为可显示的文本。"""
    info = get_model_info(base_dir, query)
    if "error" in info:
        return f"联网查询失败：{info['error']}"
    lines = []
    top = info["top"]
    lines.append("== 联网查询结果 ==")
    lines.append(f"推荐匹配: {top['id']}")
    lines.append(f"下载量: {top['downloads']:,} | 点赞: {top['likes']}")
    if top.get("tags"):
        lines.append("标签: " + ", ".join(top["tags"]))
    if info.get("desc"):
        lines.append("\n模型简介:\n" + info["desc"])
    if len(info["models"]) > 1:
        lines.append("\n其他候选:")
        for m in info["models"][1:]:
            lines.append(f"  {m['id']}  (下载 {m['downloads']:,}, 点赞 {m['likes']})")
    lines.append("\n(数据来自 HuggingFace，缓存 7 天)")
    return "\n".join(lines)
