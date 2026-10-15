import pandas as pd

from etf_rotation.pipeline import _combine_phases


def test_combine_phases_means_snapshots():
    a = pd.Series({"X": 1.0, "Y": 0.0})
    b = pd.Series({"X": 0.5, "Y": 0.5})
    out = _combine_phases([a, b, a, b, a])
    pd.testing.assert_series_equal(out, pd.Series({"X": 0.8, "Y": 0.2}))
