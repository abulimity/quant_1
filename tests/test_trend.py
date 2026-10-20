import numpy as np
import pandas as pd

from etf_rotation.signals import trend


def test_flat_series_zero_score():
    s = pd.Series(np.linspace(1, 1, 80), index=pd.date_range("2024-01-01", periods=80))
    m = trend.momentum_score(s, 21)
    assert abs(m.iloc[-1]) < 1e-9


def test_uptrend_positive_and_downtrend_negative():
    up = pd.Series(np.exp(np.linspace(0, 0.1, 40)), index=pd.date_range("2024-01-01", periods=40))
    down = pd.Series(np.exp(np.linspace(0.1, 0, 40)), index=pd.date_range("2024-01-01", periods=40))
    assert trend.momentum_score(up, 21).iloc[-1] > 0
    assert trend.momentum_score(down, 21).iloc[-1] < 0


def test_momentum_score_weighting_linear_is_default():
    idx = pd.date_range("2023-01-01", periods=80, freq="B")
    close = pd.Series(np.cumprod(1 + np.random.default_rng(0).normal(0, 0.01, len(idx))), index=idx)
    a = trend.momentum_score(close, 21)
    b = trend.momentum_score(close, 21, weighting="linear")
    np.testing.assert_allclose(a.dropna(), b.dropna(), rtol=1e-12)


def test_momentum_score_weighting_exp_differs():
    idx = pd.date_range("2023-01-01", periods=80, freq="B")
    close = pd.Series(np.cumprod(1 + np.random.default_rng(0).normal(0, 0.01, len(idx))), index=idx)
    a = trend.momentum_score(close, 21, weighting="linear")
    c = trend.momentum_score(close, 21, weighting="exp")
    assert not np.allclose(a.dropna(), c.dropna(), rtol=1e-6)

