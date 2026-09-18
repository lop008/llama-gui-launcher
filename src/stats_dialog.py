"""模型统计独立界面（功能 9）。

打开次数 / 使用时长 / 输入输出 token，支持 时/日/月 粒度与时间范围筛选。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .usage_stats import StatsStore, human_duration, human_tokens


class StatsDialog(QDialog):
    def __init__(self, store: StatsStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("模型统计")
        self.resize(860, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        # ---- 工具行：时间范围 + 粒度 + 刷新/导出 ----
        bar = QHBoxLayout()
        bar.addWidget(QLabel("时间范围:"))
        self.combo_scope = QComboBox()
        for name in ("全部", "今天", "最近一周", "本月"):
            self.combo_scope.addItem(name)
        self.combo_scope.setCurrentText("全部")
        self.combo_scope.currentIndexChanged.connect(self.refresh)

        bar.addWidget(QLabel("时间粒度:"))
        self.combo_gran = QComboBox()
        for name in ("按小时", "按日", "按月"):
            self.combo_gran.addItem(name)
        self.combo_gran.setCurrentText("按日")
        self.combo_gran.currentIndexChanged.connect(self.refresh)

        bar.addStretch(1)
        btn_export = QPushButton("导出 CSV")
        btn_export.setToolTip("把当前「模型统计」表导出为 CSV 文件（可用 Excel 打开）")
        btn_export.clicked.connect(self.export_csv)
        bar.addWidget(btn_export)
        btn_refresh = QPushButton("刷新")
        btn_refresh.clicked.connect(self.refresh)
        bar.addWidget(btn_refresh)
        root.addLayout(bar)

        # ---- 表 1：按模型汇总 ----
        root.addWidget(QLabel("<b>模型统计</b>（打开次数 / 使用时长 / 输入·输出 token）"))
        self.table_model = QTableWidget(0, 5)
        self.table_model.setHorizontalHeaderLabels(
            ["模型", "打开次数", "使用时长", "输入 Token", "输出 Token"])
        self._setup_table(self.table_model, [380, 90, 140, 120, 120])
        root.addWidget(self.table_model, 3)

        # ---- 表 2：时间明细 ----
        root.addWidget(QLabel("<b>时间明细</b>（所选粒度下，全部模型合计）"))
        self.table_time = QTableWidget(0, 5)
        self.table_time.setHorizontalHeaderLabels(
            ["时间", "打开次数", "使用时长", "输入 Token", "输出 Token"])
        self._setup_table(self.table_time, [180, 90, 140, 120, 120])
        root.addWidget(self.table_time, 3)

        tip = QLabel("说明：token 数来自 llama-server 运行日志（prompt eval / eval time），"
                     "时长为服务实际运行时间；数据保存在数据目录 stats.json。")
        tip.setStyleSheet("color: #888;")
        tip.setWordWrap(True)
        root.addWidget(tip)

    @staticmethod
    def _setup_table(t, widths):
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(True)
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i, w in enumerate(widths):
            t.setColumnWidth(i, w)

    # ------------------------------------------------------------- 数据填充
    def _scope(self):
        return ("all", "today", "week", "month")[self.combo_scope.currentIndex()]

    def _granularity(self):
        return ("hour", "day", "month")[self.combo_gran.currentIndex()]

    @staticmethod
    def _fill(t, rows, cols_fmt):
        t.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, (text, align) in enumerate(cols_fmt(row)):
                it = QTableWidgetItem(str(text))
                if align:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                t.setItem(r, c, it)

    def refresh(self):
        scope, gran = self._scope(), self._granularity()
        # 表 1：按模型
        rows = self.store.summary(scope)
        self._fill(self.table_model, rows, lambda r: [
            (r["model"], None), (r["opens"], True), (human_duration(r["seconds"]), True),
            (f"{r['in_tokens']:,}", True), (f"{r['out_tokens']:,}", True)])
        # 表 2：时间明细
        trows = self.store.breakdown(gran, scope)
        label_fmt = {"hour": lambda k: k.replace(" ", " "), "day": lambda k: k,
                     "month": lambda k: k}
        self._fill(self.table_time, trows, lambda r: [
            (label_fmt[gran](r["key"]), None), (r["opens"], True),
            (human_duration(r["seconds"]), True),
            (f"{r['in_tokens']:,}", True), (f"{r['out_tokens']:,}", True)])

    # ------------------------------------------------------------- 导出
    def export_csv(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "导出统计 CSV", "模型统计.csv", "CSV 文件 (*.csv);;所有文件 (*.*)")
        if not path:
            return
        try:
            rows = self.store.summary(self._scope())
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write("模型,打开次数,使用时长(秒),输入Token,输出Token\n")
                for r in rows:
                    f.write(f"{r['model']},{r['opens']},{int(r['seconds'])},"
                            f"{r['in_tokens']},{r['out_tokens']}\n")
            QMessageBox.information(self, "完成", f"已导出: {path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出失败: {e}")
