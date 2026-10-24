"""store_run 唯一写入口测试：档位、幂等升级、冲突保护、失败原子性、镜像。

关键纪律（计划 §1.2）：
- 暂存目录写满 → 校验 → `os.rename` 原子改名，失败不得留下半成品；
- 已存在的 run 只在「逐产物 sha256 相同 + 指标相对差 ≤ 1e-9」时补写（档位升级），
  任何不一致抛 ArtifactConflictError，绝不覆盖原始结果；
- `attempts.jsonl` 每次写入追加一行，重跑可审计。
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from etf_rotation.evaluation import artifacts


def _frames():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    return {"equity": pd.DataFrame({"nav": [1.0, 1.01]}, index=idx),
            "weights": pd.DataFrame({"A": [0.5, 0.5]}, index=idx),
            "holdings": pd.DataFrame({"A": [0.5, 0.5]}, index=idx),
            "transactions": pd.DataFrame({"Date": idx, "Security": ["A", "A"],
                                          "price": [1.0, 1.0], "quantity": [0.5, 0.5]}),
            "trades": pd.DataFrame({"date": idx, "ticker": ["A", "A"],
                                    "side": ["买入", "买入"], "cost": [0.001, 0.002]})}


def _store(tmp_path, profile, frames=None, sharpe=1.0, run_id="r1"):
    return artifacts.store_run(
        root=tmp_path / "runs", run_id=run_id, kind="backtest", profile=profile,
        meta={"kind": "backtest", "schema_version": 2,
              "created_at": "2026-10-24T00:00:00Z"},
        metrics={"sharpe": sharpe}, frames=frames if frames is not None else _frames())


def test_profile_contents(tmp_path):
    """minimal 只写登记文件；standard 写四类行情产物但不写逐笔明细。"""
    p = _store(tmp_path, "minimal")
    assert (p / "meta.parquet").exists() and not (p / "equity.parquet").exists()
    p = _store(tmp_path, "standard", run_id="r2")
    assert (p / "equity.parquet").exists() and not (p / "transactions.parquet").exists()
    assert (p / "metrics.parquet").exists() and (p / "artifacts.parquet").exists()
    assert (p / "manifest.json").exists()


def test_full_profile_writes_signal_subdir(tmp_path):
    """full 档的 diary/ticker_signals 落在 signals/ 子目录，路径映射固定。"""
    frames = _frames()
    idx = frames["equity"].index
    frames["diary"] = pd.DataFrame({"regime": ["range", "bull"]}, index=idx)
    frames["ticker_signals"] = pd.DataFrame({"weight": [0.5, 0.5]}, index=idx)
    p = _store(tmp_path, "full", frames=frames)
    assert (p / "signals" / "decision_diary.parquet").exists()
    assert (p / "signals" / "ticker_signals.parquet").exists()
    assert (p / "trades.parquet").exists()


def test_upgrade_profile_is_idempotent(tmp_path):
    """standard → full：同名产物字节一致，只补写缺失产物，attempts 两行。"""
    _store(tmp_path, "standard")
    p = _store(tmp_path, "full")
    assert (p / "transactions.parquet").exists()
    assert (p / "trades.parquet").exists()
    assert (p / "attempts.jsonl").read_text(encoding="utf-8").count("\n") == 2
    # 档位只升不降：meta 记录 full
    meta = pd.read_parquet(p / "meta.parquet")
    assert meta.loc[0, "save_profile"] == "full"


def test_conflict_raises_and_keeps_original(tmp_path):
    """同名产物内容不同 → 冲突；原始文件不被覆盖，也不留临时文件。"""
    first = _store(tmp_path, "standard")
    original = (first / "equity.parquet").read_bytes()
    bad = _frames()
    bad["equity"] = bad["equity"] * 1.5
    with pytest.raises(artifacts.ArtifactConflictError):
        _store(tmp_path, "standard", frames=bad)
    assert (first / "equity.parquet").read_bytes() == original
    assert not list((tmp_path / "runs" / "r1").glob("*.tmp"))


def test_metric_drift_raises(tmp_path):
    """产物相同但指标差超过 1e-9 → 同样视为冲突（同一 run 不可能有两个 sharpe）。"""
    _store(tmp_path, "standard", sharpe=1.0)
    with pytest.raises(artifacts.ArtifactConflictError):
        _store(tmp_path, "standard", sharpe=1.0001)
    # 浮点噪声级差异放行
    _store(tmp_path, "standard", sharpe=1.0 + 1e-12)


def test_failure_leaves_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "write_frames",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        _store(tmp_path, "standard")
    assert not (tmp_path / "runs" / "r1").exists()
    assert not (tmp_path / "runs" / ".staging" / "r1").exists()


def test_unknown_frame_name_rejected(tmp_path):
    """frames 键必须在 full 档清单内：拼错的名字不能被静默丢弃。"""
    with pytest.raises(ValueError):
        _store(tmp_path, "standard", frames={"equityy": _frames()["equity"]})


def test_mirror_latest_and_resolve_run(tmp_path):
    """latest.json 指向最近一次 run；顶层兼容副本供既有脚本/报告继续读取。"""
    p = _store(tmp_path, "standard")
    artifacts.mirror_latest(p, tmp_path)

    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == "r1" and latest["profile"] == "standard"
    assert set(latest) == {"run_id", "family_id", "kind", "profile", "updated_at"}

    eq = pd.read_csv(tmp_path / "equity.csv", parse_dates=["ts"]).set_index("ts")
    assert eq["nav"].iloc[-1] == pytest.approx(1.01)
    assert (tmp_path / "weights.parquet").exists()
    assert (tmp_path / "holdings.csv").exists()
    metrics = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["sharpe"] == pytest.approx(1.0)
    # 未落盘的 trades/benchmark 不写、也不报错
    assert not (tmp_path / "trades.csv").exists()

    assert artifacts.resolve_run(tmp_path / "runs") == p
    assert artifacts.resolve_run(tmp_path / "runs", "r1") == p


def test_resolve_run_missing(tmp_path):
    _store(tmp_path, "standard")
    with pytest.raises(FileNotFoundError):
        artifacts.resolve_run(tmp_path / "runs", "nope")
    with pytest.raises(FileNotFoundError):
        artifacts.resolve_run(tmp_path / "runs")   # 还没有 latest.json
