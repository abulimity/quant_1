"""成本与现金假设敏感性（复用已生成的权重，快速）。

每个成本档是一个 run（kind="cost"）并登记到同一个 family；DSR 仅对 4 个
高度相关的成本变体计算，报告里注明「仅作参考不作结论」。
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import pandas as pd

from etf_rotation.execution import shift_weights
from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.data import snapshot
from etf_rotation.evaluation import artifacts, metrics, registry, sweep
from etf_rotation.pipeline import build_weights, load_prices
from etf_rotation.signals import cache

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))   # scripts 不是包
from collect_runs import family_summary  # noqa: E402
KEYS = ("ann_return", "max_drawdown", "sharpe", "calmar")
COSTS = [0, 8, 16, 24]          # 单边成本 bp（0 为理论上限，用来量出成本拖累）


def main() -> None:
    """复用权重扫 4 档成本：每档一个 run + family 成员，最后写 summary 兼容镜像。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-07-31")
    ap.add_argument("--execution", choices=["close", "open"], default="open")
    ap.add_argument("--save-profile", choices=list(artifacts.SAVE_PROFILES),
                    default="minimal")
    ap.add_argument("--campaign", default="")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    base = config.load_params()
    cash_rate = base["costs"]["cash_rate_annual"]
    weights_path = ROOT / "reports" / "weights.parquet"
    if weights_path.exists():
        weights = pd.read_parquet(weights_path)      # 基准回测已生成，直接复用
    else:
        weights = build_weights(base, args.start, args.end)
    close, opn, _ = load_prices()
    close = close.reindex(index=weights.index, columns=weights.columns)
    opn = opn.reindex(index=weights.index, columns=weights.columns)
    eff = shift_weights.shift_weights(weights)  # T 日信号，T+1 生效（与基准一致）

    gsha, dirty_hash = registry.git_info()
    data_snap = snapshot.data_snapshot_id()
    base_flat = config.flatten_params(base)
    base_flat.pop("costs.one_side_bps", None)
    base_flat["_start"], base_flat["_end"] = args.start, args.end
    grid = {"costs.one_side_bps": COSTS}

    def run_one(point: dict) -> tuple[dict, dict, dict]:
        """单档成本：只重跑 bt 记账（不重建权重），这是本脚本快的原因。"""
        cost = float(point["costs.one_side_bps"])
        p = copy.deepcopy(base)
        config.set_nested(p, "costs.one_side_bps", str(point["costs.one_side_bps"]))
        r = run.run(eff, opn, close, cost_bps=cost, cash_rate=cash_rate,
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
        points=sweep.iter_points(grid), run_one=run_one, kind="cost",
        profile=args.save_profile, campaign_id=args.campaign, tag=args.tag,
        runs_root=ROOT / "reports" / "runs",
        families_root=ROOT / "reports" / "families",
        git_sha=gsha, data_snapshot_id=data_snap,
        start=args.start, end=args.end, execution=args.execution,
        spec=grid, base_params=base_flat,
    )

    # scripts/collect_runs.py 与 run_grid 共享同一份汇总逻辑（单进程）
    summary = family_summary(ROOT / "reports" / "families",
                             ROOT / "reports" / "runs", out["family_id"])

    rows = []
    for row in summary["results"]:
        rows.append({
            "cost_bps": row.get("costs.one_side_bps"),
            **{key: row.get(key) for key in KEYS},
            "turnover": row.get("turnover"),
        })
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    (ROOT / "reports/sensitivity.json").write_text(
        json.dumps(sweep.jsonable({
            "cost_sensitivity": rows,
            "dsr_cost_variants": summary["dsr_family"],
            "family_id": out["family_id"],
            "generated": True,
        }), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(f"DSR over cost variants: {summary['dsr_family']}")
    print(f"family {out['family_id']} -> reports/families/{out['family_id']}/summary.json")


if __name__ == "__main__":
    main()
