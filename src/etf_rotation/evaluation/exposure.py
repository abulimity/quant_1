"""集中度与暴露分析（ml4t-exposure-analysis）：HHI/有效持仓数/资产类暴露。"""
from __future__ import annotations

import pandas as pd


def hhi(weights: pd.Series) -> float:
    """Herfindahl-Hirschman 指数（权重平方和，0~1）。"""
    w = weights[weights > 0]
    return float((w ** 2).sum()) if len(w) else 0.0


def effective_n(weights: pd.Series) -> float:
    """等效等权持仓数 = 1 / HHI。"""
    h = hhi(weights)
    return 1.0 / h if h > 0 else 0.0


def asset_class_exposure(weights: pd.DataFrame, classification: dict) -> pd.DataFrame:
    """逐日资产类暴露（各资产类权重之和）。未分类标的归入 "risk"。"""
    classes = sorted({classification.get(t, "risk") for t in weights.columns})
    out = pd.DataFrame(0.0, index=weights.index, columns=classes, dtype=float)
    for c in classes:
        cols = [t for t in weights.columns if classification.get(t, "risk") == c]
        if cols:
            out[c] = weights[cols].sum(axis=1)
    return out


def concentration_series(weights: pd.DataFrame) -> pd.DataFrame:
    """逐日 HHI 与有效持仓数。"""
    h = weights.apply(hhi, axis=1)
    eff = pd.Series([effective_n(weights.loc[i]) for i in weights.index], index=weights.index)
    return pd.DataFrame({"hhi": h, "effective_n": eff})
