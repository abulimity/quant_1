"""样本外子区间复核（open 口径）：2019–2023 vs 2024–2026。

用法：scripts/run_oos_check.py --param trend.weighting=exp [--param a.b=v ...]

方法：在**全窗口**（2019→2026）一次性建权（保证 warmup `i>=170`/`i>=60`、五相位、
整组迟滞等状态都以 2019 起点为准、不因子区间边界重置），再对「已 shift(1) 的有效权重」
按子区间切片跑 bt。切勿对子区间独立 `build_weights`：其循环用相对索引 `i`，会把 2024
边界当作起点，导致 2024 前 ~170 日无风险仓（见 test 与审查结论）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from etf_rotation.execution import shift_weights
from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.evaluation import metrics
from etf_rotation.pipeline import build_weights, load_context

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("ann_return", "max_drawdown", "sharpe", "calmar")
FULL_START, FULL_END = "2019-01-01", "2026-07-31"
SUBPERIODS = [
    ("2019-2023", "2019-01-01", "2023-12-31"),
    ("2024-2026", "2024-01-01", "2026-07-31"),
]


def _run_slice(eff, start: str, end: str, ctx: dict, p: dict) -> dict:
    """对全窗口有效权重按子区间切片后跑 bt（不再 shift，eff 已是 T 日信号/T+1 生效）。"""
    sub = eff.loc[start:end]
    close = ctx["close"].reindex(index=sub.index, columns=sub.columns)
    opn = ctx["opn"].reindex(index=sub.index, columns=sub.columns)
    r = run.run(sub, opn, close, cost_bps=p["costs"]["one_side_bps"],
                cash_rate=p["costs"]["cash_rate_annual"], execution="open")
    s = metrics.from_stats(r.stats)
    return {k: s[k] for k in KEYS}


def main() -> None:
    """样本外子区间复核：全窗口建权 → 按 2019–2023 / 2024–2026 切片回测。

    关键纪律（见模块 docstring）：必须先在**全窗口**建权、再切片，
    不能对子区间独立调用 build_weights——后者的循环用相对索引 i，
    会把 2024 边界当成起点，导致 2024 年初约 170 个交易日没有风险仓，
    子区间结果被人为压低。

    输出：reports/oos_check.json（各子区间的 ann_return / max_drawdown /
    sharpe / calmar），并记录本次使用的参数覆写。
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--param", action="append", default=[])
    args = ap.parse_args()

    # 逐条应用 --param a.b=c 覆写（写后即做 schema 校验）
    p = config.load_params()
    for kv in args.param:
        k, v = kv.split("=", 1)
        config.set_nested(p, k, v)

    ctx = load_context()
    # 全窗口建权（warmup、五相位、迟滞状态都以 2019 起点为准）
    weights = build_weights(p, FULL_START, FULL_END, context=ctx)
    eff = shift_weights.shift_weights(weights)  # T 日信号、T+1 生效

    # 按子区间切片回测（eff 已是有效权重，不再二次 shift）
    subperiods = {}
    for label, start, end in SUBPERIODS:
        subperiods[label] = _run_slice(eff, start, end, ctx, p)

    out = {"param_overrides": args.param, "subperiods": subperiods}
    (ROOT / "reports" / "oos_check.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
