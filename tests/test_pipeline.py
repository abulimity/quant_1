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
