"""集中度/暴露分析：HHI、有效持仓数、资产类暴露，落盘 run 的 analysis/exposure.json。

用法：
    python scripts/run_exposure.py                 # 取 reports/latest.json 指向的 run
    python scripts/run_exposure.py --run-id 1a2b3c4d5e6f

输出：`reports/runs/{run_id}/analysis/exposure.json`（run 内），
同时覆盖 `reports/exposure.json` 顶层镜像，保持既有报告链接有效。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from etf_rotation import config
from etf_rotation.data import universe as univ
from etf_rotation.evaluation import artifacts, exposure
from etf_rotation.pipeline import load_fund_basic
from etf_rotation.report.serialize import clean

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
RUNS = REPORTS / "runs"


def main() -> None:
    """集中度与暴露分析，落盘 run 的 analysis/exposure.json。

    步骤：
      ① 定位 run（--run-id 或 reports/latest.json），读 weights.parquet（目标权重面板）
      ② 映射展示用资产类别（纳指/黄金/防守/风险）
      ③ 逐日集中度：HHI = Σw_i²、有效持仓数 N_eff = 1/HHI
      ④ 逐日资产类暴露：exposure_{c,t} = Σ_{i∈c} w_{i,t}

    输出含义：
      hhi_mean / effective_n_mean —— 平均集中度（越小越分散）
      hhi_max / effective_n_min    —— 最极端的单日集中度（风险提示）
      asset_class_exposure_mean     —— 全期各类资产的平均权重占比
    """
    parser = argparse.ArgumentParser(description="集中度与资产类暴露分析")
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
    fb = load_fund_basic()
    cat = univ.classify(fb)
    nasdaq, gold = p["nasdaq_etf"], p["gold_etf"]
    # 展示用资产类别映射（与 run_attribution.py 保持同一套口径，便于交叉核对）
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

    # 逐日 HHI 与有效持仓数
    conc = exposure.concentration_series(weights)
    # 逐日资产类暴露
    cls_expo = exposure.asset_class_exposure(weights, classification)

    out = clean({
        "hhi_mean": float(conc["hhi"].mean()),
        "effective_n_mean": float(conc["effective_n"].mean()),
        "hhi_max": float(conc["hhi"].max()),
        "effective_n_min": float(conc["effective_n"].min()),
        "asset_class_exposure_mean": {c: float(cls_expo[c].mean()) for c in cls_expo.columns},
    })
    payload = json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False)
    # 先写 run（可回溯到具体 run_id），再镜像到顶层（旧链接继续可用）
    analysis = run_dir / "analysis"
    analysis.mkdir(exist_ok=True)
    (analysis / "exposure.json").write_text(payload, encoding="utf-8")
    (REPORTS / "exposure.json").write_text(payload, encoding="utf-8")
    print(f"run_id: {run_dir.name}")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"写盘 {analysis / 'exposure.json'}（镜像 {REPORTS / 'exposure.json'}）")


if __name__ == "__main__":
    main()
