"""相对基准指标（N3）+ 剔除防守相关性（N9）。

公式（全部为日频收益序列，s=策略、b=基准）：
    beta            = cov(s, b) / var(b)               （ddof=1，分母为 0 → None）
    correlation     = Pearson(s, b)
    tracking_error  = std(s − b, ddof=1) × √252
    excess_arith    = (mean(s) − mean(b)) × 252        （年化算术超额）
    excess_cagr     = CAGR(s) − CAGR(b)                （日历日 CAGR，ffn.calc_cagr）
    information_ratio = excess_arith / tracking_error
    up/down_capture = mean(s | b>0, b<0) / mean(b | b>0, b<0)
    monthly_win_rate = 月收益超过基准的月份占比

剔除防守（N9）：把 bond/money 权重置 0 得到风险仓 `w_risk`，按 `mean_risk_weight`
把平均暴露归一到 1 再与基准比较。`w_risk` 整体 `.shift(1)` 后与 T+1 收益相乘
（T 日权重 → T+1 生效，与回测移位口径一致），避免用当日权重配当日收益。
`beta_scaling = mean_risk_weight`，三者一起输出，读者能还原「策略 beta 低」
到底是因为仓位低（scaling）还是因为风险仓本身与基准相关性低。
"""
from __future__ import annotations

import math

import ffn
import numpy as np
import pandas as pd

from etf_rotation.evaluation.alignment import lag_correlation
from etf_rotation.report.context import ReportContext
from etf_rotation.report.serialize import records, series

NAME = "relative"

TRADING_DAYS = 252
ROLLING_WINDOW = 252
# 低于该值的 tracking error 视为 0（浮点常数差会留下 ~1e-18 的噪声）
_TE_FLOOR = 1e-12
# 方差下限：常数序列的数值噪声约 1e-36，远低于任何真实日收益方差（~1e-4）
_VAR_FLOOR = 1e-20
# 非风险仓类别（这两类权重要置 0；可转债按计划留在风险仓）
_DEFENSIVE = ("bond", "money")


def _align(strategy: pd.Series, benchmark: pd.Series) -> pd.DataFrame:
    """按日期内连接并对齐（丢掉任一侧 NaN 的日子），返回 s/b 两列。"""
    df = pd.concat([pd.Series(strategy, dtype="float64").rename("s"),
                    pd.Series(benchmark, dtype="float64").rename("b")], axis=1)
    return df.dropna().sort_index()


def _beta_corr(s: np.ndarray, b: np.ndarray) -> tuple[float | None, float | None]:
    """beta 与 Pearson 相关；方差为 0（或样本 < 2）时均返回 None。"""
    if len(s) < 2:
        return None, None
    sc = s - s.mean()
    bc = b - b.mean()
    ss = float((sc ** 2).sum())
    bb = float((bc ** 2).sum())
    sb = float((sc * bc).sum())
    if bb <= _VAR_FLOOR or ss <= _VAR_FLOOR:
        return None, None
    beta = sb / bb
    corr = sb / math.sqrt(ss * bb)
    return _finite(beta), _finite(corr)


def _finite(value: float | None) -> float | None:
    """NaN/Inf → None（JSON 侧禁止非有限数）。"""
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _div(num: float, den: float) -> float | None:
    """安全除法：分母为 0 / 非有限 → None。"""
    if den is None or not math.isfinite(den) or abs(den) <= 0.0:
        return None
    return _finite(num / den)


def _cagr(returns: pd.Series) -> float | None:
    """日历日 CAGR（净值端点口径，直接调用 ffn.calc_cagr）。"""
    r = pd.Series(returns, dtype="float64").dropna()
    if len(r) < 2:
        return None
    nav = (1.0 + r).cumprod()
    if nav.iloc[-1] <= 0:
        return None
    try:
        return _finite(float(ffn.calc_cagr(nav)))
    except Exception:
        return None


def _monthly(returns: pd.Series) -> pd.Series:
    """日收益 → 月收益（按自然月复利）。"""
    r = pd.Series(returns, dtype="float64").dropna()
    grouped = (1.0 + r).groupby(r.index.to_period("M")).prod() - 1.0
    grouped.index = grouped.index.to_timestamp()
    return grouped


def relative_summary(strategy: pd.Series, benchmark: pd.Series) -> dict:
    """相对基准的汇总指标（键见计划 Task 9；无法定义的一律 None）。"""
    df = _align(strategy, benchmark)
    keys = ["excess_cagr", "excess_arith", "tracking_error", "information_ratio",
            "beta", "correlation", "up_capture", "down_capture",
            "monthly_win_rate", "n_months"]
    if len(df) < 2:
        return {key: None for key in keys}

    s, b = df["s"].to_numpy(), df["b"].to_numpy()
    beta, corr = _beta_corr(s, b)

    diff = df["s"] - df["b"]
    te = _finite(float(diff.std(ddof=1)) * math.sqrt(TRADING_DAYS))
    excess_arith = _finite((float(df["s"].mean()) - float(df["b"].mean())) * TRADING_DAYS)
    ir = _div(excess_arith, te) if te is not None and te > _TE_FLOOR else None

    ups = df["b"] > 0
    downs = df["b"] < 0
    up_capture = _div(float(df.loc[ups, "s"].mean()), float(df.loc[ups, "b"].mean())) \
        if ups.any() else None
    down_capture = _div(float(df.loc[downs, "s"].mean()), float(df.loc[downs, "b"].mean())) \
        if downs.any() else None

    monthly_s = _monthly(df["s"])
    monthly_b = _monthly(df["b"])
    common = monthly_s.index.intersection(monthly_b.index)
    wins = (monthly_s.reindex(common) > monthly_b.reindex(common))
    monthly_win_rate = _finite(float(wins.mean())) if len(common) else None

    return {
        "excess_cagr": _subtract(_cagr(df["s"]), _cagr(df["b"])),
        "excess_arith": excess_arith,
        "tracking_error": te,
        "information_ratio": ir,
        "beta": beta,
        "correlation": corr,
        "up_capture": up_capture,
        "down_capture": down_capture,
        "monthly_win_rate": monthly_win_rate,
        "n_months": int(len(common)),
    }


def _subtract(a: float | None, b: float | None) -> float | None:
    """两个可能为 None 的数值相减（任一缺失 → None）。"""
    return None if a is None or b is None else _finite(a - b)


def rolling_relative(strategy: pd.Series, benchmark: pd.Series,
                     window: int = ROLLING_WINDOW) -> pd.DataFrame:
    """滚动相对指标：`excess`（年化算术超额）、`ir`、`beta`、`corr`。

    窗口不足 `window` 天一律 NaN（`min_periods=window`），绝不 fillna。
    """
    df = _align(strategy, benchmark)
    window = max(2, int(window))
    s, b = df["s"], df["b"]
    roll_s = s.rolling(window, min_periods=window)
    roll_b = b.rolling(window, min_periods=window)

    beta = roll_s.cov(b) / roll_b.var()
    corr = roll_s.corr(b)
    excess = (roll_s.mean() - roll_b.mean()) * TRADING_DAYS
    te = (s - b).rolling(window, min_periods=window).std() * math.sqrt(TRADING_DAYS)
    ir = excess / te.where(te > _TE_FLOOR)

    out = pd.DataFrame({"excess": excess, "ir": ir, "beta": beta, "corr": corr})
    return out.replace([np.inf, -np.inf], np.nan)


def risk_sleeve_relative(equity_returns: pd.Series, weights: pd.DataFrame,
                         close: pd.DataFrame, classification: dict,
                         benchmark: pd.Series) -> dict:
    """剔除防守仓后的相对指标（N9）。

    步骤：
      ① `w_risk` = weights 把 bond/money 列置 0；
      ② `w_eff = w_risk.shift(1)`（T 日权重配 T+1 收益）；
      ③ `mean_risk_weight = w_eff.sum(axis=1).mean()`，`beta_scaling` 取之；
      ④ 风险仓收益 `sleeve = Σ w_eff × r_asset`；归一化 `w_norm = w_eff / mean_risk_weight`
         后得到 `sleeve_norm`（平均暴露 = 1，与满仓基准可比）；
      ⑤ `corr_risk_sleeve` 用 `sleeve_norm`（尺度无关），`beta_risk_sleeve` 同；
         `corr_full/beta_full` 用策略整体收益与基准。
    """
    keys = ["corr_full", "beta_full", "corr_risk_sleeve", "beta_risk_sleeve",
            "beta_scaling", "mean_risk_weight"]
    if weights is None or close is None or benchmark is None:
        return {key: None for key in keys}

    w = pd.DataFrame(weights).sort_index().astype("float64")
    defensive = [c for c in w.columns
                 if str(classification.get(str(c), "risk")) in _DEFENSIVE]
    w_risk = w.copy()
    w_risk[defensive] = 0.0
    w_eff = w_risk.shift(1)          # T 日权重 → T+1 生效

    rets = pd.DataFrame(close).pct_change(fill_method=None).reindex(
        index=w_eff.index, columns=w_eff.columns)

    weight_sum = w_eff.sum(axis=1, min_count=1)   # 首行（shift 后）保持 NaN，不稀释均值
    mean_risk_weight = _finite(float(weight_sum.mean())) if weight_sum.notna().any() else None
    bench = pd.Series(benchmark, dtype="float64")
    beta_full, corr_full = _beta_corr(*_pair(equity_returns, bench))

    if mean_risk_weight is None or mean_risk_weight <= 0:
        return {"corr_full": corr_full, "beta_full": beta_full,
                "corr_risk_sleeve": None, "beta_risk_sleeve": None,
                "beta_scaling": None, "mean_risk_weight": mean_risk_weight}

    sleeve = (w_eff * rets).sum(axis=1, min_count=1)
    sleeve_norm = ((w_eff / mean_risk_weight) * rets).sum(axis=1, min_count=1)
    beta_risk, corr_risk = _beta_corr(*_pair(sleeve_norm, bench))

    return {
        "corr_full": corr_full,
        "beta_full": beta_full,
        "corr_risk_sleeve": corr_risk,
        "beta_risk_sleeve": beta_risk,
        "beta_scaling": mean_risk_weight,
        "mean_risk_weight": mean_risk_weight,
    }


def _pair(a: pd.Series, b: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """两个序列按日期内连接 dropna，返回 numpy 数组（供 beta/corr 计算）。"""
    df = pd.concat([pd.Series(a, dtype="float64").rename("a"),
                    pd.Series(b, dtype="float64").rename("b")], axis=1).dropna()
    return df["a"].to_numpy(), df["b"].to_numpy()


def _annual_returns(returns: pd.Series) -> pd.Series:
    """日收益 → 年收益（自然年复利）。"""
    r = pd.Series(returns, dtype="float64").dropna()
    out = (1.0 + r).groupby(r.index.year).prod() - 1.0
    out.index = out.index.astype(int)
    return out


def annual_excess(strategy: pd.Series, benchmark: pd.Series) -> pd.DataFrame:
    """逐年对比：strategy_pct / benchmark_pct / excess_pct（差值，非比值）。"""
    s = _annual_returns(strategy)
    b = _annual_returns(benchmark)
    years = sorted(set(s.index) & set(b.index))
    rows = [{
        "year": int(year),
        "strategy_pct": _finite(float(s.loc[year])),
        "benchmark_pct": _finite(float(b.loc[year])),
        "excess_pct": _subtract(_finite(float(s.loc[year])), _finite(float(b.loc[year]))),
    } for year in years]
    return pd.DataFrame(rows, columns=["year", "strategy_pct", "benchmark_pct", "excess_pct"])


def _lag_scan(strategy: pd.Series, benchmark: pd.Series) -> dict:
    """滞后相关扫描（按 lag 数值升序写 JSON；peak_lag 在 |lag| 序上取 idxmax）。"""
    corr = lag_correlation(strategy, benchmark)
    peak_lag = int(corr.idxmax()) if corr.notna().any() else None
    ordered = corr.sort_index()
    return {
        "lags": [int(lag) for lag in ordered.index],
        "corrs": [_finite(None if pd.isna(v) else float(v)) for v in ordered.to_list()],
        "peak_lag": peak_lag,
    }


def build(ctx: ReportContext) -> dict:
    """派生产物：summary / rolling / annual_excess / ex_defensive / lag_scan。"""
    if ctx.benchmark is None:
        raise RuntimeError("benchmark 缺失：该 run 的档位不含 benchmark.parquet")
    if ctx.equity is None:
        raise RuntimeError("equity 缺失：该 run 的档位不含 equity.parquet")
    if ctx.weights is None or ctx.close is None:
        raise RuntimeError("weights/close 缺失：该 run 的档位不含 weights.parquet")
    if "hs300" not in ctx.benchmark.columns:
        raise RuntimeError("benchmark.parquet 缺少 hs300 列")

    strategy = ctx.equity["returns"]
    benchmark = ctx.benchmark["hs300"].pct_change(fill_method=None)

    rolling = rolling_relative(strategy, benchmark)
    return {
        "summary": relative_summary(strategy, benchmark),
        "rolling": {"window": ROLLING_WINDOW,
                    "rows": records(rolling, index="date")},
        "annual_excess": records(annual_excess(strategy, benchmark), index=None),
        "ex_defensive": risk_sleeve_relative(strategy, ctx.weights, ctx.close,
                                             ctx.classification, benchmark),
        "lag_scan": _lag_scan(strategy, benchmark),
    }
