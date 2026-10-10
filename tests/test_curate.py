import pandas as pd

from etf_rotation.data import curate


def _bars():
    return pd.DataFrame(
        {
            "symbol_id": [1, 1, 1],
            "ts": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "open": [1.0, 1.1, 1.2],
            "high": [1.2, 1.3, 1.4],
            "low": [0.9, 1.0, 1.1],
            "close": [1.0, 1.1, 1.2],
            "volume": [100, 100, 100],
        }
    )


def test_validate_flags_bad_ohlc():
    b = _bars()
    b.loc[1, "high"] = 0.5
    issues = curate.validate_ohlcv(b)
    assert issues["high_lt_low"] >= 1


def test_adjusted_close():
    b = _bars()
    adj = pd.DataFrame(
        {
            "symbol_id": [1, 1, 1],
            "ts": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
            "adj_factor": [2.0, 2.0, 1.0],
        }
    )
    out = curate.adjusted_close(b, adj)
    assert out.loc[out.ts == "2024-01-04", "close_adj"].iloc[0] == 1.2

