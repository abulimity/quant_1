"""资产类别/区间收益归因：把组合收益拆到风险/纳指/黄金/防守 + 分年度。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from etf_rotation import config
from etf_rotation.data import universe as univ
from etf_rotation.evaluation import attribution
from etf_rotation.pipeline import load_fund_basic, load_prices

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def main() -> None:
    p = config.load_params()
    weights = pd.read_parquet(REPORTS / "weights.parquet")
    close, _, _ = load_prices()
    close = close.reindex(index=weights.index, columns=weights.columns)
    fb = load_fund_basic()
    cat = univ.classify(fb)
    nasdaq, gold = p["nasdaq_etf"], p["gold_etf"]
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

    contrib = attribution.asset_class_contributions(weights, close, classification)
    equity = pd.read_csv(REPORTS / "equity.csv", parse_dates=["ts"]).set_index("ts")
    annual = attribution.period_contributions(equity["returns"])

    out = {
        "class_contribution": contrib.sum().to_dict(),
        "annual_returns": {str(y): float(v) for y, v in annual.items()},
    }
    (REPORTS / "attribution.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
