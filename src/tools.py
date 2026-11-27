import os
import shutil
import subprocess
from .i18n import t

CREATE_NO_WINDOW = 0x08000000


def describe_executable(path):
    """读取 Windows PE 版本信息里的 FileDescription / ProductName。

    读不到时返回空字符串（.cmd/.bat、损坏文件、非 Windows 都走这里）。
    仅用于「自动更新描述」，不参与启动逻辑。
    """
    if not path or not os.path.isfile(path):
        return ""
    if not str(path).lower().endswith((".exe", ".dll")):
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        ver = ctypes.WinDLL("version")
        ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                            wintypes.DWORD, wintypes.LPVOID]
        ver.GetFileVersionInfoW.restype = wintypes.BOOL
        ver.VerQueryValueW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR,
                                       ctypes.POINTER(wintypes.LPVOID),
                                       ctypes.POINTER(wintypes.UINT)]
        ver.VerQueryValueW.restype = wintypes.BOOL
        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return ""
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(path, 0, size, buf):
            return ""
        ptr = wintypes.LPVOID()
        length = wintypes.UINT()
        translations = []
        if ver.VerQueryValueW(buf, r"\VarFileInfo\Translation", ctypes.byref(ptr),
                              ctypes.byref(length)) and length.value >= 4:
            raw = ctypes.string_at(ptr, length.value)
            for i in range(0, len(raw) - 3, 4):
                lang = int.from_bytes(raw[i:i + 2], "little")
                codepage = int.from_bytes(raw[i + 2:i + 4], "little")
                translations.append(f"{lang:04x}{codepage:04x}")
        for code in translations + ["040904b0", "040904e4", "080404b0", "000004b0"]:
            for key in ("FileDescription", "ProductName"):
                sub = f"\\StringFileInfo\\{code}\\{key}"
                if ver.VerQueryValueW(buf, sub, ctypes.byref(ptr), ctypes.byref(length)) \
                        and length.value:
                    val = ctypes.wstring_at(ptr, length.value).rstrip("\x00").strip()
                    if val:
                        return val
    except Exception:
        return ""
    return ""

BUILTIN_TOOLS = [
    {"id": "opencode", "name": t('OpenCode (终端)'), "desc": t('AI 编程 Agent，终端界面（自动连接本服务）'),
     "category": "terminal", "cmds": ["opencode", "opencode.cmd", "opencode.exe"]},
    {"id": "opencode-desktop", "name": t('OpenCode 桌面版'), "desc": t('OpenCode 桌面客户端'),
     "category": "app", "cmds": ["OpenCode.exe"], "search_dirs": ["@opencode-aidesktop"]},
    {"id": "claude", "name": "Claude Code", "desc": t('Anthropic 官方 CLI（未自动连接本服务）'),
     "category": "terminal", "cmds": ["claude", "claude.exe", "claude.cmd"]},
    {"id": "llama-server", "name": "llama-server", "desc": t('由本启动器管理的本地服务'),
     "category": "app", "cmds": ["llama-server.exe"]},
]

ALL = list(BUILTIN_TOOLS)


def _base_dirs():
    dirs = []
    lp = os.environ.get("LOCALAPPDATA")
    if lp:
        dirs.append(os.path.join(lp, "Programs"))
    pf = os.environ.get("ProgramFiles")
    if pf:
        dirs.append(pf)
    pfx = os.environ.get("ProgramFiles(x86)")
    if pfx:
        dirs.append(pfx)
    home = os.environ.get("USERPROFILE")
    if home:
        dirs.append(os.path.join(home, "scoop", "apps"))
    return [d for d in dirs if d and os.path.isdir(d)]


def _npm_bin_dir():
    appdata = os.environ.get("APPDATA")
    if appdata:
        cand = os.path.join(appdata, "npm")
        if os.path.isdir(cand):
            return cand
    try:
        # 显式指定编码：中文系统上 npm 不存在时，cmd 会把 GBK 错误信息写进管道，
        # text=True 用本地编码解码失败会在 subprocess 的内部读线程里抛 UnicodeDecodeError
        # （界面看不出问题，但 npm 全局目录就一直探测不到）。
        r = subprocess.run(["npm", "prefix", "-g"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=10, creationflags=CREATE_NO_WINDOW)
        p = r.stdout.strip()
        if p and os.path.isdir(p):
            return p
    except Exception:
        pass
    return None


def find_executable(cmd, search_dirs=None):
    found = shutil.which(cmd)
    if found:
        return found

    if cmd.lower().endswith((".cmd", ".ps1", ".exe")):
        npm = _npm_bin_dir()
        if npm:
            cand = os.path.join(npm, cmd)
            if os.path.isfile(cand):
                return cand

    if cmd.lower().endswith(".exe") and search_dirs:
        for base in _base_dirs():
            for sub in search_dirs:
                cand = os.path.join(base, sub, cmd)
                if os.path.isfile(cand):
                    return cand

    if cmd.lower().endswith(".exe"):
        for base in _base_dirs():
            cand = os.path.join(base, cmd)
            if os.path.isfile(cand):
                return cand
    return None


def find(tool, llama_dir=None, launcher_exe=None):
    if tool["id"] == "llama-server":
        if launcher_exe and os.path.isfile(launcher_exe):
            return launcher_exe
        if llama_dir:
            cand = os.path.join(llama_dir, "llama-server.exe")
            if os.path.isfile(cand):
                return cand
    for c in tool["cmds"]:
        p = find_executable(c, tool.get("search_dirs"))
        if p:
            return p
    return None


def scan_all(overrides, llama_dir=None, launcher_exe=None):
    result = {}
    for t in ALL:
        override = (overrides or {}).get(t["id"])
        if override and override.get("path"):
            result[t["id"]] = override["path"]
        else:
            result[t["id"]] = find(t, llama_dir, launcher_exe)
    return result


def open_terminal(command, workdir=None, env=None):
    workdir = workdir or os.getcwd()
    env_use = {**os.environ, **(env or {})}
    wt = shutil.which("wt")
    try:
        if wt:
            subprocess.Popen([wt, "-d", workdir, "cmd", "/k", command],
                             env=env_use, creationflags=CREATE_NO_WINDOW)
            return True
    except Exception:
        pass
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "AgentTool", "/D", workdir, "cmd", "/k", command],
            env=env_use, creationflags=CREATE_NO_WINDOW)
        return True
    except Exception:
        return False


def launch(path, tool, args="", workdir=None, env=None):
    if tool.get("category") == "app":
        cmd = [path]
        if args:
            cmd += args.split()
        try:
            subprocess.Popen(cmd, cwd=workdir or os.getcwd(),
                             env={**os.environ, **(env or {})},
                             creationflags=CREATE_NO_WINDOW)
            return True
        except Exception:
            return False
    command = f'"{path}"'
    if args:
        command += " " + args
    return open_terminal(command, workdir, env)
