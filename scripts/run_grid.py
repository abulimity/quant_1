"""单参数网格敏感性：一次只变一个维度。用法示例：
scripts/run_grid.py --grid dedupe.corr_threshold=0.75,0.80,0.85
"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import pandas as pd

from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.evaluation import metrics, overfitting, sensitivity
from etf_rotation.pipeline import build_weights, load_prices

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """单参数网格敏感性：一次只变一个维度（AGENTS.md 阶段目标 1）。

    对每个网格点重建权重并跑 bt，输出稳健性分数、悬崖检测与 DSR
    多重检验校正；结果写 reports/grid.json。
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", action="append", required=True)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-07-31")
    args = ap.parse_args()

    grid = {}
    for spec in args.grid:
        k, v = spec.split("=", 1)
        grid[k] = [float(x) for x in v.split(",")]  # --grid 形如 a.b=0.7,0.8,0.9

    rows, sharpes = [], []
    for combo in itertools.product(*grid.values()):
        params = dict(zip(grid.keys(), combo))
        p = config.load_params()
        for k, val in params.items():
            config.set_nested(p, k, str(val))
        weights = build_weights(p, args.start, args.end)
        close, opn, _ = load_prices()
        close = close.reindex(index=weights.index, columns=weights.columns)
        opn = opn.reindex(index=weights.index, columns=weights.columns)
        eff = weights.shift(1).fillna(0.0)  # T 日信号，T+1 生效
        r = run.run(eff, opn, close,
                    cost_bps=p["costs"]["one_side_bps"],
                    cash_rate=p["costs"]["cash_rate_annual"])
        s = metrics.from_stats(r.stats)
        sharpes.append(s["sharpe"])
        rows.append({**params, "sharpe": s["sharpe"], "max_drawdown": s["max_drawdown"],
                     "ann_return": s["ann_return"], "calmar": s["calmar"]})

    results = pd.DataFrame(rows)
    n = len(rows)
    out = {
        "grid": grid, "results": rows, "n_trials": n,
        "robustness": sensitivity.robustness_score(results),
        "cliffs": sensitivity.detect_cliffs(results, list(grid)),
        "dsr": overfitting.deflated_sharpe(sharpes, n),
    }
    (ROOT / "reports" / "grid.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("n_trials", "robustness", "cliffs", "dsr")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
