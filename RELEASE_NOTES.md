# LLama 启动器 v0.3.85 发布说明 / Release Notes

> 最新版本 / Latest release: **v0.3.85** · 发布日期 / Released: 2026-09-19

---

## English

### New Features

- **Six color themes** — independent `src/themes.py` with Dark / Light / Orange / Green / Gray / Brown. All palettes share identical metrics, so switching never changes the layout size. The Light theme uses darker borders for clear separators.
- **Redesigned Model Download tab** — two-column layout (left: repositories, right: files inside the selected repo). Three-field search (A organization/author, B model name/version, C auxiliary keyword) with AND/OR matching; per-page count selector; Load more; Open download directory.
- **File table with per-row actions** — file name / size / installed / download / progress columns; header-click sorting; resumable per-file downloads. Clicking an already-downloaded file sets it as the main model and runs the full follow-up logic.
- **Repository info + operation log** below the two columns, with a draggable splitter to adjust the ratio. "Last updated" is now populated (HF `full=true`).
- **Custom download directory** — defaults to the main page's model directory, with a per-repository subfolder.
- **MTP detection broadened** — recognizes `mtp` / `nextn` / `next_n` / `eh_proj` / `shared_head` tensors and `nextn_predict_layers` metadata; MTP-capable models can enable it, and detection misses no longer force-disable the checkbox.
- **Ad slot fills horizontally** next to the launch buttons.

### Improvements

- Window default size set to 1280 × 1280.
- Generation-parameters grid redistributed so labels are never clipped.
- Advanced-parameters area compacted: continuous batching / mlock / mmap / MTP + status on one row; CPU threads and API Key no longer dominate the width (even column distribution).
- Launch buttons compressed (150 → 120 px).
- Spin-box up/down arrows explicitly drawn — both increment and decrement are visible and clickable.
- Model path shown at the left of the status bar.
- Model sorting moved next to the main-model selector.
- Theme switching no longer resizes the window.
- Tab labels enlarged/boldened; group-box titles (Basic / Multi-GPU / Advanced) bold and larger.

### Fixes

- Residual-process dialog no longer appears on every startup: the version/`--list-devices` probe processes are excluded from residual detection.
- Export launch file no longer creates an extra `.ico` next to the `.bat`; the shortcut uses the launcher's embedded icon.
- Config JSON now includes `custom_tools`, `opencode_workdir`, `last_download_dir`.

### Downloads

| File | Description |
|------|-------------|
| `LLama-Launcher-v0.3.85-win-x64.exe` | Single-file build — no Python required |
| `LLama-Launcher-v0.3.85-win-x64-portable.zip` | Portable build — extract and run |
| Source code (zip / tar.gz) | Full source |

---

## 中文

## 🎨 主题配色（新增）
- 独立配色文件 `src/themes.py`，内置 **深色 / 浅色 / 橙色 / 绿色 / 灰色 / 棕色** 六套方案
- 状态栏「🎨 主题」菜单选择，切换**不改变布局尺寸**；浅色边框加深、分割线清晰

## ⬇️ 模型下载页改版
- **左右双列**：左=模型仓库，右=仓库内文件
- **三栏检索**：A 组织/作者、B 模型名称/版本、C 辅助关键词，支持「并 / 或」匹配
- **每页数量**可选，「加载更多」「打开下载目录」
- 文件表：文件名 / 大小 / 已安装 / 下载 / 进度，**表头点击排序**；每行独立下载与进度，支持断点续传
- **点击已安装文件**即切换为主模型，并执行原有后续逻辑
- 下方新增「仓库信息」「操作日志」，并带**可上下拖动的比例条**
- 下载目录默认 = 主页「模型目录」，按仓库名建子文件夹

## 🧩 界面与参数
- 窗口默认尺寸 **1280 × 1280**
- 生成参数区重新排布，标签不再被隐藏；高级参数区压缩，连续批处理/mlock/mmap/MTP 同行
- CPU线程 / API Key 不再过宽，各控件平均分布；底部十个按钮压缩宽度，右侧广告位横向填充
- 模型路径显示在底部状态栏左侧；排序移到主模型右侧
- 六个标签字号加大加粗；分组标题（基本参数/多显卡/高级参数）加粗加大
- 数值框上下箭头显式绘制，加/减都可见可点

## 🛠️ 修复
- 每次启动误报「残留进程」已修复（排除版本/设备探测进程）
- 导出启动文件不再产生多余 `.ico` 图标文件
- 配置文件补齐 `custom_tools` / `opencode_workdir` / `last_download_dir`
- 「最近更新」列现可正确显示

---

# LLama 启动器 v0.2.0 发布说明 / Release Notes

## 🆕 新增功能 New Features

### HuggingFace 模型下载
- 内置 HF 浏览/搜索/下载，支持按下载量、点赞数排序
- 断点续传（HTTP Range + .part），多文件队列
- 默认组织：unsloth，可自定义保存目录

### llama.cpp 在线更新器
- 一键下载任意 GitHub Release 版本或分支源码 zip
- 安全安装模式：仅覆盖同名文件，自动 .bak 备份，不碰模型和配置
- 分支源码模式下载到独立 `llama.cpp-<branch>` 子目录

### 使用统计窗口（工具 → 模型统计）
- 按模型统计打开次数、使用时长、输入/输出 token 数
- 按时段/天/月维度查看，支持 CSV 导出

### KV Cache 量化
- K/V cache 独立类型设置（`-ctk` / `-ctv`），支持 q4_0、q8_0、f16 等量化格式，显著降低显存占用

### MTP 多 Token 预测
- 自动检测 GGUF 中的 MTP tensor（支持分片文件）
- 可用时启用 `--spec-type draft-mtp` 投机解码加速

### 多 GPU 面板
- 通过 `llama-server --list-devices` 检测设备
- 单卡指定、split 模式（`-sm`）、tensor-split 权重分配（`-ts`）、主 GPU 索引（`-mg`）

### 上下文预设 + VRAM 推荐
- 根据可用显存一键选择 16K–512K 上下文长度
- 与上下文输入框双向绑定

### 采样预设
- 精确 / 均衡 / 创意 三档一键切换

### Flash Attention & 连续批处理
- `-fa on/off` 和 `--cont-batching` 高级参数开关

### 系统托盘最小化
- 关闭窗口缩入托盘，托盘菜单支持显示/启动/停止/退出

### 深色 / 浅色主题
- 状态栏灯泡按钮一键切换

### 导出命令为 .bat
- 将生成的完整命令行保存为 .bat 文件到任意路径

### 配置导出 / 导入（.aic）
- 全量备份和恢复所有设置为便携 JSON 文件

### 在线模型查询
- HuggingFace 查询模型简介/下载量/点赞数（7天缓存，离线降级）

### BAT 校验器
- 执行前验证导出的 .bat 文件完整性

## 🔧 改进 Improvements

- 视觉模型配对增加 embedding 维度一致性检查，不匹配时红色警告并拦截启动
- 模型列表默认自然排序（目录+文件名），可选大小降序/仅名称
- Agent 工具选择跨会话记忆
- 日志按天归档：`logs/运行日志-YYYYMMDD.log`
- 自定义应用图标和广告位

## ⚙️ 技术改进 Technical

- Windows Job Object (KILL_ON_JOB_CLOSE) 确保进程树清理，崩溃后立即释放显存
- GGUF header 离线解析架构、上下文长度、量化格式、参数量
- HTTP Range 断点续传下载器

---

# LLama Launcher v0.2.0 Release Notes

## New Features

### HuggingFace Model Download
- Built-in HF browse/search/download with sorting by downloads/likes
- Resumable downloads (HTTP Range + .part), multi-file queue
- Default org: unsloth, customizable save directory

### llama.cpp In-App Updater
- One-click download of any GitHub Release or branch source zip
- Safe install mode: only overwrites same-named files with auto .bak backup; never touches models/configs
- Branch source mode downloads to dedicated `llama.cpp-<branch>` subdirectory

### Usage Statistics Window (Tools → Model Stats)
- Per-model open count, usage time, input/output tokens from llama-server logs
- Hour/day/month breakdown with scope filters; CSV export

### KV Cache Quantization
- Independent K/V cache types (`-ctk` / `-ctv`) supporting q4_0, q8_0, f16 and other quantized formats for reduced VRAM usage

### MTP Multi-Token Prediction
- Auto-detects MTP tensors in GGUF files (shard-aware)
- Enables `--spec-type draft-mtp` speculative decoding when available

### Multi-GPU Panel
- Device detection via `llama-server --list-devices`
- Single-card pinning, split mode (`-sm`), tensor-split weights (`-ts`), main GPU index (`-mg`)

### Context Presets with VRAM Recommendation
- One-click context length presets (16K–512K) based on available VRAM
- Two-way binding with the context length field

### Sampling Presets
- Precise / Balanced / Creative one-click sampling parameter sets

### Flash Attention & Continuous Batching
- `-fa on/off` and `--cont-batching` controls in advanced parameters

### Tray Minimize
- Closing window minimizes to system tray; menu supports show/start/stop/quit

### Dark / Light Theme
- Toggle via light-bulb button in status bar

### Export Command as .bat
- Save the generated command line to a .bat file at any path

### Config Export / Import (.aic)
- Full backup and restore of all settings as portable JSON-based file

### Online Model Lookup
- HuggingFace query for model info/downloads/likes (7-day cache, offline fallback)

### BAT Validator
- Validates exported .bat files before execution

## Improvements

- Vision model pairing: embedding-dimension consistency check with red warning and pre-start interception on mismatch
- Model list natural sorting by default; size-descending and name-only options available
- Agent tool selection remembered across sessions
- Per-day log files: `logs/运行日志-YYYYMMDD.log`
- Customizable app icon and ad slot

## Technical

- Windows Job Object (KILL_ON_JOB_CLOSE) ensures process tree cleanup, immediate VRAM release on crash
- GGUF header parser reads architecture, context length, quantization format, parameter count offline
- Resumable HTTP downloader with .part temp files and Range request support
