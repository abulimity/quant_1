"""目标 vs 实际持仓、换手分解（N6 + N8）契约（计划 Task 12）。

口径：
- `target_eff = weights.shift(1)`：T 日目标权重在 T+1 生效，必须显式 shift，
  否则会把「今天的信号」和「今天的成交」直接相减，得到虚假的执行偏差；
- `mean_abs = Σ|actual − target_eff| / 2`（单边口径，与 `equity.turnover` 同量纲），
  `max_abs = max|actual − target_eff|`；
- `turnover_split` 按日记**主事件**归因当日 `Σ|Δw|/2`，优先级
  overheat → vol_cap → switch → defensive → other，按年汇总；
- `reconcile = 分量合计 − equity.turnover 年合计`（引擎口径与权重口径的差），
  没有 equity 时该列为 None，绝不假装对齐。
"""
from __future__ import annotations

import pandas as pd
import pytest

from etf_rotation.report.steps import execution


def test_target_vs_actual_aligns_by_calendar_and_shifts_target():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    weights = pd.DataFrame({"A": [0.5, 0.5, 0.6], "B": [0.5, 0.5, 0.4]}, index=idx)
    holdings = pd.DataFrame({"A": [0.0, 0.5, 0.55], "B": [0.0, 0.5, 0.45]}, index=idx)
    out = execution.target_vs_actual(weights, holdings)
    assert out.loc[idx[1], "mean_abs"] == pytest.approx(0.0)
    assert out.loc[idx[2], "mean_abs"] == pytest.approx(0.05)


def test_target_vs_actual_reports_max_abs():
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    weights = pd.DataFrame({"A": [0.5, 0.5], "B": [0.5, 0.5]}, index=idx)
    holdings = pd.DataFrame({"A": [0.0, 0.8], "B": [0.0, 0.2]}, index=idx)
    out = execution.target_vs_actual(weights, holdings)
    assert out.loc[idx[1], "max_abs"] == pytest.approx(0.3)


def test_turnover_split_sums_to_total():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    weights = pd.DataFrame({"A": [0.5, 0.4, 0.3], "B": [0.5, 0.6, 0.7]}, index=idx)
    diary = pd.DataFrame({"hysteresis_held": [True, False, False],
                          "n_overheat_exits": [0, 0, 1], "vol_cap_scale": 1.0,
                          "n_defensive": 2}, index=idx)
    split = execution.turnover_split(diary, weights)
    assert split[["switch", "overheat", "vol_cap", "defensive", "other"]].sum().sum() == pytest.approx(0.2)


def test_turnover_split_uses_priority_order():
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    weights = pd.DataFrame({"A": [0.5, 0.3], "B": [0.5, 0.7]}, index=idx)
    # 同一天既是 switch 又是 overheat / vol_cap：主事件取 overheat
    diary = pd.DataFrame({"hysteresis_held": [True, False], "n_overheat_exits": [0, 1],
                          "vol_cap_scale": [1.0, 0.9], "n_defensive": [2, 2]}, index=idx)
    row = execution.turnover_split(diary, weights).iloc[0]
    assert row["overheat"] == pytest.approx(0.2)
    assert row["switch"] == 0.0 and row["vol_cap"] == 0.0


def test_turnover_split_defensive_change_goes_to_defensive_bucket():
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    weights = pd.DataFrame({"A": [0.5, 0.4], "B": [0.5, 0.6]}, index=idx)
    diary = pd.DataFrame({"hysteresis_held": [True, True], "n_overheat_exits": [0, 0],
                          "vol_cap_scale": [1.0, 1.0], "n_defensive": [2, 3]}, index=idx)
    row = execution.turnover_split(diary, weights).iloc[0]
    assert row["defensive"] == pytest.approx(0.1)


def test_turnover_split_reconciles_against_engine_when_equity_given():
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    weights = pd.DataFrame({"A": [0.5, 0.4], "B": [0.5, 0.6]}, index=idx)
    diary = pd.DataFrame({"hysteresis_held": [True, False], "n_overheat_exits": [0, 0],
                          "vol_cap_scale": [1.0, 1.0], "n_defensive": [2, 2]}, index=idx)
    equity = pd.DataFrame({"turnover": [0.0, 0.12]}, index=idx)
    row = execution.turnover_split(diary, weights, equity=equity).iloc[0]
    assert row["switch"] == pytest.approx(0.1)
    assert row["reconcile"] == pytest.approx(0.1 - 0.12)


def test_turnover_split_without_equity_leaves_reconcile_null():
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    weights = pd.DataFrame({"A": [0.5, 0.4], "B": [0.5, 0.6]}, index=idx)
    diary = pd.DataFrame({"hysteresis_held": [True, False], "n_overheat_exits": [0, 0],
                          "vol_cap_scale": [1.0, 1.0], "n_defensive": [2, 2]}, index=idx)
    row = execution.turnover_split(diary, weights).iloc[0]
    assert row["reconcile"] is None or pd.isna(row["reconcile"])
