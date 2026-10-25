"""水下曲线与回撤事件（N2）+ 年度/月度收益表。

定义：
    underwater_t = nav_t / max_{s<=t} nav_s − 1        （≤0，0 = 处于历史新高）
    回撤事件 = 连续水下区间，以「回到前高」为界：
        peak      —— 事件开始前的新高日
        trough    —— 区间内净值最低日
        recovery  —— 首次回到 peak 净值的日期（样本结束仍未恢复则 None）
    回撤幅度 depth = 1 − nav_trough / nav_peak            （正数，0.18 表示 −18%）
    duration_days = trough − peak                        （日历日）
    recovery_days = recovery − trough                    （日历日，未恢复为 None）

年度表用日收益复利（`(1+r).prod()−1`），年度换手/费用按年求和（引擎口径，不二次推导）。
月度表为长表（year, month, return_pct），前端自行透视。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from etf_rotation.report.context import ReportContext
from etf_rotation.report.serialize import records, series

NAME = "performance"

EPISODE_COLUMNS = ["peak_date", "trough_date", "recovery_date", "recovered",
                   "depth", "duration_days", "recovery_days"]

_DATE = "%Y-%m-%d"


def underwater(nav: pd.Series) -> pd.Series:
    """水下曲线：`nav / nav.cummax() - 1`（≤0，0 表示当日处于历史新高）。"""
    nav = pd.Series(nav, dtype="float64")
    return nav / nav.cummax() - 1


def episodes(nav: pd.Series, min_depth: float = 0.02) -> pd.DataFrame:
    """切出所有回撤事件；`min_depth` 按回撤幅度（正数）过滤浅回撤。

    返回列见 `EPISODE_COLUMNS`；没有事件时返回同列空表（调用方不用判 None）。
    """
    nav = pd.Series(nav, dtype="float64").dropna()
    if nav.empty:
        return pd.DataFrame(columns=EPISODE_COLUMNS)

    under = underwater(nav).to_numpy()
    values = nav.to_numpy()
    dates = pd.DatetimeIndex(nav.index)
    n = len(values)
    rows: list[dict] = []

    peak = 0          # 当前历史新高所在位置
    i = 1
    while i < n:
        if under[i] >= 0:      # 新高/平高：更新峰值位置
            peak = i
            i += 1
            continue
        # 水下段起点 i：向后找恢复日（under 回到 ≥0）
        j = i
        while j < n and under[j] < 0:
            j += 1
        recovered = j < n
        stop = j if recovered else n            # 谷底只能在恢复日之前
        trough = i + int(np.argmin(values[i:stop]))

        depth = 1.0 - values[trough] / values[peak]
        if depth >= min_depth:
            recovery_date = dates[j].strftime(_DATE) if recovered else None
            rows.append({
                "peak_date": dates[peak].strftime(_DATE),
                "trough_date": dates[trough].strftime(_DATE),
                "recovery_date": recovery_date,
                "recovered": bool(recovered),
                "depth": float(depth),
                "duration_days": int((dates[trough] - dates[peak]).days),
                "recovery_days": (int((dates[j] - dates[trough]).days) if recovered else None),
            })

        if recovered:
            peak = j
            i = j + 1
        else:
            i = n

    df = pd.DataFrame(rows, columns=EPISODE_COLUMNS)
    if not df.empty:
        # pandas 会把布尔列推断成 numpy bool，`row["recovered"] is True` 会失败；
        # 转 object 保持 Python bool（下游 step/前端都按真布尔判断）
        df["recovered"] = df["recovered"].astype(object)
        # 含 None 的 recovery_days 会被推断成 float（371.0），转 object 保持「整数天或 None」
        df["recovery_days"] = pd.Series(
            [None if pd.isna(v) else int(v) for v in df["recovery_days"]],
            index=df.index, dtype=object)
    return df


def annual_table(equity: pd.DataFrame) -> pd.DataFrame:
    """年度表：year, n_days, return_pct, vol, max_drawdown, turnover, fees。

    - return_pct：该年日收益复利；
    - vol：日收益标准差 × √252；
    - max_drawdown：该年内部（以年内峰值为基准）的最大回撤，负数；
    - turnover / fees：引擎同日流水按年求和（`equity["turnover"]` / `equity["fees"]`）。
    """
    df = equity.dropna(subset=["nav"]).sort_index()
    rows = []
    for year, block in df.groupby(df.index.year):
        returns = block["returns"].dropna()
        dd = (block["nav"] / block["nav"].cummax() - 1).min()
        rows.append({
            "year": int(year),
            "n_days": int(len(block)),
            "return_pct": float((1.0 + returns).prod() - 1.0) if len(returns) else None,
            "vol": float(returns.std(ddof=1) * np.sqrt(252)) if len(returns) > 1 else None,
            "max_drawdown": float(dd) if pd.notna(dd) else None,
            "turnover": float(block["turnover"].sum()) if "turnover" in block else None,
            "fees": float(block["fees"].sum()) if "fees" in block else None,
        })
    return pd.DataFrame(rows, columns=["year", "n_days", "return_pct", "vol",
                                       "max_drawdown", "turnover", "fees"])


def monthly_table(returns: pd.Series) -> pd.DataFrame:
    """月度收益长表：year, month, return_pct（该月日收益复利）。"""
    r = pd.Series(returns, dtype="float64").dropna()
    rows = []
    for (year, month), block in r.groupby([r.index.year, r.index.month]):
        rows.append({
            "year": int(year),
            "month": int(month),
            "return_pct": float((1.0 + block).prod() - 1.0),
        })
    return pd.DataFrame(rows, columns=["year", "month", "return_pct"])


def longest_underwater(nav: pd.Series) -> dict:
    """跨度最长（peak → 恢复/样本末）的回撤事件，附 `total_days`；无事件时全 None。"""
    nav = pd.Series(nav, dtype="float64").dropna()
    empty = {key: None for key in EPISODE_COLUMNS + ["total_days"]}
    if nav.empty:
        return empty
    table = episodes(nav, min_depth=0.0)
    if table.empty:
        return empty

    last_date = pd.Timestamp(nav.index[-1])
    spans = []
    for row in table.to_dict("records"):
        end = pd.Timestamp(row["recovery_date"]) if row["recovery_date"] else last_date
        spans.append((end - pd.Timestamp(row["peak_date"])).days)
    best = int(np.argmax(spans))
    out = dict(table.iloc[best].to_dict())
    out["total_days"] = int(spans[best])
    return out


def build(ctx: ReportContext) -> dict:
    """派生产物：水下曲线、回撤事件、年度/月度表、最长水下区间。"""
    if ctx.equity is None:
        raise RuntimeError("equity 缺失：该 run 的档位不含 equity.parquet")

    nav = ctx.equity["nav"].dropna()
    returns = ctx.equity["returns"]
    return {
        "summary": {"max_drawdown": float(underwater(nav).min()),
                    "n_days": int(len(nav))},
        "underwater": series(underwater(nav), name="values"),
        "episodes": records(episodes(nav), index=None),
        "annual": records(annual_table(ctx.equity), index=None),
        "monthly": records(monthly_table(returns), index=None),
        "longest": longest_underwater(nav),
    }
