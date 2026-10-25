"""极端日与当日归因（N12）契约（计划 Task 15）。

口径：
- 极端日 = 组合日收益最差 `top_n` 天 + 最好 `top_n` 天（去重后按收益升序）；
- `class_contrib_c,t = Σ_{i∈c} w_{i,t−1}·r_{i,t}`（T−1 日权重配 t 日收益，
  复用 `attribution.asset_class_contributions`）；
- `residual = return_t − Σ_c class_contrib_c,t`：真实数据里含现金利息、
  费用与执行偏差，**不强行归零**，也不断言贡献之和等于当日收益；
- `regime` / `total_weight` 取当日决策日记（信号日口径）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etf_rotation.report.steps import extremes


def test_extreme_days_returns_both_tails():
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    r = pd.Series(np.linspace(-0.02, 0.02, 30), index=idx)
    r.iloc[0] = 0.0
    weights = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    diary = pd.DataFrame({"regime": "range", "total_weight": 1.0}, index=idx)
    close = pd.DataFrame({"A": 10 * (1 + r).cumprod(), "B": 10 * (1 + r).cumprod()}, index=idx)
    out = extremes.extreme_days(r, weights, diary, close, {"A": "risk", "B": "risk"}, top_n=10)
    assert len(out) == 20
    assert out["return"].iloc[0] == pytest.approx(r.min())
    assert out["class_contrib"].iloc[0]["risk"] == pytest.approx(r.min(), abs=1e-9)
    assert abs(out["residual"].iloc[0]) < 1e-9


def test_extreme_days_output_is_sorted_and_has_contract_columns():
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    r = pd.Series(np.linspace(-0.05, 0.05, 10), index=idx)
    weights = pd.DataFrame({"A": 1.0}, index=idx)
    diary = pd.DataFrame({"regime": "bull", "total_weight": 1.0}, index=idx)
    close = pd.DataFrame({"A": 10 * (1 + r).cumprod()}, index=idx)
    out = extremes.extreme_days(r, weights, diary, close, {"A": "risk"}, top_n=3)
    assert list(out.columns) == ["date", "return", "regime", "total_weight",
                                 "class_contrib", "residual"]
    assert out["return"].is_monotonic_increasing
    assert out["regime"].tolist() == ["bull"] * len(out)


def test_residual_carries_cash_interest_instead_of_forcing_zero():
    idx = pd.date_range("2024-01-01", periods=6, freq="B")
    prices = pd.Series([10.0, 10.1, 10.2, 10.3, 10.4, 10.5], index=idx)
    close = pd.DataFrame({"A": prices})
    weights = pd.DataFrame({"A": 0.5}, index=idx)      # 半仓，另一半现金
    returns = close["A"].pct_change(fill_method=None).fillna(0.0) * 0.5 + 0.0001  # 含现金利息
    diary = pd.DataFrame({"regime": "range", "total_weight": 0.5}, index=idx)
    out = extremes.extreme_days(returns, weights, diary, close, {"A": "risk"}, top_n=3)
    assert out["residual"].abs().max() > 0.0            # 残差承载现金利息，不静默归零
    assert out["residual"].abs().max() < 0.01


def test_overlapping_tails_are_deduplicated():
    idx = pd.date_range("2024-01-01", periods=4, freq="B")
    r = pd.Series([0.01, -0.02, 0.03, 0.0], index=idx)
    weights = pd.DataFrame({"A": 1.0}, index=idx)
    diary = pd.DataFrame({"regime": "range", "total_weight": 1.0}, index=idx)
    close = pd.DataFrame({"A": 10 * (1 + r).cumprod()}, index=idx)
    out = extremes.extreme_days(r, weights, diary, close, {"A": "risk"}, top_n=3)
    assert len(out) == 4                               # 4 天全选，但不重复
    assert out["date"].is_unique
