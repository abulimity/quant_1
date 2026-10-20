from etf_rotation.portfolio import multi_asset


def test_base_weights_default_exit_threshold_zero():
    w = multi_asset.base_weights("bull", nasdaq_signal=0.01, gold_signal=-0.01)
    assert w["nasdaq"] == 0.375
    assert w["gold"] == 0.0


def test_base_weights_exit_threshold_param():
    w = multi_asset.base_weights("bull", nasdaq_signal=0.01, gold_signal=-0.01,
                                 nasdaq_exit_threshold=0.05)
    assert w["nasdaq"] == 0.0
