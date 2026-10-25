"""运行基准回测并把产物按 run 落盘。

用法：python scripts/run_backtest.py [START] [END] [--save-profile full]

产物目录：`reports/runs/{run_id}/`（meta/metrics/artifacts + 档位产物），
顶层 `reports/` 下保留兼容副本（equity.csv / weights.parquet / …）供既有脚本读取。
"""
from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import pandas as pd

from etf_rotation.execution import shift_weights
from etf_rotation import __version__, config
from etf_rotation.backtest import run
from etf_rotation.data import snapshot
from etf_rotation.evaluation import artifacts, metrics, observability, registry, trades
from etf_rotation.pipeline import build_weights, compute_benchmark, load_prices
from etf_rotation.signals import cache

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """构建目标权重 → 用 bt 记账回测 → 按档位落盘 → 镜像顶层副本 → 打印 run_id。

    目标权重代表 T 日收盘后确定的持仓，真正生效在 T+1，因此回测前整体
    .shift(1)；execution=open 按 T+1 开盘成交（OpenRebalance），close 回退收盘。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("start", nargs="?", default="2019-01-01")
    parser.add_argument("end", nargs="?", default="2026-07-31")
    parser.add_argument("--param", action="append", default=[])  # 支持 --param a.b.c=value 覆盖参数
    parser.add_argument("--execution", choices=["close", "open"], default="open",
                        help="成交口径：close=收盘成交（bt 标准 Rebalance），open=T+1 开盘成交+跳空顺延")
    parser.add_argument("--save-profile", choices=list(artifacts.SAVE_PROFILES), default="standard",
                        help="产物档位：minimal=只看数字，standard=默认（含净值/权重/持仓/基准），"
                             "full=逐笔与信号快照（出报告用）")
    args = parser.parse_args()

    p = config.load_params()
    # 逐条应用 --param a.b.c=value 覆写（写后即 schema 校验，非法取值当场报错）
    for kv in args.param:
        k, v = kv.split("=", 1)
        config.set_nested(p, k, v)
    start, end = args.start, args.end
    print(f"etf-rotation v{__version__}")
    print(f"building weights {start}..{end}")
    # ① 建权重：with_trace=True 同时采集决策轨迹（供 observability 落盘审计）
    build = build_weights(p, start, end, with_trace=True)
    weights = build.weights
    close, opn, _ = load_prices()
    # 把价格面板对齐到权重面板的交易日与标的列，避免回测时列/索引错位
    close = close.reindex(index=weights.index, columns=weights.columns)
    opn = opn.reindex(index=weights.index, columns=weights.columns)
    # ② 时点对齐：T 日信号 → T+1 生效（权重整体前移一期）
    eff = shift_weights.shift_weights(weights)  # T 日信号，T+1 生效
    # ③ bt 记账：open=开盘成交+收盘估值（默认），close=收盘成交
    res = run.run(eff, opn, close,
                  cost_bps=p["costs"]["one_side_bps"],
                  cash_rate=p["costs"]["cash_rate_annual"],
                  execution=args.execution,
                  gap_delay_pct=p["execution"]["gap_delay_pct"])
    # ④ 指标提取：ffn 全部数值统计 + 引擎的换手与费用（唯一来源，不二次推导）
    s = metrics.all_stats(res.stats)
    s["turnover"] = float(res.turnover.mean())
    s["total_fees"] = float(res.fees.sum())
    print(json.dumps({k: (round(v, 6) if isinstance(v, float) else v) for k, v in s.items()},
                     ensure_ascii=False, indent=2))

    # ⑤ 组装产物面板（索引语义各不相同，见 Review Focus §3.2）：
    #    equity=净值(t 日) / weights=目标权重(T 日) / holdings=引擎实际持仓(t 日)
    #    transactions=成交明细 / trades=逐笔往返 / diary+ticker_signals=信号快照
    equity = metrics.build_equity_frame(res.nav, res.returns, res.cash,
                                        res.turnover, res.fees)
    with warnings.catch_warnings():
        # bt 访问 get_transactions/get_weights 会触发 pandas 宽表 PerformanceWarning，仅性能提示
        warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
        tx = res.result.get_transactions().reset_index()
    trade_rows = trades.build_trade_table_from_engine(
        res.result.get_transactions(), cost_bps=p["costs"]["one_side_bps"])
    diary, ticker_signals = observability.build_frames(build.days, build.traces, build.sig, p)
    stages = observability.build_stages(build.traces, build.days)
    frames = {
        "equity": equity,
        "weights": weights,
        "holdings": res.positions,
        "benchmark": compute_benchmark(p, start, end),
        "transactions": tx,
        "trades": trade_rows,
        "diary": diary,
        "ticker_signals": ticker_signals,
        "stages": stages,
    }

    # ⑥ 内容寻址：run_id = f(参数, 代码, 数据, 执行口径, 信号集)
    flat = config.flatten_params(p)
    flat["_start"], flat["_end"] = start, end
    data_snap = snapshot.data_snapshot_id()
    gsha, dirty_hash = registry.git_info()
    sig_id = cache.signal_id(flat, data_snap)
    run_id = registry.run_identity(
        flat, git_sha=gsha, dirty_hash=dirty_hash, data_snapshot_id=data_snap,
        execution=args.execution, signal_id=sig_id,
    )
    meta = {
        "kind": "backtest",
        "schema_version": 2,
        "version": __version__,
        "run_id": run_id,
        "signal_id": sig_id,
        "data_snapshot_id": data_snap,
        "git_sha": gsha,
        "git_dirty": bool(dirty_hash),
        "dirty_hash": dirty_hash,
        "env_lock_hash": registry.env_lock_hash(),
        "execution": args.execution,
        "start": start,
        "end": end,
        "n_obs": int(res.returns.notna().sum()),
        "params_json": flat,
    }
    run_dir = artifacts.store_run(
        root=ROOT / "reports" / "runs", run_id=run_id, kind="backtest",
        profile=args.save_profile, meta=meta, metrics=s, frames=frames,
    )
    artifacts.mirror_latest(run_dir, ROOT / "reports")
    print(f"stored run {run_id} ({args.save_profile}) -> {run_dir}")
    print(f"mirrored to {ROOT / 'reports'}")


if __name__ == "__main__":
    main()
