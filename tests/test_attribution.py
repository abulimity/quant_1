import pandas as pd

from etf_rotation.evaluation import attribution


def test_asset_class_contributions_sum_to_portfolio_return():
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    close = pd.DataFrame({
        "A": [10, 10.5, 11, 10.8, 11.2, 11.5, 11.3, 11.8, 12, 12.2],
        "B": [20, 19.5, 20, 20.5, 21, 20.8, 21.2, 21.5, 21.3, 21.8],
        "C": [30, 30.5, 31, 31.5, 31.2, 31.8, 32, 32.5, 33, 33.5],
    }, index=idx)
    weights = pd.DataFrame({"A": 0.4, "B": 0.3, "C": 0.3}, index=idx)
    classification = {"A": "risk", "B": "risk", "C": "defensive"}
    contrib = attribution.asset_class_contributions(weights, close, classification)
    eff = weights.shift(1).fillna(0.0)
    total = (eff * close.pct_change(fill_method=None)).sum(axis=1)
    assert set(contrib.columns) == {"risk", "defensive"}
    pd.testing.assert_series_equal(contrib.sum(axis=1), total, check_names=False,
                                   rtol=1e-12, atol=1e-12)
