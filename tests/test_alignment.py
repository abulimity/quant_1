import pandas as pd
import pytest

from etf_rotation import pipeline
from etf_rotation.evaluation.alignment import lag_correlation


def test_lag_correlation_peaks_at_zero_when_aligned():
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    b = pd.Series([0.01, -0.02, 0.03, 0.0, -0.01] * 12, index=idx)
    corr = lag_correlation(b * 0.8 + 0.001, b)
    assert corr.idxmax() == 0 and corr.loc[0] > 0.99


def test_lag_correlation_detects_one_day_lag():
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    b = pd.Series([0.01, -0.02, 0.03, 0.0, -0.01] * 12, index=idx)
    assert lag_correlation(b.shift(1).fillna(0.0), b).idxmax() == -1


def test_benchmark_uses_same_day_return(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=4, freq="B")
    hs = pd.Series([100.0, 110.0, 99.0, 108.9], index=idx)
    close = pd.DataFrame({"A": [10.0, 11.0, 9.9, 10.89]}, index=idx)
    amt = pd.DataFrame({"A": [1e8] * 4}, index=idx)
    fb = pd.DataFrame({"ts_code": ["A"]})
    monkeypatch.setattr(pipeline, "load_prices", lambda: (close, close, amt))
    monkeypatch.setattr(pipeline, "load_indices", lambda: {"000300.SH": hs})
    monkeypatch.setattr(pipeline, "load_fund_basic", lambda: fb)
    monkeypatch.setattr(pipeline.univ, "classify", lambda _: {"A": "risk"})
    monkeypatch.setattr(pipeline.calendar, "trading_days", lambda s, e: idx)
    out = pipeline.compute_benchmark(
        {"universe": {"min_listed_days": 0, "min_avg_amount20": 0}},
        "2024-01-01",
        "2024-01-04",
    )
    assert out["hs300"].pct_change().iloc[1] == pytest.approx(
        hs.pct_change().iloc[1]
    )


def test_benchmark_first_day_is_flat(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    hs = pd.Series([100.0, 110.0, 99.0], index=idx)
    close = pd.DataFrame({"A": [10.0, 11.0, 9.9]}, index=idx)
    amt = pd.DataFrame({"A": [1e8] * 3}, index=idx)
    monkeypatch.setattr(pipeline, "load_prices", lambda: (close, close, amt))
    monkeypatch.setattr(pipeline, "load_indices", lambda: {"000300.SH": hs})
    monkeypatch.setattr(
        pipeline, "load_fund_basic", lambda: pd.DataFrame({"ts_code": ["A"]})
    )
    monkeypatch.setattr(pipeline.univ, "classify", lambda _: {"A": "risk"})
    monkeypatch.setattr(pipeline.calendar, "trading_days", lambda s, e: idx)
    out = pipeline.compute_benchmark(
        {"universe": {"min_listed_days": 0, "min_avg_amount20": 0}},
        "2024-01-01",
        "2024-01-03",
    )
    assert out["hs300"].iloc[0] == pytest.approx(1.0)
    assert out["benchmark"].iloc[0] == pytest.approx(1.0)
