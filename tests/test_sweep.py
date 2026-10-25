"""网格 sweep 公共流程测试（主计划 Task 19）。

契约：
1. `sweep.iter_points` 是笛卡尔积，且与 dict 键序无关（按 key 排序）。
2. `run_sweep` 对每个点：算身份 → `store_run` → `write_family_member`，
   并在 meta 里注入 kind/family_id/campaign_id/save_profile；
   返回 `{family_id, n_trials, run_ids}`，不写 `latest.json`（网格不抢基准位置）。
3. `run_sweep` 传 `family={"kind", "spec"}`，`load_family` 能读回 kind/spec。
4. `collect_runs.family_summary` 单进程读成员 + metrics，写 summary.json，
   同时给出 family 内与 campaign 累计的 DSR；单 trial 时 DSR 为 null（可 JSON 落盘）。

全部用注入的 `run_one`，不跑真实回测。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

from etf_rotation.evaluation import registry, sweep

ROOT = Path(__file__).resolve().parents[1]


def _load_collect_runs():
    """按文件路径加载 scripts/collect_runs.py（scripts 不是包）。"""
    path = ROOT / "scripts" / "collect_runs.py"
    spec = importlib.util.spec_from_file_location("collect_runs_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_sweep(tmp_path, points, run_one, **kwargs):
    """测试用封装：固定窗口/口径，只让用例改 kind/campaign/spec。"""
    params = dict(
        points=points, run_one=run_one, kind="grid", profile="minimal",
        campaign_id="c1", tag="t", runs_root=tmp_path / "runs",
        families_root=tmp_path / "families", git_sha="abc",
        data_snapshot_id="d1", start="2024-01-01", end="2024-12-31",
        execution="open",
    )
    params.update(kwargs)
    return sweep.run_sweep(**params)


def test_run_sweep_writes_runs_and_family(tmp_path):
    points = [{"p": 1}, {"p": 2}]

    def run_one(point):
        return ({"schema_version": 2, "created_at": "2026-10-24T00:00:00Z", "n_obs": 10},
                {"sharpe": float(point["p"])}, {})

    out = _run_sweep(tmp_path, points, run_one)
    assert out["n_trials"] == 2
    assert len(out["run_ids"]) == 2

    fam = registry.load_family(tmp_path / "families", out["family_id"])
    assert fam["n_trials"] == 2
    assert fam["kind"] == "grid"
    assert fam["spec"] == {"p": [1, 2]}

    # run 目录与注入的 meta 身份键
    run_dir = tmp_path / "runs" / out["run_ids"][0]
    assert (run_dir / "meta.parquet").exists()
    meta = pd.read_parquet(run_dir / "meta.parquet").iloc[0].to_dict()
    assert meta["kind"] == "grid"
    assert meta["family_id"] == out["family_id"]
    assert meta["campaign_id"] == "c1"
    assert meta["save_profile"] == "minimal"
    assert meta["start"] == "2024-01-01"
    assert meta["end"] == "2024-12-31"
    assert meta["execution"] == "open"

    # 成员文件：一人一个 JSON，variant 记录该点参数
    member = json.loads(
        (tmp_path / "families" / out["family_id"] / "members" / f"{out['run_ids'][0]}.json")
        .read_text(encoding="utf-8"))
    assert member["run_id"] == out["run_ids"][0]
    assert member["variant"] == {"p": 1}
    assert member["campaign_id"] == "c1"

    # 网格不写 latest.json（只有 run_backtest 能抢基准位置）
    assert not (tmp_path / "latest.json").exists()


def test_family_id_is_order_independent():
    a = sweep.iter_points({"x": [1, 2], "y": [3, 4]})
    b = sweep.iter_points({"y": [3, 4], "x": [1, 2]})
    assert list(a) == list(b)


def test_iter_points_cartesian_and_sorted():
    points = list(sweep.iter_points({"y": [4, 3], "x": [1, 2]}))
    assert points == [
        {"x": 1, "y": 4}, {"x": 1, "y": 3},
        {"x": 2, "y": 4}, {"x": 2, "y": 3},
    ]


def test_run_sweep_overrides_identity_keys(tmp_path):
    def run_one(point):
        # run_one 返回的同名键必须被 sweep 覆盖
        return ({"kind": "backtest", "family_id": "old", "campaign_id": "old",
                 "save_profile": "full", "n_obs": 5,
                 "params_json": {"a": point["a"]}},
                {"sharpe": 1.0}, {})

    out = _run_sweep(tmp_path, [{"a": 1}], run_one,
                     kind="cost", campaign_id="c9", profile="minimal")
    meta = pd.read_parquet(
        tmp_path / "runs" / out["run_ids"][0] / "meta.parquet").iloc[0].to_dict()
    assert meta["kind"] == "cost"
    assert meta["family_id"] == out["family_id"]
    assert meta["campaign_id"] == "c9"
    assert meta["save_profile"] == "minimal"


def test_run_sweep_explicit_spec_and_base_params_change_family(tmp_path):
    def run_one(point):
        return ({"n_obs": 10}, {"sharpe": 1.0}, {})

    kw = dict(points=[{"p": 1}], run_one=run_one, kind="grid", profile="minimal",
              campaign_id="c1", tag="", runs_root=tmp_path / "runs",
              families_root=tmp_path / "families", git_sha="abc",
              data_snapshot_id="d1", start="2024-01-01", end="2024-12-31",
              execution="open", spec={"p": [1, 2]})
    a = sweep.run_sweep(**kw)
    b = sweep.run_sweep(**dict(kw, base_params={"risk": 0.3}))
    assert a["family_id"] != b["family_id"]
    fam = registry.load_family(tmp_path / "families", a["family_id"])
    assert fam["spec"] == {"p": [1, 2]}


def test_run_sweep_dedupes_identical_configs(tmp_path):
    """同一配置出现两次（如多个假设维度都取默认值）→ 一个 run、一个成员。"""
    def run_one(point):
        return ({"n_obs": 10}, {"sharpe": 1.0}, {})

    out = _run_sweep(tmp_path, [{"a": 1}, {"a": 1}, {"a": 2}], run_one)
    assert out["n_trials"] == 2
    assert len(out["run_ids"]) == 2
    assert [t["run_id"] for t in out["trials"]] == [
        out["run_ids"][0], out["run_ids"][0], out["run_ids"][1]]
    members = sorted(p.name for p in
                     (tmp_path / "families" / out["family_id"] / "members").iterdir())
    assert members == [f"{run_id}.json" for run_id in sorted(out["run_ids"])]


def test_run_sweep_drops_nonfinite_metrics(tmp_path):
    """短区间 yearly_sortino 可能为 inf：指标表只收有限数，其余记入 meta。"""
    def run_one(point):
        return ({"n_obs": 10},
                {"sharpe": 1.0, "yearly_sortino": float("inf"),
                 "yearly_vol": float("nan")}, {})

    out = _run_sweep(tmp_path, [{"p": 1}], run_one)
    met = pd.read_parquet(tmp_path / "runs" / out["run_ids"][0] / "metrics.parquet")
    assert list(met["metric"]) == ["sharpe"]
    meta = pd.read_parquet(
        tmp_path / "runs" / out["run_ids"][0] / "meta.parquet").iloc[0].to_dict()
    assert meta["nonfinite_metrics"] == '["yearly_sortino", "yearly_vol"]'


def test_collect_runs_family_summary(tmp_path):
    collect_runs = _load_collect_runs()
    points = [{"p": 0.1}, {"p": 0.2}, {"p": 0.3}]

    def run_one(point):
        return ({"n_obs": 100},
                {"sharpe": float(point["p"]), "max_drawdown": -0.1}, {})

    out = _run_sweep(tmp_path, points, run_one, spec={"p": [0.1, 0.2, 0.3]})
    summary = collect_runs.family_summary(
        tmp_path / "families", tmp_path / "runs", out["family_id"])

    assert summary["family_id"] == out["family_id"]
    assert summary["n_trials"] == 3
    assert summary["robustness"] == 1.0
    assert summary["dsr_family"] is not None
    assert summary["dsr_campaign"] is not None
    assert summary["n_campaign_trials"] == 3
    assert summary["best"]["p"] == 0.3

    path = tmp_path / "families" / out["family_id"] / "summary.json"
    assert path.exists()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["n_trials"] == 3
    assert on_disk["dsr_family"] == summary["dsr_family"]


def test_collect_runs_single_trial_is_json_safe(tmp_path):
    collect_runs = _load_collect_runs()

    def run_one(point):
        return ({"n_obs": 100}, {"sharpe": 0.5}, {})

    out = _run_sweep(tmp_path, [{"p": 1}], run_one, spec={"p": [1]})
    summary = collect_runs.family_summary(
        tmp_path / "families", tmp_path / "runs", out["family_id"])
    assert summary["dsr_family"] is None          # 单个 trial 无法定义选择偏差
    assert summary["best"]["sharpe"] == 0.5
    text = (tmp_path / "families" / out["family_id"] / "summary.json").read_text(encoding="utf-8")
    json.loads(text)                              # 不允许 NaN/Inf


def test_collect_runs_campaign_accumulates_across_families(tmp_path):
    collect_runs = _load_collect_runs()

    def run_one(point):
        return ({"n_obs": 100}, {"sharpe": float(next(iter(point.values())))}, {})

    a = _run_sweep(tmp_path, [{"p": 0.1}, {"p": 0.2}], run_one,
                   spec={"p": [0.1, 0.2]}, campaign_id="camp")
    b = _run_sweep(tmp_path, [{"q": 0.1}, {"q": 0.2}], run_one,
                   spec={"q": [0.1, 0.2]}, campaign_id="camp")
    assert a["family_id"] != b["family_id"]
    summary = collect_runs.family_summary(
        tmp_path / "families", tmp_path / "runs", b["family_id"])
    assert summary["n_trials"] == 2
    assert summary["n_campaign_trials"] == 4
