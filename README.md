# LLama Launcher

A GUI launcher for llama.cpp local large language models. It turns the whole workflow — **pick a model → configure parameters → start the server in the background → monitor resources in real time → connect to Agent tools** — into a one-click experience. No more memorizing long command lines.

**[中文文档 / Chinese](README.zh-CN.md)**

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
- **Vision model pairing by directory**: auto-selects the `mmproj` in the same folder as the main model, with **embedding-dimension consistency checks** — red warning + pre-start interception on mismatch
- **Model info**: reads the GGUF header offline (architecture / context length / quantization / parameter count)

### Parameter Configuration
- **Basic**: listen address, port, context presets (one-click VRAM-based recommendation from 16K to 512K), GPU layers, context length, max prediction tokens
- **Advanced**: CPU threads, batch size, parallel slots, flash attention, KV cache type, continuous batching, temperature / top-p / top-k / repeat penalty, sampling presets (Precise / Balanced / Creative), API key, timeout, mlock, mmap, auto-open browser
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

### Other
- **Remembers last-used parameters** in `config.json`
- **Export / Import config**: `.aic` files (JSON content) for full backup/restore
- **Online model lookup**: queries HuggingFace for the model's intro / downloads / likes (7-day cache, falls back to local info offline)
- **Tray minimize**: closing the window minimizes to the system tray; tray menu shows / starts / stops / quits
- **Log files**: `logs/运行日志-YYYYMMDD.log`, one file per day
- **Dark/Light theme**: toggle with the light-bulb button at the bottom-right of the status bar
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

### Option B: Run the packaged exe

- Use `dist\LLama启动器.exe` (single file, ~39 MB) — **no Python required**, just double-click
- First launch is slower (it unpacks to a temp directory, a few seconds); some antivirus may flag single-file executables — add an exception if needed

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
| Tools | Refresh Models / Open Model Directory ｜ Open Web UI / View API Model List ｜ Open Agent Tool ｜ Export Config (.aic) / Import Config (.aic) ｜ Clear Log / Open Log Directory |
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
├── dist/LLama启动器.exe    # Packaged executable (built with pyinstaller)
└── src/
    ├── main_window.py       # Main window + menu + tray + status bar
    ├── config.py            # Config read/write
    ├── model_scanner.py     # Model scanning / mmproj pairing
    ├── gguf_reader.py       # GGUF header parsing
    ├── cmd_builder.py       # Command-line generation
    ├── server.py            # Subprocess / health check / stop / job object
    ├── jobobject.py         # Windows Job Object (auto-cleanup on crash)
    ├── system_monitor.py    # CPU/memory/VRAM/model/API monitoring
    ├── hf_info.py           # HuggingFace model lookup
    ├── presets.py           # Context presets / sampling presets
    ├── tools.py             # Agent tool registry & detection
    ├── opencode_launcher.py # Generates opencode.json
    └── about_dialog.py      # Developer info
```

## Developer Info

- Developer: AI创客师
- Bilibili link in "About → Developer Info" (clickable)
- To change: edit the constants at the top of `src/about_dialog.py`

## Roadmap

- [ ] Model download channel (HuggingFace / ModelScope)
- [ ] Model lookup via ModelScope source
