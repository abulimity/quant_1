import pandas as pd
import duckdb

from etf_rotation.data import calendar


def test_trading_days_excludes_weekend():
    days = calendar.trading_days("2024-01-01", "2024-01-10")
    assert len(days) > 0
    assert all(d.dayofweek < 5 for d in days)


def test_shift_by_trading_days():
    days = pd.Series(pd.to_datetime(["2024-01-02"]))
    out = calendar.shift_by_trading_days(days, 1)
    assert out.iloc[0] == pd.Timestamp("2024-01-03")


def test_trading_days_falls_back_when_warehouse_calendar_empty(tmp_path, monkeypatch):
    db = tmp_path / "w.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE trading_calendar (exchange VARCHAR, ts DATE, is_open BOOLEAN, "
        "session_close_utc TIMESTAMP, source VARCHAR, PRIMARY KEY (exchange, ts))"
    )
    con.close()
    monkeypatch.setattr(calendar, "WAREHOUSE", db)
    days = calendar.trading_days("2024-01-02", "2024-01-05")
    assert isinstance(days, pd.DatetimeIndex)
    assert len(days) >= 1

