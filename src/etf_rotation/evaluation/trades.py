"""交易明细：以 bt 引擎 get_transactions() 为唯一依据。

纪律：交易明细不做二次推断（如不用「权重变化 × 价格」反推成交），
一律取引擎成交记录，保证与净值、费用、持仓三者对得上账。
"""
from __future__ import annotations

import pandas as pd


def build_trade_table_from_engine(
    transactions: pd.DataFrame, cost_bps: float = 8.0
) -> pd.DataFrame:
    """bt get_transactions()（MultiIndex: Date×Security, cols=[price,quantity]）→ 交易明细。

    成本按引擎佣金回调同一公式 notional × bps / 10000 计算，与净值记账对得上。

    公式：
      notional = p·|q|          —— 成交金额（p = 成交价，q = 成交股数，带符号）
      cost = notional·bps/1e4   —— 单边成本，与 backtest.run._flat_commission 一致
    side 由 q 的符号决定：q > 0 为买入，q < 0 为卖出。
    """
    tx = transactions.reset_index()
    tx.columns = ["date", "ticker", "price", "quantity"]
    tx["side"] = tx["quantity"].map(lambda q: "买入" if q > 0 else "卖出")
    # 不逐行舍入：cost 量级约 1e-4，round(6) 会把每笔量化到 1e-6，
    # 单笔相对误差可达 1e-3，累计后与引擎 fees 对不上账。
    # notional = p·|q|
    tx["notional"] = tx["price"] * tx["quantity"].abs()
    # cost = notional·bps/1e4
    tx["cost"] = tx["notional"] * cost_bps / 10000.0
    return tx[tx["quantity"].abs() > 0].reset_index(drop=True)[
        ["date", "ticker", "side", "price", "quantity", "notional", "cost"]
    ]
