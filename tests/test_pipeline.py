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
