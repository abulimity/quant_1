"""调仓事件表（N4）：把决策日记里的触发条件翻译成可审计的事件行。

判定规则（唯一的判定入口是 `_event_masks`，`event_dates` 与 `rebalance_events`
共用，禁止两处各写一套 —— S3 / Task 14 会直接调用 `event_dates`）：

    switch      —— **核心持仓集合变化**：先取 `w >= 0.005` 的标的，
                   再按权重取前 3 名，`core_t = top3(w_t)`；
                   `core_t != core_{t−1}` 即为换仓（首日无前值，不算 switch）。
                   小成员进出不计入（策略几乎每天都有边缘仓位调整），
                   报告口径只关心核心持仓的更替。
    overheat    —— `n_overheat_exits > 0`（当日有标的被单 ETF 过热规则清零）
    vol_cap     —— `vol_cap_scale < 1`（组合波动触顶，按比例缩放仓位）
    defensive   —— `n_defensive` 相对前一日发生变化
    cross_asset —— 纳指/黄金腿权重相对前一日变化 ≥1pp（低于此视为每日波动缩放噪声）

`hysteresis_held` 不再单独定义 switch：五相位平滑下它几乎每天为 False（「候选
得分 > 旧组合得分」），把它当换仓会让每个交易日都成为事件。它只保留在
`triggers` 快照里供审阅；真正有经济含义的换仓是**前 3 大持仓**发生更替。

口径与索引语义：
- 事件日期 = **信号日 T**（`diary` / 目标 `weights` 的索引），实际成交在 T+1；
- `turnover = Σ|Δw|/2`，Δw = T 日目标权重 − T−1 日目标权重（单边换手，
  与引擎 `equity.turnover` 同量纲）；
- `top_changes` 取 |Δw| 最大的前 3 个标的（浮点噪声 < `_DW_TOL` 的不计）；
- 首日没有前一日权重 → 换手 0、无变化，不产生 `defensive` / `cross_asset`。

**事后信息**：`fwd_5d` / `fwd_20d` 是事件日之后 5 / 20 个交易日的组合收益
`Π(1+r_{t+1..t+n}) − 1`，只用于事后复盘，不得进入任何决策或筛选条件；
尾部样本不足 n 天时为 None（不缩短窗口凑数）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from etf_rotation.report.context import ReportContext
from etf_rotation.report.serialize import records

NAME = "events"

# 固定顺序：写进 JSON 的 types 必须可复现，不随判定实现顺序漂移
TYPE_ORDER = ("switch", "overheat", "vol_cap", "defensive", "cross_asset")

# 权重变化小于该值视为没动（浮点求和顺序会留下 ~1e-17 的噪声）
_DW_TOL = 1e-9
# 持仓集合的纳入阈值：权重 >= 0.5% 才算「持有」（低于此视为残渣仓位）
_HELD_TOL = 0.005
# 核心持仓口径：在达标标的里按权重取前 N 名；只有前 N 名更替才算换仓
_TOP_N = 3
# 跨资产腿（纳指/黄金）的「有变化」阈值：1 个百分点。
# 两者都按 EWMA 波动每日缩放，任何微小变化都算事件会让 cross_asset 淹没事件表
# （实测 981/1838 天）；1pp 阈值下约 290 天。
_CROSS_TOL = 0.01
# vol_cap_scale 小于该值才视为缩放（1.0 与 0.9999999999 不是同一个事件）
_SCALE_TOL = 1e-9
# 事后收益窗口（交易日）
FWD_HORIZONS = (5, 20)


def _series(diary: pd.DataFrame, name: str, default: float) -> pd.Series:
    """取日记列；缺列时返回同索引常量列（可选字段缺失 = 该规则不触发）。"""
    if name in diary.columns:
        return pd.Series(diary[name], index=diary.index)
    return pd.Series(default, index=diary.index)


def _change(series: pd.Series) -> pd.Series:
    """相对前一日的变化；首日 NaN 与任何数比较都为 False，即「首日不算变化」。"""
    return pd.Series(series, index=series.index).astype("float64").diff()


def _held_sets(weights: pd.DataFrame, index: pd.Index) -> pd.Series:
    """逐日核心持仓集合：`w >= 0.005` 的标的里按权重取前 3（index = 事件日历）。

    返回 Series（值为 frozenset）。并列权重按列顺序稳定取（`kind="stable"`），
    保证同一份权重在两次运行中得到同一集合。
    """
    w = pd.DataFrame(weights).sort_index().astype("float64").reindex(index=index)
    columns = np.asarray(w.columns, dtype=object)
    values = w.to_numpy(dtype="float64")
    sets = []
    for row in values:
        eligible = np.flatnonzero(row >= _HELD_TOL)   # NaN 比较为 False，自动排除
        if eligible.size > _TOP_N:
            ranked = eligible[np.argsort(-row[eligible], kind="stable")]
            eligible = ranked[:_TOP_N]
        sets.append(frozenset(columns[eligible]))
    return pd.Series(sets, index=index, dtype=object)


def _event_masks(diary: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    """逐日事件掩码（index = 信号日，columns = TYPE_ORDER）。唯一判定入口。

    `switch` 由目标权重面板的**持仓集合变化**判定；其余四类只读日记。
    事件日历 = 日记与权重索引的交集，保证每条事件都有可比的前一日权重。
    """
    d = pd.DataFrame(diary).sort_index()
    w = pd.DataFrame(weights).sort_index()
    index = d.index.intersection(w.index)

    held_sets = _held_sets(w, index)
    prev_sets = held_sets.shift(1)
    # 首日没有前值（prev 为 NaN）不算 switch，与换手/defensive 的首日口径一致
    switch = held_sets.ne(prev_sets) & prev_sets.notna()

    overheat = _series(d, "n_overheat_exits", 0.0).fillna(0.0) > 0.0
    vol_cap = _series(d, "vol_cap_scale", 1.0).fillna(1.0) < (1.0 - _SCALE_TOL)
    defensive = _change(_series(d, "n_defensive", 0.0)).abs() > 0.0

    nas = _change(_series(d, "nasdaq_weight", 0.0)).abs()
    gold = _change(_series(d, "gold_weight", 0.0)).abs()
    cross_asset = (nas >= _CROSS_TOL) | (gold >= _CROSS_TOL)

    masks = pd.DataFrame({
        "switch": switch,
        "overheat": overheat,
        "vol_cap": vol_cap,
        "defensive": defensive,
        "cross_asset": cross_asset,
    }, index=d.index)
    masks = masks.reindex(index=index)
    return masks.loc[:, list(TYPE_ORDER)].fillna(False).astype(bool)


def event_dates(diary: pd.DataFrame, weights: pd.DataFrame) -> pd.DatetimeIndex:
    """所有触发日的并集（Task 14 / S3 复用；判定规则与 `rebalance_events` 同源）。"""
    masks = _event_masks(diary, weights)
    return pd.DatetimeIndex(masks.index[masks.any(axis=1)])


def _daily_delta(weights: pd.DataFrame, index: pd.Index) -> pd.DataFrame:
    """按权重自身日历做差分，再对齐到事件日历（避免 reindex 后 diff 跨缺口）。"""
    w = pd.DataFrame(weights).sort_index().astype("float64")
    return w.diff().reindex(index=index)


def _turnover(delta: pd.DataFrame) -> pd.Series:
    """单边换手：`Σ|Δw|/2`；首日无前值 → 0。"""
    return delta.abs().sum(axis=1) / 2.0


def _top_changes(row: pd.Series, top_n: int = 3) -> list[dict]:
    """|Δw| 最大的前 `top_n` 个标的（稳定排序；并列按列顺序）。"""
    clean = row.dropna()
    clean = clean[clean.abs() > _DW_TOL]
    if clean.empty:
        return []
    ordered = clean.reindex(clean.abs().sort_values(ascending=False, kind="mergesort").index)
    return [{"ticker": str(ticker), "delta": float(delta)} for ticker, delta in ordered.head(top_n).items()]


def _forward_returns(returns: pd.Series, horizons=FWD_HORIZONS) -> pd.DataFrame:
    """事后收益：`growth_{t+n}/growth_t − 1`；尾部不足 n 天自然为 NaN。

    实现为 `growth.shift(-n) / growth − 1`，等价于 `Π(1+r_{t+1..t+n}) − 1`；
    任何一天收益缺失都会让整个窗口保持 NaN，不拿 0 补齐制造虚假窗口。
    """
    r = pd.Series(returns, dtype="float64").sort_index()
    growth = (1.0 + r).cumprod()
    out = {}
    for n in horizons:
        out[f"fwd_{n}d"] = growth.shift(-int(n)) / growth - 1.0
    return pd.DataFrame(out)


def _optional(value):
    """NaN/Inf → None（JSON 与测试都按「无定义」理解，不保留 nan 哨兵）。"""
    if value is None:
        return None
    value = float(value)
    return value if np.isfinite(value) else None


def _trigger_snapshot(diary: pd.DataFrame, date) -> dict:
    """当日原始触发值（只读镜像，便于回答「为什么判成这个事件」）。"""
    row = diary.loc[date]
    out = {}
    for key in ("hysteresis_held", "n_overheat_exits", "vol_cap_scale", "n_defensive"):
        value = row[key] if key in row.index else None
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            out[key] = None
        elif key == "hysteresis_held":
            out[key] = bool(value)
        elif key == "vol_cap_scale":
            out[key] = float(value)
        else:
            out[key] = int(value)
    return out


def rebalance_events(diary: pd.DataFrame, weights: pd.DataFrame,
                     returns: pd.Series) -> pd.DataFrame:
    """事件表：一行一个触发日，列见模块 docstring（日期为信号日 T）。"""
    d = pd.DataFrame(diary).sort_index()
    masks = _event_masks(d, weights)
    if masks.empty:
        return pd.DataFrame(columns=["date", "types", "regime", "turnover",
                                     "top_changes", "triggers", "fwd_5d", "fwd_20d"])

    delta = _daily_delta(weights, masks.index)
    turnover = _turnover(delta)
    fwd = _forward_returns(returns).reindex(masks.index)
    regime = d["regime"] if "regime" in d.columns else pd.Series(None, index=d.index)

    rows: list[dict] = []
    for date in masks.index[masks.any(axis=1)]:
        types = [name for name in TYPE_ORDER if bool(masks.loc[date, name])]
        rows.append({
            "date": date,
            "types": types,
            "regime": regime.get(date),
            "turnover": float(turnover.get(date, 0.0)),
            "top_changes": _top_changes(delta.loc[date]),
            "triggers": _trigger_snapshot(d, date),
            "fwd_5d": _optional(fwd.at[date, "fwd_5d"]) if date in fwd.index else None,
            "fwd_20d": _optional(fwd.at[date, "fwd_20d"]) if date in fwd.index else None,
        })

    table = pd.DataFrame(rows, columns=["date", "types", "regime", "turnover",
                                        "top_changes", "triggers", "fwd_5d", "fwd_20d"])
    # 含 None 的事后收益列保持 object：pandas 否则会把 None 推断回 float64 NaN，
    # 让「尾部不足」与「真实 0 收益」在类型上无法区分。
    for column in ("fwd_5d", "fwd_20d"):
        table[column] = pd.Series([row[column] for row in rows], dtype=object,
                                  index=table.index)
    return table


def build(ctx: ReportContext) -> dict:
    """派生产物：事件表 + 按类型计数 + 覆盖区间。"""
    if ctx.diary is None:
        raise RuntimeError("diary 缺失：该 run 的档位不含 signals/decision_diary.parquet")
    if ctx.weights is None:
        raise RuntimeError("weights 缺失：该 run 的档位不含 weights.parquet")
    if ctx.equity is None:
        raise RuntimeError("equity 缺失：该 run 的档位不含 equity.parquet")

    table = rebalance_events(ctx.diary, ctx.weights, ctx.equity["returns"])
    by_type = {name: int(table["types"].apply(lambda xs, n=name: n in xs).sum())
               for name in TYPE_ORDER} if len(table) else {name: 0 for name in TYPE_ORDER}

    return {
        "events": records(table, index=None),
        "n_events": int(len(table)),
        "n_by_type": by_type,
        "first_date": table["date"].iloc[0] if len(table) else None,
        "last_date": table["date"].iloc[-1] if len(table) else None,
        "note": "fwd_5d/fwd_20d 为事后信息，仅供复盘，不得进入决策",
    }
