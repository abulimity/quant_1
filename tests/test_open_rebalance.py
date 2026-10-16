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


def test_open_fill_differs_from_close_fill():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    w = pd.DataFrame({"X": [0.0, 1.0, 1.0]}, index=idx)
    opn = pd.DataFrame({"X": [10.0, 11.0, 10.0]}, index=idx)
    close = pd.DataFrame({"X": [10.0, 10.0, 10.0]}, index=idx)
    # 用极大跳空阈值禁用顺延，单独验证「开盘成交 + 收盘估值」：第 2 日以 11.0
    # 买入、收盘 10.0 估值，净值应 < 1（close 模式会在 10.0 成交，净值为 1）。
    # 需 3 根 bar：bt 的 RunDaily 跳过最后一根 bar，买单必须落在非末日才能成交。
    res = run.run(w, opn, close, cost_bps=0, cash_rate=0,
                  execution="open", gap_delay_pct=10.0)
    assert res.nav.iloc[-1] < 1.0
