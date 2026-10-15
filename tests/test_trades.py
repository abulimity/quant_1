import pandas as pd
import pytest

from etf_rotation.evaluation import trades


def test_build_trade_table_from_engine():
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2024-01-02"), "A"), (pd.Timestamp("2024-01-02"), "B")],
        names=["Date", "Security"],
    )
    tx = pd.DataFrame({"price": [10.0, 20.0], "quantity": [1.0, -0.5]}, index=idx)
    t = trades.build_trade_table_from_engine(tx, cost_bps=8)
    assert len(t) == 2
    assert t.loc[t["ticker"] == "A", "side"].iloc[0] == "买入"
    assert t.loc[t["ticker"] == "B", "cost"].iloc[0] == pytest.approx(20.0 * 0.5 * 8 / 10000)
    assert set(t.columns) >= {"date", "ticker", "side", "price", "quantity", "notional", "cost"}

