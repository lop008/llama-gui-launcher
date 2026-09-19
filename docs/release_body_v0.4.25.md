[![LLama 万能启动器 v0.4.25](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/cover-v0.4.25.png)](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/cover-v0.4.25.png)

## LLama 万能启动器 v0.4.25

基于 llama.cpp 的本地大模型图形化启动器。自动扫描模型、可视化调参、隐藏窗口后台运行、实时监控、一键连接 Agent 工具。

A GUI launcher for llama.cpp local LLMs. Auto-scan models, visual parameter tuning, hidden-window background startup, real-time monitoring, one-click Agent tool connection.

### 本次更新 / What's New in v0.4.25

- 🧩 **对话模板支持** — 新增 `--jinja`、思考强度（`--chat-template-kwargs {"reasoning_effort":"low|medium|high"}`）与推理预算（`--reasoning-budget`）；选择模型后自动检测 GGUF 的 `tokenizer.chat_template`，模型不支持时对应控件自动置灰
- 📥 **导入启动文件** — 底部 7 号位 + 菜单「工具 → 导入启动文件 (.bat)…」，解析已有 `.bat/.cmd/.ps1/.sh/文本` 文件并把参数回填到界面
- 🛡️ **残留进程提示优化** — 弹窗新增「不再提示」（写入 `config.json`），高级参数可随时重新开启
- 🔌 **端口占用建议** — 端口被占用时建议可用端口，确认后自动更新主界面端口号
- 🖼️ **广告位图片按比例缩放** — 仅横向铺满、保持原始比例，不再纵向拉伸
- 🛠️ **启动文件校验器** 识别 `--jinja` / `--chat-template-kwargs` / `--reasoning-budget`

### 主要功能 / Features

- 自动扫描模型 + 视觉模型按目录配对 + 维度一致性校验
- 可视化参数配置（上下文/采样预设联动、KV 量化、MTP、多显卡、Flash Attention）
- 对话模板：Jinja / 思考强度 / 推理预算，按模型能力自动联动
- 隐藏窗口后台启动，`/health` 就绪自动打开浏览器
- 崩溃防残留（Windows 作业对象，显存自动释放）
- 实时状态栏监控（CPU / 内存 / 显存 / 模型 / API 活动）
- Agent 工具自动连接（opencode 自动生成配置等）
- 托盘最小化 / 日志落盘 / 六套主题 / 导出导入配置(.aic) / 导入导出启动文件
- 模型下载（HuggingFace，断点续传）与 llama.cpp 在线更新

### 截图 / Screenshots

[![主界面](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/main.png)](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/main.png)
[![高级参数](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/advanced.png)](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/advanced.png)
[![模型下载](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/download.png)](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/download.png)
[![更新 llama.cpp](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/updater.png)](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/updater.png)
[![Agent 工具](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/agent.png)](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/agent.png)
[![命令预览](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/preview.png)](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/preview.png)

### 下载 / Downloads

| 文件 | 说明 |
|------|------|
| `LLama-Launcher-v0.4.25-win-x64.exe` | 单文件版，无需安装 Python，双击即用 |
| `LLama-Launcher-v0.4.25-win-x64-portable.zip` | 便携版，解压即用 |
| Source code (zip / tar.gz) | 源码 |

### 关于 / About

开发者：AI创客师 · License: MIT
