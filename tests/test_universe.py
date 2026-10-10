import pandas as pd

from etf_rotation.data import universe


def test_classify():
    fb = pd.DataFrame(
        {
            "ts_code": ["511880.SH", "511010.SH", "511380.SH", "518880.SH"],
            "name": ["银华日利", "国债ETF", "可转债ETF", "黄金ETF"],
            "invest_type": ["货币市场型", "债券型", "债券型", "商品型"],
        }
    )
    c = universe.classify(fb)
    assert c["511880.SH"] == "money"
    assert c["511380.SH"] == "convertible"
    assert c["518880.SH"] == "risk"


def test_build_pool_filters_liquidity():
    bars = pd.DataFrame(
        {
            "symbol_id": [1] * 3,
            "ts": pd.to_datetime(["2024-01-02"] * 3),
            "close": [1.0] * 3,
            "volume": [1000] * 3,
            "amount": [1e6] * 3,
        }
    )
    meta = pd.DataFrame(
        {
            "symbol_id": [1],
            "ticker": ["159999.SZ"],
            "listed_on": [pd.Timestamp("2023-01-01")],
            "category": ["risk"],
        }
    )
    pool = universe.build_pool(bars, meta, pd.Timestamp("2024-01-02"))
    assert len(pool) == 0

