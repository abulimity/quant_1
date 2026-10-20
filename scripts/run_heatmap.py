"""二维参数热力图。用法：scripts/run_heatmap.py --grid dedupe.corr_threshold=0.75,0.80,0.85 --grid costs.one_side_bps=0,8,16"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import pandas as pd
import plotly.express as px

from etf_rotation.execution import shift_weights
from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.evaluation import metrics, sensitivity
from etf_rotation.pipeline import build_weights, load_context

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", action="append", required=True)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-07-31")
    ap.add_argument("--metric", default="sharpe")
    args = ap.parse_args()

    grid = {k: v for k, v in (sensitivity.parse_grid_spec(s) for s in args.grid)}
    assert len(grid) == 2, "heatmap needs exactly two --grid dimensions"
    ctx = load_context()
    rows = []
    for combo in itertools.product(*grid.values()):
        params = dict(zip(grid.keys(), combo))
        p = config.load_params()
        for k, val in params.items():
            config.set_nested(p, k, str(val))
        weights = build_weights(p, args.start, args.end, context=ctx)
        close = ctx["close"].reindex(index=weights.index, columns=weights.columns)
        opn = ctx["opn"].reindex(index=weights.index, columns=weights.columns)
        eff = shift_weights.shift_weights(weights)
        r = run.run(eff, opn, close, cost_bps=p["costs"]["one_side_bps"],
                    cash_rate=p["costs"]["cash_rate_annual"])
        s = metrics.from_stats(r.stats)
        rows.append({**params, args.metric: s[args.metric],
                     "max_drawdown": s["max_drawdown"], "calmar": s["calmar"]})

    results = pd.DataFrame(rows)
    mat = sensitivity.pivot_heatmap(results, *grid, args.metric)
    fig = px.imshow(mat, text_auto=".2f", aspect="auto", color_continuous_scale="RdYlGn")
    out = ROOT / "reports" / f"heatmap_{'_x_'.join(grid)}.html"
    fig.write_html(out)
    print(json.dumps({"saved": str(out), "shape": list(mat.shape),
                      "rows": rows}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
