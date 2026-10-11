"""生成回测可视化（自包含 HTML + 交易明细 CSV）并更新回测报告。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from etf_rotation.evaluation import plots, trades

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
REPORT = REPORTS / "回测报告.md"
M_START = "<!-- VIS:AUTO -->"
M_END = "<!-- /VIS:AUTO -->"


def main() -> None:
    equity = pd.read_csv(REPORTS / "equity.csv", parse_dates=["ts"]).set_index("ts")
    nav = equity["nav"]
    returns = equity["returns"]
    metrics = json.loads((REPORTS / "metrics.json").read_text(encoding="utf-8"))
    sens = json.loads((REPORTS / "sensitivity.json").read_text(encoding="utf-8"))
    sens_df = pd.DataFrame(sens["cost_sensitivity"])
    weights = pd.read_parquet(REPORTS / "weights.parquet")

    f_eq = plots.equity_drawdown(nav)
    f_sh = plots.rolling_sharpe(returns)
    f_yr = plots.yearly_returns(returns)
    f_cs = plots.cost_sensitivity(sens_df)

    t = trades.build_trade_table(weights, nav)
    t.to_csv(REPORTS / "trades.csv", index=False, encoding="utf-8-sig")

    stats = [
        ("年化收益", f"{metrics['ann_return']:.2%}"),
        ("最大回撤", f"{metrics['max_drawdown']:.2%}"),
        ("Sharpe", f"{metrics['sharpe']:.2f}"),
        ("Calmar", f"{metrics['calmar']:.2f}"),
        ("年化波动", f"{metrics['ann_vol']:.2%}"),
        ("日均换手", f"{metrics['turnover']:.2%}"),
    ]
    sections = [
        (
            "净值与回撤",
            f"2019-01-02 ~ 2026-07-31，策略净值累计至 {nav.iloc[-1]:.2f} 倍；下方阴影为回撤。",
            f_eq,
        ),
        (
            "滚动夏普",
            "63 日与 252 日滚动夏普，反映风险调整后收益的时变特征。",
            f_sh,
        ),
        (
            "分年度收益",
            "各自然年度收益，绿色为正、红色为负，可与研报表 5 对照。",
            f_yr,
        ),
        (
            "成本敏感性",
            "单边成本 0→24bp 时，年化收益、最大回撤与 Calmar 的衰减。",
            f_cs,
        ),
    ]
    plots.write_report(
        sections, stats, REPORTS / "可视化报告.html",
        subtitle="2019-01 ~ 2026-07 · 多资产 ETF 轮动策略",
    )

    _write_report(_build_md(metrics, t))
    print(f"可视化报告.html + trades.csv written; report updated; {len(t)} trades")


def _build_md(metrics: dict, t: pd.DataFrame) -> str:
    lines = [
        M_START,
        "",
        "## 可视化（自动生成）",
        "",
        "- [打开交互式可视化报告](可视化报告.html)（自包含、离线可用）",
        f"- [交易明细 CSV](trades.csv)：共 {len(t)} 笔，买入 {(t['side'] == '买入').sum()} 笔 / "
        f"卖出 {(t['side'] == '卖出').sum()} 笔，合计成本 {t['cost'].sum():.4f}（净值口径）",
        "",
        f"- 年化收益 {metrics['ann_return']:.2%}，最大回撤 {metrics['max_drawdown']:.2%}，"
        f"Sharpe {metrics['sharpe']:.2f}，Calmar {metrics['calmar']:.2f}",
        "",
        M_END,
    ]
    return "\n".join(lines)


def _write_report(section: str) -> None:
    txt = REPORT.read_text(encoding="utf-8") if REPORT.exists() else ""
    if M_START in txt and M_END in txt:
        start = txt.index(M_START)
        end = txt.index(M_END) + len(M_END)
        txt = txt[:start] + section + txt[end:]
    else:
        txt = txt.rstrip() + "\n\n" + section + "\n"
    REPORT.write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    main()

