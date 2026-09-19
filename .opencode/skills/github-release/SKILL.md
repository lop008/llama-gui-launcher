---
name: github-release
description: Use ONLY when the user explicitly asks to release/publish a new version to GitHub, or explicitly asks for the release/publish workflow (version bump, packaging, GitHub Release, upload) of the LLama 万能启动器 / llama-gui-launcher. Do not trigger for unrelated edits. Triggers include 发版, 发布新版本, 上传 GitHub, 打包发布, release, version bump, gh release.
---

# GitHub 发版与推广 Skill（LLama 万能启动器）

本 Skill 固化了「改版本号 → 更新文档 → 最小化打包 → 提交推送 → 创建 Release → 推广」的完整流程，
保证每次发版**逻辑统一、可复用**。所有命令以本仓库根目录（含 `.git`）为工作目录。

## 0. 仓库固定事实

| 项目 | 值 |
|------|----|
| 仓库 | `lop008/llama-gui-launcher` |
| 默认分支 | `main` |
| 版本号格式 | `0.4.25`（三段）；tag / 文件名用 `v0.4.25` |
| 本机代理 | `http://127.0.0.1:7897`（按需改） |
| Token | 环境变量 `GH_TOKEN`（需 **write** 权限；fine-grained PAT 需 Contents + Releases 写权限） |
| 打包工具 | PyInstaller（在 `.venv` 中），spec 文件为本地构建定义 |
| 资产命名（统一 ASCII） | `LLama-Launcher-vX.Y.Z-win-x64.exe`、`LLama-Launcher-vX.Y.Z-win-x64-portable.zip` |
| 封面命名 | `docs/cover-vX.Y.Z.png`（每个版本一张，首图） |
| 正文命名 | `docs/release_body_vX.Y.Z.md` |

关键路径：

```
src/__init__.py            # __version__（程序内版本号，唯一权威）
version_info.txt           # 单文件版 exe 的 Windows 版本资源
version_info_portable.txt  # 便携版 exe 的 Windows 版本资源
CHANGELOG.md               # 累积式，最新版本置顶
RELEASE_NOTES.md           # 累积式，最新版本置顶（中英）
README.md / README.zh-CN.md# 双语 README，更新「最新版本」指针与 What's New
参数说明.md                 # 面向用户的参数/按钮说明
docs/cover-vX.Y.Z.png      # Release 首图（版本功能说明图）
docs/release_body_vX.Y.Z.md# Release 正文
docs/screenshots/*.png     # 各界面截图
release/                   # 版本化资产（.gitignore，不入源码库）
dist/                      # PyInstaller 产物（.gitignore）
```

## 1. 只上传关键文件（隐私保护）

**原则：源码 + 文档 + 封面/截图 入库；本地隐私、模型、打包产物、凭据一律不入库。**

以下内容**绝不提交**（多数已在 `.gitignore`，务必复核）：

- 配置 / 凭据：`config.json`、`*.aic`、`hf_model_cache.json`、`stats.json`
- 模型：`*.gguf`、`*.xltd`、`Qwen3.8-27B-GGUF/`
- 打包 / 运行产物：`dist/`、`build/`、`release/`、`logs/`、`LLama*-win-x64.exe`、`LLama*-win-x64-portable.zip`
- 环境 / IDE：`.venv/`、`__pycache__/`、`*.pyc`、`.idea/`、`.vscode/`
- 本地隐私图片：`assets/icon.ico`、`assets/donate_qr.*`、`assets/ad.png`、`assets/原始*.png`、`docs/参数说明.html`
- 本地脚本 / 笔记：`_test_*.py`、`_layout_screenshot.png`、`_probe*.tar*`、`_push_*.py`、`_publish_release.ps1`、`后续版本功能开发.txt`、`新建 文本文档.txt`

> ⚠️ `assets/icon.ico` / `assets/ad.png` 虽被忽略，但 **PyInstaller 打包时需要它们本地存在**——不要为了打包而解除忽略，只需保证本机文件在。

**提交前自检**（推荐每次发版都跑）：

```powershell
# 1) 看将要提交什么
git status --short

# 2) 列出已跟踪文件，人工确认无隐私
git ls-files

# 3) 用本 Skill 自带脚本一键自检（版本一致性 + 隐私 + 必填文件）
.venv\Scripts\python.exe .opencode\skills\github-release\scripts\preflight.py 0.4.25
```

## 2. 版本号同步（一步到位）

运行本 Skill 的脚本，自动同步 3 个文件：

```powershell
.venv\Scripts\python.exe .opencode\skills\github-release\scripts\bump_version.py 0.4.25
```

手动同步清单（脚本已覆盖）：

1. `src/__init__.py` → `__version__ = "0.4.25"`
2. `version_info.txt` → `filevers=(0, 4, 25, 0)`、`prodvers=(0, 4, 25, 0)`、`FileVersion`/`ProductVersion` = `0.4.25`
3. `version_info_portable.txt` → 同上

> 注意：`filevers` 用逗号分段四元组 `(0, 4, 25, 0)`；字符串版本用 `0.4.25`。

## 3. 更新文档（中英双语）

按顺序更新，**中英都要改**：

1. **`CHANGELOG.md`**：在 `All notable changes...` 之后、上一版本之前，插入
   `## [0.4.25] - YYYY-MM-DD`，分 `### New Features` / `### Improvements` / `### Fixes`。
2. **`RELEASE_NOTES.md`**：在顶部指针下方插入新版本块（`## English` + `## 中文`），保留历史版本。
3. **`README.md` / `README.zh-CN.md`**：
   - 更新 `> **Latest release: vX.Y.Z**` / `> **最新版本：vX.Y.Z**` 指针；
   - 替换 `## What's New in vX.Y.Z` / `## 最新版本 vX.Y.Z 更新` 列表（英文一份、中文一份）。
4. **`参数说明.md`**：为新功能/新按钮补充章节；若按钮位号变化，同步更新。
5. **`docs/screenshots/README.txt`**：更新版本号与截图清单（有新界面时补图）。

**刷新界面截图**（有 UI 变化时，用默认 Windows 平台渲染，勿用 offscreen）：

```powershell
# 全部刷新（main + advanced）
.venv\Scripts\python.exe .opencode\skills\github-release\scripts\capture_screenshots.py --out docs/screenshots
# 只刷某一个
.venv\Scripts\python.exe .opencode\skills\github-release\scripts\capture_screenshots.py --out docs/screenshots --only advanced
```

## 4. 最小化打包

先确保本机存在：`assets/icon.ico`、`assets/ad.png`（本地隐私文件，被 gitignore）。

```powershell
# 单文件版（无 Python 依赖，双击即用）
.venv\Scripts\python.exe -m PyInstaller "LLama启动器-win-x64.spec" --noconfirm --clean

# 便携版（解压即用）
.venv\Scripts\python.exe -m PyInstaller "LLama启动器-win-x64-portable.spec" --noconfirm --clean
```

> spec 文件名含中文；若终端乱码，用 `python -c "import os;[print(f) for f in os.listdir('.') if f.endswith('.spec')]"` 查看真实名。

最小化要点（已固化在 spec）：

- `excludes=['huggingface_hub','modelscope','modelscope_hub','tqdm','hf_transfer']`（体积与依赖最小化）
- `upx=True`（进一步压缩）
- `datas` 只打包 `assets` 与 `参数说明.md`，不带其它杂物
- `console=False`（无黑窗口）
- `version='version_info*.txt'`、`icon='assets\\icon.ico'`（版本信息与图标）
- 单文件 spec 用 `EXE(pyz, a.binaries, a.datas, ...)`；便携版用 `EXE(exclude_binaries=True)` + `COLLECT`

**若 spec 缺失**（旧版本未入库时）：用 `pyinstaller --onefile --windowed --icon assets/icon.ico --name "LLama启动器-win-x64" main.py` 生成后再补齐上述 excludes。

## 5. 生成版本化 Release 资产

产物在 `dist/`，重命名为统一 ASCII 名并放入 `release/`（`release/` 已 gitignore）：

```powershell
New-Item -ItemType Directory -Force release | Out-Null
$v = "0.4.25"

# 单文件版
Copy-Item "dist\LLama启动器-win-x64.exe" "release\LLama-Launcher-v$v-win-x64.exe" -Force

# 便携版：把 dist 下的便携目录压成 zip
Compress-Archive -Path "dist\LLama启动器-win-x64-portable\*" `
  -DestinationPath "release\LLama-Launcher-v$v-win-x64-portable.zip" -Force
```

> 注意：便携目录**内部内容**打包（用 `\*`），这样解压即得程序文件而非多一层目录。

## 6. 封面 + Release 正文（统一结构）

**首图 = 版本功能说明图**（`docs/cover-vX.Y.Z.png`），后续为界面截图。结构固定，复制模板：
`.opencode/skills/github-release/templates/release_body_template.md`。

正文 `docs/release_body_vX.Y.Z.md` 固定结构：

1. **第一行 = 封面图** `cover-vX.Y.Z.png`（版本功能说明图）
2. 标题 + 中英一句话简介
3. `### 本次更新 / What's New in vX.Y.Z`（emoji + 一句话要点）
4. `### 主要功能 / Features`
5. `### 截图 / Screenshots`（新版本界面截图）
6. `### 下载 / Downloads`（表格，文件名与资产**完全一致**）
7. `### 关于 / About`

图片统一用绝对地址：

```
https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/...
```

**封面生成**（推荐用自带脚本，风格统一，1280×640）：

```powershell
.venv\Scripts\python.exe .opencode\skills\github-release\scripts\make_cover.py `
  --version 0.4.25 --out docs/cover-v0.4.25.png `
  --heading "本次更新 / What's New" `
  --bullet "对话模板：Jinja / 思考强度 / 推理预算" `
  --bullet "导入启动文件：解析 .bat 回填参数" `
  --bullet "残留进程提示：不再提示 + 端口占用建议" `
  --bullet "广告位图片按比例缩放（不再纵向拉伸）" `
  --bullet "启动文件校验器识别新参数"
```

> 也可用设计工具手工制作：新界面截图 + 版本号 + 3~5 个新功能关键词拼成横向 banner。
> ⚠️ 脚本**不要**设 `QT_QPA_PLATFORM=offscreen`（离屏平台没有字体，中文会变成方块）；用默认 Windows 平台即可（不显示窗口）。

## 7. 提交 + 打 tag + 推送

优先用 git 直推（配置代理与 token）：

```powershell
git add -A
git commit -m "release: v0.4.25 - <一句话概述>"

git tag v0.4.25

$pushUrl = "https://x-access-token:$env:GH_TOKEN@github.com/lop008/llama-gui-launcher.git"
git -c credential.helper= -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push $pushUrl main:main
git -c credential.helper= -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push $pushUrl "refs/tags/v0.4.25:refs/tags/v0.4.25"
```

> 无 git 凭据 / 网络受限时的兜底：本仓库曾用 Git Data API 脚本 `_push_commit.py`（本地、不入库）直接上传 blob/tree/commit，以及 `_publish_release.ps1` 一键发布。二者含本地路径与用法，属本地工具，**不要提交**。

## 8. 创建 GitHub Release

```powershell
$v = "0.4.25"
gh release create "v$v" --repo lop008/llama-gui-launcher --verify-tag --latest `
  --title "LLama 万能启动器 v$v" `
  --notes-file "docs\release_body_v$v.md" `
  "release\LLama-Launcher-v$v-win-x64.exe" `
  "release\LLama-Launcher-v$v-win-x64-portable.zip"
```

## 9. 验证

```powershell
gh release view "v0.4.25" --repo lop008/llama-gui-launcher
```

人工确认：① 首图是版本功能图；② 两个资产名带正确版本号；③ 标题/正文中英正常；④ 下载链接可点。

---

## 10. GitHub 推广清单（发版之外还能做什么）

**仓库设置**
- **About**：英文 description（含 `llama.cpp` / `GGUF` / `local LLM` / `GUI launcher` 关键词）+ 官网/截图链接。
- **Topics**（Settings → Topics）：`llama-cpp` `gguf` `local-llm` `llm` `gui` `launcher` `pyqt6` `qwen` `qwen3` `windows` `cuda` `text-generation` `ai` `machine-learning` `llama` `openai-api` `llm-server` `desktop-app`。
  - 一键命令：`gh repo edit lop008/llama-gui-launcher --add-topic llama-cpp,gguf,...`（配合 `$env:GH_TOKEN` 使用）
  - ⚠️ 权限：**fine-grained PAT 需要 Administration: Read and write**，否则返回 `403 Resource not accessible by personal access token`；**classic PAT 勾选 `public_repo` 即可**（推荐，最简单）。
  - 也可完全不用 token，直接在网页 **Settings → Topics** 手动粘贴。
- **Social preview**（Settings → Social preview）：上传 `docs/cover-vX.Y.Z.png`。**只能网页设置（无公开 API）**。
- **README 徽章**：release / stars / license / platform / python（shields.io），已内置在 `README.md` 与 `README.zh-CN.md` 顶部。

**README 增强**
- 顶部徽章：stars / latest release / license / platform / python 版本（shields.io）。
- 首屏放**动图/GIF**（启动→选模型→点启动→浏览器打开），比静态图更吸引人。
- 提供 `一键启动.bat` 说明、快速上手 3 步、常见问题 FAQ。

**社区与内容**
- 开启 **Discussions**（问答/想法），降低 issue 噪音。
- **Issue 模板 / PR 模板 / CONTRIBUTING.md / CODE_OF_CONDUCT.md**。
- 每次发版写清 What's New（本 Skill 已固化），保持 **SemVer** 节奏。
- 可选 **GitHub Actions**：tag 推送时自动构建并上传 release 资产（Windows runner + PyInstaller），实现"打 tag 即发版"。
- 多平台分发与引流：HuggingFace（Model/Space）、Bilibili/YouTube 演示视频、Reddit `r/LocalLLaMA`、X/Twitter、中文社区（V2EX、少数派、即刻、B站）。
- 提交到 Awesome 列表：`awesome-llama`、`awesome-local-llm`、`awesome-llama.cpp` 等（按各列表规范提 PR）。
- 积极回复 issue / 合并 PR，保持仓库活跃度（影响搜索与推荐）。

---

## 11. 故障排查

| 现象 | 处理 |
|------|------|
| `git push` 卡住/超时 | 加 `-c http.proxy=http://127.0.0.1:7897 -c https.proxy=...`，或确认代理端口 |
| 403 / 无法推送 | 检查 `GH_TOKEN` 是否有 **write** 权限（Contents + Releases） |
| `gh release create` 报 tag 不存在 | 先 `git push` tag，或去掉 `--verify-tag` 让其自动建 tag |
| spec 文件名乱码 | 用 Python `os.listdir` 列出真实名，或直接 `pyinstaller main.py ...` 重建 |
| exe 被杀毒误报 | 关闭 UPX（`upx=False`）或对 exe 做代码签名；或提交到微软误报申诉 |
| 打包缺 PyQt6 插件 | 确认在 `.venv` 中构建，且未把 PyQt6 放进 excludes |
| 中文文件名资产在 Release 显示异常 | 统一用 ASCII 名 `LLama-Launcher-vX.Y.Z-...` |
| 封面图不显示 | 确认 `docs/cover-vX.Y.Z.png` 已 `git add` 并推送，且 raw 链接指向 `main` |
