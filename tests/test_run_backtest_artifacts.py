"""run_backtest 产物契约测试：指标全集与 equity 五列。

这两个函数是 Task 6 基准修复与后续报告派生的共同前置：
- `all_stats` 必须保留 ffn 全部数值统计（只做键名映射），否则派生层拿不到
  monthly_sharpe 等扩展指标；文本字段不得混进指标表。
- `equity` 固定五列 nav/returns/cash/turnover/fees：旧 run 只有前三个，
  ReportContext 会按 schema_version 拒绝读取，新 run 不许再缺列。
"""
from __future__ import annotations

import pandas as pd

from etf_rotation.evaluation import metrics


def test_all_stats_keeps_extra_ffn_columns():
    s = pd.Series({"cagr": 0.1, "daily_sharpe": 1.0, "daily_sortino": 1.2,
                   "max_drawdown": -0.1, "calmar": 1.0, "daily_vol": 0.1,
                   "monthly_sharpe": 0.9, "some_text": "x"})
    out = metrics.all_stats(s)
    assert out["sharpe"] == 1.0
    assert out["monthly_sharpe"] == 0.9
    assert out["ann_return"] == 0.1
    assert out["ann_vol"] == 0.1
    assert "some_text" not in out


def test_all_stats_skips_bool_and_nan():
    """bool 是 int 的子类，不能被当成数值指标；NaN/None 不进指标表（不适用即缺省）。"""
    s = pd.Series({"daily_sharpe": 1.0, "flag": True, "empty": None,
                   "nan_metric": float("nan")})
    out = metrics.all_stats(s)
    assert "flag" not in out
    assert "empty" not in out
    assert "nan_metric" not in out


def test_equity_frame_has_turnover_and_fees():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    nav = pd.Series([1.0, 1.01], index=idx)
    out = metrics.build_equity_frame(nav, nav.pct_change().fillna(0.0),
                                     pd.Series([1.0, 0.9], index=idx),
                                     pd.Series([0.0, 0.1], index=idx),
                                     pd.Series([0.0, 0.001], index=idx))
    assert list(out.columns) == ["nav", "returns", "cash", "turnover", "fees"]
    assert out.index.equals(idx)
    assert out["nav"].iloc[-1] == 1.01


def test_equity_frame_drops_bootstrap_turnover_row():
    """bt 的 turnover 带一行 bootstrap 日；equity 必须以 nav 为索引，不能取并集。

    否则 equity 首行是 nav=NaN，下游 nav.index[0]、滚动统计都会被污染。
    """
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    wider = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"])
    nav = pd.Series([1.0, 1.01], index=idx)
    turnover = pd.Series([0.0, 0.0, 0.1], index=wider)
    out = metrics.build_equity_frame(nav, nav.pct_change().fillna(0.0),
                                     pd.Series(0.1, index=idx), turnover,
                                     pd.Series(0.0, index=idx))
    assert out.index.equals(idx)
    assert out["nav"].notna().all()
    assert out["turnover"].tolist() == [0.0, 0.1]
