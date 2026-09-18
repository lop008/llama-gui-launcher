"""模型使用统计（功能 9）：打开次数 / 使用时长 / 输入输出 token，按时/日/月聚合。

- 存储：数据目录下 stats.json（JSON，线程安全，原子写入）；
- Token 来源：解析 llama-server 标准日志行
    prompt eval time = ... ms / N tokens   （输入/prompt）
    eval time        = ... ms / M tokens   （输出/生成）
  该格式与 --metrics 无关，任何版本的服务端都适用。
"""
import json
import os
import re
import threading
import time

STATS_FILE = "stats.json"

# ------------------------------------------------------------------ 日志解析
RE_PROMPT = re.compile(r'prompt eval time\s*=\s*[\d.]+\s*ms\s*/\s*(\d+)\s*tokens')
RE_GEN = re.compile(r'(?<!prompt )eval time\s*=\s*[\d.]+\s*ms\s*/\s*(\d+)\s*tokens')


def parse_log_line(line):
    """解析一行 llama-server 日志。

    返回 ("prompt", n) / ("gen", n)；非统计行返回 None。
    """
    if not line:
        return None
    m = RE_PROMPT.search(line)
    if m:
        return "prompt", int(m.group(1))
    m = RE_GEN.search(line)
    if m:
        return "gen", int(m.group(1))
    return None


# ------------------------------------------------------------------ 存储
def _now_ts():
    return time.time()


class StatsStore:
    def __init__(self, data_dir):
        self._path = os.path.join(data_dir or ".", STATS_FILE)
        self._lock = threading.Lock()
        self._data = {"version": 1, "models": {}}
        self._load()

    # ------------------------------------------------------------- 读写
    def _load(self):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("models"), dict):
                self._data = d
        except Exception:
            pass

    def save(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
                tmp = self._path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False)
                os.replace(tmp, self._path)
            except Exception:
                pass

    def _model_entry(self, name):
        m = self._data["models"].get(name)
        if m is None:
            m = {"opens": 0, "seconds": 0.0, "in_tokens": 0, "out_tokens": 0,
                 "hour": {}, "day": {}, "month": {}}
            self._data["models"][name] = m
        return m

    @staticmethod
    def _bucket_keys(ts):
        t = time.localtime(ts)
        return (time.strftime("%Y-%m-%d %H", t),
                time.strftime("%Y-%m-%d", t),
                time.strftime("%Y-%m", t))

    # ------------------------------------------------------------- 记录
    def record_open(self, model):
        """一次「启动服务」计为一次打开。"""
        if not model:
            return
        with self._lock:
            m = self._model_entry(model)
            m["opens"] += 1
            hk, dk, mk = self._bucket_keys(_now_ts())
            for store, key in ((m["hour"], hk), (m["day"], dk), (m["month"], mk)):
                b = store.setdefault(key, {"opens": 0, "seconds": 0.0, "in_tokens": 0, "out_tokens": 0})
                b["opens"] += 1

    def add_usage(self, model, seconds=0.0, in_tokens=0, out_tokens=0):
        """累计使用时长 / token（服务运行期间周期性调用）。"""
        if not model:
            return
        with self._lock:
            m = self._model_entry(model)
            m["seconds"] += float(seconds or 0.0)
            m["in_tokens"] += int(in_tokens or 0)
            m["out_tokens"] += int(out_tokens or 0)
            hk, dk, mk = self._bucket_keys(_now_ts())
            for store, key in ((m["hour"], hk), (m["day"], dk), (m["month"], mk)):
                b = store.setdefault(key, {"opens": 0, "seconds": 0.0, "in_tokens": 0, "out_tokens": 0})
                b["seconds"] += float(seconds or 0.0)
                b["in_tokens"] += int(in_tokens or 0)
                b["out_tokens"] += int(out_tokens or 0)

    # ------------------------------------------------------------- 查询
    @staticmethod
    def _allowed_days(scope):
        """返回时间范围覆盖的日期集合（YYYY-MM-DD）；None=不限。

        - today  = 今天
        - week   = 最近 7 天（含今天）
        - month  = 本月（当月 1 号 ~ 今天，按自然月而非滚动窗口）
        """
        if scope == "all":
            return None
        from datetime import date, timedelta

        today = date.today()
        days = set()
        if scope == "month":
            d = today.replace(day=1)
            while d <= today:
                days.add(d.strftime("%Y-%m-%d"))
                d += timedelta(days=1)
        else:
            span = {"today": 1, "week": 7}.get(scope, 1)
            for i in range(span):
                days.add((today - timedelta(days=i)).strftime("%Y-%m-%d"))
        return days

    @staticmethod
    def _bucket_day(key, granularity):
        """时间桶键对应的日期（YYYY-MM-DD）；月粒度返回其月份前缀。"""
        if granularity == "hour":
            return key[:10]          # "YYYY-MM-DD HH" -> 日期部分
        if granularity == "day":
            return key               # "YYYY-MM-DD"
        return key + "-01"           # month: "YYYY-MM" -> 月初（仅用于月份比较）

    def summary(self, scope="all"):
        """按模型汇总（受时间范围过滤）。"""
        allowed = self._allowed_days(scope)
        rows = []
        with self._lock:
            for name, m in sorted(self._data["models"].items()):
                if allowed is None:
                    opens, seconds = m["opens"], m["seconds"]
                    itok, otok = m["in_tokens"], m["out_tokens"]
                else:
                    opens = seconds = itok = otok = 0
                    for key, b in m.get("day", {}).items():
                        if key in allowed:
                            opens += b["opens"]; seconds += b["seconds"]
                            itok += b["in_tokens"]; otok += b["out_tokens"]
                rows.append({"model": name, "opens": opens, "seconds": float(seconds),
                             "in_tokens": int(itok), "out_tokens": int(otok)})
        rows.sort(key=lambda r: (-(r["in_tokens"] + r["out_tokens"]), r["model"]))
        return rows

    def breakdown(self, granularity="day", scope="all"):
        """按时间桶汇总（跨模型聚合）。granularity: hour/day/month。"""
        allowed = self._allowed_days(scope)
        agg = {}
        with self._lock:
            for name, m in self._data["models"].items():
                store = m.get(granularity if granularity in ("hour", "day", "month") else "day", {})
                for key, b in store.items():
                    if allowed is not None:
                        day_part = self._bucket_day(key, granularity)
                        if granularity == "month":
                            # 月粒度：保留与允许日期相交的月份
                            if not any(d[:7] == key for d in allowed):
                                continue
                        elif day_part not in allowed:
                            continue
                    a = agg.setdefault(key, {"opens": 0, "seconds": 0.0, "in_tokens": 0, "out_tokens": 0})
                    a["opens"] += b.get("opens", 0)
                    a["seconds"] += float(b.get("seconds", 0))
                    a["in_tokens"] += int(b.get("in_tokens", 0))
                    a["out_tokens"] += int(b.get("out_tokens", 0))
        rows = [{"key": k, **v} for k, v in agg.items()]
        rows.sort(key=lambda r: r["key"])
        # 时间范围「全部」时，小时粒度只保留最近 96 个桶，避免过长
        if scope == "all" and granularity == "hour" and len(rows) > 96:
            rows = rows[-96:]
        return rows


# ------------------------------------------------------------------ 格式化
def human_duration(seconds):
    s = int(float(seconds or 0))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h} 小时 {m} 分"
    if m:
        return f"{m} 分 {sec} 秒"
    return f"{sec} 秒"


def human_tokens(n):
    n = int(n or 0)
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if abs(n) >= 1000:
        return f"{n / 1000:.1f}K"
    return str(n)
