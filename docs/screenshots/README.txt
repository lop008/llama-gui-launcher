截图说明 / Screenshots (v0.5.01)

本目录包含 LLama 万能启动器 v0.5.01 的界面截图，供 README / Release 更新说明引用。
（用 .opencode/skills/github-release/scripts/capture_screenshots.py 重新抓取，1280x1040）

- pill.png       托盘悬浮小窗（上：收起胶囊，下：悬停展开数据卡片，v0.5.01 新增）
- main.png       主界面（模型选择、运行参数、主题入口；v0.5.01 起含 局域网共享/HTTPS 开关、数据统计按钮）
- advanced.png   高级参数 + 多显卡展开视图
                 （KV cache K/V 独立量化、MTP、Flash Attention、上下文预设，
                  以及 v0.4.25 新增：启用 Jinja 模板 / 思考强度 / 推理预算、
                  启动时检测残留进程 / 端口被占用时建议更换端口）
- agent.png      Agent 工具页（OpenCode / Claude Code 等外部工具集成）
- download.png   HF 模型下载页（双列布局、三栏检索、逐文件断点续传）
- updater.png    llama.cpp 更新器页（在线检查并更新 llama.cpp）
- preview.png    命令预览页（生成的启动命令 / .bat 内容预览）

v0.5.01 界面变化：
- 主界面新增「局域网共享 / 启用 HTTPS」开关与局域网访问地址提示
- 缩到托盘后右下角出现悬浮小窗（胶囊 + 悬停展开数据卡片）
- 底部标签支持拖动排序；模型信息区新增「联网查询」勾选框
- 高级参数新增「缩到托盘时显示悬浮小窗」开关

示例引用：
![主界面](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/main.png)
![高级参数](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/advanced.png)
![Agent 工具页](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/agent.png)
![HF 模型下载](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/download.png)
![llama.cpp 更新器](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/updater.png)
![命令预览](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/preview.png)
