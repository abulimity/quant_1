import pandas as pd
import pytest

from etf_rotation.evaluation import exposure


def test_hhi_and_effective_n():
    w = pd.Series({"A": 0.5, "B": 0.5})
    assert exposure.hhi(w) == pytest.approx(0.5)
    assert exposure.effective_n(w) == pytest.approx(2.0)
    w2 = pd.Series({"A": 1.0})
    assert exposure.hhi(w2) == pytest.approx(1.0)
    assert exposure.effective_n(w2) == pytest.approx(1.0)


def test_asset_class_exposure():
    idx = pd.date_range("2024-01-01", periods=3)
    w = pd.DataFrame({"A": 0.4, "B": 0.3, "C": 0.3}, index=idx)
    classification = {"A": "risk", "B": "risk", "C": "defensive"}
    expo = exposure.asset_class_exposure(w, classification)
    assert expo["risk"].iloc[0] == pytest.approx(0.7)
    assert expo["defensive"].iloc[0] == pytest.approx(0.3)


def test_concentration_series():
    idx = pd.date_range("2024-01-01", periods=2)
    w = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    s = exposure.concentration_series(w)
    assert s["hhi"].iloc[0] == pytest.approx(0.5)
    assert s["effective_n"].iloc[0] == pytest.approx(2.0)
