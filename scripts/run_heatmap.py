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
    """二维参数热力图：两个参数维度做笛卡尔积，逐点回测并出交互式 HTML。

    用法：
        scripts/run_heatmap.py --grid dedupe.corr_threshold=0.75,0.80,0.85 \\
                               --grid costs.one_side_bps=0,8,16

    与 run_grid.py 的分工：run_grid 出汇总指标（稳健性分数/悬崖/DSR），
    本脚本出「二维景观图」，用来看是否存在「孤岛」（只有极窄的参数区间表现好，
    是过拟合的典型形态）。

    输出：reports/heatmap_<x>_<y>.html（plotly imshow，可交互）。
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", action="append", required=True)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-07-31")
    ap.add_argument("--metric", default="sharpe")
    args = ap.parse_args()

    grid = {k: v for k, v in (sensitivity.parse_grid_spec(s) for s in args.grid)}
    assert len(grid) == 2, "heatmap needs exactly two --grid dimensions"
    ctx = load_context()          # 数据面板只加载一次，所有网格点共用
    rows = []
    # 两个维度的笛卡尔积，逐点建权 + 回测
    for combo in itertools.product(*grid.values()):
        params = dict(zip(grid.keys(), combo))
        p = config.load_params()
        # 逐个参数覆写（写后即 schema 校验，非法取值当场报错）
        for k, val in params.items():
            config.set_nested(p, k, str(val))
        weights = build_weights(p, args.start, args.end, context=ctx)
        close = ctx["close"].reindex(index=weights.index, columns=weights.columns)
        opn = ctx["opn"].reindex(index=weights.index, columns=weights.columns)
        eff = shift_weights.shift_weights(weights)   # T 日信号、T+1 生效
        r = run.run(eff, opn, close, cost_bps=p["costs"]["one_side_bps"],
                    cash_rate=p["costs"]["cash_rate_annual"])
        s = metrics.from_stats(r.stats)
        rows.append({**params, args.metric: s[args.metric],
                     "max_drawdown": s["max_drawdown"], "calmar": s["calmar"]})

    results = pd.DataFrame(rows)
    # 透视成 (y × x) 的 metric 矩阵，供 imshow 着色
    mat = sensitivity.pivot_heatmap(results, *grid, args.metric)
    fig = px.imshow(mat, text_auto=".2f", aspect="auto", color_continuous_scale="RdYlGn")
    out = ROOT / "reports" / f"heatmap_{'_x_'.join(grid)}.html"
    fig.write_html(out)
    print(json.dumps({"saved": str(out), "shape": list(mat.shape),
                      "rows": rows}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
