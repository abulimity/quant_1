"""集中度/暴露分析：HHI、有效持仓数、资产类暴露，落盘 reports/exposure.json。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from etf_rotation import config
from etf_rotation.data import universe as univ
from etf_rotation.evaluation import exposure
from etf_rotation.pipeline import load_fund_basic

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def main() -> None:
    p = config.load_params()
    weights = pd.read_parquet(REPORTS / "weights.parquet")
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

    conc = exposure.concentration_series(weights)
    cls_expo = exposure.asset_class_exposure(weights, classification)

    out = {
        "hhi_mean": float(conc["hhi"].mean()),
        "effective_n_mean": float(conc["effective_n"].mean()),
        "hhi_max": float(conc["hhi"].max()),
        "effective_n_min": float(conc["effective_n"].min()),
        "asset_class_exposure_mean": {c: float(cls_expo[c].mean()) for c in cls_expo.columns},
    }
    (REPORTS / "exposure.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
