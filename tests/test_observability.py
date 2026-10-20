from etf_rotation import config
from etf_rotation import pipeline as pipe
from etf_rotation.evaluation import observability


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
