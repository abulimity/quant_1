import numpy as np
import pandas as pd

from etf_rotation.evaluation import plots


def test_equity_drawdown_returns_figure():
    nav = pd.Series(
        1.0 + np.cumsum(np.random.default_rng(0).normal(0, 0.01, 100)),
        index=pd.date_range("2024-01-01", periods=100),
    )
    fig = plots.equity_drawdown(nav)
    assert fig is not None
    assert len(fig.data) == 2  # 净值 + 回撤


def test_cost_sensitivity_returns_figure():
    sens = pd.DataFrame(
        {
            "cost_bps": [0, 8, 16, 24],
            "ann_return": [0.18, 0.16, 0.14, 0.12],
            "max_drawdown": [-0.088, -0.091, -0.094, -0.104],
            "calmar": [2.08, 1.76, 1.47, 1.13],
        }
    )
    fig = plots.cost_sensitivity(sens)
    assert fig is not None
    assert len(fig.data) == 3  # 年化收益 / Calmar / 最大回撤

