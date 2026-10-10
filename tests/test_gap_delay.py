import pandas as pd

from etf_rotation.execution import gap_delay


def test_buy_delayed_on_gap_up():
    idx = pd.date_range("2024-01-01", periods=3)
    orders = pd.DataFrame([[0.0, 0.0], [0.0, 1.0], [0.0, 0.0]], index=idx, columns=["A", "B"])
    open_ = pd.DataFrame([[1.0, 1.0], [1.0, 1.02], [1.0, 1.0]], index=idx, columns=["A", "B"])
    close = pd.DataFrame([[1.0, 1.0], [1.0, 1.0], [1.0, 1.0]], index=idx, columns=["A", "B"])
    out = gap_delay.delay_orders(orders, open_, close, 0.01)
    assert out["B"].iloc[1] == 0.0
    assert out["B"].iloc[2] == 1.0

