"""llama.cpp 下载与更新（功能 10）。

- 从 https://github.com/ggml-org/llama.cpp 拉取 Release 列表（可选版本）；
- 选择 Windows 预编译包（.zip），断点续传下载；
- 「安全安装」：调用方先把目标目录顶层整体备份到 bak\\<tag>.zip，再无条件写入安装包
  内的新二进制/DLL（不按大小跳过）；仅当安装完整构建时才清理包外的旧 llama 产物，
  且不触碰 *-impl.dll 等自定义文件；模型、配置等其他文件一律不受影响。

仅依赖 requests / zipfile；阻塞式函数请在后台线程调用。
"""
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

import requests

from .model_downloader import HEADERS as _DL_HEADERS

GH_API = "https://api.github.com/repos/ggml-org/llama.cpp"
HEADERS = {**_DL_HEADERS(), "Accept": "application/vnd.github+json"}

CREATE_NO_WINDOW = 0x08000000

# 更新模式：server = llama-server.exe + 全部 DLL；all = zip 内所有文件
MODE_SERVER = "server"
MODE_ALL = "all"


class UpdaterError(Exception):
    pass


def get_local_version(exe_path, pid_cb=None):
    """运行 llama-server --version 解析本地版本号；失败/未安装返回 ""。阻塞式，请在后台线程调用。

    pid_cb(pid|None)：探测进程创建/退出时回调其 PID，便于调用方在「残留进程检测」
    中排除本程序自己发起的探测进程（否则每次启动都会误报残留）。
    """
    if not exe_path or not os.path.isfile(exe_path):
        return ""
    proc = None
    try:
        proc = subprocess.Popen(
            [exe_path, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
        if pid_cb:
            try:
                pid_cb(proc.pid)
            except Exception:
                pass
        try:
            out, _ = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            out = ""
        text = (out or "").strip()
    except Exception:
        return ""
    finally:
        if pid_cb:
            try:
                pid_cb(None)
            except Exception:
                pass
    # 优先取构建号（如 "build 11026" → "b11026"，与 Release tag 一致）
    m = re.search(r"\bbuild\s+(\d{3,7})\b", text)
    if m:
        return "b" + m.group(1)
    m = re.search(r"\bb(\d{3,7})\b", text)
    if m:
        return "b" + m.group(1)
    m = re.search(r"version\s*[:=]\s*(.+?)(?:\n|$)", text)
    if m:
        return m.group(1).strip()
    return ""


def list_releases(per_page=30, include_prerelease=True, page=1):
    """返回最近的 Release：[{tag, name, published_at, prerelease, assets:[{name,size,url}]}]

    page 从 1 开始，用于翻页（每页 per_page 条）。"""
    url = f"{GH_API}/releases"
    params = {"per_page": int(per_page)}
    try:
        p = int(page)
    except (TypeError, ValueError):
        p = 1
    if p > 1:
        params["page"] = p
    if not include_prerelease:
        params["exclude_assets"] = "true"  # 仅用于减少载荷；仍会返回元数据
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    except requests.exceptions.RequestException as e:
        raise UpdaterError(f"网络请求失败: {e}") from e
    if not (200 <= r.status_code < 300):
        raise UpdaterError(f"GitHub API 返回 HTTP {r.status_code}"
                           + ("（未认证时每小时限 60 次，请稍后再试）" if r.status_code == 403 else ""))
    out = []
    for rel in r.json() or []:
        assets = [{
            "name": a.get("name", ""),
            "size": int(a.get("size") or 0),
            "url": a.get("browser_download_url", ""),
        } for a in (rel.get("assets") or [])]
        out.append({
            "tag": rel.get("tag_name", ""),
            "name": rel.get("name", "") or rel.get("tag_name", ""),
            "published_at": (rel.get("published_at") or "")[:10],
            "prerelease": bool(rel.get("prerelease")),
            "assets": assets,
        })
    return out


def release_by_tag(tag):
    """按 tag 查询单个 Release（用于手动输入版本号）。"""
    try:
        r = requests.get(f"{GH_API}/releases/tags/{tag}", headers=HEADERS, timeout=30)
    except requests.exceptions.RequestException as e:
        raise UpdaterError(f"网络请求失败: {e}") from e
    if r.status_code == 404:
        raise UpdaterError(
            f"未找到 Release「{tag}」。\n注意：官方仅提供 Release（版本号）的预编译包，"
            "分支/源码没有可直接运行的 Windows 二进制。")
    if not (200 <= r.status_code < 300):
        raise UpdaterError(f"GitHub API 返回 HTTP {r.status_code}")
    rel = r.json()
    return [{
        "tag": rel.get("tag_name", ""),
        "name": rel.get("name", "") or rel.get("tag_name", ""),
        "published_at": (rel.get("published_at") or "")[:10],
        "prerelease": bool(rel.get("prerelease")),
        "assets": [{
            "name": a.get("name", ""),
            "size": int(a.get("size") or 0),
            "url": a.get("browser_download_url", ""),
        } for a in (rel.get("assets") or [])],
    }][0]


def list_branches(per_page=100):
    """返回仓库分支名列表（功能 10：分支源码下载）。main/master 置顶，其余按名称排序。"""
    url = f"{GH_API}/branches"
    try:
        r = requests.get(url, params={"per_page": int(per_page)}, headers=HEADERS, timeout=30)
    except requests.exceptions.RequestException as e:
        raise UpdaterError(f"网络请求失败: {e}") from e
    if not (200 <= r.status_code < 300):
        raise UpdaterError(f"GitHub API 返回 HTTP {r.status_code}"
                           + ("（未认证时每小时限 60 次，请稍后再试）" if r.status_code == 403 else ""))

    def _key(n):
        return (0 if n.lower() in ("main", "master") else 1, n.lower())

    names = [b.get("name", "") for b in (r.json() or []) if b.get("name")]
    names.sort(key=_key)
    return names


def branch_zip_url(branch):
    """分支源码 zip 的下载地址（GitHub API，302 跳转到 codeload）。"""
    safe = str(branch).strip().replace("\\", "/")
    # 逐段 URL 编码（保留 /）
    from urllib.parse import quote
    return f"{GH_API}/zipball/{quote(safe, safe='/')}"


def install_branch_source(zip_path, dest_dir):
    """把分支源码 zip「安全安装」到 dest_dir。

    - GitHub zipball 顶层只有一个目录（如 llama.cpp-main-abc123/），取其内容；
    - 只向 dest_dir 内部写入文件，绝不触碰其他路径；
    - 返回写入的文件数。
    """
    if not os.path.isdir(dest_dir):
        raise UpdaterError(f"目标目录不存在: {dest_dir}")
    tmpdir = tempfile.mkdtemp(prefix="llama_src_")
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmpdir)
        top = [e for e in os.listdir(tmpdir) if not e.startswith(".")]
        src_root = tmpdir
        if len(top) == 1 and os.path.isdir(os.path.join(tmpdir, top[0])):
            src_root = os.path.join(tmpdir, top[0])
        count = 0
        for root, _dirs, files in os.walk(src_root):
            for fn in files:
                s = os.path.join(root, fn)
                rel = os.path.relpath(s, src_root)
                d = os.path.join(dest_dir, rel)
                os.makedirs(os.path.dirname(d), exist_ok=True)
                shutil.copyfile(s, d)
                count += 1
        return count
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def win_assets(release):
    """从 Release 中挑出 Windows x64 预编译 zip。"""
    out = []
    for a in release.get("assets", []):
        n = a["name"]
        if re.search(r'^llama-.*-bin-win-.*\.zip$', n, re.IGNORECASE) and "arm" not in n.lower():
            out.append(a)
    # avx2 通用包优先靠前
    out.sort(key=lambda a: (0 if "avx2" in a["name"].lower() else 1, -a["size"]))
    return out


def list_zip_entries(zip_path):
    """列出 zip 内文件 [{name, size}]（仅根目录层，llama.cpp win 包为扁平结构）。"""
    with zipfile.ZipFile(zip_path) as z:
        return [{"name": i.filename, "size": i.file_size} for i in z.infolist() if not i.is_dir()]


def _wanted_files(entries, mode):
    """按模式挑选要安装的文件名。"""
    names = [e["name"] for e in entries]
    if mode == MODE_ALL:
        return set(names)
    # server 模式：llama-server.exe + 所有 DLL + LICENSE/说明文本
    want = set()
    for n in names:
        low = n.lower()
        if low.endswith(".dll") or low == "llama-server.exe" \
                or low.startswith("license") or low.endswith(".txt"):
            want.add(n)
    return want


def _progress(cb, done, total):
    if cb is None:
        return
    try:
        cb(done, total)
    except Exception:
        pass


def _is_custom_file(name):
    """启动器自定义文件（非 llama.cpp 官方产物），安装时永不删除。"""
    low = os.path.basename(str(name)).lower()
    return low.endswith("-impl.dll") or low.endswith("-impl.exe")


def _is_llama_artifact(name):
    """是否为 llama.cpp 官方二进制/DLL（用于清理旧版本；自定义/第三方文件返回 False）。"""
    if _is_custom_file(name):
        return False
    low = os.path.basename(str(name)).lower()
    if low.endswith(".exe"):
        return low.startswith("llama-") or low.startswith("ggml-")
    if low.endswith(".dll"):
        return (low.startswith(("llama", "ggml", "mtmd", "cublas", "cudart"))
                or low == "libomp.dll")
    return False


def install_from_zip(zip_path, target_dir, mode=MODE_SERVER, progress_cb=None):
    """把 zip 中的文件安装到 target_dir（先删旧、再装新，不做任何跳过）。

    - 先清理目标目录顶层的旧版本二进制：仅在安装「完整构建」（含 llama-server.exe /
      llama.dll）时，删除不在本次安装包内的 llama.cpp 官方产物；*-impl.dll 等自定义
      文件与第三方文件一律不删（调用方应先用 backup_launcher_dir 备份整个顶层）；
    - 对每个待安装文件：若同名旧文件存在则先删除，再无条件从 zip 复制新内容，
      绝不按大小/时间判断「相同」而跳过，保证装完一定是新版本；
    - 若某文件正被占用无法删除或写入（如运行中的 llama-server.exe），改写为
      <name>.new，记入 pending，交由 schedule_self_update 在进程退出后替换；
    - progress_cb(done, total)：每处理完一个文件回调一次（可为 None）；
    - 返回 (actions, skipped, pending)：
        actions=[(文件名, 'installed'|'replaced'|'removed'|'pending')],
        skipped=未选中的数量, pending=[被占用而写成 .new 的文件名]。
    """
    if not os.path.isdir(target_dir):
        raise UpdaterError(f"目标目录不存在: {target_dir}")
    entries = list_zip_entries(zip_path)
    want = _wanted_files(entries, mode)

    todo = [e for e in entries if e["name"] in want and os.path.basename(e["name"])]
    names_in_pkg = {os.path.basename(e["name"]) for e in todo}
    total = len(todo) + 1  # +1：清理旧文件阶段

    tmpdir = tempfile.mkdtemp(prefix="llama_upd_")
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmpdir)
        actions = []
        pending = []
        done = 0

        # 0) 清理上一轮遗留的 .new（本次会按需重新生成；旧的无用残留直接丢弃）
        for fn in os.listdir(target_dir):
            if fn.lower().endswith(".new"):
                try:
                    os.remove(os.path.join(target_dir, fn))
                except OSError:
                    pass

        # 1) 清理旧版本二进制——仅在安装「完整构建」时执行，且只删 llama.cpp 官方产物，
        #    绝不触碰 *-impl.dll 等自定义文件（9KB 存根依赖它，删了启动器就废了）。
        is_full_build = any(
            os.path.basename(e["name"]).lower() in ("llama-server.exe", "llama.dll")
            for e in todo)
        if is_full_build:
            for fn in os.listdir(target_dir):
                p = os.path.join(target_dir, fn)
                if not os.path.isfile(p):
                    continue
                if _is_llama_artifact(fn) and fn not in names_in_pkg:
                    try:
                        os.remove(p)
                        actions.append((fn, "removed"))
                    except OSError:
                        pass  # 被占用则保留，稍后复制阶段会走 .new 兜底
        done += 1
        _progress(progress_cb, done, total)

        # 2) 删除同名旧文件 → 无条件写入新内容
        for e in todo:
            name = os.path.basename(e["name"])  # win 包为扁平结构，取基名即可
            src = os.path.join(tmpdir, name)
            if not os.path.isfile(src):
                done += 1
                _progress(progress_cb, done, total)
                continue
            dst = os.path.join(target_dir, name)
            existed = os.path.isfile(dst)
            if existed:
                try:
                    os.remove(dst)
                except OSError:
                    pass  # 被占用：删除失败，复制阶段会走 .new 兜底
            try:
                shutil.copyfile(src, dst)
                actions.append((name, "replaced" if existed else "installed"))
            except OSError:
                alt = dst + ".new"
                shutil.copyfile(src, alt)
                pending.append(name)
                actions.append((name, "pending"))
            done += 1
            _progress(progress_cb, done, total)
        skipped = len(entries) - sum(1 for e in entries if e["name"] in want)
        return actions, skipped, pending
    finally:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


def backup_launcher_dir(dir_path, tag, progress_cb=None):
    """把 dir_path 顶层的常规文件打包备份到 <dir_path>\\bak\\<tag>.zip。

    - 只备份顶层文件（不递归子目录），跳过 bak 目录本身与 .new/.bak 临时产物；
    - 被占用无法读取的文件自动跳过，不阻塞流程；
    - progress_cb(done, total)：每写入一个条目回调一次（可为 None）；
    - 返回备份 zip 的路径（若无任何可备份文件则返回 None）。
    """
    if not os.path.isdir(dir_path):
        raise UpdaterError(f"目录不存在: {dir_path}")
    tag = re.sub(r'[\\/:*?"<>|\r\n]+', "_", str(tag).strip()) or "backup"
    bak_dir = os.path.join(dir_path, "bak")
    os.makedirs(bak_dir, exist_ok=True)
    dest_zip = os.path.join(bak_dir, f"{tag}.zip")

    files = []
    for fn in os.listdir(dir_path):
        full = os.path.join(dir_path, fn)
        if not os.path.isfile(full):
            continue
        low = fn.lower()
        if low.endswith(".new") or low.endswith(".bak"):
            continue
        files.append(fn)

    if not files:
        return None

    total = len(files)
    done = 0
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for fn in files:
            full = os.path.join(dir_path, fn)
            try:
                z.write(full, arcname=fn)
            except OSError:
                pass  # 被占用/只读文件跳过，不阻塞备份
            done += 1
            _progress(progress_cb, done, total)
    return dest_zip


def schedule_self_update(pending, target_dir, pid=None):
    """为 pending 中写成 .new 的文件安排「延迟替换」。

    生成一个独立 .bat：等待本进程（pid）退出后，把每个 <name>.new 覆盖回 <name>。
    以分离方式启动该 .bat，返回其路径；pending 为空时返回 None。
    """
    if not pending:
        return None
    bat_path = os.path.join(tempfile.gettempdir(), "llama_selfupdate.bat")
    lines = ["@echo off", "chcp 65001 >nul"]
    if pid:
        try:
            p = int(pid)
        except (TypeError, ValueError):
            p = 0
        if p > 0:
            lines.append(f":wait")
            lines.append(f"tasklist /fi \"PID eq {p}\" | find \"{p}\" >nul")
            lines.append("if not errorlevel 1 (ping -n 3 127.0.0.1 >nul & goto wait)")
    for name in pending:
        safe = str(name).replace('"', "")
        new_q = f'"{os.path.join(target_dir, safe + ".new")}"'
        dst_q = f'"{os.path.join(target_dir, safe)}"'
        lines.append(f"if exist {new_q} move /y {new_q} {dst_q}")
    with open(bat_path, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines) + "\r\n")
    try:
        import subprocess
        CREATE_NEW_GROUP = 0x00000200
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen(
            ["cmd", "/c", bat_path],
            creationflags=CREATE_NEW_GROUP | DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
        )
    except Exception:
        pass
    return bat_path
