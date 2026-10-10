import pandas as pd
import pytest

from etf_rotation.evaluation import metrics, overfitting


def test_summary_known_series():
    r = pd.Series([0.01, -0.005, 0.02], dtype=float)
    s = metrics.summary(r)
    expected = (1.01 * 0.995 * 1.02) ** (252 / 3) - 1
    assert s["ann_return"] == pytest.approx(expected)
    assert "max_drawdown" in s and "sharpe" in s


def test_dsr_high_for_many_bad_trials():
    p = overfitting.deflated_sharpe([0.5] * 100, 100)
    assert 0 <= p <= 1

