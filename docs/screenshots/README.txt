截图说明 / Screenshots（v0.6.5 起的标准）

发版规矩：每个版本只出 **2 张**页面截图——
  main.png    主界面
  health.png  本版主打页（v0.6.5 = 「工具 → 启动文件 → 校验启动文件 → 合理性体检」）
README.md / README.zh-CN.md / 发布正文（docs/release_body_*.md）都只嵌这两张。

目录里其余 png 是 v0.6.1 及更早版本的界面存档：**历史 Release 正文仍在引用，不要删**；
它们不代表当前界面。本版界面相对它们的差异：新增「合理性体检」页签与「让模型分析」按钮、
微批 -ub 字段、启动前显存预算弹窗、MoE 卸载预设（含计算过程行）、投机解码不可用方式置灰、
表格列宽可拖与路径中间省略、运行日志页「清屏 / 打开日志目录」、界面字号 Ctrl+滚轮缩放、
工具菜单二级化、更新页平台/后端多选与「打开 llama.cpp 下载页」。

规格：棕色主题（theme=brown），主界面 1280x1040。
脱敏：本机 IP 一律显示示例值 192.168.1.100；演示用 .bat 写在非用户目录；画面内不出现 C:\Users\<用户名>。

本版两张
- main.png    主界面：顶部标题卡 v0.6.5 + 服务状态徽章 + 检测到的 llama.cpp 版本（1.1.0-dev b12910）；
              主模型 Inkling-2-Mini-UD-Q4_K_XL.gguf (16.4 GB) 已选中，视觉投影自动配对
              mmproj-F16.gguf (609.7 MB)，投机解码 DSpark「已找到配套草稿」，显卡占用 207/24.0 GB
- health.png  合理性体检：18 项离线结论 —— 26 个参数本机 llama-server 全认识、无重复参数、
              -c 131072 未超模型训练上限 1048576、显存需求 31.3 GiB 对比显存 24.0 GiB
              （权重 16.4 + KV 6.4 + 批处理/计算 8.5，超 7.3 GiB）、批处理峰值 8.52 GiB
              （微批 -ub 1024 × 上下文 131072，KV 头 8，闪存注意力关）、内存可用 4.1 GiB、
              MoE 模型（128 个专家，每 token 激活 8 个）建议 --n-cpu-moe 从 1/4 层起、磁盘剩余；
              底部状态「体检完成：15 项通过 / 3 项需要注意」，服务未运行时「让模型分析」置灰

示例引用：
![主界面](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/main.png)
![合理性体检](https://raw.githubusercontent.com/lop008/llama-gui-launcher/main/docs/screenshots/health.png)

历史存档（老版本 Release 正文引用，勿删）：
advanced.png / model_info.png / updater.png / download.png / agent.png / preview.png /
main_en.png / spec_order.png / aux_files.png / pill.png / language.png
