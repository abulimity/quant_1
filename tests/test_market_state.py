import numpy as np
import pandas as pd

from etf_rotation.signals import market_state


def test_llt_lags_less_than_ema():
    t = pd.Series(np.arange(100.0), index=pd.date_range("2023-01-01", periods=100))
    l = market_state.llt(t, alpha=0.10)
    assert abs(l.iloc[-1] - t.iloc[-1]) < 0.5
    assert l.iloc[-1] > t.iloc[-1] - 20


def test_composite_score_bounds():
    idx = pd.date_range("2023-01-01", periods=200)
    up = pd.Series(np.linspace(100, 120, 200), index=idx)
    down = pd.Series(np.linspace(100, 80, 200), index=idx)
    flat = pd.Series(100.0, index=idx)
    score = market_state.composite_score({"a": up, "b": down, "c": flat})
    assert score.between(-1, 1).all()

