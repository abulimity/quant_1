"""市场状态识别：三指数 LLT 斜率 → 复合分 → 牛/熊/震荡。

判定链路：
    ① 每个指数用 Ehlers LLT（低延时趋势线）滤波，得到比均线更早转向的趋势线
    ② 取 LLT 的 win 日斜率，按阈值判为 +1（上升）/ 0（无方向）/ −1（下降）
    ③ 三个指数的状态等权平均成复合分 C ∈ [−1,1]
    ④ C 与 bull/bear 阈值比较 → bull / range / bear

为什么要三指数：单一指数容易被权重股或单一风格绑架（上证被金融股主导、
中证 2000 偏小盘、中证红利偏价值），三者合起来才刻画「市场整体是否在涨」。
"""
from __future__ import annotations

import pandas as pd


def llt(close: pd.Series, alpha: float) -> pd.Series:
    """Ehlers Low-Lag Filter（低延时趋势线，H2 假设）。

    与普通均线相比，LLT 用一组负系数「预补」当期价格，从而在转折点响应更快；
    alpha 越小越平滑、滞后越大。递推式：
    y[i] = c0·x[i] + c1·x[i-1] + c2·x[i-2] + c3·y[i-1] + c4·y[i-2]。

    完整公式：
      y[i] = c₀x[i]+c₁x[i−1]+c₂x[i−2]+c₃y[i−1]+c₄y[i−2]
      c₀=α−α²/4
      c₁=α²/2
      c₂=−(α−3α²/4)
      c₃=2(1−α)
      c₄=−(1−α)²
    其中 α 为平滑参数：α 越大越贴合原价（滞后小但噪声大），越小越平滑（滞后大）。
    初始 2 期直接用原始价做种子，递推从第 3 个点开始。
    """
    a = alpha
    # LLT 的 5 个递推系数（Ehlers 公式）：c0/c1 取当期与上期价格，c2 是负系数前馈项，
    # c3/c4 是自回归项，使滤波器的相位滞后小于同周期均线。
    c = [a - a * a / 4, a * a / 2, -(a - 3 * a * a / 4), 2 * (1 - a), -(1 - a) ** 2]
    y = pd.Series(index=close.index, dtype=float)
    y.iloc[:2] = close.iloc[:2]  # 前两期用原始价初始化，递推从第 3 个点开始
    x = close.to_numpy()
    for i in range(2, len(close)):
        # 递推一步：当期/上期/上上期价格 + 上期/上上期滤波值
        y.iloc[i] = (
            c[0] * x[i] + c[1] * x[i - 1] + c[2] * x[i - 2]
            + c[3] * y.iloc[i - 1] + c[4] * y.iloc[i - 2]
        )
    return y


def composite_score(indexes: dict, alpha: float = 0.10, win: int = 8,
                    slope_up: float = 1.005, slope_down: float = 0.995) -> pd.Series:
    """三指数各算 8 日 LLT 斜率状态（+1/0/−1）后等权平均，得 [-1,1] 复合分。

    公式：C = mean(上证状态, 中证2000状态, 中证红利状态)，每个状态 ∈ {+1, 0, −1}
    故 C ∈ [−1, 1]，且以 1/3 为步长取值（三个 ±1/0 的平均）。
    """
    states = pd.DataFrame({k: _slope_state(v, alpha, win, slope_up, slope_down)
                           for k, v in indexes.items()})
    # C = mean(三指数状态)（沿列方向等权平均）
    return states.mean(axis=1)


def _slope_state(close: pd.Series, alpha: float, win: int,
                 slope_up: float, slope_down: float) -> pd.Series:
    """单指数状态：8 日 LLT 斜率 > slope_up 记 +1，< slope_down 记 −1，其余 0。

    公式：s = LLT_t / LLT_{t−win}
      —— 即 LLT 在 win 日内的累计变化倍数；
         s > slope_up → +1（上升趋势）；s < slope_down → −1（下降趋势）；否则 0。
    """
    l = llt(close, alpha)
    # 8 日斜率 = LLT / LLT.shift(8)：>slope_up 即 8 日累计涨幅超阈值（上升趋势），
    # <slope_down 即累计跌幅超阈值（下降趋势），中间视为无方向。
    # 公式：s = LLT_t / LLT_{t−win}
    slope = l / l.shift(win)
    out = pd.Series(0.0, index=close.index)
    out.loc[slope > slope_up] = 1.0
    out.loc[slope < slope_down] = -1.0
    return out
