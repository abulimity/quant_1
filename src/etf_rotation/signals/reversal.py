from __future__ import annotations

import numpy as np
import pandas as pd


def zbias(close: pd.Series, ema_span: int = 14, z_window: int = 170) -> pd.Series:
    ema = close.ewm(span=ema_span, adjust=False).mean()
    logbias = np.log(close / ema)
    mu = logbias.rolling(z_window).mean().shift(1)
    sd = logbias.rolling(z_window).std().shift(1)
    return (logbias - mu) / sd


def active(close: pd.Series, threshold: float = -0.5, lookback: int = 3) -> pd.Series:
    z = zbias(close)
    return (z <= threshold) & (z > z.shift(lookback))

