import pandas as pd

from etf_rotation.execution import phases


def test_combine_averages_staggered():
    idx = pd.date_range("2024-01-01", periods=10)
    a = pd.DataFrame(1.0, index=idx, columns=["X"])
    b = pd.DataFrame(0.0, index=idx, columns=["X"])
    out = phases.combine([a, b], [0, 1])
    assert out["X"].iloc[0] == 0.5

