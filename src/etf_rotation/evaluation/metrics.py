"""回测指标：唯一来源是 bt/ffn 内置统计，不做自行推导。

纪律：所有报告里的绩效数字都直接取 ffn 的统计量，不在这里二次实现
（年化/Sharpe/Sortino/Calmar 的口径差异很容易造成「报告与代码对不上」）。
本模块只做「键名映射」，把 ffn 的列名翻译成报告口径。
"""
from __future__ import annotations

import pandas as pd


def from_stats(stats: pd.Series) -> dict:
    """bt Result.stats[name] → 报告口径（直接取 ffn 值，已是年化口径）。

    映射关系（全部是 ffn 的现成列，无自行推导）：
      ann_return   ← cagr          —— 年化复合收益率
      ann_vol      ← daily_vol     —— 日波动（ffn 口径已年化）
      sharpe       ← daily_sharpe  —— 日频夏普（ffn 口径已年化）
      sortino      ← daily_sortino —— 日频索提诺（ffn 口径已年化）
      max_drawdown ← max_drawdown  —— 最大回撤（负值）
      calmar       ← calmar        —— 年化收益 / |最大回撤|

    注意：本函数不含 VaR / CVaR —— 研报报告里的这两个指标在本项目未复现，
    对标时只比较「同量级」的核心指标（见 reports/回测报告.md）。
    """
    return {
        "ann_return": float(stats["cagr"]),
        "ann_vol": float(stats["daily_vol"]),
        "sharpe": float(stats["daily_sharpe"]),
        "sortino": float(stats["daily_sortino"]),
        "max_drawdown": float(stats["max_drawdown"]),
        "calmar": float(stats["calmar"]),
    }
