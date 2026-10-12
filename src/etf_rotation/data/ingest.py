"""tushare 数据拉取：指数日线 + ETF fund_basic（带重试）。"""
from __future__ import annotations

import time

import pandas as pd
import tushare as ts


def _pro(token: str):
    return ts.pro_api(token)


def fetch_index_daily(token: str, ts_code: str, start: str, end: str) -> pd.DataFrame:
    """拉取指数日线，重试 3 次，统一输出 ts_code/ts/close。"""
    pro = _pro(token)
    last_err = None
    for _ in range(3):
        try:
            df = pro.index_daily(
                ts_code=ts_code,
                start_date=start.replace("-", ""),
                end_date=end.replace("-", ""),
            )
            if df is None or df.empty:
                return pd.DataFrame(columns=["ts_code", "ts", "close"])
            df = df.sort_values("trade_date")
            df["ts"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
            return df[["ts_code", "ts", "close"]]
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.5)
    raise RuntimeError(f"tushare index_daily failed: {last_err}")


def fetch_fund_basic(token: str) -> pd.DataFrame:
    """拉取 ETF 基础信息（名称/类型/上市日期），用于分类与标的池。"""
    pro = _pro(token)
    fields = "ts_code,name,fund_type,invest_type,list_date,delist_date"
    df = pro.fund_basic(market="E", fields=fields)
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts_code", "name", "fund_type", "invest_type", "list_date", "delist_date"])
    df["list_date"] = pd.to_datetime(df["list_date"], format="%Y%m%d", errors="coerce")
    return df

