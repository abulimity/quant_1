# -*- coding: utf-8 -*-
"""单文件看板的数据载荷：把一个 run 重建成 `reports/front-design` 的 49 键契约。

前端（`reports/front-design/index.html` 及其尾部 `app.js`）只认 `window.__REPORT_DATA__`
的 49 个顶层键，每个字段的精度也由前端写死。本模块只做「从 run 产物重算」：

    ReportContext   equity / benchmark / weights / holdings / trades / diary /
                    ticker_signals / stages / classification / params / metrics
    run_dir/derived performance · costs · events · roundtrips · liquidity ·
                    stages · relative · extremes
    reports_dir     跨 run 汇总：sensitivity/*.json、families/*/summary.json、
                    ablation.json、assumption_sensitivity.json、oos_check.json、
                    attribution.json、exposure.json、data_quality.json

不编造数字：任何键都来自上述来源，缺失时返回空结构而不是占位值。
与设计稿的已知差异（6 个 ticker 的类分组、扫描批次、DSR 家族等）记在
`reports/回测报告.md` 的「看板数据口径」一节。
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from etf_rotation.report import dashboard_tables as TABLES
from etf_rotation.report.context import ReportContext

DASHBOARD_VERSION = 1

# 事件类型英文 → 中文（前端按中文取 icon 与配色）
EVENT_TYPE_CN = {
    "switch": "换仓",
    "overheat": "过热清零",
    "vol_cap": "波动上限缩放",
    "defensive": "防守重选",
    "cross_asset": "跨资产腿切换",
}
# primary 取值优先级（与设计稿计数一致：换仓 287 / 跨资产 199 / 过热 31 / 上限 2）
EVENT_PRIMARY_ORDER = ["switch", "overheat", "vol_cap", "defensive", "cross_asset"]

# 类分组口径：黄金/纳指两只腿单列，bond/money 归防守，其余有持仓归风险
CLASS_ORDER = ["risk", "nasdaq", "gold", "defensive", "other"]
EXPO_KEYS = ["risk", "nasdaq", "gold", "defensive", "other", "cash"]

REGIME_CODE = {"bear": 0, "range": 1, "bull": 2}
REGIME_NAME = {0: "bear", 1: "range", 2: "bull"}

# 复用设计稿的参数行定义：group/key/role/default/sensitivity
PARAMS_META = TABLES.PARAMS_META
KPI_TABLE_META = TABLES.KPI_TABLE_META
ISSUES = TABLES.ISSUES
EVENT_RULE = TABLES.EVENT_RULE
PARAM_SNAPSHOT_KEYS = TABLES.PARAM_SNAPSHOT_KEYS

SWEEP_LABELS = {
    "dedupe.corr_threshold": "相关性去重阈值",
    "dedupe.max_holdings": "最大持仓数",
    "defensive.max_vol_60d": "防守仓波动上限",
    "defensive.top_n": "防守仓持仓数",
    "market_state.alpha": "市场状态平滑 α",
    "market_state.bull_threshold": "牛市阈值",
    "risk.vol_target_risk": "风险腿波动目标",
    "trend.windows": "趋势窗口 (m21/m60)",
}
SWEEP_ORDER = [
    "dedupe.corr_threshold",
    "dedupe.max_holdings",
    "defensive.max_vol_60d",
    "defensive.top_n",
    "market_state.alpha",
    "market_state.bull_threshold",
    "risk.vol_target_risk",
    "trend.windows",
]
# sensitivity/*.json 文件名 → 参数键
SWEEP_FILES = {
    "dedupe.corr_threshold": "dedupe_corr_threshold",
    "dedupe.max_holdings": "dedupe_max_holdings",
    "defensive.max_vol_60d": "defensive_max_vol_60d",
    "defensive.top_n": "defensive_top_n",
    "market_state.alpha": "market_state_alpha",
    "market_state.bull_threshold": "market_state_bull_threshold",
    "risk.vol_target_risk": "risk_vol_target_risk",
    "trend.windows": "trend_windows",
}

ATTR_CN = {"风险": "risk", "纳指": "nasdaq", "黄金": "gold", "防守": "defensive"}

# 事件详情「四步」口径：低于 DUST 视为无仓；同侧变动小于 MIN_DELTA 视为取整噪声；
# 每类最多列 DETAIL_CAP 条（按 |d| 降序）。
DUST = 0.001
MIN_DELTA = 0.001
DETAIL_CAP = 6
# 持仓偏差明细的显著性阈值（约 1bp）
POSTDEV_MIN = 1e-4


# ---------------------------------------------------------------- 数值工具


def _r(value, ndigits):
    """四舍五入到 ndigits 位；NaN/inf → None，0 统一返回 0.0（避免 -0.0）。"""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    if v == 0.0:
        return 0.0
    return round(v, ndigits)


def _rl(values, ndigits):
    return [_r(v, ndigits) for v in values]


def _int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_default(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return _r(obj, 12)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp,)):
        return obj.strftime("%Y-%m-%d")
    raise TypeError(f"不可序列化: {type(obj)!r}")


def dumps(payload):
    """紧凑 JSON（体积优先，前端 JSON.parse 不关心缩进）。"""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                      default=_json_default, allow_nan=False)


# ---------------------------------------------------------------- 构建器


class DashboardBuilder:
    """一次 run → 49 键载荷。所有中间量懒加载并缓存。"""

    def __init__(self, ctx: ReportContext, run_dir: Path, reports_dir: Path):
        self.ctx = ctx
        self.run_dir = Path(run_dir)
        self.reports = Path(reports_dir)
        self.derived = self.run_dir / "derived"
        if not self.derived.exists():
            alt = self.reports / "derived"
            self.derived = alt if alt.exists() else self.derived
        self._cache = {}

    # ------------------------------------------------------------ 基础面板

    def _c(self, key, loader):
        if key not in self._cache:
            self._cache[key] = loader()
        return self._cache[key]

    @property
    def eq(self) -> pd.DataFrame:
        return self.ctx.equity

    @property
    def bm(self) -> pd.DataFrame:
        return self.ctx.benchmark

    @property
    def w(self) -> pd.DataFrame:
        return self._c("w", lambda: self.ctx.weights.fillna(0.0))

    @property
    def h(self) -> pd.DataFrame:
        return self._c("h", lambda: self.ctx.holdings.fillna(0.0))

    @property
    def diary(self) -> pd.DataFrame:
        return self.ctx.diary

    @property
    def tsig(self) -> pd.DataFrame:
        return self.ctx.ticker_signals

    @property
    def dates(self) -> list[str]:
        return self._c("dates", lambda: [str(ts.date()) for ts in self.eq.index])

    @property
    def pos(self) -> dict[str, int]:
        return self._c("pos", lambda: {d: i for i, d in enumerate(self.dates)})

    @property
    def nav(self) -> pd.Series:
        return self.eq["nav"]

    @property
    def ret(self) -> pd.Series:
        return self.eq["returns"]

    @property
    def hs(self) -> pd.Series:
        return self.bm["hs300"]

    @property
    def rb(self) -> pd.Series:
        return self._c("rb", lambda: self.hs.pct_change())

    @property
    def total_w(self) -> pd.Series:
        return self._c("total_w", lambda: self.w.sum(axis=1))

    @property
    def turnover(self) -> pd.Series:
        def build():
            t = self.w.diff().abs().sum(axis=1) / 2.0
            t.iloc[0] = 0.0
            return t.fillna(0.0)
        return self._c("turnover", build)

    def derived_json(self, name):
        return self._c(f"d_{name}", lambda: json.loads(
            (self.derived / f"{name}.json").read_text(encoding="utf-8")))

    def report_json(self, name):
        return self._c(f"r_{name}", lambda: json.loads(
            (self.reports / f"{name}.json").read_text(encoding="utf-8")))

    # ------------------------------------------------------------ 类分组

    def cls_of(self, ticker: str) -> str:
        params = self.ctx.params
        if ticker == params.get("gold_etf"):
            return "gold"
        if ticker == params.get("nasdaq_etf"):
            return "nasdaq"
        raw = self.ctx.classification.get(ticker)
        if raw in ("bond", "money"):
            return "defensive"
        peak = self._peak_weight().get(ticker, 0.0)
        return "risk" if peak > 1e-15 else "other"

    def _peak_weight(self) -> dict:
        def build():
            if self.w.empty:
                return {}
            return {k: float(v) for k, v in self.w.max(axis=0).items()}
        return self._c("peak_w", build)

    def cls_map(self) -> dict:
        def build():
            names = set()
            for frame in (self.w, self.h):
                if frame is not None and not frame.empty:
                    names.update(frame.columns)
            if self.tsig is not None:
                names.update(self.tsig.index.get_level_values(1).unique())
            return {t: self.cls_of(t) for t in sorted(names)}
        return self._c("cls_map", build)

    # ============================================================ 49 键

    # 1 ── meta
    def meta(self) -> dict:
        m = self.ctx.meta
        params = self.ctx.params
        dq = self.dataQuality()
        dsr = self.dsr()
        created = m.get("created_at")
        generated = None
        if created:
            ts = pd.Timestamp(created)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            generated = ts.tz_convert("Asia/Shanghai").strftime("%Y-%m-%d %H:%M:%S")
        start = self.dates[0]
        end = self.dates[-1]
        bps = _int(params.get("costs.one_side_bps"))
        execution = ("T+1 开盘（OpenRebalance，高开≥1% 顺延、停牌跳过）"
                     if str(m.get("execution")) == "open"
                     else "T 日收盘（CloseRebalance）")
        return {
            "run_id": str(m.get("run_id") or self.ctx.run_id),
            "signal_id": str(m.get("signal_id") or ""),
            "version": str(m.get("version") or ""),
            "git_sha": str(m.get("git_sha") or ""),
            "snapshot": str(m.get("data_snapshot_id") or ""),
            "generated": generated,
            "start": start,
            "end": end,
            "days": int((pd.Timestamp(end) - pd.Timestamp(start)).days),
            "n_days": len(self.dates),
            "execution": execution,
            "cost_bps": bps,
            "cash_rate": _r(params.get("costs.cash_rate_annual"), 6),
            "n_etfs": dq.get("n_etfs"),
            "n_delisted": dq.get("n_delisted"),
            "n_tickers": self._c("n_tickers", lambda: int(
                self.tsig.index.get_level_values(1).nunique() if self.tsig is not None else 0)),
            "n_trades": int(len(self.ctx.trades)) if self.ctx.trades is not None else 0,
            "nav_end": _r(self.nav.iloc[-1], 6),
            "total_fees": _r(self.ctx.metrics.get("total_fees"), 6),
            "params_brief": self._params_brief(),
            "notice": "本期报告相对研报为「同量级复现」，不是精确复制。",
            "source": "reports/ · equity / benchmark / weights / holdings / trades / signals / derived",
            "dsr": dsr.get("value"),
            "python": "3.10",
        }

    def _params_brief(self) -> str:
        p = self.ctx.params
        windows = p.get("trend.windows") or []
        win = "/".join(str(_int(x)) for x in windows) if windows else "—"

        def num(key, nd=2):
            v = p.get(key)
            if v is None:
                return "—"
            s = f"{float(v):.{nd}f}"
            return s.replace("-", "\u2212")

        parts = [
            win,
            f"corr {num('dedupe.corr_threshold')}",
            f"max {_int(p.get('dedupe.max_holdings'))}",
            f"bull {num('market_state.bull_threshold')}",
            f"bear {num('market_state.bear_threshold')}",
            f"risk {num('risk.vol_target_risk')}",
        ]
        return " · ".join(parts)

    # 2 ── kpi
    def kpi(self) -> dict:
        return self._c("kpi", self._build_kpi)

    def _build_kpi(self):
        met = self.ctx.metrics
        nav = self.nav
        peak = nav.cummax()
        uw = nav < peak
        longest, cur = 0, 0
        for flag in uw.to_numpy():
            cur = cur + 1 if flag else 0
            longest = max(longest, cur)
        diary = self.diary
        s = {
            "cagr": _r(met.get("ann_return"), 6),
            "vol": _r(met.get("ann_vol"), 6),
            "sharpe": _r(met.get("sharpe"), 4),
            "sortino": _r(met.get("sortino"), 4),
            "mdd": _r(met.get("max_drawdown"), 6),
            "calmar": _r(met.get("calmar"), 4),
            "turnover": _r(met.get("turnover"), 5),
            "longest_uw": int(longest),
            "uw_share": _r(float(uw.mean()), 4),
            "avg_exposure": _r(diary["total_weight"].mean() if diary is not None else None, 4),
        }
        hs = self.hs
        rb = self.rb
        days = (self.eq.index[-1] - self.eq.index[0]).days
        cagr = (hs.iloc[-1] / hs.iloc[0]) ** (365.25 / days) - 1 if days else None
        vol = rb.std() * math.sqrt(252)
        down = rb[rb < 0].std()
        mdd = (hs / hs.cummax() - 1).min()
        b = {
            "cagr": _r(cagr, 6),
            "vol": _r(vol, 5),
            "sharpe": _r(rb.mean() / rb.std() * math.sqrt(252), 4),
            "sortino": _r(rb.mean() * 252 / (down * math.sqrt(252)), 3),
            "mdd": _r(mdd, 6),
            "calmar": _r(cagr / abs(mdd), 4) if mdd else None,
            "end_date": self.dates[-1],
        }
        rel_raw = self.derived_json("relative").get("summary", {})
        rel = {
            "geo": _r(rel_raw.get("excess_cagr"), 6),
            "arith": _r(rel_raw.get("excess_arith"), 6),
            "te": _r(rel_raw.get("tracking_error"), 6),
            "ir": _r(rel_raw.get("information_ratio"), 4),
            "beta": _r(rel_raw.get("beta"), 4),
            "corr": _r(rel_raw.get("correlation"), 3),
            "up": _r(rel_raw.get("up_capture"), 4),
            "down": _r(rel_raw.get("down_capture"), 4),
            "mwin": _r(rel_raw.get("monthly_win_rate"), 4),
            "months": _int(rel_raw.get("n_months")),
        }
        return {"s": s, "b": b, "rel": rel}

    # 3 ── kpiTable
    def kpiTable(self) -> list:
        k = self.kpi()
        s, b, rel = k["s"], k["b"], k["rel"]
        pairs = {
            "年化收益 (CAGR)": (s["cagr"], b["cagr"]),
            "年化波动": (s["vol"], b["vol"]),
            "Sharpe": (s["sharpe"], b["sharpe"]),
            "Sortino": (s["sortino"], b["sortino"]),
            "最大回撤": (s["mdd"], b["mdd"]),
            "Calmar": (s["calmar"], b["calmar"]),
            "几何超额": (rel["geo"], None),
            "算术超额": (rel["arith"], None),
            "跟踪误差": (rel["te"], None),
            "信息比率 IR": (rel["ir"], None),
            "Beta": (rel["beta"], 1.0),
            "相关系数": (rel["corr"], 1.0),
            "上行捕获": (rel["up"], 1.0),
            "下行捕获": (rel["down"], 1.0),
            "月胜率": (rel["mwin"], 0.5),
            "最长水下 (交易日)": (float(s["longest_uw"]), None),
        }
        rows = []
        for name, fmt, verdict in KPI_TABLE_META:
            sv, bv = pairs[name]
            rows.append({"name": name, "s": _r(sv, 4), "b": _r(bv, 4),
                         "fmt": fmt, "verdict": verdict})
        return rows

    # 4 ── params
    def params(self) -> list:
        params = self.ctx.params
        rows = []
        for group, key, role, default, sensitivity in PARAMS_META:
            rows.append({
                "group": group,
                "key": key,
                "value": _fmt_param(params.get(key)),
                "role": role,
                "default": default,
                "sensitivity": sensitivity,
            })
        return rows

    # 5 ── paramSnapshot
    def paramSnapshot(self) -> dict:
        params = self.ctx.params
        out = {}
        for key in PARAM_SNAPSHOT_KEYS:
            out[key] = _plain(params.get(key))
        return out

    # 6 ── series
    def series(self) -> dict:
        return self._c("series", self._build_series)

    def _build_series(self):
        nav, hs, ret, rb = self.nav, self.hs, self.ret, self.rb
        diary = self.diary
        total = self.total_w
        sqrt252 = math.sqrt(252)
        w = self.w

        hhi = (w ** 2).sum(axis=1)
        eff_n = 1.0 / hhi.replace(0.0, np.nan)
        top5 = w.apply(lambda row: row.nlargest(5).sum(), axis=1)

        active = ret - rb
        te = active.rolling(252, min_periods=120).std() * sqrt252
        ir = (active.rolling(252, min_periods=120).mean()
              / active.rolling(252, min_periods=120).std() * sqrt252)
        ex_sharpe = (active.rolling(252, min_periods=252).mean()
                     / active.rolling(252, min_periods=252).std() * sqrt252)
        var = rb.rolling(252, min_periods=120).var()
        beta = ret.rolling(252, min_periods=120).cov(rb) / var
        corr = ret.rolling(252, min_periods=120).corr(rb)

        excess = nav / hs - 1
        excess_dd = (1 + excess) / (1 + excess).cummax() - 1

        dev, dev_sum, dev_max, dev_tk = self._tracking_deviation()

        expo = self._exposure_panel()
        return {
            "dates": self.dates,
            "nav": _rl(nav, 6),
            "bm": _rl(hs, 6),
            "ret": _rl(ret, 5),
            "rb": _rl(rb, 5),
            "dd": _rl(nav / nav.cummax() - 1, 6),
            "vol20": _rl(ret.rolling(20).std() * sqrt252, 5),
            "vol60": _rl(ret.rolling(60).std() * sqrt252, 5),
            "vol252": _rl(ret.rolling(252).std() * sqrt252, 5),
            "score": _rl(diary["comp_score"], 4),
            "riskScale": _rl(diary["risk_scale"], 4),
            "volScale": _rl(diary["vol_scale_risk"], 4),
            "budget": _rl(diary["risk_budget"], 4),
            "totalW": _rl(total, 4),
            "cashW": _rl(1 - total, 4),
            "nCands": [float(_int(v)) for v in diary["n_cands"]],
            "nKept": [float(_int(v)) for v in diary["n_kept"]],
            "exposure": {k: _rl(expo[k], 5) for k in EXPO_KEYS},
            "hhi": _rl(hhi, 5),
            "effN": _rl(eff_n, 4),
            "top5": _rl(top5, 5),
            "rollRet": _rl(nav / nav.shift(252) - 1, 6),
            "rollSharpe": _rl(
                ret.rolling(252, min_periods=252).mean()
                / ret.rolling(252, min_periods=252).std() * sqrt252, 4),
            "beta": _rl(beta, 4),
            "corr": _rl(corr, 4),
            "excess": _rl(excess, 6),
            "excessDD": _rl(excess_dd, 6),
            "ir": _rl(ir, 4),
            "te": _rl(te, 5),
            "exSharpe": _rl(ex_sharpe, 4),
            "regime": [REGIME_CODE.get(str(v), None) for v in diary["regime"]],
            "mad": _rl(dev_sum, 6),
            "madMax": _rl(dev_max, 6),
            "madMaxTicker": [None if pd.isna(v) else str(v) for v in dev_tk],
            "benchmarkStart": self.dates[0],
            "benchmarkEnd": self.dates[-1],
        }

    def _tracking_deviation(self):
        """|持仓 - 目标权重| 逐日偏差（shift(-1) 对齐到次日），最后一行无次日 → None。

        列先按 ticker 名排序，并列最大值时 idxmax 取字典序最小的那只（与设计稿一致）。
        """
        w, h = self.w, self.h
        cols = sorted(set(h.columns) | set(w.columns))
        hh = h.reindex(columns=cols, fill_value=0.0)
        ww = w.reindex(columns=cols, fill_value=0.0)
        dev = (hh.shift(-1) - ww).abs()
        dev.iloc[-1] = np.nan
        sums = dev.sum(axis=1)
        mx = dev.max(axis=1)
        # 全 NaN 行先填 0 再取 idxmax（避免 pandas all-NA FutureWarning），随后用 mx.notna() 抹回
        tk = dev.fillna(0.0).idxmax(axis=1)
        tk = tk.where(mx.notna())
        sums = sums.where(mx.notna())
        return dev, sums, mx, tk

    def _exposure_panel(self) -> dict:
        """类暴露用实际持仓（holdings），现金 = 1 - 持仓合计。"""
        cls = self.cls_map()
        h = self.h
        out = {}
        assigned = pd.Series(0.0, index=h.index)
        for name in ("risk", "nasdaq", "gold", "defensive", "other"):
            cols = [c for c in h.columns if cls.get(c) == name]
            if cols:
                series = h[cols].sum(axis=1)
            else:
                series = pd.Series(0.0, index=h.index)
            out[name] = series
            assigned = assigned + series
        # 持仓合计偶尔略超 1（权重四舍五入残留），现金不可为负
        out["cash"] = (1.0 - assigned).clip(lower=0.0)
        return out

    # 7 ── monthly
    def monthly(self) -> dict:
        return self._c("monthly", self._build_monthly)

    def _build_monthly(self):
        idx = self.eq.index
        years = sorted({int(y) for y in idx.year})
        s_mat, b_mat = [], []
        sr = (1 + self.ret).groupby([idx.year, idx.month]).prod() - 1
        br = (1 + self.rb.fillna(0.0)).groupby([idx.year, idx.month]).prod() - 1
        for y in years:
            s_row, b_row = [], []
            for m in range(1, 13):
                s_row.append(_r(sr.get((y, m)), 6))
                b_row.append(_r(br.get((y, m)), 6))
            s_mat.append(s_row)
            b_mat.append(b_row)
        return {"years": years, "s": s_mat, "b": b_mat}

    # 8 ── months
    def months(self) -> list:
        idx = self.eq.index
        sr = (1 + self.ret).groupby([idx.year, idx.month]).prod() - 1
        br = (1 + self.rb.fillna(0.0)).groupby([idx.year, idx.month]).prod() - 1
        rows = []
        for (y, m), sv in sr.items():
            bv = br.get((y, m))
            rows.append({"y": int(y), "m": int(m), "s": _r(sv, 6), "b": _r(bv, 6),
                         "ex": _r((sv - bv) if bv is not None else None, 6)})
        return rows

    # 9 ── annual
    def annual(self) -> list:
        eq, hs = self.eq, self.hs
        ret = self.ret
        turn = self.turnover
        nav = self.nav
        rows = []
        years = sorted({int(y) for y in eq.index.year})
        prev_nav, prev_hs = 1.0, 1.0
        for y in years:
            mask = eq.index.year == y
            nav_y = nav[mask]
            hs_y = hs[mask]
            r_y = ret[mask]
            ann_ret = nav_y.iloc[-1] / prev_nav - 1
            ann_bm = hs_y.iloc[-1] / prev_hs - 1
            vol = r_y.std() * math.sqrt(252)
            mdd = (nav_y / nav_y.cummax() - 1).min()
            rows.append({
                "year": y,
                "ret": _r(ann_ret, 6),
                "bm": _r(ann_bm, 6),
                "excess": _r(ann_ret - ann_bm, 6),
                "vol": _r(vol, 6),
                "sharpe": _r(r_y.mean() / r_y.std() * math.sqrt(252) if r_y.std() else None, 4),
                "mdd": _r(mdd, 6),
                "turnover": _r(turn[mask].sum(), 5),
                "fees": _r(eq.loc[mask, "fees"].sum(), 6),
                "exposure_end": _r(self.total_w[mask].iloc[-1], 4),
                "cash_end": _r(1 - self.total_w[mask].iloc[-1], 4),
            })
            prev_nav = nav_y.iloc[-1]
            prev_hs = hs_y.iloc[-1]
        return rows

    # 10 ── drawdowns
    def drawdowns(self) -> list:
        perf = self.derived_json("performance")
        eps = sorted(perf.get("episodes", []),
                     key=lambda e: -float(e.get("depth") or 0.0))
        out = []
        for e in eps:
            out.append({
                "peak": e.get("peak_date"),
                "trough": e.get("trough_date"),
                "recover": e.get("recovery_date"),
                "depth": _r(-abs(e.get("depth", 0.0)), 12),
                "length": _int(e.get("duration_days")),
                "recovery_days": _int(e.get("recovery_days")),
                "underwater_days": None,
                "ongoing": not bool(e.get("recovered", True)),
            })
        return out

    # 11 ── longest
    def longest(self) -> dict:
        lg = self.derived_json("performance").get("longest", {})
        return {
            "peak_date": lg.get("peak_date"),
            "trough_date": lg.get("trough_date"),
            "recovery_date": lg.get("recovery_date"),
            "recovered": bool(lg.get("recovered", False)),
            "depth": _r(lg.get("depth"), 12),
            "duration_days": _int(lg.get("duration_days")),
            "recovery_days": _int(lg.get("recovery_days")),
            "total_days": _int(lg.get("total_days")),
        }

    # 12 ── stats
    def stats(self) -> dict:
        return self._c("stats", self._build_stats)

    def _build_stats(self):
        diary = self.diary
        months = self.months()
        win = sum(1 for m in months if m["s"] is not None and m["b"] is not None
                  and m["s"] > m["b"])
        turn = self.turnover
        nz = turn[turn > 0]
        trades = self.ctx.trades
        cost = trades["cost"] if trades is not None else pd.Series(dtype=float)
        fees = self.ctx.metrics.get("total_fees")
        profit = self.ctx.metrics.get("total_return")
        return {
            "win_months": int(win),
            "months": len(months),
            "volcap_days": int((diary["vol_cap_scale"] < 1).sum()),
            "hyst_days": int(diary["hysteresis_held"].sum()),
            "zero_turn_days": int((turn <= 0).sum()),
            "median_turn": _r(nz.median() if len(nz) else None, 5),
            "max_turn": _r(turn.max() if len(turn) else None, 5),
            "max_turn_date": str(turn.idxmax().date()) if len(turn) else None,
            "cost": {
                "mean": _r(cost.mean() if len(cost) else None, 8),
                "median": _r(cost.median() if len(cost) else None, 8),
                "n": int(len(cost)),
                "fees": _r(fees, 8),
                "profit": _r(profit, 6),
                "share": _r(fees / profit if fees and profit else None, 3),
            },
        }

    # 13 ── events
    def events(self) -> list:
        return self._c("events", self._build_events)

    def _build_events(self):
        raw = self.derived_json("events").get("events", [])
        stages_raw = self.derived_json("stages")
        stage_by_date = {}
        for tot in stages_raw.get("totals", []):
            stage_by_date.setdefault(tot["date"], {})[tot["stage"]] = tot["total_weight"]
        stage_order = stages_raw.get("stage_order", [])

        trades = self.ctx.trades
        trade_by_date = {}
        if trades is not None and not trades.empty:
            df = trades.copy()
            df["d"] = [str(d.date()) if hasattr(d, "date") else str(d)[:10] for d in df["date"]]
            for day, grp in df.groupby("d", sort=False):
                trade_by_date[day] = grp

        hold, w = self.h, self.w
        cls = self.cls_map()
        diary = self.diary
        out = []
        for ev in raw:
            date = ev["date"]
            i = self.pos.get(date)
            if i is None:
                continue
            types_en = list(ev.get("types") or [])
            types = [EVENT_TYPE_CN.get(t, t) for t in types_en]
            primary_en = next((t for t in EVENT_PRIMARY_ORDER if t in types_en), None)
            primary = EVENT_TYPE_CN.get(primary_en, types[0] if types else None)
            out.append({
                "date": date,
                "i": i,
                "types": types,
                "primary": primary,
                "regime": ev.get("regime"),
                "turnover": _r(ev.get("turnover"), 5),
                "changes": [{"t": c["ticker"], "d": _r(c.get("delta"), 4)}
                            for c in ev.get("top_changes", [])],
                "rule": EVENT_RULE.get(primary),
                "fwd5": _r(ev.get("fwd_5d"), 5),
                "fwd20": _r(ev.get("fwd_20d"), 5),
                "triggers": ev.get("triggers"),
                "detail": self._event_detail(date, i, hold, w, cls, diary,
                                            trade_by_date, stage_by_date, stage_order),
            })
        return out

    def _event_detail(self, date, i, hold, w, cls, diary, trade_by_date, stage_by_date,
                      stage_order):
        d = self.dates
        trade_date = d[i + 1] if i + 1 < len(d) else None
        pre_row = hold.iloc[i] if i < len(hold) else None
        post_row = hold.iloc[i + 1] if i + 1 < len(hold) else None
        tgt_row = w.iloc[i] if i < len(w) else None

        def pos_list(row, limit=8):
            if row is None:
                return []
            items = [(t, float(v)) for t, v in row.items() if v > 0]
            items.sort(key=lambda x: -x[1])
            return [{"t": t, "w": _r(v, 5), "cls": cls.get(t, "other")}
                    for t, v in items[:limit]]

        def exp_of(row):
            sums = {k: 0.0 for k in CLASS_ORDER}
            total = 0.0
            if row is not None:
                for t, v in row.items():
                    fv = float(v)
                    if fv <= 0:
                        continue
                    sums[cls.get(t, "other")] = sums.get(cls.get(t, "other"), 0.0) + fv
                    total += fv
            out = {k: _r(sums.get(k, 0.0), 5) for k in CLASS_ORDER}
            cash = 1 - total
            out["cash"] = _r(cash if cash > 0 else 0.0, 5)
            return out

        pre = pos_list(pre_row)
        post = pos_list(post_row)
        pre_map = {t: float(v) for t, v in (pre_row.items() if pre_row is not None else [])}
        tgt_map = {t: float(v) for t, v in (tgt_row.items() if tgt_row is not None else [])}
        all_t = sorted(set(pre_map) | set(tgt_map))
        adds, inc, dec, exits = [], [], [], []
        for t in all_t:
            frm = pre_map.get(t, 0.0)
            to = tgt_map.get(t, 0.0)
            delta = to - frm
            # 低于 DUST 视为无仓；同侧变动小于 MIN_DELTA 视为噪声
            if frm < DUST and to >= DUST:
                adds.append({"t": t, "from_": frm, "to": to, "d": delta})
            elif frm >= DUST and to < DUST:
                exits.append({"t": t, "from_": frm, "to": to, "d": delta})
            elif frm >= DUST and to >= DUST and abs(delta) >= MIN_DELTA:
                (inc if delta > 0 else dec).append(
                    {"t": t, "from_": frm, "to": to, "d": delta})
        for lst in (adds, inc, dec, exits):
            lst.sort(key=lambda x: -abs(x["d"]))
            del lst[DETAIL_CAP:]

        rows = trade_by_date.get(trade_date) if trade_date else None
        trades_out = []
        n_trades = 0
        if rows is not None and len(rows):
            n_trades = int(len(rows))
            srt = rows.reindex(rows["notional"].abs().sort_values(ascending=False).index)
            for _, tr in srt.head(12).iterrows():
                side = "B" if float(tr["quantity"]) >= 0 else "S"
                trades_out.append({
                    "t": str(tr["ticker"]),
                    "side": side,
                    "p": _r(tr["price"], 4),
                    "q": _r(tr["quantity"], 6),
                    "n": _r(tr["notional"], 5),
                    "c": _r(tr["cost"], 9),
                })

        post_dev = []
        if trade_date is not None and trade_date in self.pos:
            ti = self.pos[trade_date]
            hh = hold.iloc[ti] if ti < len(hold) else None
            tgt = w.iloc[i] if i < len(w) else None
            if hh is not None and tgt is not None:
                devs = []
                for t in sorted(set(hh.index) | set(tgt.index)):
                    dv = abs(float(hh.get(t, 0.0)) - float(tgt.get(t, 0.0)))
                    if dv >= 1e-4:
                        devs.append((t, dv))
                devs.sort(key=lambda x: -x[1])
                post_dev = [{"t": t, "v": _r(v, 5)} for t, v in devs[:5]]

        stage_tot = stage_by_date.get(date, {})
        stages = {k: _r(stage_tot.get(k), 4) for k in stage_order}

        return {
            "pre": pre,
            "preExp": exp_of(pre_row),
            "target_total": _r(diary["total_weight"].iloc[i], 4) if diary is not None else None,
            "post": post,
            "postExp": exp_of(post_row),
            "adds": adds,
            "inc": inc,
            "dec": dec,
            "exits": exits,
            "trades": trades_out,
            "n_trades": n_trades,
            "postDev": post_dev,
            "signalDate": date,
            "tradeDate": trade_date,
            "stages": stages,
        }

    # 14 ── candidates
    def candidates(self) -> dict:
        return self._c("candidates", self._build_candidates)

    def _build_candidates(self):
        ts = self.tsig
        if ts is None or ts.empty:
            return {}
        out = {}
        held = {"held_risk", "gold", "nasdaq", "defensive"}
        for day, grp in ts.groupby(level=0, sort=True):
            g = grp.reset_index(level=0, drop=True)
            g = g.assign(_t=g.index)
            g = g.sort_values(
                by=["score", "_t"], ascending=[False, True], na_position="last")
            rows = []
            for rank, (t, rec) in enumerate(g.head(30).iterrows(), start=1):
                status = str(rec["status"])
                if status in held:
                    label, note = "保留（持仓）", "—"
                elif status == "candidate":
                    label, note = "候选", "未进入最终权重（排名/去重/上限）"
                elif status == "overheat_exit":
                    label, note = "剔除", "过热阈值"
                else:
                    label, note = status, "—"
                rows.append([str(t), _r(rec["score"], 4), rank, _r(rec["weight"], 5),
                             status, label, note])
            out[str(day.date())] = rows
        return out

    # 15 ── signals
    def signals(self) -> dict:
        return self._c("signals", self._build_signals)

    def _build_signals(self):
        ts = self.tsig
        if ts is None or ts.empty:
            return {}
        out = {}
        for ticker, grp in ts.groupby(level=1, sort=False):
            g = grp.reset_index(level=1, drop=True)
            rows = []
            for day, rec in g.iterrows():
                i = self.pos.get(str(day.date()))
                if i is None:
                    continue
                rows.append([
                    i,
                    _r(rec["m21"], 5),
                    _r(rec["m60"], 5),
                    _r(rec["score"], 4),
                    _r(rec["zbias"], 4),
                    _r(rec["close"], 4),
                    _r(rec["llt80"], 4),
                    _r(rec["weight"], 5),
                    str(rec["status"]),
                ])
            out[str(ticker)] = rows
        return out

    # 16 ── tickers
    def tickers(self) -> list:
        return self._c("tickers", self._build_tickers)

    def _build_tickers(self):
        ts = self.tsig
        if ts is None or ts.empty:
            return []
        cls = self.cls_map()
        w, h = self.w, self.h
        trades = self.ctx.trades
        trade_count = {}
        if trades is not None and not trades.empty:
            trade_count = trades["ticker"].value_counts().to_dict()
        rt = self.derived_json("roundtrips").get("roundtrips", [])
        pnl = {}
        for r in rt:
            pnl[r["ticker"]] = pnl.get(r["ticker"], 0.0) + float(r.get("pnl") or 0.0)

        hold_days = {t: int((h[t] > 1e-15).sum()) for t in h.columns}
        rows = []
        for ticker, grp in ts.groupby(level=1, sort=False):
            t = str(ticker)
            dates = grp.index.get_level_values(0)
            weights = grp["weight"]
            held_mask = weights > 1e-15
            status_counts = dict(Counter(grp["status"].tolist()))
            rows.append({
                "t": t,
                "first": str(dates.min().date()),
                "last": str(dates.max().date()),
                "days": int(len(grp)),
                "held": int(held_mask.sum()),
                "avg_w": _r(weights[held_mask].mean() if held_mask.any() else 0.0, 5),
                "trades": int(trade_count.get(t, 0)),
                "cls": cls.get(t, "other"),
                "pnl": _r(pnl.get(t), 5),
                "hold_days": hold_days.get(t, 0),
                "status": status_counts,
            })
        rows.sort(key=lambda r: (-r["held"], -r["days"], r["t"]))
        return rows

    # ── names（第 49 键，位置紧跟 tickers 便于阅读，键序仍由 BUILD_ORDER 决定）
    def names(self) -> dict:
        return self._c("names", self._build_names)

    def _build_names(self):
        from etf_rotation import pipeline
        from etf_rotation.data import universe

        codes = set(self.cls_map())
        if self.tsig is not None:
            codes.update(str(t) for t in self.tsig.index.get_level_values(1).unique())
        fb = pipeline.load_fund_basic()
        raw = fb.set_index("ts_code")["name"]
        abbr = universe.abbreviate(raw)
        # 查不到或简称为空串时回落成代码本身，前端无需再做空值判断
        return {c: abbr.get(c) or c for c in sorted(codes)}

    # 17 ── topPnl
    def topPnl(self) -> list:
        rows = [r for r in self.tickers() if r["pnl"] is not None]
        rows.sort(key=lambda r: -r["pnl"])
        return rows[:15]

    # 18 ── trades
    def trades(self) -> dict:
        return self._c("trades", self._build_trades)

    def _build_trades(self):
        tr = self.ctx.trades
        if tr is None or tr.empty:
            return {"dates": self.dates, "rows": []}
        pos = self.pos
        rows = []
        for _, r in tr.iterrows():
            day = r["date"]
            day = str(day.date()) if hasattr(day, "date") else str(day)[:10]
            i = pos.get(day)
            if i is None:
                continue
            qty = float(r["quantity"])
            rows.append([
                i,
                str(r["ticker"]),
                "B" if qty >= 0 else "S",
                _r(r["price"], 4),
                _r(qty, 6),
                _r(r["notional"], 5),
                _r(r["cost"], 9),
            ])
        return {"dates": self.dates, "rows": rows}

    # 19 ── diary
    def diary_table(self) -> dict:
        return self._c("diary_table", self._build_diary)

    def _build_diary(self):
        d = self.diary
        cols = list(d.columns)
        prec = {
            "comp_score": 4, "cyb_drop": 5, "cyb_vol": 5, "risk_scale": 4,
            "vol_scale_risk": 4, "risk_budget": 4, "nas_mom": 4, "gold_mom": 4,
            "nas_vol": 5, "gold_vol": 5, "nasdaq_weight": 4, "gold_weight": 4,
            "new_score": 4, "old_score": 4, "vol_cap_scale": 4,
            "total_weight": 4, "cash_weight": 4,
        }
        ints = {"n_cands", "n_kept", "n_overheat_exits", "n_defensive"}
        rows = []
        for _, rec in d.iterrows():
            row = []
            for c in cols:
                v = rec[c]
                if c == "regime":
                    row.append(REGIME_CODE.get(str(v)))
                elif c == "cyb_below":
                    row.append(1 if bool(v) else 0)
                elif c == "hysteresis_held":
                    row.append(1 if bool(v) else 0)
                elif c in ints:
                    row.append(_int(v))
                elif c in prec:
                    row.append(_r(v, prec[c]))
                else:
                    row.append(_plain(v))
            rows.append(row)
        return {"dates": self.dates, "cols": cols, "rows": rows}

    # 20 ── holdingsTop
    def holdingsTop(self) -> list:
        return self._c("holdingsTop", self._build_holdings_top)

    def _build_holdings_top(self):
        h = self.h
        out = []
        for _, row in h.iterrows():
            pos = [(t, float(v)) for t, v in row.items() if v > 1e-15]
            pos.sort(key=lambda x: -x[1])
            out.append([[t, _r(v, 5)] for t, v in pos[:10]])
        return out

    # 21 ── top10Changes
    def top10Changes(self) -> list:
        return self._c("top10Changes", self._build_top10_changes)

    def _build_top10_changes(self):
        h = self.h
        prev = set()
        out = []
        for i, (_, row) in enumerate(h.iterrows()):
            pos = [(t, float(v)) for t, v in row.items() if v > 1e-15]
            pos.sort(key=lambda x: (-x[1], x[0]))
            cur = {t for t, _ in pos[:10]}
            if i == 0:
                prev = cur
                continue
            en = sorted(cur - prev)
            ex = sorted(prev - cur)
            if en or ex:
                out.append({"i": i, "en": en, "ex": ex})
            prev = cur
        return out

    # 22 ── regimeIntervals
    def regimeIntervals(self) -> list:
        return self._c("regimeIntervals", self._build_regime_intervals)

    def _build_regime_intervals(self):
        d = self.diary
        reg = d["regime"].to_numpy()
        dates = self.dates
        if len(reg) == 0:
            return []
        starts = [0] + [i for i in range(1, len(reg)) if reg[i] != reg[i - 1]]
        ends = [s - 1 for s in starts[1:]] + [len(reg) - 1]
        out = []
        for s, e in zip(starts, ends):
            blk = d.iloc[s:e + 1]
            score = blk["comp_score"]
            out.append({
                "start": dates[s],
                "end": dates[e],
                "days": e - s + 1,
                "share": _r((e - s + 1) / len(reg), 4),
                "regime": str(reg[s]),
                "score_min": _r(score.min(), 4),
                "score_mean": _r(score.mean(), 4),
                "score_max": _r(score.max(), 4),
                "cyb_below": _r(blk["cyb_below"].astype(float).mean(), 3),
                "cyb_drop": _r(blk["cyb_drop"].mean(), 5),
                "cyb_vol": _r(blk["cyb_vol"].mean(), 5),
            })
        return out

    # 23 ── budgetSegments
    def budgetSegments(self) -> list:
        return self._c("budgetSegments", self._build_budget_segments)

    def _build_budget_segments(self):
        d = self.diary
        if d is None or d.empty:
            return []
        rs = d["risk_scale"].to_numpy()
        rb = d["risk_budget"].to_numpy()
        vs = d["vol_scale_risk"].to_numpy()
        cap = d["vol_cap_scale"].to_numpy()
        reg = d["regime"].to_numpy()
        # 用 np.round（半数进位）而非内置 round（半数取偶），与设计稿分段一致
        keys = list(zip(np.round(rs, 2), np.round(rb, 2)))
        # 段：连续同日键相同
        seg_id = [0]
        for i in range(1, len(keys)):
            seg_id.append(seg_id[-1] + (1 if keys[i] != keys[i - 1] else 0))
        out = []
        n_seg = seg_id[-1] + 1
        for k in range(n_seg):
            idx = [i for i in range(len(keys)) if seg_id[i] == k]
            s, e = idx[0], idx[-1]
            prev_reg = str(reg[idx[0] - 1]) if idx[0] > 0 else None
            prev_rs = float(rs[idx[0] - 1]) if idx[0] > 0 else None
            d_reg = prev_reg is not None and str(reg[s]) != prev_reg
            if d_reg and prev_reg == "range" and prev_rs is not None \
                    and abs(prev_rs - 0.05) < 1e-12 and str(reg[s]) == "bull":
                d_reg = False
            d_cap = any(cap[i] < 1 - 1e-9 for i in idx)
            d_vol = any(round(float(vs[i]), 3) < 1.0 for i in idx)
            parts = []
            if d_reg:
                parts.append("regime 切换")
            if d_cap:
                parts.append("上限截断")
            if d_vol:
                parts.append("波动缩放")
            trigger = " / ".join(parts)
            if not trigger:
                trigger = "波动缩放" if k == 0 else "评分/状态下调"
            out.append({
                "start": self.dates[s],
                "end": self.dates[e],
                "days": e - s + 1,
                "regime": str(reg[s]),
                "risk_scale": _r(float(rs[idx].mean()), 2),
                "vol_scale": _r(float(vs[idx].mean()), 3),
                "risk_budget": _r(float(rb[idx].mean()), 3),
                "trigger": trigger,
            })
        return out

    # 24 ── stages
    def stages(self) -> dict:
        return self._c("stages", self._build_stages)

    def _build_stages(self):
        raw = self.derived_json("stages")
        order = raw.get("stage_order", [])
        out = {}
        for tot in raw.get("totals", []):
            out.setdefault(tot["date"], {})
        for tot in raw.get("totals", []):
            out[tot["date"]][tot["stage"]] = _r(tot["total_weight"], 4)
        return {d: {k: v.get(k) for k in order} for d, v in out.items()}

    # 25 ── stageOrder
    def stageOrder(self) -> list:
        return self.derived_json("stages").get("stage_order", [])

    # 26 ── contribution
    def contribution(self) -> dict:
        return self._c("contribution", self._build_contribution)

    def _build_contribution(self):
        attr = self.report_json("attribution")
        exact_cn = attr.get("class_contribution", {})
        exact = {ATTR_CN.get(k, k): _r(v, 6) for k, v in exact_cn.items()}
        classes = [c for c in ("risk", "nasdaq", "gold", "defensive") if c in exact]

        cls = self.cls_map()
        hold = self.h
        close = self.ctx.close
        raw_daily = {}
        if close is not None and not hold.empty:
            cols = [c for c in hold.columns if c in close.columns]
            r = close[cols].pct_change(fill_method=None).reindex(hold.index)
            prev = hold[cols].shift(1).fillna(0.0)
            prod = prev * r.fillna(0.0)
            for name in classes:
                sub = [c for c in cols if cls.get(c) == name]
                raw_daily[name] = prod[sub].sum(axis=1) if sub else pd.Series(0.0, index=hold.index)
        else:
            for name in classes:
                raw_daily[name] = pd.Series(0.0, index=hold.index)

        scale = {}
        for name in classes:
            tot = float(raw_daily[name].sum())
            exp = exact.get(name)
            scale[name] = (exp / tot) if tot else None

        daily, annual, expo = {}, [], {}
        for name in classes:
            sc = scale[name]
            daily[name] = _rl(raw_daily[name] * sc if sc is not None else raw_daily[name], 6)
        years = sorted({int(y) for y in self.eq.index.year})
        for y in years:
            mask = self.eq.index.year == y
            row = {"year": y}
            for name in classes:
                vals = raw_daily[name][mask] * (scale[name] or 0.0)
                row[name] = _r(float(vals.sum()), 5)
            annual.append(row)
        for name in classes:
            cols = [c for c in hold.columns if cls.get(c) == name]
            expo[name] = _rl(hold[cols].sum(axis=1), 5) if cols else _rl(
                pd.Series(0.0, index=hold.index), 5)

        perf = self.derived_json("performance")
        eps = sorted(perf.get("episodes", []),
                     key=lambda e: -float(e.get("depth") or 0.0))[:5]
        episodes = []
        for e in eps:
            peak, trough = e.get("peak_date"), e.get("trough_date")
            if peak not in self.pos or trough not in self.pos:
                continue
            a, b = self.pos[peak], self.pos[trough]
            contrib = {}
            for name in classes:
                seg = raw_daily[name].iloc[a:b + 1] * (scale[name] or 0.0)
                contrib[name] = _r(float(seg.sum()), 5)
            episodes.append({
                "peak": peak,
                "trough": trough,
                "depth": _r(-abs(e.get("depth", 0.0)), 12),
                "contrib": contrib,
            })

        return {
            "classes": classes,
            "daily": daily,
            "expo": expo,
            "exact": exact,
            "note": "按复权收盘与实际持仓估算，期末合计对齐 attribution.json；"
                    "不等同于逐笔会计贡献。",
            "episodes": episodes,
            "annual": annual,
        }

    # 27 ── turnoverDecomp
    def turnoverDecomp(self) -> list:
        return self._c("turnoverDecomp", self._build_turnover_decomp)

    def _build_turnover_decomp(self):
        ev = self.derived_json("events").get("events", [])
        primary_by_day = {}
        for e in ev:
            types = e.get("types") or []
            p = next((t for t in EVENT_PRIMARY_ORDER if t in types), None)
            primary_by_day[e["date"]] = EVENT_TYPE_CN.get(p, "无事件") if p else "无事件"
        turn = self.turnover
        keys = ["换仓", "过热清零", "波动上限缩放", "防守重选", "跨资产腿切换", "无事件"]
        out = []
        for y in sorted({int(v) for v in self.eq.index.year}):
            mask = self.eq.index.year == y
            buckets = {k: 0.0 for k in keys}
            for day in self.eq.index[mask]:
                label = primary_by_day.get(str(day.date()), "无事件")
                if label not in buckets:
                    label = "无事件"
                buckets[label] += float(turn.loc[day])
            row = {"year": y}
            for k in keys:
                row[k] = _r(buckets[k], 5)
            out.append(row)
        return out

    # 28 ── costByYear
    def costByYear(self) -> list:
        costs = self.derived_json("costs")
        ret_by_year = {r["year"]: r["ret"] for r in self.annual()}
        out = []
        for row in costs.get("annual", []):
            fees = row.get("fees")
            year = _int(row.get("year"))
            # 收益口径与 annual 卡一致（nav 年末/上年末−1），不用 costs 的另一种算法
            ret = ret_by_year.get(year)
            out.append({
                "year": year,
                "cost": _r(fees, 6),
                "ret": ret,
                "cost_bp": _r(fees * 1e4 if fees is not None else None, 2),
                "ratio": _r(fees / ret if fees is not None and ret and ret > 0 else None, 4),
            })
        return out

    # 29 ── sweeps
    def sweeps(self) -> list:
        return self._c("sweeps", self._build_sweeps)

    def _build_sweeps(self):
        params = self.ctx.params
        out = []
        for key in SWEEP_ORDER:
            path = self.reports / "sensitivity" / f"{SWEEP_FILES[key]}.json"
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            grid = data.get("grid", {}).get(key, [])
            results = data.get("results", [])

            def sort_key(v):
                return tuple(v) if isinstance(v, (list, tuple)) else (v,)

            ordered = sorted(grid, key=sort_key)
            by_value = {}
            for r in results:
                by_value[_grid_key(r.get(key))] = r
            default_pos = None
            cur = _grid_key(params.get(key))
            for i, v in enumerate(ordered):
                if _grid_key(v) == cur:
                    default_pos = i
                    break
            base = by_value.get(cur)
            rows = []
            for v in ordered:
                r = by_value.get(_grid_key(v))
                if r is None:
                    continue
                sharpe = r.get("sharpe")
                rows.append({
                    "sharpe": _r(sharpe, 4),
                    "ann": _r(r.get("ann_return"), 6),
                    "mdd": _r(r.get("max_drawdown"), 6),
                    "calmar": _r(r.get("calmar"), 4),
                    "d_sharpe": _r(sharpe - base["sharpe"]
                                    if base is not None and sharpe is not None else None, 4),
                })
            cliff = (data.get("cliffs") or {}).get(key, {})
            batch_date = self._sweep_batch_date(data)
            out.append({
                "key": key,
                "label": SWEEP_LABELS.get(key, key),
                "x": [_grid_label(v) for v in ordered],
                "rows": rows,
                "default_idx": default_pos,
                "robustness": _r(data.get("robustness"), 4),
                "dsr": _r(data.get("dsr"), 4),
                "cliff": bool(cliff.get("cliff", False)),
                "max_jump": _r(cliff.get("max_jump"), 4),
                "batch": f"{batch_date} · open 口径",
            })
        return out

    def _sweep_batch_date(self, data) -> str:
        fam = data.get("family_id")
        if fam:
            p = self.reports / "families" / fam / "summary.json"
            if p.exists():
                gen = json.loads(p.read_text(encoding="utf-8")).get("generated")
                if gen:
                    return str(gen)[:10]
        gen = self.derived_json("index").get("generated") if False else None
        return self.dates[-1]

    # 30 ── grid2d
    def grid2d(self) -> dict:
        return self._c("grid2d", self._build_grid2d)

    def _build_grid2d(self):
        path = self.reports / "families" / "00d0a6f0e9f8" / "summary.json"
        if not path.exists():
            return {"x": [], "y": [], "z": [], "note": "热力图家族缺失"}
        data = json.loads(path.read_text(encoding="utf-8"))
        spec = data.get("spec", {})
        corr = sorted(spec.get("dedupe.corr_threshold", []))
        bps = sorted(spec.get("costs.one_side_bps", []))
        z = []
        peak = {"sharpe": None, "corr": None, "bps": None}
        for y in bps:
            row = []
            for x in corr:
                val = None
                for r in data.get("results", []):
                    if (abs(float(r.get("costs.one_side_bps", 1e9)) - float(y)) < 1e-12
                            and abs(float(r.get("dedupe.corr_threshold", -1e9)) - float(x)) < 1e-12):
                        val = _r(r.get("sharpe"), 6)
                        break
                row.append(val)
                if val is not None and (peak["sharpe"] is None or val > peak["sharpe"]):
                    peak = {"sharpe": val, "corr": x, "bps": y}
            z.append(row)
        if peak["sharpe"] is not None:
            note = (f"2026-10-25 open 口径；峰值 Sharpe {peak['sharpe']:.4f}"
                    f"（相关性 {peak['corr']}，{peak['bps']:g}bp）")
        else:
            note = "2026-10-25 open 口径"
        return {"x": [float(v) for v in corr], "y": [float(v) for v in bps],
                "z": z, "note": note}

    # 31 ── costLadder
    def costLadder(self) -> list:
        path = self.reports / "families" / "abc468e90e83" / "summary.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = sorted(data.get("results", []), key=lambda r: r.get("costs.one_side_bps", 0))
        out = []
        for r in rows:
            out.append({
                "cost_bps": _int(r.get("costs.one_side_bps")),
                "ann_return": r.get("ann_return"),
                "max_drawdown": r.get("max_drawdown"),
                "sharpe": r.get("sharpe"),
                "calmar": r.get("calmar"),
            })
        return out

    # 32 ── dsr
    def dsr(self) -> dict:
        return self._c("dsr", self._build_dsr)

    def _build_dsr(self):
        path = self.reports / "families" / "f42d16191378" / "summary.json"
        if not path.exists():
            return {"value": None, "threshold": 0.95, "haircut": None, "sweep": None}
        data = json.loads(path.read_text(encoding="utf-8"))
        sweep_vals = []
        for p in (self.reports / "sensitivity").glob("*.json"):
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("dsr") is not None:
                sweep_vals.append(float(d["dsr"]))
        return {
            "value": _r(data.get("dsr_family"), 4),
            "threshold": 0.95,
            "haircut": data.get("sharpe_haircut"),
            "sweep": _r(min(sweep_vals) if sweep_vals else None, 4),
        }

    # 33 ── ablation
    def ablation(self) -> list:
        rows = self.report_json("ablation")
        order = ["baseline(all-on)", "phases=off", "hysteresis=off", "reversal=off",
                 "overheat=off", "vol_cap=off"]

        def name_of(r):
            m = r.get("mechanism", "")
            return "baseline(all-on)" if m.startswith("baseline") else m

        by_name = {name_of(r): r for r in rows}
        base = by_name.get("baseline(all-on)")
        out = []
        for name in order:
            r = by_name.get(name)
            if r is None:
                continue
            item = {
                "name": name,
                "ann": _r(r.get("ann_return"), 6),
                "mdd": _r(r.get("max_drawdown"), 6),
                "sharpe": _r(r.get("sharpe"), 4),
                "calmar": _r(r.get("calmar"), 4),
                "turnover": _r(r.get("turnover"), 5),
            }
            for k, src in (("d_ann", "ann_return"), ("d_mdd", "max_drawdown"),
                           ("d_sharpe", "sharpe"), ("d_calmar", "calmar")):
                nd = 6 if k in ("d_ann", "d_mdd") else 4
                item[k] = _r((r.get(src) or 0) - (base.get(src) or 0) if base else None, nd)
            out.append(item)
        return out

    # 34 ── assumption
    def assumption(self) -> list:
        data = self.report_json("assumption_sensitivity")
        out = []
        for key, rows in data.items():
            if not isinstance(rows, list) or not rows:
                continue
            base = rows[0].get("sharpe")
            for r in rows:
                sharpe = r.get("sharpe")
                d_sharpe = _r(sharpe - base if sharpe is not None and base is not None else None, 4)
                out.append({
                    "key": key,
                    "value": str(_fmt_param(r.get("value"))),
                    "ann": _r(r.get("ann_return"), 6),
                    "mdd": _r(r.get("max_drawdown"), 6),
                    "sharpe": _r(sharpe, 4),
                    "calmar": _r(r.get("calmar"), 4),
                    "turnover": _r(r.get("turnover"), 5),
                    "d_sharpe": d_sharpe,
                    "is_default": bool(d_sharpe is not None and abs(d_sharpe) < 1e-12),
                })
        return out

    # 35 ── oos
    def oos(self) -> list:
        met = self.ctx.metrics
        check = self.report_json("oos_check").get("subperiods", {})
        idx = self.eq.index
        spans = [("2019–2023", "2019-2023"), ("2024–2026", "2024-2026")]
        out = []
        for label, key in spans:
            sub = check.get(key)
            if sub is None:
                continue
            year_end = 2023 if key.startswith("2019") else 9999
            year_start = 2019 if key.startswith("2019") else 2024
            days = int(((idx.year >= year_start) & (idx.year <= year_end)).sum())
            out.append({
                "period": label,
                "ann": _r(sub.get("ann_return"), 6),
                "mdd": _r(sub.get("max_drawdown"), 6),
                "sharpe": _r(sub.get("sharpe"), 4),
                "calmar": _r(sub.get("calmar"), 4),
                "days": days,
            })
        out.append({
            "period": "全区间",
            "ann": _r(met.get("ann_return"), 6),
            "mdd": _r(met.get("max_drawdown"), 6),
            "sharpe": _r(met.get("sharpe"), 4),
            "calmar": _r(met.get("calmar"), 4),
            "days": len(self.dates),
        })
        return out

    # 36 ── oosOverride
    def oosOverride(self) -> dict:
        data = self.report_json("oos_check")
        overrides = data.get("param_overrides") or []
        if not overrides:
            return {"param_overrides": [], "subperiods": {}}
        return {"param_overrides": overrides,
                "subperiods": data.get("subperiods") or {}}

    # 37 ── regime
    def regime(self) -> list:
        return self._c("regime", self._build_regime)

    def _build_regime(self):
        d = self.diary
        reg = d["regime"].shift(1)
        ret = self.ret
        rb = self.rb
        total = d["total_weight"]
        out = []
        for name in ("bull", "range", "bear"):
            mask = (reg == name).to_numpy()
            r = ret[mask]
            b = rb[mask]
            ann = r.mean() * 252
            vol = r.std() * math.sqrt(252)
            out.append({
                "regime": name,
                "days": int(mask.sum()),
                "ann": _r(ann, 5),
                "vol": _r(vol, 5),
                "sharpe": _r(ann / vol if vol else None, 4),
                "win": _r(float((r > 0).mean()) if len(r) else None, 4),
                "avg_exposure": _r(total[mask].mean(), 4),
                "bm_ann": _r(b.mean() * 252, 5),
            })
        return out

    # 38 ── attribution
    def attribution(self) -> dict:
        return self.report_json("attribution")

    # 39 ── exposureSummary
    def exposureSummary(self) -> dict:
        return self.report_json("exposure")

    # 40 ── exDef
    def exDef(self) -> dict:
        return self.derived_json("relative").get("ex_defensive", {})

    # 41 ── dataQuality
    def dataQuality(self) -> dict:
        data = self.report_json("data_quality")
        return {
            "counts": data.get("classification_counts"),
            "n_etfs": data.get("n_etfs"),
            "n_delisted": data.get("n_delisted"),
            "survivorship": data.get("survivorship"),
            # 卡片口径说明是静态文案，不取 source_gap（那是另一处差异说明）
            "note": "point-in-time 过滤（上市≥126 日、20 日均成交额≥500 万）；退市标的不再入池。",
        }

    # 42 ── gap
    def gap(self) -> list:
        k = self.kpi()
        s = k["s"]
        current = {
            "年化收益": (s["cagr"], "pct"),
            "最大回撤": (s["mdd"], "pct"),
            "Sharpe": (s["sharpe"], "num"),
            "Calmar": (s["calmar"], "num"),
        }
        out = []
        for name, target in TABLES.TARGET_GAP:
            value, kind = current[name]
            target_num = float(target.replace("%", "").replace("\u2212", "-"))
            if kind == "pct":
                target_num /= 100.0
            diff = (value - target_num) if value is not None else None
            out.append([
                name,
                target,
                _fmt_gap(value, kind),
                _fmt_gap_diff(diff, kind),
            ])
        return out

    # 43 ── issues
    def issues(self) -> list:
        return [{"title": t, "detail": d, "status": s} for t, d, s in ISSUES]

    # 44 ── lagScan
    def lagScan(self) -> dict:
        data = self.derived_json("relative").get("lag_scan", {})
        # 产物字段名是 peak_lag；兼容旧写法的 peak
        peak = data.get("peak_lag", data.get("peak"))
        return {
            "lags": data.get("lags", []),
            "corrs": data.get("corrs", []),
            "peak": peak,
            "ok": peak == 0,
        }

    # 45 ── roundtrips
    def roundtrips(self) -> dict:
        return self._c("roundtrips", self._build_roundtrips)

    def _build_roundtrips(self):
        raw = self.derived_json("roundtrips")
        rows = raw.get("roundtrips", [])
        # 区间上界 → 展示标签（最后一个桶无上界）
        hold_bins = [(2, "1-2"), (5, "3-5"), (10, "6-10"), (20, "11-20"),
                     (40, "21-40"), (60, "41-60"), (120, "61-120"),
                     (250, "121-250"), (None, "250+")]
        hold_counts = {label: 0 for _, label in hold_bins}
        first = hold_bins[0][1]
        for r in rows:
            d = r.get("holding_days") or 0
            for upper, label in hold_bins:
                if upper is None or d <= upper:
                    hold_counts[label] += 1
                    break
            else:
                hold_counts[first] += 1
        pnl_bins = [(-float("inf"), -0.05, "≤-5%"), (-0.05, -0.02, "-5~-2%"),
                    (-0.02, -0.01, "-2~-1%"), (-0.01, -0.005, "-1~-0.5%"),
                    (-0.005, 0.0, "-0.5~0"), (0.0, 0.005, "0~0.5%"),
                    (0.005, 0.01, "0.5~1%"), (0.01, 0.02, "1~2%"),
                    (0.02, 0.05, "2~5%"), (0.05, float("inf"), ">5%")]
        pnl_counts = {label: 0 for _, _, label in pnl_bins}
        for r in rows:
            p = float(r.get("pnl") or 0.0)
            for lo, hi, label in pnl_bins:
                if lo <= p < hi:
                    pnl_counts[label] += 1
                    break
            else:
                pnl_counts[pnl_bins[-1][2]] += 1
        # 表：盈利前 15 + 亏损前 15（按 pnl 方向各取极值，合计 30 行）
        ordered = sorted(rows, key=lambda r: -(r.get("pnl") or 0.0))
        top = ordered[:15] + ordered[::-1][:15]
        table = []
        for r in top:
            table.append({
                "t": r.get("ticker"),
                "entry": r.get("entry_date"),
                "exit": r.get("exit_date"),
                "days": _int(r.get("holding_days")),
                "pnl": _r(r.get("pnl"), 6),
                "reason": r.get("exit_reason"),
                "status": r.get("entry_status"),
            })
        return {
            "summary": raw.get("summary", {}),
            "holdHist": [{"bin": label, "n": hold_counts[label]}
                         for _, label in hold_bins],
            "pnlHist": [{"bin": label, "n": pnl_counts[label]}
                        for _, _, label in pnl_bins],
            "table": table,
        }

    # 46 ── slippage
    def slippage(self) -> dict:
        return self._c("slippage", self._build_slippage)

    def _build_slippage(self):
        liq = self.derived_json("liquidity")
        rows = liq.get("slippage", {}).get("rows", [])
        summary = liq.get("slippage", {}).get("summary", {})
        vals = np.array([float(r.get("vs_close_bps") or 0.0) for r in rows])
        edges = [-300, -200, -100, -50, -20, 0, 20, 50, 100, 200, 300]
        labels = ["-300~-200", "-200~-100", "-100~-50", "-50~-20", "-20~0",
                  "0~20", "20~50", "50~100", "100~200", "200~300"]
        cnt, _ = np.histogram(vals, bins=edges) if len(vals) else (np.zeros(10, int), None)
        hist = [{"bin": labels[i], "n": int(cnt[i])} for i in range(10)]
        top = sorted(rows, key=lambda r: -abs(float(r.get("vs_close_bps") or 0.0)))[:20]
        table = []
        for r in top:
            table.append({
                "date": r.get("date"),
                "t": r.get("ticker"),
                "p": _r(r.get("price"), 4),
                "close": _r(r.get("close"), 4),
                "opn": _r(r.get("opn"), 4),
                "vs_close": _r(r.get("vs_close_bps"), 1),
                "vs_open": _r(r.get("vs_open_bps"), 1),
            })
        sample = [[rows[i].get("date"), _r(rows[i].get("vs_close_bps"), 1)]
                  for i in range(0, len(rows), 6)]
        return {
            "n": _int(summary.get("n")),
            "mean": _r(summary.get("mean_vs_close_bps"), 2),
            "median": _r(summary.get("median_vs_close_bps"), 2),
            "p5": _r(float(np.percentile(vals, 5)) if len(vals) else None, 2),
            "p95": _r(float(np.percentile(vals, 95)) if len(vals) else None, 2),
            "mean_open": _r(summary.get("mean_vs_open_bps"), 2),
            "hist": hist,
            "table": table,
            "sample": sample,
        }

    # 47 ── capacity
    def capacity(self) -> dict:
        liq = self.derived_json("liquidity")
        cap = liq.get("capacity", {})
        return {
            "summary": cap.get("summary", {}),
            "by_year": cap.get("by_year", []),
            "assumptions": liq.get("assumptions", {}),
        }

    # 48 ── dist
    def dist(self) -> dict:
        return self._c("dist", self._build_dist)

    def _build_dist(self):
        ret = self.ret.iloc[1:]
        cnt, edges = np.histogram(ret, bins=41)
        width = float(edges[1] - edges[0])
        centers = (edges[:-1] + edges[1:]) / 2
        mu = self.ctx.metrics.get("daily_mean")
        mu = mu / 252 if mu is not None else float(self.ret.mean() / 252)
        sd = float(self.ret.std())
        norm = []
        for c in centers:
            if sd:
                y = math.exp(-0.5 * ((c - mu) / sd) ** 2) / (sd * math.sqrt(2 * math.pi))
            else:
                y = 0.0
            norm.append({"x": _r(c, 5), "y": _r(y * width * len(ret), 4)})
        # QQ：p=(i+0.5)/160，x=标准正态分位，y=样本分位标准化（用全样本，不用去掉首日的切片）
        sorted_ret = np.sort(self.ret.to_numpy())
        mean_all = float(self.ret.mean())
        qq = []
        n = 160
        for i in range(n):
            p = (i + 0.5) / n
            x = _norm_ppf(p)
            idx = min(len(sorted_ret) - 1, int(p * len(sorted_ret)))
            y = (sorted_ret[idx] - mean_all) / sd if sd else 0.0
            qq.append({"x": _r(x, 4), "y": _r(y, 4)})
        from statistics import NormalDist
        return {
            "daily": [int(v) for v in cnt],
            "edges": _rl(edges, 5),
            "norm": norm,
            "qq": qq,
            "mu": _r(mu, 6),
            "sd": _r(sd, 6),
            "skew": _r(self.ctx.metrics.get("daily_skew"), 4),
            "kurt": _r(self.ctx.metrics.get("daily_kurt"), 3),
            "_nd": NormalDist,   # 占位，序列化前删除
        }

    # ------------------------------------------------------------ 汇总

    def build(self, only=None) -> dict:
        keys = BUILD_ORDER
        payload = {}
        for key in keys:
            if only and key not in only:
                continue
            payload[key] = getattr(self, BUILDER_METHODS[key])()
        if "dist" in payload:
            payload["dist"].pop("_nd", None)
        return payload


BUILD_ORDER = [
    "meta", "kpi", "kpiTable", "params", "paramSnapshot", "series", "monthly",
    "months", "annual", "drawdowns", "longest", "stats", "events", "candidates",
    "signals", "tickers", "topPnl", "trades", "diary", "holdingsTop",
    "top10Changes", "regimeIntervals", "budgetSegments", "stages", "stageOrder",
    "contribution", "turnoverDecomp", "costByYear", "sweeps", "grid2d",
    "costLadder", "dsr", "ablation", "assumption", "oos", "oosOverride",
    "regime", "attribution", "exposureSummary", "exDef", "dataQuality", "gap",
    "issues", "lagScan", "roundtrips", "slippage", "capacity", "dist", "names",
]

BUILDER_METHODS = {
    "meta": "meta", "kpi": "kpi", "kpiTable": "kpiTable", "params": "params",
    "paramSnapshot": "paramSnapshot", "series": "series", "monthly": "monthly",
    "months": "months", "annual": "annual", "drawdowns": "drawdowns",
    "longest": "longest", "stats": "stats", "events": "events",
    "candidates": "candidates", "signals": "signals", "tickers": "tickers",
    "topPnl": "topPnl", "trades": "trades", "diary": "diary_table",
    "holdingsTop": "holdingsTop", "top10Changes": "top10Changes",
    "regimeIntervals": "regimeIntervals", "budgetSegments": "budgetSegments",
    "stages": "stages", "stageOrder": "stageOrder",
    "contribution": "contribution", "turnoverDecomp": "turnoverDecomp",
    "costByYear": "costByYear", "sweeps": "sweeps", "grid2d": "grid2d",
    "costLadder": "costLadder", "dsr": "dsr", "ablation": "ablation",
    "assumption": "assumption", "oos": "oos", "oosOverride": "oosOverride",
    "regime": "regime", "attribution": "attribution",
    "exposureSummary": "exposureSummary", "exDef": "exDef",
    "dataQuality": "dataQuality", "gap": "gap", "issues": "issues",
    "lagScan": "lagScan", "roundtrips": "roundtrips", "slippage": "slippage",
    "capacity": "capacity", "dist": "dist", "names": "names",
}


# ---------------------------------------------------------------- 小工具


def _norm_ppf(p: float) -> float:
    """标准正态分位（Abramowitz-Stegun 26.2.23，误差 < 1.5e-9）。"""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    # 用 statistics.NormalDist 更准
    from statistics import NormalDist
    return NormalDist().inv_cdf(p)


def _fmt_param(value):
    """参数值 → 展示值：标量保持原类型，列表用 ' / ' 连接，bool 用 on/off。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (list, tuple)):
        return " / ".join(_fmt_scalar(v) for v in value)
    return _plain(value)


def _fmt_scalar(v):
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        return repr(v)
    return str(v)


def _fmt_gap(value, kind):
    if value is None:
        return "—"
    if kind == "pct":
        return f"{value * 100:.2f}%"
    return f"{value:.2f}"


def _fmt_gap_diff(diff, kind):
    if diff is None:
        return "—"
    if kind == "pct":
        return f"{diff * 100:+.2f}pp".replace("+", "")
    return f"{diff:+.2f}".replace("+", "")


def _grid_key(value):
    """网格取值归一：列表 → tuple，数值 → float。"""
    if isinstance(value, (list, tuple)):
        return tuple(float(v) for v in value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _grid_label(value):
    if isinstance(value, (list, tuple)):
        return "/".join(_fmt_scalar(v) for v in value)
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return _fmt_scalar(value)


def _plain(value):
    """pandas 标量 → 原生 Python，保留精度。"""
    if value is None:
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        v = float(value)
        return None if math.isnan(v) else v
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


# ---------------------------------------------------------------- 入口


def build_dashboard(ctx: ReportContext, run_dir: Path, reports_dir: Path | None = None,
                    only=None) -> dict:
    """按 49 键契约构建看板数据；`only` 给键名列表可只算部分（调试用）。"""
    reports_dir = Path(reports_dir) if reports_dir else Path(run_dir).parent.parent
    builder = DashboardBuilder(ctx, run_dir, reports_dir)
    return builder.build(only=only)
