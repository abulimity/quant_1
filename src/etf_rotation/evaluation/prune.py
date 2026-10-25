"""清理 run 大产物：只删档位允许删的文件，保留登记与对账依据（计划 Task 21）。

可删清单 `PRUNABLE` 严格对应档位定义（计划 §1.4）：
    standard 档的面板  —— equity / holdings
    full 档的明细      —— transactions / trades / signals/*
永不删除：
    meta / metrics / artifacts / manifest / attempts —— 登记与对账依据
    weights.parquet  —— 下游归因（run_attribution）与暴露（run_exposure）的唯一输入
    benchmark.parquet —— 基准序列，体积小且常被报告引用

默认 `dry_run=True`：只返回「哪些 run 的哪些文件会被删」，一个字节都不动。
真正执行时先删文件，再给 meta 追加 `pruned=TRUE`（单行重写，属可控覆盖）。
`artifacts.parquet` **保持原样**：它记录「当初写了什么」，
所以 `verify` 对 `pruned=TRUE` 的 run 跳过「产物缺失」判定。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

# 档位允许清理的大文件（相对 run 目录的路径）
PRUNABLE = (
    "equity.parquet",             # standard：净值面板
    "holdings.parquet",           # standard：引擎实际持仓
    "transactions.parquet",       # full：成交明细
    "trades.parquet",             # full：逐笔往返
    "signals/decision_diary.parquet",   # full：决策日记
    "signals/ticker_signals.parquet",   # full：逐标的信号
    "signals/stages.parquet",           # full：决策阶段快照
)


def _read_meta(run_dir: Path) -> dict:
    """读 meta.parquet 单行 → dict；缺失或损坏返回空 dict。"""
    path = run_dir / "meta.parquet"
    if not path.exists():
        return {}
    try:
        return {str(k): v for k, v in pd.read_parquet(path).iloc[0].to_dict().items()}
    except Exception:
        return {}


def _is_pruned(meta: dict) -> bool:
    """meta 里 `pruned` 标记的宽松解析（True / "TRUE" / "1" 都算已清理）。"""
    value = meta.get("pruned")
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().upper() in ("TRUE", "1", "YES", "Y")


def _age_days(run_dir: Path, meta: dict) -> int:
    """run 的年龄（天）：优先 meta.created_at，缺失/不可解析时退回 meta.parquet 的 mtime。"""
    stamp = pd.to_datetime(meta.get("created_at"), errors="coerce", utc=True)
    if pd.isna(stamp):
        stamp = pd.Timestamp((run_dir / "meta.parquet").stat().st_mtime, unit="s", tz="UTC")
    return int((pd.Timestamp.now(tz="UTC") - stamp).days)


def _mark_pruned(run_dir: Path) -> None:
    """给 meta 追加 `pruned=TRUE`（单行重写：登记表只有一行，属可控覆盖）。"""
    path = run_dir / "meta.parquet"
    row = pd.read_parquet(path)
    row.loc[0, "pruned"] = "TRUE"
    row.to_parquet(path, compression="zstd", index=False)


def _human_size(total: int) -> str:
    """字节数 → 便于阅读的单位（KB/MB 按 1024 进位）。"""
    value = float(total)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024


def prune(root: Path, *, keep_profiles: tuple[str, ...] = ("full",),
          older_than_days: int = 90, dry_run: bool = True) -> list[str]:
    """清理过期 run 的大产物，返回每个 run 一行的动作说明。

    参数
    ----
    root            : 登记根目录（生产为 `reports/runs`）
    keep_profiles   : 这些档位一律不清理（默认保留 full：出报告要用逐笔与信号）
    older_than_days : 只清理年龄 ≥ 该天数的 run（默认 90 天）
    dry_run         : True 时只返回计划动作，不动磁盘

    没有任何 run 符合条件时返回空列表。
    """
    root = Path(root)
    if not root.exists():
        return []

    actions: list[str] = []
    runs = sorted(p for p in root.glob("*") if p.is_dir() and not p.name.startswith("."))
    for run_dir in runs:
        meta = _read_meta(run_dir)
        if not meta:
            continue          # 损坏/非 run 目录不在这里处理，交给 verify 报
        profile = str(meta.get("save_profile") or "")
        if profile in keep_profiles:
            continue
        if older_than_days > 0 and _age_days(run_dir, meta) < older_than_days:
            continue

        targets = [name for name in PRUNABLE if (run_dir / name).exists()]
        if not targets:
            continue

        total = sum((run_dir / name).stat().st_size for name in targets)
        verb = "将删除" if dry_run else "已删除"
        actions.append(
            f"{run_dir.name} ({profile or '?'}, {_human_size(total)}): "
            f"{verb} {', '.join(targets)}")
        if not dry_run:
            for name in targets:
                (run_dir / name).unlink()
            _mark_pruned(run_dir)
    return actions
