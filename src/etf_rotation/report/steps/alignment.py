"""基准对齐诊断（N1）：滞后相关扫描。

用途：确认基准收益与策略收益同日对齐（`peak_lag == 0`）。任何一次多余的 shift
都会把同日相关从约 0.5 打到 0 附近，并把峰值推到一个非零滞后上。

注意：`lag_correlation` 的索引按 `|lag|` 升序（0, ±1, ±2…），这是为了让并列峰值
时 `idxmax` 命中 0；但**写 JSON 前必须按 lag 数值升序重排**，否则前端横轴会变成
0, 1, -1, 2…。`peak_lag` 必须在原始（|lag| 序）序列上取 `idxmax`。
"""
from __future__ import annotations

import pandas as pd

from etf_rotation.evaluation.alignment import lag_correlation
from etf_rotation.report.context import ReportContext
from etf_rotation.report.serialize import clean

NAME = "alignment"


def build(ctx: ReportContext) -> dict:
    """策略日收益 vs 基准（hs300）日收益的滞后相关扫描。"""
    if ctx.benchmark is None:
        raise RuntimeError("benchmark 缺失：该 run 的档位不含 benchmark.parquet")
    if ctx.equity is None:
        raise RuntimeError("equity 缺失：该 run 的档位不含 equity.parquet")

    strategy = ctx.equity["returns"]
    benchmark = ctx.benchmark["hs300"].pct_change(fill_method=None)

    corr = lag_correlation(strategy, benchmark)
    # 峰值在原始序列上取：并列时 |lag| 序保证优先命中 0
    peak_lag = int(corr.idxmax()) if corr.notna().any() else None
    # 序列化前按 lag 数值升序（-5…5），保证前端横轴单调
    ordered = corr.sort_index()

    return {
        "lags": [int(lag) for lag in ordered.index],
        "corrs": [clean(v) for v in ordered.to_list()],
        "peak_lag": peak_lag,
        "max_lag": int(max(abs(int(lag)) for lag in corr.index)) if len(corr) else 0,
        "ok": peak_lag == 0,
    }
