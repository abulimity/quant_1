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


def search_pool(families_root: Path, runs_root: Path, campaign_id: str) -> tuple[list[float], int | None]:
    """收集同一 campaign 下**搜索类** family 的 (sharpes, n_obs)。

    只统计 `grid / ablation / assumption`：这三个是「试过多少个候选」的试验；
    `oos / cost` 是验证，不是候选，计入会稀释多重检验校正的分母。
    `n_obs` 取全窗口最大值（搜索类都应跑全窗口；OOS 只有子区间）。
    按 `run_id` 去重：同一配置（如默认参数）会被多个维度的网格重复选中，
    内容寻址后是同一个 run，DSR 的分母必须只算一次。
    """
    sharpes: list[float] = []
    nobs: list[int] = []
    seen: set[str] = set()
    for fam_dir in sorted(Path(families_root).glob("*")):
        if not fam_dir.is_dir() or not (fam_dir / "family.json").exists():
            continue
        fam = registry.load_family(families_root, fam_dir.name)
        if (fam.get("campaign_id") or "") != campaign_id:
            continue
        if fam.get("kind") not in ("grid", "ablation", "assumption"):
            continue
        if fam.get("git_dirty"):
            continue
        member_metas = [_read_meta(Path(runs_root) / str(m["run_id"]))
                        for m in fam["members"]]
        if any(m.get("git_dirty") for m in member_metas):
            continue
        for member, meta in zip(fam["members"], member_metas):
            run_id = str(member["run_id"])
            if run_id in seen:
                continue
            seen.add(run_id)
            run_dir = Path(runs_root) / run_id
            metrics = _read_metrics(run_dir)
            if "sharpe" in metrics:
                sharpes.append(float(metrics["sharpe"]))
            if meta.get("n_obs") is not None:
                nobs.append(int(meta["n_obs"]))
    return sharpes, (max(nobs) if nobs else None)


# 旧名保留为只读别名：family_summary 与其它调用方沿用原路径。
_search_pool = search_pool


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
    if campaign_id:
        campaign_sharpes, campaign_nobs = _search_pool(families_root, runs_root, campaign_id)
        # 搜索池为空（如本 campaign 的搜索 family 全是脏工作区产物）时，campaign DSR
        # 无定义：不得回退到 n_family / 本 family 的 sharpes——那会把脏 run 重新塞进
        # 多重检验分母。n_campaign 与 dsr_campaign 都置 None，前端渲染为 —。
        n_campaign = len(campaign_sharpes) or None
        dsr_campaign = _dsr(campaign_sharpes, n_campaign or 0,
                            campaign_nobs or n_obs)
    else:
        n_campaign = n_family
        dsr_campaign = _dsr(sharpes, n_family, n_obs)

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
        "dsr_campaign": dsr_campaign,
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


def latest_family(families_root: Path, kind: str) -> str | None:
    """返回 kind 匹配、`family.json.created_at` 最新的 family_id；无则 None。"""
    families_root = Path(families_root)
    best: str | None = None
    best_ts = ""
    for path in sorted(families_root.glob("*/family.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if meta.get("kind") != kind:
            continue
        ts = meta.get("created_at") or ""
        if best is None or ts > best_ts:
            best, best_ts = path.parent.name, ts
    return best


def cost_rows(families_root: Path, runs_root: Path, family_id: str) -> list[dict]:
    """读成本 family 的成员 variant + metrics，按 `costs.one_side_bps` 升序返回。

    供 `run_report.py` 用同一份 run 产物出成本敏感性图，替代顶层 `sensitivity.json`
    （后者是 campaign 级文件，不绑定 run，可能混入别的 run 的成本曲线）。
    """
    families_root, runs_root = Path(families_root), Path(runs_root)
    fam = registry.load_family(families_root, family_id)
    rows: list[dict] = []
    for member in fam["members"]:
        rid = str(member["run_id"])
        variant = member.get("variant") or {}
        metrics = _read_metrics(runs_root / rid)
        rows.append({
            "one_side_bps": variant.get("costs.one_side_bps"),
            "run_id": rid,
            "sharpe": metrics.get("sharpe"),
            "ann_return": metrics.get("ann_return"),
            "max_drawdown": metrics.get("max_drawdown"),
            "calmar": metrics.get("calmar"),
            "total_fees": metrics.get("total_fees"),
        })
    rows.sort(key=lambda r: (r["one_side_bps"] is None, r["one_side_bps"]))
    return rows


def _read_summary(families_root: Path, fid: str) -> dict:
    """读 `families/{fid}/summary.json`；缺失/损坏返回空 dict。"""
    path = Path(families_root) / fid / "summary.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def index_rows(families_root: Path, runs_root: Path,
               campaign_id: str | None = None) -> list[dict]:
    """每 family 一行索引：身份、trial 数、DSR、最优 Sharpe、脏标记、缺失成员。

    `n_campaign_trials` / `dsr_*` 直接读 family_summary 写的 summary.json
    （单一来源，不在索引里二次推导）；缺失成员按 run 目录是否可读判断。
    """
    families_root, runs_root = Path(families_root), Path(runs_root)
    if not families_root.exists():
        return []
    rows: list[dict] = []
    for fam_dir in sorted(p for p in families_root.glob("*")
                          if p.is_dir() and (p / "family.json").exists()):
        fam = registry.load_family(families_root, fam_dir.name)
        cid = fam.get("campaign_id") or ""
        if campaign_id is not None and cid != campaign_id:
            continue
        summary = _read_summary(families_root, fam_dir.name)
        best = summary.get("best") or {}
        member_metas = [_read_meta(runs_root / str(m["run_id"])) for m in fam["members"]]
        member_dirty = any(m.get("git_dirty") for m in member_metas)
        missing = [str(m["run_id"]) for m in fam["members"]
                   if not (runs_root / str(m["run_id"]) / "meta.parquet").exists()]
        rows.append({
            "family_id": fam_dir.name,
            "kind": fam.get("kind"),
            "campaign_id": cid,
            "n_trials": fam.get("n_trials", 0),
            "n_campaign_trials": summary.get("n_campaign_trials"),
            "dsr_family": summary.get("dsr_family"),
            "dsr_campaign": summary.get("dsr_campaign"),
            "best_sharpe": best.get("sharpe"),
            "git_dirty": bool(fam.get("git_dirty", False)) or member_dirty,
            "missing_members": missing,
        })
    return rows


def _fmt(value) -> str:
    """索引单元格的展示：None → —，float → 4 位小数，其余原样。"""
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_index(rows: list[dict], generated_at: str) -> str:
    """把 index_rows 的结果渲染成 Markdown：口径说明 + 汇总表 + 缺失成员清单。"""
    lines = [
        "# 调参 campaign 索引",
        "",
        f"> 生成时间：{generated_at}。`n_campaign_trials` 为去重且排除脏工作区后的搜索 trial 数。",
        "",
        "| family_id | kind | campaign_id | n_trials | n_campaign_trials | "
        "dsr_family | dsr_campaign | best_sharpe | dirty |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        dirty = "⚠ dirty" if row.get("git_dirty") else ""
        lines.append("| " + " | ".join([
            str(row.get("family_id")), str(row.get("kind") or ""),
            str(row.get("campaign_id") or ""), str(row.get("n_trials", 0)),
            _fmt(row.get("n_campaign_trials")), _fmt(row.get("dsr_family")),
            _fmt(row.get("dsr_campaign")), _fmt(row.get("best_sharpe")), dirty,
        ]) + " |")
    lines.append("")
    lines.append("## 缺失成员（run 目录不存在）")
    lines.append("")
    missing = [(r["family_id"], m) for r in rows for m in r.get("missing_members", [])]
    if missing:
        for fid, rid in missing:
            lines.append(f"- {fid}: `{rid}`")
    else:
        lines.append("无")
    lines.append("")
    return "\n".join(lines)


def write_index(families_root: Path, runs_root: Path, path: Path,
                campaign_id: str | None = None) -> Path:
    """生成 `reports/index.md`（原子写：同目录临时文件 + `os.replace`）。"""
    rows = index_rows(families_root, runs_root, campaign_id)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render_index(rows, datetime.now(timezone.utc).isoformat())
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def main() -> None:
    """CLI：`--family <fid>` 或 `--campaign <cid>`，逐个生成 summary.json，并写 index.md。"""
    parser = argparse.ArgumentParser(description="汇总 family 成员为 summary.json（单进程）")
    parser.add_argument("--family", action="append", default=[],
                        help="family_id，可重复")
    parser.add_argument("--campaign", action="append", default=[],
                        help="campaign_id，汇总该 campaign 下全部 family")
    parser.add_argument("--runs-root", default=str(ROOT / "reports" / "runs"))
    parser.add_argument("--families-root", default=str(ROOT / "reports" / "families"))
    parser.add_argument("--index-path", default=str(ROOT / "reports" / "index.md"),
                        help="索引输出路径（默认 reports/index.md）")
    parser.add_argument("--no-index", action="store_true", help="不生成 index.md")
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

    if not args.no_index:
        index_path = write_index(Path(args.families_root), Path(args.runs_root),
                                 Path(args.index_path))
        print(f"index: {index_path}")


if __name__ == "__main__":
    main()
