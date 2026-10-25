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
            kind: str = "grid", family_extra: dict | None = None) -> None:
    """登记一个成员，并确保 family.json 存在（search_pool 只扫有 family.json 的目录）。"""
    family = {"kind": kind, "campaign_id": campaign}
    if family_extra:
        family.update(family_extra)
    registry.write_family_member(fams_root, fid, rid, {}, campaign_id=campaign,
                                 family=family)


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
