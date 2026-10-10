from etf_rotation.portfolio import multi_asset, risk_layers


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

