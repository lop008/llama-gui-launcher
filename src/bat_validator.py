"""启动文件校验器（任务 C2）：静态校验 .bat/.cmd/.ps1/.sh/文本脚本能否正常拉起 llama-server。

包含两部分：
- 纯函数 normalize_script / parse_script / validate_script / overall_conclusion（便于测试，不依赖 Qt 运行环境）；
- ValidateBatDialog(QDialog)：文件选择 + 双列表格报告 + 重新校验 / 保存配置。

规范化能力（bat/cmd）：
- `set VAR=value` 变量收集与 `%VAR%` 引用替换（含 %% 转义、环境变量回退、%~dp0 = 脚本目录）；
- 行尾 `^` 续行合并为一条完整命令行再解析（支持空格分行书写）；
- REM / :: 注释行跳过，避免把注释里的 `-n cap` 之类误识别成参数；
- 查找可执行文件时跳过 set/echo/cd/chcp 等批处理内建语句行。
"""
import os
import re
import shutil
import socket

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

# ---------------------------------------------------------------- 参数识别表
# flag（小写）→ 参数名。覆盖 bat/cmd/ps1/sh 常见写法与 llama.cpp 长短选项。
_PARAM_FLAGS = {
    "-m": "model", "--model": "model",
    "-c": "ctx", "--ctx-size": "ctx",
    "--port": "port",
    "--host": "host",
    "-ngl": "ngl", "--n-gpu-layers": "ngl", "--gpu-layers": "ngl",
    "-b": "batch", "--batch-size": "batch",
    "-ub": "ubatch",
    "-t": "threads", "--threads": "threads",
    "-n": "predict", "--predict": "predict", "--n-predict": "predict",
    "--api-key": "api_key",
    "--spec-type": "spec_type",
    "--tensor-split": "tensor_split", "-ts": "tensor_split",
    "--mmproj": "mmproj",
    "-fa": "flash_attn", "--flash-attn": "flash_attn",
    "-dev": "device",
    "-ctk": "kv_k", "-ctv": "kv_v",
    "--temp": "temp",
    "--top-k": "top_k",
    "--top-p": "top_p",
    "--repeat-penalty": "repeat_penalty",
    "--timeout": "timeout",
    "-a": "alias",
    "-np": "slots", "--parallel": "slots",
    "-sm": "split_mode", "--split-mode": "split_mode",
    "-mg": "main_gpu", "--main-gpu": "main_gpu",
    "-rea": "reasoning_format", "--reasoning-format": "reasoning_format",
}

# 布尔开关（不带值）：识别后不吞掉下一个 token。
_FLAG_FLAGS = {
    "--cont-batching": "cont_batching",
    "-cmoe": "cmoe",
    "--context-shift": "context_shift",
    "--mlock": "mlock",
    "--no-mmap": "no_mmap",
}

_PARAM_LABELS = {
    "model": "模型", "ctx": "上下文长度", "port": "端口", "host": "监听地址",
    "ngl": "GPU层数", "batch": "批大小", "ubatch": "微批(-ub)", "threads": "线程",
    "predict": "预测Token", "api_key": "API Key", "spec_type": "MTP(--spec-type)",
    "tensor_split": "tensor-split", "mmproj": "视觉模型", "flash_attn": "闪存注意力",
    "device": "设备(-dev)", "kv_k": "KV缓存K(-ctk)", "kv_v": "KV缓存V(-ctv)",
    "temp": "温度", "top_k": "Top-K", "top_p": "Top-P",
    "repeat_penalty": "重复惩罚", "timeout": "超时(秒)", "alias": "模型别名(-a)",
    "slots": "并行slots(-np)", "split_mode": "拆分模式(-sm)", "main_gpu": "主GPU(-mg)",
    "reasoning_format": "推理格式",
    "cont_batching": "连续批处理", "cmoe": "MoE加速(-cmoe)",
    "context_shift": "上下文移位", "mlock": "锁定内存(--mlock)",
    "no_mmap": "禁用mmap(--no-mmap)",
}

_EXE_RE = re.compile(r"llama-(server|cli)\.exe$", re.IGNORECASE)

# 查找可执行文件时跳过的批处理内建语句（首 token，小写）
_BAT_BUILTINS = {
    "set", "echo", "cd", "chcp", "rem", "pause", "cls", "title",
    "if", "for", "goto", "shift", "exit", "setlocal", "endlocal",
}

# 「所有单元格随时可编辑」：旧版 PyQt6 有 AllCells 常量；Qt 6.11+ 移除了它，
# 改用全部触发标志按位或（CurrentChanged|DoubleClicked|SelectedClicked|EditKeyPressed|AnyKeyPressed）。
try:
    _ALL_CELLS_EDIT = QAbstractItemView.EditTrigger.AllCells
except AttributeError:
    _ALL_CELLS_EDIT = (QAbstractItemView.EditTrigger.CurrentChanged |
                       QAbstractItemView.EditTrigger.DoubleClicked |
                       QAbstractItemView.EditTrigger.SelectedClicked |
                       QAbstractItemView.EditTrigger.EditKeyPressed |
                       QAbstractItemView.EditTrigger.AnyKeyPressed)


def _unquote(tok):
    t = tok.strip()
    if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
        return t[1:-1]
    return t


def _tokenize(line):
    """按空白切分 token；引号内的子串（含空格路径）保持为一个 token，保留原引号。"""
    toks, cur, in_q = [], "", False
    for ch in line:
        if ch == '"':
            in_q = not in_q
            cur += ch
        elif ch.isspace() and not in_q:
            if cur:
                toks.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        toks.append(cur)
    return toks


def _mask_api_key(v):
    """API Key 打码：只显示前 4 位。"""
    v = str(v)
    if len(v) <= 4:
        return "*" * max(len(v), 1)
    return v[:4] + "****"


# ---------------------------------------------------------------- bat 规范化
_SET_RE = re.compile(r"^set\s+(?P<rest>\S.*)$", re.IGNORECASE | re.DOTALL)
_VAR_REF_RE = re.compile(r"%([A-Za-z_~][A-Za-z0-9_]*)%")


def _collect_set(line, vars_map):
    """从 `set VAR=value` / `set "VAR=value"` 收集变量（忽略 set /a、/p 等带开关形式）。"""
    m = _SET_RE.match(line.strip())
    if not m:
        return
    rest = m.group("rest").strip()
    if rest.startswith("/"):          # set /a X=1+2、set /p VAR=... 等，跳过
        return
    body = rest
    if rest.startswith('"'):
        endq = rest.find('"', 1)
        if endq < 0:
            return
        body = rest[1:endq]
    m2 = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", body, re.DOTALL)
    if not m2:
        return
    vars_map[m2.group(1).upper()] = m2.group(2).strip()


def _substitute(text, vars_map, script_dir):
    """替换 %VAR%：脚本变量 → 环境变量（Windows 不区分大小写）→ %~dp0=脚本目录；%% 还原为字面 %。"""
    text = text.replace("%%", "\x00")

    def repl(m):
        name = m.group(1)
        if name.startswith("~"):
            base = name[1:]
            if base.lower().startswith("dp") and base[2:].strip() in ("", "0"):
                return script_dir or ""
            return m.group(0)
        up = name.upper()
        if up in vars_map:
            return vars_map[up]
        for k, v in os.environ.items():
            if k.upper() == up:
                return v
        return m.group(0)   # 未知变量原样保留

    text = _VAR_REF_RE.sub(repl, text)
    return text.replace("\x00", "%")


def normalize_script(text, path=""):
    """把脚本文本规范化为 (vars_map, phys_info)。

    - vars_map：脚本内 `set` 定义的变量（大写键 → 值，已做迭代解析）；
    - phys_info：与原始物理行一一对应的列表，每项为
      ("head", 合并续行并替换变量后的完整命令行) / ("cont", None) / ("comment", None)。
    """
    lines = [ln.rstrip("\r") for ln in (text or "").splitlines()]

    # 1) 注释行（REM / ::）
    is_comment = []
    for ln in lines:
        s = ln.strip()
        low = s.lower()
        is_comment.append(s.startswith("::") or re.match(r"^rem\b", low) is not None)

    # 2) set 变量收集（在续行合并前，按原始行）
    vars_map = {}
    for i, ln in enumerate(lines):
        if not is_comment[i]:
            _collect_set(ln, vars_map)
    # 迭代解析：值里可能引用其它已定义变量（set A=%B%x），最多 5 轮
    script_dir = os.path.dirname(path) + "\\" if path else ""
    for _ in range(5):
        changed = False
        for k, v in list(vars_map.items()):
            nv = _substitute(v, vars_map, script_dir)
            if nv != v:
                vars_map[k] = nv
                changed = True
        if not changed:
            break

    # 3) 续行合并（行尾奇数个 ^ → 与下一行拼接；偶数个为字面量不合并）+ 变量替换
    phys_info = []
    i, n = 0, len(lines)
    while i < n:
        if is_comment[i]:
            phys_info.append(("comment", None))
            i += 1
            continue
        parts = []
        head_i = i
        cur = lines[i]
        while True:
            c = cur.rstrip()
            carets = len(c) - len(c.rstrip("^"))
            if carets % 2 == 1 and c.endswith("^"):
                parts.append(c[:-1])          # 去掉续行符，接下一物理行
                i += 1
                if i >= n:
                    break
                cur = lines[i]
                continue
            parts.append(c)
            i += 1
            break
        eff = " ".join(p.strip() for p in parts if p.strip())
        # head 行记录合并后的完整命令；被并入的后续物理行标记为 cont（保持一一对应）
        phys_info.append(("head", _substitute(eff, vars_map, script_dir)))
        while len(phys_info) < i:
            phys_info.append(("cont", None))
    return vars_map, phys_info


def _parse_line(line):
    """解析单行中的所有 llama 参数 → [(原始片段, 参数名, 值), ...]。

    支持 -m xxx / --port=8080 / 引号路径；布尔开关（--cont-batching 等）不吞下一个 token。
    （%VAR% 应在调用前由 normalize_script 替换完毕。）
    """
    toks = _tokenize(line)
    out = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        low = tok.lower()
        name, value, frag = None, "", tok

        if low in _FLAG_FLAGS:
            # 布尔开关：只记录标志本身，不消费后续 token
            out.append((tok, _FLAG_FLAGS[low], ""))
            i += 1
            continue

        if "=" in tok and not tok.startswith('"'):
            head, _, tail = low.partition("=")
            if head in _PARAM_FLAGS:
                name = _PARAM_FLAGS[head]
                value = tail.strip().strip('"')
        elif low in _PARAM_FLAGS:
            name = _PARAM_FLAGS[low]
            if i + 1 < len(toks):
                value = _unquote(toks[i + 1])
                frag = f"{tok} {value}"
                i += 2
                if name == "api_key" and value:
                    value = _mask_api_key(value)
                out.append((frag, name, value))
                continue
        if name is not None:
            if name == "api_key" and value:
                value = _mask_api_key(value)
            out.append((frag, name, value))
        i += 1
    return out


def parse_script(text, path=""):
    """从脚本文本提取 llama-server/llama-cli 相关参数。

    先做 bat 规范化（set 变量替换 / ^ 续行合并 / REM 注释跳过），再逐条命令解析。
    返回 [(原始片段, 参数名, 值), ...]，按出现顺序：
    - 含参数的命令行 → 每个参数一条；
    - 未识别的命令行 → (整行, "", "")，原样保留。
    """
    _vars, phys_info = normalize_script(text, path)
    out = []
    for kind, eff in phys_info:
        if kind != "head" or not eff.strip():
            continue
        found = _parse_line(eff)
        if found:
            out.extend(found)
        else:
            out.append((eff, "", ""))
    return out


def _decode_bytes(data):
    """UTF-8(含 BOM) → GBK 依次尝试解码。返回 (text, 编码名)；失败返回 (None, None)。"""
    for enc in ("utf-8-sig", "gbk"):
        try:
            return data.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return None, None


def _resolve(base_path, p):
    """相对路径按脚本所在目录解析；%VAR% 先展开环境变量。"""
    p = os.path.expandvars(str(p))
    if os.path.isabs(p) or not base_path:
        return p
    return os.path.normpath(os.path.join(os.path.dirname(base_path), p))


def _find_exe(eff_lines):
    """在规范化后的命令行中找第一个可执行文件 token（llama-server.exe 等）。

    跳过 set/echo/cd/chcp 等内建语句行，避免把 `set EXE=llama-server.exe` 误当成主命令。
    返回 (exe_token, 所在完整命令行)；找不到返回 (None, "")。
    """
    for s in eff_lines:
        if not s.strip():
            continue
        toks = _tokenize(s)
        if toks and toks[0].lower().strip('"') in _BAT_BUILTINS:
            continue
        for tok in toks:
            t = _unquote(tok)
            tl = t.lower()
            if tl.endswith(".exe") or _EXE_RE.search(tl):
                return t, s
    return None, ""


def validate_script(text, path=""):
    """静态校验脚本，返回 [(项目名, 状态 ok/warn/fail, 说明), ...]。

    text 可为 str（跳过解码检查）或 bytes（执行 UTF-8→GBK 解码检查；
    失败视为二进制文件，报告后终止后续解析）。
    bat/cmd 会先做规范化：set 变量替换、^ 续行合并、REM/:: 注释跳过。
    """
    items = []

    # a. 文件存在且可读
    if path:
        if os.path.isfile(path) and os.access(path, os.R_OK):
            items.append(("文件存在且可读", "ok", f"文件存在且可读：{path}"))
        else:
            items.append(("文件存在且可读", "fail", f"文件不存在或不可读：{path}"))
    else:
        items.append(("文件存在且可读", "warn", "未提供文件路径，跳过存在性检查"))

    # b. 文本可解码（bytes 输入时执行；二进制则终止后续解析）
    if isinstance(text, (bytes, bytearray)):
        data = bytes(text)
        decoded, enc = _decode_bytes(data)
        if decoded is None:
            items.append(("文本可解码", "fail", "二进制文件，仅校验存在性与大小"))
            return items
        text = decoded
    else:
        enc = "str"
    items.append(("文本可解码", "ok", f"文本可解码（{enc}）"))

    # 规范化：变量替换 + 续行合并 + 注释跳过
    _vars, phys_info = normalize_script(text, path)
    eff_lines = [eff for kind, eff in phys_info if kind == "head"]

    # c. 脚本引用的可执行文件是否存在
    exe, exe_line = _find_exe(eff_lines)
    if not exe:
        items.append(("可执行文件", "warn", "未找到 llama-server/llama-cli 可执行命令行"))
    else:
        if os.path.isabs(exe):
            exists = os.path.isfile(exe)
        else:
            cand = _resolve(path, exe)
            exists = os.path.isfile(cand) or shutil.which(exe) is not None
        if exists:
            items.append(("可执行文件", "ok", f"可执行文件存在：{exe}"))
        else:
            items.append(("可执行文件", "fail",
                           f"可执行文件不存在：{exe}（请检查路径或先安装 llama.cpp）"))

    # 参数提取（c/d/e 共用）
    params = {}
    for _frag, name, value in parse_script(text, path):
        if name and name not in params:
            params[name] = value

    # d. -m 模型文件是否存在
    model = params.get("model", "")
    if not model:
        items.append(("数据模型", "warn", "脚本未指定 -m/--model 模型参数"))
    else:
        mp = _resolve(path, model)
        exists = os.path.isfile(mp)
        yes_no = "是" if exists else "否"
        items.append(("数据模型", "ok" if exists else "fail",
                      f"数据模型是否已就位（能否加载）：{yes_no}（{mp}）"))

    # d2. --mmproj 视觉模型文件是否存在
    mm = params.get("mmproj", "")
    if mm:
        mp = _resolve(path, mm)
        exists = os.path.isfile(mp)
        items.append(("视觉模型", "ok" if exists else "fail",
                      f"视觉模型是否已就位：{'是' if exists else '否'}（{mp}）"))

    # e. --port 合法性 + socket 绑定测试当前是否空闲
    port = params.get("port", "")
    if not port:
        items.append(("端口", "ok", "脚本未指定 --port（llama-server 默认使用 8080）"))
    elif not str(port).isdigit():
        items.append(("端口", "fail", f"--port 值不是合法数字：{port}"))
    else:
        p = int(port)
        free = True
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", p))
        except OSError:
            free = False
        finally:
            s.close()
        if free:
            items.append(("端口", "ok", f"端口 {p}（当前空闲）"))
        else:
            items.append(("端口", "warn",
                          f"端口 {p} 当前被占用，启动时会失败（可先释放该端口或改用其他端口）"))

    # f. bat 基本语法检查（存在主命令行即可，不做强校验）
    if exe_line:
        head = exe_line if len(exe_line) <= 60 else exe_line[:57] + "..."
        items.append(("脚本语法", "ok", f"存在主命令行：{head}"))
    else:
        items.append(("脚本语法", "fail", "未找到可执行的主命令行"))

    return items


def overall_conclusion(items):
    """整体结论：全部 ok → ✔；有 warn → ⚠ 可运行但有问题；有 fail → ✘。"""
    st = [s for _n, s, _d in items]
    if "fail" in st:
        return "✘ 无法正常运行"
    if "warn" in st:
        return "⚠ 可运行但有问题"
    return "✔ 可以正常运行"


# ---------------------------------------------------------------- 报告对话框
_STATUS_ICON = {"ok": "✔", "warn": "⚠", "fail": "✘"}


class ValidateBatDialog(QDialog):
    """启动文件校验报告：左列源文件（可编辑），右列解析说明（只读）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("启动文件校验报告")
        self.setMinimumWidth(720)
        self.resize(860, 560)
        self._path = ""
        self._encoding = "gbk"     # 原始解码所用编码；保存时优先沿用
        self._raw_bytes = b""

        lay = QVBoxLayout(self)

        self.label_summary = QLabel()
        self.label_summary.setWordWrap(True)
        lay.addWidget(self.label_summary)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["源文件", "说明"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(_ALL_CELLS_EDIT)   # 所有单元格随时可编辑（兼容 Qt 6.11+）
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.btn_revalidate = QPushButton("重新校验")
        self.btn_revalidate.setToolTip(
            "读取左列当前编辑后的文本，重新解析并刷新右列说明与整体结论。\n"
            "支持 bat 变量（set VAR=… / %VAR%）、^ 续行合并、REM/:: 注释跳过。")
        self.btn_revalidate.clicked.connect(self._revalidate)
        self.btn_save_cfg = QPushButton("保存配置")
        self.btn_save_cfg.setToolTip("把左列各行按原顺序写回源文件（bat 在中文 Windows 下建议 GBK 编码写出）")
        self.btn_save_cfg.clicked.connect(self._save_back)
        row.addWidget(self.btn_revalidate)
        row.addWidget(self.btn_save_cfg)
        row.addStretch(1)
        self.label_status = QLabel("")
        self.label_status.setStyleSheet("color: #8fd0ff;")
        row.addWidget(self.label_status, 1)
        lay.addLayout(row)

        self._pick_file()

    # ---------------------------------------------------------- 文件选择/刷新
    def _pick_file(self):
        start = os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "选择启动文件", start,
            "文本脚本 (*.bat *.cmd *.ps1 *.sh *.txt);;所有文件 (*.*)")
        if not path:
            self.close()
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            QMessageBox.critical(self, "错误", f"读取文件失败：{e}")
            self.close()
            return
        self._path = path
        self._raw_bytes = data
        self._refresh(data)

    def _refresh(self, data):
        """按 bytes 重新校验并刷新表格/结论。"""
        items = validate_script(data, self._path)   # bytes → 含解码检查
        concl = overall_conclusion(items)
        checks = {name: (st, desc) for name, st, desc in items}

        lines_ = [concl]
        for name, st, desc in items:
            lines_.append(f"{_STATUS_ICON.get(st, '?')} {name}：{desc}")
        self.label_summary.setText("\n".join(lines_))

        text, enc = _decode_bytes(data) if isinstance(data, (bytes, bytearray)) else (data, "utf-8")
        if text is None:
            # 二进制文件：仅展示存在性与大小，禁用保存
            self.table.setRowCount(1)
            it_l = QTableWidgetItem("<二进制文件>")
            it_r = QTableWidgetItem("二进制文件，仅校验存在性与大小")
            it_r.setFlags(it_r.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(0, 0, it_l)
            self.table.setItem(0, 1, it_r)
            self.btn_save_cfg.setEnabled(False)
            return
        self._encoding = enc or "gbk"
        self.btn_save_cfg.setEnabled(True)

        # 左列 = 原始物理行（可编辑、可原样保存）；右列按规范化结果逐行说明
        raw_lines = text.splitlines()
        _vars, phys_info = normalize_script(text, self._path)
        rows = []
        for idx, raw in enumerate(raw_lines):
            kind, eff = (phys_info[idx] if idx < len(phys_info) else ("head", None))
            left = raw.rstrip("\r")
            if kind == "comment":
                right = "注释行（REM/::，校验时忽略）"
            elif kind == "cont":
                right = "续行（^ 与上一行合并为一条命令解析）"
            else:
                found = _parse_line(eff or "")
                descs = [self._describe_param(name, value, checks) for _f, name, value in found]
                right = "；".join(descs) if descs else ("未识别/普通语句" if left.strip() else "")
            rows.append((left, right))

        self.table.setRowCount(len(rows))
        for r, (left, right) in enumerate(rows):
            it_l = QTableWidgetItem(left)
            it_r = QTableWidgetItem(right)
            it_r.setFlags(it_r.flags() & ~Qt.ItemFlag.ItemIsEditable)  # 右列只读
            self.table.setItem(r, 0, it_l)
            self.table.setItem(r, 1, it_r)

    def _describe_param(self, name, value, checks):
        """单个参数在右列的说明文本（模型/视觉模型/端口附带校验状态）。"""
        label = _PARAM_LABELS.get(name, name or "未识别")
        if name == "model":
            st = (checks.get("数据模型") or ("", ""))[0]
            base = os.path.basename(value) or value
            return f"{label}: {base} —— 文件存在 {'✔' if st == 'ok' else '✘'}"
        if name == "mmproj":
            st = (checks.get("视觉模型") or ("", ""))[0]
            base = os.path.basename(value) or value
            return f"{label}: {base} —— 文件存在 {'✔' if st == 'ok' else '✘'}"
        if name == "port":
            desc = (checks.get("端口") or ("", ""))[1]
            free = "空闲" in desc and "被占用" not in desc
            return f"{label}: {value}（{'当前空闲' if free else '被占用/未检查'}）"
        if value == "":
            return f"{label}: 已开启"
        return f"{label}: {value}"

    # ---------------------------------------------------------- 重新校验 / 保存
    def _revalidate(self):
        """读取左列当前编辑后的文本，重新 parse + validate。"""
        lines = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            lines.append(it.text() if it else "")
        new_text = "\n".join(lines)
        try:
            data = new_text.encode(self._encoding or "gbk")
        except (UnicodeEncodeError, LookupError):
            data = new_text.encode("utf-8-sig")   # 含 BOM，保证可解码检查通过
        self._raw_bytes = data
        self._refresh(data)
        self.label_status.setText("已重新校验")

    def _save_back(self):
        """把左列各行按原顺序写回源文件（先确认；优先沿用原编码，bat 建议 GBK）。"""
        if not self._path:
            return
        ret = QMessageBox.question(
            self, "确认写回源文件",
            f"将左列当前内容按原顺序写回：\n{self._path}\n\n"
            "（bat 在中文 Windows 下建议 GBK 编码写出，避免乱码）\n确定继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return
        lines = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            lines.append(it.text() if it else "")
        text = "\r\n".join(lines)   # bat 习惯 CRLF
        enc = self._encoding or "gbk"
        try:
            data = text.encode(enc)
        except (UnicodeEncodeError, LookupError):
            enc = "utf-8-sig"       # 原编码写不下时退回 UTF-8 with BOM
            data = text.encode("utf-8-sig")
        try:
            with open(self._path, "wb") as f:
                f.write(data)
        except OSError as e:
            QMessageBox.critical(self, "错误", f"写回失败：{e}")
            return
        self.label_status.setText(f"已保存（{enc}）：{self._path}")
