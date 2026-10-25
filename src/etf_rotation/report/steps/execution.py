"""目标 vs 实际持仓（N6）与换手分解（N8）。

索引语义（计划 §3 Review Focus）：
    weights   —— 目标权重，索引是**信号日 T**（T 日收盘后确定）
    holdings  —— 引擎实际持仓，索引是**成交/估值日 t**

因此目标必须显式 `.shift(1)` 后再与 holdings 比较：
`target_eff_t = weights_{t−1}`（T 日信号在 T+1 生效）。
不 shift 会把「今天的信号」和「今天的成交」直接相减，得到虚假执行偏差。

指标：
    mean_abs_t = Σ_i |actual_{i,t} − target_eff_{i,t}| / 2      （单边口径）
    max_abs_t  = max_i |actual_{i,t} − target_eff_{i,t}|

换手分解：
    turnover_t = Σ_i |w_{i,t} − w_{i,t−1}| / 2
按日记**主事件**整日归因（优先级 overheat → vol_cap → switch → defensive → other），
再按自然年汇总。`reconcile = 分量合计 − equity.turnover 年合计`：
两边口径不同（权重面板 vs 引擎成交额/净值），差额如实给出，不强行归零。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from etf_rotation.report.context import ReportContext
from etf_rotation.report.serialize import records

NAME = "execution"

# 换手分量（顺序即输出列顺序；reconcile 不计入分量）
BUCKETS = ("switch", "overheat", "vol_cap", "defensive", "other")
# vol_cap_scale 与 1.0 的比较容差（浮点噪声不算缩放）
_SCALE_TOL = 1e-9


def target_vs_actual(weights: pd.DataFrame, holdings: pd.DataFrame) -> pd.DataFrame:
    """逐日目标权重 vs 引擎实际持仓的偏差表（index = holdings 交易日）。

    返回列 `mean_abs` / `max_abs`；两侧标的先按 holdings 的列对齐，
    目标端缺失的标的按 0 处理（未持仓），实际端 NaN 也按 0（尚未建仓）。
    """
    if holdings is None or weights is None:
        return pd.DataFrame(columns=["mean_abs", "max_abs"])

    h = pd.DataFrame(holdings).sort_index().astype("float64")
    w = pd.DataFrame(weights).sort_index().astype("float64")
    target = w.shift(1).reindex(index=h.index, columns=h.columns).fillna(0.0)
    actual = h.fillna(0.0)

    gap = (actual - target).abs()
    out = pd.DataFrame({
        "mean_abs": gap.sum(axis=1, min_count=1) / 2.0,
        "max_abs": gap.max(axis=1),
    }, index=h.index)
    return out


def _event_bucket(diary: pd.DataFrame, index: pd.Index) -> pd.Series:
    """每个交易日的**主事件**标签（唯一归属，优先级固定）。"""
    d = pd.DataFrame(diary).reindex(index)
    overheat = _numeric(d, "n_overheat_exits", 0.0) > 0.0
    vol_cap = _numeric(d, "vol_cap_scale", 1.0) < (1.0 - _SCALE_TOL)
    switch = ~_numeric(d, "hysteresis_held", 1.0).fillna(1.0).astype(bool)
    defensive = _numeric(d, "n_defensive", 0.0).diff().abs() > 0.0

    labels = np.select(
        [overheat.to_numpy(), vol_cap.to_numpy(), switch.to_numpy(), defensive.to_numpy()],
        ["overheat", "vol_cap", "switch", "defensive"],
        default="other",
    )
    return pd.Series(labels, index=index, dtype=object)


def _numeric(diary: pd.DataFrame, name: str, default: float) -> pd.Series:
    """取日记数值列；缺列返回常量列（该规则不触发）。"""
    if name in diary.columns:
        return pd.Series(diary[name], index=diary.index).astype("float64")
    return pd.Series(float(default), index=diary.index, dtype="float64")


def _annual_engine_turnover(equity: pd.DataFrame | None) -> pd.Series | None:
    """引擎年换手（`equity.turnover` 按年求和）；没有 equity/turnover 返回 None。"""
    if equity is None:
        return None
    frame = pd.DataFrame(equity)
    if "turnover" not in frame.columns or frame.empty:
        return None
    turnover = pd.Series(frame["turnover"], index=frame.index).astype("float64").dropna()
    if turnover.empty:
        return None
    out = turnover.groupby(turnover.index.year).sum()
    out.index = out.index.astype(int)
    return out


def turnover_split(diary: pd.DataFrame, weights: pd.DataFrame,
                   equity: pd.DataFrame | None = None) -> pd.DataFrame:
    """按年换手分解：`switch/overheat/vol_cap/defensive/other` + `reconcile`。

    `equity` 可选：给了才计算 `reconcile = 分量合计 − 引擎 turnover 年合计`；
    未给时该列为 None（不伪造对齐）。
    """
    w = pd.DataFrame(weights).sort_index().astype("float64")
    if w.empty:
        return pd.DataFrame(columns=["year", *BUCKETS, "total", "reconcile"])

    delta = w.diff()
    daily = delta.abs().sum(axis=1) / 2.0
    daily = daily.fillna(0.0)
    bucket = _event_bucket(diary, w.index)

    frame = pd.DataFrame({
        "year": w.index.year,
        "turnover": daily.to_numpy(),
        "bucket": bucket.to_numpy(),
    }, index=w.index)

    rows = []
    engine = _annual_engine_turnover(equity)
    for year, block in frame.groupby("year", sort=True):
        row = {"year": int(year)}
        sums = block.groupby("bucket")["turnover"].sum()
        for name in BUCKETS:
            row[name] = float(sums.get(name, 0.0))
        row["total"] = float(sum(row[name] for name in BUCKETS))
        if engine is None:
            row["reconcile"] = None
        else:
            base = float(engine.get(int(year), np.nan))
            row["reconcile"] = float(row["total"] - base) if np.isfinite(base) else None
        rows.append(row)

    return pd.DataFrame(rows, columns=["year", *BUCKETS, "total", "reconcile"])


def build(ctx: ReportContext) -> dict:
    """派生产物：目标/实际偏差序列 + 按年换手分解。"""
    if ctx.weights is None:
        raise RuntimeError("weights 缺失：该 run 的档位不含 weights.parquet")
    if ctx.holdings is None:
        raise RuntimeError("holdings 缺失：该 run 的档位不含 holdings.parquet")
    if ctx.diary is None:
        raise RuntimeError("diary 缺失：该 run 的档位不含 signals/decision_diary.parquet")

    table = target_vs_actual(ctx.weights, ctx.holdings)
    split = turnover_split(ctx.diary, ctx.weights, equity=ctx.equity)
    valid = table["mean_abs"].dropna()

    return {
        "target_vs_actual": {
            "rows": records(table, index="date"),
            "median_mean_abs": float(valid.median()) if len(valid) else None,
            "max_mean_abs": float(valid.max()) if len(valid) else None,
            "n_days": int(len(valid)),
        },
        "turnover_split": records(split, index=None),
        "summary": {
            "total_turnover": float(split["total"].sum()) if len(split) else 0.0,
            "reconcile_sum": (float(sum(v for v in split["reconcile"] if v is not None))
                              if len(split) and split["reconcile"].notna().any() else None),
        },
    }
