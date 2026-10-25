"""产物校验与清理契约测试（计划 Task 21）。

纪律（D-finalize 阶段 1「注意」）：
- `verify.verify` 返回**问题清单**，空列表才算通过；校验过程不改动任何文件；
- 篡改一个字节就必须点名该文件（sha256 是唯一判据，不看 mtime/大小猜测）；
- `total_fees` 与 `trades.cost.sum()` 的相对误差 ≥ 0.5% 必须**报错**而不是警告；
- `derived/index.json` 的 `inputs` 必须与当前产物哈希逐项一致，否则视为派生数据串台；
- `prune.prune` 默认 `dry_run=True`；只删档位允许的大文件，保留
  meta/metrics/artifacts/manifest 与 weights；真正删除后给 meta 打 `pruned=TRUE`，
  此时 verify 不再把「已清理的产物缺失」当成问题。
"""
from __future__ import annotations

import json

import ffn
import pandas as pd
import pytest

from etf_rotation.evaluation import artifacts, prune, verify


def _nav():
    """6 个交易日的净值：有涨有跌，保证 sharpe 有定义。"""
    idx = pd.bdate_range("2024-01-02", periods=6)
    return pd.Series([1.0, 1.012, 1.004, 1.02, 1.015, 1.031], index=idx)


def _frames(nav=None):
    nav = _nav() if nav is None else nav
    returns = nav.pct_change(fill_method=None).fillna(0.0)
    fees = pd.Series([0.0, 0.001, 0.0, 0.0, 0.0, 0.0], index=nav.index)
    return {
        "equity": pd.DataFrame({"nav": nav, "returns": returns, "cash": 0.1,
                                "turnover": 0.0, "fees": fees}),
        "weights": pd.DataFrame({"A": 1.0, "B": 0.0}, index=nav.index),
        "holdings": pd.DataFrame({"A": 1.0, "B": 0.0}, index=nav.index),
        "benchmark": pd.DataFrame({"benchmark": nav, "hs300": nav}, index=nav.index),
        "transactions": pd.DataFrame({"Date": [nav.index[1]], "Security": ["A"],
                                      "price": [1.0], "quantity": [10.0]}),
        "trades": pd.DataFrame({"date": [nav.index[1]], "ticker": ["A"],
                                "side": ["买入"], "price": [1.0], "quantity": [10.0],
                                "notional": [10.0], "cost": [0.001]}),
    }


def _metrics(nav, total_fees=0.001, sharpe=None):
    """与 equity 自洽的指标：ann_return/sharpe 用 ffn 从净值重算。"""
    returns = nav.pct_change(fill_method=None).dropna()
    recomputed = float(ffn.calc_sharpe(returns, rf=0.0, nperiods=252))
    return {
        "ann_return": float(ffn.calc_cagr(nav)),
        "sharpe": recomputed if sharpe is None else sharpe,
        "total_fees": float(total_fees),
    }


def _store(tmp_path, *, run_id="r1", profile="full", metrics=None, frames=None,
           created_at="2026-10-24T00:00:00+00:00"):
    frames = _frames() if frames is None else frames
    nav = frames["equity"]["nav"]
    return artifacts.store_run(
        root=tmp_path / "runs", run_id=run_id, kind="backtest", profile=profile,
        meta={"schema_version": 2, "created_at": created_at},
        metrics=_metrics(nav) if metrics is None else metrics, frames=frames)


def _write_index(run_dir, inputs, run_id="r1"):
    """按 runner 的格式写一份最小 derived/index.json（verify 只读这份契约）。"""
    derived = run_dir / "derived"
    derived.mkdir(exist_ok=True)
    payload = {"schema_version": 1, "derived_version": 1, "run_id": run_id,
               "generated_at": "2026-10-24T00:00:00+00:00",
               "data_snapshot_id": "snap", "inputs": inputs, "steps": {}}
    (derived / "index.json").write_text(json.dumps(payload), encoding="utf-8")


def _artifact_hashes(run_dir):
    df = pd.read_parquet(run_dir / "artifacts.parquet")
    return {str(n): str(h) for n, h in zip(df["name"], df["sha256"])}


# ── verify：哈希 ────────────────────────────────────────────────────────

def test_verify_passes_on_clean_run(tmp_path):
    _store(tmp_path)
    assert verify.verify(tmp_path / "runs", "r1") == []


def test_verify_detects_tampering(tmp_path):
    """改一个字节 → 必须点名该产物（计划 Task 21 Step 1 的原始用例）。"""
    p = _store(tmp_path)
    (p / "equity.parquet").write_bytes(b"broken")
    problems = verify.verify(tmp_path / "runs", "r1")
    assert any("equity" in msg for msg in problems)


def test_verify_detects_missing_artifact(tmp_path):
    p = _store(tmp_path)
    (p / "weights.parquet").unlink()
    problems = verify.verify(tmp_path / "runs", "r1")
    assert any("weights" in msg for msg in problems)


def test_verify_missing_run(tmp_path):
    _store(tmp_path)
    problems = verify.verify(tmp_path / "runs", "nope")
    assert problems and any("nope" in msg for msg in problems)


def test_verify_all_runs_when_no_run_id(tmp_path):
    """不给 run_id 时扫全部 run；只有被破坏的那一个出现在问题里。"""
    _store(tmp_path, run_id="good")
    bad = _store(tmp_path, run_id="bad")
    (bad / "holdings.parquet").write_bytes(b"broken")
    problems = verify.verify(tmp_path / "runs")
    assert problems
    assert all("bad" in msg for msg in problems)


# ── verify：total_fees 对账（0.5% 容差，超了算错）──────────────────────

def test_verify_flags_fee_mismatch_beyond_tolerance(tmp_path):
    nav = _nav()
    _store(tmp_path, run_id="bad", metrics=_metrics(nav, total_fees=0.02))
    problems = verify.verify(tmp_path / "runs", "bad")
    assert any("total_fees" in msg for msg in problems)


def test_verify_accepts_fee_drift_inside_tolerance(tmp_path):
    """0.4% 的出入仍属「对得上账」（引擎 fees 与逐笔估算的求和顺序差异）。"""
    nav = _nav()
    _store(tmp_path, metrics=_metrics(nav, total_fees=0.001 * 1.004))
    assert verify.verify(tmp_path / "runs", "r1") == []


# ── verify：metrics 与 equity 重算值 ────────────────────────────────────

def test_verify_flags_metric_drift(tmp_path):
    """指标被人为改过（sharpe=0）→ 与 equity 重算值不符。"""
    _store(tmp_path, metrics=_metrics(_nav(), sharpe=0.0))
    problems = verify.verify(tmp_path / "runs", "r1")
    assert any("sharpe" in msg for msg in problems)


# ── verify：derived/index.json 溯源 ─────────────────────────────────────

def test_verify_accepts_matching_derived_inputs(tmp_path):
    p = _store(tmp_path)
    _write_index(p, _artifact_hashes(p))
    assert verify.verify(tmp_path / "runs", "r1") == []


def test_verify_flags_stale_derived_inputs(tmp_path):
    p = _store(tmp_path)
    inputs = _artifact_hashes(p)
    inputs["equity"] = "0" * 64          # 派生数据是上一版产物算出来的
    _write_index(p, inputs)
    problems = verify.verify(tmp_path / "runs", "r1")
    assert any("derived" in msg for msg in problems)


def test_verify_flags_derived_for_other_run(tmp_path):
    p = _store(tmp_path)
    _write_index(p, _artifact_hashes(p), run_id="other")
    problems = verify.verify(tmp_path / "runs", "r1")
    assert any("derived" in msg and "run_id" in msg for msg in problems)


# ── prune：默认 dry-run，只删允许的大文件 ──────────────────────────────

def _old(tmp_path):
    """90 天前的 run：prune 的默认年龄窗口之外。"""
    return _store(tmp_path, run_id="old", profile="standard",
                  created_at="2026-01-01T00:00:00+00:00")


def test_prune_dry_run_is_default_and_touches_nothing(tmp_path):
    p = _old(tmp_path)
    before = {f.name for f in p.glob("*.parquet")}
    actions = prune.prune(tmp_path / "runs")
    assert actions and any("old" in line for line in actions)
    assert {f.name for f in p.glob("*.parquet")} == before
    assert not prune._is_pruned(pd.read_parquet(p / "meta.parquet").iloc[0].to_dict())


def test_prune_removes_only_allowed_files(tmp_path):
    p = _old(tmp_path)
    actions = prune.prune(tmp_path / "runs", dry_run=False)
    assert actions
    # 大文件被清掉
    assert not (p / "equity.parquet").exists()
    assert not (p / "holdings.parquet").exists()
    # 登记与对账依据、下游归因唯一输入必须留着
    for name in ("meta.parquet", "metrics.parquet", "artifacts.parquet",
                 "manifest.json", "weights.parquet"):
        assert (p / name).exists(), name
    assert prune._is_pruned(pd.read_parquet(p / "meta.parquet").iloc[0].to_dict())
    # artifacts.parquet 是「当初写了什么」的审计记录，不随清理改写
    assert "equity" in _artifact_hashes(p)


def test_prune_keeps_full_profile(tmp_path):
    """full 档是出报告的口径，keep_profiles 默认保留，一个字节都不动。"""
    p = _store(tmp_path, run_id="keep", profile="full",
               created_at="2026-01-01T00:00:00+00:00")
    actions = prune.prune(tmp_path / "runs", dry_run=False)
    assert actions == []
    assert (p / "equity.parquet").exists() and (p / "trades.parquet").exists()


def test_prune_respects_age_window(tmp_path):
    """默认 90 天窗口内的 run 不动（今天刚跑的 run 不该被清理）。"""
    p = _store(tmp_path, run_id="fresh", profile="standard")
    assert prune.prune(tmp_path / "runs", dry_run=False) == []
    assert (p / "equity.parquet").exists()


def test_pruned_run_still_passes_verify(tmp_path):
    """清理过的 run：缺失的是「已清理」而不是「丢失」，verify 不该报错。"""
    p = _old(tmp_path)
    prune.prune(tmp_path / "runs", dry_run=False)
    assert verify.verify(tmp_path / "runs", "old") == []


def test_verify_skips_pre_v2_runs(tmp_path):
    """pre-v2 的旧 run 只有 manifest.json：跳过，不让整体校验失败。"""
    legacy = tmp_path / "runs" / "legacy01"
    legacy.mkdir(parents=True)
    (legacy / "manifest.json").write_text("{}", encoding="utf-8")
    _store(tmp_path, run_id="v2", profile="standard")
    assert verify.verify(tmp_path / "runs") == []


def test_verify_reports_partial_v2_without_meta(tmp_path):
    """有 artifacts.parquet 却没有 meta.parquet：真损坏，必须点名。"""
    broken = tmp_path / "runs" / "broken01"
    broken.mkdir(parents=True)
    (broken / "artifacts.parquet").write_bytes(b"x")
    problems = verify.verify(tmp_path / "runs")
    assert any("broken01" in msg for msg in problems)
