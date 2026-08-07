# LLama 启动器

基于 llama.cpp 的本地大模型图形化启动器。让「选模型 → 配参数 → 后台启动 → 实时监控 → 连接 Agent 工具」整条链路一键搞定，不再需要手敲命令行。

## 一、这个项目解决什么问题？

在本地跑大模型（llama.cpp）时，你通常要面对：

- **命令行繁琐**：`llama-server.exe -m 模型 -ngl all -c 32768 -n 8192 -fa on ...` 一长串参数靠记忆
- **模型难管理**：模型文件散落在多个目录，还要区分视觉模型（mmproj）、跳过未下完的文件
- **后台服务难控制**：黑窗口一闪而过、崩溃后显存不释放、模型跑飞/无限复读停不下来
- **视觉模型容易配错**：主模型和 mmproj 维度不匹配时加载直接失败
- **接 Agent 工具麻烦**：opencode、Claude Code 等要手动配 baseURL、API Key

本启动器把以上全部图形化、自动化：**自动扫描模型、可视化调参、隐藏窗口后台运行、实时监控资源、一键停止、打开 Agent 自动连接服务**。

---

## 二、主要功能

### 模型管理
- **自动扫描**：递归扫描 llama 目录下所有 `.gguf`，自动跳过未下载完成的文件（`.xltd` 等）
- **视觉模型按目录配对**：只自动选中与主模型同目录的 `mmproj`；并做**嵌入维度一致性校验**——不匹配时红字警告 + 启动前拦截，避免"加载失败"报错
- **模型信息**：离线解析 GGUF 头，显示架构/训练上下文/量化格式/参数量

### 参数配置
- **基本参数**：监听地址、端口、上下文预设（按显存一键推荐 16K~512K）、GPU 层数、上下文长度、预测 Token
- **高级参数**：CPU 线程、批大小、并行 slots、闪存注意力、KV 缓存类型、连续批处理、温度/Top-P/Top-K/重复惩罚、采样预设（严谨/均衡/创意）、API Key、超时、mlock、mmap、自动开浏览器
- **上下文预设 ↔ 上下文长度联动**：预设点选自动写上下文；手动改上下文自动回显对应档位（非预设值显示「自定义」）
- **每个参数带悬停说明**，完整解释见 `参数说明.md`（菜单「关于 → 参数说明」）

### 服务与监控
- **隐藏窗口后台启动**：`/health` 就绪后自动打开浏览器 Web 界面
- **一键停止**：`taskkill /T` 清理进程树（模型跑飞/无限复读时救命）
- **崩溃防残留（显存自动释放）**：服务进程放入 Windows 作业对象（KILL_ON_JOB_CLOSE），本程序无论崩溃还是被强杀，系统都会自动清理 llama-server 进程树，立即释放显存
- **实时状态监控**：状态栏显示 CPU、内存、显存（nvidia-smi）、运行模型、API 活动

### Agent 工具
- 内置 4 个：**opencode**（自动生成 opencode.json 连接服务）、**opencode 桌面版**（自动复制连接信息到剪贴板）、**Claude Code**（保留，不自动连接）、**llama-server**
- 底部「打开 Agent 工具」打开列表当前高亮的工具；**记住上次选中的工具并高亮**，下次启动一眼看到
- 服务运行时打开工具自动连接；服务未运行时正常打开并提示

### 其他
- **记住上次参数**：自动保存到 `config.json`
- **导出/导入配置**：`.aic` 文件（内容即 JSON），完整备份/还原设置
- **模型联网评估**：用模型名查 HuggingFace，显示简介/下载量/点赞（缓存 7 天，离线自动退回本地信息）
- **托盘最小化**：关闭窗口缩到托盘，托盘菜单可显示/启动/停止/退出
- **日志落盘**：`logs/运行日志-YYYYMMDD.log` 按天分文件
- **深浅主题**：状态栏右下角灯泡一键切换
- **可自定义图标 / 广告位**：放入 `assets/icon.ico` 换图标；`assets/ad.png` 显示在底部 430×40 广告位

---

## 三、安装方法

### 方式 A：源码运行（开发/自用）

**环境要求**
- Windows
- Python 3.9+（本机验证 3.13）
- 目录内需有 llama.cpp 的 `llama-server.exe` 及配套 DLL（从 llama.cpp Releases 解压）

**步骤**
```bat
cd /d 你的启动器目录
pip install -r requirements.txt
python main.py
```

依赖（`requirements.txt`）：`PyQt6`、`requests`、`psutil`

### 方式 B：直接运行打包好的 exe

- 使用 `dist\LLama启动器.exe`（单文件，约 39 MB），**无需安装 Python**，双击即可运行
- 首次启动较慢（需解压到临时目录，约几秒）；个别杀毒软件可能误报，加入白名单即可

---

## 四、使用方法

### 快速上手
1. **设置 llama 目录**：选择 llama.cpp 所在文件夹（含 `llama-server.exe`），点「刷新模型」
2. **选模型**：下拉选择主模型；视觉模型自动按目录配对（维度不匹配会有红色警告，可改选或选「不使用」）
3. **调参数**：端口默认 8080、监听地址 `127.0.0.1`；可用「上下文预设」按显存一键推荐上下文；高级参数按需展开
4. **启动**：点「启动服务」→ 隐藏窗口后台运行 → 就绪后自动打开浏览器 Web 界面（`http://127.0.0.1:8080/`）
5. **监控**：状态栏实时显示 CPU/内存/显存/运行模型/API 活动
6. **停止**：模型跑飞、幻觉复读时点「停止服务」一键终止
7. **接 Agent**：切到「Agent 工具」页选中工具 → 点底部「打开 Agent 工具」（服务运行时自动连接）

### 菜单说明
| 菜单 | 项目 |
|------|------|
| 开始 | 启动服务 / 停止服务 / 退出 |
| 工具 | 刷新模型 / 打开模型目录 ｜ 打开管理页面 / 查看 API 模型列表 ｜ 打开 Agent 工具 ｜ 导出配置(.aic) / 导入配置(.aic) ｜ 清空日志 / 打开日志目录 |
| 关于 | 参数说明 / 开发者信息 |

---

## 五、输入输出示例

### 1. 启动命令示例

界面点「启动服务」后，底部「命令预览」和日志会显示**实际执行的命令行**。例如：

```
llama-server.exe -m <你的模型路径，如 D:\models\gemma-4-31B-it-Q6_K.gguf>
  --mmproj <你的视觉模型路径，如 D:\models\mmproj-BF16.gguf>
  -ngl all -c 32768 -n 8192 -fa on --cont-batching
  --host 127.0.0.1 --port 8080
  -b 2048 -ctk f16 -ctv f16
  --temp 0.80 --top-k 40 --top-p 0.95 --repeat-penalty 1.00
  --timeout 3600 -a gemma-4-31B-it-Q6_K
```

### 2. 启动日志示例（「运行日志」页）

```
[防护] 已启用 Job Object：本程序退出/崩溃时，llama-server 将被系统自动清理，显存立即释放
common_params_print_info: verbosity = 3
srv  load_model: loading model '<你的模型路径>'
服务已就绪: http://127.0.0.1:8080
```

### 3. 浏览器 / API 地址

- Web 聊天界面：`http://127.0.0.1:8080/`
- OpenAI 兼容接口：`http://127.0.0.1:8080/v1`

用 curl 测试接口（输入/输出）：

```
curl http://127.0.0.1:8080/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"gemma-4-31B-it-Q6_K\",\"messages\":[{\"role\":\"user\",\"content\":\"你好\"}],\"max_tokens\":64}"
```

输出（节选）：

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "gemma-4-31B-it-Q6_K",
  "choices": [{ "message": { "role": "assistant", "content": "你好！很高兴见到你……" } }]
}
```

### 4. Agent 自动连接示例

服务运行时打开 opencode，启动器自动在 llama 目录写入 `opencode.json`（备份并合并已有配置）：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "llama.cpp": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "llama-server (local :8080)",
      "options": { "baseURL": "http://127.0.0.1:8080/v1" },
      "models": { "gemma-4-31B-it-Q6_K": { "name": "gemma-4-31B-it-Q6_K" } }
    }
  }
}
```

### 5. 配置导出示例

「工具 → 导出配置」生成 `xxx.aic`（内容即 JSON，与 `config.json` 结构一致），可在另一台机器「导入配置」还原全部设置。

---

## 目录结构

```
LLama启动器/
├── main.py                # 程序入口
├── requirements.txt       # 依赖
├── 参数说明.md             # 每个参数的完整解释
├── .gitignore
├── config.json            # 运行配置（自动生成，含 API Key，请勿上传）
├── hf_model_cache.json    # HF 查询缓存（自动生成）
├── logs/                  # 运行日志（自动生成）
├── assets/
│   ├── icon.ico           # 程序图标（可选，放入即生效）
│   ├── ad.png             # 底部广告位 430×40（可选）
│   └── donate_qr.jpg      # 开发者信息中的捐款二维码（可选）
├── dist/LLama启动器.exe    # 打包好的可执行文件（pyinstaller 生成）
└── src/
    ├── main_window.py       # 主窗口 + 菜单 + 托盘 + 状态栏
    ├── config.py            # 配置读写
    ├── model_scanner.py     # 模型扫描 / mmproj 配对
    ├── gguf_reader.py       # GGUF 头解析
    ├── cmd_builder.py       # 命令行生成
    ├── server.py            # 子进程 / 健康检查 / 停止 / 作业对象
    ├── jobobject.py         # Windows 作业对象（崩溃自动清理）
    ├── system_monitor.py    # CPU/内存/显存/模型/API 监控
    ├── hf_info.py           # HuggingFace 模型评估
    ├── presets.py           # 上下文预设 / 采样预设
    ├── tools.py             # Agent 工具注册与检测
    ├── opencode_launcher.py # 生成 opencode.json
    └── about_dialog.py      # 开发者信息
```

## 开发者信息

- 开发者：AI创客师
- 哔哩哔哩入口见「关于 → 开发者信息」（链接可点击直达）
- 如需更换：编辑 `src/about_dialog.py` 顶部常量

## 二次开发规划

- [ ] 模型下载通道（HuggingFace / ModelScope）
- [ ] 模型评估接入 ModelScope 来源
