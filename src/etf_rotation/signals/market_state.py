"""市场状态识别：三指数 LLT 斜率 → 复合分 → 牛/熊/震荡。"""
from __future__ import annotations

import pandas as pd


def llt(close: pd.Series, alpha: float) -> pd.Series:
    """Ehlers Low-Lag Filter（低延时趋势线，H2 假设）。

    与普通均线相比，LLT 用一组负系数「预补」当期价格，从而在转折点响应更快；
    alpha 越小越平滑、滞后越大。递推式：
    y[i] = c0·x[i] + c1·x[i-1] + c2·x[i-2] + c3·y[i-1] + c4·y[i-2]。
    """
    a = alpha
    # LLT 的 5 个递推系数（Ehlers 公式）：c0/c1 取当期与上期价格，c2 是负系数前馈项，
    # c3/c4 是自回归项，使滤波器的相位滞后小于同周期均线。
    c = [a - a * a / 4, a * a / 2, -(a - 3 * a * a / 4), 2 * (1 - a), -(1 - a) ** 2]
    y = pd.Series(index=close.index, dtype=float)
    y.iloc[:2] = close.iloc[:2]  # 前两期用原始价初始化，递推从第 3 个点开始
    x = close.to_numpy()
    for i in range(2, len(close)):
        y.iloc[i] = (
            c[0] * x[i] + c[1] * x[i - 1] + c[2] * x[i - 2]
            + c[3] * y.iloc[i - 1] + c[4] * y.iloc[i - 2]
        )
    return y


def composite_score(indexes: dict, alpha: float = 0.10, win: int = 8,
                    slope_up: float = 1.005, slope_down: float = 0.995) -> pd.Series:
    """三指数各算 8 日 LLT 斜率状态（+1/0/−1）后等权平均，得 [-1,1] 复合分。"""
    states = pd.DataFrame({k: _slope_state(v, alpha, win, slope_up, slope_down)
                           for k, v in indexes.items()})
    return states.mean(axis=1)


def _slope_state(close: pd.Series, alpha: float, win: int,
                 slope_up: float, slope_down: float) -> pd.Series:
    """单指数状态：8 日 LLT 斜率 > slope_up 记 +1，< slope_down 记 −1，其余 0。"""
    l = llt(close, alpha)
    # 8 日斜率 = LLT / LLT.shift(8)：>slope_up 即 8 日累计涨幅超阈值（上升趋势），
    # <slope_down 即累计跌幅超阈值（下降趋势），中间视为无方向。
    slope = l / l.shift(win)
    out = pd.Series(0.0, index=close.index)
    out.loc[slope > slope_up] = 1.0
    out.loc[slope < slope_down] = -1.0
    return out

