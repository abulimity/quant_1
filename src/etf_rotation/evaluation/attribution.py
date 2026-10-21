"""收益归因：把组合收益拆到资产类别/区间（ml4t-exposure-analysis）。

归因的两条纪律：
  ① 时点对齐：用 T 日权重配 T+1 收益（权重 .shift(1)），与策略的 T 日信号 / T+1 成交一致
  ② 加总闭合：各资产类的贡献之和 = 组合日收益（不含现金利息）
"""
from __future__ import annotations

import pandas as pd


def asset_class_contributions(weights: pd.DataFrame, close: pd.DataFrame,
                              classification: dict) -> pd.DataFrame:
    """逐日把组合收益贡献拆到资产类别（T 日权重 × T+1 收益，无未来信息）。

    返回 DataFrame（index=交易日，columns=资产类别），各行之和 = 组合日收益
    （不含现金利息）。未在 classification 中的标的归入 "risk"。

    公式：
      contrib_{c,t} = Σ_{i∈c} w_{i,t−1}·r_{i,t}
      —— 权重取 t−1 日（.shift(1)，即 T 日收盘算出的持仓），
         收益取 t 日（.pct_change），两者相乘即该标的当日的收益贡献；
         再对同一资产类的所有标的求和。
    """
    ret = close.pct_change(fill_method=None)
    eff = weights.shift(1).fillna(0.0)     # T 日权重：向后对齐到 T+1 的收益
    contrib = eff * ret                     # 逐标的收益贡献
    classes = sorted({classification.get(t, "risk") for t in weights.columns})
    out = pd.DataFrame(0.0, index=weights.index, columns=classes, dtype=float)
    for c in classes:
        cols = [t for t in weights.columns if classification.get(t, "risk") == c]
        if cols:
            out[c] = contrib[cols].sum(axis=1)
    return out


def period_contributions(returns: pd.Series) -> pd.Series:
    """分年度累计收益（几何复合）。

    公式：R_y = Π(1+r) − 1（y = 年份）
    —— 用几何复合而非算术加总，与净值口径一致（算术平均会高估复利效应）。
    """
    r = returns.dropna()
    return r.groupby(r.index.year).apply(lambda s: (1 + s).prod() - 1)
