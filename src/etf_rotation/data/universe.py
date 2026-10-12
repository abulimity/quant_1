"""标的池：ETF 分类（风险/债券/货币/可转债）+ point-in-time 可投资过滤。"""
from __future__ import annotations

import pandas as pd

CONVERTIBLE_KW = ["转债"]
MONEY_KW = ["货币", "现金", "理财", "保证金"]
BOND_KW = ["债", "国债", "国开", "政金", "短融", "存单", "信用"]


def classify(fund_basic: pd.DataFrame) -> pd.Series:
    """按名称关键词 + fund_type 大类划分 risk/bond/money/convertible。

    实测 tushare fund_basic：fund_type 为资产大类（股票型/债券型/货币型/REITs/其他），
    invest_type 为更细策略标签，故优先用 fund_type。该口径是对研报分类的近似（H8）。
    """
    type_col = "fund_type" if "fund_type" in fund_basic.columns else "invest_type"

    def _one(row):
        name = str(row["name"])
        ft = str(row.get(type_col, ""))
        if any(k in name for k in CONVERTIBLE_KW):
            return "convertible"
        if ft in ("货币型", "货币市场型") or any(k in name for k in MONEY_KW):
            return "money"
        if ft == "债券型" or any(k in name for k in BOND_KW):
            return "bond"
        return "risk"

    out = fund_basic.apply(_one, axis=1)
    out.index = fund_basic["ts_code"]
    return out.rename("category")


def build_pool(
    bars: pd.DataFrame,
    meta: pd.DataFrame,
    as_of: pd.Timestamp,
    min_days: int = 126,
    min_amount: float = 5_000_000,
) -> pd.DataFrame:
    """point-in-time 可投资池：截至 as_of 的上市天数 ≥ min_days 且 20 日均成交额 ≥ min_amount。"""
    if "amount" not in bars.columns:
        bars = bars.assign(amount=bars["close"] * bars["volume"] * 100)
    recent = bars[bars["ts"] <= as_of]
    agg = recent.groupby("symbol_id").agg(
        listed_days=("ts", "nunique"),
        avg_amount20=("amount", lambda s: s.tail(20).mean()),
    ).reset_index()
    pool = agg[(agg["listed_days"] >= min_days) & (agg["avg_amount20"] >= min_amount)]
    return pool.merge(meta, on="symbol_id", how="left")

