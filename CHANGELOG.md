# Changelog

All notable changes to LLama 启动器 / LLama Launcher.

## [0.5.15] - 2026-11-27

### New Features

- **Speculative decoding** — the old "Enable MTP" checkbox on the Advanced page became a full **Speculative decoding** row under the model selector on the Basic page: a method dropdown (**Off / Auto** plus 12 methods — MTP, DFlash 2, DFlash, DSpark, LiliCorr, EAGLE-3, small-model draft and the four n-gram variants), a colour-coded status label, a **Draft model** dropdown and a **Draft length** spinner (`--spec-draft-n-max`, 0 = engine default). Detection is three-layer and all measured, never guessed: which `--spec-type` values the local `llama-server` actually accepts (parsed from its `--help`), what the selected model supports (GGUF contents: built-in nextn/MTP head, matching draft files nearby) and whether a draft really pairs with the model (base name / architecture). Methods the local engine does not know are greyed out with the reason in the tooltip ("update llama.cpp"), missing drafts say what to download, and mismatches only warn — they never block a launch. `Auto` picks the first currently usable method; if none is usable, **no `--spec-type` is passed at all** and the status bar explains why, so a speculative-decoding mistake can never stop the server from starting.
- **Auto priority editor** — the **Sort** button beside the dropdown opens a dialog listing the methods in the order `Auto` will try them: reorder by dragging an item, with ▲ / ▼ buttons and Alt+↑ / Alt+↓ as equivalents, plus Restore default order. Persisted to `config.json` (`spec_order`); methods you never ordered are appended, so a new release's methods still get tried.
- **Download draft** — a dialog that finds speculative drafts on HuggingFace for the currently selected model: it takes the base model name from the GGUF metadata, prefers official GGUF publishers (ggml-org / unsloth / bartowski), then lists each candidate as method / file / repository / size / notes, and downloads it **into the main model's own folder** (drafts are only paired when they sit next to the model) before re-scanning and selecting it. Repos that publish safetensors only are not offered as fake downloads — instead the dialog prints the exact `convert_hf_to_gguf.py … --target-model-dir …` recipe and where to put the result.
- **Auxiliary files inspector** — a one-line summary under the model row (`Auxiliary files: vision projection 8 · draft head 4 · calibration file 1 (view)`) opens a table of every non-model GGUF in the catalogue with its role, filename, size, folder and which main model it belongs to, and a button to open that folder.
- **Model catalogue role screening** — vision projections (`mmproj`), speculative draft heads and quantization calibration files (`imatrix_*`) no longer pollute the main model dropdown. Roles are decided by GGUF **contents** (tensor names, `general.type`, architecture) with the filename only as a fallback, and anything unreadable is treated as a main model — a helper file may be shown where it should not be, but a real model is never silently hidden. If the saved main model turns out to be a helper file, it is dropped from the list with an explicit notice.
- **ARM64 packages are visible again** — the "Update llama.cpp" page used to filter out every asset whose name contained `arm`, so Windows-on-ARM machines saw an empty list although every llama.cpp release ships four arm64 builds. Both architectures are now listed with the machine's own architecture first (`src/llama_updater.win_assets`).

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
