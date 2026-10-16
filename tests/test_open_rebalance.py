import numpy as np
import pandas as pd

from etf_rotation.backtest import run


def test_open_rebalance_matches_close_when_open_equals_close():
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    rng = np.random.default_rng(0)
    close = pd.DataFrame({
        "A": np.cumprod(1 + rng.normal(0, 0.008, len(idx))),
        "B": np.cumprod(1 + rng.normal(0, 0.006, len(idx))),
    }, index=idx)
    w = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    eff = w.shift(1).fillna(0.0)
    base = run.run(eff, close, close, cost_bps=8, cash_rate=0.018, execution="close")
    opn = run.run(eff, close, close, cost_bps=8, cash_rate=0.018, execution="open")
    pd.testing.assert_series_equal(base.nav, opn.nav, rtol=1e-9, atol=1e-9)
    assert abs(base.fees.sum() - opn.fees.sum()) < 1e-9
