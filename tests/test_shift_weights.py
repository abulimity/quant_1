import pandas as pd

from etf_rotation.execution import shift_weights


def test_shift_weights_shifts_and_fills():
    idx = pd.date_range("2024-01-01", periods=3)
    w = pd.DataFrame({"A": [0.1, 0.2, 0.3]}, index=idx)
    out = shift_weights.shift_weights(w)
    assert out["A"].iloc[0] == 0.0
    assert out["A"].iloc[1] == 0.1
    assert out["A"].iloc[2] == 0.2
