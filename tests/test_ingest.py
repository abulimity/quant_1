import pandas as pd

from etf_rotation.data import ingest


def test_fetch_index_daily_renames(monkeypatch):
    class FakePro:
        def index_daily(self, **kw):
            return pd.DataFrame(
                {
                    "ts_code": ["932000.CSI"] * 2,
                    "trade_date": ["20240102", "20240103"],
                    "close": [100, 101],
                }
            )

    monkeypatch.setattr(ingest.ts, "pro_api", lambda token: FakePro())
    df = ingest.fetch_index_daily("tok", "932000.CSI", "2024-01-01", "2024-01-03")
    assert list(df.columns) == ["ts_code", "ts", "close"]

