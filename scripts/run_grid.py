"""单参数网格敏感性：一次只变一个维度。用法示例：

    scripts/run_grid.py --grid dedupe.corr_threshold=0.75,0.80,0.85
    scripts/run_grid.py --grid defensive.max_vol_60d=0.03,0.04 --save-profile minimal --campaign demo

落盘契约（Task 19）：
- 每个网格点一个 run（`reports/runs/{run_id}/`），kind="grid"；
- 每个点登记一条 family 成员（`reports/families/{fid}/members/{run_id}.json`）；
- sweep 结束后由本进程（单进程）生成 `families/{fid}/summary.json`；
- `reports/grid.json` 变成 summary 的兼容镜像（带 `generated` 标记），不再手写。
- 网格不写 `reports/latest.json`：基准位置只属于 `run_backtest`。
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from etf_rotation.execution import shift_weights
from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.data import snapshot
from etf_rotation.evaluation import artifacts, metrics, registry, sensitivity, sweep
from etf_rotation.pipeline import build_weights, compute_benchmark, load_context
from etf_rotation.signals import cache

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))   # scripts 不是包
from collect_runs import family_summary  # noqa: E402


def main() -> None:
    """笛卡尔积逐点建权 → bt 记账 → store_run → 登记 family → 写 summary 镜像。

    与旧版的差异：不再调用 `registry.register_run`（已删除），也不再手写
    `reports/grid.json`；身份、落盘、成员登记全部走 `sweep.run_sweep`。
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", action="append", required=True,
                    help="参数名=候选值1,候选值2（可重复，多维度做笛卡尔积）")
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-07-31")
    ap.add_argument("--execution", choices=["close", "open"], default="open")
    ap.add_argument("--save-profile", choices=list(artifacts.SAVE_PROFILES),
                    default="standard")
    ap.add_argument("--campaign", default="", help="campaign_id（DSR 跨 family 累计用）")
    ap.add_argument("--tag", default="", help="自由标签，只写 meta，不参与身份")
    args = ap.parse_args()

    grid = {k: v for k, v in (sensitivity.parse_grid_spec(s) for s in args.grid)}
    base = config.load_params()       # 基准参数：每个点都从这份干净副本出发
    ctx = load_context()              # 数据面板只加载一次，所有网格点共用
    gsha, dirty_hash = registry.git_info()
    data_snap = snapshot.data_snapshot_id()

    # 未参与网格的基准参数进入 family 身份，避免「同名网格、不同底参」串族
    base_flat = config.flatten_params(base)
    for key in grid:
        base_flat.pop(key, None)
    base_flat["_start"], base_flat["_end"] = args.start, args.end

    # 基准序列与网格点无关（8 个维度都不改 universe），循环外算一次复用
    bench = compute_benchmark(base, args.start, args.end)

    def run_one(point: dict) -> tuple[dict, dict, dict]:
        """单点：覆写参数 → 建权 → bt 记账 → 指标 + 产物面板。"""
        p = copy.deepcopy(base)
        for key, value in point.items():
            config.set_nested(p, key, str(value))
        weights = build_weights(p, args.start, args.end, context=ctx)
        close = ctx["close"].reindex(index=weights.index, columns=weights.columns)
        opn = ctx["opn"].reindex(index=weights.index, columns=weights.columns)
        eff = shift_weights.shift_weights(weights)      # T 日信号，T+1 生效
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
            "benchmark": bench,
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

    # grid.json：summary 的兼容镜像（旧读法：grid/results/n_trials/robustness/
    # cliffs/dsr）。dsr 指向 family 内校正；campaign 累计值只在 summary 里。
    mirror = {
        "grid": grid,
        "results": summary["results"],
        "n_trials": summary["n_trials"],
        "robustness": summary["robustness"],
        "cliffs": summary["cliffs"],
        "dsr": summary["dsr_family"],
        "sharpe_haircut": summary["sharpe_haircut"],
        "family_id": out["family_id"],
        "campaign_id": args.campaign,
        "generated": True,
        "generated_from": f"reports/families/{out['family_id']}/summary.json",
        "generated_at": summary["generated"],
    }
    (ROOT / "reports" / "grid.json").write_text(
        json.dumps(sweep.jsonable(mirror), ensure_ascii=False, indent=2,
                   allow_nan=False), encoding="utf-8")

    # 单维度文件 + 跨维度汇总：保留旧路径，内容改为 summary 派生
    key = sorted(grid)[0]
    sens_dir = ROOT / "reports" / "sensitivity"
    sens_dir.mkdir(exist_ok=True)
    (sens_dir / f"{key.replace('.', '_')}.json").write_text(
        json.dumps(sweep.jsonable(mirror), ensure_ascii=False, indent=2,
                   allow_nan=False), encoding="utf-8")
    summary_path = ROOT / "reports" / "sensitivity_summary.json"
    summary_old = (json.loads(summary_path.read_text(encoding="utf-8"))
                   if summary_path.exists() else {})
    summary_old[key] = {
        "n_trials": summary["n_trials"],
        "robustness": summary["robustness"],
        "cliffs": summary["cliffs"],
        "dsr": summary["dsr_family"],
        "sharpe_haircut": summary["sharpe_haircut"],
        "family_id": out["family_id"],
    }
    summary_path.write_text(json.dumps(sweep.jsonable(summary_old), ensure_ascii=False,
                                       indent=2, allow_nan=False), encoding="utf-8")

    print(json.dumps({
        "family_id": out["family_id"],
        "n_trials": out["n_trials"],
        "run_ids": out["run_ids"],
        "robustness": summary["robustness"],
        "cliffs": summary["cliffs"],
        "dsr_family": summary["dsr_family"],
        "dsr_campaign": summary["dsr_campaign"],
        "summary": f"reports/families/{out['family_id']}/summary.json",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
