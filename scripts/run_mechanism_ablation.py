"""机制开关对照（ablation）：逐项关闭一个机制，观察边际增量。

每个变体一个 run（kind="ablation"）+ 一条 family 成员；baseline 与 5 个
「关闭一个机制」共 6 个 trial。最后写 `reports/ablation.json` 兼容镜像
（旧读法：行列表，每行 mechanism + 指标）。
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
from etf_rotation.evaluation import artifacts, metrics, registry, sweep
from etf_rotation.pipeline import build_weights, load_context
from etf_rotation.signals import cache

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))   # scripts 不是包
from collect_runs import family_summary  # noqa: E402

MECHANISMS = ["phases", "hysteresis", "reversal", "overheat", "vol_cap"]
KEYS = ("ann_return", "max_drawdown", "sharpe", "calmar", "turnover")
BASELINE = "baseline(all-on)"


def main() -> None:
    """baseline（全开）+ 逐项关闭一个机制，其余保持默认。"""
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
    ctx = load_context()          # 数据面板只加载一次，所有变体共用
    gsha, dirty_hash = registry.git_info()
    data_snap = snapshot.data_snapshot_id()

    points = [{"mechanism": BASELINE}, *({"mechanism": f"{m}=off"} for m in MECHANISMS)]
    base_flat = config.flatten_params(base)
    base_flat["_start"], base_flat["_end"] = args.start, args.end

    def run_one(point: dict) -> tuple[dict, dict, dict]:
        """单变体：baseline 全开；其余把对应机制置为 False 后跑完整链路。"""
        p = copy.deepcopy(base)
        label = point["mechanism"]
        if label != BASELINE:
            mechanism = label.split("=", 1)[0]
            config.set_nested(p, f"mechanisms.{mechanism}", "false")
        weights = build_weights(p, args.start, args.end, context=ctx)
        close = ctx["close"].reindex(index=weights.index, columns=weights.columns)
        opn = ctx["opn"].reindex(index=weights.index, columns=weights.columns)
        eff = shift_weights.shift_weights(weights)
        r = run.run(eff, opn, close, cost_bps=p["costs"]["one_side_bps"],
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
        points=points, run_one=run_one, kind="ablation",
        profile=args.save_profile, campaign_id=args.campaign, tag=args.tag,
        runs_root=ROOT / "reports" / "runs",
        families_root=ROOT / "reports" / "families",
        git_sha=gsha, data_snapshot_id=data_snap,
        start=args.start, end=args.end, execution=args.execution,
        spec={"mechanisms": MECHANISMS}, base_params=base_flat,
    )
    summary = family_summary(ROOT / "reports" / "families",
                             ROOT / "reports" / "runs", out["family_id"])

    rows = [{"mechanism": row.get("mechanism"),
             **{key: row.get(key) for key in KEYS}}
            for row in summary["results"]]
    (ROOT / "reports" / "ablation.json").write_text(
        json.dumps(sweep.jsonable(rows), ensure_ascii=False, indent=2,
                   allow_nan=False), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"family {out['family_id']} -> reports/families/{out['family_id']}/summary.json")


if __name__ == "__main__":
    main()
