"""Hydra 驱动的单参数网格回测（multirun 并行）。用法：

.venv\\Scripts\\python.exe scripts\\run_grid_hydra.py -m \\
    param_key=dedupe.corr_threshold param_value=0.75,0.80,0.85
"""
from __future__ import annotations

import json
from pathlib import Path

import hydra
from omegaconf import DictConfig

from etf_rotation.execution import shift_weights
from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.data import snapshot
from etf_rotation.evaluation import metrics, registry
from etf_rotation.pipeline import build_weights, load_context

ROOT = Path(__file__).resolve().parents[1]


def _run_one(p: dict, start: str, end: str, execution: str, ctx: dict) -> dict:
    """单组参数：建权 → bt 记账 → 登记 registry → 返回指标。"""
    weights = build_weights(p, start, end, context=ctx)
    close = ctx["close"].reindex(index=weights.index, columns=weights.columns)
    opn = ctx["opn"].reindex(index=weights.index, columns=weights.columns)
    eff = shift_weights.shift_weights(weights)
    r = run.run(eff, opn, close, cost_bps=p["costs"]["one_side_bps"],
                cash_rate=p["costs"]["cash_rate_annual"], execution=execution)
    s = metrics.from_stats(r.stats)
    s["turnover"] = float(r.turnover.mean())
    s["total_fees"] = float(r.fees.sum())
    flat = config.flatten_params(p)
    flat["_start"], flat["_end"] = start, end
    data_snap = snapshot.data_snapshot_id()
    gsha = registry.git_sha()
    run_id = registry.run_identity(flat, git_sha=gsha, data_snapshot_id=data_snap,
                                   execution=execution, signal_version=gsha)
    registry.register_run(
        ROOT / "data" / "warehouse.duckdb", run_id, flat, s, {},
        data_snapshot_id=data_snap, git_sha=gsha, execution=execution,
    )
    return s


@hydra.main(version_base=None, config_path="../config/hydra", config_name="grid")
def main(cfg: DictConfig) -> None:
    """Hydra 驱动的单参数网格回测（multirun 并行，一次只变一个维度）。

    用法：
        .venv\\Scripts\\python.exe scripts\\run_grid_hydra.py -m \\
            param_key=dedupe.corr_threshold param_value=0.75,0.80,0.85

    与 run_grid.py 的分工：
      run_grid.py       —— 进程内串行扫网格，输出稳健性分数/悬崖/DSR 汇总
      run_grid_hydra.py —— Hydra multirun 并行，每个变体一个进程，
                           通过 registry 落库，适合大网格
    本函数只负责「把 Hydra 的一组配置翻译成一次单变体回测」，
    网格展开与并行调度由 Hydra 的 -m 语法负责。
    """
    # 以默认参数为底，只覆写本次 multirun 指定的那一个参数
    p = config.load_params()
    config.set_nested(p, cfg.param_key, str(cfg.param_value))
    ctx = load_context()
    s = _run_one(p, cfg.start, cfg.end, cfg.execution, ctx)
    # 打印精简结果（完整指标已登记到 warehouse 的 runs 表）
    print(json.dumps({"param_key": cfg.param_key, "param_value": cfg.param_value,
                      "ann_return": s["ann_return"], "sharpe": s["sharpe"],
                      "max_drawdown": s["max_drawdown"], "calmar": s["calmar"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
