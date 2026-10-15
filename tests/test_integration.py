import numpy as np
import pandas as pd
import pytest

from etf_rotation.backtest import run
from etf_rotation.evaluation import metrics, plots, trades


def test_downstream_chain_on_synthetic_data(tmp_path):
    idx = pd.date_range("2024-01-01", periods=120)
    rng = np.random.default_rng(0)
    close = pd.DataFrame(
        {
            "A": np.cumprod(1 + rng.normal(0, 0.008, 120)),
            "B": np.cumprod(1 + rng.normal(0, 0.006, 120)),
            "C": np.cumprod(1 + rng.normal(0, 0.010, 120)),
        },
        index=idx,
    )
    open_ = close.shift(1).fillna(close.iloc[0])
    w = pd.DataFrame({"A": 0.5, "B": 0.3, "C": 0.2}, index=idx)
    eff = w.shift(1).fillna(0.0)

    res = run.run(eff, open_, close, cost_bps=8, cash_rate=0.018)
    assert res.nav.iloc[0] == pytest.approx(1.0)
    assert res.returns.notna().all()

    s = metrics.from_stats(res.stats)
    assert {"ann_return", "sharpe", "max_drawdown", "calmar"} <= set(s)

    t = trades.build_trade_table_from_engine(res.result.get_transactions())
    assert len(t) > 0

    fig = plots.nav_comparison(res.nav, res.nav, res.nav)
    out = tmp_path / "r.html"
    plots.write_report([("测试", "说明", fig)], [("年化", f"{s['ann_return']:.2%}")], out)
    assert out.exists() and out.stat().st_size > 1000

