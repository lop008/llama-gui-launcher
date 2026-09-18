import os
import shutil
import subprocess

CREATE_NO_WINDOW = 0x08000000

BUILTIN_TOOLS = [
    {"id": "opencode", "name": "OpenCode (终端)", "desc": "AI 编程 Agent，终端界面（自动连接本服务）",
     "category": "terminal", "cmds": ["opencode", "opencode.cmd", "opencode.exe"]},
    {"id": "opencode-desktop", "name": "OpenCode 桌面版", "desc": "OpenCode 桌面客户端",
     "category": "app", "cmds": ["OpenCode.exe"], "search_dirs": ["@opencode-aidesktop"]},
    {"id": "claude", "name": "Claude Code", "desc": "Anthropic 官方 CLI（未自动连接本服务）",
     "category": "terminal", "cmds": ["claude", "claude.exe", "claude.cmd"]},
    {"id": "llama-server", "name": "llama-server", "desc": "由本启动器管理的本地服务",
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
        r = subprocess.run(["npm", "prefix", "-g"], capture_output=True, text=True,
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
