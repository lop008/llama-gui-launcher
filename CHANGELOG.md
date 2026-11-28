# Changelog

All notable changes to LLama 启动器 / LLama Launcher.
## [0.6.2] - 2026-11-28

Three feedback rounds folded into one release (v0.6.1 was never published): a launch-script sanity
check with an opt-in local-model report, UI font scaling, platform/backend filters on the updater
page, MoE offload presets that size `--n-cpu-moe` from this machine and this model, plus a
launch-breaking upstream change (`--mlock` removed) that is now handled per build.

### Fixes

- **A launch could die with `error: invalid argument` because of `--mlock` / `--no-mmap`** —
  llama.cpp 0.4.1 (2026-09) removed `--mlock`, `--mmap`, `--no-mmap` and `--direct-io`, merging
  them into `-lm/--load-mode` (`auto` / `none` / `mmap` / `mlock` / `mmap+mlock` / `dio`). The
  launcher no longer hard-codes the old spelling: it reads the local `llama-server --help`
  (cached per executable, warmed up in the background a few seconds after start) and emits
  `-lm mmap+mlock` / `-lm none` / `-lm mlock` on new builds while keeping `--mlock` / `--no-mmap`
  on old ones. Importing a `.bat` reads `-lm` values back into the checkboxes, and the sanity
  check tells you the exact replacement for a flag your build no longer knows — but stays quiet
  when your build is the old one, so it can't recommend a flag that would also fail.
- **Two native crashes** — `QComboBox.setItemText()` faulted (`0xC0000005`) when the window was
  rebuilt repeatedly (multi-language stress in the suite); text now goes through
  `combo.model().item(i).setText()`. And background callbacks could land in a window that was
  already being destroyed: the residual-process check uses a `QTimer` parented to the window
  instead of a parentless `QTimer.singleShot`, status-bar monitor slots are named slots guarded
  by `_closing` (they are emitted from the probe thread), and `closeEvent` stops the monitor and
  usage timers on the real exit path only — after the "stop the service too?" dialog, so
  cancelling keeps monitoring.
- **"Downloaded only" listed packages that were not on disk** — the status "current version" was
  counted as downloaded, but that only means the installed llama.cpp happens to be that build
  (the zip may have been cleaned up, or the build came from elsewhere). Now only files that
  actually exist count.
- **Non-Windows packages were invisible no matter what you set** — the updater filtered assets
  at fetch time (`win_assets`), so nothing downstream could un-filter them. The list now fetches
  every package and filters in the UI.
- **`ubuntu-26.04-s390x` / `android-arm64-snapdragon` were classified as an unknown backend** —
  distro version segments and variant suffixes are no longer mistaken for a backend name, so
  plain CPU packages are matched by the "CPU" filter instead of falling into "other".
- **Dense models no longer receive MoE expert flags** — `--cpu-moe` / `--n-cpu-moe` /
  `--moe-cache-mib` only looked at the saved configuration, and configuration survives a model
  switch: after running Inkling 2 with "first N layers on CPU", launching the dense
  Qwen3.8-27B (`expert_count=0`) still carried `--n-cpu-moe`. The three flags are now emitted only
  when the model really has expert weights, measured layer by layer from the GGUF tensor table
  (multi-shard models read shard by shard, since each shard's table lists only its own tensors).
  When the layout cannot be read at all, the user's explicit settings are kept rather than
  silently dropped.
- **The sanity check crashed on models that store per-layer arrays** — Inkling 2 writes
  `attention.head_count` as an array (24 identical entries), which was passed straight into
  arithmetic and raised `TypeError`. Array metadata now collapses to that value when every entry
  agrees, or to the largest entry — better to over-estimate VRAM needs than to under-estimate.
- **A failed self-update could leave the launcher unopenable** — the swap script was three `move`
  commands with no error checking: if the freshly downloaded unsigned exe got quarantined by
  antivirus in the meantime (routine), the script had already renamed the working exe to `.bak`,
  then moved a file that no longer existed and still tried to start it. Reproduced on this machine
  with the real script over dummy files: the user's entry point was simply gone. Every step now
  checks `errorlevel`, any failure restores the `.bak`, nothing is started that may not exist, and
  the result code is written for the next launch to explain in the status bar (once). Rollback
  keeps the *reason* code rather than overwriting it with a generic "restored".
- **The download was never verified, and resume could splice two releases together** — the GitHub
  asset size was available and unused, and a `.part` from a re-uploaded release of the same name
  would be appended to, producing a corrupt exe that then hit the bug above. Downloads are now
  checked against the reported size plus a file-header check (`MZ` / a readable zip), and `.part`
  files record their source URL: a different URL, or more bytes than expected, forces a re-download.
  Disk space is checked before starting (a portable package needs roughly 3×: zip + unpacked deps).
- **Portable installs were replaced by the single-file build** — asset picking always preferred
  `.exe`, so a folder-based install (exe + `_internal`) got the 47 MB single-file build dropped on
  it: it runs, but leaves `_internal` as tens of MB of dead weight and starts slower. The launcher
  now detects its own install type (`install_kind()`) and a portable folder upgrades via
  `-portable.zip`, replacing the exe **and** `_internal` while leaving your `config.json`, `logs/`
  and `stats.json` alone. If a release only ships one flavour, the dialog says so instead of
  swapping silently. The zip's Chinese top-level folder name is not trusted — PyInstaller does not
  set the UTF-8 flag, so `zipfile` returns mojibake; entries are mapped by "ends with .exe" and
  "below `_internal/`" instead.

### New Features

- **Launch-script sanity check** — "Tools → Launch file → Validate launch script" gained a second
  tab, **Sanity check**, running entirely offline against *this machine*: removed/renamed flags,
  unknown flags, duplicate settings, out-of-range values (threads vs logical cores, `-ub` vs
  `-b`, port), context length vs the model's trained limit, and estimates for VRAM (weights +
  KV cache + compute cache), RAM and free disk. Missing metadata is reported as missing — no
  invented numbers.
- **Opt-in "Ask the model" report** — one button sends the health data (machine profile + model
  metadata + parameters, **API keys stripped**) to the llama-server that is *already running on
  this machine* and renders its analysis. It is disabled while the service is stopped, no model
  is ever called unless you click, and no external service is used. If the call fails, the
  built-in table above is explicitly still valid.
- **UI font scaling** — Ctrl + mouse wheel anywhere in the window, or Ctrl + `+` / `-` / `0`,
  scales the entire interface between 80% and 180%, fixed pixel metrics (row heights, icons,
  margins) included. The ratio is stored in `config.json` (`ui_scale`) and never overwrites the
  theme's factory sizes, so switching themes keeps your zoom and Ctrl+0 returns to 100%.
- **Platform and backend filters on the updater page** — a "Windows packages only" checkbox plus
  a multi-select backend list (CPU / CUDA / Vulkan / ROCm / SYCL / OpenVINO / OpenCL / zDNN)
  populated only from backends that actually appear in the loaded list. Semantics: multiple
  selections within one dimension are OR-ed, different dimensions are AND-ed, and selecting no
  backend means no backend limit. Non-Windows packages can still be downloaded for a second
  machine but the install control is disabled with a tooltip explaining why.
- **MoE offload presets** — the MoE row gained a goal chooser (Auto / All in VRAM / Balanced /
  Save VRAM / Extreme / Long context). Choosing one computes `--n-cpu-moe N` and
  `--moe-cache-mib` from this machine's VRAM and RAM **plus the real per-layer expert size of the
  selected model**, and the line underneath spells out the arithmetic: VRAM × watermark, minus
  non-expert weights, KV cache and compute cache, versus the model's expert total. Hardware tiers
  are deliberately inputs to the algorithm rather than a static matrix of options — the same
  24 GiB card wants N=0 for Inkling 2 (14.7 GiB of experts) and `--cpu-moe` for Flash-Next
  (71.7 GiB). Because `--n-cpu-moe` offloads the *first* N layers while dynamic quantisation makes
  the upper layers up to twice as heavy per layer (Inkling 2: 547 MiB for 21 layers, 1033 MiB for
  the last 3), the fit is searched greedily from the top down instead of dividing by layer count.
  Editing any of the three controls returns the chooser to "manual, nothing applied"; switching
  model or context length recomputes the selected preset. Dense models grey the whole group out
  with the reason. If VRAM or the model layout can't be read, it says so instead of inventing an N.
- **Editable preset dropdowns for predict tokens and batch size** — `-n` and `-b` became
  type-or-choose controls (`src/ui/kit.py:NumberCombo`, same shape as `-ngl`): common steps in the
  list (`-1 = unlimited output`, 1024 … 65536; 256 … 8192), any number typed directly, clamped to
  the valid range, and half-typed input never fires a change.
- **Clear screen on the run-log tab** — "Clear" and "Open log folder" buttons at the top of the tab
  instead of a buried menu item. Clearing affects only what is displayed; the per-day log files on
  disk are untouched, and the status bar says so. The widget also keeps at most 5000 lines, so a
  long-running service no longer grows memory by holding every line in the view.
- **Micro-batch (`-ub`) exposed, plus a pre-launch VRAM budget** — the launcher never sent `-ub`
  before (only an imported `.bat` could bring it in), yet it is the knob that decides how many
  tokens actually enter the GPU at once. It now has its own field next to the batch size. Pressing
  *Start* first estimates `weights + KV + batch activation buffer` against the VRAM that is
  **actually free**: when the estimate doesn't fit, a dialog shows the three numbers and offers
  "apply suggested micro-batch and start", "start anyway" or "cancel" — it never silently rewrites
  your settings, and it is skipped entirely when the VRAM size cannot be read.
- **The batch activation buffer is modelled from measurements** — a **Batch peak** item in the
  sanity check built on `launch_advisor.attn_scratch_gib()`, whose coefficients come from 15 points
  measured on this machine by reading llama-server's own `CUDA0 compute buffer size`: the same
  0.6 GiB model spends 58 MiB at `-c 32768 -ub 512 -fa on` but **4.4 GiB** at
  `-c 32768 -ub 2048 -fa off`. Max deviation 3.7%, deliberately biased to over-estimate, and the
  text names the knob to turn: lower `-ub`, turn `-fa on`, lower `-c`, or quantise the KV cache.

### Improvements

- **Speculative decoding now greys out what your model can't use** — the build not knowing the
  `--spec-type` value, or the model having neither the structure nor a usable draft, makes the
  entry un-selectable with the reason on hover; "needs a draft" stays selectable but is marked
  `⚠`, since downloading the draft is all it takes. A saved mode that no longer applies to the
  current model falls back to Auto with a one-off status-bar note. The UI and the command line
  share one predicate (`spec_decode.spec_selectable()`), so they can never disagree.
- **mmproj auto-pairing prefers the cheapest sensible precision** — F16 > BF16 > F32 > quantised
  (picking a stray F32 projector cost roughly twice the memory), and a hint appears when a vision
  model has a projector file next to it while the field is left empty. Inkling 2 is confirmed a
  vision model: `clip.has_vision_encoder=True` and `projection_dim=2304` matching the main model's
  `embedding_length=2304`, with `has_clip=False` on the main weights — the vision tower lives in
  the projector file, which is normal.
- **The command preview became two draggable panes** — a per-flag "flag / what it means" table
  above the raw command line (new `src/cmd_explainer.py`). It parses only the final command
  line, so the explanation can never drift from what actually gets launched; unknown flags are
  labelled as unknown instead of being made up; Windows quoting, embedded escaped quotes,
  boolean flags and negative values are tokenised correctly.
- **Every table column is draggable** (`src/ui/kit.py:ColumnResizer`) — leftover viewport width
  is still given to the main column, but the auto-fill now stops only when you drag *that*
  column; previously dragging any column permanently disabled it and left the table short. The
  fill itself also moved to one event *after* the resize: the event filter used to run before
  `QAbstractScrollArea`'s own `resizeEvent`, so it measured the previous viewport and a maximized
  window kept a blank strip on the right (it also subtracted a frame border that `viewport()` had
  already excluded).
- **Updater page layout** — version table, details and log live in one vertical splitter you can
  rebalance; the action column is measured from the buttons' own `sizeHint` (+28 px, floor
  330 px) so "Download / Install" is never clipped in any language or zoom level.
- **Tool menu grouped** into 模型 / 服务与网页 / 启动文件 / 配置 / 日志与统计 / 字号 / 语言,
  and the duplicate top-level Language menu was dropped.
- **Path columns elide in the middle**, so a narrow window still shows the file name instead of
  the directory tail.
- **Tabs are visibly tabs** — the v0.6.0 `brown` theme had `QTabBar::tab { border: none }`,
  leaving only a background tint. Unselected tabs have a 1 px border, 3 px offset and rounded
  corners again; the selected one gets a 2 px accent border and bold text.
- 259 interface strings from the four batches translated into all 7 languages (zh-TW / en / ja /
  ko / ru / es / fr); 19 strings obsoleted by the reworked pages were removed. All tables hold
  1199 entries with 0 missing, 0 unused and identical placeholders.

## [0.6.0] - 2026-11-27

A feature release built around llama.cpp's newest switches: speculative decoding can no
longer break a launch, MoE expert offloading and the thinking/reasoning-effort split are now
exposed, the llama.cpp updater and the HuggingFace download page were rebuilt, the launcher
can update itself, and Inkling 2 (MoE) is fully supported — including a documented way to keep
it out of a full GPU.

### New Features

- **Speculative decoding is now launch-safe (P0)** — a method you explicitly selected is only
  passed to `llama-server` when detection says `state=ok` **and** the paired draft is
  `valid=true`. Otherwise the launcher drops `--spec-type` entirely, starts the server
  un-accelerated and explains why in the status bar. Previously a saved `spec_mode=mtp` on a
  model without an MTP head produced `failed to create MTP context` and the server never came up.
  All 13 `--spec-type` values of a current build are handled
  (`none`, `draft-mtp`, `draft-dflash`, `draft-dflash2`, `draft-dspark`, `draft-lilicorr`,
  `draft-eagle3`, `draft-simple`, `ngram-mod`, `ngram-cache`, `ngram-simple`, `ngram-map-k`,
  `ngram-map-k4v`); `ngram-simple` / `ngram-map-k4v` are correctly reported as needing no draft.
- **Draft matching rewritten (no more false "architecture mismatch")** — `draft_matches_model()`
  now compares what actually matters: vocabulary size, `embedding_length` and the
  **architecture family**. Draft families (`dflash` / `dflash2` /
  `dspark` / `lilicorr` / `eagle3`) and external heads (`<arch>-mtp`) are allowed to differ from
  the main model's architecture, so DSpark drafts for Inkling and an external `qwen4exp-mtp`
  head are no longer rejected. Multi-shard main models are probed across **all** shards
  (`probe_model_gguf()`), so an MTP head living in shard 3/4 is detected.
- **MoE expert offloading** — new "MoE experts" row on the Advanced page drives
  `--cpu-moe` (all experts on CPU), `--n-cpu-moe N` (first N layers' experts on CPU — the usual
  fix) and `--moe-cache-mib N` (GPU cache for CPU-resident experts). This is the answer to
  "`-ngl all` pushed every expert into VRAM".
- **Inkling 2 support** — Inkling's `inkling2_loop` architecture is recognised as MoE
  (128 experts, 8 active per token, 1 048 576-token context in the released Mini checkpoints),
  its `dspark-*` drafts (arch `dflash`) now pair automatically, and the draft list prefers the
  smaller `Q8_0` draft over `BF16` and pushes `*_Old` legacy conversions last. Requires
  llama.cpp ≥ b12780 — the built-in updater lists those builds, see below.
- **Thinking switch vs. reasoning effort, properly separated** — a new "Thinking mode" dropdown
  maps to `--reasoning on|off|auto`, and a separate "Reasoning effort" dropdown emits
  `--chat-template-kwargs {"reasoning_effort": "…"}`. The effort dropdown is only enabled when
  the model's own Jinja template really declares `reasoning_effort`, and its entries are
  rebuilt from the values that template accepts (e.g. Inkling's
  `minimal/low/medium/high/xhigh/max`); a stale `medium` left in `config.json` for a model that
  has no such variable is cleared instead of being silently sent to the server.
- **llama.cpp updater page rebuilt** — stat cards (current version incl. the real
  `1.1.0-dev (b12780)` string, latest stable, packages found on disk), a visible segmented
  filter (All / Stable only / Pre-release only), row checkboxes + select-all + "Download
  selected", a recursive scan of the download folder for already-downloaded packages, and a
  status column that says current / downloaded / available / **no Windows package**. Releases
  that ship no Windows binaries (llama.cpp `v1.1.0` ships only `nightly-tag.txt`) are kept
  visible as a labelled placeholder row with a link to the release, instead of vanishing.
- **Model download page rebuilt** — organisation/author is now an editable combo with common
  publishers (`unsloth` default, `ggml-org`, `bartowski`, `Qwen`, …); the file list is a
  **folder tree** where checking a folder downloads the whole group (multi-shard GGUFs need one
  click instead of four); repository info gained the folder listing and a clickable
  `huggingface.co/<repo>` link.
- **Richer model info** — beyond the GGUF basics the page now shows MoE facts (expert count,
  experts per token, dense vs MoE), the detected thinking capability, a speculative-decoding
  support table (state / reason / draft path per method), and clickable model-homepage /
  HuggingFace-search links rendered in a `QTextBrowser`.
- **Agent tool management** — column order is now Tool / Type / Path / Description / Open with a
  stretchy description and a narrow action column; add, edit and delete are wired up (built-in
  tools are hidden, not erased), and descriptions can be filled automatically from a PE
  executable's `FileDescription` / `ProductName`. Custom entries persist in `custom_tools`.
- **Launcher self-update** — "About → Check for launcher update…" reads the latest GitHub
  release, compares versions, downloads the exe matching the machine's architecture and swaps it
  in after exit via a detached script, then relaunches. Running from source only opens the
  release page. A silent start-up check (opt-out on the Advanced page) just flags the new
  version in the title bar / status bar.
- **Modern UI kit** — new `src/ui/kit.py` (`Card`, `SectionHeader`, `Badge`, `StatCard`,
  `SegmentedControl`, `EmptyState`) plus reworked QSS: radio buttons finally have a visible
  checked state, buttons gained primary / danger / ghost / segment variants, and tables, tabs,
  progress bars, combos, splitters and menus share one modern look. The header card shows the
  version, a one-line pitch, service state and the detected llama.cpp version.

### Improvements

- i18n kept exhaustive: 165 new UI strings translated into all 7 locale tables
  (en / zh_tw / ja / ko / ru / es / fr) and 26 strings orphaned by this release's rewritten
  pages removed — the tables match the source exactly (959 keys, 0 missing, 0 unused,
  placeholders / line breaks / HTML tags verified entry by entry).
- Updater page size 100 → 30 with tag de-duplication, so paged GitHub responses can never
  append the same release twice.
- `draft-dflash` also accepts `dflash2` / `dspark` / `lilicorr` drafts, matching upstream's note
  that draft-dflash auto-detects those variants.
- The draft dialog is a strict application-modal window (main window disabled while it is open)
  and download buttons set `autoDefault(False)`, so Enter/clicks cannot leak through to the
  download page underneath.
- About dialog now links the GitHub repository next to the Bilibili page.

### Fixes

- An unusable speculative mode can no longer be emitted (`--spec-type` omitted → server starts).
- Version display shows `1.1.0-dev (b12780)` rather than a bare build number, which read as
  "not 1.1.0".
- `list_releases(include_prerelease=False)` no longer misuses `exclude_assets`; pre-releases are
  filtered locally; `tag_name` (API) and `tag` (parsed) are both accepted.
- Links in model / repository info are clickable (`QTextBrowser` instead of `QTextEdit`).
- A start-up update check whose window had been destroyed no longer raises on signal delivery.
- **The packaged build ignored the saved language** — `main.py` located `config.json` via
  `__file__`, which in PyInstaller 6 lives in the read-only `_internal\` directory while the
  user's configuration sits next to the exe. Packaged users were always served the system
  language. The frozen build now resolves the base directory from `sys.executable`, the same
  rule `MainWindow` uses (verified: `language=en` next to the portable exe now starts English).

### Testing

- New _test_v06.py — draft pairing (architecture family / vocab / embedding), thinking
  capability detection, MoE and --reasoning argument emission, self-update version compare,
  asset selection and the frozen-build language bootstrap (19 checks).
- logic / roles / specargs / draft / arm / layout / pill / gui / edge suites pass; live checks
  confirmed the updater lists `v1.1.0` as "no Windows package", the folder tree groups and
  downloads correctly, `Inkling-2-Mini` + `dspark-*-Q8_0` resolves to
  `--spec-type draft-dspark`, and a `spec_mode=mtp` config on a model without MTP emits nothing.

## [0.5.15] - 2026-11-27

### New Features

- **Speculative decoding** — the old "Enable MTP" checkbox on the Advanced page became a full **Speculative decoding** row under the model selector on the Basic page: a method dropdown (**Off / Auto** plus 12 methods — MTP, DFlash 2, DFlash, DSpark, LiliCorr, EAGLE-3, small-model draft and the four n-gram variants), a colour-coded status label, a **Draft model** dropdown and a **Draft length** spinner (`--spec-draft-n-max`, 0 = engine default). Detection is three-layer and all measured, never guessed: which `--spec-type` values the local `llama-server` actually accepts (parsed from its `--help`), what the selected model supports (GGUF contents: built-in nextn/MTP head, matching draft files nearby) and whether a draft really pairs with the model (base name / architecture). Methods the local engine does not know are greyed out with the reason in the tooltip ("update llama.cpp"), missing drafts say what to download, and mismatches only warn — they never block a launch. `Auto` picks the first currently usable method; if none is usable, **no `--spec-type` is passed at all** and the status bar explains why, so a speculative-decoding mistake can never stop the server from starting.
- **Auto priority editor** — the **Sort** button beside the dropdown opens a dialog listing the methods in the order `Auto` will try them: reorder by dragging an item, with ▲ / ▼ buttons and Alt+↑ / Alt+↓ as equivalents, plus Restore default order. Persisted to `config.json` (`spec_order`); methods you never ordered are appended, so a new release's methods still get tried.
- **Download draft** — a dialog that finds speculative drafts on HuggingFace for the currently selected model: it takes the base model name from the GGUF metadata, prefers official GGUF publishers (ggml-org / unsloth / bartowski), then lists each candidate as method / file / repository / size / notes, and downloads it **into the main model's own folder** (drafts are only paired when they sit next to the model) before re-scanning and selecting it. Repos that publish safetensors only are not offered as fake downloads — instead the dialog prints the exact `convert_hf_to_gguf.py … --target-model-dir …` recipe and where to put the result.
- **Auxiliary files inspector** — a one-line summary under the model row (`Auxiliary files: vision projection 8 · draft head 4 · calibration file 1 (view)`) opens a table of every non-model GGUF in the catalogue with its role, filename, size, folder and which main model it belongs to, and a button to open that folder.
- **Model catalogue role screening** — vision projections (`mmproj`), speculative draft heads and quantization calibration files (`imatrix_*`) no longer pollute the main model dropdown. Roles are decided by GGUF **contents** (tensor names, `general.type`, architecture) with the filename only as a fallback, and anything unreadable is treated as a main model — a helper file may be shown where it should not be, but a real model is never silently hidden. If the saved main model turns out to be a helper file, it is dropped from the list with an explicit notice.
- **ARM64 packages are visible again** — the "Update llama.cpp" page used to filter out every asset whose name contained `arm`, so Windows-on-ARM machines saw an empty list although every llama.cpp release ships four arm64 builds. Both architectures are now listed with the machine's own architecture first (`src/llama_updater.win_assets`).
- **`Arm64.bat` one-click launcher** — an ARM64 counterpart to `一键启动.bat`: double-click it next to the exe and it looks for `LLama*arm64*.exe` first, then the extracted `*arm64-portable*` folder, then anything else that looks like the launcher, and finally any Python with PyQt6 (installing the requirements into `.venv` first if needed). `一键启动.bat` in turn now tries `LLama*win-x64*.exe` before the generic patterns, because since this release both architectures can sit in one folder and `arm64` sorts before `x64`, which used to hand an x64 machine the wrong binary. Both scripts are covered by a suite that runs them for real with dummy exes and checks which file each one picks.

### Improvements

- **Main window split into modules** — `src/main_window.py` went from 3338 to ~500 lines: widgets, workers, page layouts, GPU probing, model probing, launch flow, launch-file I/O, agent tools, tray pill, app preferences, config I/O and the About menu moved into `src/ui/*` mixins. Pure code motion with no behaviour change (member inventory and cross-class name collisions verified), one commit per group.
- **i18n kept exhaustive** — 93 new strings translated into all 7 tables (en / zh_tw / ja / ko / ru / es / fr) and the 7 strings left over from the retired MTP checkbox removed, so the tables match the source exactly (820 keys, 0 missing, 0 unused, placeholders and mnemonics verified).
- Two tooltips that still told users to drag items inside the dropdown were rewritten to point at the Sort dialog instead — the dropdown cannot start an internal drag, so the old wording described an action with no effect.

### Fixes

- **Queued downloads are no longer silently dropped** — `ModelDownloader.enqueue()` only appended to the queue when nothing was downloading, so clicking Download on a second file while one was in flight did nothing at all, with no message. Tasks are now always queued and the worker thread is started only when needed (regression-tested with three queued tasks, the last two enqueued mid-download).
- **No `--spec-type` without its draft** — every method that requires an external draft model omits the flag entirely when the file is absent, instead of handing llama-server a path it cannot open.
- **Russian translation table loads again** — the last entry of `src/locales/ru.py` had no trailing comma; the file failed to parse, which meant Russian users were silently served Simplified Chinese. The maintenance tooling now normalises trailing commas, and the loader reports the failure reason (`i18n.failed_languages()`) instead of failing quietly.
- **Residual-process detection works on Chinese Windows** — `find_llama_server_processes()` runs `tasklist`, which on a Chinese system writes "信息: 没有运行的任务…" (GBK) to stdout when nothing matches; with `text=True` and no encoding, Python's internal reader thread raised `UnicodeDecodeError`, `stdout` came back `None` and the check returned nothing — i.e. the "leftover llama-server processes" warning never fired in exactly the case where the command prints localised text. Every text-decoded subprocess call in the app now specifies `encoding`/`errors`, and a static check in the logic suite fails the build if a new one forgets it.

### Testing

- New suites wired into the single serial entry point (`_test_all.py`): role screening of the model catalogue (59 checks, including a real config pointing at a helper file), the speculative-decoding parameter layer (26 checks), draft download candidate ranking / destination / conversion hint / queue regression (35 checks), an opt-in online smoke test that only HEADs a draft URL and skips cleanly when HuggingFace is unreachable, and the ARM64 asset-selection regression against real llama.cpp release asset names.
- Drag-to-reorder is verified with synthetic mouse events: the implementation deliberately avoids `QDrag` (on Windows it enters an OLE modal loop that scripted events cannot reach, which would make the feature untestable) and avoids `takeItem()` / `rowAt()` during event dispatch, both of which take the whole process down with `0xC0000409`.

## [0.5.14] - 2026-11-26

### Fixes

- **Launch-file validator no longer dies on an illegal port** — a script containing `--port 99999` / `--port 0` reached a raw `socket.bind()`, which raises `OverflowError` (not an `OSError`), so "Validate launch file" aborted with an unhandled exception instead of reporting a problem. The port is now range-checked first and reported as `✘ --port out of the valid range (1-65535)`, and the probe socket is guarded so it can neither leak nor raise when it cannot be created. The new message was added to all 7 translation tables, keeping the 8 languages key-aligned (734 keys each).
- **Data Statistics survives corrupt `stats.json`** — a single malformed entry (a model record that is not an object, or string / `null` / `NaN` field values) used to raise `TypeError` / `AttributeError` when opening the Data Statistics window, and again from the 5-second usage timer while a server was running. Malformed entries are now skipped when reading (the rest of the statistics still work) and are rebuilt into a valid record automatically on the next write; numeric fields are coerced defensively.

### Improvements

- **Silent i18n fallback is now observable** — if a language table fails to load in a packaged build (missing module, syntax error, empty or non-dict table), the UI used to fall back to Simplified Chinese with no trace anywhere. Each table is now loaded individually with the reason written to stderr, and the new `i18n.failed_languages()` returns `{language-code: reason}` for diagnostics or a UI notice.

### Testing

- Added end-to-end suites that really start `llama-server` (with `Qwen3-0.6B-Q8_0`, 0.65 GB) and drive the launcher through: window assembly, model scan, GGUF info, MTP and chat-template detection, 6 themes, tab reordering, port-occupied → port suggestion, config export/import, interface rebuild in all 8 languages; the full OpenAI surface (`/health`, `/props`, `/slots`, `/tokenize`, `/metrics`, `/v1/models`, non-streaming and streaming `/v1/chat/completions`, legacy `/completion`, 4xx on a broken request body); API-key auth (401 without a bearer token, 200 with); Job Object protection plus watchdog cleanup after an external process kill; exported `.bat` files executed for real; HTTPS with a generated self-signed certificate (verified client accepts, strict client rejects) and LAN sharing on `0.0.0.0`; pill tok/s, VRAM and busy-slot readings during live generation; and robustness against broken config / model / stats data and residual processes.
- The suites run serially from a single development entry point and print a pass matrix, so a full regression is one command.
- Fixed three stale local test scripts that asserted hardcoded model paths and shard counts (they reported false failures after models were re-downloaded with a different number of shards); shard count is now derived from the filename and fixtures are created in a temp directory.

## [0.5.13] - 2026-11-08

### New Features

- **Multilingual UI** — new "Language" menu with 8 UI languages (Simplified Chinese built-in; 繁體中文 / English / 日本語 / 한국어 / Русский / Español / Français shipped as translation tables in `src/locales/`, ~730 strings each) plus "Follow system language" which auto-matches the OS language on first launch. Switching prompts a confirmed restart and persists to `config.json` (`language`). Lightweight engine in `src/i18n.py` uses the Chinese source text as the lookup key (missing translations fall back to Chinese), `main.py` bootstraps i18n before any UI import, and all language modules are bundled into the packaged exe.

### Improvements

- Bottom action buttons and the theme button now use minimum widths instead of fixed widths — long Russian / French labels are no longer clipped and windows auto-widen.
- Version centralization: `__version__` in `src/__init__.py` is the single source of truth; the Windows version resource for all three build specs is generated at PyInstaller build time from it (hand-maintained `version_info.txt` / `version_info_portable.txt` removed).

### Fixes

- Fixed a native crash (`0xC0000409`) while scanning tools: a loop variable `t` shadowed the `t()` translator inside a Qt slot callback.
- Fixed swapped Korean translations for the "Browse…" and "Dark" entries.

## [0.5.01] - 2026-11-07

### New Features

- **Tray hover pill** — after minimizing to the tray, a 30 px always-on-top capsule stays above the taskbar showing the app icon, **LLama.cpp**, live output speed in tok/s and a status dot. Hover or click to expand a data card (speed, CPU %, memory, GPU load %, VRAM, API busy slots, model name); system stats (CPU / memory / VRAM / GPU) are shown even while the server is idle. Drag to move (position remembered), double-click to restore the main window, right-click for a menu (open / start / stop / hide / quit, start·stop auto-disabled by service state). Theme-aware and can be turned off from Advanced parameters.
- **Live output speed** — new tok/s readout derived by diffing the llama-server `/metrics` generated/predicted counters, with an automatic fallback that parses the latest `eval time` log line when `/metrics` is unavailable (returns to 0 about 8 s after generation ends). Also adds GPU core utilization and API busy-slot count.
- **HTTPS + LAN sharing** — an "Enable HTTPS" toggle generates a self-signed key/cert into `certs/` (via `cryptography`, lazy-loaded) and wires `--ssl-key-file` / `--ssl-cert-file` through the command builder, health checks, browser URLs and opencode config. A "LAN sharing" toggle sets the host to `0.0.0.0` and shows the reachable `http(s)://<local-ip>:<port>` address. Self-signed requests skip verification locally.
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

## [0.4.25] - 2026-09-20

### New Features

- **Chat-template support** — new advanced row for `--jinja`, thinking effort (`--chat-template-kwargs {"reasoning_effort":"low|medium|high"}`) and `--reasoning-budget`. The model's `tokenizer.chat_template` is auto-detected from the GGUF: models without a template disable the Jinja checkbox, and models without `reasoning_effort`/`enable_thinking` disable the effort/reasoning-budget controls. Thinking effort is hard-bound to Jinja (not sent without `--jinja`).
- **Import launch file** — new button at position 7 (and menu `Tools → Import launch file (.bat)…`): parse an existing `.bat/.cmd/.ps1/.sh/text` file and apply its `llama-server` parameters (model, mmproj, context, sampling, KV cache, chat template, …) back into the UI. Handles UTF-8/GBK.
- **Residual-process prompt improved** — the dialog now has a "don't ask again" checkbox persisted to `config.json`, with a new "check residual processes on startup" toggle in Advanced parameters to re-enable it.
- **Port-in-use suggestion** — when the configured port is occupied, suggest a free port and update the main-window port automatically after confirmation (new Advanced toggle).
- **Ad image scales by width** — the right-side image now keeps its aspect ratio (no more vertical stretching).
- **Launch-file validator** recognizes `--jinja`, `--chat-template-kwargs` and `--reasoning-budget`.

### Improvements

- Advanced parameters gained two rows: chat template (Jinja / thinking effort / reasoning budget) and startup behavior (residual check / port suggestion).

## [0.3.85] - 2026-09-19

### New Features

- **Multi-theme color schemes** — Independent `src/themes.py` with 6 palettes: Dark, Light, Orange, Green, Gray, Brown. All themes share identical metrics, so switching never changes the layout size. Light theme uses darker borders for clear separators.
- **Redesigned Model Download tab** — Two-column layout (left: repositories, right: files inside the selected repo). Three-field search (A organization/author, B model name/version, C auxiliary keyword) with AND/OR matching; per-page count selector; Load more; Open download directory.
- **File table with per-row actions** — File name / size / installed / download / progress columns; header-click sorting; resumable per-file downloads. Clicking an already-downloaded file sets it as the main model and runs the full follow-up logic.
- **Repository info + operation log** — Below the two columns, with a draggable splitter to adjust the ratio. "Last updated" now populated (HF `full=true`).
- **Custom download directory** — Defaults to the main page's model directory, with a per-repository subfolder.
- **MTP detection broadened** — Recognizes `mtp` / `nextn` / `next_n` / `eh_proj` / `shared_head` tensors and `nextn_predict_layers` metadata; MTP-capable models can enable it, and detection misses no longer force-disable the checkbox.
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

## [0.2.0] - 2026-07-19

### New Features

- **HuggingFace Model Download Tab** — Browse, search, and download `.gguf` models from huggingface.co (default org: `unsloth`). Supports sorting by downloads/likes/name/recency, multi-select queue, resumable downloads (HTTP Range + `.part`), and user-chosen save directory.
- **llama.cpp In-App Updater** — Download any GitHub Release version or branch source zip. Safe install mode only overwrites same-named files with automatic `.bak` backups; models and configs are never touched. Branch source mode downloads into a dedicated `llama.cpp-<branch>` subdirectory.
- **Usage Statistics Window** (Tools → Model Stats) — Per-model open count, usage time, input/output tokens parsed from llama-server logs. Time breakdown by hour/day/month with scope filters; CSV export.
- **KV Cache Quantization** — Independent K/V cache types (`-ctk` / `-ctv`) supporting quantized formats (e.g. `q4_0`, `q8_0`, `f16`) to reduce VRAM usage.
- **MTP Multi-Token Prediction** — Auto-detects MTP tensors in GGUF files (shard-aware); enables `--spec-type draft-mtp` speculative decoding when available.
- **Multi-GPU Panel** — Device detection via `llama-server --list-devices`; single-card pinning, split mode (`-sm`), tensor-split weights (`-ts`), and main GPU index (`-mg`).
- **Context Presets with VRAM Recommendation** — One-click context length presets (16K–512K) based on available VRAM; two-way binding with the context length field.
- **Sampling Presets** — Precise / Balanced / Creative one-click sampling parameter sets.
- **Flash Attention & Continuous Batching Toggles** — `-fa on/off` and `--cont-batching` controls in advanced parameters.
- **Tray Minimize** — Closing the window minimizes to system tray; tray menu supports show/start/stop/quit.
- **Dark / Light Theme** — Toggle via light-bulb button in status bar.
- **Export Command Preview as .bat** — Save the exact generated command line to a `.bat` file at any path.
- **Config Export / Import (.aic)** — Full backup and restore of all settings as a portable JSON-based file.
- **Online Model Lookup** — Queries HuggingFace for model intro/downloads/likes (7-day cache, offline fallback).
- **BAT Validator** — Validates exported `.bat` files before execution.

### Improvements

- Vision model pairing now shows embedding-dimension consistency check with red warning and pre-start interception on mismatch.
- Model list natural sorting (directory + filename) by default; size-descending and name-only options available.
- Agent tool selection is remembered across sessions; last-highlighted tool auto-restored.
- Log files organized per-day: `logs/运行日志-YYYYMMDD.log`.
- Customizable app icon (`assets/icon.ico`) and ad slot (`assets/ad.png`, 430×40).

### Technical

- Windows Job Object (`KILL_ON_JOB_CLOSE`) ensures llama-server process tree is cleaned up on crash or force-kill, immediately freeing VRAM.
- GGUF header parser reads architecture, context length, quantization format, and parameter count offline.
- Resumable HTTP downloader with `.part` temp files and Range request support.

---

## [0.1.3] - 2026-07 (earlier)

### Features (cumulative through 0.1.x)

- Core GUI launcher for llama.cpp with model scanning, parameter configuration, background server management
- Hidden-window startup with auto browser open on `/health` ready
- One-click stop via `taskkill /T` process tree kill
- Real-time status bar: CPU, memory, VRAM (nvidia-smi), running model, API activity
- Agent tool integration: opencode, OpenCode desktop, Claude Code, llama-server
- GGUF header parsing for offline model info display
- Config persistence in `config.json`
