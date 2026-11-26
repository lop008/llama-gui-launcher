# -*- coding: utf-8 -*-
"""界面构建：基础设置页、高级参数页、GPU 分配页（控件与默认值）。"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)
from ..cmd_builder import KV_CACHE_TYPES, SPLIT_MODES
from ..i18n import t
from ..presets import PRESETS, SAMPLING_PRESETS


class LayoutBasicMixin:

    def _build_basic(self, lay):
        # ---- A4: 「生成参数」分组（先创建；控件由 basic/advanced 两处添加进来）----
        self.group_gen = QGroupBox(t('生成参数'))
        self._gen_grid = QGridLayout(self.group_gen)
        self._gen_grid.setContentsMargins(8, 2, 8, 6)
        self._gen_grid.setHorizontalSpacing(10)
        self._gen_grid.setVerticalSpacing(6)
        # 标签列不伸缩、控件列平均伸缩：四组「标签+控件」均匀铺满整行，标签完整可见
        for _c in (0, 2, 4, 6):
            self._gen_grid.setColumnStretch(_c, 0)
        for _c in (1, 3, 5, 7):
            self._gen_grid.setColumnStretch(_c, 1)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        # 标签列/按钮列不伸缩；监听地址(1)与 API Key(5) 两列平分多余宽度
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setColumnStretch(3, 0)
        grid.setColumnStretch(4, 0)
        grid.setColumnStretch(5, 1)
        for _c in (6, 7, 8):
            grid.setColumnStretch(_c, 0)

        # ---- 目录类设置（模型 / 启动器 / 数据）并排一行，充分利用横向宽度 ----
        self.edit_dir = QLineEdit()
        self.edit_dir.setPlaceholderText(t('扫描模型的根目录'))
        self.edit_dir.setToolTip(t('模型扫描根目录。程序会在此目录的 2~3 级子目录内扫描 .gguf 模型（自动跳过 .venv/.git 等无关目录）。'))
        btn_dir = QPushButton(t('浏览…'))
        btn_dir.clicked.connect(self._browse_dir)
        btn_dir.setToolTip(t('选择模型扫描目录'))
        self.btn_refresh = QPushButton(t('刷新模型'))
        self.btn_refresh.clicked.connect(lambda: self.refresh_models())
        self.btn_refresh.setToolTip(t('重新扫描模型目录下的所有 GGUF 模型文件'))

        self.edit_launcher = QLineEdit()
        self.edit_launcher.setPlaceholderText(t('留空 = 模型目录\\llama-server.exe'))
        self.edit_launcher.setToolTip(
            t('启动服务时使用的可执行文件（默认 llama-server.exe）。\n若将来 llama 改名字或路径不同，可在此直接用文件选择器指定新文件。\n留空 = 自动回退到 模型目录\\llama-server.exe'))
        btn_launcher = QPushButton(t('浏览…'))
        btn_launcher.clicked.connect(self._browse_launcher)
        btn_launcher.setToolTip(t('选择启动器可执行文件（*.exe）'))
        btn_launcher_clear = QPushButton(t('清除'))
        btn_launcher_clear.clicked.connect(self._clear_launcher)
        btn_launcher_clear.setToolTip(t('清除自定义启动器文件，恢复为自动查找'))

        self.edit_data_dir = QLineEdit()
        self.edit_data_dir.setPlaceholderText(t('留空 = 程序所在目录'))
        # A3: tooltip 按实际行为撰写（redirect_data_dir 只迁移 config.json，不复制旧统计/日志）
        self.edit_data_dir.setToolTip(
            t('存放本地数据：config.json 权威副本、使用统计 stats.json、运行日志 logs/、联网查询缓存 hf_model_cache.json。\n留空 = 程序所在目录。切换后新产生的数据写入新目录，并在程序目录留下指向文件（已有的统计/日志文件不会自动迁移）。'))
        btn_data_dir = QPushButton(t('浏览…'))
        btn_data_dir.clicked.connect(self._browse_data_dir)
        btn_data_dir.setToolTip(t('选择数据存储目录'))
        btn_data_reset = QPushButton(t('恢复默认'))
        btn_data_reset.clicked.connect(self._reset_data_dir)
        btn_data_reset.setToolTip(t('恢复为程序所在目录'))

        def _path_group(label_text, edit, *buttons):
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(4)
            h.addWidget(QLabel(label_text))
            h.addWidget(edit, 1)
            for b in buttons:
                h.addWidget(b)
            return box

        dir_row = QWidget()
        dir_lay = QHBoxLayout(dir_row)
        dir_lay.setContentsMargins(0, 0, 0, 0)
        dir_lay.setSpacing(10)
        dir_lay.addWidget(_path_group(t('模型目录:'), self.edit_dir, btn_dir, self.btn_refresh), 1)
        dir_lay.addWidget(_path_group(t('启动器文件:'), self.edit_launcher, btn_launcher, btn_launcher_clear), 1)
        dir_lay.addWidget(_path_group(t('数据目录:'), self.edit_data_dir, btn_data_dir, btn_data_reset), 1)
        grid.addWidget(dir_row, 0, 0, 1, 9)

        # ---- A2: 排序方式移到「主模型」行末尾（功能 1）----
        self.combo_sort = QComboBox()
        for name in (t('目录+文件名'), t('大小降序'), t('名称')):
            self.combo_sort.addItem(name)
        self.combo_sort.setToolTip(
            t('模型列表排序方式：\n· 目录+文件名 = 先按所在目录、再按文件名从小到大（自然排序，默认）；\n· 大小降序 = 大文件在前；\n· 名称 = 仅按文件名从小到大。'))
        self.combo_sort.setMinimumWidth(118)

        # ---- 功能 5：主模型 / 视觉模型 / 排序 并排一行（功能不变）----
        self.combo_model = QComboBox()
        self.combo_model.setToolTip(t('选择要加载的 GGUF 主模型（自动扫描目录得到）'))
        self.combo_mmproj = QComboBox()
        self.combo_mmproj.setToolTip(t('视觉模型（mmproj）文件，负责把图像编码成模型能理解的向量。\n只列出与主模型同一目录下的 mmproj（保证配套一致），或选择「（不使用）」以纯文本模式运行。\n鼠标悬停可查看完整路径。'))
        self.combo_mmproj.addItem(t('（不使用）'), None)
        self.label_mmproj_warn = QLabel("")
        self.label_mmproj_warn.setStyleSheet("color: #ff6a6a;")
        self.label_mmproj_warn.setWordWrap(True)

        model_row = QWidget()
        mrow = QHBoxLayout(model_row)
        mrow.setContentsMargins(0, 0, 0, 0)
        mrow.setSpacing(6)
        mrow.addWidget(QLabel(t('主模型:')))
        mrow.addWidget(self.combo_model, 4)
        mrow.addWidget(QLabel(t('视觉模型:')))
        mrow.addWidget(self.combo_mmproj, 4)
        mrow.addWidget(QLabel(t('排序:')))
        mrow.addWidget(self.combo_sort, 1)
        mrow.addWidget(self.label_mmproj_warn, 2)

        # ---- v0.5.15：投机解码（方式 + 「自动」优先级 + 草稿 + 长度）+ 辅助文件摘要 ----
        self.combo_spec = QComboBox()
        self.combo_spec.setMinimumWidth(150)
        self.combo_spec.setToolTip(
            t('投机解码：先由草稿「猜」出若干 token，再交给主模型一次性验证，猜中即加速，输出结果不变。\n'
              '· 自动 = 按「排序」里设定的顺序，挑第一个当前可用的方式；\n'
              '· 不启用 = 不下发 --spec-type；\n'
              '· MTP = 用模型自带的 MTP 头，不需要额外文件；\n'
              '· DFlash / DSpark / LiliCorr / EAGLE-3 / 小模型草稿 = 需要下载对应的草稿模型；\n'
              '· n-gram 系列 = 不需要任何草稿文件，遇到重复片段时加速，几乎所有模型都能用。\n'
              '灰色条目 = 本机 llama-server 不认这种方式，更新 llama.cpp 后可用。'))
        self.label_spec_status = QLabel("")
        self.label_spec_status.setStyleSheet("color: #8fd0ff;")
        self.label_spec_status.setToolTip(
            t('当前投机方式的状态：绿色=可用，橙色=缺草稿文件或没检测到，红色=本机 llama.cpp 不支持。悬停看具体原因。'))
        self.combo_draft = QComboBox()
        self.combo_draft.setMinimumWidth(200)
        self.combo_draft.setToolTip(
            t('草稿模型文件。默认「（自动配对）」= 使用与主模型同一目录、命名配套的草稿头；\n'
              '需要草稿的方式找不到配套文件时会提示下载。悬停可查看完整路径。'))
        self.btn_spec_download = QPushButton(t('下载草稿'))
        self.btn_spec_download.setToolTip(
            t('在 HuggingFace 上找与当前模型配套的草稿模型：官方 GGUF 仓库优先（可直接下载）；\n'
              '第三方仓库需要自己转换格式，列表里会标注说明。'))
        self.spin_spec_n = QSpinBox()
        self.spin_spec_n.setRange(0, 32)
        self.spin_spec_n.setValue(0)
        self.spin_spec_n.setSpecialValueText(t('引擎默认(3)'))
        self.spin_spec_n.setToolTip(
            t('--spec-draft-n-max：一次让草稿猜多少个 token 再交给主模型验证（引擎默认 3）。\n'
              '不是越大越快：猜错的部分要回退重算，显存也会多占一些。0 = 不传该参数，用引擎默认。'))

        self.btn_spec_order = QPushButton(t('排序'))
        self.btn_spec_order.setToolTip(
            t('调整「自动」的优先级：排在上面的方式先尝试。\n'
              '打开后可以按住条目上下拖动，也可以用 ▲▼ / Alt+↑↓。'))

        spec_row = QWidget()
        sp_row = QHBoxLayout(spec_row)
        sp_row.setContentsMargins(0, 0, 0, 0)
        sp_row.setSpacing(6)
        sp_row.addWidget(QLabel(t('投机解码:')))
        sp_row.addWidget(self.combo_spec, 3)
        sp_row.addWidget(self.btn_spec_order)
        sp_row.addWidget(self.label_spec_status, 5)
        sp_row.addWidget(QLabel(t('草稿模型:')))
        sp_row.addWidget(self.combo_draft, 4)
        sp_row.addWidget(self.btn_spec_download)
        sp_row.addWidget(QLabel(t('草稿长度:')))
        sp_row.addWidget(self.spin_spec_n)

        self.btn_aux = QPushButton("")
        self.btn_aux.setFlat(True)
        self.btn_aux.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_aux.setStyleSheet("border: none; text-align: left; color: #8a8a8a;")
        self.btn_aux.setToolTip(
            t('这些文件不是独立模型，所以不出现在主模型列表里：\n'
              '· 视觉投影（mmproj）= 负责把图片编码成模型能读懂的向量；\n'
              '· 投机草稿头 = MTP / DFlash / DSpark 等加速用的小文件；\n'
              '· 量化标定文件（imatrix）= 制作量化模型时用，运行不需要。\n'
              '点击查看清单、所在目录与它对应的主模型。'))
        self.label_spec_hint = QLabel(t('（点「排序」调整「自动」的尝试顺序）'))
        self.label_spec_hint.setStyleSheet("color: #8a8a8a;")

        aux_row = QWidget()
        ax_row = QHBoxLayout(aux_row)
        ax_row.setContentsMargins(0, 0, 0, 0)
        ax_row.setSpacing(6)
        ax_row.addWidget(self.btn_aux)
        ax_row.addWidget(self.label_spec_hint)
        ax_row.addStretch(1)

        # 三行合成一块，仍然占网格第 1 行：下面的监听地址/端口等行号全部不用动
        model_block = QWidget()
        mb_lay = QVBoxLayout(model_block)
        mb_lay.setContentsMargins(0, 0, 0, 0)
        mb_lay.setSpacing(4)
        mb_lay.addWidget(model_row)
        mb_lay.addWidget(spec_row)
        mb_lay.addWidget(aux_row)
        grid.addWidget(model_block, 1, 0, 1, 9)
        self._rebuild_spec_combo()
        self._update_aux_summary()

        grid.addWidget(QLabel(t('监听地址:')), 2, 0)
        self.edit_host = QLineEdit()
        self.edit_host.setToolTip(t('服务监听的地址（Host）。\n127.0.0.1 = 仅本机访问；0.0.0.0 = 局域网内其他设备也能访问。'))
        grid.addWidget(self.edit_host, 2, 1)

        grid.addWidget(QLabel(t('端口:')), 2, 2)
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(8080)
        self.spin_port.setToolTip(t('服务监听的端口（默认 8080）。\nOpenAI 兼容接口地址为 http(s)://监听地址:端口/v1'))
        grid.addWidget(self.spin_port, 2, 3)

        # ---- API Key：从高级参数移到此处（端口之后、局域网共享之前）----
        grid.addWidget(QLabel("API Key:"), 2, 4)
        self.edit_apikey = QLineEdit()
        self.edit_apikey.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit_apikey.setToolTip(t('API 密钥（--api-key）。\n设置后客户端调用接口必须携带此 Key，否则会被拒绝。\n留空 = 不设密钥，任何人都能访问。'))
        grid.addWidget(self.edit_apikey, 2, 5)

        # ---- 局域网共享 / HTTPS / 本机 IP：与监听地址同一行，紧凑排布 ----
        self.check_lan = QCheckBox(t('局域网共享'))
        self.check_lan.setToolTip(
            t('勾选后监听地址自动设为 0.0.0.0，局域网内其他电脑可通过「本机IP:端口」访问本服务。\n取消勾选恢复为 127.0.0.1（仅本机可访问）。'))
        grid.addWidget(self.check_lan, 2, 6)

        self.check_ssl = QCheckBox(t('启用 HTTPS'))
        self.check_ssl.setToolTip(
            t('勾选后以 HTTPS 协议提供服务，并自动生成自签名证书。\n若数据目录含中文等非 ASCII 字符，证书会改放到英文目录（避免 llama-server 无法读取）。\n浏览器首次访问会提示「不安全」，手动信任即可；对外正式使用建议换成受信任证书。'))
        grid.addWidget(self.check_ssl, 2, 7)

        self.label_local_ip = QLabel("")
        self.label_local_ip.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label_local_ip.setToolTip(t('本机在局域网中的访问地址，可直接复制给其他设备使用。'))
        grid.addWidget(self.label_local_ip, 2, 8)

        # GPU层数(-ngl) 已移入「生成参数」分组（见 _build_advanced）

        lay.addLayout(grid)

        # ---- A4: 上下文预设 / 上下文长度 / 预测Token → 「生成参数」分组 ----
        self._gen_grid.addWidget(QLabel(t('上下文预设:')), 0, 0)
        self.combo_preset = QComboBox()
        for name, _ctx in PRESETS:
            self.combo_preset.addItem(name)
        self.combo_preset.setToolTip(t('根据显卡显存大小，一键应用推荐的「上下文长度」（只修改「上下文长度」参数）。\n点选后「上下文长度」会同步更新为该档位；手动修改「上下文长度」后此下拉会自动回显对应档位或「自定义」。\n例：24GB 显存推荐 512K 上下文。'))
        self._gen_grid.addWidget(self.combo_preset, 0, 1)

        self._gen_grid.addWidget(QLabel(t('上下文长度:')), 0, 2)
        self.spin_ctx = QSpinBox()
        self.spin_ctx.setRange(256, 1048576)
        self.spin_ctx.setSingleStep(1024)
        self.spin_ctx.setValue(32768)
        self.spin_ctx.setToolTip(t('上下文长度（token），即模型一次会话最多能「记住」的对话量。\n这是真正传给 llama-server 的参数（-c），可自由设为任意值。\n越大越占显存/内存，也越慢。建议 ≤ 模型的训练上下文。\n可参考「模型信息」页显示的模型训练上下文。'))
        self._gen_grid.addWidget(self.spin_ctx, 0, 3)

        self._gen_grid.addWidget(QLabel(t('预测Token:')), 0, 4)
        self.spin_np = QSpinBox()
        self.spin_np.setRange(-1, 1000000)
        self.spin_np.setValue(8192)
        self.spin_np.setSpecialValueText(t('-1 = 无限'))
        self.spin_np.setToolTip(t('每次回答最多生成的 token 数（-n）。\n-1 = 不限制，直到模型输出结束符为止；\n若模型「停不下来/无限复读」，可调小此值限制回答长度。'))
        self._gen_grid.addWidget(self.spin_np, 0, 5)

        lay.addWidget(self.group_gen)

    def _build_advanced(self, lay):
        grid = QGridLayout()
        grid.setContentsMargins(8, 2, 8, 6)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        # 标签列不伸缩、控件列平均伸缩：CPU线程/API Key 不再独占宽度，
        # 右侧 KV 缓存 V(-ctv) 等控件同样获得均等宽度。
        for _c in (0, 2, 4, 6):
            grid.setColumnStretch(_c, 0)
        for _c in (1, 3, 5, 7):
            grid.setColumnStretch(_c, 1)

        # ---- 第 0 行：计算 / 服务（CPU线程 / 闪存注意力 / 超时 / 自动打开浏览器）----
        grid.addWidget(QLabel(t('CPU线程:')), 0, 0)
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(-1, 256)
        self.spin_threads.setValue(-1)
        self.spin_threads.setSpecialValueText(t('-1 = 自动'))
        self.spin_threads.setToolTip(t('用于计算的 CPU 线程数（-t）。\n-1 = 自动（使用全部逻辑核心）。'))
        grid.addWidget(self.spin_threads, 0, 1)

        grid.addWidget(QLabel(t('闪存注意力:')), 0, 2)
        self.combo_fa = QComboBox()
        self.combo_fa.addItems(["on", "off", "auto"])
        self.combo_fa.setToolTip(t('Flash Attention 闪存注意力（-fa）。\non = 开启，省显存且更快（N 卡 / 新架构推荐）；\noff = 关闭，兼容性更好。'))
        grid.addWidget(self.combo_fa, 0, 3)

        grid.addWidget(QLabel(t('超时(秒):')), 0, 4)
        self.spin_timeout = QSpinBox()
        self.spin_timeout.setRange(30, 86400)
        self.spin_timeout.setValue(3600)
        self.spin_timeout.setToolTip(t('服务读写超时（--timeout）。\n单个请求超过该秒数会被强制断开，默认 3600。'))
        grid.addWidget(self.spin_timeout, 0, 5)

        self.check_browser = QCheckBox(t('启动成功后自动打开浏览器'))
        self.check_browser.setChecked(True)
        self.check_browser.setToolTip(t('服务就绪后自动用默认浏览器打开 Web 界面。'))
        grid.addWidget(self.check_browser, 0, 6, 1, 2)

        # ---- 功能 6/7：连续批处理 / mlock / mmap（MTP 已升级为「投机解码」，见基础页模型区）----
        self.check_cont = QCheckBox(t('连续批处理'))
        self.check_cont.setChecked(True)
        self.check_cont.setToolTip(
            t('连续批处理（--cont-batching）：\n多个客户端并发请求时，新请求可以在解码过程中随时插入当前批次，不必等整批全部生成完才处理下一个，显著提升总吞吐量、降低等待。\n多客户端场景推荐开启；单客户端使用时无影响。'))
        self.check_mlock = QCheckBox(t('mlock 锁定内存'))
        self.check_mlock.setToolTip(t('--mlock：把模型锁定在内存中，防止被系统换出到磁盘。\n占内存更多，但推理更稳定。'))
        self.check_mmap = QCheckBox(t('禁用 mmap'))
        self.check_mmap.setToolTip(t('--no-mmap：关闭内存映射加载。\n加载更慢但内存占用更可控，个别磁盘/内存环境可改善稳定性。'))
        grid.addWidget(self.check_cont, 1, 0, 1, 2)
        grid.addWidget(self.check_mlock, 1, 2)
        grid.addWidget(self.check_mmap, 1, 3)

        # ---- 第 2 行：对话模板（Jinja 模板 / 思考强度 / 推理预算）----
        self.check_jinja = QCheckBox(t('启用 Jinja 模板'))
        self.check_jinja.setToolTip(
            t('启用模型自带的 Jinja 对话模板（--jinja）。\nllama-server 默认用内置的硬编码模板；开启后改用模型 GGUF 元数据里的\ntokenizer.chat_template，能正确套用新版模型（Qwen3.x 等）自己的对话格式，\n并且是「思考强度」(--chat-template-kwargs) 生效的前提。'))
        grid.addWidget(self.check_jinja, 2, 0, 1, 2)

        grid.addWidget(QLabel(t('思考强度:')), 2, 2)
        self.combo_reasoning = QComboBox()
        for _name, _val in ((t('不设置'), ""), (t('低 (low)'), "low"),
                            (t('中 (medium)'), "medium"), (t('高 (high)'), "high")):
            self.combo_reasoning.addItem(_name, _val)
        self.combo_reasoning.setToolTip(
            t('传给对话模板的 reasoning_effort 变量（--chat-template-kwargs）。\nQwen3 等支持思考的模型用它控制「思考深度」：low/medium/high。\n「不设置」= 不传该参数（使用模板默认）。\n需同时勾选「启用 Jinja 模板」才会生效。'))
        grid.addWidget(self.combo_reasoning, 2, 3)

        grid.addWidget(QLabel(t('推理预算:')), 2, 4)
        self.spin_reasoning_budget = QSpinBox()
        self.spin_reasoning_budget.setRange(-1, 1000000)
        self.spin_reasoning_budget.setValue(-1)
        self.spin_reasoning_budget.setSpecialValueText(t('-1 = 不限制'))
        self.spin_reasoning_budget.setToolTip(
            t('思考段最多能消耗的 token 数（--reasoning-budget）。\n模型在 reasoning/thinking 里用完这么多 token 后会被强制收尾、输出正式答案。\n-1 = 不限制（默认）。与「思考强度」是两套机制：一个是软引导，一个是硬上限。'))
        grid.addWidget(self.spin_reasoning_budget, 2, 5)
        self.label_chat_status = QLabel("")
        self.label_chat_status.setStyleSheet("color: #8fd0ff;")
        self.label_chat_status.setToolTip(t('对话模板检测结果（读取模型 GGUF 的 tokenizer.chat_template）：绿色=支持，橙色=不支持/无法检测'))
        grid.addWidget(self.label_chat_status, 2, 6, 1, 2)

        # ---- 第 3 行：启动时行为（残留进程检测 / 端口占用建议）----
        self.check_residual = QCheckBox(t('启动时检测残留进程'))
        self.check_residual.setToolTip(
            t('启动时扫描系统中残留的 llama-server 进程并询问是否清理。\n若在弹窗中勾选了「不再提示」，可在此重新开启。'))
        grid.addWidget(self.check_residual, 3, 0, 1, 4)

        self.check_port_hint = QCheckBox(t('端口被占用时建议更换端口'))
        self.check_port_hint.setToolTip(
            t('启动时若发现配置的端口已被占用，则建议一个可用端口，\n确认后自动更新主界面的端口号。'))
        grid.addWidget(self.check_port_hint, 3, 4, 1, 2)

        self.check_hover_pill = QCheckBox(t('缩到托盘时显示悬浮小窗'))
        self.check_hover_pill.setToolTip(
            t('点 X 收起主窗口后，屏幕右下角显示一个小胶囊：状态圆点 + 实时输出速度(tok/s)。\n鼠标停留展开数据卡片：速度 / CPU / 内存 / GPU 负载 / 显存 / API 接入数 / 模型名；\n单击=展开或收起，拖动=移动位置，双击=返回主界面，右键=菜单（打开主界面/启动模型/停止模型/隐藏图标/退出），✕=停用（可再勾选恢复）。'))
        grid.addWidget(self.check_hover_pill, 3, 6, 1, 2)

        # ---- 「生成参数」分组：每行 4 组 ----
        # 第 0 行末尾：批大小（前三组 上下文预设/上下文长度/预测Token 在 _build_basic）
        self._gen_grid.addWidget(QLabel(t('批大小:')), 0, 6)
        self.spin_batch = QSpinBox()
        self.spin_batch.setRange(1, 16384)
        self.spin_batch.setValue(2048)
        self.spin_batch.setToolTip(t('逻辑批大小（-b），影响 prompt 处理速度。默认 2048 即可。'))
        self._gen_grid.addWidget(self.spin_batch, 0, 7)

        # 第 1 行：并行slots / 采样预设 / 温度 / Top-P
        self._gen_grid.addWidget(QLabel(t('并行slots:')), 1, 0)
        self.spin_slots = QSpinBox()
        self.spin_slots.setRange(-1, 64)
        self.spin_slots.setValue(-1)
        self.spin_slots.setSpecialValueText(t('-1 = 自动'))
        self.spin_slots.setToolTip(t('同时处理的并发请求数（-np）。\n多个客户端同时使用时建议 ≥2；每个 slot 会额外占用上下文内存。\n-1 = 自动。'))
        self._gen_grid.addWidget(self.spin_slots, 1, 1)

        self._gen_grid.addWidget(QLabel(t('采样预设:')), 1, 2)
        self.combo_sampling = QComboBox()
        for name, _v in SAMPLING_PRESETS:
            self.combo_sampling.addItem(name)
        self.combo_sampling.setToolTip(
            t('一键应用一组采样参数（温度/Top-P/Top-K/重复惩罚）。\n严谨=低温度适合写代码/翻译；均衡=日常对话；创意=高温度适合写作/脑洞。\n手动修改任一采样参数后会自动回到「自定义」。'))
        self._gen_grid.addWidget(self.combo_sampling, 1, 3)

        self._gen_grid.addWidget(QLabel(t('温度:')), 1, 4)
        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(0.0, 2.0)
        self.spin_temp.setSingleStep(0.05)
        self.spin_temp.setValue(0.8)
        self.spin_temp.setToolTip(t('温度（--temp）：控制随机性/创造力。\n越低越保守严谨（0 = 每次都选最可能的词，趋于复读）；\n越高越发散创意（可能胡言乱语）。\n建议 0.3~1.2。'))
        self._gen_grid.addWidget(self.spin_temp, 1, 5)

        self._gen_grid.addWidget(QLabel("Top-P:"), 1, 6)
        self.spin_topp = QDoubleSpinBox()
        self.spin_topp.setRange(0.0, 1.0)
        self.spin_topp.setSingleStep(0.05)
        self.spin_topp.setValue(0.95)
        self.spin_topp.setToolTip(t('核采样（--top-p）：只从累计概率达到该值的候选词中选。\n0.95 = 默认；1.0 = 关闭；越小越保守。'))
        self._gen_grid.addWidget(self.spin_topp, 1, 7)

        # 第 2 行：Top-K / 重复惩罚 / GPU层数 / KV缓存(K/V)
        self._gen_grid.addWidget(QLabel("Top-K:"), 2, 0)
        self.spin_topk = QSpinBox()
        self.spin_topk.setRange(0, 200)
        self.spin_topk.setValue(40)
        self.spin_topk.setSpecialValueText(t('0 = 默认'))
        self.spin_topk.setToolTip(t('（--top-k）：只从概率最高的前 K 个候选词中选。\n40 = 默认；0 = 关闭；越小越保守。'))
        self._gen_grid.addWidget(self.spin_topk, 2, 1)

        self._gen_grid.addWidget(QLabel(t('重复惩罚:')), 2, 2)
        self.spin_rp = QDoubleSpinBox()
        self.spin_rp.setRange(0.0, 2.0)
        self.spin_rp.setSingleStep(0.1)
        self.spin_rp.setValue(1.0)
        self.spin_rp.setSpecialValueText(t('0 = 默认'))
        self.spin_rp.setToolTip(t('重复惩罚（--repeat-penalty）。\n>1 抑制重复输出，有助于缓解「无限复读/幻觉循环」；\n1.0 = 关闭；建议 1.0~1.3。'))
        self._gen_grid.addWidget(self.spin_rp, 2, 3)

        self._gen_grid.addWidget(QLabel(t('GPU层数:')), 2, 4)
        self.combo_ngl = QComboBox()
        self.combo_ngl.setEditable(True)
        self.combo_ngl.addItems(["all", "auto", "0", "1", "10", "20", "32", "40", "64"])
        self.combo_ngl.setToolTip(
            t('卸载到 GPU 显存中的层数（-ngl）。\nall = 尽可能全部放入显存；auto = 自动判断；0 = 纯 CPU 运行；也可填具体层数。\n与多显卡部署不冲突：ngl 决定总共卸载多少层，\n-ts/-sm（多显卡区）再决定这些层如何在多张卡之间分配。'))
        self._gen_grid.addWidget(self.combo_ngl, 2, 5)

        # ---- KV 缓存 K/V：从「高级参数」移入「生成参数」----
        self.combo_kvc_k = QComboBox()
        self.combo_kvc_k.addItems(KV_CACHE_TYPES)
        self.combo_kvc_k.setCurrentText("f16")
        self.combo_kvc_k.setToolTip(
            t('KV 缓存 K（Key）部分的量化类型，对应参数 -ctk，可与 V 独立设置。\nf16 = 默认质量好；q8_0/q4_0 = 更省显存但精度略降；f32 = 最占显存。'))
        self.combo_kvc_v = QComboBox()
        self.combo_kvc_v.addItems(KV_CACHE_TYPES)
        self.combo_kvc_v.setCurrentText("f16")
        self.combo_kvc_v.setToolTip(
            t('KV 缓存 V（Value）部分的量化类型，对应参数 -ctv，可与 K 独立设置。\nK/V 可分别选不同精度；常见做法：K 用 q8_0、V 用 f16，兼顾精度与显存。'))
        kv_box = QWidget()
        kv_lay = QHBoxLayout(kv_box)
        kv_lay.setContentsMargins(0, 0, 0, 0)
        kv_lay.setSpacing(4)
        kv_lay.addWidget(self.combo_kvc_k, 1)
        kv_lay.addWidget(self.combo_kvc_v, 1)
        kv_label = QLabel(t('KV缓存K/V:'))
        kv_label.setToolTip(t('KV 缓存量化类型（K=-ctk / V=-ctv），可分别设置；\n常见做法：K 用 q8_0、V 用 f16，兼顾精度与显存。'))
        self._gen_grid.addWidget(kv_label, 2, 6)
        self._gen_grid.addWidget(kv_box, 2, 7)

        lay.addLayout(grid)

    def _build_gpu(self, lay):
        """多显卡设置面板（功能 3）。"""
        row0 = QHBoxLayout()
        self.btn_detect_gpus = QPushButton(t('检测 GPU'))
        self.btn_detect_gpus.setToolTip(
            t('运行 llama-server --list-devices 列出本机可用设备（CUDA0/CUDA1…），\n勾选要参与计算的显卡；只勾一张 = 指定只用该卡，多张 = 拆分到多卡。'))
        row0.addWidget(self.btn_detect_gpus)
        self.label_gpus = QLabel(t('尚未检测'))
        self.label_gpus.setStyleSheet("color: #8fd0ff;")
        row0.addWidget(self.label_gpus, 1)
        lay.addLayout(row0)

        # GPU 复选框容器（检测后动态填充）
        self.gpu_panel = QWidget()
        self.gpu_layout = QHBoxLayout(self.gpu_panel)
        self.gpu_layout.setContentsMargins(4, 2, 4, 2)
        self.gpu_checks = []   # [QCheckBox]，data = 设备名（如 CUDA0）
        lay.addWidget(self.gpu_panel)

        # ---- A5: 每卡权重分配（检测后动态生成；row 0 为自动分配按钮）----
        self.gpu_ratio_panel = QWidget()
        self.gpu_ratio_layout = QGridLayout(self.gpu_ratio_panel)
        self.gpu_ratio_layout.setHorizontalSpacing(8)
        self.gpu_ratio_layout.setVerticalSpacing(6)
        self.gpu_ratio_spins = []     # [QDoubleSpinBox]，每张检测到的卡一个
        self._gpu_ratio_labels = []   # 对应的 QLabel（重建时清理用）
        self.btn_auto_split = QPushButton(t('按显存自动分配'))
        self.btn_auto_split.setEnabled(False)
        self.btn_auto_split.setToolTip(
            t('检测 GPU（≥2 张且可用 nvidia-smi）后可用：\n查询每张卡总显存，按比例换算成整数权重填入 tensor-split。'))
        self.btn_auto_split.clicked.connect(self._auto_split_by_vram)
        self.gpu_ratio_layout.addWidget(self.btn_auto_split, 0, 0)
        self.gpu_ratio_panel.setVisible(False)
        lay.addWidget(self.gpu_ratio_panel)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.addWidget(QLabel(t('拆分模式:')), 0, 0)
        self.combo_split_mode = QComboBox()
        for m in SPLIT_MODES:
            self.combo_split_mode.addItem(m)
        self.combo_split_mode.setCurrentText("layer")
        self.combo_split_mode.setToolTip(
            t('多卡拆分方式（-sm）：\n· layer = 按层切分（默认，KV 也跨卡）；\n· row = 按行并行切分权重；\n· tensor = 张量级切分（实验性）；\n· none = 只用单卡。'))
        grid.addWidget(self.combo_split_mode, 0, 1)

        grid.addWidget(QLabel("tensor-split:"), 0, 2)
        self.edit_tensor_split = QLineEdit()
        self.edit_tensor_split.setPlaceholderText(t('如 3,1（留空=均分）'))
        self.edit_tensor_split.setToolTip(
            t('各 GPU 的算力权重比例（-ts），逗号分隔，例如两张卡写 3,1。\n显存差异大时建议按显存比例填写；留空 = llama.cpp 自动均分。'))
        grid.addWidget(self.edit_tensor_split, 0, 3)

        grid.addWidget(QLabel(t('主GPU:')), 0, 4)
        self.spin_main_gpu = QSpinBox()
        self.spin_main_gpu.setRange(0, 63)
        self.spin_main_gpu.setValue(0)
        self.spin_main_gpu.setToolTip(
            t('主 GPU 索引（-mg）：中间结果/KV 的归属卡，一般保持 0。'))
        grid.addWidget(self.spin_main_gpu, 0, 5)

        tip = QLabel(
            t('提示：勾选 ≥2 张显卡后才会添加 -dev/-sm/-ts 参数；单卡/不勾选 = 行为与原来一致（自动选卡）。\nGPU层数(-ngl)与多显卡部署不冲突：-ngl 决定总共卸载多少层到显存，\n-ts(tensor-split)/-sm(拆分模式) 再决定这些层如何在多张卡之间分配；-ngl all = 全部放卡上。'))
        tip.setStyleSheet("color: #888;")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addLayout(grid)
