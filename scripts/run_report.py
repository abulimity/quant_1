"""生成回测可视化（PNG + 交易明细）并更新回测报告。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from etf_rotation.evaluation import plots, trades

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
FIG = REPORTS / "figures"
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

    plots.save_fig(plots.equity_drawdown(nav), FIG / "equity_drawdown.png")
    plots.save_fig(plots.rolling_sharpe(returns), FIG / "rolling_sharpe.png")
    plots.save_fig(plots.yearly_returns(returns), FIG / "yearly_returns.png")
    plots.save_fig(plots.cost_sensitivity(sens_df), FIG / "cost_sensitivity.png")

    t = trades.build_trade_table(weights, nav)
    t.to_csv(REPORTS / "trades.csv", index=False, encoding="utf-8-sig")

    section = _build_md(metrics, t)
    _write_report(section)
    print(f"figures + trades.csv written; report updated; {len(t)} trades")


def _build_md(metrics: dict, t: pd.DataFrame) -> str:
    lines = [
        M_START,
        "",
        "## 可视化（自动生成）",
        "",
        "![净值与回撤](figures/equity_drawdown.png)",
        "",
        "![滚动夏普](figures/rolling_sharpe.png)",
        "",
        "![分年度收益](figures/yearly_returns.png)",
        "",
        "![成本敏感性](figures/cost_sensitivity.png)",
        "",
        "- 年化收益 "
        f"{metrics['ann_return']:.2%}，最大回撤 {metrics['max_drawdown']:.2%}，"
        f"Sharpe {metrics['sharpe']:.2f}，Calmar {metrics['calmar']:.2f}",
        f"- 交易明细：共 {len(t)} 笔，买入 {(t['side'] == '买入').sum()} 笔 / "
        f"卖出 {(t['side'] == '卖出').sum()} 笔，合计成本 {t['cost'].sum():.4f}（净值口径）",
        "",
        "<details><summary>交易明细（前 20 笔，全量见 reports/trades.csv）</summary>",
        "",
        t.head(20).to_markdown(index=False),
        "",
        "</details>",
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

