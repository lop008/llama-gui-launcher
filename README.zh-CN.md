# LLama 启动器

**[English / English](README.md)**

基于 llama.cpp 的本地大模型图形化启动器。让「选模型 → 配参数 → 后台启动 → 实时监控 → 连接 Agent 工具」整条链路一键搞定，不再需要手敲命令行。

> **最新版本：v0.3.85** —— 六套主题配色、模型下载页双列改版、逐文件断点续传，以及一大轮界面打磨。详见 [发布说明](RELEASE_NOTES.md) 与 [更新日志](CHANGELOG.md)。

## 最新版本 v0.3.85 更新

- **六套主题配色**：深色 / 浅色 / 橙色 / 绿色 / 灰色 / 棕色，独立文件 `src/themes.py`；各配色尺寸完全一致，切换**不改变布局大小**。
- **模型下载页改版**：左右双列（左=模型仓库，右=仓库内文件）；**三栏检索**（A 组织/作者 · B 模型名称/版本 · C 辅助关键词），支持「并 / 或」匹配；每页数量可选、「加载更多」「打开下载目录」。
- **逐文件操作**：文件名 / 大小 / 已安装 / 下载 / 进度列，**表头点击排序**，**每行独立断点续传**；点击已安装文件即切换为主模型并执行原有后续逻辑。
- **仓库信息 + 操作日志**位于双列下方，带**可拖动比例条**。
- **自定义下载目录**：默认 = 主页「模型目录」，按仓库名建子文件夹。
- **MTP 检测增强**：识别 `mtp` / `nextn` / `next_n` / `eh_proj` / `shared_head` 张量及 `nextn_predict_layers` 元数据。
- **界面打磨**：窗口默认 1280 × 1280、高级参数区压缩、数值框上下箭头始终可见、模型路径显示在状态栏、标签与分组标题加大加粗、广告位横向填充。
- **修复**：启动不再误报「残留进程」；导出启动文件不再产生多余 `.ico`；配置补齐 `custom_tools` / `opencode_workdir` / `last_download_dir`。

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
- **列表排序**：目录+文件名升序（自然排序，默认）/ 大小降序 / 仅名称
- **视觉模型按目录配对**：选择主模型后**只列出同目录下的 mmproj**；自动选中配套项并做**嵌入维度一致性校验**——不匹配时红字警告 + 启动前拦截，避免"加载失败"报错
- **模型信息**：离线解析 GGUF 头，显示架构/训练上下文/量化格式/参数量

### 参数配置
- **基本参数**：监听地址、端口、上下文预设（按显存一键推荐 16K~512K）、GPU 层数、上下文长度、预测 Token
- **高级参数**：CPU 线程、批大小、并行 slots、闪存注意力、**KV 缓存 K / V 独立类型**（`-ctk`/`-ctv`，如 K=q8_0 + V=f16）、连续批处理、温度/Top-P/Top-K/重复惩罚、采样预设（严谨/均衡/创意）、API Key、超时、mlock、mmap、自动开浏览器
- **多显卡面板**：`llama-server --list-devices` 检测设备；勾 1 张 = 指定只用该卡，≥2 张 = 拆分模式（`-sm`）/ tensor-split 权重（`-ts`）/ 主 GPU（`-mg`）
- **MTP 多 token 预测**：选模型后自动检测 GGUF 是否含 MTP 张量（支持分片模型；识别 `mtp` / `nextn` / `next_n` / `eh_proj` / `shared_head` 张量及 `nextn_predict_layers` 元数据），可用时勾选启用 `--spec-type draft-mtp` 投机解码提速
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

### 模型下载 & llama.cpp 更新
- **模型下载页**（huggingface.co/unsloth）：**左右双列**（左=模型仓库，右=仓库内文件）；**三栏检索**（A 组织/作者 · B 模型名称/版本 · C 辅助关键词）支持「并 / 或」匹配；按下载量/点赞/名称/更新时间排序；**逐文件表格**（文件名/大小/已安装/下载/进度），表头点击排序，**每行独立断点续传**（HTTP Range + `.part`）；「加载更多」+ 每页数量；仓库信息 + 操作日志（可拖动比例条）；**自定义下载目录**（默认主页模型目录，按仓库建子文件夹）
- **更新 llama.cpp 页**：选择任意 GitHub **Release 版本**（或手输 tag）→ 下载 Windows x64 预编译包 → **安全安装**：只覆盖目标目录同名文件并自动备份 `.bak`，模型/配置等其他文件一律不动；也可切到**分支源码模式**：任选分支（如 `main`），断点续传下载源码 zip 到自选目录下的 `llama.cpp-<分支>` 子目录
- **导出命令预览为 .bat**（工具菜单）：把「命令预览」页的完整命令行原样存成 `.bat`，存储路径任选；另有「导出一键启动(.bat)」并创建桌面快捷方式

### 模型统计（独立窗口：工具 → 模型统计…）
- 按模型统计：**打开次数、使用时长、输入/输出 Token**（解析 llama-server 日志 `prompt eval time` / `eval time`）
- 时间明细支持 **小时 / 日 / 月** 粒度，范围可选 全部/今天/最近一周/本月（自然月），可导出 CSV

### 其他
- **记住上次参数**：自动保存到 `config.json`
- **导出/导入配置**：`.aic` 文件（内容即 JSON），完整备份/还原设置
- **导出一键启动**：把当前模型与参数导出成双击即启动 `llama-server` 的 `.bat`，并自动在桌面创建带软件图标的快捷方式
- **模型联网评估**：用模型名查 HuggingFace，显示简介/下载量/点赞（缓存 7 天，离线自动退回本地信息）
- **托盘最小化**：关闭窗口缩到托盘，托盘菜单可显示/启动/停止/退出
- **日志落盘**：`logs/运行日志-YYYYMMDD.log` 按天分文件
- **六套主题配色**（深色 / 浅色 / 橙色 / 绿色 / 灰色 / 棕色）：状态栏右下角「🎨 主题」菜单选择，切换不改变布局尺寸
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

### 方式 B：直接运行打包好的 exe（无需安装 Python）

从 [Releases](https://github.com/lop008/llama-gui-launcher/releases) 页面下载：

| 文件 | 说明 |
|------|------|
| `LLama-Launcher-v0.3.85-win-x64.exe` | **单文件版**（约 43 MB），双击即运行。首次启动较慢（需解压到临时目录，约几秒）；个别杀毒软件可能误报，加入白名单即可。 |
| `LLama-Launcher-v0.3.85-win-x64-portable.zip` | **便携版**，解压后运行 `LLama启动器-win-x64-portable.exe`，启动更快、无需自解压。 |

将 `llama-server.exe` 及配套 DLL 放到同一目录（或在界面中指定启动器路径）。

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
| 工具 | 刷新模型 / 打开模型目录 ｜ 打开管理页面 / 查看 API 模型列表 ｜ 打开 Agent 工具 ｜ 导出配置(.aic) / 导入配置(.aic) / 导出一键启动(.bat)（并在桌面创建带软件图标的快捷方式）/ **导出命令预览(.bat)…（自选存储路径）** / **模型统计…（独立窗口）** ｜ 清空日志 / 打开日志目录 |
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
├── docs/
│   ├── cover.png          # 发布封面图（v0.3.85）
│   └── screenshots/       # README / Release 引用的界面截图
├── dist/                  # 打包好的可执行文件（pyinstaller 生成，不入库）
└── src/
    ├── main_window.py       # 主窗口 + 菜单 + 托盘 + 状态栏
    ├── config.py            # 配置读写
    ├── themes.py            # 六套配色（深/浅/橙/绿/灰/棕）
    ├── model_scanner.py     # 模型扫描 / 排序 / mmproj 配对
    ├── gguf_reader.py       # GGUF 头解析 + MTP 张量检测
    ├── cmd_builder.py       # 命令行生成（KV K/V、多显卡、MTP）
    ├── server.py            # 子进程 / 健康检查 / 停止 / 作业对象
    ├── jobobject.py         # Windows 作业对象（崩溃自动清理）
    ├── system_monitor.py    # CPU/内存/显存/模型/API 监控
    ├── hf_info.py           # HuggingFace 模型评估
    ├── hf_browse.py         # HF 仓库检索 / 文件列表（下载页后端）
    ├── hf_download_tab.py   # 模型下载 UI（双列、三栏检索、逐文件续传）
    ├── model_downloader.py  # 断点续传 HTTP 下载器（.part + Range）
    ├── llama_updater.py     # llama.cpp Release/分支获取 + 安全安装
    ├── updater_tab.py       # 更新 llama.cpp UI（版本 / 分支源码）
    ├── usage_stats.py       # 使用统计存储（打开次数/时长/token，时日月分桶）
    ├── stats_dialog.py      # 独立模型统计窗口
    ├── bat_validator.py     # .bat/.cmd/.ps1 启动脚本静态校验
    ├── presets.py           # 上下文预设 / 采样预设
    ├── tools.py             # Agent 工具注册与检测
    ├── opencode_launcher.py # 生成 opencode.json
    └── about_dialog.py      # 开发者信息
```

## 界面截图

| | |
|---|---|
| ![主界面](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/main.png) | ![高级参数](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/advanced.png) |
| 主界面 | 高级参数 + 多显卡 |
| ![模型下载](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/download.png) | ![llama.cpp 更新器](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/updater.png) |
| 模型下载（双列、断点续传） | 更新 llama.cpp |
| ![Agent 工具](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/agent.png) | ![命令预览](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/preview.png) |
| Agent 工具 | 命令预览 |

## 开发者信息

- 开发者：AI创客师
- 哔哩哔哩入口见「关于 → 开发者信息」（链接可点击直达）
- 如需更换：编辑 `src/about_dialog.py` 顶部常量

## 二次开发规划

- [x] 模型下载通道（HuggingFace，默认组织 `unsloth`；断点续传队列 + 保存目录选择）
- [x] llama.cpp 应用内更新（Release 版本安全安装；分支源码 zip 下载）
- [ ] 模型评估接入 ModelScope 来源
