"""交易明细：以 bt 引擎 get_transactions() 为唯一依据。"""
from __future__ import annotations

import pandas as pd


def build_trade_table_from_engine(
    transactions: pd.DataFrame, cost_bps: float = 8.0
) -> pd.DataFrame:
    """bt get_transactions()（MultiIndex: Date×Security, cols=[price,quantity]）→ 交易明细。

    成本按引擎佣金回调同一公式 notional × bps / 10000 计算，与净值记账对得上。
    """
    tx = transactions.reset_index()
    tx.columns = ["date", "ticker", "price", "quantity"]
    tx["side"] = tx["quantity"].map(lambda q: "买入" if q > 0 else "卖出")
    tx["notional"] = (tx["price"] * tx["quantity"].abs()).round(6)
    tx["cost"] = (tx["notional"] * cost_bps / 10000.0).round(6)
    return tx[tx["quantity"].abs() > 0].reset_index(drop=True)[
        ["date", "ticker", "side", "price", "quantity", "notional", "cost"]
    ]

