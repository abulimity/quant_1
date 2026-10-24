"""派生数据 runner：发现 step、原子写盘、生成 index.json（计划 Task 7）。

流程：
    发现 `steps/` 下所有模块（`NAME` + `build(ctx)`）
    → 在 `derived/.tmp` 写本次 step 的 JSON
    → `index.json` 最后写（永远写成功，单步失败只记 `ok=False`）
    → `rmtree(derived)` + `os.rename(.tmp, derived)` 原子替换
    → 可选把整棵 derived 镜像到 `reports/derived/`

为什么不直接写 `derived/`：读者可能正好在写盘中途打开 JSON；临时目录换名后
`derived/` 要么是旧版本、要么是新版本，不会出现半份文件。

增量规则（`only`）：旧 `index.json` 的 `run_id` 与 `inputs` 与本次一致时，
未重跑的 step 文件与状态原样保留；不一致（换 run / 换产物）则一律不继承，
避免派生数据串台。
"""
from __future__ import annotations

import importlib
import json
import os
import pkgutil
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from etf_rotation.report import serialize
from etf_rotation.report import steps as steps_pkg
from etf_rotation.report.context import ReportContext

# 派生数据自身的 schema 版本（与 run 的 meta.schema_version 无关）
INDEX_SCHEMA_VERSION = 1
DERIVED_VERSION = 1

INDEX_NAME = "index.json"


def available_steps() -> dict[str, str]:
    """发现 step 模块：`{NAME: 模块导入名}`，按 NAME 排序（与文件系统枚举顺序无关）。"""
    found = {}
    for info in pkgutil.iter_modules(steps_pkg.__path__):
        module = importlib.import_module(f"{steps_pkg.__name__}.{info.name}")
        name = getattr(module, "NAME", None)
        if not name:
            continue
        found[str(name)] = module.__name__
    return dict(sorted(found.items()))


def load_input_hashes(run_dir: Path) -> dict[str, str]:
    """index.json 的 inputs：取 `artifacts.parquet` 的 name→sha256；缺失时为空 dict。"""
    path = Path(run_dir) / "artifacts.parquet"
    if not path.exists():
        return {}
    df = pd.read_parquet(path)
    return {str(n): str(h) for n, h in zip(df["name"], df["sha256"])}


def run(run_dir: Path, ctx: ReportContext, only: list[str] | None = None,
        mirror_to: Path | None = None) -> dict[str, dict]:
    """跑 step 并写 `{run_dir}/derived/`，返回 `{step: {ok, duration_ms, error}}`。

    - `only`：只跑列出的 step（其余同 run 同输入的既有产物保留）；
    - 单步异常只记 `ok=False, error=str(exc)`，不中断其它 step，也不抛给调用方；
    - `mirror_to`：把整棵 derived 覆盖复制过去（生产为 `reports/derived`）。
    """
    run_dir = Path(run_dir)
    derived = run_dir / "derived"
    tmp = run_dir / ".derived.tmp"
    inputs = load_input_hashes(run_dir)

    steps = available_steps()
    if only is not None:
        unknown = sorted(set(only) - set(steps))
        if unknown:
            raise ValueError(f"未知 step {unknown}，可选 {sorted(steps)}")
        steps = {name: steps[name] for name in steps if name in set(only)}

    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    # 同 run 同输入的既有产物先搬进临时目录（增量重跑不丢其它 step）
    carried = _carry_over(derived, tmp, ctx.run_id, inputs)
    statuses = _carried_statuses(derived, ctx.run_id, inputs, carried)

    try:
        for name, module_name in steps.items():
            module = importlib.import_module(module_name)
            started = time.perf_counter()
            try:
                payload = module.build(ctx)
                payload = serialize.clean(payload)
                _write_json(tmp / f"{name}.json", payload)
                statuses[name] = {
                    "ok": True,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "error": None,
                }
            except Exception as exc:   # 单步失败不扩散：写好状态继续下一个
                statuses[name] = {
                    "ok": False,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "error": f"{type(exc).__name__}: {exc}",
                }

        index = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "derived_version": DERIVED_VERSION,
            "run_id": ctx.run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_snapshot_id": ctx.meta.get("data_snapshot_id"),
            "inputs": inputs,
            "steps": {name: statuses[name] for name in sorted(statuses)},
        }
        _write_json(tmp / INDEX_NAME, index)

        if derived.exists():
            shutil.rmtree(derived)
        os.rename(tmp, derived)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise

    if mirror_to is not None:
        mirror_to = Path(mirror_to)
        mirror_to.mkdir(parents=True, exist_ok=True)
        shutil.copytree(derived, mirror_to, dirs_exist_ok=True)

    return {name: statuses[name] for name in sorted(steps)}


def _read_index(derived: Path) -> dict | None:
    """读既有 index.json；缺失或损坏都当「没有」，绝不因派生数据坏了阻断重跑。"""
    path = derived / INDEX_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _same_run(index: dict | None, run_id: str, inputs: dict[str, str]) -> bool:
    """旧 index 是否属于同一个 run 的同一批产物（inputs 哈希逐项一致）。"""
    return bool(index) and index.get("run_id") == run_id and index.get("inputs") == inputs


def _carry_over(derived: Path, tmp: Path, run_id: str, inputs: dict[str, str]) -> set[str]:
    """把同一 run 同一输入的旧 step JSON 复制到临时目录，返回继承的 step 名。"""
    index = _read_index(derived)
    if not _same_run(index, run_id, inputs):
        return set()
    carried = set()
    for name in index.get("steps", {}):
        src = derived / f"{name}.json"
        if src.exists():
            shutil.copy2(src, tmp / f"{name}.json")
            carried.add(name)
    return carried


def _carried_statuses(derived: Path, run_id: str, inputs: dict[str, str],
                      names: set[str]) -> dict[str, dict]:
    """继承 step 的状态条目（仅同 run 同输入）；本次要重跑的 name 会被覆盖。"""
    index = _read_index(derived)
    if not _same_run(index, run_id, inputs):
        return {}
    return {name: dict(status) for name, status in index.get("steps", {}).items()
            if name in names}


def _write_json(path: Path, payload) -> None:
    """写单个 JSON：`allow_nan=False` 是硬约束，任何 NaN 都会当场暴露。"""
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
