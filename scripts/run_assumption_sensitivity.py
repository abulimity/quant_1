"""假设敏感性网格（H1/H3/H4/H5/H7 标量假设）。

每个变体建权 → 回测 → 一个 run（kind="assumption"）+ 一条 family 成员；
全部变体结束后单进程生成 summary，再写 `reports/assumption_sensitivity.json`
兼容镜像（逐假设结果 + DSR + Sharpe 扣除上限）。
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


def main() -> None:
    """对每个假设参数逐一取候选值，其余保持默认（一次只动一个维度）。"""
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

    # 点序列：一次只变一个维度（18 个变体），不是笛卡尔积
    points = [{key: value} for key, values in ASSUMPTIONS.items() for value in values]

    base_flat = config.flatten_params(base)
    for key in ASSUMPTIONS:
        base_flat.pop(key, None)
    base_flat["_start"], base_flat["_end"] = args.start, args.end

    def run_one(point: dict) -> tuple[dict, dict, dict]:
        """单变体：从干净默认参数出发，覆写一个假设值后跑完整链路。"""
        p = copy.deepcopy(base)
        for key, value in point.items():
            config.set_nested(p, key, str(value))
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
        points=points, run_one=run_one, kind="assumption",
        profile=args.save_profile, campaign_id=args.campaign, tag=args.tag,
        runs_root=ROOT / "reports" / "runs",
        families_root=ROOT / "reports" / "families",
        git_sha=gsha, data_snapshot_id=data_snap,
        start=args.start, end=args.end, execution=args.execution,
        spec=ASSUMPTIONS, base_params=base_flat,
    )
    summary = family_summary(ROOT / "reports" / "families",
                             ROOT / "reports" / "runs", out["family_id"])

    # 兼容旧结构：{假设参数: [{value, 指标...}], "dsr": ..., "sharpe_haircut": ...}
    # 用 trials（点 → run_id）而不是 summary.results：多个假设维度取默认值时，
    # 内容寻址会把它们折叠成同一个 run，但报告仍需逐维度各列一行。
    by_run = {row["run_id"]: row for row in summary["results"]}
    grouped: dict[str, list] = {key: [] for key in ASSUMPTIONS}
    for trial in out["trials"]:
        row = by_run[trial["run_id"]]
        (key, value), = trial["point"].items()
        grouped[key].append({"value": value, **{k: row.get(k) for k in KEYS}})
    payload = {
        **grouped,
        "dsr": summary["dsr_family"],
        "sharpe_haircut": summary["sharpe_haircut"],
        "family_id": out["family_id"],
        "generated": True,
    }
    (ROOT / "reports" / "assumption_sensitivity.json").write_text(
        json.dumps(sweep.jsonable(payload), ensure_ascii=False, indent=2,
                   allow_nan=False), encoding="utf-8")
    print(json.dumps({"family_id": out["family_id"], "n_trials": out["n_trials"],
                      "dsr_family": summary["dsr_family"]},
                     ensure_ascii=False, indent=2))
    print("saved reports/assumption_sensitivity.json")


if __name__ == "__main__":
    main()
