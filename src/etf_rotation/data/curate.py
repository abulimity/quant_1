"""数据校验与复权价重建（ml4t-validate-data 思路）。"""
from __future__ import annotations

import pandas as pd


def validate_ohlcv(bars: pd.DataFrame) -> dict:
    """OHLC 一致性、缺失收盘价、重复（symbol_id, ts）检查，返回各类问题计数。"""
    issues = {}
    issues["high_lt_low"] = int((bars["high"] < bars["low"]).sum())
    issues["close_outside_hl"] = int(
        ((bars["close"] > bars["high"]) | (bars["close"] < bars["low"])).sum()
    )
    issues["null_close"] = int(bars["close"].isna().sum())
    issues["duplicates"] = int(bars.duplicated(["symbol_id", "ts"]).sum())
    return issues


def adjusted_close(bars: pd.DataFrame, adj: pd.DataFrame) -> pd.DataFrame:
    """后复权收盘价 = close × adj_factor / 末日 adj_factor（以各标的最近一期为基准）。"""
    m = bars.merge(adj, on=["symbol_id", "ts"], how="left")
    m["adj_factor"] = m["adj_factor"].ffill().fillna(1.0)
    last = m.groupby("symbol_id")["adj_factor"].transform("last")
    m["close_adj"] = m["close"] * m["adj_factor"] / last
    return m[["symbol_id", "ts", "close_adj"]]

