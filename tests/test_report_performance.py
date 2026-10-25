"""水下曲线与回撤事件（N2）契约（计划 Task 8）。

口径：
- `underwater = nav / nav.cummax() - 1`（负数，0 表示在历史新高）；
- 一个回撤事件以「回到前高」为界：peak → trough → recovery；
  `recovery_date` 为 None 表示到样本结束仍未恢复；
- `depth` 是回撤幅度（**正数**，0.18 = -18%），`min_depth` 按它过滤浅回撤；
- duration_days = trough − peak，recovery_days = recovery − trough（日历日）。

另含 runner 的增量规则测试：`--only` 重跑只保留「同 run 同 inputs」的既有 step，
换 run 后不得继承旧产物（否则派生数据串台）。
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from etf_rotation.report import runner
from etf_rotation.report.context import ReportContext
from etf_rotation.report.steps import performance


def test_underwater_and_episode_bounds():
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    nav = pd.Series([1.0, 1.1, 0.9, 1.2, 1.0], index=idx)
    assert abs(performance.underwater(nav).loc[idx[2]] + 0.1818181818) < 1e-9
    row = performance.episodes(nav, min_depth=0.02).iloc[0]
    assert (row["peak_date"], row["trough_date"], row["recovery_date"]) == ("2024-01-02", "2024-01-03", "2024-01-04")
    assert row["recovered"] is True and row["duration_days"] == 1 and row["recovery_days"] == 1


def test_unrecovered_episode_has_null_recovery():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    ep = performance.episodes(pd.Series([1.0, 0.9, 0.8], index=idx))
    assert ep.iloc[0]["recovery_date"] is None and ep.iloc[0]["recovered"] is False


def test_episode_depth_is_positive_and_min_depth_filters():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    shallow = performance.episodes(pd.Series([1.0, 0.995, 1.0], index=idx), min_depth=0.02)
    assert shallow.empty
    deep = performance.episodes(pd.Series([1.0, 0.90, 1.0], index=idx), min_depth=0.02)
    assert deep.iloc[0]["depth"] == pytest.approx(0.10, abs=1e-12)


def test_annual_table_compounds_within_year():
    idx = pd.date_range("2023-06-01", periods=300, freq="B")
    r = pd.Series(np.linspace(-0.01, 0.01, 300), index=idx)
    eq = pd.DataFrame({"nav": (1 + r).cumprod(), "returns": r,
                       "turnover": 0.01, "fees": 0.001}, index=idx)
    ann = performance.annual_table(eq)
    assert ann["year"].tolist() == [2023, 2024]
    first = ann.iloc[0]
    expected = (1 + r[r.index.year == 2023]).prod() - 1
    assert first["return_pct"] == pytest.approx(expected, abs=1e-12)
    n2023 = int((r.index.year == 2023).sum())
    assert first["turnover"] == pytest.approx(0.01 * n2023, abs=1e-12)
    assert first["fees"] == pytest.approx(0.001 * n2023, abs=1e-12)


def test_monthly_table_has_one_row_per_month():
    idx = pd.date_range("2024-01-01", periods=90, freq="B")
    r = pd.Series(np.linspace(-0.002, 0.002, 90), index=idx)
    mon = performance.monthly_table(r)
    assert list(mon.columns) == ["year", "month", "return_pct"]
    assert len(mon) == r.index.to_period("M").nunique()
    first = mon.iloc[0]
    jan = r[(r.index.year == first["year"]) & (r.index.month == first["month"])]
    assert first["return_pct"] == pytest.approx((1 + jan).prod() - 1, abs=1e-12)


def test_longest_underwater_picks_widest_span():
    idx = pd.date_range("2024-01-01", periods=6, freq="B")
    nav = pd.Series([1.0, 1.2, 1.0, 0.9, 1.3, 1.1], index=idx)
    out = performance.longest_underwater(nav)
    assert out["peak_date"] == "2024-01-02"
    assert out["trough_date"] == "2024-01-04"
    assert out["recovery_date"] == "2024-01-05"
    assert out["total_days"] == 3


def _ctx(run_id="r1"):
    """runner 增量测试用的最小上下文（equity 五列齐全，benchmark 有 hs300）。"""
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    b = pd.Series(np.sin(np.arange(30)) * 0.01, index=idx)
    return ReportContext(run_id=run_id, meta={"data_snapshot_id": "d1"}, params={},
                         equity=pd.DataFrame({"nav": (1 + b).cumprod(), "returns": b,
                                              "cash": 0.0, "turnover": 0.01, "fees": 0.0},
                                             index=idx),
                         benchmark=pd.DataFrame({"hs300": (1 + b).cumprod()}, index=idx),
                         weights=None, holdings=None, trades=None, transactions=None,
                         diary=None, ticker_signals=None, stages=None, classification={},
                         close=None, opn=None, amount=None)


def test_incremental_only_keeps_only_same_run(tmp_path):
    run_dir = tmp_path / "r1"
    runner.run(run_dir, _ctx(), only=["alignment"])
    runner.run(run_dir, _ctx(), only=["performance"])
    assert (run_dir / "derived" / "alignment.json").exists()
    idx_json = json.loads((run_dir / "derived" / "index.json").read_text(encoding="utf-8"))
    assert set(idx_json["steps"]) == {"alignment", "performance"}

    runner.run(run_dir, _ctx(run_id="r9"), only=["performance"])
    assert not (run_dir / "derived" / "alignment.json").exists()
    idx_json = json.loads((run_dir / "derived" / "index.json").read_text(encoding="utf-8"))
    assert set(idx_json["steps"]) == {"performance"}
    assert idx_json["run_id"] == "r9"


def test_build_reports_max_drawdown_summary():
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    nav = pd.Series([1.0, 1.1, 0.9, 1.2, 1.0], index=idx)
    ctx = _ctx()
    ctx.equity = pd.DataFrame({"nav": nav, "returns": nav.pct_change().fillna(0.0),
                               "cash": 0.0, "turnover": 0.01, "fees": 0.0}, index=idx)
    out = performance.build(ctx)
    assert out["summary"]["max_drawdown"] == pytest.approx(0.9 / 1.1 - 1.0, abs=1e-12)
    assert out["summary"]["n_days"] == 5
