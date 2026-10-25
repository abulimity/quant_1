import pandas as pd

from etf_rotation import config
from etf_rotation import pipeline as pipe
from etf_rotation.evaluation import observability, plots


def test_build_frames_shapes_and_status():
    p = config.load_params()
    res = pipe.build_weights(p, "2024-01-01", "2024-06-30", with_trace=True)
    diary, tk = observability.build_frames(res.days, res.traces, res.sig, p)
    assert len(diary) == len(res.days)
    assert {"regime", "risk_budget", "total_weight", "cash_weight",
            "hysteresis_held"} <= set(diary.columns)
    assert set(tk.index.names) == {"date", "ticker"}
    assert {"m21", "m60", "score", "zbias", "weight", "status",
            "overheat_ratio"} <= set(tk.columns)
    assert not tk["status"].isna().all()


def test_ticker_signals_only_held_and_candidates():
    p = config.load_params()
    res = pipe.build_weights(p, "2024-01-01", "2024-06-30", with_trace=True)
    _, tk = observability.build_frames(res.days, res.traces, res.sig, p)
    assert tk.groupby(level="date").size().max() <= 3 * p["dedupe"]["max_holdings"] + 10


def _mock_diary_tk():
    import numpy as np
    idx = pd.date_range("2024-01-01", periods=20, freq="B")
    diary = pd.DataFrame({
        "regime": (["bull", "range", "bear"] * 7)[:20],
        "comp_score": np.linspace(-0.5, 0.5, 20),
        "risk_budget": np.full(20, 0.5),
        "nasdaq_weight": np.full(20, 0.2),
        "gold_weight": np.full(20, 0.1),
        "total_weight": np.full(20, 0.9),
        "cash_weight": np.full(20, 0.1),
        "n_overheat_exits": np.zeros(20),
        "hysteresis_held": [False] * 20,
        "vol_cap_scale": np.ones(20),
    }, index=idx)
    tk = pd.DataFrame({
        "m21": np.linspace(0, 0.1, 20),
        "m60": np.linspace(0, 0.2, 20),
        "score": np.full(20, 0.5),
        "zbias": np.linspace(-1, 0, 20),
        "rev_active": [False] * 20,
        "close": np.linspace(1, 1.2, 20),
        "llt80": np.linspace(1.0, 1.15, 20),
        "overheat_ratio": np.full(20, 0.95),
        "weight": np.full(20, 0.3),
        "status": ["held_risk"] * 20,
    })
    tk.index = pd.MultiIndex.from_arrays([idx, ["AAA.SH"] * 20], names=["date", "ticker"])
    return diary, tk


def test_trace_stages_in_semantic_order_and_final_matches_diary():
    p = config.load_params()
    res = pipe.build_weights(p, "2024-01-01", "2024-02-29", with_trace=True)
    assert res.traces
    expected = ["candidate", "overheat", "cross_asset", "defensive",
                "phases", "hysteresis", "final"]
    assert list(res.traces[0]["stages"]) == expected
    assert all(list(t["stages"]) == expected for t in res.traces)

    diary, _ = observability.build_frames(res.days, res.traces, res.sig, p)
    long = observability.build_stages(res.traces, res.days)
    final = (long.loc[long["stage"] == "final"]
             .groupby("date")["weight"].sum()
             .reindex(res.days, fill_value=0.0))
    assert (final - diary["total_weight"]).abs().max() < 1e-12


def test_write_with_stages_writes_parquet(tmp_path):
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    diary = pd.DataFrame({"total_weight": [0.5, 0.5]}, index=idx)
    tk = pd.DataFrame({"weight": [0.5, 0.5]})
    tk.index = pd.MultiIndex.from_arrays([idx, ["A.SH", "A.SH"]],
                                         names=["date", "ticker"])
    stages = pd.DataFrame({
        "date": [idx[0], idx[0], idx[1], idx[1]],
        "ticker": ["A.SH"] * 4,
        "stage": ["candidate"] * 2 + ["final"] * 2,
        "weight": [0.6, 0.6, 0.5, 0.5],
    })

    observability.write(tmp_path, diary, tk, stages=stages)

    out = pd.read_parquet(tmp_path / "signals" / "stages.parquet")
    assert list(out.columns) == ["date", "ticker", "stage", "weight"]
    assert len(out) == 4
    # 不给 stages 时保持旧行为：不产生 stages.parquet
    compat = tmp_path / "compat"
    observability.write(compat, diary, tk)
    assert not (compat / "signals" / "stages.parquet").exists()


def test_signal_plot_figures_build():
    import plotly.graph_objects as go

    diary, tk = _mock_diary_tk()
    nav = pd.Series(1.0, index=diary.index)
    for fig in (plots.market_state_timeline(diary, nav),
                plots.risk_budget_stack(diary),
                plots.signal_trends(tk, "AAA.SH")):
        assert isinstance(fig, go.Figure) and len(fig.data) > 0
