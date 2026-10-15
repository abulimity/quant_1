"""交易日历：优先 warehouse.trading_calendar，为空回退行情 ts 去重。"""
from __future__ import annotations

import duckdb
import pandas as pd

from etf_rotation.data.paths import BARS, WAREHOUSE


def _from_bars(start: str, end: str) -> pd.DatetimeIndex:
    """从行情 ts 去重得到交易日（warehouse 日历为空时的回退）。"""
    con = duckdb.connect()
    df = con.execute(
        f"SELECT DISTINCT ts FROM read_parquet('{BARS.as_posix()}') "
        f"WHERE ts BETWEEN '{start}' AND '{end}' ORDER BY ts"
    ).fetchdf()
    con.close()
    return pd.DatetimeIndex(df["ts"])


def trading_days(start: str, end: str) -> pd.DatetimeIndex:
    """交易日历：优先读 warehouse.trading_calendar，为空回退行情 ts 去重。"""
    con = duckdb.connect(str(WAREHOUSE))
    try:
        df = con.execute(
            "SELECT ts FROM trading_calendar WHERE is_open AND ts BETWEEN ? AND ? ORDER BY ts",
            [start, end],
        ).fetchdf()
    finally:
        con.close()
    if df.empty:
        return _from_bars(start, end)
    return pd.DatetimeIndex(df["ts"])


def shift_by_trading_days(dates: pd.Series, n: int) -> pd.Series:
    """把一组日期按交易日平移 n 天（跨周末/节假日按交易日计）。"""
    lo = str((dates.min() - pd.Timedelta(days=10)).date())
    hi = str((dates.max() + pd.Timedelta(days=abs(n) + 10)).date())
    cal = trading_days(lo, hi)
    pos = {d: i for i, d in enumerate(cal)}
    out = []
    for d in dates:
        key = d.normalize()
        j = pos.get(key)
        if j is None:
            out.append(pd.NaT)
            continue
        k = j + n
        out.append(cal[k] if 0 <= k < len(cal) else pd.NaT)
    return pd.Series(pd.to_datetime(out), index=dates.index)

