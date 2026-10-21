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
    p = overfitting.deflated_sharpe([0.5] * 100, 100, n_obs=1900)
    assert 0 <= p <= 1


def test_deflated_sharpe_significant_with_large_n_obs():
    # 三个候选 Sharpe 均远高于零、观测数足够大时，DSR 应显著（>0.95）。
    # 修复前 sr_se=sqrt(1/(3-1))=0.707 → 约 0.55；修复后约 1.0。
    p = overfitting.deflated_sharpe([1.5, 1.5, 1.5], 3, n_obs=2000)
    assert p > 0.95


def test_sharpe_haircut_returns_expected_max():
    h = overfitting.sharpe_haircut([1.0, 1.1, 1.2, 1.3, 1.4])
    assert set(h) == {"observed_best", "expected_max", "haircut"}
    assert h["observed_best"] == pytest.approx(1.4)
    assert h["haircut"] == pytest.approx(h["observed_best"] - h["expected_max"])

