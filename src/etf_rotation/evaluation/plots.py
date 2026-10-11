"""回测结果可视化（matplotlib，静态 PNG）。"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd


def setup_cn_font() -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def equity_drawdown(nav: pd.Series):
    setup_cn_font()
    nav = nav.dropna()
    dd = (nav / nav.cummax() - 1) * 100
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(10, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax1.plot(nav.index, nav.values, lw=1, color="#1f77b4")
    ax1.set_ylabel("净值")
    ax1.set_title("策略净值")
    ax2.fill_between(dd.index, dd.values, 0, color="#d62728", alpha=0.5)
    ax2.set_ylabel("回撤 %")
    fig.tight_layout()
    return fig


def rolling_sharpe(returns: pd.Series, windows=(63, 252)):
    setup_cn_font()
    r = returns.dropna()
    fig, ax = plt.subplots(figsize=(10, 4))
    for w in windows:
        roll = r.rolling(w).mean() / r.rolling(w).std() * np.sqrt(252)
        ax.plot(roll.index, roll.values, lw=1, label=f"{w} 日")
    ax.axhline(0, color="gray", lw=0.6)
    ax.legend()
    ax.set_title("滚动夏普")
    ax.set_ylabel("Sharpe")
    fig.tight_layout()
    return fig


def yearly_returns(returns: pd.Series):
    setup_cn_font()
    r = returns.dropna()
    yr = r.groupby(r.index.year).apply(lambda s: (1 + s).prod() - 1)
    fig, ax = plt.subplots(figsize=(10, 4))
    colors = ["#d62728" if v < 0 else "#2ca02c" for v in yr]
    ax.bar([str(y) for y in yr.index], yr.values, color=colors)
    ax.axhline(0, color="gray", lw=0.6)
    ax.set_title("分年度收益")
    ax.set_ylabel("收益 %")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0))
    fig.tight_layout()
    return fig


def cost_sensitivity(sens: pd.DataFrame):
    setup_cn_font()
    fig, ax = plt.subplots(figsize=(10, 4))
    x = sens["cost_bps"].astype(float)
    ax.plot(x, sens["ann_return"] * 100, marker="o", label="年化收益 %")
    ax.plot(x, sens["calmar"], marker="s", label="Calmar")
    ax.plot(x, -sens["max_drawdown"] * 100, marker="^", label="最大回撤 %（取正）")
    ax.set_xlabel("单边成本 bp")
    ax.set_title("成本敏感性")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def save_fig(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)

