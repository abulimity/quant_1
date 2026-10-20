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


def momentum_panel(logp: pd.DataFrame, window: int, ann: int = 250,
                   weighting: str = "linear") -> pd.DataFrame:
    """向量化的时间加权回归趋势分面板（列 = ticker，与 momentum_score 同公式）。

    对每个标的的对数价序列，用最近 window 期做时间加权最小二乘：Slope 是回归斜率
    （ann 日年化后经 exp 映射为动量），R² 是拟合优度折扣因子；最终
    Momentum = (exp(ann·Slope) − 1) · R²。滑动窗口视图一次算完全列，按 chunk 分批控制内存。
    """
    x = np.arange(1, window + 1, dtype=float)
    w = _time_weights(window, weighting)
    xw = (w * x).sum()
    denom = (w * (x - xw) ** 2).sum()
    arr = logp.to_numpy()
    n, m = arr.shape
    out = np.full((n, m), np.nan)
    chunk = 128
    for c in range(0, m, chunk):
        sub = arr[:, c : c + chunk]
        y = np.lib.stride_tricks.sliding_window_view(sub, window, axis=0)
        yw = np.tensordot(y, w, axes=([2], [0]))
        slope = np.tensordot(y, w * (x - xw), axes=([2], [0])) / denom
        yhat = slope[..., None] * x + (yw - slope * xw)[..., None]
        ss_res = np.tensordot((y - yhat) ** 2, w, axes=([2], [0]))
        ss_tot = np.tensordot((y - yw[..., None]) ** 2, w, axes=([2], [0]))
        r2 = 1 - ss_res / np.where(ss_tot > 0, ss_tot, 1.0)
        r2 = np.where(ss_tot > 0, r2, 0.0)
        mom = (np.exp(ann * slope) - 1) * r2
        out[window - 1 :, c : c + chunk] = mom
    return pd.DataFrame(out, index=logp.index, columns=logp.columns)


def momentum_score(close: pd.Series, window: int, ann: int = 250,
                   weighting: str = "linear") -> pd.Series:
    """Momentum(w) = [exp(ann·Slope(w)) − 1] · R²(w)，单序列薄封装（momentum_panel 单列）。"""
    return momentum_panel(np.log(close).to_frame(), window, ann, weighting).iloc[:, 0]
