"""运行基准回测并输出绩效指标。用法：python scripts/run_backtest.py [START] [END]"""
from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import pandas as pd

from etf_rotation import __version__, config
from etf_rotation.backtest import run
from etf_rotation.data import snapshot
from etf_rotation.evaluation import metrics, registry
from etf_rotation.pipeline import build_weights, compute_benchmark, load_prices

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """构建目标权重 → 用 bt 记账回测 → 输出绩效并登记 run。

    目标权重代表 T 日收盘后确定的持仓，真正生效在 T+1，因此回测前整体
    .shift(1)；执行价按 T+1 收盘近似（bt 单价格模型，见 backtest/run.py）。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("start", nargs="?", default="2019-01-01")
    parser.add_argument("end", nargs="?", default="2026-07-31")
    parser.add_argument("--param", action="append", default=[])  # 支持 --param a.b.c=value 覆盖参数
    parser.add_argument("--execution", choices=["close", "open"], default="close",
                        help="成交口径：close=收盘成交（bt 标准 Rebalance），open=T+1 开盘成交+跳空顺延")
    args = parser.parse_args()

    p = config.load_params()
    for kv in args.param:
        k, v = kv.split("=", 1)
        config.set_nested(p, k, v)
    start, end = args.start, args.end
    print(f"etf-rotation v{__version__}")
    print(f"building weights {start}..{end}")
    weights = build_weights(p, start, end)
    close, opn, _ = load_prices()
    # 把价格面板对齐到权重面板的交易日与标的列，避免回测时列/索引错位
    close = close.reindex(index=weights.index, columns=weights.columns)
    opn = opn.reindex(index=weights.index, columns=weights.columns)
    eff = weights.shift(1).fillna(0.0)  # T 日信号，T+1 生效
    res = run.run(eff, opn, close,
                  cost_bps=p["costs"]["one_side_bps"],
                  cash_rate=p["costs"]["cash_rate_annual"],
                  execution=args.execution,
                  gap_delay_pct=p["execution"]["gap_delay_pct"])
    s = metrics.from_stats(res.stats)
    s["turnover"] = float(res.turnover.mean())
    s["total_fees"] = float(res.fees.sum())
    print(json.dumps({k: (round(v, 6) if isinstance(v, float) else v) for k, v in s.items()},
                     ensure_ascii=False, indent=2))
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    pd.DataFrame({"nav": res.nav, "returns": res.returns}).to_csv(out / "equity.csv")
    with warnings.catch_warnings():
        # bt 访问 get_transactions/get_weights 会触发 pandas 宽表 PerformanceWarning，仅性能提示，屏蔽
        warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
        res.result.get_transactions().reset_index().to_csv(out / "transactions.csv", index=False)
        res.result.get_weights().to_csv(out / "holdings.csv")
    weights.to_parquet(out / "weights.parquet")
    compute_benchmark(p, start, end).to_csv(out / "benchmark.csv")
    (out / "metrics.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")

    flat = config.flatten_params(p)
    flat["_start"], flat["_end"] = start, end
    data_snap = snapshot.data_snapshot_id()
    gsha = registry.git_sha()
    run_id = registry.run_identity(
        flat, git_sha=gsha, data_snapshot_id=data_snap,
        execution=args.execution, signal_version=gsha,
    )
    registry.register_run(
        ROOT / "data" / "warehouse.duckdb", run_id, flat, s,
        {"equity": str(out / "equity.csv"), "weights": str(out / "weights.parquet"),
         "benchmark": str(out / "benchmark.csv"), "metrics": str(out / "metrics.json")},
        data_snapshot_id=data_snap, git_sha=gsha,
    )
    print(f"registered run {run_id}")
    print(f"saved to {out}")


if __name__ == "__main__":
    main()

