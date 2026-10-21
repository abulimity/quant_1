"""交易日历：优先 warehouse.trading_calendar，为空回退行情 ts 去重。

日历是整个「T 日信号 / T+1 成交」时点纪律的基础：
所有平移（信号顺延、执行延迟、OOS 切分）都必须按交易日算，不能按自然日算，
否则周末与节假日会让 T+1 落到非交易日上。
"""
from __future__ import annotations

import duckdb
import pandas as pd

from etf_rotation.data.paths import BARS, WAREHOUSE


def _from_bars(start: str, end: str) -> pd.DatetimeIndex:
    """从行情 ts 去重得到交易日（warehouse 日历为空时的回退）。

    注意：这是「有行情的日期」而非严格的开市日，属近似口径，仅作回退使用。
    """
    con = duckdb.connect()
    df = con.execute(
        f"SELECT DISTINCT ts FROM read_parquet('{BARS.as_posix()}') "
        f"WHERE ts BETWEEN '{start}' AND '{end}' ORDER BY ts"
    ).fetchdf()
    con.close()
    return pd.DatetimeIndex(df["ts"])


def trading_days(start: str, end: str) -> pd.DatetimeIndex:
    """交易日历：优先读 warehouse.trading_calendar，为空回退行情 ts 去重。

    主路径：查 trading_calendar 表的 is_open = TRUE 记录，按 ts 升序返回 [start, end] 区间内的开市日。
    回退路径：warehouse 尚未 curate（或日历表为空）时用行情 ts 去重近似。
    """
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
    """把一组日期按交易日平移 n 天（跨周末/节假日按交易日计）。

    做法：在 [min−10日, max+|n|+10日] 的窗口上取交易日历 cal，
    建立「日期 → 序号」映射 pos，然后按下标平移：
        j = pos.get(d)        —— 原日期在日历中的位置（不在日历中则 NaT）
        k = j + n             —— 平移后的位置
        结果 = cal[k]（越界则 NaT）
    这样跨周末/长假也是按「交易日个数」而不是自然日推进。
    """
    lo = str((dates.min() - pd.Timedelta(days=10)).date())
    hi = str((dates.max() + pd.Timedelta(days=abs(n) + 10)).date())
    cal = trading_days(lo, hi)                 # 交易日历窗口
    pos = {d: i for i, d in enumerate(cal)}    # 日期 → 交易日序号
    out = []
    for d in dates:
        key = d.normalize()
        j = pos.get(key)                       # 原日期的日历位置
        if j is None:
            out.append(pd.NaT)                 # 该日不在日历中（非交易日）
            continue
        k = j + n
        out.append(cal[k] if 0 <= k < len(cal) else pd.NaT)   # 越界则 NaT
    return pd.Series(pd.to_datetime(out), index=dates.index)
