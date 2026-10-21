"""反转信号：14 日 EMA 偏离度经 170 日滚动 z-score 标准化（ZBias）。

用途：在震荡市里识别「短期超跌、正在修复」的标的，作为动量分之外的补充信号。

关键纪律：均值与标准差都用 `.shift(1)`，即基准分布只包含截至前一日的数据，
避免「用当日偏离值参与计算当日基准」这一前视偏差（见 docs/代码审阅手册.md §8.2）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def zbias(close: pd.Series, ema_span: int = 14, z_window: int = 170) -> pd.Series:
    """ZBias = (LogBias − Mean170) / Std170，均值/标准差均 .shift(1) 防前视。

    三步公式：
      ① EMA_t = (1−α)P_t + α·EMA_{t−1}   —— α = 2/(span+1)，span=14
      ② LogBias = ln(P/EMA)              —— 当前价相对 EMA 的对数偏离
      ③ ZBias = (LogBias − μ̄_{170,t−1}) / σ_{170,t−1}
         —— μ̄、σ 取截至 t−1 日的 170 期滚动均值/标准差（.shift(1)），
            标准化后可比不同标的、不同价位的偏离幅度。
    ZBias < 0 表示价格低于自身 EMA（超跌方向），越大越超跌。
    """
    ema = close.ewm(span=ema_span, adjust=False).mean()
    logbias = np.log(close / ema)          # LogBias = ln(P/EMA)
    # 基准分布截至前一日：.shift(1) 保证今天只用昨天的均值/标准差
    mu = logbias.rolling(z_window).mean().shift(1)
    sd = logbias.rolling(z_window).std().shift(1)
    # ZBias = (LogBias − μ̄_{170,t−1}) / σ_{170,t−1}
    return (logbias - mu) / sd


def active(close: pd.Series, threshold: float = -0.5, lookback: int = 3) -> pd.Series:
    """反转激活：明显超跌（ZBias ≤ −0.5）且负向偏离较 3 个交易日前收窄。

    公式：active_t = (ZBias_t ≤ θ) 且 (ZBias_t > ZBias_{t−lookback})
      —— θ 为超跌阈值（默认 −0.5）；第二个条件要求「比 lookback 日前更靠近 0」，
         即偏离正在收窄（修复中）而不是继续下跌。
    """
    z = zbias(close)
    return (z <= threshold) & (z > z.shift(lookback))
