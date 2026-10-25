"""信号/决策可观测化：把决策轨迹 + 信号面板拼成结构化快照（decision_diary + ticker_signals）。

目标：让「策略为什么这么调仓」可被事后审计，而不是只能看一条净值曲线。

产出两张表：
  decision_diary  —— 组合级，一行一个交易日，记录当天的状态、缩放、预算、
                     候选/持仓数量、迟滞判定、波动上限缩放、最终总权重等
  ticker_signals  —— 标的级，MultiIndex [date, ticker]，记录每个标的当天的
                     动量/反转信号、价格相对 LLT 的过热比、最终权重与状态标签

两张表都是「只读镜像」：它们不参与任何决策，也不影响回测数值，
纯粹是把决策链路里的中间量落盘，供归因与审阅使用。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# 阶段快照的固定顺序（与 pipeline trace["stages"] 的写入顺序一致）。
# 顺序即语义：candidate → overheat → cross_asset → defensive → phases → hysteresis → final。
STAGE_ORDER = ("candidate", "overheat", "cross_asset", "defensive",
               "phases", "hysteresis", "final")


def _get(df: pd.DataFrame, d, t) -> float:
    """安全取面板值：列/索引缺失或 NaN 时返回 nan。"""
    if t in df.columns:
        v = df.loc[d, t]
        return float(v) if pd.notna(v) else float("nan")
    return float("nan")


def _diary_row(trace: dict) -> dict:
    """把单日决策轨迹压成 decision_diary 的一行。

    字段分组（便于审阅时按「先看市场、再看仓位」顺序读）：
      ① 市场状态   comp_score / regime / cyb_below / cyb_drop / cyb_vol
      ② 风险缩放   risk_scale / vol_scale_risk / risk_budget
      ③ 跨资产腿   nas_mom / gold_mom / nas_vol / gold_vol / nasdaq_weight / gold_weight
      ④ 选股计数   n_cands（候选）/ n_kept（去重后保留）/ n_overheat_exits（过热清零）
      ⑤ 平滑与约束 hysteresis_held / new_score / old_score / vol_cap_scale
      ⑥ 防守与仓位 n_defensive / total_weight / cash_weight

    注意：nasdaq_weight / gold_weight 在 build_weights 中已被覆盖为「最终（平滑后）」口径，
    与 total_weight / cash_weight 同源，可直接相加核对。
    """
    return {
        # ① 市场状态：三指数复合分、regime、创业板趋势与波动
        "comp_score": trace["comp_score"],
        "regime": trace["regime"],
        "cyb_below": trace["cyb_below"],
        "cyb_drop": trace["cyb_drop"],
        "cyb_vol": trace["cyb_vol"],
        # ② 风险缩放与预算：risk_scale（状态/趋势） × vol_scale_risk（波动） → risk_budget
        "risk_scale": trace["risk_scale"],
        "vol_scale_risk": trace["vol_scale_risk"],
        "risk_budget": trace["risk_budget"],
        # ③ 跨资产腿：纳指/黄金的动量、波动与最终权重
        "nas_mom": trace["nas_mom"],
        "gold_mom": trace["gold_mom"],
        "nas_vol": trace["nas_vol"],
        "gold_vol": trace["gold_vol"],
        "nasdaq_weight": trace["nasdaq_weight"],
        "gold_weight": trace["gold_weight"],
        # ④ 选股链路计数：候选 → 去重保留 → 过热清零
        "n_cands": len(trace["cands"]),
        "n_kept": len(trace["keep"]),
        "n_overheat_exits": len(trace["overheat_exited"]),
        # ⑤ 平滑与约束：整组迟滞是否维持旧组合、新旧得分、组合波动上限缩放
        "hysteresis_held": trace["hysteresis_held"],
        "new_score": trace["new_score"],
        "old_score": trace["old_score"],
        "vol_cap_scale": trace["vol_cap_scale"],
        # ⑥ 防守仓与总仓位：cash_weight = 1 − total_weight
        "n_defensive": len(trace["defensive"]),
        "total_weight": trace["total_weight"],
        "cash_weight": 1.0 - trace["total_weight"],
    }


def _status(t, held, cands, exited, defensive, nasdaq, gold, nasdaq_w, gold_w) -> str:
    """判定单个标的当天的状态标签（六状态机，按优先级从高到低判定）。

    六种状态与判定顺序：
      1. nasdaq        —— 该标的是纳指 ETF 且当前有仓位
      2. gold          —— 该标的是黄金 ETF 且当前有仓位
      3. overheat_exit —— 因单 ETF 过热被清零（P_t ≥ LLT₈₀,t·(1+pct)）
      4. defensive     —— 属于防守仓（债券/货币 ETF）
      5. held_risk     —— 属于风险仓且被去重后保留（实际持有）
      6. candidate     —— 进入过候选池但最终未持有

    顺序不可调换：纳指/黄金与防守仓也可能在候选集合里，
    过热退出是「曾持有后被清零」，必须排在 held_risk 之前才有信息量。
    """
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

    ticker_signals 的覆盖范围 = 当天出现过的所有标的的并集：
        持仓 ∪ 候选 ∪ 过热退出 ∪ 防守仓 ∪（有仓位的）纳指/黄金
    这样即使某标的当天最终权重为 0（如刚被过热清零），它的事件记录仍会保留，
    便于回答「为什么这个标的全卖掉了」。

    overheat_ratio 字段 = close / llt80，即「价格相对自身 80 日趋势线的倍数」，
    该值 ≥ 1+pct 即触发过热退出，是最直接的过热证据。
    """
    nasdaq, gold = params["nasdaq_etf"], params["gold_etf"]
    # decision_diary：一行一天，索引为交易日
    diary = pd.DataFrame([_diary_row(t) for t in traces], index=days)

    rows = []
    for d, trace in zip(days, traces):
        # 把当天的四个集合转成 set，便于后续做并集与成员判断
        held = set(trace["keep"])                 # 去重后保留（实际持有的风险仓）
        cands = set(trace["cands"])               # 候选池
        exited = set(trace["overheat_exited"])    # 过热清零
        defensive = set(trace["defensive"])       # 防守仓
        fw = trace.get("final_weights", {})       # 最终（平滑后）权重
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
                # 信号：21/60 日动量、当日横截面得分、反转 z 分数与激活标记
                "m21": _get(sig["m21"], d, t),
                "m60": _get(sig["m60"], d, t),
                "score": trace["score"].get(t, float("nan")),
                "zbias": _get(sig["zbias"], d, t),
                "rev_active": _get(sig["rev_active"], d, t),
                # 价格与过热证据：close / llt80 ≥ 1+pct 即触发过热退出
                "close": close,
                "llt80": llt80,
                "overheat_ratio": close / llt80 if pd.notna(llt80) and llt80 > 0 else float("nan"),
                # 结果：最终权重与状态标签
                "weight": fw.get(t, 0.0),
                "status": _status(t, held, cands, exited, defensive, nasdaq, gold,
                                  trace["nasdaq_weight"], trace["gold_weight"]),
            })
    tk = pd.DataFrame(rows)
    if len(tk):
        tk = tk.set_index(["date", "ticker"])
    else:
        # 空结果也要保留列结构与 MultiIndex 类型，避免下游读取时炸掉
        tk = pd.DataFrame(columns=["m21", "m60", "score", "zbias", "rev_active",
                                   "close", "llt80", "overheat_ratio", "weight", "status"])
        tk.index = pd.MultiIndex.from_arrays([[], []], names=["date", "ticker"])
    return diary, tk


def build_stages(traces: list[dict], days) -> pd.DataFrame:
    """把每日 `trace["stages"]` 展成长表：`date, ticker, stage, weight`。

    - 一行 = 某个交易日、某个标的、某个阶段的权重；
    - 阶段按 `STAGE_ORDER` 输出（顺序稳定，便于前端做瀑布）；
    - trace 里缺某个阶段（旧 trace / 合成数据）时跳过该阶段，不补 0 行；
    - `days` 与 `traces` 按下标一一对应（与 `build_frames` 同一口径）。
    """
    rows: list[dict] = []
    for d, trace in zip(days, traces):
        stage_weights = trace.get("stages") or {}
        for stage in STAGE_ORDER:
            weights = stage_weights.get(stage) or {}
            for ticker in sorted(weights):
                rows.append({
                    "date": d,
                    "ticker": str(ticker),
                    "stage": stage,
                    "weight": float(weights[ticker]),
                })
    table = pd.DataFrame(rows, columns=["date", "ticker", "stage", "weight"])
    table["date"] = pd.to_datetime(table["date"])
    return table


def write(reports_dir: Path, diary: pd.DataFrame, ticker_signals: pd.DataFrame,
          stages: pd.DataFrame | None = None) -> None:
    """落盘 `reports/signals/{decision_diary,ticker_signals,stages}.parquet`。

    `stages=None` 时保持旧行为（只写两张表）；主路径已改为
    `run_backtest` 把 stages 放进 `store_run(frames=...)`，这里的参数只为兼容
    旧调用方（手工落盘 / 测试）保留。
    """
    out = Path(reports_dir) / "signals"
    out.mkdir(parents=True, exist_ok=True)
    diary.to_parquet(out / "decision_diary.parquet")
    ticker_signals.to_parquet(out / "ticker_signals.parquet")
    if stages is not None:
        stages.to_parquet(out / "stages.parquet", compression="zstd")
