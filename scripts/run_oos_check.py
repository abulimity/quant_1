"""样本外子区间复核（open 口径）：2019–2023 vs 2024–2026。

用法：scripts/run_oos_check.py --param trend.weighting=exp [--param a.b=v ...]

方法：在**全窗口**（2019→2026）一次性建权（保证 warmup `i>=170`/`i>=60`、五相位、
整组迟滞等状态都以 2019 起点为准、不因子区间边界重置），再对「已 shift(1) 的有效权重」
按子区间切片跑 bt。切勿对子区间独立 `build_weights`：其循环用相对索引 `i`，会把 2024
边界当作起点，导致 2024 前 ~170 日无风险仓（见 test 与审查结论）。

落盘：每个子区间一个 run（kind="oos"），同一 family；最后写
`reports/oos_check.json` 兼容镜像。
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

KEYS = ("ann_return", "max_drawdown", "sharpe", "calmar")
FULL_START, FULL_END = "2019-01-01", "2026-07-31"
SUBPERIODS = [
    ("2019-2023", "2019-01-01", "2023-12-31"),
    ("2024-2026", "2024-01-01", "2026-07-31"),
]


def main() -> None:
    """全窗口建权 → 按子区间切片回测；每个子区间一个 run。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--param", action="append", default=[],
                    help="参数覆写 a.b=c（写后即做 schema 校验）")
    ap.add_argument("--execution", choices=["close", "open"], default="open")
    ap.add_argument("--save-profile", choices=list(artifacts.SAVE_PROFILES),
                    default="minimal")
    ap.add_argument("--campaign", default="")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    # 逐条应用 --param a.b=c 覆写（写后即做 schema 校验）
    p = config.load_params()
    for kv in args.param:
        k, v = kv.split("=", 1)
        config.set_nested(p, k, v)

    ctx = load_context()
    # 全窗口建权（warmup、五相位、迟滞状态都以 2019 起点为准）
    weights = build_weights(p, FULL_START, FULL_END, context=ctx)
    eff = shift_weights.shift_weights(weights)  # T 日信号、T+1 生效

    gsha, dirty_hash = registry.git_info()
    data_snap = snapshot.data_snapshot_id()
    base_flat = config.flatten_params(p)
    base_flat["_start"], base_flat["_end"] = FULL_START, FULL_END
    points = [{"label": label, "start": start, "end": end}
              for label, start, end in SUBPERIODS]

    def run_one(point: dict) -> tuple[dict, dict, dict]:
        """子区间切片回测（eff 已是有效权重，不再二次 shift）。"""
        start, end = point["start"], point["end"]
        sub = eff.loc[start:end]
        close = ctx["close"].reindex(index=sub.index, columns=sub.columns)
        opn = ctx["opn"].reindex(index=sub.index, columns=sub.columns)
        r = run.run(sub, opn, close, cost_bps=p["costs"]["one_side_bps"],
                    cash_rate=p["costs"]["cash_rate_annual"],
                    execution=args.execution,
                    gap_delay_pct=p["execution"]["gap_delay_pct"])
        s = metrics.all_stats(r.stats)
        s["turnover"] = float(r.turnover.mean())
        s["total_fees"] = float(r.fees.sum())

        flat = copy.deepcopy(base_flat)
        flat["_start"], flat["_end"] = start, end   # 子区间进入身份，避免两点撞 id
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
            "start": start,
            "end": end,
            "n_obs": int(r.returns.notna().sum()),
        }
        frames = {
            "equity": metrics.build_equity_frame(r.nav, r.returns, r.cash,
                                                 r.turnover, r.fees),
            "weights": sub,
            "holdings": r.positions,
        }
        return meta, s, frames

    out = sweep.run_sweep(
        points=points, run_one=run_one, kind="oos",
        profile=args.save_profile, campaign_id=args.campaign, tag=args.tag,
        runs_root=ROOT / "reports" / "runs",
        families_root=ROOT / "reports" / "families",
        git_sha=gsha, data_snapshot_id=data_snap,
        start=FULL_START, end=FULL_END, execution=args.execution,
        spec={"subperiod": [label for label, _, _ in SUBPERIODS]},
        base_params=base_flat, dirty_hash=dirty_hash,
    )
    summary = family_summary(ROOT / "reports" / "families",
                             ROOT / "reports" / "runs", out["family_id"])

    subperiods = {}
    for row in summary["results"]:
        subperiods[row["label"]] = {key: row.get(key) for key in KEYS}
    payload = {
        "param_overrides": args.param,
        "subperiods": subperiods,
        "family_id": out["family_id"],
        "generated": True,
    }
    (ROOT / "reports" / "oos_check.json").write_text(
        json.dumps(sweep.jsonable(payload), ensure_ascii=False, indent=2,
                   allow_nan=False), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
