"""Hydra 驱动的单参数网格回测（multirun 并行）。用法：

    .venv\\Scripts\\python.exe scripts\\run_grid_hydra.py -m \\
        param_key=dedupe.corr_threshold param_value=0.75,0.80,0.85

与 run_grid.py 的分工：
  run_grid.py       —— 进程内串行扫网格，结束后生成 family summary
  run_grid_hydra.py —— Hydra multirun 并行，每个变体一个进程；
                       worker 只 `store_run` + 写成员 JSON，绝不写共享汇总。
                       family_id 由 cfg 的 param_key/候选值/窗口/口径确定性算出，
                       因此同一 multirun 的所有 worker 得到同一个 id。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import hydra
from omegaconf import DictConfig

from etf_rotation.execution import shift_weights
from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.data import snapshot
from etf_rotation.evaluation import artifacts, metrics, registry, sweep
from etf_rotation.pipeline import build_weights, load_context
from etf_rotation.signals import cache

ROOT = Path(__file__).resolve().parents[1]


def _sweep_values(fallback) -> list:
    """从 multirun 的原始 argv 里取出 `param_value` 的完整候选列表。

    Hydra 给每个 job 的 cfg 只留一个 value，但 `sys.argv` 仍保留 `-m ...
    param_value=v1,v2` 原样（已实测 1.3.7）。用整份候选列表算 family_id，
    worker 之间无需通信，也无需写任何共享文件。
    """
    argv = sys.argv
    if "-m" in argv or "--multirun" in argv:
        for arg in argv:
            token = arg.lstrip("+")
            if token.startswith("-") or "=" not in token:
                continue
            name, raw = token.split("=", 1)
            if name == "param_value":       # config/hydra/grid.yaml 的候选值字段
                # 与 config.set_nested 相同的类型推断，保证和 run_grid 的 spec 一致
                return [config._coerce(value) for value in raw.split(",")]  # noqa: SLF001
    return [fallback]


def _run_one(p: dict, cfg: DictConfig, ctx: dict, *, gsha: str, dirty_hash: str,
             data_snap: str, campaign: str, tag: str, profile: str,
             fid: str, values: list) -> dict:
    """单组参数：建权 → bt 记账 → store_run → 写 family 成员（不写 summary）。"""
    start, end, execution = cfg.start, cfg.end, cfg.execution
    weights = build_weights(p, start, end, context=ctx)
    close = ctx["close"].reindex(index=weights.index, columns=weights.columns)
    opn = ctx["opn"].reindex(index=weights.index, columns=weights.columns)
    eff = shift_weights.shift_weights(weights)
    r = run.run(eff, opn, close, cost_bps=p["costs"]["one_side_bps"],
                cash_rate=p["costs"]["cash_rate_annual"], execution=execution,
                gap_delay_pct=p["execution"]["gap_delay_pct"])
    s = metrics.all_stats(r.stats)
    s["turnover"] = float(r.turnover.mean())
    s["total_fees"] = float(r.fees.sum())
    clean_metrics, dropped = sweep.finite_metrics(s)

    flat = config.flatten_params(p)
    flat["_start"], flat["_end"] = start, end
    sig_id = cache.signal_id(flat, data_snap)
    run_id = registry.run_identity(
        flat, git_sha=gsha, dirty_hash=dirty_hash, data_snapshot_id=data_snap,
        execution=execution, signal_id=sig_id)
    variant = {cfg.param_key: cfg.param_value}
    meta = {
        "schema_version": 2,
        "params_json": flat,
        "signal_id": sig_id,
        "git_sha": gsha,
        "git_dirty": bool(dirty_hash),
        "dirty_hash": dirty_hash,
        "env_lock_hash": registry.env_lock_hash(),
        "data_snapshot_id": data_snap,
        "execution": execution,
        "start": start,
        "end": end,
        "n_obs": int(r.returns.notna().sum()),
        "kind": "grid",
        "family_id": fid,
        "campaign_id": campaign,
        "tag": tag,
        "variant": variant,
    }
    if dropped:
        meta["nonfinite_metrics"] = dropped
    frames = {
        "equity": metrics.build_equity_frame(r.nav, r.returns, r.cash,
                                             r.turnover, r.fees),
        "weights": weights,
        "holdings": r.positions,
    }
    artifacts.store_run(root=ROOT / "reports" / "runs", run_id=run_id, kind="grid",
                        profile=profile, meta=meta, metrics=clean_metrics, frames=frames)
    registry.write_family_member(
        ROOT / "reports" / "families", fid, run_id, variant=variant,
        campaign_id=campaign,
        family={"kind": "grid", "spec": {cfg.param_key: values},
                "start": start, "end": end, "execution": execution,
                "git_sha": gsha, "data_snapshot_id": data_snap,
                "campaign_id": campaign,
                "git_dirty": bool(dirty_hash), "dirty_hash": dirty_hash},
    )
    return {"run_id": run_id, "family_id": fid, **{k: s[k] for k in
            ("ann_return", "sharpe", "max_drawdown", "calmar")}}


@hydra.main(version_base=None, config_path="../config/hydra", config_name="grid")
def main(cfg: DictConfig) -> None:
    """把 Hydra 的一组配置翻译成一次单变体回测（网格展开由 Hydra 负责）。"""
    campaign = str(cfg.get("campaign", ""))
    tag = str(cfg.get("tag", ""))
    profile = str(cfg.get("save_profile", "minimal"))
    p = config.load_params()
    config.set_nested(p, cfg.param_key, str(cfg.param_value))
    ctx = load_context()

    gsha, dirty_hash = registry.git_info()
    data_snap = snapshot.data_snapshot_id()
    values = _sweep_values(cfg.param_value)

    # 与 run_grid.py 同一口径：未参与网格的默认参数 + 窗口进入 family 身份
    base_flat = config.flatten_params(config.load_params())
    base_flat.pop(cfg.param_key, None)
    base_flat["_start"], base_flat["_end"] = cfg.start, cfg.end
    fid = registry.family_id("grid", {cfg.param_key: values}, base_flat,
                             cfg.start, cfg.end, cfg.execution,
                             gsha, data_snap, campaign)

    result = _run_one(p, cfg, ctx, gsha=gsha, dirty_hash=dirty_hash,
                      data_snap=data_snap, campaign=campaign, tag=tag,
                      profile=profile, fid=fid, values=values)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"family {fid}: 汇总请在所有 worker 结束后运行 "
          f"scripts/collect_runs.py --family {fid}")


if __name__ == "__main__":
    main()
