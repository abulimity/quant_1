"""family / trial 登记测试（主计划 Task 18）。

契约：
1. `registry.family_id` 确定性：同输入同 id，dict 键序无关；spec/campaign_id/
   execution 任一变化都要换 id。
2. `registry.write_family_member` 一个成员一个文件（`families/{fid}/members/
   {run_id}.json`），并行进程之间没有共享写；不残留临时文件。
3. `registry.load_family` 收集成员并给出 `n_trials`，同时带出 kind/spec。
4. `overfitting.campaign_trials` 统计同一 campaign_id 的成员文件数（跨 family 累加）。
"""
from __future__ import annotations

import json

from etf_rotation.evaluation import overfitting, registry


def _fid(kind="grid", spec=None, base=None, execution="open", campaign="c1"):
    return registry.family_id(
        kind, spec if spec is not None else {"dedupe.corr_threshold": [0.8, 0.85]},
        base if base is not None else {}, "2024-01-01", "2024-12-31",
        execution, "abc", "d1", campaign)


def test_family_members_and_trial_count(tmp_path):
    fid = _fid()
    for i in range(3):
        registry.write_family_member(tmp_path, fid, f"r{i}", {"p": i})
    fam = registry.load_family(tmp_path, fid)
    assert fam["n_trials"] == 3 and len(fam["members"]) == 3
    assert [m["run_id"] for m in fam["members"]] == ["r0", "r1", "r2"]


def test_campaign_trials_sums_across_families(tmp_path):
    for f in ("f1", "f2"):
        for i in range(2):
            registry.write_family_member(tmp_path, f, f"{f}-r{i}", {}, campaign_id="c1")
    assert overfitting.campaign_trials(tmp_path, "c1") == 4


def test_campaign_trials_dedupes_same_run_across_families(tmp_path):
    registry.write_family_member(tmp_path, "f1", "shared", {}, campaign_id="c1")
    registry.write_family_member(tmp_path, "f1", "a", {}, campaign_id="c1")
    registry.write_family_member(tmp_path, "f2", "shared", {}, campaign_id="c1")
    assert overfitting.campaign_trials(tmp_path, "c1") == 2


def test_family_id_is_deterministic_and_order_independent():
    a = registry.family_id("grid", {"x": [1, 2], "y": [3]}, {"b": 1, "a": 2},
                           "2024-01-01", "2024-12-31", "open", "abc", "d1", "c1")
    b = registry.family_id("grid", {"y": [3], "x": [1, 2]}, {"a": 2, "b": 1},
                           "2024-01-01", "2024-12-31", "open", "abc", "d1", "c1")
    c = registry.family_id("grid", {"y": [3], "x": [1, 2]}, {"a": 2, "b": 1},
                           "2024-01-01", "2024-12-31", "open", "abc", "d1", "")
    assert a == b
    assert a != c                                    # campaign 参与身份
    assert a != _fid(execution="close")              # 执行口径参与身份


def test_family_id_changes_with_each_identity_input():
    base = dict(kind="grid", spec={"a": [1]}, base_params={},
                start="2024-01-01", end="2024-12-31", execution="open",
                git_sha="abc", data_snapshot_id="d1", campaign_id="c1")
    fid = registry.family_id(**base)
    for key, value in [("kind", "sensitivity"), ("start", "2023-01-01"),
                       ("end", "2025-12-31"), ("execution", "close"),
                       ("git_sha", "def"), ("data_snapshot_id", "d2"),
                       ("campaign_id", "c2"), ("spec", {"a": [2]}),
                       ("base_params", {"b": 1})]:
        changed = dict(base, **{key: value})
        assert registry.family_id(**changed) != fid, key


def test_write_family_member_is_one_file_per_run(tmp_path):
    fid = _fid()
    registry.write_family_member(tmp_path, fid, "run-a", {"lr": 1}, campaign_id="c1")
    registry.write_family_member(tmp_path, fid, "run-b", {"lr": 2}, campaign_id="c1")

    members_dir = tmp_path / fid / "members"
    files = sorted(p.name for p in members_dir.iterdir())
    assert files == ["run-a.json", "run-b.json"]      # 没有共享汇总文件、没有 .tmp
    row = json.loads((members_dir / "run-a.json").read_text(encoding="utf-8"))
    assert row["run_id"] == "run-a"
    assert row["variant"] == {"lr": 1}
    assert row["campaign_id"] == "c1"
    assert row["family_id"] == fid


def test_load_family_reports_kind_spec_and_missing(tmp_path):
    fid = _fid()
    registry.write_family_member(
        tmp_path, fid, "r0", {}, campaign_id="c1",
        family={"kind": "grid", "spec": {"dedupe.corr_threshold": [0.8, 0.85]}})
    fam = registry.load_family(tmp_path, fid)
    assert fam["family_id"] == fid
    assert fam["kind"] == "grid"
    assert fam["spec"] == {"dedupe.corr_threshold": [0.8, 0.85]}

    empty = registry.load_family(tmp_path, "nope")
    assert empty["n_trials"] == 0 and empty["members"] == []


def test_campaign_trials_ignores_other_campaigns_and_tmp(tmp_path):
    fid = _fid()
    registry.write_family_member(tmp_path, fid, "r0", {}, campaign_id="c1")
    registry.write_family_member(tmp_path, fid, "r1", {}, campaign_id="c2")
    (tmp_path / fid / "members" / ".r2.json.tmp-1").write_text("{}", encoding="utf-8")
    assert overfitting.campaign_trials(tmp_path, "c1") == 1
    assert overfitting.campaign_trials(tmp_path, "c2") == 1
    assert overfitting.campaign_trials(tmp_path, "missing") == 0
    assert overfitting.campaign_trials(tmp_path / "no-such-root", "c1") == 0
