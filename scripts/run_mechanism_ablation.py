"""机制开关对照（ablation）：逐项关闭一个机制，登记结果，观察边际增量。"""
from __future__ import annotations

import json
from pathlib import Path

from etf_rotation.execution import shift_weights
from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.data import snapshot
from etf_rotation.evaluation import metrics, registry
from etf_rotation.pipeline import build_weights, load_context

ROOT = Path(__file__).resolve().parents[1]
MECHANISMS = ["phases", "hysteresis", "reversal", "overheat", "vol_cap"]
KEYS = ("ann_return", "max_drawdown", "sharpe", "calmar", "turnover")


def _run(p, start, end, ctx):
    """跑一组参数并登记 run，返回该组的绩效指标字典。

    步骤（每个 ablation 变体都走同一条路径，保证可比）：
      ① 按参数 p 建目标权重面板（build_weights）
      ② 把价格面板裁到权重面板的行列（reindex），避免多出无持仓的标的
      ③ 权重整体 shift(1)：T 日信号、T+1 生效（与基准回测完全一致）
      ④ bt 记账：open 口径成交 + 收盘估值，成本/现金利率取自参数
      ⑤ 提取指标：ffn 统计 + 平均换手率
      ⑥ 内容寻址登记：run_id = f(参数, git_sha, 数据快照, 执行口径)
    """
    weights = build_weights(p, start, end, context=ctx)
    close = ctx["close"].reindex(index=weights.index, columns=weights.columns)
    opn = ctx["opn"].reindex(index=weights.index, columns=weights.columns)
    eff = shift_weights.shift_weights(weights)
    r = run.run(eff, opn, close, cost_bps=p["costs"]["one_side_bps"],
                cash_rate=p["costs"]["cash_rate_annual"], execution="open")
    s = metrics.from_stats(r.stats)
    s["turnover"] = float(r.turnover.mean())
    flat = config.flatten_params(p)
    flat["_start"], flat["_end"] = start, end
    data_snap = snapshot.data_snapshot_id()
    gsha = registry.git_sha()
    run_id = registry.run_identity(flat, git_sha=gsha, data_snapshot_id=data_snap,
                                   execution="open", signal_version=gsha)
    registry.register_run(
        ROOT / "data" / "warehouse.duckdb", run_id, flat, s, {},
        data_snapshot_id=data_snap, git_sha=gsha, execution="open")
    return s


def main() -> None:
    """机制开关对照（ablation）：逐项关闭一个机制，登记结果，观察边际增量。

    对照设计：先跑 baseline（全部机制开启），再逐个把某个机制置为 False，
    其余保持默认。每行与 baseline 的差值就是该机制的「边际贡献」。

    输出：reports/ablation.json（每行含 ann_return / max_drawdown / sharpe /
    calmar / turnover），并同步登记到 warehouse 的 runs 表。
    """
    start, end = "2019-01-01", "2026-07-31"
    ctx = load_context()          # 数据面板只加载一次，所有变体共用
    rows = []
    # baseline：所有机制开启
    s = _run(config.load_params(), start, end, ctx)
    rows.append({"mechanism": "baseline(all-on)", **{k: s[k] for k in KEYS}})
    for m in MECHANISMS:
        # 逐项关闭一个机制（其余保持默认），观察该机制的边际增量
        p = config.load_params()
        p["mechanisms"][m] = False
        s = _run(p, start, end, ctx)
        rows.append({"mechanism": f"{m}=off", **{k: s[k] for k in KEYS}})
    (ROOT / "reports" / "ablation.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
