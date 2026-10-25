"""family 汇总：单进程读成员 + metrics，写 `families/{fid}/summary.json`。

为什么必须单进程：Hydra multirun 下 worker 只写自己的 run 目录与成员 JSON；
summary 是「跨成员聚合」，如果每个 worker 都写就会互相覆盖（计划 §3.3）。
本脚本在 sweep 全部结束后运行一次。

汇总内容：
- `robustness`  —— 成员 Sharpe > 0 的占比（ml4t-sensitivity-analysis）
- `cliffs`      —— 沿每个网格维度的悬崖检测
- `dsr_family`  —— 只在当前 family 的 trial 数上做多重检验校正
- `dsr_campaign`—— 在 campaign 累计 trial 数上做校正（跨 family 累加）
- `best`        —— Sharpe 最高的成员（参数 + 指标）
- `results`     —— 全部成员一行一个（参数 + 指标），供报告镜像使用
"""
from __future__ import annotations

import argparse
import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from etf_rotation.evaluation import overfitting, registry, sensitivity, sweep

ROOT = Path(__file__).resolve().parents[1]


def _read_metrics(run_dir: Path) -> dict[str, float]:
    """读一个 run 的 metrics.parquet 长表 → {指标名: 值}（缺文件返回空）。"""
    path = Path(run_dir) / "metrics.parquet"
    if not path.exists():
        return {}
    df = pd.read_parquet(path)
    return {str(m): float(v) for m, v in zip(df["metric"], df["value"])}


def _read_meta(run_dir: Path) -> dict:
    """读一个 run 的 meta.parquet 单行（缺文件返回空）。"""
    path = Path(run_dir) / "meta.parquet"
    if not path.exists():
        return {}
    return pd.read_parquet(path).iloc[0].to_dict()


def _n_obs(metas: list[dict]) -> int | None:
    """观测数 T：各成员应同窗口，取最大非空整数（DSR 标准误依赖 T）。"""
    values = []
    for meta in metas:
        value = meta.get("n_obs")
        try:
            if value is not None and not pd.isna(value):
                values.append(int(value))
        except (TypeError, ValueError):
            continue
    return max(values) if values else None


def _dsr(sharpes: list[float], n_trials: int, n_obs: int | None) -> float | None:
    """安全版 DSR：候选 <2 或 T<2 时无定义，返回 None（而不是 NaN）。"""
    if len(sharpes) < 2 or not n_trials or n_obs is None or n_obs < 2:
        return None
    value = overfitting.deflated_sharpe(np.asarray(sharpes, dtype=float), n_trials, n_obs)
    return float(value) if np.isfinite(value) else None


def _write_atomic(path: Path, payload: dict) -> None:
    """同目录临时文件 + `os.replace`：读者不会看到半截 summary.json。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
                   encoding="utf-8")
    os.replace(tmp, path)


def family_summary(families_root: Path, runs_root: Path, fid: str) -> dict:
    """读 `families/{fid}` 的成员与对应 run 指标，生成并落盘 summary.json。

    参数
    ----
    families_root : family 根目录（生产为 `reports/families`）
    runs_root     : run 根目录（生产为 `reports/runs`）
    fid           : family_id

    返回写入磁盘的同一份 dict。
    """
    families_root, runs_root = Path(families_root), Path(runs_root)
    fam = registry.load_family(families_root, fid)

    rows: list[dict] = []
    metas: list[dict] = []
    sharpes: list[float] = []
    run_ids: list[str] = []
    for member in fam["members"]:
        run_id = str(member["run_id"])
        run_ids.append(run_id)
        metrics = _read_metrics(runs_root / run_id)
        meta = _read_meta(runs_root / run_id)
        metas.append(meta)
        variant = member.get("variant") or {}
        rows.append({"run_id": run_id, **variant, **metrics})
        if "sharpe" in metrics:
            sharpes.append(float(metrics["sharpe"]))

    n_obs = _n_obs(metas)
    campaign_id = fam.get("campaign_id") or next(
        (m.get("campaign_id", "") for m in fam["members"]), "")

    results = pd.DataFrame(rows)
    spec = fam.get("spec") or {}
    robustness = None
    cliffs = {}
    if not results.empty and "sharpe" in results.columns:
        robustness = sensitivity.robustness_score(results)
        keys = [key for key in spec if key in results.columns]
        if keys:
            cliffs = sweep.jsonable(sensitivity.detect_cliffs(results, keys))

    best = None
    finite = [value for value in sharpes if math.isfinite(value)]
    if finite:
        top = max(finite)
        best = sweep.jsonable(next(row for row in rows if row.get("sharpe") == top))

    n_family = fam["n_trials"]
    n_campaign = overfitting.campaign_trials(families_root, campaign_id) if campaign_id else n_family

    summary = {
        "family_id": fid,
        "kind": fam.get("kind"),
        "spec": spec,
        "campaign_id": campaign_id,
        "n_trials": n_family,
        "n_campaign_trials": n_campaign,
        "n_obs": n_obs,
        "metric": "sharpe",
        "robustness": robustness,
        "cliffs": cliffs,
        "sharpe_haircut": (sweep.jsonable(overfitting.sharpe_haircut(sharpes))
                           if len(sharpes) >= 2 else None),
        "dsr_family": _dsr(sharpes, n_family, n_obs),
        "dsr_campaign": _dsr(sharpes, n_campaign, n_obs),
        "best": best,
        "run_ids": run_ids,
        "results": sweep.jsonable(rows),
        "generated": datetime.now(timezone.utc).isoformat(),
    }
    _write_atomic(families_root / fid / "summary.json", summary)
    return summary


def families_for_campaign(families_root: Path, campaign_id: str) -> list[str]:
    """列出某 campaign 下的 family_id（按 family.json 的 campaign_id 精确匹配）。"""
    families_root = Path(families_root)
    if not families_root.exists():
        return []
    out = []
    for path in sorted(families_root.glob("*/family.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("campaign_id", "") == campaign_id:
            out.append(path.parent.name)
    return out


def main() -> None:
    """CLI：`--family <fid>` 或 `--campaign <cid>`，逐个生成 summary.json。"""
    parser = argparse.ArgumentParser(description="汇总 family 成员为 summary.json（单进程）")
    parser.add_argument("--family", action="append", default=[],
                        help="family_id，可重复")
    parser.add_argument("--campaign", action="append", default=[],
                        help="campaign_id，汇总该 campaign 下全部 family")
    parser.add_argument("--runs-root", default=str(ROOT / "reports" / "runs"))
    parser.add_argument("--families-root", default=str(ROOT / "reports" / "families"))
    args = parser.parse_args()

    fids = list(args.family)
    for campaign in args.campaign:
        fids.extend(families_for_campaign(Path(args.families_root), campaign))
    fids = list(dict.fromkeys(fids))       # 去重且保序
    if not fids:
        parser.error("需要 --family 或 --campaign（且 campaign 下有已登记的 family）")

    for fid in fids:
        summary = family_summary(Path(args.families_root), Path(args.runs_root), fid)
        print(json.dumps({
            "family_id": fid,
            "n_trials": summary["n_trials"],
            "n_campaign_trials": summary["n_campaign_trials"],
            "dsr_family": summary["dsr_family"],
            "dsr_campaign": summary["dsr_campaign"],
            "summary": str(Path(args.families_root) / fid / "summary.json"),
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
