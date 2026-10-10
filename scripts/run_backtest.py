"""运行基准回测并输出绩效指标。用法：python scripts/run_backtest.py [START] [END]"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.evaluation import metrics
from etf_rotation.pipeline import build_weights, load_prices

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    p = config.load_params()
    start = sys.argv[1] if len(sys.argv) > 1 else "2019-01-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2026-07-31"
    print(f"building weights {start}..{end}")
    weights = build_weights(p, start, end)
    close, opn, _ = load_prices()
    close = close.reindex(index=weights.index, columns=weights.columns)
    opn = opn.reindex(index=weights.index, columns=weights.columns)
    eff = weights.shift(1).fillna(0.0)  # T 日信号，T+1 生效
    res = run.run(eff, opn, close,
                  cost_bps=p["costs"]["one_side_bps"],
                  cash_rate=p["costs"]["cash_rate_annual"])
    s = metrics.summary(res["returns"])
    s["turnover"] = float(eff.diff().abs().sum(axis=1).mean())
    print(json.dumps({k: (round(v, 6) if isinstance(v, float) else v) for k, v in s.items()},
                     ensure_ascii=False, indent=2))
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    res.to_csv(out / "equity.csv")
    weights.to_parquet(out / "weights.parquet")
    (out / "metrics.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved to {out}")


if __name__ == "__main__":
    main()

