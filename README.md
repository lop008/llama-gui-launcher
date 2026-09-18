# LLama Launcher

A GUI launcher for llama.cpp local large language models. It turns the whole workflow — **pick a model → configure parameters → start the server in the background → monitor resources in real time → connect to Agent tools** — into a one-click experience. No more memorizing long command lines.

**[中文文档 / Chinese](README.zh-CN.md)**

> **Latest release: v0.3.85** — six color themes, a fully redesigned model-download tab, per-row resumable downloads, and a large round of UI polish. See [Release Notes](RELEASE_NOTES.md) and [CHANGELOG](CHANGELOG.md).

## What's New in v0.3.85

- **Six built-in themes** — Dark / Light / Orange / Green / Gray / Brown, defined in `src/themes.py`. All palettes share identical metrics, so switching never changes the layout size.
- **Redesigned Model Download tab** — two-column layout (repositories on the left, files inside the selected repo on the right), three-field search (A organization/author · B model name/version · C auxiliary keyword) with AND/OR matching, per-page count selector, "Load more", and "Open download directory".
- **Per-row file actions** — file name / size / installed / download / progress columns with header-click sorting and **resumable per-file downloads**. Clicking an already-downloaded file sets it as the main model and runs the full follow-up logic.
- **Repository info + operation log** below the two columns, with a draggable splitter.
- **Custom download directory** — defaults to the main page's model directory with a per-repository subfolder.
- **Broader MTP detection** — recognizes `mtp` / `nextn` / `next_n` / `eh_proj` / `shared_head` tensors and `nextn_predict_layers` metadata.
- **UI polish** — default window 1280 × 1280, compact advanced-parameter area, always-visible spin-box arrows, model path in the status bar, enlarged tab labels and group titles, and a horizontally-filled ad slot.
- **Fixes** — no more false "residual process" dialog on startup; exporting a launch file no longer leaves a stray `.ico`; config now persists `custom_tools` / `opencode_workdir` / `last_download_dir`.

## What Problem Does It Solve?

Running local LLMs with llama.cpp usually means dealing with:

- **Complex command lines**: `llama-server.exe -m model -ngl all -c 32768 -n 8192 -fa on ...` — a long list of flags you have to remember
- **Messy model management**: model files scattered across folders, plus vision projectors (mmproj) and half-downloaded files to keep track of
- **Hard-to-control background server**: a console window flashes by, VRAM is not released after a crash, and a runaway/looping model is hard to stop
- **Vision model mismatches**: loading fails when the main model and its mmproj have different embedding dimensions
- **Trouble connecting Agent tools**: opencode, Claude Code, etc. need manual baseURL / API Key setup

This launcher automates and visualizes all of the above: **auto model scanning, visual parameter tuning, hidden-window background startup, real-time resource monitoring, one-click stop, and auto-connection for Agent tools**.

---

## Features

### Model Management
- **Auto scan**: recursively scans all `.gguf` files under the llama directory, skipping incomplete downloads (e.g. `.xltd`)
- **Model list sorting**: by directory + filename ascending (natural sort, default), size descending, or name only
- **Vision model pairing by directory**: after picking a main model, **only mmproj files in the same folder** are listed; auto-selects the matching one with **embedding-dimension consistency checks** — red warning + pre-start interception on mismatch
- **Model info**: reads the GGUF header offline (architecture / context length / quantization / parameter count)

### Parameter Configuration
- **Basic**: listen address, port, context presets (one-click VRAM-based recommendation from 16K to 512K), GPU layers, context length, max prediction tokens
- **Advanced**: CPU threads, batch size, parallel slots, flash attention, **KV cache K / V independent types** (`-ctk` / `-ctv`, e.g. K=q8_0 + V=f16), continuous batching, temperature / top-p / top-k / repeat penalty, sampling presets (Precise / Balanced / Creative), API key, timeout, mlock, mmap, auto-open browser
- **Multi-GPU panel**: detect devices via `llama-server --list-devices`; check 1 card = pin to it, ≥2 cards = split with `-sm` mode / `-ts` tensor-split weights / `-mg` main GPU index
- **MTP (multi-token prediction)**: auto-detects MTP tensors in the selected GGUF (shard-aware; recognizes `mtp` / `nextn` / `next_n` / `eh_proj` / `shared_head` tensors and `nextn_predict_layers` metadata); when present you can enable `--spec-type draft-mtp` speculative decoding for faster generation
- **Context preset ↔ context length link**: picking a preset writes the context value; editing the context value auto-highlights the matching preset (or "Custom")
- **Every parameter has a hover tooltip**; full explanations are in `参数说明.md` (menu: About → Parameter Guide)

### Server & Monitoring
- **Hidden-window background startup**: opens the browser Web UI automatically once `/health` is ready
- **One-click stop**: `taskkill /T` kills the whole process tree (a lifesaver when the model runs away / loops)
- **Crash-proof, VRAM auto-release**: the server process runs inside a Windows Job Object (`KILL_ON_JOB_CLOSE`) — if this app crashes or is force-killed, the system cleans up the llama-server process tree and frees VRAM immediately
- **Real-time status bar**: CPU, memory, VRAM (nvidia-smi), running model, API activity

### Agent Tools
- 4 built-in tools: **opencode** (auto-generates `opencode.json` pointing at the service), **OpenCode desktop** (copies connection info to clipboard), **Claude Code** (launch only, not auto-connected), **llama-server**
- "Open Agent Tool" opens the currently highlighted tool; **the last-selected tool is remembered and highlighted** on next launch
- Opening a tool auto-connects it to the running service; if the service is not running it still opens with a hint

### Model Download & llama.cpp Updates
- **Model download tab** (huggingface.co/unsloth): **two-column layout** (repositories on the left, files inside the selected repo on the right); **three-field search** (A organization/author · B model name/version · C auxiliary keyword) with AND/OR matching; sort by downloads / likes / name / recency; **per-row file table** (name / size / installed / download / progress) with header-click sorting and **resumable per-file downloads** (HTTP Range + `.part`); "Load more" + per-page count; repository info + operation log with a draggable splitter; and a **custom download directory** (defaults to the main page's model directory, one subfolder per repo)
- **Update llama.cpp tab**: pick any GitHub **Release version** (or type a tag) → download the Windows x64 prebuilt zip → **safe install** that only overwrites same-named files in the target dir with automatic `.bak` backups — models, configs and everything else are never touched. Or switch to **branch source mode**: pick any branch (e.g. `main`) and its source zip is downloaded (resumable) into a dedicated `llama.cpp-<branch>` subdirectory of your chosen folder
- **Export command preview as .bat** (Tools menu): save the exact "Command Preview" line to a `.bat` file at any path you choose; also "Export one-click launch (.bat)" with a desktop shortcut

### Usage Statistics (independent window, Tools → Model Stats)
- Per model: open count, usage time, input / output tokens (parsed from llama-server log lines `prompt eval time` / `eval time`)
- Time breakdown by **hour / day / month**, scope filter all / today / last week / this calendar month; CSV export

### Other
- **Remembers last-used parameters** in `config.json`
- **Export / Import config**: `.aic` files (JSON content) for full backup/restore
- **Online model lookup**: queries HuggingFace for the model's intro / downloads / likes (7-day cache, falls back to local info offline)
- **Tray minimize**: closing the window minimizes to the system tray; tray menu shows / starts / stops / quits
- **Log files**: `logs/运行日志-YYYYMMDD.log`, one file per day
- **Six color themes** (Dark / Light / Orange / Green / Gray / Brown): pick from the "🎨 Theme" menu at the bottom-right of the status bar; switching never changes the layout size
- **Customizable icon / ad slot**: put `assets/icon.ico` to change the app icon; `assets/ad.png` fills the 430×40 ad slot at the bottom

---

## Installation

### Option A: Run from source (development / personal use)

**Requirements**
- Windows
- Python 3.9+ (verified on 3.13)
- llama.cpp's `llama-server.exe` and its DLLs (extract from llama.cpp Releases) inside the directory

**Steps**
```bat
cd /d your-launcher-directory
pip install -r requirements.txt
python main.py
```

Dependencies (`requirements.txt`): `PyQt6`, `requests`, `psutil`

### Option B: Run the packaged exe (no Python required)

Download from the [Releases](https://github.com/lop008/llama-gui-launcher/releases) page:

| File | Description |
|------|-------------|
| `LLama启动器-v0.3.85-win-x64.exe` | **Single-file** build (~43 MB) — just double-click. First launch is slower (it unpacks to a temp dir, a few seconds); some antivirus may flag single-file executables — add an exception if needed. |
| `LLama启动器-v0.3.85-win-x64-portable.zip` | **Portable** build — extract and run `LLama启动器-win-x64-portable.exe`; starts faster, no self-extraction. |

Put `llama-server.exe` and its DLLs in the same directory (or set the launcher path in the UI).

---

## Usage

### Quick Start
1. **Set the llama directory**: select the folder containing `llama-server.exe`, click "Refresh Models"
2. **Pick a model**: select the main model; the vision model is auto-paired by directory (a red warning appears on dimension mismatch — switch it or choose "None" to run text-only)
3. **Tune parameters**: default port 8080, listen address `127.0.0.1`; use "Context Preset" for a VRAM-based recommendation; expand "Advanced" as needed
4. **Start**: click "Start Server" → runs in the background without a console window → the browser opens the Web UI at `http://127.0.0.1:8080/` when ready
5. **Monitor**: the status bar shows CPU / memory / VRAM / running model / API activity in real time
6. **Stop**: click "Stop Server" to terminate everything instantly when the model runs away or loops
7. **Connect Agents**: go to the "Agent Tools" tab, select a tool, click "Open Agent Tool" (auto-connects when the service is running)

### Menu Reference
| Menu | Items |
|------|-------|
| Start | Start Server / Stop Server / Exit |
| Tools | Refresh Models / Open Model Directory ｜ Open Web UI / View API Model List ｜ Open Agent Tool ｜ Export Config (.aic) / Import Config (.aic) / Export One-Click Launch (.bat) / **Export Command Preview (.bat)… (choose save path)** / **Model Stats… (independent window)** ｜ Clear Log / Open Log Directory |
| About | Parameter Guide / Developer Info |

---

## Input / Output Examples

### 1. Generated startup command

After clicking "Start Server", the "Command Preview" and log show the **actual command executed**. For example:

```
llama-server.exe -m <your-model-path>
  --mmproj <your-mmproj-path>
  -ngl all -c 32768 -n 8192 -fa on --cont-batching
  --host 127.0.0.1 --port 8080
  -b 2048 -ctk f16 -ctv f16
  --temp 0.80 --top-k 40 --top-p 0.95 --repeat-penalty 1.00
  --timeout 3600 -a gemma-4-31B-it-Q6_K
```

### 2. Startup log (in the "Logs" tab)

```
[防护] Job Object enabled: llama-server will be auto-cleaned if this app exits/crashes, VRAM released immediately
common_params_print_info: verbosity = 3
srv  load_model: loading model '<your-model-path>'
Server ready: http://127.0.0.1:8080
```

### 3. Browser / API endpoints

- Web chat UI: `http://127.0.0.1:8080/`
- OpenAI-compatible API: `http://127.0.0.1:8080/v1`

Test with curl:

```
curl http://127.0.0.1:8080/v1/chat/completions ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"gemma-4-31B-it-Q6_K\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}],\"max_tokens\":64}"
```

Response (abridged):

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "model": "gemma-4-31B-it-Q6_K",
  "choices": [{ "message": { "role": "assistant", "content": "Hello! Nice to meet you..." } }]
}
```

### 4. Agent auto-connection

When the service is running, opening opencode automatically writes `opencode.json` into the llama directory (backing up and merging any existing config):

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

### 5. Config export

"Tools → Export Config" produces `xxx.aic` (JSON content, same structure as `config.json`) that can be restored on another machine with "Import Config".

---

## Directory Structure

```
LLama启动器/
├── main.py                # Entry point
├── requirements.txt       # Dependencies
├── 参数说明.md             # Full parameter documentation (in-app)
├── .gitignore
├── config.json            # Runtime config (auto-generated, contains API key - DO NOT upload)
├── hf_model_cache.json    # HF lookup cache (auto-generated)
├── logs/                  # Runtime logs (auto-generated)
├── assets/
│   ├── icon.ico           # App icon (optional, put here to apply)
│   ├── ad.png             # Bottom ad slot 430×40 (optional)
│   └── donate_qr.jpg      # Donation QR code in About dialog (optional)
├── docs/
│   ├── cover.png          # Release cover image (v0.3.85)
│   └── screenshots/       # UI screenshots used by the README / Release
├── dist/                  # Packaged executables (pyinstaller, not in repo)
└── src/
    ├── main_window.py       # Main window + menu + tray + status bar
    ├── config.py            # Config read/write
    ├── themes.py            # Six color palettes (Dark/Light/Orange/Green/Gray/Brown)
    ├── model_scanner.py     # Model scanning / sorting / mmproj pairing
    ├── gguf_reader.py       # GGUF header parsing + MTP tensor detection
    ├── cmd_builder.py       # Command-line generation (KV K/V, multi-GPU, MTP)
    ├── server.py            # Subprocess / health check / stop / job object
    ├── jobobject.py         # Windows Job Object (auto-cleanup on crash)
    ├── system_monitor.py    # CPU/memory/VRAM/model/API monitoring
    ├── hf_info.py           # HuggingFace model lookup
    ├── hf_browse.py         # HF repo search / file listing (download tab backend)
    ├── hf_download_tab.py   # Model download UI (two-column, three-field search, per-row resume)
    ├── model_downloader.py  # Resumable HTTP downloader (.part + Range)
    ├── llama_updater.py     # llama.cpp releases/branches fetch + safe install
    ├── updater_tab.py       # Update llama.cpp UI (version / branch source)
    ├── usage_stats.py       # Usage stats store (opens/time/tokens, h/d/m buckets)
    ├── stats_dialog.py      # Independent model statistics window
    ├── bat_validator.py     # Static .bat/.cmd/.ps1 launch-script validator
    ├── presets.py           # Context presets / sampling presets
    ├── tools.py             # Agent tool registry & detection
    ├── opencode_launcher.py # Generates opencode.json
    └── about_dialog.py      # Developer info
```

## Screenshots

| | |
|---|---|
| ![Main window](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/main.png) | ![Advanced parameters](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/advanced.png) |
| Main window | Advanced parameters + Multi-GPU |
| ![Model download](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/download.png) | ![llama.cpp updater](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/updater.png) |
| Model download (two-column, resumable) | Update llama.cpp |
| ![Agent tools](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/agent.png) | ![Command preview](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/preview.png) |
| Agent tools | Command preview |

## Developer Info

- Developer: AI创客师
- Bilibili link in "About → Developer Info" (clickable)
- To change: edit the constants at the top of `src/about_dialog.py`

## Roadmap

- [x] Model download channel (HuggingFace, default org `unsloth`; resumable queue + save-dir picker)
- [x] llama.cpp in-app updates (Release versions with safe install; branch source zip download)
- [ ] Model lookup via ModelScope source
