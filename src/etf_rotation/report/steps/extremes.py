"""极端日（N12）：最差/最好的若干天 + 当日资产类别归因。

口径：
- 极端日 = 组合日收益最差 `top_n` 天 ∪ 最好 `top_n` 天（去重后按收益升序）；
- `class_contrib_{c,t} = Σ_{i∈c} w_{i,t−1}·r_{i,t}`，
  直接复用 `attribution.asset_class_contributions`（T−1 日权重配 t 日收益，无前视）；
- `residual_t = return_t − Σ_c class_contrib_{c,t}`：真实数据里含现金利息、费用、
  停牌/执行偏差，**不强行归零**，也不断言「贡献之和等于当日收益」；
- `regime` / `total_weight` 取当日决策日记（T 日信号口径，只读展示）。
"""
from __future__ import annotations

import math

import pandas as pd

from etf_rotation.evaluation.attribution import asset_class_contributions
from etf_rotation.report.context import ReportContext
from etf_rotation.report.serialize import records

NAME = "extremes"

COLUMNS = ["date", "return", "regime", "total_weight", "class_contrib", "residual"]

# 残差体检阈值（计划 Task 15：中位数 < 5bp、最大 < 50bp）；超出记 warning 不丢弃
MEDIAN_WARN = 0.0005
MAX_WARN = 0.005


def _finite(value):
    """NaN/Inf → None。"""
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def extreme_days(returns: pd.Series, weights: pd.DataFrame, diary: pd.DataFrame,
                 close: pd.DataFrame, classification: dict,
                 top_n: int = 10) -> pd.DataFrame:
    """组合最差/最好各 `top_n` 天的收益、状态与类别贡献（按收益升序）。"""
    r = pd.Series(returns, dtype="float64").dropna().sort_index()
    if r.empty or int(top_n) <= 0:
        return pd.DataFrame(columns=COLUMNS)

    contrib = asset_class_contributions(weights, close, classification)
    contrib = contrib.reindex(r.index).fillna(0.0)
    total_contrib = contrib.sum(axis=1)
    residual = r - total_contrib

    n = int(top_n)
    chosen = r.nsmallest(n).index.union(r.nlargest(n).index)
    chosen = chosen.sort_values()

    d = pd.DataFrame(diary).reindex(chosen)
    regime = d["regime"] if "regime" in d.columns else pd.Series(None, index=chosen)
    total_weight = d["total_weight"] if "total_weight" in d.columns \
        else pd.Series(None, index=chosen)

    rows = []
    for date in chosen:
        rows.append({
            "date": date,
            "return": float(r.loc[date]),
            "regime": regime.get(date),
            "total_weight": _finite(total_weight.get(date)),
            "class_contrib": {str(c): float(v) for c, v in contrib.loc[date].items()},
            "residual": float(residual.loc[date]),
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def build(ctx: ReportContext) -> dict:
    """派生产物：极端日表 + 残差体检（超阈值写 warnings，不静默丢弃）。"""
    if ctx.equity is None:
        raise RuntimeError("equity 缺失：该 run 的档位不含 equity.parquet")
    if ctx.weights is None:
        raise RuntimeError("weights 缺失：该 run 的档位不含 weights.parquet")
    if ctx.diary is None:
        raise RuntimeError("diary 缺失：该 run 的档位不含 signals/decision_diary.parquet")
    if ctx.close is None:
        raise RuntimeError("close 缺失：无法读取价格面板")

    table = extreme_days(ctx.equity["returns"], ctx.weights, ctx.diary,
                         ctx.close, ctx.classification)
    abs_residual = table["residual"].abs()
    median = float(abs_residual.median()) if len(table) else None
    maximum = float(abs_residual.max()) if len(table) else None

    warnings = []
    if median is not None and median > MEDIAN_WARN:
        warnings.append(f"|residual| 中位数 {median:.6f} 超过 {MEDIAN_WARN:.4f}")
    if maximum is not None and maximum > MAX_WARN:
        warnings.append(f"|residual| 最大 {maximum:.6f} 超过 {MAX_WARN:.4f}")

    return {
        "days": records(table, index=None),
        "n_days": int(len(table)),
        "median_abs_residual": median,
        "max_abs_residual": maximum,
        "warnings": warnings,
        "note": "residual = 当日收益 − Σ类别贡献（现金利息/费用/执行偏差），不强行归零",
    }
