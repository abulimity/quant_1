"""生成回测可视化（自包含 HTML + 交易明细 CSV）并更新回测报告。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from etf_rotation import __version__, config
from etf_rotation.evaluation import plots, trades
from etf_rotation.pipeline import load_fund_basic, market_regime
from etf_rotation.data import universe as univ

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
REPORT = REPORTS / "回测报告.md"
M_START = "<!-- VIS:AUTO -->"
M_END = "<!-- /VIS:AUTO -->"


def main() -> None:
    """汇总 run_backtest 的产物，生成自包含 HTML 可视化报告 + 交易明细，并回写回测报告。

    依赖 reports/ 下已存在的 equity/metrics/sensitivity/weights/benchmark 与
    transactions 文件，因此须先跑 run_backtest.py（及可选 run_sensitivity.py）。
    """
    params = config.load_params()
    equity = pd.read_csv(REPORTS / "equity.csv", parse_dates=["ts"]).set_index("ts")
    nav = equity["nav"]
    returns = equity["returns"]
    metrics = json.loads((REPORTS / "metrics.json").read_text(encoding="utf-8"))
    sens = json.loads((REPORTS / "sensitivity.json").read_text(encoding="utf-8"))
    sens_df = pd.DataFrame(sens["cost_sensitivity"])
    weights = pd.read_parquet(REPORTS / "weights.parquet")
    bench = pd.read_csv(REPORTS / "benchmark.csv", parse_dates=["ts"]).set_index("ts")

    fb = load_fund_basic()
    cat = univ.classify(fb)
    nasdaq, gold = params["nasdaq_etf"], params["gold_etf"]
    label_map = {}
    # 把每只标的归到四大类，供持仓分布图按资产类别堆叠
    for t in weights.columns:
        if t == nasdaq:
            label_map[t] = "纳指"
        elif t == gold:
            label_map[t] = "黄金"
        elif cat.get(t) in ("bond", "money"):
            label_map[t] = "防守"
        else:
            label_map[t] = "风险资产"

    start, end = str(nav.index[0].date()), str(nav.index[-1].date())
    regime = market_regime(start, end)

    stats = [
        ("年化收益", f"{metrics['ann_return']:.2%}"),
        ("最大回撤", f"{metrics['max_drawdown']:.2%}"),
        ("Sharpe", f"{metrics['sharpe']:.2f}"),
        ("Calmar", f"{metrics['calmar']:.2f}"),
        ("年化波动", f"{metrics['ann_vol']:.2%}"),
        ("日均换手", f"{metrics['turnover']:.2%}"),
    ]
    sections = [
        ("净值曲线对比", "策略 vs 等权持有全池基准 vs 沪深300，均归一化到 1.0 起始。",
         plots.nav_comparison(nav, bench["benchmark"], bench["hs300"])),
        ("回撤曲线", "策略与基准的滚动回撤，可直观看出回撤深度与持续时间。",
         plots.drawdown_curve(nav, bench["benchmark"])),
        ("滚动收益与滚动夏普", "63 日与 252 日滚动年化收益、滚动夏普，观察表现的时间稳定性。",
         plots.rolling_perf(returns)),
        ("子区间表现", "分年度收益 + 按牛/熊/震荡分组的累计收益，评估不同市场环境的适应性。",
         plots.subperiod_performance(returns, regime)),
        ("月度收益热力图", "年份 × 月份收益矩阵，绿为正、红为负，识别季节性。",
         plots.monthly_heatmap(returns)),
        ("持仓分布", "上：按资产类别堆叠；下：前 10 大持仓堆叠，观察轮动与集中度。",
         plots.holdings_distribution(weights, label_map)),
        ("收益分布", "日收益直方图叠加正态拟合，观察肥尾与偏度。",
         plots.return_distribution(returns)),
        ("成本敏感性", "单边成本 0→24bp 时，年化收益、最大回撤与 Calmar 的衰减。",
         plots.cost_sensitivity(sens_df)),
    ]
    plots.write_report(sections, stats, REPORTS / "可视化报告.html",
                       subtitle=f"{start} ~ {end} · 多资产 ETF 轮动策略 · v{__version__}")

    tx = pd.read_csv(REPORTS / "transactions.csv", parse_dates=["Date"]).set_index(["Date", "Security"])
    t = trades.build_trade_table_from_engine(tx, cost_bps=params["costs"]["one_side_bps"])
    try:
        t.to_csv(REPORTS / "trades.csv", index=False, encoding="utf-8-sig")
    except PermissionError:
        print("WARNING: trades.csv 被占用（可能已在 Excel 中打开），保留现有文件")
    _write_report(_build_md(metrics, t))
    print(f"可视化报告.html + trades.csv written; report updated; {len(t)} trades")


def _build_md(metrics: dict, t: pd.DataFrame) -> str:
    """生成回测报告中的自动可视化段落（含指标与交易摘要）。"""
    # 合计成本以引擎 fees 为准（run_backtest 落进 metrics.json）；
    # 兼容旧 metrics.json：缺 total_fees 时回退到逐笔估算合计。
    fees = metrics.get("total_fees", float(t["cost"].sum()))
    heatmap_lines = []
    for p in sorted(REPORTS.glob("heatmap_*.html")):
        heatmap_lines.append(f"- [打开参数敏感性热力图]({p.name})（{p.name}）")
    if heatmap_lines:
        heatmap_lines = ["", "### 参数敏感性热力图", ""] + heatmap_lines
    lines = [
        M_START,
        "",
        "## 可视化（自动生成）",
        "",
        "- [打开交互式可视化报告](可视化报告.html)（自包含、离线可用）",
        f"- [交易明细 CSV](trades.csv)：共 {len(t)} 笔，买入 {(t['side'] == '买入').sum()} 笔 / "
        f"卖出 {(t['side'] == '卖出').sum()} 笔，合计成本 {fees:.4f}（引擎 fees 口径，"
        f"逐笔估算合计 {t['cost'].sum():.4f}）",
        "",
        *heatmap_lines,
        f"- 年化收益 {metrics['ann_return']:.2%}，最大回撤 {metrics['max_drawdown']:.2%}，"
        f"Sharpe {metrics['sharpe']:.2f}，Calmar {metrics['calmar']:.2f}",
        "",
        M_END,
    ]
    return "\n".join(lines)


def _write_report(section: str) -> None:
    """用 <!-- VIS:AUTO --> 标记替换/追加自动生成段落，避免覆盖报告的手写部分。"""
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

