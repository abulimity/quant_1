import pandas as pd

import numpy as np

import etf_rotation.pipeline as pipe
from etf_rotation.pipeline import _combine_phases
from etf_rotation import config


def test_combine_phases_means_snapshots():
    a = pd.Series({"X": 1.0, "Y": 0.0})
    b = pd.Series({"X": 0.5, "Y": 0.5})
    out = _combine_phases([a, b, a, b, a])
    pd.testing.assert_series_equal(out, pd.Series({"X": 0.8, "Y": 0.2}))


def test_portfolio_vol_cap_only_shrinks():
    params = config.load_params()
    cand = pd.Series({"A": 0.5, "B": 0.3})
    rets_high = [0.05, -0.05, 0.06, -0.06] * 5
    out_high, scale_high = pipe._apply_portfolio_vol_cap(cand, rets_high, params)
    assert scale_high < 1.0 and (out_high <= cand).all()
    rets_low = [0.0001, -0.0001] * 5
    out_low, scale_low = pipe._apply_portfolio_vol_cap(cand, rets_low, params)
    assert scale_low == 1.0 and (out_low == cand).all()


def test_apply_overheat_removes_overheated():
    target = {"A": 0.3, "B": 0.2}
    close_d = pd.Series({"A": 12.0, "B": 10.0})
    llt80_d = pd.Series({"A": 10.0, "B": 10.0})
    out = pipe._apply_overheat(target, close_d, llt80_d, 0.2)
    assert "A" not in out and out["B"] == 0.2


def test_range_score_boosts_active_oversold():
    mom = pd.Series({"A": 0.5, "B": 0.5})
    zbias = pd.Series({"A": -1.0, "B": 0.0})
    active = pd.Series({"A": True, "B": False})
    score = pipe._range_score(mom, zbias, active)
    assert score["A"] > score["B"]


def test_range_score_no_active_falls_back_to_momentum_order():
    mom = pd.Series({"A": 0.9, "B": 0.1})
    zbias = pd.Series({"A": 0.0, "B": 0.0})
    active = pd.Series({"A": False, "B": False})
    score = pipe._range_score(mom, zbias, active)
    assert score["A"] > score["B"]


def test_hysteresis_holds_when_no_improvement():
    candidate = pd.Series({"B": 1.0})
    prev = pd.Series({"A": 1.0})
    score = pd.Series({"A": 0.80, "B": 0.81})
    out = pipe._apply_hysteresis(candidate, prev, score, ["A", "B"], 0.02)
    pd.testing.assert_series_equal(out, prev)


def test_hysteresis_switches_when_improves():
    candidate = pd.Series({"B": 1.0})
    prev = pd.Series({"A": 1.0})
    score = pd.Series({"A": 0.80, "B": 0.90})
    out = pipe._apply_hysteresis(candidate, prev, score, ["A", "B"], 0.02)
    pd.testing.assert_series_equal(out, candidate)


def _synthetic_panels():
    idx = pd.date_range("2023-01-01", periods=140, freq="B")
    a = np.linspace(1.0, 1.4, len(idx))
    b = np.linspace(1.0, 0.9, len(idx))
    close = pd.DataFrame({"513100.SH": a, "518880.SH": b}, index=idx)
    indices = {
        "000001.SH": pd.Series(np.linspace(3000, 3100, len(idx)), index=idx),
        "932000.CSI": pd.Series(np.linspace(2000, 2050, len(idx)), index=idx),
        "000922.CSI": pd.Series(np.linspace(5000, 5050, len(idx)), index=idx),
        "399006.SZ": pd.Series(np.linspace(1800, 1820, len(idx)), index=idx),
    }
    return close, indices


def test_precompute_signals_respects_trend_windows():
    close, indices = _synthetic_panels()
    params = config.load_params()
    params["nasdaq_etf"], params["gold_etf"] = "513100.SH", "518880.SH"
    params["trend"]["windows"] = [21, 63]
    sig = pipe._precompute_signals(
        close, close, close * 1e7, indices, params,
        {"513100.SH": "risk", "518880.SH": "gold"})
    m63 = pipe.momentum_panel(np.log(close), 63)
    pd.testing.assert_frame_equal(sig["m60"], m63)


def test_signal_cache_key_ignores_cost_and_dedupe():
    p1 = config.load_params()
    p2 = config.load_params()
    p2["costs"]["one_side_bps"] = 16
    p2["dedupe"]["corr_threshold"] = 0.85
    assert pipe.signal_cache_key(p1) == pipe.signal_cache_key(p2)


def test_signal_cache_key_changes_with_window():
    p1 = config.load_params()
    p2 = config.load_params()
    p2["trend"]["windows"] = [21, 63]
    assert pipe.signal_cache_key(p1) != pipe.signal_cache_key(p2)


def test_signal_cache_key_changes_with_bull_threshold():
    p1 = config.load_params()
    p2 = config.load_params()
    p2["market_state"]["bull_threshold"] = 0.30
    assert pipe.signal_cache_key(p1) != pipe.signal_cache_key(p2)


def test_signal_cache_key_changes_with_reversal():
    p1 = config.load_params()
    p2 = config.load_params()
    p2["reversal"]["zbias_threshold"] = -0.6
    assert pipe.signal_cache_key(p1) != pipe.signal_cache_key(p2)


def test_load_context_is_cached():
    assert pipe.load_context() is pipe.load_context()
