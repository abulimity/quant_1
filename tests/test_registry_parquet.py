"""parquet 登记层测试：一次 run 的 meta/metrics/artifacts 落盘与只读查询。

纪律（对应计划 §1.2/§1.3）：
- 读层只扫 `*/meta.parquet` 并跳过 `.` 开头的目录，所以暂存目录永远不会被查到；
- 空目录返回空表而不抛错（扫描型脚本必须先能容忍「还没有 run」）；
- run_id 的内容寻址必须对参数/代码/数据/执行口径/信号任一维度敏感。
"""
from __future__ import annotations

import pandas as pd
import pytest

from etf_rotation.evaluation import registry

_META = {"kind": "backtest", "schema_version": 2, "created_at": "2026-10-24T00:00:00Z"}


def _art(name="weights"):
    return registry.ArtifactInfo(name, f"{name}.parquet", "abc", 10, 3, 2)


def test_write_and_load_roundtrip(tmp_path):
    registry.write_run(tmp_path, "r1", _META, {"sharpe": 1.1, "ann_return": 0.1}, [_art()])
    runs = registry.load_runs(tmp_path)
    assert runs.loc[0, "run_id"] == "r1"
    assert runs.loc[0, "sharpe"] == 1.1
    assert runs.loc[0, "kind"] == "backtest"
    assert runs.loc[0, "schema_version"] == 2


def test_metrics_long_table(tmp_path):
    """load_metrics 返回长表（run_id, metric, value），供分布/敏感性聚合使用。"""
    registry.write_run(tmp_path, "r1", _META, {"sharpe": 1.1, "ann_return": 0.1}, [])
    met = registry.load_metrics(tmp_path)
    assert set(met.columns) >= {"run_id", "metric", "value"}
    assert set(met["metric"]) == {"sharpe", "ann_return"}
    assert float(met.loc[met["metric"] == "sharpe", "value"].iloc[0]) == 1.1


def test_empty_root_returns_empty(tmp_path):
    assert registry.load_runs(tmp_path).empty
    assert registry.load_metrics(tmp_path).empty
    # 目录都不存在也必须返回空表（curate 前/首次运行前的常态）
    assert registry.load_runs(tmp_path / "nope").empty


def test_content_hash_ignores_timestamp(tmp_path):
    a = registry.content_hash({"x": 1, "created_at": "A"}, {"s": 1.0}, {"w": "h"})
    b = registry.content_hash({"created_at": "B", "x": 1}, {"s": 1.0}, {"w": "h"})
    assert a == b
    c = registry.content_hash({"x": 2, "created_at": "A"}, {"s": 1.0}, {"w": "h"})
    assert a != c
    # 指标/产物哈希变化同样必须改变内容哈希
    assert registry.content_hash({"x": 1}, {"s": 2.0}, {"w": "h"}) != a
    assert registry.content_hash({"x": 1}, {"s": 1.0}, {"w": "z"}) != a


def test_load_skips_staging_and_hidden_dirs(tmp_path):
    """暂存目录（.staging）与任何点目录不得进入查询结果。"""
    registry.write_run(tmp_path / ".staging", "s1", _META, {"sharpe": 9.9}, [])
    registry.write_run(tmp_path, ".hidden", _META, {"sharpe": 8.8}, [])
    assert registry.load_runs(tmp_path).empty


def test_metrics_reject_non_numeric(tmp_path):
    with pytest.raises(TypeError):
        registry.write_run(tmp_path, "r1", _META, {"sharpe": "high"}, [])


def test_write_run_uses_argument_run_id(tmp_path):
    """run_id 以参数为准，meta 里残留的旧值不得覆盖（防串号）。"""
    registry.write_run(tmp_path, "r1", {**_META, "run_id": "stale"}, {"sharpe": 1.0}, [])
    assert registry.load_runs(tmp_path).loc[0, "run_id"] == "r1"
    assert (tmp_path / "r1" / "manifest.json").exists()


def test_run_identity_dimensioned():
    p = {"x": 1, "y": {"z": 2}}
    kw = dict(git_sha="g1", dirty_hash="", data_snapshot_id="d1",
              execution="close", signal_id="s1")
    id1 = registry.run_identity(p, **kw)
    # 参数键序无关（sort_keys）
    assert id1 == registry.run_identity({"y": {"z": 2}, "x": 1}, **kw)
    # 任一维度变化 → id 变化
    for field, val in [("execution", "open"), ("git_sha", "g2"), ("dirty_hash", "h1"),
                       ("data_snapshot_id", "d2"), ("signal_id", "s2")]:
        kw2 = dict(kw)
        kw2[field] = val
        assert registry.run_identity(p, **kw2) != id1, field
    # 参数本身变化 → id 变化
    assert registry.run_identity({"x": 2, "y": {"z": 2}}, **kw) != id1


def _git(cwd, *args):
    """在临时仓库里执行 git 命令（关掉全局配置，避免机器差异影响测试）。"""
    import os
    import subprocess
    env = {**os.environ, "HOME": str(cwd), "USERPROFILE": str(cwd),
           "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   text=True, env=env)


def test_git_info_ignores_generated_dirs(tmp_path, monkeypatch):
    """回测镜像会改写已被跟踪的 reports/metrics.json；这不得改变 dirty_hash。

    这是确定性要求的核心：同一 commit + 同参数重跑，run_id 必须不变。
    """
    (tmp_path / "reports").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "reports" / "metrics.json").write_text("{}", encoding="utf-8")
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", "commit", "-qm", "init")
    monkeypatch.setattr(registry, "ROOT", tmp_path)

    assert registry.git_info()[1] == ""
    # 回测自己改写 reports/ 下的已跟踪产物 → 仍视为干净
    (tmp_path / "reports" / "metrics.json").write_text('{"sharpe": 1}', encoding="utf-8")
    assert registry.git_info()[1] == ""
    # 源码改动 → 必须变脏，且不同改动得到不同哈希
    (tmp_path / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    dirty = registry.git_info()[1]
    assert dirty != ""
    (tmp_path / "src" / "a.py").write_text("x = 3\n", encoding="utf-8")
    assert registry.git_info()[1] != dirty
