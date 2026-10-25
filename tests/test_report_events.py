"""调仓事件表与触发规则（N4）契约（计划 Task 10）。

口径：
- 事件判定只看 T 日决策日记与 T 日目标权重（信号日），成交在 T+1；
- `switch` = 整组迟滞未维持（`hysteresis_held == False`）；
- `overheat` = 当日有标的被过热规则清零（`n_overheat_exits > 0`）；
- `vol_cap` = 组合波动触顶缩放（`vol_cap_scale < 1`）；
- `defensive` = 防守仓数量相对前一日发生变化（`n_defensive.diff() != 0`）；
- `cross_asset` = 纳指/黄金腿权重相对前一日发生变化；
- `turnover = Σ|Δw|/2`（T 日目标权重相对前一日的单边换手），
  `top_changes` 为 |Δw| 最大的前 3 个标的；
- `fwd_5d/fwd_20d` 是**事后信息**：`Π(1+r_{t+1..t+n}) − 1`，尾部样本不足给 None。

`event_dates` 与 `rebalance_events` 必须共用同一判定函数（S3 / Task 14 复用），
禁止两处各写一套规则。
"""
from __future__ import annotations

import pandas as pd
import pytest

from etf_rotation.report.steps import events


def _diary(idx, **overrides):
    """最小决策日记：默认无任何触发（迟滞维持、无过热、无缩放、防守数不变）。"""
    data = {
        "regime": ["bull"] * len(idx),
        "hysteresis_held": [True] * len(idx),
        "n_overheat_exits": [0] * len(idx),
        "vol_cap_scale": [1.0] * len(idx),
        "n_defensive": [2] * len(idx),
    }
    data.update(overrides)
    return pd.DataFrame(data, index=idx)


def test_events_capture_switch_and_overheat():
    idx = pd.date_range("2024-01-01", periods=4, freq="B")
    diary = pd.DataFrame({"regime": ["bull"] * 4,
                          "hysteresis_held": [True, False, True, True],
                          "n_overheat_exits": [0, 0, 1, 0],
                          "vol_cap_scale": [1.0, 1.0, 1.0, 0.9],
                          "n_defensive": [2, 2, 2, 2]}, index=idx)
    weights = pd.DataFrame({"A": [0.6, 0.4, 0.0, 0.2], "B": [0.4, 0.6, 1.0, 0.8]}, index=idx)
    ev = events.rebalance_events(diary, weights, pd.Series(0.001, index=idx))
    assert {"switch", "overheat", "vol_cap"} <= set(ev["types"].explode())
    assert ev.loc[ev["date"] == "2024-01-02", "types"].iloc[0] == ["switch"]


def test_event_dates_uses_same_rule_as_rebalance_events():
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    diary = _diary(idx, hysteresis_held=[True, True, False, False, True],
                   n_overheat_exits=[0, 0, 0, 1, 0])
    weights = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    ev = events.rebalance_events(diary, weights, pd.Series(0.0, index=idx))
    dates = events.event_dates(diary, weights)
    assert isinstance(dates, pd.DatetimeIndex)
    assert list(dates) == list(pd.DatetimeIndex(ev["date"]))
    assert list(dates) == [idx[2], idx[3]]


def test_turnover_and_top_changes_use_previous_day():
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    diary = _diary(idx, hysteresis_held=[True, False])
    weights = pd.DataFrame({"A": [0.5, 0.3], "B": [0.3, 0.4], "C": [0.2, 0.3]}, index=idx)
    ev = events.rebalance_events(diary, weights, pd.Series(0.0, index=idx))
    row = ev.iloc[0]
    assert row["turnover"] == pytest.approx(0.2)
    assert [c["ticker"] for c in row["top_changes"]] == ["A", "B", "C"]
    assert row["top_changes"][0]["delta"] == pytest.approx(-0.2)


def test_first_day_has_no_change_so_no_turnover():
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    diary = _diary(idx)
    weights = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    ev = events.rebalance_events(diary, weights, pd.Series(0.0, index=idx))
    assert ev.empty                      # 无任何触发 → 无事件行
    assert events.event_dates(diary, weights).empty


def test_forward_returns_are_ex_post_and_none_when_tail_short():
    idx = pd.date_range("2024-01-01", periods=6, freq="B")
    diary = _diary(idx, hysteresis_held=[False, True, True, False, True, True])
    weights = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    returns = pd.Series([0.0, 0.01, 0.01, 0.01, 0.01, 0.01], index=idx)
    ev = events.rebalance_events(diary, weights, returns).reset_index(drop=True)

    first, second = ev.iloc[0], ev.iloc[1]
    assert first["fwd_5d"] == pytest.approx((1.01 ** 5) - 1.0)
    assert first["fwd_20d"] is None
    assert second["fwd_5d"] is None      # 尾部不足 5 个交易日


def test_defensive_and_cross_asset_changes_are_detected():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    diary = _diary(idx, n_defensive=[2, 2, 3],
                   nasdaq_weight=[0.10, 0.10, 0.25], gold_weight=[0.0, 0.0, 0.0])
    weights = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    ev = events.rebalance_events(diary, weights, pd.Series(0.0, index=idx))
    assert len(ev) == 1
    assert set(ev.iloc[0]["types"]) == {"defensive", "cross_asset"}


def test_types_are_deterministically_ordered():
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    diary = _diary(idx, hysteresis_held=[True, False], n_overheat_exits=[0, 2],
                   vol_cap_scale=[1.0, 0.8], n_defensive=[2, 3],
                   nasdaq_weight=[0.1, 0.2], gold_weight=[0.1, 0.1])
    weights = pd.DataFrame({"A": [0.5, 0.4], "B": [0.5, 0.6]}, index=idx)
    ev = events.rebalance_events(diary, weights, pd.Series(0.0, index=idx))
    assert ev.iloc[0]["types"] == ["switch", "overheat", "vol_cap", "defensive", "cross_asset"]
