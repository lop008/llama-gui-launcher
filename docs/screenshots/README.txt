截图说明 / Screenshots (v0.5.15)

本目录包含 LLama 万能启动器当前版本（v0.5.15）的界面截图，供 README / Release 更新说明引用。
（v0.5.15 起统一使用「棕色」主题，1280x1040；已做脱敏：本机 IP 显示为示例值 192.168.1.100，
 辅助文件明细表里的目录一律显示为示例路径 D:\models\<目录名>。）

- main.png       主界面（v0.5.15 重点：模型行下方的「投机解码」行 + 辅助文件摘要行）
- main_en.png    英文界面主视图（多语言效果 + 投机解码行英文文案）
- spec_order.png 「排序」对话框（v0.5.15 新增：12 种方式的「自动」优先级，可拖动 / ▲▼ / Alt+↑↓）
- aux_files.png  「辅助文件」明细表（v0.5.15 新增：视觉投影 / 投机草稿头 / 量化标定文件 +
                 对应主模型；主模型下拉里已经不再出现这些文件）
- advanced.png   高级参数 + 多显卡展开视图（本页原有的「启用 MTP」勾选框已在 v0.5.15
                 升级为投机解码控件组，移到基础页，本页少了那一项）
- preview.png    命令预览页（生成的启动命令里现在带 --spec-type / --spec-draft-model）
- language.png   多语言菜单展开（v0.5.13 新增：简体中文 / 繁體中文 / English /
                 日本語 / 한국어 / Русский / Español / Français / 跟随系统语言）
- pill.png       托盘悬浮小窗（上：收起胶囊，下：悬停展开数据卡片，v0.5.01 新增）
- agent.png      Agent 工具页（OpenCode / Claude Code 等外部工具集成）
- download.png   HF 模型下载页（双列布局、三栏检索、逐文件断点续传）
- updater.png    llama.cpp 更新器页（v0.5.15 起 x64 与 arm64 包都列出，本机架构排最前）

沿用未重拍的截图：language.png / pill.png / agent.png / download.png 界面与上一版一致。

v0.5.15 界面变化：
- 基础页模型区从两行变三行：模型行 / 投机解码行（方式 + 状态标签 + 草稿模型 + 下载草稿 + 草稿长度）/ 辅助文件摘要行
- 高级页去掉「启用 MTP」勾选框（配置自动迁移：勾过 = mtp，没勾 = off，启动参数不变）
- 新增两个对话框：「排序」（自动优先级）与「辅助文件」明细表

示例引用：
![主界面](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/main.png)
![排序对话框](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/spec_order.png)
![辅助文件明细](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/aux_files.png)
![多语言菜单](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/language.png)
![高级参数](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/advanced.png)
![Agent 工具页](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/agent.png)
![HF 模型下载](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/download.png)
![llama.cpp 更新器](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/updater.png)
![命令预览](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/preview.png)
