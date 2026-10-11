import pandas as pd
import pytest

from etf_rotation.evaluation import trades


def test_build_trade_table_derives_buys_and_sells():
    idx = pd.date_range("2024-01-01", periods=3)
    w = pd.DataFrame(
        {"A": [1.0, 0.5, 0.5], "B": [0.0, 0.5, 0.5]},
        index=idx,
    )
    nav = pd.Series([1.0, 1.0, 1.0], index=idx)
    t = trades.build_trade_table(w, nav)
    # 执行日：第 1 天买入 A(1.0)，第 2 天卖出 A(0.5)+买入 B(0.5)
    assert len(t) == 3
    assert set(t["ticker"]) == {"A", "B"}
    assert t.loc[(t["ticker"] == "A") & (t["side"] == "卖出"), "weight_change"].iloc[0] == pytest.approx(-0.5)


def test_build_trade_table_ignores_tiny_changes():
    idx = pd.date_range("2024-01-01", periods=4)
    w = pd.DataFrame({"A": [1.0, 1.0, 1.0 - 1e-8, 1.0 - 1e-8]}, index=idx)
    nav = pd.Series([1.0, 1.0, 1.0, 1.0], index=idx)
    t = trades.build_trade_table(w, nav, min_weight=1e-5)
    assert len(t) == 1

