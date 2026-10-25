"""单笔往返配对（N7）契约（计划 Task 13）。

口径：
- 买入按 (date, price, qty, cost) 入队；卖出按 FIFO 跨批次消耗，
  分数份额也按同比例摊成本；
- `pnl = qty × (sell − buy) − (买入分摊成本 + 卖出分摊成本)`；
- `holding_days = (exit_date − entry_date).days`（日历日）；
- `entry_status` 查 `ticker_signals.status`（查不到 None）；
- `exit_reason`：出场日 status 为 `overheat_exit` → `overheat`，有记录 → `switch`，
  查不到 → `other`；
- 未平仓批次不进往返表，只在 `summary.open_lots/open_cost` 里统计。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etf_rotation.report.context import ReportContext
from etf_rotation.report.steps import roundtrips

COLUMNS = ["ticker", "entry_date", "exit_date", "quantity", "entry_price",
           "exit_price", "pnl", "holding_days", "entry_status", "exit_reason"]


def _trades(rows):
    return pd.DataFrame(rows, columns=["date", "ticker", "side", "price",
                                       "quantity", "notional", "cost"])


def test_fifo_sell_consumes_multiple_lots():
    trades = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-05", "2024-01-10"]),
        "ticker": ["A"] * 3, "side": ["买入", "买入", "卖出"],
        "price": [10.0, 12.0, 11.0], "quantity": [1.0, 1.0, 1.5],
        "notional": [10.0, 12.0, 16.5], "cost": [0.001, 0.001, 0.0]})
    out = roundtrips.match_round_trips(trades, signals=None)
    assert len(out) == 2
    assert out.iloc[0]["quantity"] == pytest.approx(1.0)
    assert out.iloc[1]["quantity"] == pytest.approx(0.5)
    assert out.iloc[0]["pnl"] == pytest.approx(1.0 - 0.001, abs=1e-9)
    assert out.iloc[1]["pnl"] == pytest.approx(-0.5 - 0.0005, abs=1e-9)
    assert out.iloc[0]["holding_days"] == 9


def test_fractional_shares_allocate_cost_proportionally():
    trades = _trades([
        ("2024-01-01", "A", "买入", 10.0, 0.5, 5.0, 0.0005),
        ("2024-01-02", "A", "买入", 12.0, 0.25, 3.0, 0.00025),
        ("2024-01-05", "A", "卖出", 11.0, 0.6, 6.6, 0.0),
    ])
    out = roundtrips.match_round_trips(trades)
    assert out["quantity"].tolist() == pytest.approx([0.5, 0.1])
    assert out.iloc[0]["pnl"] == pytest.approx(0.5 * 1.0 - 0.0005, abs=1e-12)
    assert out.iloc[1]["pnl"] == pytest.approx(0.1 * -1.0 - 0.0001, abs=1e-12)


def test_partial_lot_keeps_remainder_for_next_sell():
    trades = _trades([
        ("2024-01-01", "A", "买入", 10.0, 2.0, 20.0, 0.0),
        ("2024-01-02", "A", "卖出", 11.0, 0.5, 5.5, 0.0),
        ("2024-01-03", "A", "卖出", 12.0, 1.0, 12.0, 0.0),
        ("2024-01-04", "A", "卖出", 13.0, 0.7, 9.1, 0.0),   # 只剩 0.5，不产生负持仓
    ])
    out = roundtrips.match_round_trips(trades)
    assert out["quantity"].tolist() == pytest.approx([0.5, 1.0, 0.5])
    assert out["pnl"].tolist() == pytest.approx([0.5, 2.0, 1.5])
    assert out.iloc[2]["holding_days"] == 3


def _signals(rows):
    df = pd.DataFrame(rows, columns=["date", "ticker", "status"])
    return df.set_index(["date", "ticker"])


def test_entry_status_and_overheat_exit_reason():
    trades = _trades([("2024-01-02", "A", "买入", 10.0, 1.0, 10.0, 0.0),
                      ("2024-01-10", "A", "卖出", 11.0, 1.0, 11.0, 0.0)])
    signals = _signals([("2024-01-02", "A", "held_risk"),
                        ("2024-01-10", "A", "overheat_exit")])
    out = roundtrips.match_round_trips(trades, signals)
    assert out.iloc[0]["entry_status"] == "held_risk"
    assert out.iloc[0]["exit_reason"] == "overheat"


def test_exit_reason_switch_and_other():
    trades = _trades([("2024-01-02", "A", "买入", 10.0, 1.0, 10.0, 0.0),
                      ("2024-01-10", "A", "卖出", 11.0, 1.0, 11.0, 0.0)])
    held = _signals([("2024-01-02", "A", "held_risk"),
                     ("2024-01-10", "A", "candidate")])
    assert roundtrips.match_round_trips(trades, held).iloc[0]["exit_reason"] == "switch"

    out = roundtrips.match_round_trips(trades, signals=None)
    assert out.iloc[0]["entry_status"] is None
    assert out.iloc[0]["exit_reason"] == "other"


def test_empty_trades_returns_contract_columns():
    out = roundtrips.match_round_trips(pd.DataFrame(columns=["date", "ticker", "side",
                                                             "price", "quantity",
                                                             "notional", "cost"]))
    assert list(out.columns) == COLUMNS
    assert out.empty


def _ctx(nav_end=1.05, trades=None, signals=None):
    idx = pd.bdate_range("2024-01-01", "2024-01-31")
    nav = pd.Series(np.linspace(1.0, nav_end, len(idx)), index=idx)
    eq = pd.DataFrame({"nav": nav, "returns": nav.pct_change().fillna(0.0),
                       "cash": 0.0, "turnover": 0.0, "fees": 0.0}, index=idx)
    return ReportContext(run_id="r1", meta={}, params={}, equity=eq, benchmark=None,
                         weights=None, holdings=None, trades=trades,
                         transactions=None, diary=None, ticker_signals=signals,
                         stages=None, classification={}, close=None, opn=None,
                         amount=None, metrics={})


def test_build_summary_win_rate_and_residual():
    trades = _trades([("2024-01-02", "A", "买入", 0.10, 1.0, 0.10, 0.0),
                      ("2024-01-10", "A", "卖出", 0.12, 1.0, 0.12, 0.0),
                      ("2024-01-11", "B", "买入", 0.20, 1.0, 0.20, 0.0)])
    out = roundtrips.build(_ctx(trades=trades))

    summary = out["summary"]
    assert summary["n_roundtrips"] == 1
    assert summary["win_rate"] == pytest.approx(1.0)
    assert summary["pnl_sum"] == pytest.approx(0.02)
    assert summary["open_lots"] == 1
    assert summary["open_cost"] == pytest.approx(0.0)
    assert summary["nav_return"] == pytest.approx(0.05)
    assert summary["residual"] == pytest.approx(0.05 - 0.02)
    assert out["roundtrips"][0]["ticker"] == "A"


def test_build_counts_open_lot_cost():
    trades = _trades([("2024-01-02", "A", "买入", 0.10, 1.0, 0.10, 0.001)])
    out = roundtrips.build(_ctx(trades=trades))
    assert out["summary"]["n_roundtrips"] == 0
    assert out["summary"]["open_lots"] == 1
    assert out["summary"]["open_cost"] == pytest.approx(0.001)
