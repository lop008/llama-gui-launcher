# -*- coding: utf-8 -*-
"""「命令预览」的逐条拆解：把最终命令行翻译成「这个参数是干什么的」。

只读不写：命令行始终由 cmd_builder 唯一决定，本模块按 token 解析它的产物，
所以「界面上的解释」和「真正下发的参数」永远是同一套口径，不会各说各话。

用法：
    from .cmd_explainer import explain_command
    for flag, value, meaning in explain_command(cmd_text):
        ...
"""
import re

from .i18n import t

# 需要跟一个取值的参数（布尔开关不在这里）。判断「这个参数带不带值」靠它，
# 而不是「下一个 token 是不是以 - 开头」—— 后者会被 -2.0 这类负数取值骗到。
VALUE_FLAGS = {
    "-m", "--model", "--mmproj", "-ngl", "-c", "-np", "-fa", "-b", "-ub",
    "-ctk", "-ctv", "-sm", "-ts", "-dev", "-a", "-n", "--temp", "--top-k",
    "--top-p", "--repeat-penalty", "--host", "--port", "--api-key", "--timeout",
    "--reasoning", "--reasoning-budget", "--chat-template-kwargs", "--spec-type",
    "--spec-draft-model", "--spec-draft-n-max", "--n-cpu-moe", "--moe-cache-mib",
    "--ssl-key-file", "--ssl-cert-file",
}

# 长写法 → 表内 key，避免同一条说明写两遍
ALIAS = {"--model": "-m"}

# 参数作用说明。key 用中文原文（界面语言由 t() 在取用时才翻译，切语言立即生效）。
DESC = {
    "-m": "主模型：本次服务加载的 GGUF 权重，决定回答质量，也决定要占多少显存/内存。",
    "--mmproj": "视觉投影文件：把图片编码成模型能读的向量，带上它模型才看得懂图。",
    "-ngl": "卸载到 GPU 的层数。数值越大越快，也越吃显存。",
    "-c": "上下文窗口长度（token）：一次能装下多长的对话与检索内容，越大 KV 缓存越占显存。",
    "-np": "最大并行请求数：多少个客户端可以同时对话，每一路都要占一份 KV 缓存。",
    "-fa": "Flash Attention：长上下文时更快、更省显存，新硬件建议开启。",
    "-b": "批大小：处理 prompt 时一次喂给模型的 token 数，越大读长文越快。",
    "-ub": "单批 token 上限：与 -b 配合，在吞吐和显存之间找平衡。",
    "-ctk": "K 缓存量化格式：KV 缓存的一半，用一点精度换大量显存，长上下文时收益最明显。",
    "-ctv": "V 缓存量化格式：KV 缓存的另一半，作用与 -ctk 相同。",
    "-sm": "多显卡切分方式：按层切（layer）/ 按行切（row）/ 不切（none）。",
    "-ts": "各显卡承担的权重比例：两张卡显存不一样大时用它调整分配。",
    "-dev": "指定推理设备：哪些层走 GPU、哪些走 CPU，或多张卡分别用什么。",
    "-a": "模型别名：客户端请求里 model 字段就填这个名字，不用写一长串文件路径。",
    "-n": "单次回复最多生成多少 token，超了就停。",
    "--temp": "温度：越低回答越确定保守，越高越发散有创意。",
    "--top-k": "每步只从概率最高的 K 个词里挑，压住低概率的胡言乱语。",
    "--top-p": "核采样：累计概率达到 p 的词才有机会被选中，兼顾多样性与稳定。",
    "--repeat-penalty": "重复惩罚：太低容易复读，太高分寸失当、话说一半。",
    "--host": "监听地址：127.0.0.1 只允许本机访问，0.0.0.0 让局域网其他设备也能连。",
    "--port": "监听端口：API 地址就是 http://<本机地址>:<端口>/v1。",
    "--api-key": "访问令牌：客户端必须带上 Authorization 才允许调用。",
    "--timeout": "单个请求的超时秒数，超时就断开，避免长尾请求卡住服务。",
    "--metrics": "开放 /metrics 指标端点，启动器的实时 tok/s、请求数等监控靠它取数。",
    "--jinja": "使用模型内置的 Jinja 对话模板：新模型基本必须开启，否则思考标签、工具调用会错乱。",
    "--reasoning": "思考开关：on 强制先思考，off 直接回答，auto 由模型自己判断。",
    "--reasoning-budget": "思考预算：限制思考阶段最多花掉多少 token，防止它想太久。",
    "--chat-template-kwargs": "传给对话模板的额外变量，例如 {\"reasoning_effort\":\"medium\"} 用来控制思考深度。",
    "--spec-type": "投机解码方式：先让小草稿猜一串 token，再由主模型一次性验证，提速但不降低质量。",
    "--spec-draft-model": "草稿模型：负责猜 token 的小权重，必须与主模型同词表、同架构族。",
    "--spec-draft-n-max": "一次最多猜多少个 token：猜得多收益高，猜错时回退也更多。",
    "--cpu-moe": "把所有 MoE 专家放进 CPU 内存：显存装不下专家时的整包方案，代价是速度下降。",
    "--n-cpu-moe": "把前 N 层的 MoE 专家放到 CPU：细粒度腾出显存，MoE 模型最常用的开关。",
    "--moe-cache-mib": "给留在 CPU 的专家预留一块 GPU 缓存（MiB），缓解 --n-cpu-moe 带来的掉速。",
    "--mlock": "把模型锁在内存中，禁止被系统换出到磁盘：更稳定，但内存占用实打实。",
    "--no-mmap": "关闭内存映射加载：读盘更慢，但内存占用更可控，个别环境能改善稳定性。",
    "--cont-batching": "连续批处理：长短请求交替执行，并行时不再互相干等。",
    "--ssl-key-file": "HTTPS 私钥文件，与证书配合对外提供 https:// 访问。",
    "--ssl-cert-file": "HTTPS 证书文件（自签名），客户端需要信任它或跳过校验。",
}

# 少数参数值得把「当前取值」也讲清楚，否则用户看不出这个数字意味着什么
VALUE_HINT = {
    "-ngl": "当前：最多 {0} 层进显存（大于等于模型总层数就等于全部层都在 GPU 上）。",
    "-c": "当前：{0} token 的上下文，约占 KV 显存随模型大小一起增长。",
    "-np": "当前：最多 {0} 路并行。",
    "--port": "当前端口 {0}，浏览器与 Agent 工具都连这个口。",
    "--n-cpu-moe": "当前：前 {0} 层的专家放 CPU（数值越大越省显存、也越慢）。",
    "--moe-cache-mib": "当前：为 CPU 专家缓存 {0} MiB。",
    "--spec-draft-n-max": "当前：每轮最多猜 {0} 个 token。",
}

UNKNOWN = "未收录的参数：原样交给 llama-server 处理。"
EXE_LINE = "启动的程序本体（llama-server 或它的包装脚本），后面的参数都是给它看的。"

# "..."（内部可含 \" 转义）或 非空白串；POSIX 反斜杠规则不适用 Windows 命令行
_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|[^\s]+')


def _unquote(tok):
    """去掉 Windows 命令行的外层引号，并还原内部转义引号。"""
    if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
        return tok[1:-1].replace('\\"', '"')
    return tok


def split_command(cmd_text):
    """按 Windows 命令行规则切 token（保留值内部的空格与转义引号）。"""
    return [m.group(0) for m in _TOKEN.finditer(cmd_text or "")]


def _is_value(tok):
    """下一个 token 是取值还是新参数：负数（-0.5）也是值，不是参数。"""
    if not tok.startswith("-"):
        return True
    try:
        float(tok)
        return True
    except ValueError:
        return False


def explain_command(cmd_text):
    """把一行命令拆成 [(参数, 取值, 中文说明)]，顺序与命令行一致。

    - 第 0 个 token 是可执行文件，说明固定为 EXE_LINE；
    - 参数不在表里时说明写 UNKNOWN，绝不猜一个听起来像的解释糊弄用户。
    """
    toks = split_command(cmd_text)
    total = len(toks)
    rows = []
    i = 0
    while i < total:                     # 必须用下标循环：吃掉取值后游标要跨两格
        tok = toks[i]
        if i == 0 and not tok.startswith("-"):
            rows.append((_unquote(tok), "", t(EXE_LINE)))
            i += 1
            continue
        if tok.startswith("-"):
            key = ALIAS.get(tok, tok)
            value = ""
            nxt = toks[i + 1] if i + 1 < total else None
            if key in VALUE_FLAGS and nxt is not None and _is_value(nxt):
                value = _unquote(nxt)
                i += 1                   # 取值已被吃掉
            rows.append((tok, value, _meaning(key, value)))
        else:
            rows.append(("", _unquote(tok), t(UNKNOWN)))
        i += 1
    return rows


def _meaning(key, value):
    """说明正文 + 取值补充（如果有）。缺参数说明时回退到 UNKNOWN。"""
    text = t(DESC.get(key, UNKNOWN))
    hint = VALUE_HINT.get(key)
    if hint and value:
        text = text + "\n" + t(hint).format(value)
    return text
