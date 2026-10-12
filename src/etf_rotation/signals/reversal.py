"""反转信号：14 日 EMA 偏离度经 170 日滚动 z-score 标准化（ZBias）。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def zbias(close: pd.Series, ema_span: int = 14, z_window: int = 170) -> pd.Series:
    """ZBias = (LogBias − Mean170) / Std170，均值/标准差均 .shift(1) 防前视。"""
    ema = close.ewm(span=ema_span, adjust=False).mean()
    logbias = np.log(close / ema)
    mu = logbias.rolling(z_window).mean().shift(1)
    sd = logbias.rolling(z_window).std().shift(1)
    return (logbias - mu) / sd


def active(close: pd.Series, threshold: float = -0.5, lookback: int = 3) -> pd.Series:
    """反转激活：明显超跌（ZBias ≤ −0.5）且负向偏离较 3 个交易日前收窄。"""
    z = zbias(close)
    return (z <= threshold) & (z > z.shift(lookback))

