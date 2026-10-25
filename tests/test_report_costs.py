"""成本拖累与盈亏平衡成本（N13）契约（计划 Task 11）。

口径：
- 分年 `fees` 取 `equity["fees"]` 当年求和（引擎记账，不二次推导）；
- `drag_pct = 年费用 / 年均净值`，`return_pct = 年末/年初 − 1`，
  `cost_share_pct = 费用 / (收益额 + 费用)`（收益额按年初净值计）；
- `breakeven_bps = (ann_return + annual_drag) / (2 × ann_one_side_turnover) × 1e4`，
  `ann_one_side_turnover` 必须与 `equity["turnover"]` 同口径（bt 的
  `min(买入额, 卖出额)/nav`，日均 × 252）；
- `ctx.metrics` 可能缺键（NaN 指标被 all_stats 丢弃），缺失时输出 None 而非抛错。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etf_rotation.report.context import ReportContext
from etf_rotation.report.steps import costs


def test_breakeven_formula():
    assert costs.breakeven_bps(0.10, 12.5, 0.02) == pytest.approx(0.12 / (2 * 12.5) * 1e4, rel=1e-9)


def test_breakeven_returns_none_on_zero_turnover():
    assert costs.breakeven_bps(0.10, 0.0, 0.02) is None
    assert costs.breakeven_bps(None, 12.5, 0.02) is None


def test_annual_drag_sums_daily_fee_flow():
    idx = pd.date_range("2024-01-01", "2024-12-31", freq="B")
    eq = pd.DataFrame({"nav": 1.0 + 0.0002 * np.arange(len(idx)),
                       "fees": [0.001] * len(idx), "turnover": 0.05}, index=idx)
    out = costs.annual_cost_drag(eq, trades=None)
    assert out.iloc[0]["year"] == 2024
    assert out.iloc[0]["fees"] == pytest.approx(0.001 * len(idx))


def test_annual_drag_columns_and_share_formula():
    idx = pd.bdate_range("2023-12-01", "2024-12-31")
    nav = pd.Series(np.linspace(1.0, 1.2, len(idx)), index=idx)
    eq = pd.DataFrame({"nav": nav, "fees": 0.001, "turnover": 0.05}, index=idx)
    out = costs.annual_cost_drag(eq)

    assert list(out.columns) == ["year", "fees", "avg_nav", "drag_pct",
                                 "return_pct", "cost_share_pct"]
    row = out[out["year"] == 2024].iloc[0]
    block = nav[nav.index.year == 2024]
    fees = 0.001 * len(block)
    assert row["fees"] == pytest.approx(fees)
    assert row["avg_nav"] == pytest.approx(block.mean())
    assert row["drag_pct"] == pytest.approx(fees / block.mean())
    assert row["return_pct"] == pytest.approx(block.iloc[-1] / block.iloc[0] - 1)
    assert row["cost_share_pct"] == pytest.approx(
        fees / ((block.iloc[-1] - block.iloc[0]) + fees))


def test_annual_one_side_turnover_annualizes_daily_mean():
    idx = pd.bdate_range("2024-01-01", "2024-03-29")
    eq = pd.DataFrame({"nav": 1.0, "fees": 0.0, "turnover": 0.05}, index=idx)
    assert costs.annual_one_side_turnover(eq) == pytest.approx(0.05 * 252)


def test_reconcile_reports_fee_relative_error():
    trades = pd.DataFrame({"cost": [0.01, 0.02]})
    out = costs.reconcile(trades, {"total_fees": 0.0300000001})
    assert out["trades_cost"] == pytest.approx(0.03)
    assert out["total_fees"] == pytest.approx(0.0300000001)
    assert out["relative_error"] < 1e-6


def test_reconcile_tolerates_missing_metrics_and_trades():
    out = costs.reconcile(None, {})
    assert out["trades_cost"] is None and out["relative_error"] is None


def _ctx(metrics, trades=None):
    idx = pd.bdate_range("2024-01-01", "2024-12-31")
    eq = pd.DataFrame({
        "nav": np.linspace(1.0, 1.1, len(idx)),
        "returns": 0.0,
        "cash": 0.0,
        "turnover": 0.05,
        "fees": 0.001,
    }, index=idx)
    return ReportContext(run_id="r1", meta={}, params={}, equity=eq, benchmark=None,
                         weights=None, holdings=None, trades=trades,
                         transactions=None, diary=None, ticker_signals=None,
                         stages=None, classification={}, close=None, opn=None,
                         amount=None, metrics=metrics)


def test_build_outputs_breakeven_and_reconciliation():
    idx = pd.bdate_range("2024-01-01", "2024-12-31")
    trades = pd.DataFrame({"date": idx[:2], "notional": [10.0, 10.0], "cost": [0.1, 0.1]})
    ctx = _ctx({"ann_return": 0.10, "total_fees": 0.2}, trades)
    out = costs.build(ctx)

    assert out["annual"][0]["year"] == 2024
    assert out["breakeven"]["ann_one_side_turnover"] == pytest.approx(0.05 * 252)
    ann_drag = out["breakeven"]["annual_drag"]
    expected = (0.10 + ann_drag) / (2 * 0.05 * 252) * 1e4
    assert out["breakeven"]["bps"] == pytest.approx(expected)
    assert out["reconciliation"]["relative_error"] == pytest.approx(0.0, abs=1e-12)
    assert out["reconciliation"]["turnover"]["relative_error"] is not None


def test_build_survives_missing_metric_keys():
    out = costs.build(_ctx({}))
    assert out["breakeven"]["bps"] is None
    assert out["breakeven"]["ann_return"] is None
