"""从权重面板推导交易明细（以「执行日」为基准）。"""
from __future__ import annotations

import pandas as pd


def build_trade_table(
    weights: pd.DataFrame,
    nav: pd.Series,
    min_weight: float = 1e-5,
    cost_bps: float = 8.0,
) -> pd.DataFrame:
    eff = weights.shift(1).fillna(0.0)  # T 日信号、T+1 生效
    delta = eff.diff()
    rows = []
    for t in range(1, len(delta)):
        day = delta.index[t]
        if day not in nav.index:
            continue
        nv = float(nav.loc[day])
        for ticker in delta.columns:
            dw = float(delta.iloc[t][ticker])
            if abs(dw) < min_weight:
                continue
            notional = abs(dw) * nv
            rows.append(
                {
                    "date": day,
                    "ticker": ticker,
                    "side": "买入" if dw > 0 else "卖出",
                    "weight_change": dw,
                    "notional": notional,
                    "cost": notional * cost_bps / 10000.0,
                }
            )
    return pd.DataFrame(
        rows, columns=["date", "ticker", "side", "weight_change", "notional", "cost"]
    )

