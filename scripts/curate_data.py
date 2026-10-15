"""把 bronze parquet curation 进 warehouse（bars_daily / close_adj / trading_calendar / symbols）。"""
from __future__ import annotations

import duckdb
import pandas as pd

from etf_rotation.data import curate
from etf_rotation.data.paths import ADJ, BARS, SYMBOLS, WAREHOUSE


def _read(path):
    con = duckdb.connect()
    df = con.execute(f"SELECT * FROM read_parquet('{path.as_posix()}')").fetchdf()
    con.close()
    return df


def main(snapshot_id: str = "curated-1") -> None:
    bars = _read(BARS)
    adj = _read(ADJ)
    sym = _read(SYMBOLS)

    issues = curate.validate_ohlcv(bars)
    if any(issues.values()):
        print("WARNING data issues:", issues)

    sym_out = sym[["symbol_id", "ticker"]].copy()
    sym_out = sym_out.assign(
        exchange=sym_out["ticker"].str.split(".").str[-1],
        calendar="CN",
        currency="CNY",
    )

    m = bars.merge(adj, on=["symbol_id", "ts"], how="left")
    m = m[m["symbol_id"].isin(set(sym_out["symbol_id"]))]
    m["adj_factor"] = m.groupby("symbol_id")["adj_factor"].ffill().fillna(1.0)
    last = m.groupby("symbol_id")["adj_factor"].transform("last")
    m["close_adj"] = m["close"] * m["adj_factor"] / last
    m["amount"] = m["close"] * m["volume"] * 100

    now = pd.Timestamp.now()
    bars_out = m[["symbol_id", "ts", "open", "high", "low", "close", "volume"]].copy()
    bars_out = bars_out.assign(
        currency="CNY", close_utc=pd.NaT, available_utc=now, source="tushare",
        downloaded_at=now, snapshot_id=snapshot_id, amount=m["amount"],
    )
    close_out = m[["symbol_id", "ts", "close_adj", "adj_factor"]].copy()
    close_out = close_out.assign(
        method="fund_adj_forward", available_utc=now,
        source="tushare", snapshot_id=snapshot_id,
    )
    cal = curate.build_trading_calendar(bars)

    con = duckdb.connect(str(WAREHOUSE))
    con.register("sym_out", sym_out)
    con.register("bars_out", bars_out)
    con.register("close_out", close_out)
    con.register("cal", cal)
    # 先写 symbols（bars/close_adj 有外键引用）
    con.execute(
        "INSERT OR REPLACE INTO symbols (symbol_id, ticker, exchange, calendar, currency) "
        "SELECT symbol_id, ticker, exchange, calendar, currency FROM sym_out"
    )
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
