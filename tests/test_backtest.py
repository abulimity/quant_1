import pandas as pd
import pytest

from etf_rotation.backtest import run
from etf_rotation.backtest.run import _flat_commission


def test_buy_and_hold_nav_matches_price():
    idx = pd.date_range("2024-01-01", periods=4)
    w = pd.DataFrame(1.0, index=idx, columns=["X"])
    close = pd.DataFrame([10, 11, 12, 13], index=idx, columns=["X"], dtype=float)
    open_ = close.shift(1).fillna(10.0)
    res = run.run(w, open_, close, cost_bps=0, cash_rate=0)
    assert abs(res.nav.iloc[-1] - 1.3) < 1e-9


def test_cash_interest_accrues():
    idx = pd.date_range("2024-01-01", periods=3)
    w = pd.DataFrame(0.0, index=idx, columns=["X"])
    close = pd.DataFrame([10.0, 10.0, 10.0], index=idx, columns=["X"])
    res = run.run(w, close, close, cost_bps=0, cash_rate=0.252)
    assert res.nav.iloc[-1] > 1.0
    assert res.nav.is_monotonic_increasing


def test_flat_commission_formula():
    fn = _flat_commission(8)
    assert fn(100, 2.0) == pytest.approx(100 * 2.0 * 8 / 10000.0)
    assert fn(-100, 2.0) == pytest.approx(100 * 2.0 * 8 / 10000.0)

