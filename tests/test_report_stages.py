"""决策阶段快照与事件瀑布归因（N5）契约（计划 Task 14）。

阶段顺序是语义的一部分，不可调换：

    candidate → overheat → cross_asset → defensive → phases → hysteresis → final

- `candidate`：风险池 HRP 配权后的逐日目标（过热退出前）；
- `overheat`：单 ETF 过热退出后；
- `cross_asset`：纳指/黄金腿按各自波动缩放后；
- `defensive`：防守仓承接剩余资金后（当日完整目标）；
- `phases`：五相位等权汇总后（进入平滑/约束链路）；
- `hysteresis`：整组迟滞判定后；
- `final`：组合波动上限缩放后（落进 weights 的最终目标）。

`stage_table` 把长表折成「标的 × 阶段」矩阵：`weights[i][j]` 是
`tickers[i]` 在 `stage_order[j]` 的权重，缺失阶段补 0；`totals` 为各阶段总权重，
用于画瀑布总量。
"""
from __future__ import annotations

import pandas as pd
import pytest

from etf_rotation import pipeline
from etf_rotation.evaluation import observability
from etf_rotation.report.steps import stages

STAGE_ORDER = ["candidate", "overheat", "cross_asset", "defensive",
               "phases", "hysteresis", "final"]


def test_stage_snapshot_filters_zero():
    assert pipeline._stage_snapshot({"A": 0.3, "B": 0.0, "C": -0.1}) == {"A": 0.3}


def test_build_stages_long_format():
    days = pd.date_range("2024-01-01", periods=2, freq="B")
    traces = [{"stages": {"candidate": {"A": 0.6}, "final": {"A": 0.5}}},
              {"stages": {"candidate": {"A": 0.4}, "final": {"A": 0.4}}}]
    df = observability.build_stages(traces, days)
    assert set(df.columns) == {"date", "ticker", "stage", "weight"}
    assert len(df) == 4
    assert df.loc[df["date"] == days[0], "weight"].sum() == pytest.approx(1.1)


def test_build_stages_empty_keeps_columns():
    df = observability.build_stages([], pd.DatetimeIndex([]))
    assert list(df.columns) == ["date", "ticker", "stage", "weight"]
    assert df.empty


def test_build_stages_skips_missing_stages():
    days = pd.date_range("2024-01-01", periods=1, freq="B")
    df = observability.build_stages([{"stages": {"final": {"A": 0.5, "B": 0.5}}}], days)
    assert set(df["stage"]) == {"final"}
    assert df["weight"].sum() == pytest.approx(1.0)


def test_stage_table_limits_to_top10():
    rows = [{"date": pd.Timestamp("2024-01-02"), "ticker": f"T{i:02d}",
             "stage": stg, "weight": w * (i + 1)}
            for i in range(12) for stg, w in [("candidate", 0.05), ("final", 0.04)]]
    out = stages.stage_table(pd.DataFrame(rows), [pd.Timestamp("2024-01-02")], top_n=10)
    assert out["stage_order"] == STAGE_ORDER
    assert len(out["events"][0]["tickers"]) == 10


def test_stage_table_matrix_and_totals():
    day = pd.Timestamp("2024-01-02")
    rows = [
        {"date": day, "ticker": "A", "stage": "candidate", "weight": 0.6},
        {"date": day, "ticker": "A", "stage": "final", "weight": 0.5},
        {"date": day, "ticker": "B", "stage": "candidate", "weight": 0.4},
        {"date": day, "ticker": "B", "stage": "defensive", "weight": 0.3},
    ]
    out = stages.stage_table(pd.DataFrame(rows), [day], top_n=10)

    assert out["events"][0]["date"] == "2024-01-02"
    # 按 max(weight) 排序：A(0.6) 在 B(0.4) 前
    assert out["events"][0]["tickers"] == ["A", "B"]
    matrix = out["events"][0]["weights"]
    assert len(matrix) == 2 and all(len(row) == len(STAGE_ORDER) for row in matrix)
    assert matrix[0][STAGE_ORDER.index("candidate")] == pytest.approx(0.6)
    assert matrix[0][STAGE_ORDER.index("final")] == pytest.approx(0.5)
    assert matrix[0][STAGE_ORDER.index("overheat")] == 0.0
    assert matrix[1][STAGE_ORDER.index("defensive")] == pytest.approx(0.3)

    totals = {row["stage"]: row["total_weight"] for row in out["totals"]}
    assert set(totals) == set(STAGE_ORDER)
    assert totals["candidate"] == pytest.approx(1.0)
    assert totals["defensive"] == pytest.approx(0.3)
    assert totals["hysteresis"] == pytest.approx(0.0)
    assert out["totals"][0]["date"] == "2024-01-02"
