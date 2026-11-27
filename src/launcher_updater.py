"""启动器自升级：检查 GitHub Release、下载对应架构的 exe、退出后替换并重启。

只依赖 requests + 标准库；GUI 在 ui/launcher_update_dialog.py。
源码运行（python main.py）不做替换，只提示打开 Release 页面。
"""
import os
import re
import subprocess
import sys
import tempfile

import requests

from . import __version__
from .i18n import t

GH_API = "https://api.github.com/repos/lop008/llama-gui-launcher"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "LLamaLauncher-Updater",
}
CREATE_NO_WINDOW = 0x08000000


class UpdateError(Exception):
    pass


def parse_version(text):
    """把 v0.6.0 / 0.5.15 / 0.6.0-beta 解析成可比较的元组。

    返回 (major, minor, patch, suffix)；suffix 为空表示正式版，beta/rc 排在
    同版本正式版之前。解析不出返回 (0,0,0,"")。
    """
    s = str(text or "").strip().lstrip("vV")
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?(?:[-+]?([0-9A-Za-z.\-]+))?", s)
    if not m:
        return (0, 0, 0, "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), m.group(4) or "")


def is_newer(current, latest):
    a = parse_version(current)
    b = parse_version(latest)
    if b[:3] != a[:3]:
        return b[:3] > a[:3]
    # 同版本：正式版 > 预发布
    return bool(a[3]) and not b[3]


def latest_release():
    try:
        r = requests.get(f"{GH_API}/releases/latest", headers=HEADERS, timeout=30)
    except requests.exceptions.RequestException as e:
        raise UpdateError(t('网络请求失败: {0}').format(e)) from e
    if not (200 <= r.status_code < 300):
        raise UpdateError(t('GitHub API 返回 HTTP {0}').format(r.status_code))
    rel = r.json() or {}
    return {
        "tag": rel.get("tag_name", ""),
        "name": rel.get("name", "") or rel.get("tag_name", ""),
        "published_at": (rel.get("published_at") or "")[:10],
        "body": rel.get("body") or "",
        "html_url": rel.get("html_url") or "",
        "assets": [{
            "name": a.get("name", ""),
            "size": int(a.get("size") or 0),
            "url": a.get("browser_download_url", ""),
        } for a in (rel.get("assets") or [])],
    }


def host_arch():
    for probe in (os.environ.get("PROCESSOR_ARCHITEW6432"),
                  os.environ.get("PROCESSOR_ARCHITECTURE"),
                  os.environ.get("PROCESSOR_IDENTIFIER")):
        if (probe or "").lower().find("arm") >= 0:
            return "arm64"
    return "x64"


def pick_asset(release, arch=None):
    """挑当前架构的单文件 exe；没有 exe 时返回 portable zip。"""
    arch = arch or host_arch()
    assets = release.get("assets") or []
    exes = [a for a in assets if a.get("name", "").lower().endswith(".exe")]
    zips = [a for a in assets if a.get("name", "").lower().endswith(".zip")]
    for pool in (exes, zips):
        for a in pool:
            name = a.get("name", "").lower()
            if arch in name:
                return a
        for a in pool:
            if "x64" in a.get("name", "").lower() and arch == "x64":
                return a
            if "arm64" in a.get("name", "").lower() and arch == "arm64":
                return a
    return None


def download(url, dest, progress_cb=None, cancel=None):
    """断点续传下载到 dest（先写 .part，完成后替换）。返回最终路径。"""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    part = dest + ".part"
    pos = os.path.getsize(part) if os.path.isfile(part) else 0
    headers = dict(HEADERS)
    if pos:
        headers["Range"] = f"bytes={pos}-"
    try:
        r = requests.get(url, headers=headers, stream=True, timeout=60)
    except requests.exceptions.RequestException as e:
        raise UpdateError(t('网络请求失败: {0}').format(e)) from e
    if r.status_code == 416 and pos:
        os.replace(part, dest)
        return dest
    if not (200 <= r.status_code < 300):
        raise UpdateError(t('下载失败：HTTP {0}').format(r.status_code))
    mode = "ab" if pos and r.status_code == 206 else "wb"
    total = 0
    try:
        total = int(r.headers.get("Content-Length") or 0) + (pos if mode == "ab" else 0)
    except Exception:
        total = 0
    done = pos if mode == "ab" else 0
    with open(part, mode) as f:
        for chunk in r.iter_content(chunk_size=1024 * 256):
            if not chunk:
                continue
            if cancel and cancel():
                raise UpdateError(t('已取消下载'))
            f.write(chunk)
            done += len(chunk)
            if progress_cb:
                try:
                    progress_cb(done, total)
                except Exception:
                    pass
    os.replace(part, dest)
    return dest


def can_self_update():
    return bool(getattr(sys, "frozen", False))


def schedule_replace(new_exe, current_exe, pid=None, restart=True):
    """生成一个独立 .bat：等本进程退出 → 备份旧 exe → 覆盖 → 重启。

    返回 bat 路径；失败抛 UpdateError。
    """
    if not os.path.isfile(new_exe):
        raise UpdateError(t('新版本文件不存在：{0}').format(new_exe))
    if not os.path.isfile(current_exe):
        raise UpdateError(t('当前程序文件不存在：{0}').format(current_exe))
    bat_path = os.path.join(tempfile.gettempdir(), "llama_launcher_update.bat")
    bak = current_exe + ".bak"
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "setlocal",
    ]
    if pid:
        try:
            p = int(pid)
        except (TypeError, ValueError):
            p = 0
        if p > 0:
            lines += [
                ":wait",
                f'tasklist /fi "PID eq {p}" | find "{p}" >nul',
                "if not errorlevel 1 (ping -n 3 127.0.0.1 >nul & goto wait)",
            ]
    lines += [
        f'if exist "{bak}" del /f /q "{bak}"',
        f'move /y "{current_exe}" "{bak}" >nul',
        f'move /y "{new_exe}" "{current_exe}" >nul',
    ]
    if restart:
        lines.append(f'start "" "{current_exe}"')
    lines += [
        'del /f /q "%~f0" >nul 2>nul',
        "endlocal",
    ]
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines) + "\r\n")
    try:
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_GROUP = 0x00000200
        subprocess.Popen(["cmd", "/c", bat_path],
                         creationflags=DETACHED_PROCESS | CREATE_NEW_GROUP | CREATE_NO_WINDOW,
                         close_fds=True)
    except Exception as e:
        raise UpdateError(t('无法启动替换脚本：{0}').format(e)) from e
    return bat_path
