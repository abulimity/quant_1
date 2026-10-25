"""runner / serialize 契约：派生产物原子落地 + index.json 可追溯（计划 Task 7）。

纪律：
- 单步失败不抛异常，只把 `ok=False, error=...` 写进 index.json；index.json 永远写成功；
- index.json 必须带 run_id 与 inputs（产物 name→sha256），派生数据可自证归属；
- 派生 JSON 必须通过 `json.dumps(..., allow_nan=False)`，不允许 "NaN" 字样。
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from etf_rotation.report import runner
from etf_rotation.report.context import ReportContext


def _ctx(benchmark=True):
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    b = pd.Series(np.sin(np.arange(30)) * 0.01, index=idx)
    return ReportContext(run_id="r1", meta={"data_snapshot_id": "d1"}, params={},
                         equity=pd.DataFrame({"nav": (1 + b).cumprod(), "returns": b}, index=idx),
                         benchmark=pd.DataFrame({"hs300": (1 + b).cumprod()}, index=idx)
                         if benchmark else None,
                         weights=None, holdings=None, trades=None,
                         transactions=None, diary=None, ticker_signals=None, stages=None,
                         classification={}, close=None, opn=None, amount=None)


def test_index_has_run_id_and_inputs(tmp_path):
    ctx = _ctx()
    out = runner.run(tmp_path, ctx, only=["alignment"], mirror_to=None)
    idx_json = json.loads((tmp_path / "derived" / "index.json").read_text(encoding="utf-8"))
    assert idx_json["run_id"] == "r1"
    assert idx_json["steps"]["alignment"]["ok"] is True
    assert "inputs" in idx_json
    assert "NaN" not in (tmp_path / "derived" / "alignment.json").read_text(encoding="utf-8")
    assert out["alignment"]["ok"] is True


def test_alignment_lags_are_sorted_by_lag_value(tmp_path):
    """滞后序列必须按 lag 数值升序（-5…5），否则前端横轴会变成 0,1,-1,2…。"""
    runner.run(tmp_path, _ctx(), only=["alignment"])
    payload = json.loads((tmp_path / "derived" / "alignment.json").read_text(encoding="utf-8"))
    assert payload["lags"] == sorted(payload["lags"])
    assert len(payload["lags"]) == len(payload["corrs"])


def test_step_failure_is_recorded_not_raised(tmp_path):
    ctx = _ctx(benchmark=False)   # alignment 缺基准 → RuntimeError
    out = runner.run(tmp_path, ctx, only=["alignment"])
    idx_json = json.loads((tmp_path / "derived" / "index.json").read_text(encoding="utf-8"))
    assert out["alignment"]["ok"] is False
    assert idx_json["steps"]["alignment"]["ok"] is False
    assert "benchmark" in idx_json["steps"]["alignment"]["error"]


def test_inputs_come_from_artifacts_parquet(tmp_path):
    from etf_rotation.evaluation import artifacts

    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    run_dir = artifacts.store_run(
        root=tmp_path / "runs", run_id="r2", kind="backtest", profile="standard",
        meta={"kind": "backtest", "schema_version": 2, "data_snapshot_id": "d2",
              "created_at": "2026-10-24T00:00:00Z"},
        metrics={"sharpe": 1.0},
        frames={"equity": pd.DataFrame({"nav": [1.0, 1.01], "returns": [0.0, 0.01]}, index=idx)})
    ctx = _ctx()
    ctx.run_id = "r2"
    runner.run(run_dir, ctx, only=["alignment"])
    idx_json = json.loads((run_dir / "derived" / "index.json").read_text(encoding="utf-8"))
    assert set(idx_json["inputs"]) == {"equity"}
    assert len(idx_json["inputs"]["equity"]) == 64


def test_mirror_copies_derived_tree(tmp_path):
    mirror = tmp_path / "reports" / "derived"
    runner.run(tmp_path / "runs" / "r1", _ctx(), only=["alignment"], mirror_to=mirror)
    assert (mirror / "index.json").exists()
    assert (mirror / "alignment.json").exists()


def test_should_mirror_only_for_latest():
    assert runner.should_mirror("r1", "r1") is True
    assert runner.should_mirror("r0", "r1") is False
    assert runner.should_mirror("r0", "r1", force=True) is True
    assert runner.should_mirror("r0", None) is False


def test_mirror_derived_removes_stale_files(tmp_path):
    derived = tmp_path / "run" / "derived"
    mirror = tmp_path / "derived"
    derived.mkdir(parents=True)
    mirror.mkdir()
    (derived / "index.json").write_text("{}", encoding="utf-8")
    (mirror / "old_step.json").write_text("{}", encoding="utf-8")
    runner.mirror_derived(derived, mirror)
    assert (mirror / "index.json").exists()
    assert not (mirror / "old_step.json").exists()
