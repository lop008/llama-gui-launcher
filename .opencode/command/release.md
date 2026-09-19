---
description: 发布新版本到 GitHub（改版本号 → 更新文档 → 打包 → 提交打 tag → 推送 → 创建 Release）
agent: build
---

请先**完整读取** `.opencode/skills/github-release/SKILL.md`，然后严格按其中流程发布新版本。

参数：$ARGUMENTS

执行要求：
- 版本号 = `$1`（若为空，先询问用户要发布的版本号，格式 X.Y.Z）。
- 全程遵循 SKILL.md 的「隐私清单」「版本号同步清单」「统一 Release 结构」。
- 步骤：同步版本号（`scripts/bump_version.py`）→ 更新中英 README/CHANGELOG/RELEASE_NOTES/参数说明 →
  刷新截图（`scripts/capture_screenshots.py`）与封面（`scripts/make_cover.py`）→ 写 `docs/release_body_vX.Y.Z.md`
  → `scripts/preflight.py` 自检通过 → PyInstaller 打包 → 生成版本化资产 → 提交 + 打 tag + 推送 → `gh release create`。
- 推送/创建 Release 前必须向用户确认（除非用户已明确授权本次直接发布）。
- 若网络被重置，使用本机代理 `http://127.0.0.1:7897`，并优先用 `gh auth git-credential` 避免明文 token。
