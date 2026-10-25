"""生成回测可视化（自包含 HTML + 交易明细 CSV）并更新回测报告。

用法：
    python scripts/run_report.py                 # 取 reports/latest.json 指向的 run
    python scripts/run_report.py --run-id 1a2b3c4d5e6f

读：`reports/runs/{run_id}/` 下的 equity/metrics/weights/benchmark/
trades/signals（需要 full 档；档位不足时报错并打印重跑命令，不静默降级）。
写：`reports/可视化报告.html`（顶层，保持既有链接）并把同一份拷进
`reports/runs/{run_id}/analysis/`；`reports/回测报告.md` 的自动段落一并更新。

`reports/sensitivity.json` 由 `run_sensitivity.py`（成本敏感性扫描）产出，
不属于单个 run 的档位产物，因此仍从顶层读取。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

from etf_rotation import __version__, config
from etf_rotation.pipeline import load_fund_basic, market_regime
from etf_rotation.data import universe as univ
from etf_rotation.evaluation import artifacts, plots

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
RUNS = REPORTS / "runs"
REPORT = REPORTS / "回测报告.md"
M_START = "<!-- VIS:AUTO -->"
M_END = "<!-- /VIS:AUTO -->"


def _read_metrics(run_dir: Path) -> dict[str, float]:
    """metrics.parquet（长表 metric→value）→ dict（与 ReportContext 同一口径）。"""
    df = pd.read_parquet(run_dir / "metrics.parquet")
    return {str(m): float(v) for m, v in zip(df["metric"], df["value"])}


def main() -> None:
    """汇总 run 的产物，生成自包含 HTML 可视化报告并回写回测报告。

    只读 run 目录下的产物；交易明细由 run_backtest 的 full 档产出，本脚本不再写
    trades.csv。档位不足时报错并打印重跑命令，不静默降级。
    """
    parser = argparse.ArgumentParser(description="生成回测可视化报告")
    parser.add_argument("--run-id", default=None,
                        help="指定 run_id（默认读 reports/latest.json）")
    args = parser.parse_args()

    try:
        run_dir = artifacts.resolve_run(RUNS, args.run_id)
    except FileNotFoundError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)

    profile = str(pd.read_parquet(run_dir / "meta.parquet").iloc[0]["save_profile"])
    if profile != "full":
        sys.exit(
            f"run {run_dir.name} 的档位是 {profile}，报告需要 full 档，"
            f"请重跑：scripts\\run_backtest.py --save-profile full")
    params = config.load_params()
    # 读取 run 产物（equity / metrics / weights / benchmark / trades）
    equity = pd.read_parquet(run_dir / "equity.parquet")
    nav = equity["nav"]
    returns = equity["returns"]
    # 现金占比 = 现金余额 / 净值（引擎的 cash 是绝对金额，除以 nav 才是权重口径）
    cash_weight = equity["cash"] / equity["nav"] if "cash" in equity.columns else None
    metrics = _read_metrics(run_dir)
    sens_path = REPORTS / "sensitivity.json"
    if not sens_path.exists():
        sys.exit(f"{sens_path} 缺失：成本敏感性章节需要它，请先跑 "
                 f"scripts\\run_sensitivity.py（该文件不属于单个 run 的档位产物）")
    sens = json.loads(sens_path.read_text(encoding="utf-8"))
    sens_df = pd.DataFrame(sens["cost_sensitivity"])
    weights = pd.read_parquet(run_dir / "weights.parquet")
    bench = pd.read_parquet(run_dir / "benchmark.parquet")

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

    # 市场状态序列（与策略同一套判定，用于子区间表现图）
    start, end = str(nav.index[0].date()), str(nav.index[-1].date())
    regime = market_regime(start, end)

    # 顶部指标卡片
    stats = [
        ("年化收益", f"{metrics['ann_return']:.2%}"),
        ("最大回撤", f"{metrics['max_drawdown']:.2%}"),
        ("Sharpe", f"{metrics['sharpe']:.2f}"),
        ("Calmar", f"{metrics['calmar']:.2f}"),
        ("年化波动", f"{metrics['ann_vol']:.2%}"),
        ("日均换手", f"{metrics['turnover']:.2%}"),
    ]
    # 交易明细（以引擎成交记录为唯一依据；trades.parquet 由 run_backtest full 档产出）
    t = pd.read_parquet(run_dir / "trades.parquet")

    # 八个固定章节：每节 = (标题, 说明文字, plotly 图)
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
         plots.holdings_distribution(weights, label_map, cash=cash_weight)),
        ("收益分布", "日收益直方图叠加正态拟合，观察肥尾与偏度。",
         plots.return_distribution(returns)),
        ("成本敏感性", "单边成本 0→24bp 时，年化收益、最大回撤与 Calmar 的衰减。",
         plots.cost_sensitivity(sens_df)),
    ]
    # 信号/决策章节：观测层产物存在时追加，缺失则优雅降级
    signals = run_dir / "signals"
    diary_path = signals / "decision_diary.parquet"
    tk_path = signals / "ticker_signals.parquet"
    if diary_path.exists() and tk_path.exists():
        diary = pd.read_parquet(diary_path)
        tk = pd.read_parquet(tk_path)
        held = tk[tk["status"] == "held_risk"]
        top = held.groupby("ticker")["weight"].mean().nlargest(3).index.tolist()
        sections.append(("市场状态与风险预算", "市场状态复合分与 ±0.30 阈值、策略净值联动。",
                         plots.market_state_timeline(diary, nav)))
        sections.append(("风险预算堆叠", "风险（含防守）/纳指/黄金/现金逐日仓位。",
                         plots.risk_budget_stack(diary)))
        for ticker in top:
            sections.append((f"信号趋势：{ticker}", f"{ticker} 的 m21/m60、score、zbias、close vs llt80 与权重变化。",
                             plots.signal_trends(tk, ticker)))
        sections.append(("交易触发事件", "换仓、过热退出、波动上限缩放事件标记（信号 T 日 → 成交 T+1）。",
                         plots.trade_triggers(diary, t)))
    else:
        print(f"WARNING: {signals}/*.parquet 缺失，跳过「信号与决策」章节")
    html = REPORTS / "可视化报告.html"
    plots.write_report(sections, stats, html,
                       subtitle=f"{start} ~ {end} · 多资产 ETF 轮动策略 · v{__version__}")
    # run 内留一份，报告内容与 run_id 绑定，便于回溯
    analysis = run_dir / "analysis"
    analysis.mkdir(exist_ok=True)
    shutil.copy2(html, analysis / html.name)

    _write_report(_build_md(metrics, t, run_dir.name))
    print(f"可视化报告.html written; report updated; {len(t)} trades (run {run_dir.name})")


def _build_md(metrics: dict, t: pd.DataFrame, run_id: str) -> str:
    """生成回测报告中的自动可视化段落（含 run_id、指标与交易摘要）。"""
    # 合计成本以引擎 fees 为准（run_backtest 落进 metrics）；缺 total_fees 时回退逐笔估算
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
        f"- 对应 run：`{run_id}`（产物 `reports/runs/{run_id}/`，档位 full）",
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
