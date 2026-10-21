"""样本外子区间复核（open 口径）：2019–2023 vs 2024–2026。

用法：scripts/run_oos_check.py --param trend.weighting=exp [--param a.b=v ...]
对给定参数覆盖，在两个子区间各跑一次 build_weights + bt 记账，落盘 reports/oos_check.json。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from etf_rotation.execution import shift_weights
from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.evaluation import metrics
from etf_rotation.pipeline import build_weights, load_context

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("ann_return", "max_drawdown", "sharpe", "calmar")
SUBPERIODS = [
    ("2019-2023", "2019-01-01", "2023-12-31"),
    ("2024-2026", "2024-01-01", "2026-07-31"),
]


def _run(p: dict, start: str, end: str, ctx: dict) -> dict:
    weights = build_weights(p, start, end, context=ctx)
    close = ctx["close"].reindex(index=weights.index, columns=weights.columns)
    opn = ctx["opn"].reindex(index=weights.index, columns=weights.columns)
    eff = shift_weights.shift_weights(weights)  # T 日信号，T+1 生效
    r = run.run(eff, opn, close, cost_bps=p["costs"]["one_side_bps"],
                cash_rate=p["costs"]["cash_rate_annual"], execution="open")
    s = metrics.from_stats(r.stats)
    return {k: s[k] for k in KEYS}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--param", action="append", default=[])
    args = ap.parse_args()

    p = config.load_params()
    for kv in args.param:
        k, v = kv.split("=", 1)
        config.set_nested(p, k, v)

    ctx = load_context()
    subperiods = {}
    for label, start, end in SUBPERIODS:
        subperiods[label] = _run(p, start, end, ctx)

    out = {"param_overrides": args.param, "subperiods": subperiods}
    (ROOT / "reports" / "oos_check.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
