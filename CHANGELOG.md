# Changelog

All notable changes to LLama 启动器 / LLama Launcher.

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
