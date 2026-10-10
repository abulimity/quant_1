import numpy as np
import pandas as pd

from etf_rotation.portfolio import hrp


def test_hrp_weights_sum_to_one():
    rng = np.random.default_rng(1)
    ret = pd.DataFrame(rng.normal(0, 0.01, (300, 5)),
        columns=list("ABCDE"), index=pd.date_range("2023-01-01", periods=300))
    w = hrp.hrp_weights(ret)
    assert abs(w.sum() - 1) < 1e-6
    assert (w >= 0).all()

