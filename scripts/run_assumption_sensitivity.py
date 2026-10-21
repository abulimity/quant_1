"""假设敏感性网格（H1/H3/H4/H5/H7 标量假设）：每个变体建权 → 回测 → 登记 registry。"""
from __future__ import annotations

import json
from pathlib import Path

from etf_rotation.execution import shift_weights
from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.data import snapshot
from etf_rotation.evaluation import metrics, overfitting, registry
from etf_rotation.pipeline import build_weights, load_context

ROOT = Path(__file__).resolve().parents[1]
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


def _run_one(p, start, end, execution, ctx):
    """跑一组假设变体并登记 run，返回 (指标, 回测窗口内日收益样本数)。

    返回第二个值 n_obs 的原因：DSR 的标准误 sr_se = √(1/(T−1)) 依赖观测数 T，
    而 T 只能从实际跑出来的收益序列长度得到（回测窗口内的有效交易日数），
    不能用「一年 252 天 × 年数」粗算，否则停牌/节假日会让 T 偏大、DSR 偏乐观。
    """
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
        data_snapshot_id=data_snap, git_sha=gsha, execution=execution)
    return s, int(r.returns.notna().sum())


def main() -> None:
    """假设敏感性网格（H1/H3/H4/H5/H7 标量假设）：每个变体建权 → 回测 → 登记 registry。

    对每个假设参数逐一取候选值，其余参数保持默认，一次只动一个维度
    （AGENTS.md 纪律：一次只动一个维度，避免多参数同时调整导致归因困难）。

    输出：reports/assumption_sensitivity.json，含每个假设的逐值指标，
    以及跨全部变体的 DSR 与 Sharpe 扣除上限（多重检验校正）。
    """
    start, end = "2019-01-01", "2026-07-31"
    ctx = load_context()          # 数据面板只加载一次，所有变体共用
    out = {}
    all_sharpes = []              # 收集全部变体的年化 Sharpe，供 DSR / haircut 使用
    n_obs = 0
    for key, values in ASSUMPTIONS.items():
        rows = []
        for v in values:
            # 每个变体都从干净参数重新开始，再覆写一个假设值
            p = config.load_params()
            config.set_nested(p, key, str(v))
            s, n_obs = _run_one(p, start, end, "open", ctx)
            all_sharpes.append(s["sharpe"])
            rows.append({"value": v, **{k: s[k] for k in KEYS}})
        out[key] = rows
        print(json.dumps({key: rows}, ensure_ascii=False, indent=2))
    # 18 个变体的多重检验校正（DSR 与 Sharpe 扣除上限，观测数 = 回测窗口日收益样本数）
    out["dsr"] = overfitting.deflated_sharpe(all_sharpes, len(all_sharpes), n_obs)
    out["sharpe_haircut"] = overfitting.sharpe_haircut(all_sharpes)
    (ROOT / "reports" / "assumption_sensitivity.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved reports/assumption_sensitivity.json")


if __name__ == "__main__":
    main()
