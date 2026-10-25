"""二维参数热力图。用法：

    scripts/run_heatmap.py --grid dedupe.corr_threshold=0.75,0.80,0.85 \
                           --grid costs.one_side_bps=0,8,16

与 run_grid.py 的分工：run_grid 出汇总指标（稳健性分数/悬崖/DSR），
本脚本出「二维景观图」，用来看是否存在「孤岛」（只有极窄的参数区间表现好，
是过拟合的典型形态）。

落盘契约（Task 19）：
- 每个点一个 run（kind="grid"）+ 一条 family 成员；
- `families/{fid}/results.json` 保存逐点结果（供前端读）；
- HTML 仍写 `reports/heatmap_<x>_<y>.html`。
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px

from etf_rotation.execution import shift_weights
from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.data import snapshot
from etf_rotation.evaluation import artifacts, metrics, registry, sensitivity, sweep
from etf_rotation.pipeline import build_weights, load_context
from etf_rotation.signals import cache

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))   # scripts 不是包
from collect_runs import family_summary  # noqa: E402


def main() -> None:
    """两个参数维度做笛卡尔积，逐点回测并出交互式 HTML。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", action="append", required=True)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-07-31")
    ap.add_argument("--execution", choices=["close", "open"], default="open")
    ap.add_argument("--metric", default="sharpe")
    ap.add_argument("--save-profile", choices=list(artifacts.SAVE_PROFILES),
                    default="minimal")
    ap.add_argument("--campaign", default="")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    grid = {k: v for k, v in (sensitivity.parse_grid_spec(s) for s in args.grid)}
    assert len(grid) == 2, "heatmap needs exactly two --grid dimensions"
    base = config.load_params()
    ctx = load_context()          # 数据面板只加载一次，所有网格点共用
    gsha, dirty_hash = registry.git_info()
    data_snap = snapshot.data_snapshot_id()

    base_flat = config.flatten_params(base)
    for key in grid:
        base_flat.pop(key, None)
    base_flat["_start"], base_flat["_end"] = args.start, args.end

    def run_one(point: dict) -> tuple[dict, dict, dict]:
        """单点：覆写参数 → 建权 → bt 记账 → 指标 + 产物面板。"""
        p = copy.deepcopy(base)
        for key, value in point.items():
            config.set_nested(p, key, str(value))
        weights = build_weights(p, args.start, args.end, context=ctx)
        close = ctx["close"].reindex(index=weights.index, columns=weights.columns)
        opn = ctx["opn"].reindex(index=weights.index, columns=weights.columns)
        eff = shift_weights.shift_weights(weights)   # T 日信号、T+1 生效
        r = run.run(eff, opn, close,
                    cost_bps=p["costs"]["one_side_bps"],
                    cash_rate=p["costs"]["cash_rate_annual"],
                    execution=args.execution,
                    gap_delay_pct=p["execution"]["gap_delay_pct"])
        s = metrics.all_stats(r.stats)
        s["turnover"] = float(r.turnover.mean())
        s["total_fees"] = float(r.fees.sum())

        flat = config.flatten_params(p)
        flat["_start"], flat["_end"] = args.start, args.end
        meta = {
            "schema_version": 2,
            "params_json": flat,
            "signal_id": cache.signal_id(flat, data_snap),
            "git_sha": gsha,
            "git_dirty": bool(dirty_hash),
            "dirty_hash": dirty_hash,
            "env_lock_hash": registry.env_lock_hash(),
            "data_snapshot_id": data_snap,
            "execution": args.execution,
            "start": args.start,
            "end": args.end,
            "n_obs": int(r.returns.notna().sum()),
        }
        frames = {
            "equity": metrics.build_equity_frame(r.nav, r.returns, r.cash,
                                                 r.turnover, r.fees),
            "weights": weights,
            "holdings": r.positions,
        }
        return meta, s, frames

    out = sweep.run_sweep(
        points=sweep.iter_points(grid), run_one=run_one, kind="grid",
        profile=args.save_profile, campaign_id=args.campaign, tag=args.tag,
        runs_root=ROOT / "reports" / "runs",
        families_root=ROOT / "reports" / "families",
        git_sha=gsha, data_snapshot_id=data_snap,
        start=args.start, end=args.end, execution=args.execution,
        spec=grid, base_params=base_flat, dirty_hash=dirty_hash,
    )
    summary = family_summary(ROOT / "reports" / "families",
                             ROOT / "reports" / "runs", out["family_id"])

    # 逐点结果写进 family 目录（不是共享的 reports/ 根）
    fam_dir = ROOT / "reports" / "families" / out["family_id"]
    (fam_dir / "results.json").write_text(
        json.dumps(sweep.jsonable(summary["results"]), ensure_ascii=False,
                   indent=2, allow_nan=False), encoding="utf-8")

    results = pd.DataFrame(summary["results"])
    # 透视成 (y × x) 的 metric 矩阵，供 imshow 着色
    mat = sensitivity.pivot_heatmap(results, *grid, args.metric)
    fig = px.imshow(mat, text_auto=".2f", aspect="auto", color_continuous_scale="RdYlGn")
    html = ROOT / "reports" / f"heatmap_{'_x_'.join(grid)}.html"
    fig.write_html(html)

    print(json.dumps({
        "saved": str(html),
        "family_id": out["family_id"],
        "n_trials": out["n_trials"],
        "shape": list(mat.shape),
        "results": f"reports/families/{out['family_id']}/results.json",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
