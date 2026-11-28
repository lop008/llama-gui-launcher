"""启动器自升级：检查 GitHub Release、下载对应架构的包、退出后替换并重启。

只依赖 requests + 标准库；GUI 在 ui/launcher_update_dialog.py。
源码运行（python main.py）不做替换，只提示打开 Release 页面。

三种安装形态要分开处理（v0.6.2）：
  single   单文件 exe（PyInstaller onefile）→ 直接换 exe
  portable 便携目录（exe + `_internal/`）→ 换 exe **并且**换 `_internal`，用户数据不动
  source   源码运行 → 不换自己，只打开 Release 页面

替换脚本（一个临时 .bat）**每一步都判 errorlevel，失败就回滚**，并把结果写进
`update_result.txt`（只写 ASCII 标记码，由界面翻成各语言）：老版本曾出现
「新版本 exe 被杀毒隔离 → 旧 exe 已被改名 .bak → 脚本照样启动不存在的文件」，
用户看到的现象是软件打不开了。现在这种情形会自动把 .bak 改回去。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import requests

from . import __version__
from .i18n import t

GH_API = "https://api.github.com/repos/lop008/llama-gui-launcher"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "LLamaLauncher-Updater",
}
CREATE_NO_WINDOW = 0x08000000

#: 替换脚本写回的标记码（ASCII，避免 bat 写中文时的编码坑），界面按 key 翻译
RESULT_OK = "ok"
RESULT_CODES = ("ok", "fail_locked", "fail_internal_locked", "fail_copy_internal",
                "fail_move_exe", "fail_rollback", "pending")


def result_text(code):
    """把替换脚本写的 ASCII 标记翻成当前语言的说明（惰性，跟着界面语言走）。"""
    return {
        RESULT_OK: t('升级完成'),
        "pending": t('升级脚本还在等程序退出'),
        "fail_locked": t('旧程序文件被占用（可能还没退出），已取消替换，原版本可以正常打开'),
        "fail_internal_locked": t('旧程序目录被占用，已取消替换，原版本可以正常打开'),
        "fail_copy_internal": t('新文件复制失败（磁盘空间不足或被安全软件拦截），已恢复原版本'),
        "fail_move_exe": t('新版本文件放不下（磁盘空间不足或被安全软件拦截），已恢复原版本'),
        "fail_rollback": t('替换失败，而且自动恢复也失败了：请把同目录下的 .bak 文件改回原来的文件名再启动'),
    }.get(str(code or ""), t('未知的升级结果标记：{0}').format(code))


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


# ------------------------------------------------------------------ 安装形态
def install_kind(exe_path=None):
    """当前是哪种安装方式：`portable` / `single` / `source`。

    判据是「exe 旁边有没有 `_internal/`」：PyInstaller onedir（便携包）必然带
    `_internal`，onefile 单文件没有。源码运行时两个条件都不满足。
    """
    if not getattr(sys, "frozen", False):
        return "source"
    exe = exe_path or sys.executable
    try:
        if os.path.isdir(os.path.join(os.path.dirname(os.path.abspath(exe)), "_internal")):
            return "portable"
    except OSError:
        pass
    return "single"


def can_self_update():
    return bool(getattr(sys, "frozen", False))


def _asset_kind(asset):
    name = str((asset or {}).get("name", "")).lower()
    if name.endswith(".exe"):
        return "exe"
    if name.endswith(".zip"):
        return "zip"
    return "other"


def pick_asset(release, arch=None, kind=None):
    """挑适合当前安装形态与架构的资产。

    单文件/源码 → 优先 `.exe`；**便携目录 → 优先 `-portable.zip`**（v0.6.2 修：
    原来一律优先 exe，便携版用户会被换成单文件包，`_internal/` 变成几十 MB 垃圾，
    启动还慢一截）。目标形态没有对应包时退而求其次，由界面如实说明。
    """
    arch = arch or host_arch()
    kind = kind or install_kind()
    assets = release.get("assets") or []
    exes = [a for a in assets if _asset_kind(a) == "exe"]
    zips = [a for a in assets if _asset_kind(a) == "zip"]

    def match(pool, want_name=None):
        if want_name:            # 先严格：架构 + 形态关键字都对上
            for a in pool:
                name = a.get("name", "").lower()
                if arch in name and want_name in name:
                    return a
        for a in pool:           # 再放宽：只按架构
            if arch in a.get("name", "").lower():
                return a
        return None

    if kind == "portable":
        got = match(zips, "portable") or match(exes)
    else:
        got = match(exes) or match(zips, "portable")
    return got


def disk_space_ok(path, need_bytes):
    """目标盘（以及临时目录）够不够放新文件。返回 (够不够, 可用 GiB)。"""
    need = max(0, int(need_bytes or 0))
    avail = float("inf")
    for probe in {os.path.abspath(path or "."), tempfile.gettempdir()}:
        try:
            avail = min(avail, shutil.disk_usage(probe).free)
        except OSError:
            continue
    if avail == float("inf"):
        return True, 0.0        # 查不到就别拦人，交给后续 errorlevel 判定
    return avail >= need * 1.25 + 64 * 1024 * 1024, avail / 1024 ** 3


def verify_download(path, asset=None):
    """下载完整性检查：大小对不对 + 是不是个像样的 exe / zip。

    以前下载完直接改名覆盖，什么都不看。GitHub API 其实给了 asset 的 size，
    用它做第一道闸；再验文件头（`MZ` / zip 签名），能挡住「被安全软件截成
    空壳」「断点续传拼坏」这类文件。
    """
    if not os.path.isfile(path):
        return False, t('文件不存在')
    size = os.path.getsize(path)
    want = int((asset or {}).get("size") or 0)
    if want and size != want:
        return False, t('大小不符：下载到 {0} 字节，应为 {1} 字节').format(size, want)
    if size < 64:
        return False, t('文件太小，不像是可用的程序包')
    try:
        with open(path, "rb") as f:
            head = f.read(4)
    except OSError as e:
        return False, t('读不了文件：{0}').format(e)
    if path.lower().endswith(".zip"):
        if head[:2] != b"PK":
            return False, t('不是有效的 zip 包')
        if not zipfile.is_zipfile(path):
            return False, t('zip 包结构不完整')
    else:
        if head[:2] != b"MZ":
            return False, t('不是有效的 Windows 程序（文件头不对）')
    return True, ""


def download(url, dest, progress_cb=None, cancel=None, expect_size=0):
    """断点续传下载到 dest（先写 .part，完成后替换）。返回最终路径。

    `expect_size` 是 GitHub 报的资产大小：`.part` 只有在「和这次下载是同一个 URL，
    且不超过预期大小」时才复用。否则说明 Release 被重新上传过同名文件，续传会拼出
    一个坏 exe，必须重下（用 `.part.meta.json` 记下 URL）。
    """
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    part = dest + ".part"
    meta = part + ".meta.json"
    pos = os.path.getsize(part) if os.path.isfile(part) else 0
    if pos:
        keep = False
        try:
            import json
            old = json.load(open(meta, encoding="utf-8"))
            keep = old.get("url") == url
        except Exception:
            keep = False
        if keep and expect_size and pos > expect_size:
            keep = False       # 比预期还大：拼不上，重下
        if not keep:
            try:
                os.remove(part)
                if os.path.isfile(meta):
                    os.remove(meta)
            except OSError:
                pass
            pos = 0
    headers = dict(HEADERS)
    if pos:
        headers["Range"] = f"bytes={pos}-"
    try:
        r = requests.get(url, headers=headers, stream=True, timeout=60)
    except requests.exceptions.RequestException as e:
        raise UpdateError(t('网络请求失败: {0}').format(e)) from e
    if r.status_code == 416 and pos and (not expect_size or pos == expect_size):
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
    if mode == "wb":
        pos = 0
    done = pos
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
    try:
        import json
        with open(meta, "w", encoding="utf-8") as f:
            json.dump({"url": url, "size": done}, f)
    except OSError:
        pass
    os.replace(part, dest)
    return dest


def extract_package(zip_path, stage_dir):
    """把便携 zip 解到 stage_dir，返回 {"exe": 路径, "internal": 目录}。

    **不照搬 zip 里的顶层目录名**：便携包里那层目录名含中文（`LLama启动器-win-x64-portable/`），
    而 PyInstaller 写 zip 时没置 UTF-8 标志位，`zipfile` 按 cp437 解出来是乱码，
    路径就没法用。这里按「以 .exe 结尾 / 在 `_internal/` 之下」两类逐条落盘，
    既绕开乱码，也让替换脚本能预期目录结构。
    """
    if not zipfile.is_zipfile(zip_path):
        raise UpdateError(t('下载到的包不是有效 zip：{0}').format(os.path.basename(zip_path)))
    if os.path.isdir(stage_dir):
        shutil.rmtree(stage_dir, ignore_errors=True)
    os.makedirs(stage_dir, exist_ok=True)
    out_exe = ""
    has_internal = False
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            parts = info.filename.replace("\\", "/").split("/")
            leaf = parts[-1]
            if not leaf or leaf.startswith("."):
                continue
            if leaf.lower().endswith(".exe") and "_internal" not in parts:
                if out_exe:
                    continue           # 只认第一个 exe（便携包里本来就只有一个）
                out_exe = os.path.join(stage_dir, "launcher-new.exe")
                with zf.open(info) as src, open(out_exe, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 512)
            elif "_internal" in parts:
                rel = "/".join(parts[parts.index("_internal") + 1:])
                if not rel:
                    continue
                dst_path = os.path.join(stage_dir, "_internal", *rel.split("/"))
                os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                with zf.open(info) as src, open(dst_path, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 512)
                has_internal = True
    if not out_exe:
        raise UpdateError(t('包里没有找到启动器 exe'))
    if not has_internal:
        raise UpdateError(t('包里没有找到 _internal 目录，不像完整的便携包'))
    return {"exe": out_exe, "internal": os.path.join(stage_dir, "_internal")}


def result_path():
    return os.path.join(tempfile.gettempdir(), "llama_launcher_update_result.txt")


def read_last_result():
    """读上次替换脚本写的结果标记；没有记录返回 None。"""
    path = result_path()
    if not os.path.isfile(path):
        return None
    try:
        code = open(path, encoding="utf-8", errors="replace").read().strip().splitlines()
        code = code[-1].strip() if code else ""
    except OSError:
        return None
    try:
        os.remove(path)
    except OSError:
        pass
    return code or None


def _wait_for_exit(pid):
    """bat 里等本进程退出的片段：最多约 60 秒，避免误判时永久卡住。"""
    try:
        p = int(pid)
    except (TypeError, ValueError):
        p = 0
    if p <= 0:
        return []
    return [
        ":wait",
        f'tasklist /nh /fi "PID eq {p}" | find "{p}" >nul',
        "if errorlevel 1 goto go",
        "set /a UP_TRIES+=1",
        "if %UP_TRIES% GEQ 40 goto go",
        "ping -n 2 127.0.0.1 >nul",
        "goto wait",
        ":go",
    ]


def _bat(lines):
    """拼出完整的 bat 文本（统一 CRLF + 无 BOM，中文只在注释里出现不写）。"""
    return "\r\n".join(lines) + "\r\n"


def schedule_replace(new_exe, current_exe, pid=None, restart=True, internal_dir=None,
                     res_path=None):
    """生成独立 .bat：等本进程退出 → 备份 → 覆盖 → 重启；**任何一步失败都回滚**。

    - `internal_dir=None`：单文件版，只换 exe。
    - `internal_dir` 给了值：便携版，连 `_internal` 一起换（新内容先在 stage 目录里
      备齐），用户自己的 `config.json` / `logs` / `stats.json` 一个都不碰。
    - 结果写进 `res_path`（只有 ASCII 标记码），下次启动由界面翻成提示。

    返回 bat 路径；准备阶段失败抛 UpdateError。
    """
    if not os.path.isfile(new_exe):
        raise UpdateError(t('新版本文件不存在：{0}').format(new_exe))
    if not os.path.isfile(current_exe):
        raise UpdateError(t('当前程序文件不存在：{0}').format(current_exe))
    tmp = tempfile.gettempdir()
    bat_path = os.path.join(tmp, "llama_launcher_update.bat")
    res = res_path or result_path()
    bak = current_exe + ".bak"
    cur_dir = os.path.dirname(os.path.abspath(current_exe))
    tgt_internal = os.path.join(cur_dir, "_internal")
    old_internal = os.path.join(cur_dir, "_internal.old")

    lines = ["@echo off", "chcp 65001 >nul", "setlocal enableextensions",
             "set UP_TRIES=0"]
    lines += _wait_for_exit(pid)
    lines += [f'echo pending> "{res}"',
              f'if exist "{bak}" del /f /q "{bak}"']

    if internal_dir:
        # 便携版：exe + _internal 都要换，先挪旧的，再放新的，全程可回滚
        lines += [
            f'move /y "{current_exe}" "{bak}" >nul',
            f'if errorlevel 1 (echo fail_locked> "{res}" & goto end)',
            f'if exist "{old_internal}" rd /s /q "{old_internal}"',
            f'if exist "{tgt_internal}" (',
            f'  move /y "{tgt_internal}" "{old_internal}" >nul',
            f'  if errorlevel 1 (echo fail_internal_locked> "{res}" '
            f'& move /y "{bak}" "{current_exe}" >nul & goto end)',
            ')',
            f'xcopy /e /i /y /q "{internal_dir}" "{tgt_internal}" >nul',
            f'if errorlevel 1 (echo fail_copy_internal> "{res}" & goto rollback)',
            f'move /y "{new_exe}" "{current_exe}" >nul',
            f'if errorlevel 1 (echo fail_move_exe> "{res}" & goto rollback)',
            f'if exist "{old_internal}" rd /s /q "{old_internal}"',
            f'del /f /q "{bak}" >nul 2>nul',
            (f'start "" "{current_exe}"' if restart else "rem 不自动重启"),
            f'echo ok> "{res}"',
            "goto end",
            ":rollback",
            f'if exist "{tgt_internal}" rd /s /q "{tgt_internal}"',
            f'if exist "{old_internal}" move /y "{old_internal}" "{tgt_internal}" >nul',
            f'move /y "{bak}" "{current_exe}" >nul',
            # 回滚成功就**保留原来的失败原因**，界面才知道是哪一步出的问题；
            # 只有回滚也失败才改成 fail_rollback（那时才需要教用户手动改 .bak）
            f'if errorlevel 1 (echo fail_rollback> "{res}")',
        ]
    else:
        # 单文件版：只有 exe（这里不能复用上面的 :rollback——那条会清 _internal，
        # 而单文件版根本没动过它，误删就是拿用户目录里的东西开刀）
        lines += [
            f'move /y "{current_exe}" "{bak}" >nul',
            f'if errorlevel 1 (echo fail_locked> "{res}" & goto end)',
            f'move /y "{new_exe}" "{current_exe}" >nul',
            f'if errorlevel 1 (echo fail_move_exe> "{res}" & goto rollback_exe)',
            f'del /f /q "{bak}" >nul 2>nul',
            (f'start "" "{current_exe}"' if restart else "rem 不自动重启"),
            f'echo ok> "{res}"',
            "goto end",
            ":rollback_exe",
            f'move /y "{bak}" "{current_exe}" >nul',
            f'if errorlevel 1 (echo fail_rollback> "{res}")',
        ]
    lines += [":end", 'del /f /q "%~f0" >nul 2>nul', "endlocal"]
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write(_bat(lines))
    try:
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_GROUP = 0x00000200
        subprocess.Popen(["cmd", "/c", bat_path],
                         creationflags=DETACHED_PROCESS | CREATE_NEW_GROUP | CREATE_NO_WINDOW,
                         close_fds=True)
    except Exception as e:
        raise UpdateError(t('无法启动替换脚本：{0}').format(e)) from e
    return bat_path
