"""网格 sweep 的公共落盘流程：身份 → store_run → family 成员。

设计（主计划 §1.1 / Task 19）：

- `iter_points`：网格笛卡尔积，按参数名排序，保证同一网格无论 dict 键序如何
  都得到同一个点序列（family_id 内容寻址依赖这一点）。
- `run_sweep`：不关心「怎么跑回测」，只负责编排。调用方注入 `run_one(point)`，
  返回 `(meta, metrics, frames)`；本模块负责：
    ① 用 `meta.params_json`（缺省用 point）算内容寻址 `run_id`；
    ② `artifacts.store_run` 按档位落盘（唯一写入口）；
    ③ `registry.write_family_member` 一人一个成员 JSON（无共享文件、无锁）；
    ④ 在 meta 里注入 kind/family_id/campaign_id/save_profile。
- 任何进程都不写共享数据库、不写 `latest.json`：网格结果不抢「基准回测」的位置，
  family 汇总只能由单进程 `scripts/collect_runs.py` 生成。
"""
from __future__ import annotations

import itertools
import math
import numbers
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

import pandas as pd

from etf_rotation.evaluation import artifacts, registry


def iter_points(grid: dict) -> Iterator[dict]:
    """网格笛卡尔积，按 key 排序后展开（键序不同 → 点序列相同）。

    例：{"y": [3, 4], "x": [1, 2]} → [{"x":1,"y":3}, {"x":1,"y":4},
                                       {"x":2,"y":3}, {"x":2,"y":4}]
    公式：points = ∏_{k ∈ sorted(grid)} grid[k]（字典序即稳定顺序）。
    """
    keys = sorted(grid)
    for combo in itertools.product(*(grid[k] for k in keys)):
        yield dict(zip(keys, combo))


def _unique(values: list) -> list:
    """按首次出现顺序去重（spec 只描述候选值集合，重复值不应改变身份）。"""
    out, seen = [], set()
    for value in values:
        marker = repr(value)          # list/dict 不可哈希，用 repr 做去重键
        if marker not in seen:
            seen.add(marker)
            out.append(value)
    return out


def spec_from_points(points: list[dict]) -> dict:
    """从点序列反推网格 spec：每个参数名 → 出现过的候选值（去重、保序）。

    调用方通常直接传原始 grid（`run_sweep(..., spec=grid)`）；这里只是让
    只拿到 points 的调用方也能得到确定性的 family 身份。
    """
    values: dict[str, list] = {}
    for point in points:
        for key, value in point.items():
            values.setdefault(key, []).append(value)
    return {key: _unique(values[key]) for key in sorted(values)}


def jsonable(value):
    """递归转成可 `json.dumps(..., allow_nan=False)` 的结构（NaN/Inf → None）。

    summary.json 里会出现 pandas/numpy 标量与「单点无定义」产生的 NaN；
    这个函数保证落盘前全部合法（与 registry 的序列化口径一致）。
    """
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        return jsonable(value.item())
    return str(value)


def finite_metrics(metrics: dict) -> tuple[dict, list[str]]:
    """拆出「可落盘的数字」与「无定义的非有限指标」。

    指标表只放数字；NaN/Inf 表示该指标在本窗口无定义（例如短区间的
    `yearly_sortino` 分母为 0），必须剔除才能满足 manifest 的
    `json.dumps(..., allow_nan=False)`。返回 `(clean, dropped)`。
    """
    clean, dropped = {}, []
    for key, value in (metrics or {}).items():
        if (isinstance(value, numbers.Real) and not isinstance(value, bool)
                and not math.isfinite(float(value))):
            dropped.append(str(key))
            continue
        clean[key] = value
    return clean, sorted(dropped)


def run_sweep(*, points, run_one, kind: str, profile: str, campaign_id: str,
              tag: str, runs_root: Path, families_root: Path, git_sha: str,
              data_snapshot_id: str, start: str, end: str, execution: str,
              spec: dict | None = None, base_params: dict | None = None) -> dict:
    """逐点执行 sweep 并落盘，返回
    `{"family_id", "n_trials", "run_ids", "trials"}`。

    `trials` 是「点 → run_id」的完整映射（长度 = points）；`run_ids` 去重，
    因为同一配置（参数完全相同）内容寻址后就是同一个 run。

    参数
    ----
    points   : 参数点序列（每项是「参数名 → 值」的覆写字典）
    run_one  : 注入的执行函数，接收 point，返回 `(meta, metrics, frames)`；
               build/backtest 由调用方负责，便于测试注入、不跑真实回测
    kind     : grid / cost / assumption / ablation / oos
    profile  : minimal / standard / full（见 artifacts.SAVE_PROFILES）
    spec     : family 身份里的原始网格；缺省由 points 反推
    base_params : 未参与网格的基准参数（进入 family 身份，避免同名网格串族）

    family_id 公式见 `registry.family_id`；run_id 公式见 `registry.run_identity`
    （参数 + 代码 + 数据 + 口径 + 信号集，sort_keys 保证确定性）。
    """
    points = [dict(point) for point in points]
    spec = spec_from_points(points) if spec is None else dict(spec)
    base_params = dict(base_params or {})

    fid = registry.family_id(
        kind, spec, base_params, start, end, execution,
        git_sha, data_snapshot_id, campaign_id,
    )
    family = {
        "kind": kind, "spec": spec, "start": start, "end": end,
        "execution": execution, "git_sha": git_sha,
        "data_snapshot_id": data_snapshot_id, "campaign_id": campaign_id,
    }

    run_ids: list[str] = []
    trials: list[dict] = []
    for point in points:
        meta, metrics, frames = run_one(dict(point))
        meta = dict(meta or {})
        # 指标表只放数字：NaN/Inf 表示该指标在本窗口无定义（如短区间的
        # yearly_sortino 分母为 0），落盘前剔除并记入 meta，满足 allow_nan=False。
        clean_metrics, dropped = finite_metrics(metrics)
        if dropped:
            meta["nonfinite_metrics"] = dropped
        # 身份优先用 run_one 给的全量参数（含基准参数）；只有 point 时退化为点本身
        identity_params = meta.get("params_json") or point
        run_id = registry.run_identity(
            identity_params,
            git_sha=meta.get("git_sha", git_sha),
            dirty_hash=meta.get("dirty_hash", ""),
            data_snapshot_id=meta.get("data_snapshot_id", data_snapshot_id),
            execution=meta.get("execution", execution),
            signal_id=meta.get("signal_id", ""),
        )

        # 身份/族信息以 sweep 为准，覆盖 run_one 返回的同名键
        meta.update({
            "kind": kind,
            "family_id": fid,
            "campaign_id": campaign_id,
            "tag": tag,
            "save_profile": profile,
            "variant": point,
        })
        meta.setdefault("git_sha", git_sha)
        meta.setdefault("data_snapshot_id", data_snapshot_id)
        meta.setdefault("execution", execution)
        meta.setdefault("start", start)
        meta.setdefault("end", end)

        artifacts.store_run(
            root=Path(runs_root), run_id=run_id, kind=kind, profile=profile,
            meta=meta, metrics=clean_metrics, frames=frames or {},
        )
        # 同一配置（run_id 相同）只登记一个成员：成员文件按 run_id 命名，
        # 重复写会覆盖 variant。调用方需要的「点 → run_id」映射见返回值 trials。
        if run_id not in run_ids:
            registry.write_family_member(
                families_root, fid, run_id, variant=point,
                campaign_id=campaign_id, family=family,
            )
            run_ids.append(run_id)
        trials.append({"point": point, "run_id": run_id})

    return {"family_id": fid, "n_trials": len(run_ids), "run_ids": run_ids,
            "trials": trials}
