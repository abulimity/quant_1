"""信号/决策可观测化：把决策轨迹 + 信号面板拼成结构化快照（decision_diary + ticker_signals）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def _get(df: pd.DataFrame, d, t) -> float:
    """安全取面板值：列/索引缺失或 NaN 时返回 nan。"""
    if t in df.columns:
        v = df.loc[d, t]
        return float(v) if pd.notna(v) else float("nan")
    return float("nan")


def _diary_row(trace: dict) -> dict:
    return {
        "comp_score": trace["comp_score"],
        "regime": trace["regime"],
        "cyb_below": trace["cyb_below"],
        "cyb_drop": trace["cyb_drop"],
        "cyb_vol": trace["cyb_vol"],
        "risk_scale": trace["risk_scale"],
        "vol_scale_risk": trace["vol_scale_risk"],
        "risk_budget": trace["risk_budget"],
        "nas_mom": trace["nas_mom"],
        "gold_mom": trace["gold_mom"],
        "nas_vol": trace["nas_vol"],
        "gold_vol": trace["gold_vol"],
        "nasdaq_weight": trace["nasdaq_weight"],
        "gold_weight": trace["gold_weight"],
        "n_cands": len(trace["cands"]),
        "n_kept": len(trace["keep"]),
        "n_overheat_exits": len(trace["overheat_exited"]),
        "hysteresis_held": trace["hysteresis_held"],
        "new_score": trace["new_score"],
        "old_score": trace["old_score"],
        "vol_cap_scale": trace["vol_cap_scale"],
        "n_defensive": len(trace["defensive"]),
        "total_weight": trace["total_weight"],
        "cash_weight": 1.0 - trace["total_weight"],
    }


def _status(t, held, cands, exited, defensive, nasdaq, gold, nasdaq_w, gold_w) -> str:
    if t == nasdaq and nasdaq_w > 0:
        return "nasdaq"
    if t == gold and gold_w > 0:
        return "gold"
    if t in exited:
        return "overheat_exit"
    if t in defensive:
        return "defensive"
    if t in held:
        return "held_risk"
    return "candidate"


def build_frames(days, traces, sig, params):
    """把 (days, traces, sig) 组装成两张快照。

    - decision_diary：portfolio 级，一行一天。
    - ticker_signals：MultiIndex [date, ticker]，覆盖持仓 + 候选 + 过热退出 + 纳指/黄金 + 防守。
    """
    nasdaq, gold = params["nasdaq_etf"], params["gold_etf"]
    diary = pd.DataFrame([_diary_row(t) for t in traces], index=days)

    rows = []
    for d, trace in zip(days, traces):
        held = set(trace["keep"])
        cands = set(trace["cands"])
        exited = set(trace["overheat_exited"])
        defensive = set(trace["defensive"])
        fw = trace.get("final_weights", {})
        tickers = held | cands | exited | defensive
        if trace["nasdaq_weight"] > 0:
            tickers.add(nasdaq)
        if trace["gold_weight"] > 0:
            tickers.add(gold)
        for t in sorted(tickers):
            close = _get(sig["close"], d, t)
            llt80 = _get(sig["llt80"], d, t)
            rows.append({
                "date": d,
                "ticker": t,
                "m21": _get(sig["m21"], d, t),
                "m60": _get(sig["m60"], d, t),
                "score": trace["score"].get(t, float("nan")),
                "zbias": _get(sig["zbias"], d, t),
                "rev_active": _get(sig["rev_active"], d, t),
                "close": close,
                "llt80": llt80,
                "overheat_ratio": close / llt80 if pd.notna(llt80) and llt80 > 0 else float("nan"),
                "weight": fw.get(t, 0.0),
                "status": _status(t, held, cands, exited, defensive, nasdaq, gold,
                                  trace["nasdaq_weight"], trace["gold_weight"]),
            })
    tk = pd.DataFrame(rows)
    if len(tk):
        tk = tk.set_index(["date", "ticker"])
    else:
        tk = pd.DataFrame(columns=["m21", "m60", "score", "zbias", "rev_active",
                                   "close", "llt80", "overheat_ratio", "weight", "status"])
        tk.index = pd.MultiIndex.from_arrays([[], []], names=["date", "ticker"])
    return diary, tk


def write(reports_dir: Path, diary: pd.DataFrame, ticker_signals: pd.DataFrame) -> None:
    """落盘 reports/signals/{decision_diary,ticker_signals}.parquet。"""
    out = Path(reports_dir) / "signals"
    out.mkdir(parents=True, exist_ok=True)
    diary.to_parquet(out / "decision_diary.parquet")
    ticker_signals.to_parquet(out / "ticker_signals.parquet")
