"""回测结果可视化（plotly，自包含交互式 HTML，文字与图表混排）。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

FONT = "Microsoft YaHei, SimHei, sans-serif"

# 统一配色：蓝=主/净值，橙=Calmar，绿=正收益/中长窗，红=回撤/负收益
BLUE = "#2c6fbb"
BLUE_LIGHT = "#7fb3d5"
ORANGE = "#e67e22"
GREEN = "#27ae60"
RED = "#c0392b"
GRID = "#dfe4ea"


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


def equity_drawdown(nav: pd.Series) -> go.Figure:
    nav = nav.dropna()
    dd = (nav / nav.cummax() - 1) * 100
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28],
        vertical_spacing=0.04, subplot_titles=("策略净值", "回撤 %"),
    )
    fig.add_trace(
        go.Scatter(x=nav.index, y=nav.values, name="净值", line=dict(color=BLUE, width=1.4)),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=dd.index, y=dd.values, name="回撤", fill="tozeroy",
            line=dict(color=RED, width=0.6), fillcolor="rgba(192,57,43,0.18)",
        ),
        row=2, col=1,
    )
    fig.update_layout(height=520)
    return _style(fig, height=520)


def rolling_sharpe(returns: pd.Series, windows=(63, 252)) -> go.Figure:
    r = returns.dropna()
    fig = go.Figure()
    for w, color in zip(windows, (BLUE, GREEN)):
        roll = r.rolling(w).mean() / r.rolling(w).std() * np.sqrt(252)
        fig.add_trace(go.Scatter(x=roll.index, y=roll.values, name=f"{w} 日", line=dict(color=color, width=1.2)))
    fig.add_hline(y=0, line=dict(color="#b0b8c0", width=0.7, dash="dot"))
    fig.update_layout(title="滚动夏普", yaxis_title="Sharpe")
    return _style(fig)


def yearly_returns(returns: pd.Series) -> go.Figure:
    r = returns.dropna()
    yr = r.groupby(r.index.year).apply(lambda s: (1 + s).prod() - 1)
    colors = [RED if v < 0 else GREEN for v in yr]
    fig = go.Figure(
        go.Bar(
            x=[str(y) for y in yr.index], y=yr.values, marker_color=colors,
            text=[f"{v:.1%}" for v in yr.values], textposition="outside",
        )
    )
    fig.add_hline(y=0, line=dict(color="#b0b8c0", width=0.7, dash="dot"))
    fig.update_layout(title="分年度收益", yaxis_title="收益 %")
    fig.update_yaxes(tickformat=".0%")
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

