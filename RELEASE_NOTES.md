# LLama 启动器 发布说明 / Release Notes

> 最新版本 / Latest release: **v0.5.15** · 发布日期 / Released: 2026-11-27

---

# LLama 启动器 v0.5.15 发布说明 / Release Notes

## English

A feature release: speculative decoding becomes a first-class part of the interface, the model folder is finally sorted by what the files actually are, and every version now ships both x64 and ARM64 builds.

### New Features

- **Speculative decoding** — the "Enable MTP" checkbox on the Advanced page grew into a **Speculative decoding** row right under the model selector: a method dropdown with **Off / Auto** plus 12 methods (MTP, DFlash 2, DFlash, DSpark, LiliCorr, EAGLE-3, small-model draft, and the four n-gram variants), a colour-coded status label, a **Draft model** picker and a **Draft length** spinner. Support is detected, never guessed: which `--spec-type` values your local `llama-server` really accepts (read from its own `--help`), whether the selected model has a built-in MTP head, and whether a draft file actually matches the model. Methods your engine does not know are greyed out with the reason ("update llama.cpp"); methods missing their draft tell you what to download; and **Auto passes no `--spec-type` at all when nothing is usable**, so speculative decoding can never be the reason the server fails to start.
- **Auto priority editor** — **Sort** opens a dialog where you set which method `Auto` tries first: drag items with the mouse, or use ▲ / ▼ and Alt+↑ / Alt+↓. The order is saved; methods introduced later are appended automatically.
- **Download draft** — finds draft models on HuggingFace that pair with the model you selected (official GGUF publishers first), shows method / file / repository / size / notes, downloads into the main model's own folder — which is where drafts must live to be recognised — and selects the result for you. Authors' repos that publish safetensors only are not offered as one-click downloads; you get the exact `convert_hf_to_gguf.py … --target-model-dir …` command instead.
- **Auxiliary files inspector** — a summary line (`vision projection 8 · draft head 4 · calibration file 1 (view)`) opens a table of every non-model GGUF with its role, size, folder and which main model it serves, plus a button to open the folder.
- **Model list role screening** — vision projections, draft heads and quantization calibration files are no longer offered as "models". Roles are read from GGUF contents (tensor names, `general.type`, architecture) with the filename only as a fallback, and unreadable files are treated as models — a helper may be listed once in a while, but a real model is never silently hidden.
- **ARM64 support in the updater** — the "Update llama.cpp" page filtered out every asset with `arm` in its name, so Windows-on-ARM users saw an empty list. Both architectures are listed now, your own first.

### Improvements

- The main window was split from 3338 lines into ten focused modules under `src/ui/` with no behaviour change, so future features no longer pile into one file.
- 93 new interface strings translated into all 7 languages and 7 dead ones removed — the translation tables now match the source exactly (820 keys, 0 missing, 0 unused).

### Fixes

- **Queued downloads were silently dropped**: selecting a second download while one was running did nothing at all, with no message.
- A method that needs a draft file no longer emits `--spec-type` when the file is missing.
- The Russian translation table failed to parse (a missing trailing comma), so Russian users were served Chinese without any indication.
- **Residual-process detection never fired on Chinese Windows** — when no `llama-server` is running, `tasklist` writes a localised (GBK) "no tasks" message, which raised inside Python's reader thread and made the probe always return an empty list. Every text-decoded subprocess call now states its encoding, with a static check that fails the suite if a new call forgets it.

### Downloads

| File | Description |
|------|-------------|
| `LLama-Launcher-v0.5.15-win-x64.exe` | Single-file build (x64) — no Python required |
| `LLama-Launcher-v0.5.15-win-x64-portable.zip` | Portable build (x64) — extract and run |
| `LLama-Launcher-v0.5.15-win-arm64.exe` | Single-file build (ARM64, Snapdragon / Windows on ARM) |
| `LLama-Launcher-v0.5.15-win-arm64-portable.zip` | Portable build (ARM64) — extract and run |

## 中文

功能版本：投机解码正式做进界面，模型目录按文件真实身份筛查，并且从本版起每个版本同时发布 x64 与 ARM64 两套产物。

### 🆕 新增功能

- **投机解码**：高级页那个「启用 MTP」勾选框升级成基础页模型选择下方的**投机解码**行——**不启用 / 自动** 加 12 种方式（MTP、DFlash 2、DFlash、DSpark、LiliCorr、EAGLE-3、小模型草稿、4 种 n-gram），配状态标签、草稿模型选择、草稿长度。支持与否全部实测：读本机 `llama-server --help` 看引擎认哪些取值、读模型 GGUF 看有没有内嵌 MTP 头、看草稿与主模型配不配对。本机不认的方式置灰并在悬停里写原因（提示更新 llama.cpp），缺草稿的方式告诉你该下什么；**自动在一种可用方式都没有时完全不下发 `--spec-type`**，投机解码绝不会变成服务起不来的原因。
- **「自动」优先级排序**：下拉旁的「排序」按钮打开对话框，按住条目上下拖动，或用 ▲▼ 与 Alt+↑ / Alt+↓ 调整；顺序会保存，以后新版本新增的方式自动补在后面。
- **下载草稿**：按当前选中的模型在 HuggingFace 上找配套草稿（官方 GGUF 发布方优先），列表给出方式 / 文件 / 仓库 / 大小 / 说明，下载直接落到**主模型所在目录**（草稿必须同目录才会被配对），完成后自动选中。只放 safetensors 的原作者仓库不提供假下载，改为给出完整的 `convert_hf_to_gguf.py … --target-model-dir …` 转换命令与放回位置。
- **辅助文件清单**：模型行下方一行摘要（`视觉投影 8 · 投机草稿头 4 · 量化标定文件 1（查看）`），点开是全部非模型 GGUF 的表格：类型、文件名、大小、所在目录以及它服务于哪个主模型，并可一键打开目录。
- **模型目录角色筛查**：视觉投影（mmproj）、投机草稿头、量化标定文件（imatrix）不再出现在主模型下拉里。角色以 GGUF **内容**为准（张量名、`general.type`、架构），文件名只作兜底；读不出来的文件一律当主模型——宁可偶尔多显示一个辅助文件，也绝不静默藏掉真模型。
- **ARM64 支持回归**：「更新 llama.cpp」页以前把所有名字里带 `arm` 的资产都过滤掉了，导致 ARM 设备面对空列表（官方每个版本其实都发 4 个 arm64 包）。现在两种架构都列出，本机架构排最前。

### 🔧 改进

- 主窗口从 3338 行拆成 `src/ui/` 下十个职责单一的模块，行为逐字不变，新功能不必再往一个巨型文件里堆。
- 93 条新界面文案翻译进全部 7 张语言表，并清掉旧 MTP 勾选框遗留的 7 条死文案：语言表与源码严格一一对应（820 个 key，缺失 0、多余 0）。

### 🐛 修复

- **排队中的下载不再被静默丢弃**：正在下载时再点第二个文件，以前什么都不发生也没有提示。
- 需要草稿文件的投机方式，在草稿缺失时不再下发 `--spec-type`。
- 俄语语言表因缺少一个尾逗号而无法解析，导致俄语用户被无声地显示成简体中文。
- **中文系统上「启动时检测残留进程」一直静默失效**：没有 llama-server 在跑时 `tasklist` 会输出 GBK 的「信息: 没有运行的任务…」，Python 内部读线程解码失败，探测结果永远是空表。现在所有按文本读取的子进程都显式指定编码，并加了静态门禁防止新代码再漏。

### 下载

| 文件 | 说明 |
|------|------|
| `LLama-Launcher-v0.5.15-win-x64.exe` | 单文件版（x64），无需安装 Python，双击即用 |
| `LLama-Launcher-v0.5.15-win-x64-portable.zip` | 便携版（x64），解压即用 |
| `LLama-Launcher-v0.5.15-win-arm64.exe` | 单文件版（ARM64，骁龙本 / Windows on ARM） |
| `LLama-Launcher-v0.5.15-win-arm64-portable.zip` | 便携版（ARM64），解压即用 |

---

# LLama 启动器 v0.5.14 发布说明 / Release Notes

## English

A stability release: two crash bugs found by a new end-to-end test suite are fixed, and silent failures now leave a trace.

### Fixes

- **"Validate launch file" no longer dies on an illegal port** — a `.bat` / `.sh` containing `--port 99999` or `--port 0` reached a raw `socket.bind()`, which raises `OverflowError` rather than `OSError`, so the whole check aborted with an unhandled exception instead of telling you what was wrong. The port is now range-checked first and reported as `✘ --port out of the valid range (1-65535)`. The message was translated into all 8 languages.
- **Data Statistics no longer breaks on a damaged `stats.json`** — a single malformed record (a model entry that is not an object, or string / `null` / `NaN` numbers) made the Data Statistics window raise an exception on open, and the 5-second usage timer raise again while a server was running. Bad records are now skipped when reading so everything else still shows up, and they are repaired automatically on the next write.

### Improvements

- **Silent translation failures are now visible** — when a language table failed to load in a packaged build (missing file, syntax error, empty or non-dict table), the interface quietly fell back to Simplified Chinese with no clue anywhere. The reason is now written to stderr and can be queried programmatically via `i18n.failed_languages()`, which returns `{language-code: reason}`.

### Testing

- New end-to-end suites that **really start `llama-server`** and drive the launcher through the whole OpenAI surface (`/health`, `/props`, `/slots`, `/tokenize`, `/metrics`, `/v1/models`, non-streaming and streaming `/v1/chat/completions`, legacy `/completion`, 4xx on a malformed request body), API-key auth (401 without a token, 200 with), Job Object protection plus watchdog cleanup after an external kill, exported `.bat` files executed for real, HTTPS with a generated self-signed certificate, LAN sharing on `0.0.0.0`, pill tok/s / VRAM / busy-slot readings during live generation, and interface rebuild in all 8 languages.
- Robustness coverage for broken config / model / statistics data, invalid arguments, port conflicts and residual `llama-server` processes.
- Ten suites now run serially from one command and print a pass matrix; 3 stale test scripts that asserted hardcoded model paths and shard counts no longer report false failures.

### Downloads

| File | Description |
|------|-------------|
| `LLama-Launcher-v0.5.14-win-x64.exe` | Single-file build — no Python required |
| `LLama-Launcher-v0.5.14-win-x64-portable.zip` | Portable build — extract and run |
| Source code (zip / tar.gz) | Full source |

---

## 中文

稳定性版本：新增的端到端测试套件找出并修复了两个闪退问题，静默失败现在也会留下线索。

### 🐛 修复

- **修复「校验启动文件」遇到非法端口直接闪退**：脚本里写 `--port 99999` 或 `--port 0` 时会走到裸的 `socket.bind()`，抛出的是 `OverflowError`（不是 `OSError`），整个校验流程被异常打断，你看到的是程序出错而不是问题提示。现在先做 1–65535 范围校验并给出 `✘ --port 超出合法范围（1-65535）`，探测用 socket 也做了保护。新增文案已翻译进全部 8 种语言。
- **修复 `stats.json` 损坏时「数据统计」打不开**：只要有一条记录结构异常（模型条目不是对象，或数值字段是字符串 / `null` / `NaN`），打开数据统计窗口就会抛异常，服务运行期间的 5 秒统计定时器同样会反复报错。现在读取时跳过损坏条目（其余统计照常显示），并在下次写入时自动修复成正常记录。

### ⚡ 改进

- **语言包加载失败不再是静默回退**：打包后的 exe 里某张语言表加载失败（文件缺失、语法错误、表为空或类型不对）时，界面以前只是悄悄回退简体中文，任何地方都查不到原因。现在失败原因会写入 stderr，并可由 `i18n.failed_languages()` 查询到 `{语言代码: 原因}`。

### 🧪 测试

- 新增**真实启动 llama-server** 的端到端套件，覆盖完整 OpenAI 接口（`/health`、`/props`、`/slots`、`/tokenize`、`/metrics`、`/v1/models`、流式与非流式 `/v1/chat/completions`、旧版 `/completion`、异常请求体返回 4xx）、API Key 鉴权（无 token 401、带 token 200）、Job Object 进程保护与外部强杀后的看门狗清理、导出的 `.bat` 真实执行、HTTPS 自签证书、局域网 `0.0.0.0` 共享、悬浮窗生成期间的 tok/s / 显存 / 繁忙槽位读数，以及 8 种语言下的界面重建。
- 补齐坏配置 / 坏模型 / 坏统计数据、非法参数、端口冲突、残留 llama-server 进程等健壮性用例。
- 10 个套件可用一条命令串行跑完并输出通过矩阵；3 个写死模型路径与分片数的过期脚本不再误报失败。

### 下载

| 文件 | 说明 |
|------|------|
| `LLama-Launcher-v0.5.14-win-x64.exe` | 单文件版，无需安装 Python，双击即用 |
| `LLama-Launcher-v0.5.14-win-x64-portable.zip` | 便携版，解压即用 |
| Source code (zip / tar.gz) | 源码 |

---

# LLama 启动器 v0.5.13 发布说明 / Release Notes

## English

### New Features

- **Full multilingual interface** — a new "Language" menu offers 8 UI languages: 简体中文 / 繁體中文 / English / 日本語 / 한국어 / Русский / Español / Français, plus "Follow system language" which auto-matches the OS language on first launch. Switching applies after a confirmed restart and is remembered in `config.json` (`language`). Around 730 UI strings are translated through a lightweight built-in engine (`src/i18n.py` + `src/locales/`, the Chinese source text doubles as the lookup key); all languages ship inside the exe.

### Improvements

- Bottom action buttons and the theme button use minimum widths instead of fixed widths, so long Russian / French labels are no longer clipped and windows auto-size.
- Version number centralized: `__version__` in `src/__init__.py` is now the single source; the Windows version resource is generated at build time (hand-maintained `version_info*.txt` files removed).

### Fixes

- Fixed a startup crash caused by a loop variable shadowing the translation function in the tool-scan callback.
- Fixed swapped Korean translations for the "Browse…" and "Dark" entries.

### Downloads

| File | Description |
|------|-------------|
| `LLama-Launcher-v0.5.13-win-x64.exe` | Single-file build — no Python required |
| `LLama-Launcher-v0.5.13-win-x64-portable.zip` | Portable build — extract and run |
| Source code (zip / tar.gz) | Full source |

---

## 中文

### 🆕 新增功能

- **多语言界面**：新增「语言」菜单，支持 8 种界面语言（简体中文 / 繁體中文 / English / 日本語 / 한국어 / Русский / Español / Français），并提供「跟随系统语言」首次启动自动匹配系统语言；切换后确认重启即时生效，选择记入 `config.json` 的 `language`。约 730 条界面文案全量翻译（`src/i18n.py` + `src/locales/`，中文原文即索引键，缺失译文自动回退中文），所有语言随 exe 分发。

### 🔧 改进

- 底部按钮与主题按钮改用最小宽度替代固定宽度，俄/法等长文案不再裁字，窗口自适应加宽。
- 版本号集中化：`src/__init__.py` 的 `__version__` 为唯一来源，打包时自动生成 exe 版本资源，不再手工维护 `version_info*.txt`。

### 🐛 修复

- 修复工具扫描回调中循环变量遮蔽翻译函数导致的闪退。
- 修复韩语「浏览… / 深色」两条译文错位。

### 下载

| 文件 | 说明 |
|------|------|
| `LLama-Launcher-v0.5.13-win-x64.exe` | 单文件版，无需安装 Python，双击即用 |
| `LLama-Launcher-v0.5.13-win-x64-portable.zip` | 便携版，解压即用 |
| Source code (zip / tar.gz) | 源码 |

---

# LLama 启动器 v0.5.01 发布说明 / Release Notes

## English

### New Features

- **Tray hover pill** — after minimizing to the tray, a 30 px always-on-top capsule stays above the taskbar showing the app icon, **LLama.cpp**, live output speed in tok/s and a status dot. Hover or click to expand a data card (speed, CPU %, memory, GPU load %, VRAM, API busy slots, model name); system stats (CPU / memory / VRAM / GPU) are shown even while the server is idle. Drag to move (position remembered), double-click to restore the main window, right-click for a menu (open / start / stop / hide / quit, start·stop auto-disabled by service state). Theme-aware and can be turned off from Advanced parameters.
- **Live output speed** — a real-time tok/s readout derived by diffing the llama-server `/metrics` generated/predicted counters, with an automatic fallback that parses the latest `eval time` log line when `/metrics` is unavailable (drops to 0 about 8 s after generation ends). Adds GPU core utilization and API busy-slot count.
- **HTTPS + LAN sharing** — an "Enable HTTPS" toggle generates a self-signed key/cert into `certs/` (via `cryptography`, lazy-loaded) and wires `--ssl-key-file` / `--ssl-cert-file` through the command builder, health checks, browser URLs and opencode config. A "LAN sharing" toggle sets the host to `0.0.0.0` and shows the reachable `http(s)://<local-ip>:<port>` address.
- **Richer GGUF info** — supports Unsloth dynamic quantization (`UD-*`, `Q4_K_XL`, …) and skips the huge vocab/merge arrays for much faster parsing (recording the vocab size instead). Displays parameter count, license, quantizer, base model, block count, embedding / feed-forward size, attention heads + GQA, head dims, RoPE base, MTP/NextN layers, SSM state, tensor count, GGUF version, description and model URL.
- **Reorderable bottom tabs** — drag tabs to reorder; the order is persisted to `config.json` (`tab_order`) and restored next launch.
- **Online model query toggle** — the model-info pane gains a "query online" checkbox that auto-fetches HuggingFace details when a model is selected.
- **Updater target directory** — the llama.cpp updater honors a custom `updater_target` directory when set and valid.
- **More robust one-click launch** — `一键启动.bat` now locates the standalone exe via wildcards, falls back to `.venv` / portable / PATH Python, and self-heals missing PyQt6 dependencies.

### Improvements

- Launch-file validator recognizes `--ssl-key-file` and `--ssl-cert-file`; opencode config and Web UI/API links switch to `https` when HTTPS is enabled.
- Main-page 9th button now opens the Data Statistics window; "Model Stats" was renamed to "Data Statistics".
- Added `src/net_utils.py` (local IP discovery + self-signed certificate generation) and `src/pill.py` (tray hover pill).
- New dependency: `cryptography>=41` (also added to PyInstaller `hiddenimports`).

### Downloads

| File | Description |
|------|-------------|
| `LLama-Launcher-v0.5.01-win-x64.exe` | Single-file build — no Python required |
| `LLama-Launcher-v0.5.01-win-x64-portable.zip` | Portable build — extract and run |
| Source code (zip / tar.gz) | Full source |

---

## 中文

### 🆕 新增功能

- **托盘悬浮小窗**：点「×」收进托盘后，屏幕右下角常驻一个 30 像素高的置顶胶囊，最左为程序图标、随后显示「LLama.cpp」与实时输出速度 tok/s，并有状态圆点。鼠标悬停或单击展开数据卡片（速度、CPU%、内存、GPU 负载%、显存、API 接入数、模型名）；CPU / 内存 / 显存 / GPU 为实时系统数据，服务未运行时也照常显示。可拖动记忆位置、双击返回主界面、右键菜单（打开/启动/停止/隐藏/退出，启动·停止按服务状态自动置灰）。配色跟随主题，可在高级参数中关闭或重新开启。
- **实时输出速度**：对 llama-server 的 `/metrics` 生成计数器做差分得到 tok/s；旧版无 `/metrics` 时自动回退解析最新 `eval time` 日志行（生成结束约 8 秒后归零）。同时新增 GPU 核心利用率与 API 并发占用数。
- **HTTPS + 局域网共享**：勾选「启用 HTTPS」时用 `cryptography`（惰性加载）在 `certs/` 生成自签名证书，并把 `--ssl-key-file` / `--ssl-cert-file` 贯通到命令生成、健康检查、浏览器地址与 opencode 配置；勾选「局域网共享」时 host 自动切为 `0.0.0.0`，并显示可访问的 `http(s)://<本机IP>:<端口>` 地址。
- **更完整的 GGUF 信息**：支持 Unsloth 动态量化（`UD-*`、`Q4_K_XL` 等），跳过超大词表/merges 数组以显著提速（同时记录词表大小）。展示参数量、许可证、量化者、基础模型、层数、嵌入/前馈维度、注意力头与 GQA、头维度、RoPE 基数、MTP/NextN 层、SSM state、张量数、GGUF 版本、简介与模型主页。
- **底部标签可拖动排序**：拖动调整标签顺序，持久化到 `config.json` 的 `tab_order`，下次启动自动恢复。
- **联网查询开关**：模型信息区新增「联网查询」勾选框，选择模型后自动向 HuggingFace 拉取补充信息。
- **更新器自定义目标目录**：llama.cpp 更新器在配置 `updater_target` 非空且有效时优先安装到该目录。
- **一键启动更健壮**：`一键启动.bat` 用通配符定位单文件 exe，依次回退 `.venv` / 便携 / PATH 中的 Python，并在缺少 PyQt6 时自动补装依赖。

### 🔧 改进

- 启动文件校验器识别 `--ssl-key-file`、`--ssl-cert-file`；启用 HTTPS 时 opencode 配置与 Web/API 链接同步改用 `https`。
- 首页第 9 个按钮改为打开「数据统计」窗口；原「模型统计」统一更名为「数据统计」。
- 新增 `src/net_utils.py`（本机 IP 探测 + 自签名证书生成）与 `src/pill.py`（托盘悬浮小窗）。
- 新增依赖 `cryptography>=41`（同时加入 PyInstaller `hiddenimports`）。

### 下载

| 文件 | 说明 |
|------|------|
| `LLama-Launcher-v0.5.01-win-x64.exe` | 单文件版，无需安装 Python，双击即用 |
| `LLama-Launcher-v0.5.01-win-x64-portable.zip` | 便携版，解压即用 |
| Source code (zip / tar.gz) | 源码 |

---

# LLama 启动器 v0.4.25 发布说明 / Release Notes

## English

### New Features

- **Chat-template support** — a new Advanced row for `--jinja`, thinking effort (`--chat-template-kwargs {"reasoning_effort":"low|medium|high"}`) and `--reasoning-budget`. The model's `tokenizer.chat_template` is auto-detected from the GGUF: a model without a template disables the Jinja checkbox, and a model without `reasoning_effort`/`enable_thinking` disables the effort/reasoning-budget controls. Thinking effort is hard-bound to Jinja and is never sent without `--jinja`.
- **Import launch file** — new button at position 7 plus `Tools → Import launch file (.bat)…`: parse an existing `.bat/.cmd/.ps1/.sh/text` file and apply its `llama-server` parameters (model, mmproj, context, sampling, KV cache, chat template, …) back into the UI. UTF-8/GBK aware; the API key is intentionally not imported.
- **Friendlier residual-process prompt** — the dialog now offers a "don't ask again" checkbox persisted to `config.json`, and Advanced parameters has a new "check residual processes on startup" toggle to re-enable it.
- **Port-in-use suggestion** — when the configured port is occupied, a free port is suggested and, on confirmation, the main-window port is updated automatically (new Advanced toggle).
- **Aspect-ratio ad image** — the right-side image now stretches horizontally only and keeps its original proportions.
- **Launch-file validator** recognizes `--jinja`, `--chat-template-kwargs` and `--reasoning-budget`.

### Improvements

- Advanced parameters gained two rows: chat template (Jinja / thinking effort / reasoning budget) and startup behavior (residual check / port suggestion).

### Downloads

| File | Description |
|------|-------------|
| `LLama-Launcher-v0.4.25-win-x64.exe` | Single-file build — no Python required |
| `LLama-Launcher-v0.4.25-win-x64-portable.zip` | Portable build — extract and run |
| Source code (zip / tar.gz) | Full source |

---

## 中文

### 🆕 新增功能

- **对话模板支持**：高级参数新增一行，支持 `--jinja`、思考强度（`--chat-template-kwargs {"reasoning_effort":"low|medium|high"}`）与推理预算（`--reasoning-budget`）。选择模型后自动检测 GGUF 的 `tokenizer.chat_template`：无模板则禁用 Jinja 勾选；无 `reasoning_effort`/`enable_thinking` 则禁用思考强度与推理预算。思考强度与 Jinja 强绑定，未开 Jinja 不会发送该参数。
- **导入启动文件**：底部 7 号位 + 菜单「工具 → 导入启动文件 (.bat)…」，解析已有 `.bat/.cmd/.ps1/.sh/文本` 文件并把 `llama-server` 参数（模型、视觉模型、上下文、采样、KV 缓存、对话模板等）回填到界面；自动兼容 UTF-8/GBK，API Key 出于安全不导入。
- **残留进程提示优化**：弹窗新增「不再提示」（写入 `config.json`）；高级参数新增「启动时检测残留进程」开关，可随时重新开启。
- **端口占用建议**：端口被占用时建议一个可用端口，确认后自动更新主界面端口号（高级参数新增开关）。
- **广告位图片按比例缩放**：右侧图片仅横向铺满、保持原始比例，不再纵向拉伸。
- **启动文件校验器** 识别 `--jinja`、`--chat-template-kwargs`、`--reasoning-budget`。

### 🔧 改进

- 高级参数区新增两行：对话模板（Jinja / 思考强度 / 推理预算）与启动时行为（残留检测 / 端口建议）。

### 下载

| 文件 | 说明 |
|------|------|
| `LLama-Launcher-v0.4.25-win-x64.exe` | 单文件版，无需安装 Python，双击即用 |
| `LLama-Launcher-v0.4.25-win-x64-portable.zip` | 便携版，解压即用 |
| Source code (zip / tar.gz) | 源码 |

---

# LLama 启动器 v0.3.85 发布说明 / Release Notes

> 版本 / Version: v0.3.85 · 发布日期 / Released: 2026-09-19

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
