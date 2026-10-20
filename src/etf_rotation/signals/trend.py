"""趋势得分：时间加权线性回归的斜率与 R² 合成（研报 Momentum 公式）。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _time_weights(window: int, weighting: str = "linear") -> np.ndarray:
    """H1 时间权重（越近权重越大，归一化）。

    - linear：线性递增权重（默认，研报原假设 H1）。
    - exp：指数衰减权重（H1 敏感性候选），w ∝ exp(0.05·(t−window))。
    """
    x = np.arange(1, window + 1, dtype=float)
    if weighting == "linear":
        w = x
    elif weighting == "exp":
        w = np.exp(0.05 * (x - window))
    else:
        raise ValueError(f"unknown weighting: {weighting!r} (expected 'linear' or 'exp')")
    return w / w.sum()


def momentum_score(close: pd.Series, window: int, ann: int = 250,
                   weighting: str = "linear") -> pd.Series:
    """Momentum(w) = [exp(ann·Slope(w)) − 1] · R²(w)。

    对复权价对数序列做时间加权（H1，权重见 `_time_weights`）最小二乘，
    Slope 为回归斜率（ann 日年化），R² 为趋势质量折扣因子。单序列循环实现，
    供纳指/黄金等少量标的；大批量横截面用 pipeline.momentum_panel 的向量化版本。
    """
    logp = np.log(close)
    x = np.arange(1, window + 1, dtype=float)
    w = _time_weights(window, weighting)
    xw = (w * x).sum()
    denom = (w * (x - xw) ** 2).sum()
    out = pd.Series(index=close.index, dtype=float)
    for i in range(window, len(close) + 1):
        y = logp.iloc[i - window : i].to_numpy()
        yw = (w * y).sum()
        slope = (w * (x - xw) * (y - yw)).sum() / denom
        yhat = slope * x + (yw - slope * xw)
        ss_res = (w * (y - yhat) ** 2).sum()
        ss_tot = (w * (y - yw) ** 2).sum()
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        out.iloc[i - 1] = (np.exp(ann * slope) - 1) * r2
    return out
