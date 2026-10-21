"""趋势得分：时间加权线性回归的斜率与 R² 合成（研报 Momentum 公式）。

本模块是「选股信号」的核心：把一段时间的对数价序列压成一个可比的分值。

两段式结构：
  ① 拟合：对最近 window 期的对数价做时间加权最小二乘，得到斜率 β 与拟合优度 R²
  ② 映射：Momentum = (exp(ann·β) − 1)·R²
     —— β 是「每期对数收益」（近似百分比收益），exp(ann·β) 把日频斜率年化成
        累计涨幅；R² 是拟合优度，用来给「趋势不干净」的标的打折。

为什么用对数价：log 价格的线性斜率可直接解释为复合增长率，且对价格绝对水平
不敏感，跨标的可比性好（R² 同理是尺度无关量）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _time_weights(window: int, weighting: str = "linear") -> np.ndarray:
    """H1 时间权重（越近权重越大，归一化）。

    - linear：线性递增权重（默认，研报原假设 H1）。
    - exp：指数衰减权重（H1 敏感性候选），w ∝ exp(0.05·(t−window))。

    归一化：Σw=1（权重和为 1），保证后续加权回归的截距项就是加权均值，
    且不同 window 下权重尺度可比。
    """
    x = np.arange(1, window + 1, dtype=float)      # 位置：1 = 最老，window = 最新
    if weighting == "linear":
        w = x                                       # 线性递增：越新权重越大
    elif weighting == "exp":
        w = np.exp(0.05 * (x - window))             # 指数衰减：衰减率 0.05/期
    else:
        raise ValueError(f"unknown weighting: {weighting!r} (expected 'linear' or 'exp')")
    return w / w.sum()                              # 归一化：Σw=1


def momentum_panel(logp: pd.DataFrame, window: int, ann: int = 250,
                   weighting: str = "linear") -> pd.DataFrame:
    """向量化的时间加权回归趋势分面板（列 = ticker，与 momentum_score 同公式）。

    对每个标的的对数价序列，用最近 window 期做时间加权最小二乘：Slope 是回归斜率
    （ann 日年化后经 exp 映射为动量），R² 是拟合优度折扣因子；最终
    Momentum = (exp(ann·Slope) − 1) · R²。滑动窗口视图一次算完全列，按 chunk 分批控制内存。

    ── 完整公式（对每个标的、在每个滚动窗口上）────────────────────
      记窗口内对数价为 y_1..y_n（y_n 最新），时间位置 x_i = i（1..n），权重 w_i。

      ① 加权均值（因 Σw=1，加权均值即加权平均）
         x̄_w = Σ w_i·x_i
         ȳ_w = Σ w_i·y_i
      ② 回归斜率（加权最小二乘的一阶条件）
         β = Σ w_i·(x_i − x̄_w)·(y_i − ȳ_w) / Σ w_i·(x_i − x̄_w)²
         代码中分母记为 denom，分子由 w·(x − x̄_w) 与 y 的张量收缩得到
      ③ 拟合值与残差平方和
         ŷ_i = β·x_i + (ȳ_w − β·x̄_w)
         SS_res = Σ w_i·(y_i − ŷ_i)²
      ④ 总平方和与拟合优度
         SS_tot = Σ w_i·(y_i − ȳ_w)²
         R² = 1 − SS_res/SS_tot（SS_tot = 0 时取 0，避免 0/0）
      ⑤ 最终动量分
         Momentum = (exp(ann·β) − 1)·R²，ann=250（年化交易日数）

    向量化说明：步骤 ②–⑤ 对所有标的、所有滚动窗口一次性算完
    （sliding_window_view + tensordot），按 chunk=128 列分批以控制内存峰值。
    """
    x = np.arange(1, window + 1, dtype=float)
    w = _time_weights(window, weighting)
    # 加权位置均值 x̄_w = Σ w_i·x_i（因 Σw=1，它同时是回归截距的构成项）
    xw = (w * x).sum()
    # denom = Σ w_i·(x_i − x̄_w)²：斜率公式的分母，与标的价格无关，全列共用
    denom = (w * (x - xw) ** 2).sum()
    arr = logp.to_numpy()
    n, m = arr.shape
    out = np.full((n, m), np.nan)
    chunk = 128   # 每次处理 128 列，避免一次性展开全部滑动窗口导致内存峰值过高
    for c in range(0, m, chunk):
        sub = arr[:, c : c + chunk]
        # y 的最后一维是窗口内的 window 期（滑窗视图，不复制数据）
        y = np.lib.stride_tricks.sliding_window_view(sub, window, axis=0)
        # ȳ_w = Σ w_i·y_i（加权价格均值，即拟合直线的加权截距基准）
        yw = np.tensordot(y, w, axes=([2], [0]))
        # β = Σ w_i·(x_i − x̄_w)·(y_i − ȳ_w) / denom
        slope = np.tensordot(y, w * (x - xw), axes=([2], [0])) / denom
        # ŷ_i = β·x_i + (ȳ_w − β·x̄_w)
        yhat = slope[..., None] * x + (yw - slope * xw)[..., None]
        # SS_res = Σ w_i·(y_i − ŷ_i)²
        ss_res = np.tensordot((y - yhat) ** 2, w, axes=([2], [0]))
        # SS_tot = Σ w_i·(y_i − ȳ_w)²
        ss_tot = np.tensordot((y - yw[..., None]) ** 2, w, axes=([2], [0]))
        # R² = 1 − SS_res/SS_tot（SS_tot = 0 时置 0，防止除零产生 NaN）
        r2 = 1 - ss_res / np.where(ss_tot > 0, ss_tot, 1.0)
        r2 = np.where(ss_tot > 0, r2, 0.0)
        # Momentum = (exp(ann·β) − 1)·R²：年化斜率映射为累计涨幅，再乘拟合优度
        mom = (np.exp(ann * slope) - 1) * r2
        # 前 window−1 个点没有完整窗口，保持 NaN（下游据此判定不可用）
        out[window - 1 :, c : c + chunk] = mom
    return pd.DataFrame(out, index=logp.index, columns=logp.columns)


def momentum_score(close: pd.Series, window: int, ann: int = 250,
                   weighting: str = "linear") -> pd.Series:
    """Momentum(w) = [exp(ann·Slope(w)) − 1] · R²(w)，单序列薄封装（momentum_panel 单列）。

    公式与 momentum_panel 完全一致，只是把单只标的的价格序列包成单列 DataFrame
    走同一条向量化路径，避免两套实现产生口径漂移。
    """
    return momentum_panel(np.log(close).to_frame(), window, ann, weighting).iloc[:, 0]
