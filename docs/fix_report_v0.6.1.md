# LLama 万能启动器 v0.6.1 修复报告

针对 v0.6.0 发布后反馈的 7 条问题逐条处理。全部改动已完成并通过回归（17 套件 + 55 项 v06 断言 + 界面端到端 15 项 + 七张语言表缺失 0）。
当时状态：改动先在本地工作树完成；**已随 `a25d517` 提交**，并因 v0.6.1 从未单独发布而**并入 v0.6.5**（版本号直接从 0.6.0 提到 0.6.5，见 `fix_report_v0.6.5.md`）。

---

## ① 六个标签页看不出是可点的

- **现象**：顶部「基础设置 / 高级参数 / 模型信息 / 命令预览 / 模型下载 / Agent 工具」像一排普通文字，选中哪个不明显。
- **根因**：v0.6.0 换新的 `brown` 主题 QSS 时写了 `QTabBar::tab { border: none }`，页签只剩背景色差，在深色主题下几乎不可辨。
- **改法**（`src/themes.py`）：未选中页签恢复 1px 描边 + 圆角 + 向下错位 3px（做出「未抬起」的层次感）；选中页签描边加粗为 2px 高亮色并 `font-weight: 700`；hover 时描边与文字同步变亮。
- **验证**：`_check_ui_fixes.py` 断言生成的 QSS 含 `QTabBar::tab` 描边规则与 `:selected` 加粗规则；截图 `main.png` 目视确认六个页签边界清晰。

## ② 投机解码：当前模型用不了的方式要置灰

- **现象**：下拉里所有方式都能选，选完启动才发现「这个模型没有 MTP 头」或「本机 llama-server 不认这个 `--spec-type`」。
- **改法**：判定口径抽成纯函数 `spec_decode.spec_selectable()`，`UNSELECTABLE_STATES = (ST_NO_ENGINE, ST_NO)`，界面置灰与命令行下发共用同一份判定，不会两边说得不一样。
  - **置灰不可选**：本机 llama-server 不认该取值（提示「✖ 更新 llama.cpp 后即可用」）；主模型没有对应结构且本机找不到可用草稿（提示「—」）。
  - **保持可选但加 `⚠`**：「缺草稿」。点「下载草稿」补齐就能用，堵死反而挡路；`⚠` 让「立刻可用」和「还要下一个文件」一眼能分开。
  - **自动纠偏**：重启加载老配置时，如果配置里存的方式对当前模型已失效，重建下拉时直接落到「自动」，绝不让当前项停在一个灰掉的取值上；运行中检测结果变化导致当前项失效时同样回退，并在状态栏附一句一次性说明（「原先选中的「XX」不适用于该模型，已改回「自动」」）。
- **涉及文件**：`src/spec_decode.py`、`src/ui/model_probe.py`。
- **验证**：注入 `ST_NO_ENGINE` / `ST_NO` 两种状态后，对应下拉项确实变灰、其它项仍可选、失效的遗留配置落到 `auto`；真实数据下 6 个模型 × 14 个下拉项逐个点选无异常。

## ③ Inkling 2 到底是不是视觉模型 —— 是，而且必须选投影文件才能看图

实测 `D:\models\Inkling-2` 目录下文件的 GGUF 元数据：

| 文件 | 关键字段 |
|---|---|
| `mmproj-F16/BF16/F32.gguf` | `general.architecture = clip`、`clip.has_vision_encoder = True`、`clip.vision.projector_type = inkling2v`、`projection_dim = 2304` |
| `Inkling-2-Mini-UD-*.gguf`（主模型） | `has_clip = False`、`embedding_length = 2304` |

`projection_dim = 2304` 与主模型 `embedding_length = 2304` 完全对应，而主模型自身 `has_clip = False` —— 说明**视觉塔不在主权重里，全部在这个外挂 mmproj 文件里**。因此：

- 选上 mmproj → 能看图；
- 留空 → 不会报错，但当纯文本模型跑，多模态能力默默没了（用户很容易以为「这模型不支持图片」）。

主模型 `has_clip = False` 是正常现象，不是文件坏了。

顺手修了两处（`src/model_scanner.py`、`src/ui/model_probe.py`）：

1. 同目录有多份精度时，自动配对按 **F16 > BF16 > F32 > 量化** 择优（此前按扫描顺序，可能撞上 BF16 甚至 F32，白占约一倍显存/内存 —— F32 那份 1.18 GB）。
2. 模型带投影文件却把「视觉投影」留空时，界面提示：「ℹ 该模型带视觉投影文件：选上才能看图（只做纯对话可以留空）」，选上后提示自动收回。

## ④ 投机草稿下载到哪个目录 —— 就是当前选中模型所在目录

代码依据（`src/ui/draft_download.py`）：

- `self.model_dir = os.path.dirname(str(model_path or ""))` —— 对话框的目标目录直接取**当前选中主模型**的所在目录；
- 落盘前用同目录已有文件名做查重（`draft_hub.dest_path(..., taken)`），重名自动改名，不会覆盖；
- 下载完成后 `self._pair_back(path)` 自动把草稿选进「草稿模型」下拉，不用手动找。

对话框里也直接把这句话显示出来（「下载到：…\模型目录」），并给「打开目录」按钮。这一条**无需改代码**，行为已经符合要求。

## ⑤ 命令预览改成「拆解 + 意义」两栏

不算复杂，已做完（新增 `src/cmd_explainer.py`）：

- 页面拆成上下两块：上半是「参数拆解 / 目的与意义」两栏表格，下半保留**完整命令行原文**。
- 拆解器**只解析最终生成的命令行文本**，不参与命令行生成 —— 保证解释的和实际下发的永远同源；导出 `.bat` 仍读原来那份命令，完全不受影响。
- 按 Windows 命令行规则切 token：带空格的路径（`-m "D:\my models\a b.gguf"`）、`--chat-template-kwargs "{\"reasoning_effort\":\"medium\"}"` 这类内嵌转义引号、布尔项不吞下一个值、负数取值（`--temp -0.5`）都不会错位。
- **未收录的参数如实标注**「未收录的参数：原样交给 llama-server 处理」，绝不编造解释。
- 左列用等宽字体，长路径列宽不够时悬停可看全。
- 拆解快验 13 项 PASS（含上述边界）。

## ⑥ 模型下载页文件列表列宽不能拖

- **根因**：名称列用的是 `QHeaderView.Stretch`。Qt 里 Stretch 列**禁止手动拖动**，这是设计如此，不是 bug 触发。
- **改法**：统一到新组件 `src/ui/kit.py:ColumnResizer` —— 全部列 `Interactive`（都能拖），视口剩余宽度自动补给指定的「主列」（名称列），右侧不留白；**用户一旦真拖过某一列就停止自动补宽**，避免「刚拖宽就被弹回去」。表头允许拖动换位。
- 下载页的文件树（`tree_files`）与仓库表都走这套。

## ⑦ 更新页列宽不能拖 + 「下载 / 安装」按钮被裁

- 列宽：与 ⑥ 同源，同一套 `ColumnResizer` 解决。
- 按钮被裁：操作列宽度不再写死，改成**按按钮 `sizeHint` 实测宽度**计算（`_note_op_width()` / `_fit_op_column()`），换语言、换字号、按钮文字变长都不会再裁字；同时行高固定 40px，保证一排放得下整组按钮。

---

## 额外发现并修掉的两个真实崩溃

这两个是回归测试里抓出来的，属于「用户会遇到的闪退」，不是测试环境问题。

### A. `QComboBox.setItemText()` 稳定 0xC0000005

为了在投机方式名字后加 `⚠`，最初用了 `combo_spec.setItemText(i, label)`。全量回归里 `core` 套件从 PASS 变 FAIL（崩在「8 种语言重建界面」那段）。改走与旁边 `setFlags` 同一层次的 `combo_spec.model().item(i).setText(label)` 后消失。已在 `_test_v06.py` 加静态断言，禁止再出现 `combo_spec.setItemText`。

### B. 关窗后后台回调打进正在销毁的界面（概率性闪退）

- **归因数据**：`gui + args + 8 语言重建界面` 组合，v0.6.0 基线跑 8 次 **0 崩**；本轮改动（未加固）跑 6 次崩 1 次、该组合 3 次全崩；加固后同组合再跑 8 次 **0 崩**。
- 本轮改动给每个窗口增加了拆解表填充 + 逐下拉项刷新，主线程耗时变长，把一个**原本就存在**的隐患顶到了必现边缘。
- 三处真实缺陷与修法：
  1. `QTimer.singleShot(600, self._check_residual)` —— **无父对象的定时器不受窗口生命周期约束**，窗口销毁后照样触发，而 `_check_residual` 里会 `QMessageBox(self)` 并读控件。改为挂在窗口下的 `QTimer(self)`，随窗口一起销毁。
  2. 状态栏三个监控槽是裸 `lambda`，直连 `SystemMonitor`，而该类的 `api_changed / model_changed / vram_* / speed_changed` 是**从后台探测线程 emit** 的。改为带 `_closing` 判断的具名槽。
  3. `closeEvent` 真退出路径上**没有停掉监控 1 秒节拍与 5 秒用量统计**。现已停掉，且刻意放在「服务正在运行，是否同时停止服务？」对话框**之后** —— 用户点「取消」继续用时，不能把监控给停了。
- 同一闸门（`_closing`）覆盖：`_on_mtp_detected`、`_update_spec_ui`、`_update_pill`、`_on_llama_version`、`detect_gpus`、`check_launcher_update_silent`、`_on_model_scan_done`、`_on_tool_scan_done`、`_on_model_info`、`_tick_usage`、`_apply_reflow`。
- `_test_v06.py` 第 10 节 10 条静态断言守住这套规则（残留检测必须是挂窗口的定时器、关窗必须置位并停三类周期任务、停后台动作必须排在取消分支之后、监控槽不得再用裸 lambda 等）。

---

## 多语言

界面新增文案 53 + 2 条（拆解两栏表头与说明、投机置灰/`⚠` 说明、回退说明、视觉投影提示、列宽提示等）已全部译入 7 张语言表：

```
zh-TW / en / ja / ko / ru / es / fr  各 1014 条
缺失 0，多余 0；占位符 {0} / 换行 / HTML 标签 / URL 全量校验通过
```

## 回归结果

| 套件 | 结果 |
|---|---|
| logic / bat / i18ndiag / roles / specargs / v06 / draft / draftnet / arm / batarm / layout / pill / gui / core / edge / residual / net | **全部 17 个 PASS** |
| `_test_v06.py` | ALL 55 CHECKS PASSED（含本轮新增置灰、拆解、列宽、mmproj、关窗加固断言） |
| 界面端到端 `_check_ui_fixes.py` | 15 项全 PASS |
| `_i18n_missing.py` | 7 张表缺失 0 / 多余 0 |

截图已按新界面重拍（`docs/screenshots/`）：`main.png` 六个页签描边清晰、视觉投影自动配对 `mmproj-F16.gguf (609.7 MB)`；`preview.png` 两栏拆解 + 完整命令行；`updater.png` 320 行版本、操作列「下载 / 进度 / 安装」完整不被裁；`download.png` 文件树列头可拖（脱敏检查：IP 显示 192.168.1.100，无 `C:\Users\...`）。

## 改动文件

**新增**：`src/cmd_explainer.py`（命令行逐条拆解）
**功能改动**：`src/themes.py`、`src/spec_decode.py`、`src/ui/model_probe.py`、`src/model_scanner.py`、`src/main_window.py`、`src/ui/launch_flow.py`、`src/ui/kit.py`、`src/hf_download_tab.py`、`src/updater_tab.py`、`src/locales/*.py`（7 张）
**崩溃加固**：`src/main_window.py`、`src/ui/app_prefs.py`、`src/ui/menu_about.py`、`src/ui/gpu_probe.py`、`src/ui/agent_tools.py`、`src/ui/tray_pill.py`、`src/ui/launch_flow.py`
**文档**：`docs/screenshots/README.txt`

## 本次提交未包含（发版时再做）

- 版本号当时仍是 `0.6.0`；后续直接从 0.6.0 提到 **0.6.5**（v0.6.1 未单独占用号）。
- `CHANGELOG.md` / `RELEASE_NOTES.md` / `README.md` / `参数说明.md` 未更新。
- 未重新打包、未发 GitHub Release。

也就是说：这批改动目前只进了代码库，用户侧要等下一次发版才拿得到。
