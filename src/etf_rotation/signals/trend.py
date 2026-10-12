"""趋势得分：时间加权线性回归的斜率与 R² 合成（研报 Momentum 公式）。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def momentum_score(close: pd.Series, window: int, ann: int = 250) -> pd.Series:
    """Momentum(w) = [exp(250·Slope(w)) − 1] · R²(w)。

    对复权价对数序列做时间加权（线性权重，越近权重越大，H1 假设）最小二乘，
    Slope 为回归斜率（250 日年化），R² 为趋势质量折扣因子。单序列循环实现，
    供纳指/黄金等少量标的；大批量横截面用 pipeline.momentum_panel 的向量化版本。
    """
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

