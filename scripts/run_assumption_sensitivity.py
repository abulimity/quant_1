"""假设敏感性网格（H1/H3/H4/H5/H7 标量假设）：每个变体建权 → 回测 → 登记 registry。"""
from __future__ import annotations

import json
from pathlib import Path

from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.data import snapshot
from etf_rotation.evaluation import metrics, registry
from etf_rotation.pipeline import build_weights, load_context

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("ann_return", "max_drawdown", "sharpe", "calmar", "turnover")

# 标量假设候选（H1/H3/H4/H5/H7，见 docs/assumptions.md）
ASSUMPTIONS = {
    "trend.weighting": ["linear", "exp"],                       # H1
    "risk.llm80_alpha": [0.0247, 0.05, 0.015],                  # H3（80/60/120 日等价）
    "execution.hysteresis_improve": [0.0, 0.02, 0.05, 0.10],    # H4
    "reversal.momentum_weight": [0.3, 0.5, 0.7],                # H5
    "multi_asset.nasdaq_exit_threshold": [0.0, 0.05, -0.05],    # H7
    "multi_asset.gold_exit_threshold": [0.0, 0.05, -0.05],      # H7
}


def _run_one(p, start, end, execution, ctx):
    weights = build_weights(p, start, end, context=ctx)
    close = ctx["close"].reindex(index=weights.index, columns=weights.columns)
    opn = ctx["opn"].reindex(index=weights.index, columns=weights.columns)
    eff = weights.shift(1).fillna(0.0)
    r = run.run(eff, opn, close, cost_bps=p["costs"]["one_side_bps"],
                cash_rate=p["costs"]["cash_rate_annual"], execution=execution)
    s = metrics.from_stats(r.stats)
    s["turnover"] = float(r.turnover.mean())
    s["total_fees"] = float(r.fees.sum())
    flat = config.flatten_params(p)
    flat["_start"], flat["_end"] = start, end
    data_snap = snapshot.data_snapshot_id()
    gsha = registry.git_sha()
    run_id = registry.run_identity(flat, git_sha=gsha, data_snapshot_id=data_snap,
                                   execution=execution, signal_version=gsha)
    registry.register_run(
        ROOT / "data" / "warehouse.duckdb", run_id, flat, s, {},
        data_snapshot_id=data_snap, git_sha=gsha)
    return s


def main() -> None:
    start, end = "2019-01-01", "2026-07-31"
    ctx = load_context()
    out = {}
    for key, values in ASSUMPTIONS.items():
        rows = []
        for v in values:
            p = config.load_params()
            config.set_nested(p, key, str(v))
            s = _run_one(p, start, end, "open", ctx)
            rows.append({"value": v, **{k: s[k] for k in KEYS}})
        out[key] = rows
        print(json.dumps({key: rows}, ensure_ascii=False, indent=2))
    (ROOT / "reports" / "assumption_sensitivity.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved reports/assumption_sensitivity.json")


if __name__ == "__main__":
    main()
