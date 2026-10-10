import pandas as pd

from etf_rotation.data import calendar


def test_trading_days_excludes_weekend():
    days = calendar.trading_days("2024-01-01", "2024-01-10")
    assert len(days) > 0
    assert all(d.dayofweek < 5 for d in days)


def test_shift_by_trading_days():
    days = pd.Series(pd.to_datetime(["2024-01-02"]))
    out = calendar.shift_by_trading_days(days, 1)
    assert out.iloc[0] == pd.Timestamp("2024-01-03")

