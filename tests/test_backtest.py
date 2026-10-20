import numpy as np
import pandas as pd
import pytest

from etf_rotation.backtest import run
from etf_rotation.backtest.run import _flat_commission
from etf_rotation.evaluation import trades


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


def test_result_exposes_engine_cash_positions_fees():
    idx = pd.date_range("2024-01-01", periods=30)
    w = pd.DataFrame({"X": 0.5, "Y": 0.5}, index=idx)
    close = pd.DataFrame(
        {"X": pd.Series(10.0, index=idx) + pd.Series(range(30), index=idx) * 0.1,
         "Y": 20.0 - pd.Series(range(30), index=idx) * 0.05},
        index=idx,
    )
    res = run.run(w, close, close, cost_bps=8, cash_rate=0.018)
    assert res.cash.index.equals(close.index)
    assert res.positions.index.equals(close.index)
    assert res.fees.index.equals(close.index)
    assert set(res.positions.columns) == {"X", "Y"}
    assert res.fees.sum() > 0
    # 目标权重满仓（Σw=1）→ 现金记账为 0，佣金再从这条空现金线上扣，
    # 残差仅为浮点噪声（约 1e-10），不代表杠杆；用噪声级容差锁定「未放大仓位」。
    assert (res.cash >= -1e-9).all()
    assert res.cash.abs().max() < 1e-6


def test_nav_uses_result_prices():
    idx = pd.date_range("2024-01-01", periods=60)
    rng = np.random.default_rng(0)
    close = pd.DataFrame(
        {"A": np.cumprod(1 + rng.normal(0, 0.008, 60)),
         "B": np.cumprod(1 + rng.normal(0, 0.006, 60))},
        index=idx,
    )
    w = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    eff = w.shift(1).fillna(0.0)
    res = run.run(eff, close, close, cost_bps=8, cash_rate=0.018)
    official = res.result.prices["etf_rotation"].reindex(close.index)
    # 只锁数值等价：自算净值与官方 Result.prices 已一致到机器精度（约 2e-16），
    # 差异仅在 Series.name（自算为 "value"，官方为回测名），无下游消费者读取该 name。
    pd.testing.assert_series_equal(
        res.nav, official / official.iloc[0], rtol=1e-12, atol=1e-12, check_names=False
    )


def test_weigh_target_binds_by_name():
    idx = pd.date_range("2024-01-01", periods=5)
    w = pd.DataFrame(1.0, index=idx, columns=["X"])
    close = pd.DataFrame({"X": [10.0, 11.0, 12.0, 13.0, 14.0]}, index=idx)
    # 显式 close 口径：本测试锁定 WeighTarget 按名绑定的 close 成交净值（14/11），
    # open 默认会因 10% 日涨触发跳空顺延、成交后移，净值不同。
    res = run.run(w.shift(1).fillna(0.0), close, close, cost_bps=0, cash_rate=0,
                  execution="close")
    assert abs(res.nav.iloc[-1] - 14.0 / 11.0) < 1e-9


def test_trade_cost_reconciles_with_engine_fees():
    idx = pd.date_range("2024-01-01", periods=60)
    rng = np.random.default_rng(0)
    close = pd.DataFrame(
        {"A": np.cumprod(1 + rng.normal(0, 0.008, 60)),
         "B": np.cumprod(1 + rng.normal(0, 0.006, 60))},
        index=idx,
    )
    w = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    eff = w.shift(1).fillna(0.0)
    res = run.run(eff, close, close, cost_bps=8, cash_rate=0.018)
    t = trades.build_trade_table_from_engine(res.result.get_transactions(), cost_bps=8)
    assert t["cost"].sum() == pytest.approx(res.fees.sum(), abs=1e-9)


def test_run_defaults_to_open_execution():
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    w = pd.DataFrame({"A": [0.0, 0.5, 0.5, 0.0, 0.0]}, index=idx)
    close = pd.DataFrame({"A": [10.0, 10.5, 11.0, 10.8, 10.9]}, index=idx)
    opn = pd.DataFrame({"A": [10.0, 10.0, 10.6, 10.4, 10.5]}, index=idx)
    r_def = run.run(w, opn, close, cost_bps=0, cash_rate=0)
    r_open = run.run(w, opn, close, cost_bps=0, cash_rate=0, execution="open")
    r_close = run.run(w, opn, close, cost_bps=0, cash_rate=0, execution="close")
    pd.testing.assert_series_equal(r_def.nav, r_open.nav)
    assert not r_def.nav.equals(r_close.nav)

