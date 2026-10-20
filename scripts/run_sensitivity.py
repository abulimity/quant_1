"""成本与现金假设敏感性（复用已生成的权重，快速）。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from etf_rotation.execution import shift_weights
from etf_rotation.backtest import run
from etf_rotation.evaluation import metrics, overfitting
from etf_rotation.pipeline import load_prices

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """成本敏感性：复用 run_backtest 生成的权重，快速扫 4 档单边成本。

    只重跑 bt 记账（不重建权重），因此很快；DSR 仅对 4 个高度相关的成本
    变体计算，报告里注明「仅作参考不作结论」。
    """
    weights = pd.read_parquet(ROOT / "reports/weights.parquet")
    close, opn, _ = load_prices()
    close = close.reindex(index=weights.index, columns=weights.columns)
    opn = opn.reindex(index=weights.index, columns=weights.columns)
    eff = shift_weights.shift_weights(weights)  # T 日信号，T+1 生效（与基准回测一致）
    rows = []
    sharpes = []
    for cost in [0, 8, 16, 24]:  # 单边成本 0/8/16/24bp
        r = run.run(eff, opn, close, cost_bps=cost, cash_rate=0.018)
        s = metrics.from_stats(r.stats)
        sharpes.append(s["sharpe"])
        rows.append({"cost_bps": cost, "ann_return": s["ann_return"],
                     "max_drawdown": s["max_drawdown"], "sharpe": s["sharpe"],
                     "calmar": s["calmar"]})
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    dsr = overfitting.deflated_sharpe(sharpes, len(sharpes))
    print(f"DSR over cost variants: {dsr:.3f}")
    (ROOT / "reports/sensitivity.json").write_text(
        json.dumps({"cost_sensitivity": rows, "dsr_cost_variants": dsr},
                   ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

