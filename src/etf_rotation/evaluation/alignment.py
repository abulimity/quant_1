"""信号/收益对齐诊断：滞后相关扫描。

用途：基准对齐自检（N1）。若基准被多 shift 了一次，同日相关系数会从
约 0.5 掉到 0 附近，而峰值会出现在滞后项上；本模块把这条诊断固化成函数。
"""
from __future__ import annotations

import pandas as pd


def lag_correlation(
    strategy: pd.Series, benchmark: pd.Series, max_lag: int = 5
) -> pd.Series:
    """扫描策略收益与基准收益在不同滞后下的相关系数。

    定义（k 为「策略相对基准的滞后」，负值表示策略滞后）：
      corr_k = Corr(s_t, b_{t+k})
    即 k=-1 时比较 s_t 与 b_{t-1}：若策略晚一天反应，峰值会落在 -1；
    同日对齐则峰值落在 0。

    参数：
      strategy  —— 策略日收益序列
      benchmark —— 基准日收益序列
      max_lag   —— 扫描范围 [-max_lag, max_lag]

    返回：
      index 为 lag（整数）、值为相关系数的 Series。NaN 按 pandas 默认
      成对剔除，不做 fillna，避免制造虚假相关性。索引按 |lag| 升序排列
      （0, ±1, ±2…），这样周期性样本出现并列峰值时，idxmax 会优先
      返回最靠近 0 的滞后，而不是边界的 ±max_lag。
    """
    strategy = pd.Series(strategy)
    benchmark = pd.Series(benchmark)
    order = [0]
    for k in range(1, max_lag + 1):
        order.extend([k, -k])
    corr = {
        k: strategy.corr(benchmark.shift(-k))
        for k in order
        if abs(k) <= max_lag
    }
    out = pd.Series(corr, dtype=float, name="correlation")
    out.index.name = "lag"
    return out
