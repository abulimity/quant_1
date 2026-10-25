"""collect_runs 的 campaign 汇总逻辑测试（审计整改 Task 1/2/7/8）。

纪律：
- `search_pool` 只收 `grid/ablation/assumption` 三类 family，按 `run_id` 去重；
- 污染 family（family.json 或成员 meta 带 `git_dirty`）不进搜索池；
- `cost_rows` 读成本 family 的成员 variant + metrics，按 bps 升序；
- `render_index` 输出 Markdown 表，含 family 数、campaign trial 数与缺成员清单。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from etf_rotation.evaluation import registry

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect_runs  # noqa: E402


def _run(runs_root: Path, run_id: str, sharpe: float, n_obs: int = 100) -> Path:
    """写一个最小 run 目录：只有 metrics.parquet + meta.parquet（够 search_pool 读）。"""
    d = runs_root / run_id
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"metric": ["sharpe"], "value": [sharpe]}).to_parquet(d / "metrics.parquet")
    pd.DataFrame({"n_obs": [n_obs]}).to_parquet(d / "meta.parquet")
    return d


def _member(fams_root: Path, fid: str, rid: str, campaign: str = "c1",
            kind: str = "grid", family_extra: dict | None = None,
            variant: dict | None = None) -> None:
    """登记一个成员，并确保 family.json 存在（search_pool 只扫有 family.json 的目录）。"""
    family = {"kind": kind, "campaign_id": campaign}
    if family_extra:
        family.update(family_extra)
    registry.write_family_member(fams_root, fid, rid, variant or {},
                                 campaign_id=campaign, family=family)


def test_search_pool_dedupes_run_shared_by_two_families(tmp_path):
    runs, fams = tmp_path / "runs", tmp_path / "families"
    _run(runs, "base", 0.9)
    _run(runs, "a", 0.8)
    _run(runs, "b", 1.0)
    for fid, members in (("f1", ["base", "a"]), ("f2", ["base", "b"])):
        for rid in members:
            _member(fams, fid, rid)
    sharpes, _ = collect_runs.search_pool(fams, runs, "c1")
    assert len(sharpes) == 3            # base 只算一次
    assert sorted(sharpes) == [0.8, 0.9, 1.0]


def test_search_pool_ignores_non_search_kinds(tmp_path):
    runs, fams = tmp_path / "runs", tmp_path / "families"
    _run(runs, "cost1", 0.5)
    _run(runs, "grid1", 0.7)
    _member(fams, "fc", "cost1", kind="cost")
    _member(fams, "fg", "grid1", kind="grid")
    sharpes, _ = collect_runs.search_pool(fams, runs, "c1")
    assert sharpes == [0.7]


def test_search_pool_skips_dirty_family(tmp_path):
    runs, fams = tmp_path / "runs", tmp_path / "families"
    _run(runs, "dirty1", 0.9)
    _member(fams, "fd", "dirty1", family_extra={"git_dirty": True, "dirty_hash": "h"})
    _run(runs, "clean1", 0.8)
    _member(fams, "fc", "clean1", family_extra={"git_dirty": False})
    sharpes, _ = collect_runs.search_pool(fams, runs, "c1")
    assert sharpes == [0.8]


def test_search_pool_skips_family_with_dirty_member_run(tmp_path):
    runs, fams = tmp_path / "runs", tmp_path / "families"
    _run(runs, "dirtyrun", 0.9)
    # 成员 run 的 meta 标 dirty，但 family.json 没标（当前线上状态）
    pd.DataFrame({"n_obs": [100], "git_dirty": [True]}).to_parquet(
        runs / "dirtyrun" / "meta.parquet")
    _member(fams, "fd", "dirtyrun")
    _run(runs, "cleanrun", 0.8)
    _member(fams, "fc", "cleanrun")
    sharpes, _ = collect_runs.search_pool(fams, runs, "c1")
    assert sharpes == [0.8]


def test_render_index_lists_families_and_missing():
    rows = [{"family_id": "f1", "kind": "grid", "campaign_id": "c1",
             "n_trials": 3, "n_campaign_trials": 43, "dsr_family": 0.99,
             "dsr_campaign": 0.98, "best_sharpe": 1.0, "git_dirty": False,
             "missing_members": []},
            {"family_id": "f2", "kind": "cost", "campaign_id": "c1",
             "n_trials": 4, "n_campaign_trials": 43, "dsr_family": None,
             "dsr_campaign": None, "best_sharpe": 0.9, "git_dirty": True,
             "missing_members": ["gone"]}]
    text = collect_runs.render_index(rows, "2026-10-25T00:00:00+00:00")
    assert "| family_id |" in text
    assert "f1" in text and "f2" in text
    assert "43" in text
    assert "gone" in text
    assert "dirty" in text.lower()


def test_index_rows_reports_missing_member(tmp_path):
    runs, fams = tmp_path / "runs", tmp_path / "families"
    _run(runs, "present", 0.9)
    _member(fams, "f1", "present")
    _member(fams, "f1", "absent")
    rows = collect_runs.index_rows(fams, runs)
    assert len(rows) == 1
    assert rows[0]["missing_members"] == ["absent"]
    assert rows[0]["n_trials"] == 2


def test_write_index_writes_markdown(tmp_path):
    runs, fams = tmp_path / "runs", tmp_path / "families"
    _run(runs, "m1", 0.9)
    _member(fams, "f1", "m1")
    out = collect_runs.write_index(fams, runs, tmp_path / "index.md")
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "f1" in text and "| family_id |" in text


def test_index_rows_flags_member_dirty(tmp_path):
    runs, fams = tmp_path / "runs", tmp_path / "families"
    _run(runs, "d", 0.9)
    pd.DataFrame({"n_obs": [100], "git_dirty": [True]}).to_parquet(
        runs / "d" / "meta.parquet")
    _member(fams, "f1", "d")
    rows = collect_runs.index_rows(fams, runs)
    assert rows[0]["git_dirty"] is True


def test_cost_rows_reads_family_members_sorted(tmp_path):
    runs, fams = tmp_path / "runs", tmp_path / "families"
    _run(runs, "c16", 0.5)
    _run(runs, "c0", 1.0)
    _member(fams, "fc", "c16", kind="cost", variant={"costs.one_side_bps": 16})
    _member(fams, "fc", "c0", kind="cost", variant={"costs.one_side_bps": 0})
    rows = collect_runs.cost_rows(fams, runs, "fc")
    assert [r["one_side_bps"] for r in rows] == [0, 16]
    assert rows[0]["run_id"] == "c0"
    assert collect_runs.latest_family(fams, "cost") == "fc"
