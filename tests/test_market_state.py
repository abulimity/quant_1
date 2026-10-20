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


def test_composite_score_slope_thresholds_param():
    idx = pd.date_range("2023-01-01", periods=200)
    up = pd.Series(np.linspace(100, 120, 200), index=idx)
    down = pd.Series(np.linspace(100, 80, 200), index=idx)
    flat = pd.Series(100.0, index=idx)
    a = market_state.composite_score({"a": up, "b": down, "c": flat})
    b = market_state.composite_score({"a": up, "b": down, "c": flat},
                                     slope_up=1.005, slope_down=0.995)
    pd.testing.assert_series_equal(a, b)


def test_composite_score_slope_thresholds_wired():
    idx = pd.date_range("2023-01-01", periods=200)
    # 缓涨序列：8 日涨幅约 0.3%（斜率介于 1.001 与 1.005 之间，落在阈值夹缝）
    slow = pd.Series(100 * (1.003 ** (np.arange(200) / 8)), index=idx)
    flat = pd.Series(100.0, index=idx)
    strict = market_state.composite_score({"a": slow, "b": slow, "c": flat},
                                          slope_up=1.005, slope_down=0.995)
    loose = market_state.composite_score({"a": slow, "b": slow, "c": flat},
                                         slope_up=1.001, slope_down=0.999)
    assert not strict.equals(loose)

