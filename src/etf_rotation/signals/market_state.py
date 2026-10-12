"""市场状态识别：三指数 LLT 斜率 → 复合分 → 牛/熊/震荡。"""
from __future__ import annotations

import pandas as pd


def llt(close: pd.Series, alpha: float) -> pd.Series:
    """Ehlers Low-Lag Filter（低延时趋势线，H2 假设）。"""
    a = alpha
    c = [a - a * a / 4, a * a / 2, -(a - 3 * a * a / 4), 2 * (1 - a), -(1 - a) ** 2]
    y = pd.Series(index=close.index, dtype=float)
    y.iloc[:2] = close.iloc[:2]
    x = close.to_numpy()
    for i in range(2, len(close)):
        y.iloc[i] = (
            c[0] * x[i] + c[1] * x[i - 1] + c[2] * x[i - 2]
            + c[3] * y.iloc[i - 1] + c[4] * y.iloc[i - 2]
        )
    return y


def composite_score(indexes: dict, alpha: float = 0.10, win: int = 8) -> pd.Series:
    """三指数各算 8 日 LLT 斜率状态（+1/0/−1）后等权平均，得 [-1,1] 复合分。"""
    states = pd.DataFrame({k: _slope_state(v, alpha, win) for k, v in indexes.items()})
    return states.mean(axis=1)


def _slope_state(close: pd.Series, alpha: float, win: int) -> pd.Series:
    """单指数状态：8 日 LLT 斜率 >1.005 记 +1，<0.995 记 −1，其余 0。"""
    l = llt(close, alpha)
    slope = l / l.shift(win)
    out = pd.Series(0.0, index=close.index)
    out.loc[slope > 1.005] = 1.0
    out.loc[slope < 0.995] = -1.0
    return out

