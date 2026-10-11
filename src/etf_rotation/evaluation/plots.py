"""回测结果可视化（plotly，交互式 HTML）。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

FONT = "Microsoft YaHei, SimHei, sans-serif"


def _style(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        font=dict(family=FONT),
        hovermode="x unified",
        template="plotly_white",
        margin=dict(l=60, r=20, t=50, b=40),
    )
    return fig


def equity_drawdown(nav: pd.Series) -> go.Figure:
    nav = nav.dropna()
    dd = (nav / nav.cummax() - 1) * 100
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25],
        vertical_spacing=0.04, subplot_titles=("策略净值", "回撤 %"),
    )
    fig.add_trace(
        go.Scatter(x=nav.index, y=nav.values, name="净值", line=dict(color="#1f77b4", width=1)),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=dd.index, y=dd.values, name="回撤", fill="tozeroy",
                   line=dict(color="#d62728", width=0.5)),
        row=2, col=1,
    )
    fig.update_layout(height=520)
    return _style(fig)


def rolling_sharpe(returns: pd.Series, windows=(63, 252)) -> go.Figure:
    r = returns.dropna()
    fig = go.Figure()
    for w in windows:
        roll = r.rolling(w).mean() / r.rolling(w).std() * np.sqrt(252)
        fig.add_trace(go.Scatter(x=roll.index, y=roll.values, name=f"{w} 日", line=dict(width=1)))
    fig.add_hline(y=0, line=dict(color="gray", width=0.6))
    fig.update_layout(title="滚动夏普", yaxis_title="Sharpe", height=380)
    return _style(fig)


def yearly_returns(returns: pd.Series) -> go.Figure:
    r = returns.dropna()
    yr = r.groupby(r.index.year).apply(lambda s: (1 + s).prod() - 1)
    colors = ["#d62728" if v < 0 else "#2ca02c" for v in yr]
    fig = go.Figure(
        go.Bar(x=[str(y) for y in yr.index], y=yr.values, marker_color=colors,
               text=[f"{v:.1%}" for v in yr.values], textposition="outside")
    )
    fig.update_layout(title="分年度收益", yaxis_title="收益 %", height=380)
    fig.update_yaxes(tickformat=".0%")
    return _style(fig)


def cost_sensitivity(sens: pd.DataFrame) -> go.Figure:
    x = sens["cost_bps"].astype(float)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=sens["ann_return"] * 100, mode="lines+markers",
                             name="年化收益 %"))
    fig.add_trace(go.Scatter(x=x, y=sens["calmar"], mode="lines+markers", name="Calmar"))
    fig.add_trace(go.Scatter(x=x, y=-sens["max_drawdown"] * 100, mode="lines+markers",
                             name="最大回撤 %（取正）"))
    fig.update_layout(title="成本敏感性", xaxis_title="单边成本 bp", height=380)
    return _style(fig)


def save_fig(fig: go.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(path, include_plotlyjs="cdn")


def write_dashboard(figs: list[go.Figure], path: Path, intro: str = "") -> None:
    parts = []
    for i, fig in enumerate(figs):
        title = fig.layout.title.text or ""
        if title:
            parts.append(f"<h2>{title}</h2>")
        parts.append(pio.to_html(fig, full_html=False, include_plotlyjs=(i == 0)))
    html = (
        "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
        "<title>ETF 轮动回测可视化</title>"
        f"<style>body{{font-family:'{FONT}';margin:2rem;max-width:1200px;margin-inline:auto;}}"
        "h1,h2{color:#222}</style></head><body>"
        f"<h1>ETF 轮动回测可视化</h1>{intro}" + "".join(parts) + "</body></html>"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")

