"""运行基准回测并输出绩效指标。用法：python scripts/run_backtest.py [START] [END]"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from etf_rotation import __version__, config
from etf_rotation.backtest import run
from etf_rotation.evaluation import metrics, registry
from etf_rotation.pipeline import build_weights, compute_benchmark, load_prices

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("start", nargs="?", default="2019-01-01")
    parser.add_argument("end", nargs="?", default="2026-07-31")
    parser.add_argument("--param", action="append", default=[])
    args = parser.parse_args()

    p = config.load_params()
    for kv in args.param:
        k, v = kv.split("=", 1)
        config.set_nested(p, k, v)
    start, end = args.start, args.end
    print(f"etf-rotation v{__version__}")
    print(f"building weights {start}..{end}")
    weights = build_weights(p, start, end)
    close, opn, _ = load_prices()
    close = close.reindex(index=weights.index, columns=weights.columns)
    opn = opn.reindex(index=weights.index, columns=weights.columns)
    eff = weights.shift(1).fillna(0.0)  # T 日信号，T+1 生效
    res = run.run(eff, opn, close,
                  cost_bps=p["costs"]["one_side_bps"],
                  cash_rate=p["costs"]["cash_rate_annual"])
    s = metrics.from_stats(res.stats)
    s["turnover"] = float(res.turnover.mean())
    print(json.dumps({k: (round(v, 6) if isinstance(v, float) else v) for k, v in s.items()},
                     ensure_ascii=False, indent=2))
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    pd.DataFrame({"nav": res.nav, "returns": res.returns}).to_csv(out / "equity.csv")
    weights.to_parquet(out / "weights.parquet")
    compute_benchmark(p, start, end).to_csv(out / "benchmark.csv")
    (out / "metrics.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

    flat = config.flatten_params(p)
    flat["_start"], flat["_end"] = start, end
    run_id = registry.config_hash(flat)
    registry.register_run(
        ROOT / "data" / "warehouse.duckdb", run_id, flat, s,
        {"equity": str(out / "equity.csv"), "weights": str(out / "weights.parquet"),
         "benchmark": str(out / "benchmark.csv"), "metrics": str(out / "metrics.json")},
    )
    print(f"registered run {run_id}")
    print(f"saved to {out}")


if __name__ == "__main__":
    main()

