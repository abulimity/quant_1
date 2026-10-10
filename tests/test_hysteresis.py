import pandas as pd

from etf_rotation.execution import hysteresis


def test_hysteresis_keeps_old_when_no_improvement():
    old = pd.Series({"A": 1.0})
    new = pd.Series({"B": 1.0})
    out = hysteresis.apply(old, new, score_old=0.8, score_new=0.8, min_improve=0.02)
    assert out.equals(old)

