import pytest

import numpy as np
import pandas as pd

from etf_rotation.portfolio import defensive, multi_asset, risk_layers


def test_base_weights_bull():
    w = multi_asset.base_weights("bull", 1.0, 1.0)
    assert w == {"risk": 0.50, "nasdaq": 0.375, "gold": 0.125}


def test_base_weights_bear():
    w = multi_asset.base_weights("bear", 1.0, 1.0)
    assert w["risk"] == 0.0


def test_risk_scale_weakness():
    assert risk_layers.risk_scale("bull", True, -0.01) == 1.0
    assert risk_layers.risk_scale("bull", False, -0.04) == 0.05
    assert risk_layers.risk_scale("bear", True, -0.01) == 0.0


def test_vol_scale_only_shrinks():
    assert risk_layers.vol_scale(0.20, 0.26) == 1.0
    assert abs(risk_layers.vol_scale(0.52, 0.26) - 0.5) < 1e-9


def test_range_95pct_applied_once():
    base = multi_asset.base_weights("range", 1.0, 1.0)
    scale = risk_layers.risk_scale("range", True, -0.01)
    assert base["risk"] * scale == pytest.approx(0.50 * 0.95)


def test_risk_scale_custom_drop_threshold():
    assert risk_layers.risk_scale("bull", False, -0.02, drop_threshold=-0.03) == 1.0
    assert risk_layers.risk_scale("bull", False, -0.04, drop_threshold=-0.03) == 0.05


def test_defensive_select_respects_top_n():
    idx = pd.date_range("2023-01-01", periods=120, freq="B")
    ret = pd.DataFrame(np.random.default_rng(0).normal(0, 0.01, (120, 6)),
                       index=idx, columns=list("ABCDEF"))
    vol = pd.Series([0.01] * 6, index=list("ABCDEF"))
    cat = pd.Series({"A": "bond", "B": "money", "C": "bond",
                     "D": "money", "E": "bond", "F": "money"})
    assert len(defensive.select(ret, vol, cat, top_n=2)) == 2
    assert len(defensive.select(ret, vol, cat, top_n=1)) == 1

