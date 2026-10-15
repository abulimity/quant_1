"""回测指标：唯一来源是 bt/ffn 内置统计，不做自行推导。"""
from __future__ import annotations

import pandas as pd


def from_stats(stats: pd.Series) -> dict:
    """bt Result.stats[name] → 报告口径（直接取 ffn 值，已是年化口径）。"""
    return {
        "ann_return": float(stats["cagr"]),
        "ann_vol": float(stats["daily_vol"]),
        "sharpe": float(stats["daily_sharpe"]),
        "sortino": float(stats["daily_sortino"]),
        "max_drawdown": float(stats["max_drawdown"]),
        "calmar": float(stats["calmar"]),
    }

