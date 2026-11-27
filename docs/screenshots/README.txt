截图说明 / Screenshots (v0.6.1)

本目录包含 LLama 万能启动器当前版本（v0.6.0）的界面截图，供 README / Release 更新说明引用。
（v0.5.15 起统一使用「棕色」主题，1280x1040；已做脱敏：本机 IP 一律显示为示例值 192.168.1.100。）

- main.png        主界面（v0.6.0：顶部标题卡显示版本 + 服务状态徽章 + 检测到的 llama.cpp 版本；
                  投机解码行示例为 DSpark「✔ 已找到配套草稿」）
- advanced.png    高级参数展开（v0.6.0 新增：**MoE 专家**行 = --cpu-moe / --n-cpu-moe / --moe-cache-mib；
                  思考模式(--reasoning) 与思考强度(reasoning_effort) 拆成两项；
                  「启动时检查启动器更新」勾选框）
- model_info.png  模型信息页（v0.6.0 扩充：模型类型 MoE 128 专家 / 每 token 激活 8 个、
                  思考能力、投机解码支持表、可点击的模型主页与 HuggingFace 链接）
- updater.png     「更新 llama.cpp」页（v0.6.0 重做：统计卡 + 分段筛选 + 行复选框与下载选中 +
                  已下载扫描；v1.1.0 这类没有 Windows 包的 Release 保留一行标注「无 Windows 包」）
- download.png    「模型下载」页（v0.6.0 重做：可输入的常用作者下拉 + 按目录分组的文件树，
                  勾文件夹即整组下载 + 仓库信息与可点击链接）
- agent.png       Agent 工具页（列顺序：工具 / 类型 / 路径 / 描述 / 打开；支持添加、编辑、删除）
- preview.png     命令预览页（v0.6.1 改成两栏：上「参数拆解 / 目的与意义」逐条解释，下完整命令行；
                   拆解只是解释，完整命令始终原样可复制，导出 .bat 不受影响）
- main_en.png     英文界面主视图（v0.6.0 新增 165 条文案已译入 7 张语言表）
- spec_order.png  「排序」对话框：12 种方式的「自动」优先级（可拖动 / ▲▼ / Alt+↑↓）
- aux_files.png   「辅助文件」明细表（视觉投影 / 投机草稿头 / 量化标定文件 + 对应主模型）
- pill.png        托盘悬浮小窗（上：收起胶囊，下：悬停展开数据卡片）
- language.png    多语言菜单展开（简体中文 / 繁體中文 / English / 日本語 / 한국어 / Русский /
                  Español / Français / 跟随系统语言）

v0.6.1 界面变化：
- 六个页签恢复可见描边（未选中 1px 圆角边框、选中加粗 + 2px 高亮边框），此前 border:none 导致
  「看不出那排字是能点的标签页」
- 「投机解码」下拉：本机 llama-server 不认该取值、或主模型没有对应结构且本机无可用草稿的方式
  **置灰不可选**；「可以用但还缺一个草稿文件」的方式保持可选，名字后加 ⚠ 标记
- 「视觉投影（多模态）」留空而模型带 mmproj 时给出提示：选上才能看图（只做纯对话可以留空）；
  同目录多份精度时自动配对优先 F16（不再按文件名撞上 BF16 / F32 就用）
- 「模型下载」文件树与「更新 llama.cpp」表格：每一列都能手动拖宽（此前名称列是 Stretch 模式锁死），
  更新页操作列按按钮实测宽度定宽，「下载 / 安装」不再被裁字
- 命令预览改为两栏（见上）

v0.6.0 界面变化：
- 顶部新增标题卡：版本徽章 + 一句话定位 + 服务状态徽章 + llama 版本
- 基础页「对话模板」：思考模式（--reasoning on/off/auto）与思考强度（reasoning_effort）分开，
  强度下拉仅在模型模板声明该变量时启用，选项按模板实际取值重建
- 高级页新增「MoE 专家」（--cpu-moe / --n-cpu-moe N / --moe-cache-mib N）与「启动时检查启动器更新」
- 「更新 llama.cpp」页重做：统计卡 + 分段筛选控件 + 复选框批量下载 + 状态列
- 「模型下载」页重做：常用作者可输入下拉 + 目录树整组勾选 + 仓库可点击链接
- 「模型信息」页扩充：模型能力（稠密 / MoE）、思考能力、投机解码支持表
- 新增「关于 → 检查启动器更新…」自升级对话框

示例引用：
![主界面](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/main.png)
![高级参数](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/advanced.png)
![模型信息](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/model_info.png)
![更新 llama.cpp](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/updater.png)
![模型下载](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/download.png)
![Agent 工具页](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/agent.png)
![命令预览](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/preview.png)
![英文界面](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/main_en.png)
