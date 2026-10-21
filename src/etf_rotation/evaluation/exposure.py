"""集中度与暴露分析（ml4t-exposure-analysis）：HHI/有效持仓数/资产类暴露。

回答三个问题：
  ① 组合是不是押在少数标的上？（HHI / 有效持仓数）
  ② 组合实际暴露在哪些资产大类上？（各资产类权重之和）
  ③ 这些指标随时间怎么变？（逐日序列，用于事后归因）
"""
from __future__ import annotations

import pandas as pd


def hhi(weights: pd.Series) -> float:
    """Herfindahl-Hirschman 指数（权重平方和，0~1）。

    公式：HHI = Σw_i²（只对正权重求和；空仓时为 0.0）
    取值解读：
      HHI = 1/N  → N 只等权持仓（最分散）
      HHI → 1    → 单一标的（最集中）
    """
    w = weights[weights > 0]
    return float((w ** 2).sum()) if len(w) else 0.0


def effective_n(weights: pd.Series) -> float:
    """等效等权持仓数 = 1 / HHI。

    公式：N_eff = 1/HHI
    直观含义：当前集中度若换成等权组合，等效于持有多少只标的。
    例：3 只等权 → HHI = 1/3 → N_eff = 3；2 只各 70%/30% → HHI = 0.58 → N_eff ≈ 1.72。
    """
    h = hhi(weights)
    return 1.0 / h if h > 0 else 0.0


def asset_class_exposure(weights: pd.DataFrame, classification: dict) -> pd.DataFrame:
    """逐日资产类暴露（各资产类权重之和）。未分类标的归入 "risk"。

    公式：exposure_{c,t} = Σ_{i ∈ c} w_{i,t}（对每个资产类 c 逐日求和）
    """
    classes = sorted({classification.get(t, "risk") for t in weights.columns})
    out = pd.DataFrame(0.0, index=weights.index, columns=classes, dtype=float)
    for c in classes:
        cols = [t for t in weights.columns if classification.get(t, "risk") == c]
        if cols:
            out[c] = weights[cols].sum(axis=1)
    return out


def concentration_series(weights: pd.DataFrame) -> pd.DataFrame:
    """逐日 HHI 与有效持仓数（两列：hhi / effective_n）。"""
    h = weights.apply(hhi, axis=1)
    eff = pd.Series([effective_n(weights.loc[i]) for i in weights.index], index=weights.index)
    return pd.DataFrame({"hhi": h, "effective_n": eff})
