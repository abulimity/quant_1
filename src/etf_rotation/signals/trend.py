from __future__ import annotations

import numpy as np
import pandas as pd


def momentum_score(close: pd.Series, window: int, ann: int = 250) -> pd.Series:
    logp = np.log(close)
    out = pd.Series(index=close.index, dtype=float)
    for i in range(window, len(close) + 1):
        y = logp.iloc[i - window : i].to_numpy()
        x = np.arange(1, window + 1, dtype=float)
        w = x / x.sum()  # H1：线性时间权重
        xw = (w * x).sum()
        yw = (w * y).sum()
        slope = (w * (x - xw) * (y - yw)).sum() / (w * (x - xw) ** 2).sum()
        yhat = slope * x + (yw - slope * xw)
        ss_res = (w * (y - yhat) ** 2).sum()
        ss_tot = (w * (y - yw) ** 2).sum()
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        out.iloc[i - 1] = (np.exp(ann * slope) - 1) * r2
    return out

