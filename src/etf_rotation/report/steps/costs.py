"""成本拖累与盈亏平衡成本（N13）。

口径（先对账再写公式）：
    equity["turnover"] 是 bt 的 `min(买入额, 卖出额) / nav`（单边换手），不是
    `Σ|Δw|/2`。用 `trades.notional / (2 × 当日 nav)` 复算会系统性偏高，因为
    单边成交日（只有买或只有卖）的 min 为 0，而按名义额折半仍计入。本模块的
    换手口径一律直接取 `equity["turnover"]`，年化 = 日均 × 252。

公式：
    drag_pct       = 年费用 / 年均净值
    return_pct     = 年末净值 / 年初净值 − 1
    cost_share_pct = 费用 / (收益额 + 费用)        （收益额 = return_pct × 年初净值）
    breakeven_bps  = (ann_return + annual_drag) / (2 × ann_one_side_turnover) × 1e4

`ctx.metrics` 可能缺键（NaN 指标会被 `all_stats` 丢掉），一律 `.get`，缺失输出 None。
"""
from __future__ import annotations

import math

import pandas as pd

from etf_rotation.report.context import ReportContext
from etf_rotation.report.serialize import records

NAME = "costs"

TRADING_DAYS = 252

ANNUAL_COLUMNS = ["year", "fees", "avg_nav", "drag_pct", "return_pct", "cost_share_pct"]

_TURNOVER_BASIS = (
    "equity.turnover = bt 的 min(买入额, 卖出额)/nav（单边换手，逐日）；"
    "年化 = 日均 × 252。trades.notional/(2×当日nav) 因单边成交日的 min 为 0 "
    "而系统性偏高，仅作量级对账，不用于 breakeven。"
)


def _num(value) -> float | None:
    """None/NaN/Inf → None，其余转 float（JSON 侧禁止非有限数）。"""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def annual_cost_drag(equity: pd.DataFrame, trades: pd.DataFrame | None = None) -> pd.DataFrame:
    """分年成本表：year, fees, avg_nav, drag_pct, return_pct, cost_share_pct。

    费用只取 `equity["fees"]`（引擎记账口径，与净值同源）；`trades` 参数保留给
    上游契约，不参与计算——逐笔成本已按同一公式汇总进 `equity["fees"]`。
    """
    if equity is None or "nav" not in equity:
        return pd.DataFrame(columns=ANNUAL_COLUMNS)

    df = equity.sort_index()
    nav = pd.to_numeric(df["nav"], errors="coerce")
    rows: list[dict] = []
    for year, positions in nav.groupby(nav.index.year).groups.items():
        block = df.loc[positions]
        navs = nav.loc[positions].dropna()

        fees = _num(block["fees"].sum()) if "fees" in block.columns else None
        avg_nav = _num(navs.mean()) if len(navs) else None
        drag = fees / avg_nav if fees is not None and avg_nav not in (None, 0) else None

        ret = None
        if len(navs) >= 2 and navs.iloc[0] > 0:
            ret = _num(navs.iloc[-1] / navs.iloc[0] - 1.0)

        share = None
        if fees is not None and ret is not None and navs.iloc[0] > 0:
            denom = ret * float(navs.iloc[0]) + fees
            if abs(denom) > 0:
                share = _num(fees / denom)

        rows.append({
            "year": int(year),
            "fees": fees,
            "avg_nav": avg_nav,
            "drag_pct": _num(drag),
            "return_pct": ret,
            "cost_share_pct": share,
        })

    return pd.DataFrame(rows, columns=ANNUAL_COLUMNS)


def breakeven_bps(ann_return: float | None,
                  ann_one_side_turnover: float | None,
                  annual_drag: float | None) -> float | None:
    """盈亏平衡单边成本（bp）：`(ann_return + annual_drag) / (2 × turnover) × 1e4`。

    分母为零/缺失 → None（无换手时「平衡成本」没有定义）。
    """
    ann_return = _num(ann_return)
    turnover = _num(ann_one_side_turnover)
    drag = _num(annual_drag)
    if ann_return is None or turnover is None or drag is None or turnover <= 0:
        return None
    return _num((ann_return + drag) / (2.0 * turnover) * 1e4)


def annual_one_side_turnover(equity: pd.DataFrame) -> float | None:
    """年化单边换手：`equity["turnover"]` 日均 × 252（与 bt 口径一致）。"""
    if equity is None or "turnover" not in equity.columns:
        return None
    turnover = pd.to_numeric(equity["turnover"], errors="coerce").dropna()
    if turnover.empty:
        return None
    return _num(float(turnover.mean()) * TRADING_DAYS)


def turnover_reconciliation(equity: pd.DataFrame | None,
                            trades: pd.DataFrame | None) -> dict:
    """量级对账：`equity["turnover"]` 合计 vs `trades.notional / (2 × 当日 nav)`。

    两者定义不同（见模块 docstring），这里只记录差异供审计，不据此改写换手。
    """
    empty = {
        "equity_turnover_sum": None,
        "trades_one_side_sum": None,
        "relative_error": None,
        "basis": _TURNOVER_BASIS,
    }
    if equity is None or trades is None or equity.empty or trades.empty:
        return empty
    if "turnover" not in equity.columns or "notional" not in trades.columns:
        return empty

    total = _num(pd.to_numeric(equity["turnover"], errors="coerce").sum())
    nav = pd.to_numeric(equity["nav"], errors="coerce") if "nav" in equity.columns else None
    if nav is None or total in (None, 0):
        return empty

    dates = pd.to_datetime(trades["date"])
    nav_on_date = nav.reindex(pd.DatetimeIndex(dates)).to_numpy(dtype="float64")
    one_side = pd.Series(
        pd.to_numeric(trades["notional"], errors="coerce").to_numpy(dtype="float64")
        / (2.0 * nav_on_date), index=trades.index)
    one_side = one_side.replace([float("inf"), float("-inf")], float("nan")).dropna()
    implied = _num(one_side.sum())
    rel = _num(abs(implied - total) / abs(total)) if implied is not None else None
    return {
        "equity_turnover_sum": total,
        "trades_one_side_sum": implied,
        "relative_error": rel,
        "basis": _TURNOVER_BASIS,
    }


def reconcile(trades: pd.DataFrame | None, metrics: dict,
              equity: pd.DataFrame | None = None) -> dict:
    """费用对账：`trades.cost.sum()` vs `metrics["total_fees"]`，附换手量级对账。"""
    trades_cost = None
    if trades is not None and not trades.empty and "cost" in trades.columns:
        trades_cost = _num(pd.to_numeric(trades["cost"], errors="coerce").sum())

    total_fees = _num((metrics or {}).get("total_fees"))
    diff = _num(trades_cost - total_fees) if trades_cost is not None and total_fees is not None else None
    if diff is None:
        relative_error = None
    elif total_fees == 0:
        relative_error = 0.0 if diff == 0 else None
    else:
        relative_error = _num(abs(diff) / abs(total_fees))

    return {
        "trades_cost": trades_cost,
        "total_fees": total_fees,
        "diff": diff,
        "relative_error": relative_error,
        "turnover": turnover_reconciliation(equity, trades),
    }


def build(ctx: ReportContext) -> dict:
    """派生产物：分年成本表、盈亏平衡成本、费用/换手对账与假设。"""
    if ctx.equity is None:
        raise RuntimeError("equity 缺失：该 run 的档位不含 equity.parquet")

    annual = annual_cost_drag(ctx.equity, ctx.trades)
    drags = pd.to_numeric(annual["drag_pct"], errors="coerce").dropna() if not annual.empty else pd.Series(dtype=float)
    annual_drag = _num(drags.mean()) if not drags.empty else None

    ann_return = _num((ctx.metrics or {}).get("ann_return"))
    ann_turnover = annual_one_side_turnover(ctx.equity)
    bps = breakeven_bps(ann_return, ann_turnover, annual_drag)

    return {
        "annual": records(annual, index=None),
        "breakeven": {
            "bps": bps,
            "ann_return": ann_return,
            "ann_one_side_turnover": ann_turnover,
            "annual_drag": annual_drag,
        },
        "reconciliation": reconcile(ctx.trades, ctx.metrics or {}, ctx.equity),
        "assumptions": {
            "turnover_basis": _TURNOVER_BASIS,
            "breakeven_formula": "(ann_return + annual_drag) / (2 × ann_one_side_turnover) × 1e4",
            "ann_return_source": "metrics.ann_return（缺失时 bps 为 null，不猜测）",
            "annual_drag": "分年 drag_pct（费用/年均净值）的均值",
            "cost_basis": "trades.cost = notional × 单边 bps / 1e4，与 equity.fees 同源",
        },
    }
