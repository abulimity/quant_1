"""单笔往返配对与已实现盈亏（N7）。

FIFO 纪律：
    买入按 (date, price, qty, cost) 入队；卖出按先进先出跨批次消耗，
    允许分数份额（bt 的 quantity 是净值份额，天然带小数）。每笔成本按
    「批次成本 / 批次数量 × 本次消耗数量」分摊，卖出成本按同样比例分到
    当次配对，避免整笔成本被重复计入。

公式：
    pnl          = qty × (sell_price − buy_price) − 买入分摊成本 − 卖出分摊成本
    holding_days = (exit_date − entry_date).days        （日历日）

未平仓批次不进往返表，只在 `summary.open_lots/open_cost` 中统计；
`residual = nav_end − 1 − (Σpnl + open_cost)`，差额主要由未平仓浮盈与现金利息解释。
"""
from __future__ import annotations

import math

import pandas as pd

from etf_rotation.report.context import ReportContext
from etf_rotation.report.serialize import records

NAME = "roundtrips"

COLUMNS = ["ticker", "entry_date", "exit_date", "quantity", "entry_price",
           "exit_price", "pnl", "holding_days", "entry_status", "exit_reason"]

_EPS = 1e-12


def _num(value) -> float | None:
    """None/NaN/Inf → None，其余转 float。"""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _is_buy(side) -> bool:
    """成交方向：兼容引擎的「买入/卖出」与英文 buy/sell。"""
    text = str(side).strip().lower()
    return text in ("买入", "buy", "b")


def _status_map(signals: pd.DataFrame | None) -> dict[tuple[pd.Timestamp, str], str]:
    """ticker_signals → {(date, ticker): status}；支持 MultiIndex 或普通列。"""
    if signals is None or len(signals) == 0 or "status" not in getattr(signals, "columns", []):
        return {}
    df = signals.reset_index() if isinstance(signals.index, pd.MultiIndex) else signals.copy()
    date_col = "date" if "date" in df.columns else df.columns[0]
    ticker_col = "ticker" if "ticker" in df.columns else df.columns[1]
    return {
        (pd.Timestamp(d).normalize(), str(t)): str(s)
        for d, t, s in zip(df[date_col], df[ticker_col], df["status"])
    }


def _simulate(trades: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """逐标的 FIFO 模拟：返回 (已平仓往返行, 未平仓批次)。"""
    if trades is None or trades.empty:
        return [], []

    df = trades.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["ticker"] = df["ticker"].astype(str)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").abs()
    df["cost"] = pd.to_numeric(df.get("cost", 0.0), errors="coerce").fillna(0.0)
    df = df.dropna(subset=["date", "price", "quantity"])
    df = df[df["quantity"] > 0]

    trips: list[dict] = []
    open_lots: list[dict] = []

    for ticker, group in df.groupby("ticker", sort=True):
        lots: list[dict] = []
        for row in group.sort_values("date", kind="stable").itertuples(index=False):
            qty = float(row.quantity)
            price = float(row.price)
            if _is_buy(row.side):
                lots.append({
                    "date": pd.Timestamp(row.date),
                    "price": price,
                    "qty": qty,
                    "unit_cost": float(row.cost) / qty if qty > 0 else 0.0,
                })
                continue

            sell_unit_cost = float(row.cost) / qty if qty > 0 else 0.0
            remaining = qty
            while remaining > _EPS and lots:
                lot = lots[0]
                take = min(remaining, lot["qty"])
                buy_cost = lot["unit_cost"] * take
                sell_cost = sell_unit_cost * take
                trips.append({
                    "ticker": ticker,
                    "entry_date": lot["date"],
                    "exit_date": pd.Timestamp(row.date),
                    "quantity": take,
                    "entry_price": lot["price"],
                    "exit_price": price,
                    "pnl": take * (price - lot["price"]) - buy_cost - sell_cost,
                    "holding_days": int((pd.Timestamp(row.date) - lot["date"]).days),
                    "entry_status": None,
                    "exit_reason": None,
                })
                lot["qty"] -= take
                remaining -= take
                if lot["qty"] <= _EPS:
                    lots.pop(0)

        for lot in lots:
            if lot["qty"] > _EPS:
                open_lots.append({"ticker": ticker, **lot})

    return trips, open_lots


def match_round_trips(trades: pd.DataFrame | None,
                      signals: pd.DataFrame | None = None) -> pd.DataFrame:
    """买卖 FIFO 配对；`signals` 为 ticker_signals（取 status 标注进出场原因）。"""
    trips, _ = _simulate(trades)
    if not trips:
        return pd.DataFrame(columns=COLUMNS)

    out = pd.DataFrame(trips, columns=COLUMNS)
    status = _status_map(signals)
    if status:
        out["entry_status"] = [
            status.get((pd.Timestamp(d).normalize(), str(t)))
            for d, t in zip(out["entry_date"], out["ticker"])
        ]
        reasons = []
        for d, t in zip(out["exit_date"], out["ticker"]):
            code = status.get((pd.Timestamp(d).normalize(), str(t)))
            reasons.append("overheat" if code == "overheat_exit" else "switch")
        out["exit_reason"] = reasons
    else:
        out["entry_status"] = None
        out["exit_reason"] = "other"

    return out.sort_values(["exit_date", "ticker"], kind="stable").reset_index(drop=True)


def build(ctx: ReportContext) -> dict:
    """派生产物：往返明细 + 胜率/盈亏/未平仓统计 + 净值残差。"""
    if ctx.trades is None:
        raise RuntimeError("trades 缺失：该 run 的档位不含 trades.parquet")

    trips = match_round_trips(ctx.trades, ctx.ticker_signals)
    _, open_lots = _simulate(ctx.trades)

    pnl_sum = _num(pd.to_numeric(trips["pnl"], errors="coerce").sum()) if len(trips) else 0.0
    win_rate = None
    if len(trips):
        win_rate = _num((pd.to_numeric(trips["pnl"], errors="coerce") > 0).mean())

    nav_return = None
    if ctx.equity is not None and "nav" in ctx.equity.columns:
        nav = pd.to_numeric(ctx.equity["nav"], errors="coerce").dropna()
        if len(nav):
            nav_return = _num(nav.iloc[-1] - 1.0)

    open_cost = _num(sum(lot["unit_cost"] * lot["qty"] for lot in open_lots)) if open_lots else 0.0
    residual = None
    if nav_return is not None and pnl_sum is not None and open_cost is not None:
        residual = _num(nav_return - (pnl_sum + open_cost))

    reasons = trips["exit_reason"].value_counts().to_dict() if len(trips) else {}
    return {
        "roundtrips": records(trips, index=None),
        "summary": {
            "n_roundtrips": int(len(trips)),
            "win_rate": win_rate,
            "pnl_sum": pnl_sum,
            "holding_days_median": (
                _num(trips["holding_days"].median()) if len(trips) else None),
            "open_lots": int(len(open_lots)),
            "open_cost": open_cost,
            "nav_return": nav_return,
            "residual": residual,
            "exit_reason_counts": {
                "overheat": int(reasons.get("overheat", 0)),
                "switch": int(reasons.get("switch", 0)),
                "other": int(reasons.get("other", 0)),
            },
        },
    }
