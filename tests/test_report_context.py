"""ReportContext 加载契约：run 目录 → 只读上下文（计划 Task 7）。

纪律：
- 价格面板与分类一律走 `pipeline` / `universe` 的模块级函数，单测全部 monkeypatch，
  不读真实数据；
- 先校验 meta（schema_version、strict 时的 data_snapshot_id），再加载产物；
- 缺哪个产物字段就是 None，不抛异常；缺 `meta.parquet` 直接 FileNotFoundError。
"""
from __future__ import annotations

import pandas as pd
import pytest

from etf_rotation.report.context import ReportContext


def _make_run(tmp_path):
    from etf_rotation.evaluation import artifacts
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    frames = {"equity": pd.DataFrame({"nav": [1.0, 1.01], "returns": [0.0, 0.01],
                                      "cash": [1.0, 0.99], "turnover": [0.0, 0.0],
                                      "fees": [0.0, 0.0]}, index=idx),
              "weights": pd.DataFrame({"A": [1.0, 1.0]}, index=idx)}
    return artifacts.store_run(root=tmp_path, run_id="r1", kind="backtest", profile="standard",
                               meta={"kind": "backtest", "schema_version": 2,
                                     "data_snapshot_id": "d1", "run_id": "r1",
                                     "created_at": "2026-10-24T00:00:00Z"},
                               metrics={"sharpe": 1.0}, frames=frames)


def _patch_prices(monkeypatch):
    from etf_rotation import pipeline
    from etf_rotation.data import universe
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    prices = pd.DataFrame({"A": [10.0, 10.1]}, index=idx)
    monkeypatch.setattr(pipeline, "load_prices", lambda: (prices, prices, prices))
    monkeypatch.setattr(pipeline, "load_fund_basic", lambda: pd.DataFrame({"ts_code": ["A"]}))
    monkeypatch.setattr(universe, "classify", lambda _: {"A": "risk"})


def test_load_reads_run_dir_and_meta(tmp_path, monkeypatch):
    _patch_prices(monkeypatch)
    ctx = ReportContext.load(_make_run(tmp_path), strict_snapshot=False)
    assert ctx.run_id == "r1"
    assert ctx.equity["nav"].iloc[-1] == 1.01
    assert ctx.stages is None


def test_missing_meta_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReportContext.load(tmp_path / "nope")


def test_strict_snapshot_rejects_mismatch(tmp_path, monkeypatch):
    from etf_rotation.data import snapshot
    _patch_prices(monkeypatch)
    monkeypatch.setattr(snapshot, "data_snapshot_id", lambda: "other")
    with pytest.raises(RuntimeError):
        ReportContext.load(_make_run(tmp_path), strict_snapshot=True)


def test_metrics_loaded_from_long_table(tmp_path, monkeypatch):
    """契约补充：metrics 从 metrics.parquet 长表读成 {metric: value}（Task 11 要用 total_fees）。"""
    _patch_prices(monkeypatch)
    ctx = ReportContext.load(_make_run(tmp_path), strict_snapshot=False)
    assert ctx.metrics == {"sharpe": 1.0}


def test_missing_metrics_file_yields_empty_dict(tmp_path, monkeypatch):
    _patch_prices(monkeypatch)
    run_dir = _make_run(tmp_path)
    (run_dir / "metrics.parquet").unlink()
    ctx = ReportContext.load(run_dir, strict_snapshot=False)
    assert ctx.metrics == {}
