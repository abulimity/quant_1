"""成交滑点与容量估算（N10 + N11）。

滑点（N10）：
    vs_close_bps = sign × (price / close − 1) × 1e4
    vs_open_bps  = sign × (price / opn  − 1) × 1e4
    买入 sign=+1、卖出 sign=−1（正数 = 对策略不利）。方向优先取 `trades.side`，
    缺失时回退到 transactions.quantity 的符号。

容量（N11）：
    value = weight × capital               （元；weight 为目标权重）
    adv20 = amount.rolling(20).mean()      （元；20 日均成交额）
    days  = value / adv20                  （按当前成交额清仓所需天数）
    只统计 weight > 0 的持仓；adv20 预热期为 NaN，整行剔除，不 fillna。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from etf_rotation.report.context import ReportContext
from etf_rotation.report.serialize import records

NAME = "liquidity"

SLIPPAGE_COLUMNS = ["date", "ticker", "side", "price", "close", "opn",
                    "vs_close_bps", "vs_open_bps"]
CAPACITY_COLUMNS = ["date", "ticker", "weight", "adv20", "days"]

CAPITAL = 1e8
ADV_WINDOW = 20

_BUY, _SELL = "买入", "卖出"


def _num(value) -> float | None:
    """None/NaN/Inf → None，其余转 float。"""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _lookup(panel: pd.DataFrame | None, dates, tickers) -> np.ndarray:
    """按 (date, ticker) 取面板值；缺列/缺行返回 NaN（不抛错）。"""
    values = np.full(len(dates), np.nan, dtype="float64")
    if panel is None or panel.empty:
        return values
    columns = set(map(str, panel.columns))
    for i, (date, ticker) in enumerate(zip(dates, tickers)):
        if ticker not in columns:
            continue
        try:
            value = panel.at[date, ticker]
        except (KeyError, IndexError):
            continue
        if pd.notna(value):
            values[i] = float(value)
    return values


def _side_map(trades: pd.DataFrame | None) -> dict[tuple[pd.Timestamp, str], str]:
    """trades(date, ticker, side) → {(date, ticker): side}。"""
    if trades is None or trades.empty or "side" not in trades.columns:
        return {}
    dates = pd.to_datetime(trades["date"])
    return {
        (pd.Timestamp(d).normalize(), str(t)): str(s)
        for d, t, s in zip(dates, trades["ticker"], trades["side"])
    }


def slippage(transactions: pd.DataFrame | None, trades: pd.DataFrame | None,
             close: pd.DataFrame | None, opn: pd.DataFrame | None) -> pd.DataFrame:
    """成交价相对当日 close/open 的滑点（bp，已按买卖方向调整符号）。"""
    if transactions is None or transactions.empty:
        return pd.DataFrame(columns=SLIPPAGE_COLUMNS)

    dates = pd.to_datetime(transactions["Date"])
    tickers = transactions["Security"].astype(str)
    price = pd.to_numeric(transactions["price"], errors="coerce")
    close_values = _lookup(close, dates, tickers)
    open_values = _lookup(opn, dates, tickers)

    sides = _side_map(trades)
    labels: list[str | None] = []
    signs: list[float] = []
    for date, ticker, qty in zip(dates, tickers, transactions["quantity"]):
        side = sides.get((pd.Timestamp(date).normalize(), ticker))
        if side is None:
            qty = float(qty) if pd.notna(qty) else 0.0
            side = _BUY if qty > 0 else (_SELL if qty < 0 else None)
        labels.append(side)
        signs.append(1.0 if side == _BUY else (-1.0 if side == _SELL else np.nan))

    signs_arr = np.asarray(signs, dtype="float64")
    with np.errstate(divide="ignore", invalid="ignore"):
        vs_close = signs_arr * (price.to_numpy(dtype="float64") / close_values - 1.0) * 1e4
        vs_open = signs_arr * (price.to_numpy(dtype="float64") / open_values - 1.0) * 1e4

    out = pd.DataFrame({
        "date": dates.to_numpy(),
        "ticker": tickers.to_numpy(),
        "side": labels,
        "price": price.to_numpy(),
        "close": close_values,
        "opn": open_values,
        "vs_close_bps": vs_close,
        "vs_open_bps": vs_open,
    }, columns=SLIPPAGE_COLUMNS)
    return out.replace([np.inf, -np.inf], np.nan)


def capacity(weights: pd.DataFrame | None, amount: pd.DataFrame | None,
             capital: float = CAPITAL, adv_window: int = ADV_WINDOW) -> pd.DataFrame:
    """持仓市值 / 20 日均成交额（清仓天数），返回长表 date,ticker,weight,adv20,days。"""
    if weights is None or weights.empty or amount is None or amount.empty:
        return pd.DataFrame(columns=CAPACITY_COLUMNS)

    w = pd.DataFrame(weights).sort_index()
    amt = pd.DataFrame(amount).reindex(index=w.index, columns=w.columns)
    adv = amt.rolling(int(adv_window), min_periods=int(adv_window)).mean()

    weight_long = w.stack(future_stack=True).rename("weight")
    adv_long = adv.stack(future_stack=True).rename("adv20")
    df = pd.concat([weight_long, adv_long], axis=1, join="inner").dropna()
    df = df[df["weight"] > 0]
    if df.empty:
        return pd.DataFrame(columns=CAPACITY_COLUMNS)

    df = df.assign(days=df["weight"] * float(capital) / df["adv20"])
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["days"])
    df = df.reset_index()
    df.columns = ["date", "ticker", "weight", "adv20", "days"]
    return df.sort_values(["date", "ticker"], kind="stable").reset_index(drop=True)


def _slippage_summary(rows: pd.DataFrame) -> dict:
    """滑点汇总：中位数/均值 + 20bp 内占比（正负各自按方向调整后）。"""
    if rows.empty:
        return {
            "n": 0, "median_vs_close_bps": None, "median_vs_open_bps": None,
            "mean_vs_close_bps": None, "mean_vs_open_bps": None,
            "share_within_20bp": None,
        }
    vs_close = pd.to_numeric(rows["vs_close_bps"], errors="coerce").dropna()
    vs_open = pd.to_numeric(rows["vs_open_bps"], errors="coerce").dropna()
    within = (vs_close.abs() <= 20.0).mean() if len(vs_close) else None
    return {
        "n": int(len(rows)),
        "median_vs_close_bps": _num(vs_close.median()) if len(vs_close) else None,
        "median_vs_open_bps": _num(vs_open.median()) if len(vs_open) else None,
        "mean_vs_close_bps": _num(vs_close.mean()) if len(vs_close) else None,
        "mean_vs_open_bps": _num(vs_open.mean()) if len(vs_open) else None,
        "share_within_20bp": _num(within),
    }


def _capacity_tables(rows: pd.DataFrame) -> tuple[dict, list, list]:
    """容量汇总：整体分位、分年分位、最差 20 个 (date, ticker, days)。"""
    if rows.empty:
        return ({"n": 0, "p50_days": None, "p95_days": None, "max_days": None}, [], [])

    days = pd.to_numeric(rows["days"], errors="coerce")
    summary = {
        "n": int(len(rows)),
        "p50_days": _num(days.quantile(0.50)),
        "p95_days": _num(days.quantile(0.95)),
        "max_days": _num(days.max()),
    }

    work = rows.assign(year=pd.to_datetime(rows["date"]).dt.year)
    by_year = []
    for year, block in work.groupby("year"):
        values = pd.to_numeric(block["days"], errors="coerce")
        by_year.append({
            "year": int(year),
            "n": int(len(block)),
            "p50_days": _num(values.quantile(0.50)),
            "p95_days": _num(values.quantile(0.95)),
            "max_days": _num(values.max()),
        })

    worst = work.nlargest(20, "days")[["date", "ticker", "weight", "adv20", "days"]]
    return summary, by_year, records(worst, index=None)


def build(ctx: ReportContext) -> dict:
    """派生产物：滑点明细/汇总、容量分年分位与最差持仓、假设。"""
    if ctx.weights is None or ctx.amount is None:
        raise RuntimeError("weights/amount 缺失：容量估算需要 weights.parquet 与行情面板")

    if ctx.transactions is not None and ctx.close is not None:
        slip_rows = slippage(ctx.transactions, ctx.trades, ctx.close, ctx.opn)
    else:
        slip_rows = pd.DataFrame(columns=SLIPPAGE_COLUMNS)

    cap_rows = capacity(ctx.weights, ctx.amount, capital=CAPITAL, adv_window=ADV_WINDOW)
    cap_summary, cap_by_year, worst = _capacity_tables(cap_rows)

    return {
        "slippage": {
            "rows": records(slip_rows, index=None),
            "summary": _slippage_summary(slip_rows),
        },
        "capacity": {
            "summary": cap_summary,
            "by_year": cap_by_year,
            "worst": worst,
        },
        "assumptions": {
            "capital": CAPITAL,
            "adv_window": ADV_WINDOW,
            "amount_unit": "CNY（元）",
            "price_unit": "元/份",
            "note": "容量按目标权重 × capital 估算持仓市值，adv20 为 20 日均成交额；"
                    "未考虑冲击成本与分批执行，属于上界估计。",
        },
    }
