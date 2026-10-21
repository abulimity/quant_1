"""把 bronze parquet curation 进 warehouse（bars_daily / close_adj / trading_calendar / symbols）。"""
from __future__ import annotations

import duckdb
import pandas as pd

from etf_rotation.data import curate
from etf_rotation.data.paths import ADJ, BARS, SYMBOLS, WAREHOUSE


def _read(path):
    """用 duckdb 读单个 bronze parquet（比 pandas 更快、省内存）。"""
    con = duckdb.connect()
    df = con.execute(f"SELECT * FROM read_parquet('{path.as_posix()}')").fetchdf()
    con.close()
    return df


def main(snapshot_id: str = "curated-1") -> None:
    """把 bronze parquet 清洗/复权后写入 warehouse 的 bars_daily / close_adj / 日历 / 标的表。

    snapshot_id 用于标记数据版本；同一 snapshot 重复写入会先删旧行再插入，保证可重复运行。
    """
    bars = _read(BARS)
    adj = _read(ADJ)
    sym = _read(SYMBOLS)

    issues = curate.validate_ohlcv(bars)  # 先做数据质量检查，发现问题只告警不中断
    if any(issues.values()):
        print("WARNING data issues:", issues)

    sym_out = sym[["symbol_id", "ticker"]].copy()
    # symbols 表最小字段：由 ticker 后缀推导交易所，统一使用 CN 日历与 CNY 计价
    sym_out = sym_out.assign(
        exchange=sym_out["ticker"].str.split(".").str[-1],
        calendar="CN",
        currency="CNY",
    )

    # 左连接复权因子（停牌日无因子 → 沿用上一有效值 → 兜底 1.0）
    m = bars.merge(adj, on=["symbol_id", "ts"], how="left")
    # 只保留在标的表里的 symbol_id（剔除孤儿行情行）
    m = m[m["symbol_id"].isin(set(sym_out["symbol_id"]))]
    m["adj_factor"] = m.groupby("symbol_id")["adj_factor"].ffill().fillna(1.0)
    # 后复权基准：每个标的最后一期的复权因子
    last = m.groupby("symbol_id")["adj_factor"].transform("last")
    # close_adj = close × adj_factor / adj_factor_last
    m["close_adj"] = m["close"] * m["adj_factor"] / last
    # 成交额 = 收盘价 × 成交量 × 100（volume 单位：手，1 手 = 100 股）
    m["amount"] = m["close"] * m["volume"] * 100  # 成交额 = 收盘价 × 成交量 × 100（volume 单位：手）

    now = pd.Timestamp.now()
    # bars_daily：原始行情 + 元信息（币种、可用时间、快照号）
    bars_out = m[["symbol_id", "ts", "open", "high", "low", "close", "volume"]].copy()
    bars_out = bars_out.assign(
        currency="CNY", close_utc=pd.NaT, available_utc=now, source="tushare",
        downloaded_at=now, snapshot_id=snapshot_id, amount=m["amount"],
    )
    # close_adj：后复权价表（复权方法标记为 fund_adj_forward）
    close_out = m[["symbol_id", "ts", "close_adj", "adj_factor"]].copy()
    close_out = close_out.assign(
        method="fund_adj_forward", available_utc=now,
        source="tushare", snapshot_id=snapshot_id,
    )
    # 交易日历（优先用 warehouse 已有日历，回退到行情 ts 去重）
    cal = curate.build_trading_calendar(bars)

    # 写库：先注册 pandas 对象为 duckdb 视图，再执行 SQL
    con = duckdb.connect(str(WAREHOUSE))
    con.register("sym_out", sym_out)
    con.register("bars_out", bars_out)
    con.register("close_out", close_out)
    con.register("cal", cal)
    # 先写 symbols（bars/close_adj 有外键引用）；同 snapshot 先删旧行再插入，保证可重复运行
    con.execute(
        "INSERT OR REPLACE INTO symbols (symbol_id, ticker, exchange, calendar, currency) "
        "SELECT symbol_id, ticker, exchange, calendar, currency FROM sym_out"
    )
    # 幂等重跑：同一 snapshot_id 的旧行先删再插，不会出现重复行
    con.execute("DELETE FROM bars_daily WHERE snapshot_id = ?", [snapshot_id])
    con.execute("DELETE FROM close_adj WHERE snapshot_id = ?", [snapshot_id])
    con.execute("INSERT INTO bars_daily SELECT * FROM bars_out")
    con.execute("INSERT INTO close_adj SELECT * FROM close_out")
    con.execute("INSERT OR REPLACE INTO trading_calendar SELECT * FROM cal")
    con.close()
    print(
        f"curated {len(bars_out)} bars; {len(close_out)} close_adj; "
        f"{len(cal)} calendar days; {len(sym_out)} symbols"
    )


if __name__ == "__main__":
    main()
