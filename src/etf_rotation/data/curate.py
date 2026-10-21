"""数据校验与复权价重建（ml4t-validate-data 思路）。

数据层的两个职责：
  ① 校验：OHLC 一致性、缺失值、重复行——在进入策略之前把脏数据挡住
  ② 复权：把「原始价」转成「后复权价」，消除除权/拆分造成的虚假跳空
"""
from __future__ import annotations

import pandas as pd


def validate_ohlcv(bars: pd.DataFrame) -> dict:
    """OHLC 一致性、缺失收盘价、重复（symbol_id, ts）检查，返回各类问题计数。

    检查项与判据：
      high_lt_low     —— high < low：区间倒挂，说明行情源有脏数据
      close_outside_hl—— close 越出 [low, high]：收盘价不在当日区间内
      null_close      —— close 为空：无法估值，策略会跳过该点
      duplicates      —— (symbol_id, ts) 重复：join 后会放大行数，必须先去重
    """
    issues = {}
    issues["high_lt_low"] = int((bars["high"] < bars["low"]).sum())
    issues["close_outside_hl"] = int(
        ((bars["close"] > bars["high"]) | (bars["close"] < bars["low"])).sum()
    )
    issues["null_close"] = int(bars["close"].isna().sum())
    issues["duplicates"] = int(bars.duplicated(["symbol_id", "ts"]).sum())
    return issues


def adjusted_close(bars: pd.DataFrame, adj: pd.DataFrame) -> pd.DataFrame:
    """后复权收盘价 = close × adj_factor / 末日 adj_factor（以各标的最近一期为基准）。

    公式：close_adj = close × adj_factor / adj_factor_last
      —— adj_factor 为 tushare 的累计复权因子（分红送股后跳变）；
         除以该标的「最后一期」的因子，等价于把整条序列以最新一期为基准向前回溯调整，
         得到后复权序列（与研报 Wind 后复权口径的差异见 H9 假设）。
    停牌日的复权因子沿用上一有效值（ffill），再兜底为 1.0（视为未复权）。
    """
    m = bars.merge(adj, on=["symbol_id", "ts"], how="left")
    # 停牌日沿用上一有效复权因子；完全缺失则按 1.0（不调整）处理
    m["adj_factor"] = m["adj_factor"].ffill().fillna(1.0)
    # 每个标的最后一期的复权因子（后复权基准）
    last = m.groupby("symbol_id")["adj_factor"].transform("last")
    # close_adj = close × adj_factor / adj_factor_last
    m["close_adj"] = m["close"] * m["adj_factor"] / last
    return m[["symbol_id", "ts", "close_adj"]]


def build_trading_calendar(bars: pd.DataFrame) -> pd.DataFrame:
    """从行情 ts 去重得到 A 股交易日（exchange=SSE）。

    回退方案：warehouse.trading_calendar 为空时，用行情表出现过的日期近似交易日。
    该近似的局限是「有行情的日期」不一定等于「开市日」（例如某标的当日全无成交），
    故仅作为回退，正常路径应使用真实交易日历。
    """
    ts = pd.Series(pd.to_datetime(bars["ts"]).dt.date.unique())
    return pd.DataFrame({
        "exchange": "SSE",
        "ts": pd.to_datetime(ts.sort_values()),
        "is_open": True,
        "session_close_utc": pd.NaT,
        "source": "tushare",
    })
