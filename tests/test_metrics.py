import pandas as pd
import pytest

from etf_rotation.evaluation import metrics, overfitting


def test_from_stats_maps_bt_stats():
    st = pd.Series({"cagr": 0.10, "daily_vol": 0.02, "daily_sharpe": 0.05,
                    "daily_sortino": 0.04, "max_drawdown": -0.20, "calmar": 0.5})
    s = metrics.from_stats(st)
    assert s["ann_return"] == 0.10
    assert s["ann_vol"] == 0.02
    assert s["sharpe"] == 0.05
    assert s["sortino"] == 0.04
    assert s["max_drawdown"] == -0.20
    assert s["calmar"] == 0.5
    assert "var_95" not in s and "cvar_95" not in s


def test_dsr_high_for_many_bad_trials():
    p = overfitting.deflated_sharpe([0.5] * 100, 100)
    assert 0 <= p <= 1

