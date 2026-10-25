"""事件阶段归因（N5）：把决策阶段快照折成「标的 × 阶段」瀑布矩阵。

数据来源是 `signals/stages.parquet`（`observability.build_stages` 展出的长表，
index 语义为 T 日信号、T+1 成交），事件日期直接复用 `events.event_dates`
（S2a，唯一判定入口），本模块**不重新判定事件**。

阶段顺序是语义的一部分：

    candidate → overheat → cross_asset → defensive → phases → hysteresis → final

`stage_table` 的产物：
- `stage_order`：固定阶段顺序，前端矩阵的列顺序；
- `events[i] = {"date", "tickers", "weights"}`：
  `tickers` 按各阶段最大权重降序取前 `top_n` 个，
  `weights[i][j]` = `tickers[i]` 在 `stage_order[j]` 的权重（缺失补 0）；
- `totals`：每个事件日 × 阶段的总权重（长表），用于画瀑布总量。
"""
from __future__ import annotations

import pandas as pd

from etf_rotation.report.context import ReportContext
from etf_rotation.report.steps import events

NAME = "stages"

# 固定顺序：与 pipeline trace["stages"] 的插入顺序一致
STAGE_ORDER = ("candidate", "overheat", "cross_asset", "defensive",
               "phases", "hysteresis", "final")

_DATE = "%Y-%m-%d"
_COLUMNS = ("date", "ticker", "stage", "weight")


def _normalise(long: pd.DataFrame) -> pd.DataFrame:
    """统一成 date/ticker/stage/weight 四列的普通表（兼容 MultiIndex 索引）。"""
    df = pd.DataFrame(long).copy()
    if isinstance(df.index, pd.MultiIndex) and {"date", "ticker"} <= set(df.index.names):
        df = df.reset_index()
    missing = [name for name in _COLUMNS if name not in df.columns]
    if missing:
        raise ValueError(f"stages 长表缺少列 {missing}；需要 {list(_COLUMNS)}")
    df = df.loc[:, list(_COLUMNS)]
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].astype(str)
    df["stage"] = df["stage"].astype(str)
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce").fillna(0.0)
    return df


def stage_table(long: pd.DataFrame, event_dates, top_n: int = 10) -> dict:
    """把阶段长表折成事件瀑布矩阵（字段与含义见模块 docstring）。"""
    df = _normalise(long)
    dates = pd.DatetimeIndex(pd.to_datetime(list(event_dates))).sort_values()

    out_events: list[dict] = []
    out_totals: list[dict] = []
    for day in dates:
        day_text = pd.Timestamp(day).strftime(_DATE)
        block = df.loc[df["date"] == day]
        totals = block.groupby("stage")["weight"].sum()
        for stage in STAGE_ORDER:
            out_totals.append({
                "date": day_text,
                "stage": stage,
                "total_weight": float(totals.get(stage, 0.0)),
            })

        if block.empty:
            out_events.append({"date": day_text, "tickers": [], "weights": []})
            continue

        pivot = block.pivot_table(index="ticker", columns="stage", values="weight",
                                  aggfunc="sum", fill_value=0.0)
        strength = pivot.max(axis=1).sort_values(ascending=False, kind="mergesort")
        tickers = [str(ticker) for ticker in strength.index[:int(top_n)]]
        matrix = [
            [float(pivot.at[ticker, stage]) if stage in pivot.columns else 0.0
             for stage in STAGE_ORDER]
            for ticker in tickers
        ]
        out_events.append({"date": day_text, "tickers": tickers, "weights": matrix})

    return {
        "stage_order": list(STAGE_ORDER),
        "events": out_events,
        "totals": out_totals,
        "n_events": int(len(dates)),
    }


def build(ctx: ReportContext) -> dict:
    """派生产物：事件日的阶段瀑布（事件日期复用 `events.event_dates`）。"""
    if ctx.stages is None:
        raise RuntimeError("stages 缺失：该 run 的档位不含 signals/stages.parquet")
    if ctx.diary is None:
        raise RuntimeError("diary 缺失：该 run 的档位不含 signals/decision_diary.parquet")
    if ctx.weights is None:
        raise RuntimeError("weights 缺失：该 run 的档位不含 weights.parquet")

    event_dates = events.event_dates(ctx.diary, ctx.weights)
    return stage_table(ctx.stages, event_dates, top_n=10)
