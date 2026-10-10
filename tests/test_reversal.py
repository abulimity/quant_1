import numpy as np
import pandas as pd

from etf_rotation.signals import reversal


def test_zbias_centered():
    rng = np.random.default_rng(0)
    s = pd.Series(100 + np.cumsum(rng.normal(0, 0.1, 400)),
                  index=pd.date_range("2022-01-01", periods=400))
    z = reversal.zbias(s)
    assert abs(z.iloc[-200:].mean()) < 0.5

