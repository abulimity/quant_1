"""收益归因：把组合收益拆到资产类别/区间（ml4t-exposure-analysis）。"""
from __future__ import annotations

import pandas as pd


def asset_class_contributions(weights: pd.DataFrame, close: pd.DataFrame,
                              classification: dict) -> pd.DataFrame:
    """逐日把组合收益贡献拆到资产类别（T 日权重 × T+1 收益，无未来信息）。

    返回 DataFrame（index=交易日，columns=资产类别），各行之和 = 组合日收益
    （不含现金利息）。未在 classification 中的标的归入 "risk"。
    """
    ret = close.pct_change(fill_method=None)
    eff = weights.shift(1).fillna(0.0)
    contrib = eff * ret
    classes = sorted({classification.get(t, "risk") for t in weights.columns})
    out = pd.DataFrame(0.0, index=weights.index, columns=classes, dtype=float)
    for c in classes:
        cols = [t for t in weights.columns if classification.get(t, "risk") == c]
        if cols:
            out[c] = contrib[cols].sum(axis=1)
    return out


def period_contributions(returns: pd.Series) -> pd.Series:
    """分年度累计收益（几何复合）。"""
    r = returns.dropna()
    return r.groupby(r.index.year).apply(lambda s: (1 + s).prod() - 1)
