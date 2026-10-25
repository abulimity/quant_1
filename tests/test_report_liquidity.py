"""成交滑点与容量估算（N10 + N11）契约（计划 Task 16）。

口径：
- 滑点 `vs_close_bps = sign × (price / close − 1) × 1e4`，买入 sign=+1、
  卖出 sign=−1（正数表示对策略不利）；同时给 `vs_open_bps`；
- 成交方向优先取 `trades.side`，缺失时回退到 transactions.quantity 的符号；
- 容量 `value = weight × capital`（元），`adv20 = amount.rolling(20).mean()`，
  `days = value / adv20`；`amount` 单位为元，`capital` 单位为元；
- 容量只统计实际持仓（weight > 0），预热期 adv20 为 NaN 时整行剔除。
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from etf_rotation.report import serialize
from etf_rotation.report.context import ReportContext
from etf_rotation.report.steps import liquidity


def test_slippage_sign_is_side_adjusted():
    tx = pd.DataFrame({"Date": pd.to_datetime(["2024-01-02"]), "Security": ["A"],
                       "price": [10.1], "quantity": [100.0]})
    trades = pd.DataFrame({"date": pd.to_datetime(["2024-01-02"]), "ticker": ["A"],
                           "side": ["买入"]})
    close = pd.DataFrame({"A": [10.0]}, index=tx["Date"])
    opn = pd.DataFrame({"A": [10.0]}, index=tx["Date"])
    assert liquidity.slippage(tx, trades, close, opn).iloc[0]["vs_close_bps"] == pytest.approx(100.0)


def test_slippage_sell_sign_and_open_reference():
    tx = pd.DataFrame({"Date": pd.to_datetime(["2024-01-02"]), "Security": ["A"],
                       "price": [9.9], "quantity": [100.0]})
    trades = pd.DataFrame({"date": pd.to_datetime(["2024-01-02"]), "ticker": ["A"],
                           "side": ["卖出"]})
    close = pd.DataFrame({"A": [10.0]}, index=tx["Date"])
    opn = pd.DataFrame({"A": [10.2]}, index=tx["Date"])
    out = liquidity.slippage(tx, trades, close, opn).iloc[0]
    assert out["vs_close_bps"] == pytest.approx(100.0)
    assert out["vs_open_bps"] == pytest.approx(-1 * (9.9 / 10.2 - 1) * 1e4)


def test_slippage_columns_and_quantity_fallback():
    tx = pd.DataFrame({"Date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                       "Security": ["A", "B"], "price": [10.2, 9.8],
                       "quantity": [1.0, -1.0]})
    close = pd.DataFrame({"A": [10.0, np.nan], "B": [np.nan, 10.0]},
                         index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    opn = close.copy()
    out = liquidity.slippage(tx, None, close, opn)
    assert list(out.columns) == ["date", "ticker", "side", "price", "close", "opn",
                                 "vs_close_bps", "vs_open_bps"]
    # 买入 10.2 vs close 10.0 = +200bp；卖出 9.8 vs close 10.0 = +200bp
    assert out["vs_close_bps"].tolist() == pytest.approx([200.0, 200.0])


def test_capacity_uses_cny_amount():
    idx = pd.date_range("2024-01-01", periods=25, freq="B")
    weights = pd.DataFrame({"A": [1.0] * 25}, index=idx)
    amount = pd.DataFrame({"A": [1e8] * 25}, index=idx)
    assert liquidity.capacity(weights, amount, capital=1e8).iloc[-1]["days"] == pytest.approx(1.0)


def test_capacity_scales_with_capital_and_adv():
    idx = pd.date_range("2024-01-01", periods=20, freq="B")
    weights = pd.DataFrame({"A": [0.5] * 20}, index=idx)
    amount = pd.DataFrame({"A": [2e8] * 20}, index=idx)
    out = liquidity.capacity(weights, amount, capital=1e8)
    assert len(out) == 1                      # 预热 19 天无 adv20，剔除
    assert out.iloc[0]["weight"] == pytest.approx(0.5)
    assert out.iloc[0]["adv20"] == pytest.approx(2e8)
    assert out.iloc[0]["days"] == pytest.approx(0.25)


def test_capacity_skips_zero_weights():
    idx = pd.date_range("2024-01-01", periods=20, freq="B")
    weights = pd.DataFrame({"A": [0.0] * 20, "B": [1.0] * 20}, index=idx)
    amount = pd.DataFrame({"A": [1e8] * 20, "B": [1e8] * 20}, index=idx)
    out = liquidity.capacity(weights, amount)
    assert out["ticker"].tolist() == ["B"]


def _ctx():
    idx = pd.date_range("2024-01-01", periods=25, freq="B")
    weights = pd.DataFrame({"A": [1.0] * 25}, index=idx)
    amount = pd.DataFrame({"A": [1e8] * 25}, index=idx)
    close = pd.DataFrame({"A": [10.0] * 25}, index=idx)
    opn = pd.DataFrame({"A": [10.0] * 25}, index=idx)
    tx = pd.DataFrame({"Date": idx, "Security": "A", "price": [10.05] * 25,
                       "quantity": [1.0] * 25})
    trades = pd.DataFrame({"date": idx, "ticker": "A", "side": "买入"})
    return ReportContext(run_id="r1", meta={}, params={}, equity=None, benchmark=None,
                         weights=weights, holdings=None, trades=trades,
                         transactions=tx, diary=None, ticker_signals=None,
                         stages=None, classification={}, close=close, opn=opn,
                         amount=amount, metrics={})


def test_build_outputs_slippage_and_capacity_summaries():
    out = liquidity.build(_ctx())
    assert out["assumptions"]["capital"] == 1e8
    assert out["assumptions"]["adv_window"] == 20
    assert out["slippage"]["summary"]["median_vs_close_bps"] == pytest.approx(50.0)
    assert out["slippage"]["summary"]["median_vs_open_bps"] == pytest.approx(50.0)
    assert out["capacity"]["summary"]["max_days"] == pytest.approx(1.0)
    assert out["capacity"]["worst"][0]["ticker"] == "A"

    # 派生 JSON 必须过 allow_nan=False
    json.dumps(serialize.clean(out), allow_nan=False)


def test_build_requires_weights_and_amount():
    ctx = _ctx()
    ctx.weights = None
    with pytest.raises(RuntimeError):
        liquidity.build(ctx)


def test_build_tolerates_missing_transactions():
    ctx = _ctx()
    ctx.transactions = None
    ctx.trades = None
    out = liquidity.build(ctx)
    assert out["slippage"]["rows"] == []
    assert out["slippage"]["summary"]["n"] == 0
