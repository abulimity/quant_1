"""tushare 数据拉取：指数日线 + ETF fund_basic（带重试）。

只负责「取数」，不做任何清洗与复权（那是 data/curate.py 的职责）。
所有接口都只接受 token 参数，不在模块内读环境变量——token 由 config.load_token
从 .env 注入，模块内不打印、不落盘（.env 的 token 不得出现在日志里）。
"""
from __future__ import annotations

import time

import pandas as pd
import tushare as ts


def _pro(token: str):
    """构造 tushare pro 客户端（token 由调用方从 .env 注入，不在此处读取或打印）。"""
    return ts.pro_api(token)


def fetch_index_daily(token: str, ts_code: str, start: str, end: str) -> pd.DataFrame:
    """拉取指数日线，重试 3 次，统一输出 ts_code/ts/close。

    tushare 的日期参数格式为 YYYYMMDD，故先去掉短横线。
    重试策略：最多 3 次，每次失败后 sleep 1.5 秒（tushare 有调用频率限制）。
    空结果返回带列名的空 DataFrame（保证下游列结构一致）。
    """
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
    """拉取 ETF 基础信息（名称/类型/上市日期），用于分类与标的池。

    market="E" 表示场内（ETF）；只取分类与 point-in-time 资格所需字段。
    list_date 转为 datetime（errors="coerce"：脏日期置 NaT 而不中断拉取）。
    """
    pro = _pro(token)
    fields = "ts_code,name,fund_type,invest_type,list_date,delist_date"
    df = pro.fund_basic(market="E", fields=fields)
    if df is None or df.empty:
        return pd.DataFrame(columns=["ts_code", "name", "fund_type", "invest_type", "list_date", "delist_date"])
    df["list_date"] = pd.to_datetime(df["list_date"], format="%Y%m%d", errors="coerce")
    return df
