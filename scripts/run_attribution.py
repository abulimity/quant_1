"""资产类别/区间收益归因：把组合收益拆到风险/纳指/黄金/防守 + 分年度。

用法：
    python scripts/run_attribution.py                 # 取 reports/latest.json 指向的 run
    python scripts/run_attribution.py --run-id 1a2b3c4d5e6f

输出：`reports/runs/{run_id}/analysis/attribution.json`（run 内），
同时覆盖 `reports/attribution.json` 顶层镜像，保持既有报告链接有效。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from etf_rotation import config
from etf_rotation.data import universe as univ
from etf_rotation.evaluation import artifacts, attribution
from etf_rotation.pipeline import load_fund_basic, load_prices
from etf_rotation.report.serialize import clean

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
RUNS = REPORTS / "runs"


def main() -> None:
    """资产类别收益归因 + 分年度收益，落盘 run 的 analysis/attribution.json。

    步骤：
      ① 定位 run（--run-id 或 reports/latest.json），读 weights.parquet（目标权重面板）
      ② 读收盘价并裁到权重面板的行列
      ③ 把每个标的映射到展示用资产类别（纳指/黄金/防守/风险）
      ④ 逐日归因：contrib_{c,t} = Σ_{i∈c} w_{i,t−1}·r_{i,t}（权重 shift(1)，T 日持仓 × T+1 收益）
      ⑤ 分年度累计收益：R_y = Π(1+r) − 1

    注意：第 ④ 步只归因「持仓期收益」，不含现金利息，
    故各类别贡献之和 ≈ 组合日收益之和（利息部分为差额）。
    """
    parser = argparse.ArgumentParser(description="资产类别/区间收益归因")
    parser.add_argument("--run-id", default=None,
                        help="指定 run_id（默认读 reports/latest.json）")
    args = parser.parse_args()

    try:
        run_dir = artifacts.resolve_run(RUNS, args.run_id)
    except FileNotFoundError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)

    p = config.load_params()
    weights = pd.read_parquet(run_dir / "weights.parquet")
    close, _, _ = load_prices()
    close = close.reindex(index=weights.index, columns=weights.columns)
    fb = load_fund_basic()
    cat = univ.classify(fb)
    nasdaq, gold = p["nasdaq_etf"], p["gold_etf"]
    # 展示用资产类别映射：纳指/黄金优先（它们同时也是 risk 类 ETF），
    # 其次债券/货币 → 防守，其余 → 风险
    classification = {}
    for t in weights.columns:
        if t == nasdaq:
            classification[t] = "纳指"
        elif t == gold:
            classification[t] = "黄金"
        elif cat.get(t) in ("bond", "money"):
            classification[t] = "防守"
        else:
            classification[t] = "风险"

    # 逐日收益贡献拆到资产类别（权重取 T 日，收益取 T+1）
    contrib = attribution.asset_class_contributions(weights, close, classification)
    equity = pd.read_parquet(run_dir / "equity.parquet")
    # 分年度几何复合收益
    annual = attribution.period_contributions(equity["returns"])

    out = clean({
        # 全期各类别的累计贡献（按类别汇总逐日贡献）
        "class_contribution": contrib.sum().to_dict(),
        "annual_returns": {str(y): float(v) for y, v in annual.items()},
    })
    payload = json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False)
    # 先写 run（可回溯到具体 run_id），再镜像到顶层（旧链接继续可用）
    analysis = run_dir / "analysis"
    analysis.mkdir(exist_ok=True)
    (analysis / "attribution.json").write_text(payload, encoding="utf-8")
    (REPORTS / "attribution.json").write_text(payload, encoding="utf-8")
    print(f"run_id: {run_dir.name}")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"写盘 {analysis / 'attribution.json'}（镜像 {REPORTS / 'attribution.json'}）")


if __name__ == "__main__":
    main()
