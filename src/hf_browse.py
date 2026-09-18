"""HuggingFace 仓库浏览：检索组织/关键词下的模型仓库，列出其中 GGUF 文件。

默认面向 https://huggingface.co/unsloth （功能 5）。
仅依赖 requests；所有函数均为阻塞式（在后台线程中调用）。
"""
from urllib.parse import quote

import requests

HF_API = "https://huggingface.co/api/models"
HEADERS = {"User-Agent": "LLamaLauncher/0.2"}


class HFError(Exception):
    pass


def _get(url, params=None, timeout=25):
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise HFError(f"网络请求失败: {e}") from e
    if not (200 <= r.status_code < 300):
        raise HFError(f"HF 接口返回 HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError as e:
        raise HFError("HF 接口返回了非 JSON 内容") from e


def _get_raw(url, params=None, timeout=25):
    """返回 (json, headers)，用于读取分页 Link 头。"""
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise HFError(f"网络请求失败: {e}") from e
    if not (200 <= r.status_code < 300):
        raise HFError(f"HF 接口返回 HTTP {r.status_code}")
    try:
        return r.json(), r.headers
    except ValueError as e:
        raise HFError("HF 接口返回了非 JSON 内容") from e


def list_repos(author="unsloth", search=None, limit=100, cursor=None):
    """列出某组织（或关键词）下的模型仓库，按下载量降序。

    返回 [{id, downloads, likes, last_modified}]。
    """
    params = {
        "limit": int(limit),
        "sort": "downloads",
        "direction": -1,
        # 只要 GGUF 仓库，避免出现点进去没有 .gguf 文件的条目
        "filter": "gguf",
        # full=true 才会在列表接口返回 lastModified（「最近更新」列）
        "full": "true",
    }
    author = (author or "").strip().lstrip("@")
    search = (search or "").strip()
    if author:
        params["author"] = author
    if search:
        # author + search 组合可在该组织内做子串过滤；无组织时即全局搜索
        params["search"] = search
    if cursor:
        params["cursor"] = cursor
    try:
        data, _headers = _get_raw(HF_API, params)
    except HFError:
        # 个别镜像/旧接口不接受 full，退回基础参数（仅缺「最近更新」）
        params.pop("full", None)
        data, _headers = _get_raw(HF_API, params)
    out = []
    for m in data or []:
        mid = (m.get("id") or "").strip()
        if not mid:
            continue
        lm = (m.get("lastModified") or m.get("last_modified")
              or m.get("createdAt") or "")
        out.append({
            "id": mid,
            "downloads": int(m.get("downloads") or 0),
            "likes": int(m.get("likes") or 0),
            "last_modified": str(lm)[:10],
        })
    return out


def repo_info(repo_id):
    """仓库概览信息（不含文件列表）：下载量/点赞/标签/简介等。"""
    data = _get(f"https://huggingface.co/api/models/{quote(repo_id)}")
    card = data.get("cardData") if isinstance(data.get("cardData"), dict) else {}
    return {
        "id": repo_id,
        "downloads": int(data.get("downloads") or 0),
        "likes": int(data.get("likes") or 0),
        "last_modified": (data.get("lastModified") or "")[:10],
        "pipeline_tag": data.get("pipeline_tag") or "",
        "tags": list(data.get("tags") or []),
        "private": bool(data.get("private")),
        "description": (card.get("text") or card.get("model-index") or ""),
    }


def _natural_key(path):
    import re
    parts = re.split(r'(\d+)', str(path).lower())
    return [(0, int(p)) if p.isdigit() else (1, p) for p in parts if p]


def _files_from_tree(repo_id):
    """用 tree 接口获取文件（含每个文件的最近提交日期）。失败返回 None。"""
    url = f"https://huggingface.co/api/models/{quote(repo_id)}/tree/main"
    data = _get(url, params={"recursive": "true"})
    if not isinstance(data, list):
        return None
    files = []
    for e in data:
        if (e.get("type") or "file") != "file":
            continue
        fn = (e.get("path") or "").strip()
        if not fn.lower().endswith(".gguf"):
            continue
        lc = e.get("lastCommit") or {}
        date = ""
        if isinstance(lc, dict):
            date = str(lc.get("date") or "")[:10]
        try:
            size = int(e.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        files.append({"path": fn, "size": size, "date": date})
    return files


def repo_files(repo_id):
    """列出仓库中的 .gguf 文件（含子目录路径、大小与最近提交日期）。

    返回 {"id", "downloads", "likes", "last_modified", "tags", "pipeline_tag",
          "files": [{path, size, date}]}，files 按自然序排序。
    """
    data = _get(f"https://huggingface.co/api/models/{quote(repo_id)}")
    files = None
    try:
        files = _files_from_tree(repo_id)
    except Exception:
        files = None
    if files is None:
        # 回退：老接口 siblings（无日期）
        files = []
        for s in (data.get("siblings") or []):
            fn = (s.get("rfilename") or "").strip()
            if not fn.lower().endswith(".gguf"):
                continue
            try:
                size = int(s.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            files.append({"path": fn, "size": size, "date": ""})

    files.sort(key=lambda f: _natural_key(f["path"]))
    return {
        "id": repo_id,
        "downloads": int(data.get("downloads") or 0),
        "likes": int(data.get("likes") or 0),
        "last_modified": (data.get("lastModified") or "")[:10],
        "tags": list(data.get("tags") or []),
        "pipeline_tag": data.get("pipeline_tag") or "",
        "files": files,
    }


def file_url(repo_id, path):
    """仓库内文件的直链（resolve/main）。"""
    return f"https://huggingface.co/{quote(repo_id)}/resolve/main/{quote(path)}"
