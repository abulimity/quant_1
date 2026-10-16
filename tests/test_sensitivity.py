import pandas as pd

from etf_rotation.evaluation import sensitivity


def test_robustness_and_cliffs():
    r = pd.DataFrame({
        "lookback": [20, 21, 22, 20, 21, 22],
        "sharpe": [0.1, 1.5, 0.2, 0.3, 0.4, 0.5],
        "max_drawdown": [-0.1] * 6,
        "ann_return": [0.1] * 6,
        "calmar": [0.5] * 6,
    })
    assert sensitivity.robustness_score(r) == 1.0
    assert "lookback" in sensitivity.detect_cliffs(r, ["lookback"])


def test_parse_grid_spec():
    k, v = sensitivity.parse_grid_spec("dedupe.corr_threshold=0.75,0.80,0.85")
    assert k == "dedupe.corr_threshold" and v == [0.75, 0.80, 0.85]
    k2, v2 = sensitivity.parse_grid_spec("trend.windows=[[21,60],[21,63]]")
    assert k2 == "trend.windows" and v2 == [[21, 60], [21, 63]]
