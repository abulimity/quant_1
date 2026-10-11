import numpy as np
import pandas as pd

from etf_rotation.evaluation import plots


def _series(n=400, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n)
    return pd.Series(1.0 + np.cumsum(rng.normal(0, 0.008, n)), index=idx)


def _returns(n=400, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-01-01", periods=n)
    return pd.Series(rng.normal(0.0004, 0.01, n), index=idx)


def test_nav_and_drawdown_figures():
    nav = _series()
    bench = _series(400, 1)
    hs = _series(400, 2)
    assert len(plots.nav_comparison(nav, bench, hs).data) == 3
    assert len(plots.drawdown_curve(nav, bench).data) == 2


def test_rolling_and_subperiod_and_monthly():
    r = _returns()
    regime = pd.Series("range", index=r.index)
    regime.iloc[:100] = "bull"
    assert len(plots.rolling_perf(r).data) == 4
    assert len(plots.subperiod_performance(r, regime).data) == 2
    assert plots.monthly_heatmap(r) is not None


def test_holdings_and_distribution_and_cost():
    r = _returns(300)
    idx = r.index
    w = pd.DataFrame(
        {"A": np.full(300, 0.4), "B": np.full(300, 0.3), "C": np.full(300, 0.2)},
        index=idx,
    )
    label_map = {"A": "风险资产", "B": "纳指", "C": "防守"}
    assert plots.holdings_distribution(w, label_map) is not None
    assert plots.return_distribution(r) is not None
    sens = pd.DataFrame(
        {"cost_bps": [0, 8, 16, 24], "ann_return": [0.18, 0.16, 0.14, 0.12],
         "max_drawdown": [-0.088, -0.091, -0.094, -0.104],
         "calmar": [2.08, 1.76, 1.47, 1.13]}
    )
    assert len(plots.cost_sensitivity(sens).data) == 3

