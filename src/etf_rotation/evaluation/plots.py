"""回测结果可视化（plotly，自包含交互式 HTML，文字与图表混排）。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

FONT = "Microsoft YaHei, SimHei, sans-serif"

BLUE = "#2c6fbb"
BLUE_LIGHT = "#7fb3d5"
ORANGE = "#e67e22"
GREEN = "#27ae60"
RED = "#c0392b"
GREY = "#95a5a6"
GRID = "#dfe4ea"

CAT_COLORS = {
    "风险资产": "#2c6fbb",
    "纳指": "#27ae60",
    "黄金": "#e67e22",
    "防守": "#8e44ad",
    "现金": "#bdc3c7",
}


def _style(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(
        font=dict(family=FONT, color="#2c3e50"),
        hovermode="x unified",
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin=dict(l=52, r=18, t=42, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def nav_comparison(nav: pd.Series, benchmark: pd.Series, hs300: pd.Series) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=nav.index, y=nav.values / nav.iloc[0], name="策略",
                             line=dict(color=BLUE, width=1.8)))
    fig.add_trace(go.Scatter(x=benchmark.index, y=benchmark.values / benchmark.iloc[0],
                             name="等权全池基准", line=dict(color=GREEN, width=1.4)))
    fig.add_trace(go.Scatter(x=hs300.index, y=hs300.values / hs300.iloc[0], name="沪深300",
                             line=dict(color=ORANGE, width=1.4, dash="dot")))
    fig.update_layout(title="净值曲线对比（归一化 1.0 起始）", yaxis_title="净值")
    return _style(fig, 440)


def drawdown_curve(nav: pd.Series, benchmark: pd.Series | None = None) -> go.Figure:
    fig = go.Figure()
    if benchmark is not None:
        bdd = (benchmark / benchmark.cummax() - 1) * 100
        fig.add_trace(go.Scatter(x=bdd.index, y=bdd.values, name="基准", fill="tozeroy",
                                 line=dict(color=GREY, width=0.6),
                                 fillcolor="rgba(127,140,141,0.15)"))
    dd = (nav / nav.cummax() - 1) * 100
    fig.add_trace(go.Scatter(x=dd.index, y=dd.values, name="策略", fill="tozeroy",
                             line=dict(color=RED, width=0.6),
                             fillcolor="rgba(192,57,43,0.20)"))
    fig.update_layout(title="回撤曲线", yaxis_title="回撤 %")
    return _style(fig)


def rolling_perf(returns: pd.Series, windows=(63, 252)) -> go.Figure:
    r = returns.dropna()
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.5, 0.5],
        vertical_spacing=0.06, subplot_titles=("滚动年化收益", "滚动夏普"),
    )
    for w, color in zip(windows, (BLUE, GREEN)):
        ann = r.rolling(w).mean() * 252
        fig.add_trace(go.Scatter(x=ann.index, y=ann.values, name=f"{w} 日收益",
                                 line=dict(color=color, width=1.2)), row=1, col=1)
    for w, color in zip(windows, (BLUE, GREEN)):
        sh = r.rolling(w).mean() / r.rolling(w).std() * np.sqrt(252)
        fig.add_trace(go.Scatter(x=sh.index, y=sh.values, name=f"{w} 日夏普",
                                 line=dict(color=color, width=1.2)), row=2, col=1)
    fig.add_hline(y=0, row=1, col=1, line=dict(color="#b0b8c0", width=0.7, dash="dot"))
    fig.add_hline(y=0, row=2, col=1, line=dict(color="#b0b8c0", width=0.7, dash="dot"))
    fig.update_yaxes(tickformat=".0%", row=1, col=1)
    fig.update_layout(height=540)
    return _style(fig, height=540)


def subperiod_performance(returns: pd.Series, regime: pd.Series) -> go.Figure:
    r = returns.dropna()
    g = regime.reindex(r.index).fillna("range")
    yr = r.groupby(r.index.year).apply(lambda s: (1 + s).prod() - 1)
    by_reg = r.groupby(g).apply(lambda s: (1 + s).prod() - 1)
    reg_cn = {"bull": "牛市", "bear": "熊市", "range": "震荡"}
    fig = make_subplots(
        rows=1, cols=2, subplot_titles=("分年度收益", "市场阶段收益"),
        horizontal_spacing=0.08,
    )
    fig.add_trace(
        go.Bar(x=[str(y) for y in yr.index], y=yr.values,
               marker_color=[RED if v < 0 else GREEN for v in yr],
               text=[f"{v:.1%}" for v in yr.values], textposition="outside"),
        row=1, col=1,
    )
    labels = [reg_cn.get(k, str(k)) for k in by_reg.index]
    fig.add_trace(
        go.Bar(x=labels, y=by_reg.values,
               marker_color=[RED if v < 0 else GREEN for v in by_reg.values],
               text=[f"{v:.1%}" for v in by_reg.values], textposition="outside"),
        row=1, col=2,
    )
    fig.update_yaxes(tickformat=".0%")
    fig.update_layout(height=420)
    return _style(fig, height=420)


def monthly_heatmap(returns: pd.Series) -> go.Figure:
    r = returns.dropna()
    m = r.groupby([r.index.year, r.index.month]).apply(
        lambda s: (1 + s).prod() - 1
    ).unstack()
    text = [[f"{v:.1%}" for v in row] for row in m.values]
    fig = go.Figure(
        go.Heatmap(
            z=m.values, x=[f"{i}月" for i in m.columns], y=[str(y) for y in m.index],
            colorscale=[[0, RED], [0.5, "#ffffff"], [1, GREEN]], zmid=0,
            text=text, texttemplate="%{text}", colorbar=dict(title="收益"),
        )
    )
    fig.update_layout(title="月度收益热力图")
    return _style(fig, 460)


def holdings_distribution(weights: pd.DataFrame, label_map: dict) -> go.Figure:
    w = weights.copy()
    order = ["风险资产", "纳指", "黄金", "防守", "现金"]
    by_cat = pd.DataFrame(index=w.index)
    for c in order[:-1]:
        cols = [t for t in w.columns if label_map.get(t, "风险资产") == c]
        by_cat[c] = w[cols].sum(axis=1) if cols else 0.0
    by_cat["现金"] = 1.0 - w.sum(axis=1)

    meanw = w.mean().sort_values(ascending=False)
    top = list(meanw.head(10).index)
    top_df = w[top].copy()
    others = [t for t in w.columns if t not in top]
    top_df["其他"] = w[others].sum(axis=1)
    top_df["现金"] = 1.0 - w.sum(axis=1)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        subplot_titles=("资产类别分布", "前 10 大持仓分布"),
    )
    for c in order:
        fig.add_trace(go.Scatter(x=by_cat.index, y=by_cat[c], name=c, stackgroup="a",
                                 line=dict(width=0.3), fillcolor=CAT_COLORS.get(c)),
                      row=1, col=1)
    for t in top_df.columns:
        fig.add_trace(go.Scatter(x=top_df.index, y=top_df[t], name=t, stackgroup="b",
                                 line=dict(width=0.3)), row=2, col=1)
    fig.update_yaxes(tickformat=".0%")
    fig.update_layout(height=620, showlegend=True)
    return _style(fig, height=620)


def return_distribution(returns: pd.Series) -> go.Figure:
    r = returns.dropna()
    fig = go.Figure()
    fig.add_trace(go.Histogram(x=r.values, nbinsx=80, histnorm="probability density",
                               name="日收益", marker_color="rgba(44,111,187,0.55)"))
    mu, sd = r.mean(), r.std()
    xs = np.linspace(float(r.min()), float(r.max()), 200)
    pdf = np.exp(-0.5 * ((xs - mu) / sd) ** 2) / (sd * np.sqrt(2 * np.pi))
    fig.add_trace(go.Scatter(x=xs, y=pdf, name="正态拟合", line=dict(color=ORANGE, width=1.5)))
    fig.update_layout(title="日收益分布", bargap=0.02)
    fig.update_xaxes(tickformat=".1%")
    return _style(fig)


def cost_sensitivity(sens: pd.DataFrame) -> go.Figure:
    x = sens["cost_bps"].astype(float)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=sens["ann_return"] * 100, mode="lines+markers",
                             name="年化收益 %", line=dict(color=BLUE, width=1.6)))
    fig.add_trace(go.Scatter(x=x, y=sens["calmar"], mode="lines+markers",
                             name="Calmar", line=dict(color=ORANGE, width=1.6)))
    fig.add_trace(go.Scatter(x=x, y=-sens["max_drawdown"] * 100, mode="lines+markers",
                             name="最大回撤 %（取正）", line=dict(color=RED, width=1.6)))
    fig.update_layout(title="成本敏感性", xaxis_title="单边成本 bp")
    return _style(fig)


def write_report(
    sections: list[tuple[str, str, go.Figure]],
    stats: list[tuple[str, str]],
    path: Path,
    subtitle: str = "",
) -> None:
    """把多个（标题、说明文字、图表）合并成一个自包含 HTML（内嵌 plotly.js）。"""
    cards = "".join(
        f'<div class="stat"><div class="v">{v}</div><div class="k">{k}</div></div>'
        for k, v in stats
    )
    body = []
    for i, (title, text, fig) in enumerate(sections):
        div = pio.to_html(fig, full_html=False, include_plotlyjs=(i == 0))
        body.append(
            f'<section class="card"><h2>{title}</h2><p class="desc">{text}</p>{div}</section>'
        )
    html = (
        "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>ETF 轮动回测可视化报告</title>"
        "<style>"
        ":root{--ink:#2c3e50;--muted:#7f8c8d;--bg:#f5f6f8;--card:#ffffff;--line:#e6e9ef;--accent:#2c6fbb}"
        f"*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:'{FONT}';line-height:1.7}}"
        ".wrap{max-width:1080px;margin:0 auto;padding:36px 20px 64px}"
        "header h1{margin:0 0 4px;font-size:26px}"
        "header .sub{color:var(--muted);margin:0 0 20px}"
        ".stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:20px 0 8px}"
        ".stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}"
        ".stat .v{font-size:22px;font-weight:600;color:var(--accent)}"
        ".stat .k{font-size:13px;color:var(--muted)}"
        ".card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin-top:18px;box-shadow:0 1px 2px rgba(0,0,0,.03)}"
        ".card h2{margin:0 0 6px;font-size:19px;color:var(--ink)}"
        ".card .desc{margin:0 0 10px;color:var(--muted);font-size:14px}"
        "footer{color:var(--muted);font-size:12px;margin-top:24px;text-align:center}"
        "</style></head><body><div class='wrap'>"
        "<header><h1>ETF 轮动回测可视化报告</h1><p class='sub'>" + subtitle + "</p></header>"
        "<div class='stats'>" + cards + "</div>"
        + "".join(body)
        + "<footer>由 scripts/run_report.py 生成 · 数据源 tushare</footer></div></body></html>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")

