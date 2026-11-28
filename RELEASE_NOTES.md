# LLama 启动器 发布说明 / Release Notes

> 最新版本 / Latest release: **v0.6.5** · 发布日期 / Released: 2026-11-28

---

# LLama 启动器 v0.6.5 发布说明 / Release Notes

## English

Four rounds of user feedback folded into one release (v0.6.1 - v0.6.4 were never published individually). The headline is a
launch-breaking upstream change handled transparently: llama.cpp 0.4.1 removed `--mlock`, so the
launcher now writes the load-mode flag your build actually understands. Alongside it: an offline
sanity check for your launch scripts with an **opt-in** local-model report, whole-UI font scaling,
real platform/backend filters on the llama.cpp updater page, and **MoE offload presets** that size
`--n-cpu-moe` from your machine *and* the model you actually selected — with dense models no longer
receiving expert flags at all.

### Fixes

- **`--mlock` no longer breaks launches on new llama.cpp** — 0.4.1 replaced `--mlock` / `--mmap` /
  `--no-mmap` / `--direct-io` with `-lm/--load-mode`, so the old spelling returned
  `error: invalid argument` and the server never came up. The launcher reads `llama-server --help`
  (cached per executable, pre-warmed in the background) and emits `-lm mmap+mlock` / `-lm none` /
  `-lm mlock` on new builds, keeping the legacy flags on old ones. `.bat` import understands `-lm`
  too, and the sanity check names the exact replacement — while staying silent on old builds.
- **Two native crashes fixed** — `QComboBox.setItemText()` faulted when the window was rebuilt
  repeatedly; background callbacks could reach a window that was already being destroyed (now a
  window-parented timer, `_closing`-guarded named slots, and monitors stopped only on the real
  exit path, after the "stop the service too?" dialog).
- **"Downloaded only" told the truth again** — the "current version" status used to count as
  downloaded even when no zip was on disk.
- **Non-Windows packages are reachable again** — the updater used to filter assets before the UI
  ever saw them.
- **CPU packages are matched by the CPU filter** — version segments and variant suffixes in names
  like `bin-ubuntu-26.04-s390x` or `bin-android-arm64-snapdragon` were mistaken for backends.
- **Dense models no longer receive MoE expert flags** — configuration survives a model switch, so
  after running a MoE model with "first N layers on CPU", launching the dense Qwen3.8-27B still
  carried `--n-cpu-moe`. The three expert flags are now emitted only when the model really has
  expert weights, measured layer by layer from the GGUF tensor table (multi-shard models summed
  shard by shard); the matching UI controls are greyed out with the reason. If the layout can't be
  read, the explicit user settings are kept rather than dropped.
- **The sanity check crashed on models that store per-layer arrays** — Inkling 2 writes
  `attention.head_count` as a 24-element array; it went straight into arithmetic and raised
  `TypeError`. Array metadata now collapses to the common value, or to the largest entry, so VRAM
  is over-estimated rather than the check falling over.
- **A failed self-update could leave the launcher unopenable** — the swap script was three `move`
  commands with no error checking, so an antivirus quietly eating the freshly downloaded exe meant:
  working exe renamed to `.bak`, second move fails, script still launches a file that isn't there.
  Reproduced with the real script over dummy files. Every step now checks for failure, restores the
  `.bak`, never starts something that may not exist, and explains itself in the status bar on the
  next launch (once only).
- **Self-update downloads were unverified, and portable installs got the wrong package** — the
  download now has to match the size GitHub reports and pass a file-header check, `.part` resumes
  refuse to splice two different releases together, and free disk space is checked first. The
  launcher also detects whether it is a single-file or a folder (`_internal`) install: portable
  upgrades now swap the exe **and** `_internal` from `-portable.zip` while leaving `config.json`,
  logs and stats untouched, instead of dropping the 47 MB single-file build on top.

### New Features

- **Launch-script sanity check** — "Tools → Launch file → Validate launch script" now has a
  **Sanity check** tab next to the line-by-line parse. Fully offline, evaluated against *this*
  machine: removed or unknown flags, duplicates, out-of-range values (threads vs logical cores,
  `-ub` vs `-b`, port), context length vs the model's trained limit, plus VRAM (weights + KV cache
  + compute cache), RAM and disk estimates. If metadata is missing it says so instead of guessing.
- **"Ask the model" — only when you press it** — the health data (machine profile + model
  metadata + parameters, with **API keys stripped**) is sent to the llama-server *already running
  on your machine*; nothing is sent to any external service, the button is disabled while the
  service is stopped, and no model runs unless you click. If it fails, the built-in conclusions
  above remain valid.
- **UI font scaling** — Ctrl + mouse wheel, or Ctrl `+` / `-` / `0`, zooms the whole interface
  from 80% to 180%, fixed pixel metrics included, so scaled-up text still fits. Persisted as
  `ui_scale` in `config.json`; the theme's factory sizes are never overwritten, so a theme switch
  keeps your zoom and Ctrl+0 returns to 100%.
- **Platform and backend filters (updater page)** — "Windows packages only" plus a multi-select
  backend list (CPU / CUDA / Vulkan / ROCm / SYCL / OpenVINO / OpenCL / zDNN), built only from
  backends that actually appear in the loaded list. Within one dimension selections are OR-ed;
  across dimensions they are AND-ed; nothing selected means no limit. Packages for other
  platforms can be downloaded for a second machine, with install disabled and the reason on hover.
- **MoE offload presets** — pick a goal (Auto / All in VRAM / Balanced / Save VRAM / Extreme /
  Long context) and the launcher works out `--n-cpu-moe N` and `--moe-cache-mib` from your actual
  VRAM and RAM **plus the real per-layer expert size of the model you selected**, then prints the
  arithmetic underneath so you can check it. Hardware tiers are inputs to that calculation rather
  than a static option table: the same 24 GiB card wants N=0 for Inkling 2 (14.7 GiB of experts)
  and `--cpu-moe` for Flash-Next (71.7 GiB). Since `--n-cpu-moe` offloads the *first* N layers
  while dynamic quantisation makes upper layers up to twice as heavy per layer, the fit is
  searched from the top down instead of dividing the total by a layer count. Editing mode, N or
  cache by hand returns the chooser to "manual"; changing model or context length recomputes.
  Missing information is reported as missing — never an invented N.
- **Preset dropdowns you can also type into** for predict tokens (`-n`) and batch size (`-b`):
  common steps listed, any number accepted, clamped to the legal range.
- **Clear screen on the run-log tab** — "Clear" and "Open log folder" at the top of the tab.
  Clearing only empties what is displayed; the per-day log files on disk are untouched. The view
  now also holds at most 5000 lines so a long-running service stops eating memory.
- **Micro-batch (`-ub`) + a pre-launch VRAM budget** — `-ub` was never sent by the launcher, yet
  it decides how many tokens actually enter the GPU at once. It has its own field now. *Start* first
  estimates `weights + KV + batch activation buffer` against the VRAM that is really free; when it
  does not fit you get the three numbers plus "apply suggested micro-batch and start" / "start
  anyway" / "cancel" — never a silent rewrite of your settings, and no dialog at all when the VRAM
  size can't be read. The batch term is a measured model (15 points from llama-server's own
  `CUDA0 compute buffer size`, max deviation 3.7%, biased to over-estimate): the same 0.6 GiB
  model needs 58 MiB at `-c 32768 -ub 512 -fa on` and 4.4 GiB at `-c 32768 -ub 2048 -fa off`.

### Improvements

- **Speculative decoding greys out what your model cannot use**, with the reason on hover;
  "needs a draft" stays selectable and is marked `⚠`. A saved mode that does not apply to the
  current model falls back to Auto and explains itself once in the status bar.
- **mmproj auto-pairing prefers F16 > BF16 > F32 > quantised**, and hints when a vision model's
  projector file is present but the field is empty. Inkling 2 is confirmed a vision model — the
  vision tower lives in the projector (`projection_dim=2304` matching the main model's
  `embedding_length`), so `has_clip=False` on the main weights is normal.
- **The command preview became two draggable panes** — a per-flag "flag / what it means" table
  above the raw command line, parsed from the final command text so the explanation always
  matches what runs; unknown flags are labelled unknown rather than invented.
- **All table columns draggable** — auto-filling of leftover width now stops only when you resize
  the fill column itself, not after dragging any column. The fill also happens one event after the
  resize instead of inside the event filter (which ran before `resizeEvent` and measured the
  previous viewport), so a maximized window no longer keeps a blank strip on the right.
- **Updater page** — version table / details / log in one vertical splitter; the action column is
  measured from the buttons so nothing is clipped in any language or zoom level.
- **Tool menu grouped** (model / service & web / launch file / config / logs & stats / font size /
  language); path columns elide in the middle so file names survive; tabs have visible borders
  again (the v0.6.0 theme had removed them).
- 259 interface strings from the four batches translated into all 7 languages; 19 obsolete ones
  removed — every table holds 1199 entries, 0 missing, 0 unused.

### Downloads

| File | Description |
|------|-------------|
| `LLama-Launcher-v0.6.5-win-x64.exe` | Single-file build (x64) — no Python required |
| `LLama-Launcher-v0.6.5-win-x64-portable.zip` | Portable build (x64) — extract and run |
| `LLama-Launcher-v0.6.5-win-arm64.exe` | Single-file build (ARM64, Snapdragon / Windows on ARM) |
| `LLama-Launcher-v0.6.5-win-arm64-portable.zip` | Portable build (ARM64) — extract and run |
| `Arm64.bat` | One-click launcher for ARM64 — put it next to the exe, it always starts the arm64 build |

## 中文

四批用户反馈合并成一个版本发布（v0.6.1–v0.6.4 均未单独发布）。重点是**上游一处会让服务起不来的改动被自动兼容**：
llama.cpp 0.4.1 删掉了 `--mlock`，启动器现在按本机版本写出你这份 llama.cpp 真正认识的加载模式参数。
另外新增：启动文件「合理性体检」（AI 分析必须手点）、界面整体字号缩放、更新页平台与后端筛选、
**MoE「卸载预设」**（按本机显存 + 这个模型每层专家的实际大小算该卸几层，稠密模型不再误收专家参数）。

### 🐛 修复

- **新版 llama.cpp 上 `--mlock` 不再把服务搞崩**：0.4.1 把 `--mlock` / `--mmap` / `--no-mmap` /
  `--direct-io` 合并成 `-lm/--load-mode`，旧写法直接 `error: invalid argument`、服务根本起不来。
  启动器改为读本机 `llama-server --help`（按 exe 缓存、启动后后台预热）决定写法：新版给
  `-lm mmap+mlock` / `-lm none` / `-lm mlock`，旧版仍用 `--mlock` / `--no-mmap`；导入 `.bat`
  时也认识 `-lm`；体检会直接给出替代写法，而本机是旧版时保持沉默，不会推荐一个同样会失败的参数。
- **两处概率性闪退**：`QComboBox.setItemText()` 在反复重建窗口时崩溃（改走 model item 设置文本）；
  后台回调打进正在销毁的界面（残留检测改成挂窗口的定时器、状态栏监控改带 `_closing` 闸门的具名槽、
  关窗只在**真正退出**时停监控且排在「是否同时停止服务」对话框之后，点取消不会把监控停掉）。
- **「仅显示已下载」不再谎报**：以前把「当前版本」也算已下载，但那只代表本机装的正好是这个版本，
  zip 可能早已清理或从别处装的。现在只认硬盘上真实存在的文件。
- **非 Windows 包重新可见**：更新页过去在**取数据阶段**就把非 Windows 包过滤掉了，界面再怎么筛也没用。
- **纯 CPU 包能被「CPU」筛到了**：`bin-ubuntu-26.04-s390x`、`bin-android-arm64-snapdragon`
  这类包名里的版本号段与变体后缀不再被误认成后端名。
- **稠密模型不再收到 MoE 专家参数**：配置是跨模型留存的，跑完 Inkling 2 选了「前 N 层放 CPU」，
  切到稠密的 Qwen3.8-27B 命令行还带着 `--n-cpu-moe`。现在 `--cpu-moe` / `--n-cpu-moe` /
  `--moe-cache-mib` 只在**实测到专家权重**时下发（按 GGUF 张量表逐层累加，多分片逐片求和），
  界面上整套设置同步置灰并说明原因；专家分布读不出时**不猜**，保留用户显式设置的值。
- **体检不再被逐层数组元数据打崩**：Inkling 2 把 `attention.head_count` 写成 24 个元素的数组，
  原样取出参与运算直接抛 `TypeError`。现在数组元素全相同取该值、不全相同取最大值（宁可高估显存）。
- **自升级替换失败不再弄丢程序**：原来那步替换脚本是三条 `move`、**一处失败判断都没有**。新版
  exe 被安全软件隔离（未签名新程序被 Defender 吞掉是常事）时：旧 exe 已被改名成 `.bak`、第二条
  搬的是不存在的文件、脚本还照样去启动它——现象就是「点了升级，软件打不开了」。本机拿真脚本对
  假文件复现过。现在每一步都判 `errorlevel`，失败自动把 `.bak` 改回去、绝不启动不存在的文件，
  下次启动在状态栏说明失败原因（只提醒一次，回滚成功时保留的是**失败原因**而不是笼统一句）。
- **自升级先验货，便携版不再被换成单文件包**：下载要通过与 GitHub 报的大小比对 + 文件头检查
  （exe 查 `MZ`、zip 要能解开），不合格直接删掉重来、根本不进替换流程；`.part` 断点续传会记住
  来源 URL，Release 重传同名包时丢弃重下，不会拼出坏文件；升级前先看磁盘余量。另外启动器现在
  认得自己是**单文件版**还是**便携目录版（exe + `_internal`）**：便携版走 `-portable.zip`，连
  `_internal` 一起换，**你自己的 `config.json` / `logs/` / `stats.json` 一个都不动**，也不会再被
  47 MB 的单文件包盖掉（能跑，但留一堆死文件、启动还更慢）。

### 🆕 新增功能

- **启动文件体检**：「工具 → 启动文件 → 校验启动文件」在原有「逐行解析」旁增加**合理性体检**页签，
  完全离线、按**本机实况**评估：被废弃或不认识的参数、重复设置、取值越界（线程数 vs 逻辑核心、
  `-ub` vs `-b`、端口）、上下文长度是否超出模型训练上限，以及显存（权重 + KV 缓存 + 计算缓存）、
  内存、磁盘余量估算。元数据取不到就如实说取不到，不编数字。
- **「让模型分析」——不点就绝不调用模型**：把体检数据（本机配置 + 模型元数据 + 参数，**已剔除 API Key**）
  交给**本机正在运行**的那个 llama-server 生成分析报告；不访问任何外部服务，服务未运行时按钮不可点。
  分析失败时，上面的内置结论明确仍然有效。
- **界面字号缩放**：在界面任意处 `Ctrl + 滚轮`，或用 `Ctrl` + `+` / `-` / `0`，整体缩放 80%～180%，
  行高、图标、边距等固定像素量一起等比缩放（否则字放大了控件装不下）。缩放值存 `config.json`
  的 `ui_scale`，**不覆盖主题的出厂字号**：换主题仍保持你的缩放，`Ctrl+0` 回到 100%。
- **更新页平台 + 后端筛选**：「仅显示有 Windows 包」复选 + 后端多选下拉（CPU / CUDA / Vulkan / ROCm /
  SYCL / OpenVINO / OpenCL / zDNN），选项只从**当前列表里真实出现过的**后端生成。语义：**同一维度内多选是
  「或」，维度之间是「且」**，后端一个都不勾 = 不限后端。其他平台的包可以为第二台机器下载备用，
  但安装按钮禁用并在悬停时说明原因。
- **MoE「卸载预设」**（高级参数 → MoE 专家行）：选一个目标（自动 / 全放显存 / 平衡 / 省显存 / 极限省显存 /
  长上下文优先），启动器按**本机显存内存 + 这个模型每层专家的实际字节数**算出 `--n-cpu-moe N` 与
  `--moe-cache-mib`，并在下一行把计算过程写出来供复核（显存 × 水位、扣掉非专家权重 / KV / 计算缓存、
  模型专家总量、于是留几层卸几层）。**没有做成「显存档位 × 内存档位」的死表**：同样 24 GiB 显存跑
  Inkling 2（专家 14.7 GiB）该 N=0，跑 Flash-Next（专家 71.7 GiB）只能 `--cpu-moe`，硬件是算法输入。
  又因为 `--n-cpu-moe` 卸的是**前 N 层**而动态量化上层更重（Inkling 2 前 21 层 547 MiB、后 3 层 1033 MiB），
  装载顺序必须从最上层往下连续算，不能拿总量除层数。手动改任一项退回「不套用」，换模型或改上下文后
  同一档自动重算；显存或模型信息取不到就直说取不到，绝不编一个 N。
- **预测 Token / 批大小改成「预设 + 可自定义」下拉**：常用档位（`-1 = 无限输出`、1024～65536 /
  256～8192）一点就填，也能直接敲任意数字，超范围自动钳到边界。
- **运行日志页顶部「清屏 / 打开日志目录」**：清屏**只清界面显示**，磁盘上按天存放的日志文件不动，
  状态栏也会说明；界面另外只保留最近 5000 行，长时间跑服务不再把几十万行日志全吃进内存。
- **微批 `-ub` 进界面 + 启动前显存预算**：启动器以前**根本不下发** `-ub`（只有导入的 bat 才带得上），
  而它才是「一次真正进 GPU 算多少 token」的旋钮。现在它有独立一档；点启动时先按
  `权重 + KV + 批处理激活缓冲` 与**当前可用显存**核算，超了就把三项数字摆出来，并给
  「按建议改微批并启动 / 仍然启动 / 取消」——**绝不静默改你的设置**，取不到显存时不弹窗。
  批处理那项是按本机 15 个实测点建的模式（llama-server 自报的 `CUDA0 compute buffer size`，最大偏差 3.7%，偏保守）：
  同一个 0.6 GiB 模型，`-c 32768 -ub 512 -fa on` 只要 58 MiB，`-c 32768 -ub 2048 -fa off` 要 **4.4 GiB**。

### 🔧 改进

- **投机解码把当前模型用不了的方式置灰**，悬停说明原因（本机不认该取值 / 模型既无对应结构也找不到可用草稿）；
  「缺草稿」保持可选并标 `⚠`（下一个草稿就能用，堵死不划算）。配置里存的方式对当前模型失效时自动回退「自动」，
  并在状态栏一次性说明。界面与命令行共用同一份判定函数，两边不会说法不一。
- **视觉投影自动配对按精度择优**：F16 > BF16 > F32 > 量化（撞上 F32 那份要多占约一倍显存/内存）；
  模型带投影文件却留空时给出提示。实测确认 **Inkling 2 是视觉模型**：视觉塔在外挂 mmproj 里
  （`projection_dim=2304` 与主模型 `embedding_length=2304` 对应），主权重 `has_clip=False` 属正常现象。
- **命令预览改成可拖两栏**：上半「参数拆解 / 目的与意义」逐条解释，下半完整命令行；拆解只解析**最终命令行文本**，
  解释与实际下发永远同源；未收录的参数如实标注而不编造。
- **所有表格列都能拖**：剩余宽度补给「主列」的逻辑改成**只有拖过主列本身才停止补宽**（以前拖任意一列就永久不再铺满）。
  补宽时机也挪到 resize **之后延一帧**：事件过滤器比 `QAbstractScrollArea` 自己的 `resizeEvent` 先跑，
  量到的是上一次的视口宽度，导致窗口最大化后右侧总留一条空白（还多减了一次边框）。
- **更新页布局**：版本表 / 版本信息 / 操作日志放进一个竖向分栏；操作列宽度按按钮实测尺寸计算，任何语言、任何字号都不裁字。
- **工具菜单收进二级**（模型 / 服务与网页 / 启动文件 / 配置 / 日志与统计 / 字号 / 语言）；路径列改中间省略，
  窗口变窄也看得见文件名；页签恢复可见描边（v0.6.0 主题误写 `border: none`）。
- 四批共 259 条新增界面文案全部译入 7 张语言表，并清掉改版失效的 19 条：各表 1199 条，缺失 0、多余 0、占位符一致。

---

# LLama 启动器 v0.6.0 发布说明 / Release Notes

## English

A release about llama.cpp's newest switches: speculative decoding can no longer break a launch, MoE expert offloading is finally exposed, thinking on/off and reasoning effort are separated, Inkling 2 (MoE) is supported end to end, the llama.cpp updater and the HuggingFace download page were rebuilt, and the launcher can update itself.

### New Features

- **Speculative decoding can no longer fail a launch** — a method you explicitly pick is passed to `llama-server` only when it is both supported by your build (`--spec-type` appears in its `--help`) **and** paired with a draft that actually matches the model. Otherwise the launcher emits **no `--spec-type` at all**, the server starts un-accelerated, and the status bar tells you why. All 13 values of a current build are handled (`none`, `draft-mtp`, `draft-dflash`, `draft-dflash2`, `draft-dspark`, `draft-lilicorr`, `draft-eagle3`, `draft-simple`, `ngram-mod`, `ngram-cache`, `ngram-simple`, `ngram-map-k`, `ngram-map-k4v`).
- **Draft matching is now real matching** — vocabulary size, `embedding_length` and the *architecture family* are compared, so DSpark / DFlash / LiliCorr drafts (family `dflash`) and external `<arch>-mtp` heads are no longer rejected as "architecture mismatch"; multi-shard main models are scanned across all shards, so an MTP head in part 3 of 4 is found. `ngram-simple` / `ngram-map-k4v` are correctly reported as needing no draft file.
- **New llama.cpp parameters you can now set from the UI**
  - `--cpu-moe` — keep **all** MoE expert weights on the CPU (biggest VRAM saving, slowest);
  - `--n-cpu-moe N` — keep the experts of the **first N** layers on the CPU, the rest stay on the GPU (the usual MoE fix; raise N until VRAM fits);
  - `--moe-cache-mib N` — GPU cache for CPU-resident expert weights (256–2048 when VRAM has room to spare);
  - `--reasoning on|off|auto` — force / disable / defer thinking, distinct from the effort level;
  - `--chat-template-kwargs {"reasoning_effort":"…"}` — the effort level, only for templates that declare the variable;
  - `--jinja` with a per-model capability probe, and `--spec-type` / `--spec-draft-model` / `--spec-draft-n-max` for speculative decoding.
- **Inkling 2 supported (and configurable on a full GPU)** — `inkling2_loop` is recognised as MoE (128 experts, 8 active per token, 1 048 576-token context), DSpark drafts sitting next to the model are paired automatically with `Q8_0` preferred over `BF16` and legacy `*_Old` files last. Set the expert offloading above and a ~11 GB Inkling runs on a GPU that is already busy. See the Chinese section for a step-by-step recipe.
- **Thinking switch vs. reasoning effort** — "Thinking mode" (`--reasoning`) and "Reasoning effort" (`reasoning_effort`) are two controls now. The effort dropdown is only enabled when the selected model's Jinja template really declares `reasoning_effort`, and its entries are rebuilt from that template (Inkling: `minimal / low / medium / high / xhigh / max`; Qwen3-0.6B and Gemma 4 expose only the on/off switch). A stale `medium` left in `config.json` is cleared rather than sent to a model that cannot use it.
- **llama.cpp updater page rebuilt** — stat cards (current version shown as `1.1.0-dev (b12780)`, latest stable, packages found on disk), a visible segmented filter (All / Stable only / Pre-release only), row checkboxes + select-all + Download selected, and a status column: current / downloaded / available / **no Windows package**. Releases that ship no Windows binaries — llama.cpp `v1.1.0` publishes only `nightly-tag.txt` — stay visible as a labelled row with a link, instead of disappearing from the list.
- **Model download page rebuilt** — organisation/author is an editable combo pre-filled with common publishers (`unsloth` default, plus `ggml-org`, `bartowski`, `Qwen`, …) but free-typed for anything else; the file list is a **folder tree** where checking a folder downloads the whole group, so a 4-shard GGUF is one click; repository info shows the folder layout and a clickable `huggingface.co/<repo>` link.
- **Richer model info** — MoE facts (expert count, experts per token, dense vs MoE), detected thinking capability, a speculative-decoding support table (state / reason / draft path per method) and clickable homepage / HuggingFace-search links.
- **Agent tools are manageable** — Tool / Type / **Path** / Description / Open (path now left of the description, action column narrowed), plus add / edit / delete and "read description from the exe" (`FileDescription` / `ProductName`).
- **The launcher updates itself** — "About → Check for launcher update…" fetches the latest GitHub release, compares versions, downloads the exe for your architecture and swaps it in after exit, then relaunches. Running from source just opens the release page. A silent start-up check only flags a new version in the header.
- **Modern UI** — a new widget kit (cards, segmented controls, badges, stat blocks, empty states) and reworked styles: radio buttons finally have a visible checked state, buttons gained primary / danger / ghost / segment variants, tables, tabs, progress bars, combos, splitters and menus were restyled, and the header card shows version, service state and the detected llama.cpp version.

### Improvements

- 165 new interface strings translated into all 7 languages, and 26 strings orphaned by the rewritten pages removed — the tables match the source exactly (959 keys, 0 missing, 0 unused).
- Updater page size 100 → 30 with tag de-duplication, so paged results can never list a release twice.
- `draft-dflash` also accepts `dflash2` / `dspark` / `lilicorr` drafts, matching upstream's auto-detection note.
- The draft-download dialog is strictly modal and its download buttons no longer react to Enter, so clicks cannot leak through to the page underneath.

### Fixes

- An unusable speculative mode can no longer reach the command line (`--spec-type` omitted → server starts).
- The updater showed a bare `b12780`; it now shows `1.1.0-dev (b12780)`.
- `list_releases(include_prerelease=False)` no longer misuses the asset filter; `tag` / `tag_name` both accepted.
- Model / repository links are clickable (`QTextBrowser`).
- A start-up update check no longer raises if its window closed while the request was in flight.
- **The packaged build ignored your language choice**: `main.py` looked for `config.json` next to `__file__`, which in PyInstaller 6 is the read-only `_internal\` folder, while the real configuration lives next to the exe — so packaged users always got the system language. The frozen build now uses `sys.executable`, the same rule as the main window.

### Downloads

| File | Description |
|------|-------------|
| `LLama-Launcher-v0.6.0-win-x64.exe` | Single-file build (x64) — no Python required |
| `LLama-Launcher-v0.6.0-win-x64-portable.zip` | Portable build (x64) — extract and run |
| `LLama-Launcher-v0.6.0-win-arm64.exe` | Single-file build (ARM64, Snapdragon / Windows on ARM) |
| `LLama-Launcher-v0.6.0-win-arm64-portable.zip` | Portable build (ARM64) — extract and run |
| `Arm64.bat` | One-click launcher for ARM64 — put it next to the exe, it always starts the arm64 build |

## 中文

本次围绕 llama.cpp 的新参数：投机解码不再可能把服务启动搞崩、MoE 专家卸载参数终于进了界面、思考开关与思考强度分开、Inkling 2（MoE）全链路支持、llama.cpp 更新页与模型下载页重做、启动器支持自升级。

### 🆕 新增功能

- **投机解码绝不再拖垮启动** — 明确选中的方式必须「本机 `llama-server` 认识这个 `--spec-type`」且「草稿与主模型真配套」才下发；否则**完全不带 `--spec-type`**，服务照常启动，状态栏说明原因。当前构建的 13 个取值全部覆盖：`none`、`draft-mtp`、`draft-dflash`、`draft-dflash2`、`draft-dspark`、`draft-lilicorr`、`draft-eagle3`、`draft-simple`、`ngram-mod`、`ngram-cache`、`ngram-simple`、`ngram-map-k`、`ngram-map-k4v`。
- **草稿配对改成真配对** — 比较词表大小、`embedding_length` 与**架构族**：DSpark / DFlash / LiliCorr（架构族 `dflash`）与外挂 `<arch>-mtp` 头不再被误判「架构不一致」；多分片主模型跨全部分片扫描，MTP 头在第 3/4 片也能识别；`ngram-simple` / `ngram-map-k4v` 不再误报缺草稿。
- **新增可直接设置的 llama.cpp 参数**
  - `--cpu-moe`：全部 MoE 专家权重放 CPU（最省显存、最慢）；
  - `--n-cpu-moe N`：**前 N 层**的专家放 CPU，其余仍在 GPU（MoE 最常用，N 越大越省显存）；
  - `--moe-cache-mib N`：给驻留在内存里的专家留 N MiB 的 GPU 缓存（显存有富余时 256~2048）；
  - `--reasoning on|off|auto`：强制思考 / 关闭思考 / 交给模板与请求，与「强度」是两件事；
  - `--chat-template-kwargs {"reasoning_effort":"…"}`：思考强度档位，仅对声明了该变量的模板开放；
  - `--jinja`（配合逐模型能力探测）以及投机解码的 `--spec-type` / `--spec-draft-model` / `--spec-draft-n-max`。
- **Inkling 2 支持** — `inkling2_loop` 被识别为 MoE（**128 个专家、每 token 激活 8 个**、上下文 1 048 576），同目录的 `dspark-*` 草稿自动配对，草稿排序优先 `Q8_0`、其次 `BF16`、`*_Old` 旧转换件排最后。配合下面的专家卸载，显存已被占满的卡也能跑起约 11 GB 的 Inkling。详细步骤见本节末尾「Inkling 2 配置指引」。
- **思考开关 ≠ 思考强度** — 「思考模式」对应 `--reasoning`，「思考强度」对应 `reasoning_effort`。只有模型的 Jinja 模板真的声明了 `reasoning_effort` 才启用强度下拉，并按该模板实际支持的取值重建（Inkling：`minimal / low / medium / high / xhigh / max`；Qwen3-0.6B、Gemma 4 只有开关）。旧配置里残留的 `medium` 会被清掉，不会下发给不支持的模型。
- **llama.cpp 更新页重做** — 顶部统计卡（当前版本按 `1.1.0-dev (b12780)` 显示、最新稳定版、磁盘上已下载的包）、**可见的分段筛选**（全部 / 仅稳定 / 仅预发布）、行复选框 + 全选 + 下载选中、递归扫描下载目录，状态列直接写「当前版本 / 已下载 / 可下载 / 无 Windows 包」。没发 Windows 二进制包的 Release（llama.cpp `v1.1.0` 只有 `nightly-tag.txt`）不再整条消失，而是保留一行标注并给出 Release 链接。
- **模型下载页重做** — 组织/作者改成**可输入 + 常用作者下拉**（默认 `unsloth`，预置 `ggml-org`、`bartowski`、`Qwen` 等，其他作者直接输入）；右侧文件列表改成**目录树**，勾选文件夹即整组下载，4 分片模型不用一片片点；仓库信息追加目录清单与可点击的 `huggingface.co/<仓库>` 链接。
- **模型信息更丰富** — 除基础 GGUF 信息外，显示 MoE 事实（专家数 / 每 token 激活数 / 稠密还是 MoE）、思考能力、投机解码支持表（每种方式的状态、原因、草稿路径），以及可点击的模型主页 / HuggingFace 搜索链接。
- **Agent 工具可管理** — 列顺序改成 工具 / 类型 / **路径** / 描述 / 打开（路径移到描述左侧、「打开」列收窄），并支持添加、编辑、删除，以及「从 exe 版本信息自动读取描述」（`FileDescription` / `ProductName`）。
- **启动器自升级** — 菜单「关于 → 检查启动器更新…」读取 GitHub 最新 Release、比较版本、按本机架构下载 exe，退出后由独立脚本替换并自动重启；源码运行模式只打开 Release 页面。启动时的静默检查只在标题栏/状态栏提示，不会自动下载。
- **界面整体升级** — 新增组件库（卡片、分段控件、状态徽章、统计块、空状态），QSS 重做：单选按钮终于有可见选中态，按钮新增 primary / danger / ghost / segment 变体，表格、页签、进度条、下拉框、分栏、菜单统一风格；顶部标题卡显示版本、服务状态与检测到的 llama.cpp 版本。

### 🔧 改进

- 165 条新增界面字符串全部译入 7 张语言表，并清掉改版后失效的 26 条：与源码严格对齐（959 个 key，缺失 0、多余 0）。
- 更新页每页 100 → 30 并按 tag 去重，翻页不会重复列出同一个版本。
- `draft-dflash` 同时接受 `dflash2` / `dspark` / `lilicorr` 草稿，与上游「draft-dflash 自动识别变体」的说明一致。
- 「下载草稿」对话框改成严格模态（打开期间禁用主窗口），下载按钮不再响应回车，鼠标点击不会穿透到下方下载页。

### 🐛 修复

- 不可用的投机解码方式不再进入命令行（改为省略 `--spec-type`，服务正常启动）。
- 更新页只显示 `b12780` 的问题：现在显示 `1.1.0-dev (b12780)`。
- `list_releases(include_prerelease=False)` 误用资产过滤参数；`tag` / `tag_name` 两种字段都兼容。
- 模型 / 仓库里的链接可以点了（改用 `QTextBrowser`）。
- 启动时的静默更新检查，窗口已关闭时不再因信号投递报错。
- **打包版不再忽略语言设置**：`main.py` 原先按 `__file__` 找 `config.json`，而 PyInstaller 6 的入口脚本在只读的 `_internal\` 里、用户配置在 exe 同级目录，导致打包版永远读不到 `language`、固定跟随系统语言。现在冻结态按 `sys.executable` 定位（便携版实测：`language=en` 生效，标题显示 `LLama Launcher v0.6.0`）。

### Inkling 2 配置指引

**1. 先更新 llama.cpp**：Inkling 2 需要 **b12780 及以后** 的构建。打开「更新 llama.cpp」页，选 `b12780`（或更高的 nightly）安装。注意 `v1.1.0` 那个 tag 只发布了 `nightly-tag.txt`，没有 Windows 包，页面会标成「无 Windows 包」，不要选它。

**2. 放文件**：主模型与草稿放**同一个目录**（草稿只有和主模型同目录才会被配对），例如：

```
D:\models\Inkling-2\
├─ Inkling-2-Mini-UD-IQ3_XXS.gguf          ← 主模型
└─ dspark-Inkling-2-Mini-Q8_0.gguf         ← DSpark 草稿（优先 Q8_0）
```

**3. 基本页**：选中主模型 → 投机解码选 `DSpark`，草稿下拉会自动选中 `dspark-*-Q8_0.gguf`；「草稿长度」保持 0 用引擎默认即可。模型状态那行应显示 `✔ DSpark：已找到配套草稿`。

**4. 高级参数 → MoE 专家**（关键，决定显存够不够）：

| 显存情况 | 设置 |
|---|---|
| 显存充裕（≥20 GB 空闲） | 「不额外处理」，`-ngl all` |
| 已被其他模型占掉一半 | 「前 N 层放 CPU」，N 从 **8** 起，不够就 12 / 16 / 24 |
| 几乎没显存了 | 「全部放 CPU（`--cpu-moe`）」，再配合把上下文调小 |
| 用 `--n-cpu-moe` 后速度明显掉 | 「专家缓存(MiB)」设 **512~2048** |

MoE 的专家权重默认跟着 `-ngl all` 一起进显存，这就是「怎么全进显存了」的原因；`--n-cpu-moe` 是唯一能按层把专家挪出显存的开关。

**5. 上下文与思考**：Inkling 元数据上下文是 1 048 576，但按显存设更实际（32K/64K 起步）。勾上 Jinja 模板 → 思考模式选 `auto` 或 `on` → 思考强度可选 `minimal / low / medium / high / xhigh / max`。

**6. 最终命令大致长这样**（「命令预览」里可以看到实际下发的）：

```bat
llama-server.exe -m Inkling-2-Mini-UD-IQ3_XXS.gguf ^
  --spec-type draft-dspark --spec-draft-model dspark-Inkling-2-Mini-Q8_0.gguf ^
  -ngl all --n-cpu-moe 12 --moe-cache-mib 1024 ^
  -c 32768 --jinja --reasoning auto ^
  --chat-template-kwargs "{\"reasoning_effort\":\"medium\"}" ^
  --port 8080 --metrics
```

**7. 还是起不来？** 依次试：把上下文减半 → `-ngl` 从 `all` 降到 20 → `--n-cpu-moe` 加大 → 换更小量化（IQ3_XXS 已经很小）。启动失败时状态栏与日志会给出最后 20 行原始输出。

### 下载

| 文件 | 说明 |
|------|------|
| `LLama-Launcher-v0.6.0-win-x64.exe` | 单文件版（x64），无需安装 Python，双击即用 |
| `LLama-Launcher-v0.6.0-win-x64-portable.zip` | 便携版（x64），解压即用 |
| `LLama-Launcher-v0.6.0-win-arm64.exe` | 单文件版（ARM64，骁龙本 / Windows on ARM） |
| `LLama-Launcher-v0.6.0-win-arm64-portable.zip` | 便携版（ARM64），解压即用 |
| `Arm64.bat` | ARM64 一键启动脚本，与 exe 同目录双击即可（优先 arm64） |

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
| `Arm64.bat` | One-click launcher for ARM64 — put it next to the exe, it always starts the arm64 build |

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
| `Arm64.bat` | ARM64 一键启动脚本，与 exe 同目录双击即可（永远优先挑 arm64 包） |

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
