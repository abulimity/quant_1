"""机制开关对照（ablation）：逐项关闭一个机制，登记结果，观察边际增量。"""
from __future__ import annotations

import json
from pathlib import Path

from etf_rotation.execution import shift_weights
from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.data import snapshot
from etf_rotation.evaluation import metrics, registry
from etf_rotation.pipeline import build_weights, load_context

ROOT = Path(__file__).resolve().parents[1]
MECHANISMS = ["phases", "hysteresis", "reversal", "overheat", "vol_cap"]
KEYS = ("ann_return", "max_drawdown", "sharpe", "calmar", "turnover")


def _run(p, start, end, ctx):
    weights = build_weights(p, start, end, context=ctx)
    close = ctx["close"].reindex(index=weights.index, columns=weights.columns)
    opn = ctx["opn"].reindex(index=weights.index, columns=weights.columns)
    eff = shift_weights.shift_weights(weights)
    r = run.run(eff, opn, close, cost_bps=p["costs"]["one_side_bps"],
                cash_rate=p["costs"]["cash_rate_annual"], execution="open")
    s = metrics.from_stats(r.stats)
    s["turnover"] = float(r.turnover.mean())
    flat = config.flatten_params(p)
    flat["_start"], flat["_end"] = start, end
    data_snap = snapshot.data_snapshot_id()
    gsha = registry.git_sha()
    run_id = registry.run_identity(flat, git_sha=gsha, data_snapshot_id=data_snap,
                                   execution="open", signal_version=gsha)
    registry.register_run(
        ROOT / "data" / "warehouse.duckdb", run_id, flat, s, {},
        data_snapshot_id=data_snap, git_sha=gsha, execution="open")
    return s


def main() -> None:
    start, end = "2019-01-01", "2026-07-31"
    ctx = load_context()
    rows = []
    s = _run(config.load_params(), start, end, ctx)
    rows.append({"mechanism": "baseline(all-on)", **{k: s[k] for k in KEYS}})
    for m in MECHANISMS:
        p = config.load_params()
        p["mechanisms"][m] = False
        s = _run(p, start, end, ctx)
        rows.append({"mechanism": f"{m}=off", **{k: s[k] for k in KEYS}})
    (ROOT / "reports" / "ablation.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
