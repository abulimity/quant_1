"""run 产物持久化：`store_run` 是唯一写入口（计划 §1.2）。

写入流程（顺序不可换）：
    校验档位/产物名 → 写 `reports/runs/.staging/{run_id}/`
    → 计算每个产物的 sha256/bytes/rows/cols → `registry.write_run` 写登记四件套
    → 追加 attempts.jsonl → `os.rename` 原子改名为 `reports/runs/{run_id}/`

幂等规则：
- 目录不存在：直接改名；
- 目录已存在：同名产物逐个比对 sha256，指标按相对容差 1e-9 比对；
  全部一致 → 只补写缺失产物（档位升级），追加 attempts.jsonl；
  任一不一致 → `ArtifactConflictError`，原目录一字不动；
- 任何异常都删掉暂存目录后重抛，磁盘上不会留下半成品。

为什么不用共享数据库：Hydra multirun 下每个进程只写自己的 run 目录，
不需要锁；`load_runs` 也永远看不到 `.staging`（读取层跳过 `.` 开头的目录）。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from etf_rotation.evaluation import registry

# 档位 → 实际落盘的逻辑产物名（顺序即写入顺序，便于人工核对目录结构）
SAVE_PROFILES = {
    "minimal": (),
    "standard": ("equity", "weights", "holdings", "benchmark"),
    "full": ("equity", "weights", "holdings", "benchmark", "transactions", "trades",
             "diary", "ticker_signals", "stages"),
}

# 逻辑名 → run 目录内的相对路径（前端与报告层只认这张表）
FILENAMES = {
    "equity": "equity.parquet",
    "weights": "weights.parquet",
    "holdings": "holdings.parquet",
    "benchmark": "benchmark.parquet",
    "transactions": "transactions.parquet",
    "trades": "trades.parquet",
    "diary": "signals/decision_diary.parquet",
    "ticker_signals": "signals/ticker_signals.parquet",
    "stages": "signals/stages.parquet",
}

# 顶层镜像映射：run 产物 → reports/ 下的兼容副本（旧脚本/报告继续按原路径读）
_MIRROR_CSV = {
    "equity.parquet": ("equity.csv", "ts"),
    "holdings.parquet": ("holdings.csv", "ts"),
    "benchmark.parquet": ("benchmark.csv", "ts"),
    "transactions.parquet": ("transactions.csv", None),
    "trades.parquet": ("trades.csv", None),
}
_MIRROR_COPY = ("weights.parquet",)

_PROFILE_RANK = {"minimal": 0, "standard": 1, "full": 2}

# 指标比较的相对容差：只吸收浮点求和顺序差异，不吸收任何真实数值偏差
_METRIC_RTOL = 1e-9


class ArtifactConflictError(RuntimeError):
    """同名 run 的产物/指标与磁盘上的既有版本不一致（拒绝覆盖）。"""


def _sha256(path: Path) -> str:
    """单个产物文件的 sha256（与 registry/snapshot 一致的十六进制摘要）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_frames(directory: Path, names: list[str], frames: dict[str, pd.DataFrame]) -> None:
    """把档位内的 DataFrame 写成 parquet（zstd），`signals/` 等子目录按需创建。

    独立成函数是为了让测试可以整体替换它（验证「写盘失败不留痕迹」）。
    """
    for name in names:
        if name not in frames:
            continue
        path = Path(directory) / FILENAMES[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        frames[name].to_parquet(path, compression="zstd")


def _append_attempt(directory: Path, run_id: str, profile: str, action: str) -> None:
    """向 attempts.jsonl 追加一行（每次 store_run 一条，重跑可审计）。"""
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "profile": profile,
        "action": action,
        "pid": os.getpid(),
    }
    with open(Path(directory) / "attempts.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _close_enough(a: float, b: float) -> bool:
    """指标比较：NaN 视为相等；其余用相对容差（分母取 max(1, |a|, |b|)）。"""
    if math.isnan(a) and math.isnan(b):
        return True
    return abs(a - b) <= _METRIC_RTOL * max(1.0, abs(a), abs(b))


def _read_metrics(path: Path) -> dict[str, float]:
    """读 metrics.parquet 长表 → {指标名: 值}。"""
    if not path.exists():
        return {}
    df = pd.read_parquet(path)
    return {str(m): float(v) for m, v in zip(df["metric"], df["value"])}


def _read_artifacts(path: Path) -> list[dict]:
    """读 artifacts.parquet → ArtifactInfo 字段字典列表。"""
    if not path.exists():
        return []
    df = pd.read_parquet(path)
    return [{k: v for k, v in row.items()} for row in df.to_dict("records")]


def _merge_existing(staging: Path, final: Path, infos: list, metrics: dict,
                    meta: dict, run_id: str, profile: str) -> None:
    """已存在 run 的幂等升级：先全量比对（不动盘），一致后补写缺失产物与登记。"""
    # ① 同名产物内容比对：任何差异都在写盘前抛出，保证「拒绝覆盖」是原子的
    for info in infos:
        target = final / info.path
        if target.exists() and _sha256(target) != info.sha256:
            raise ArtifactConflictError(
                f"run {run_id} 的产物 {info.path} 与磁盘版本不一致，拒绝覆盖；"
                f"如确需重跑，请换参数或先归档旧目录")

    # ② 指标比对（相对容差 1e-9）
    existing_metrics = _read_metrics(final / "metrics.parquet")
    new_metrics = {k: float(v) for k, v in metrics.items()}
    for key, value in new_metrics.items():
        if key in existing_metrics and not _close_enough(existing_metrics[key], value):
            raise ArtifactConflictError(
                f"run {run_id} 的指标 {key} 冲突：磁盘 {existing_metrics[key]!r} vs 本次 {value!r}")

    # ③ 补写缺失产物（档位升级：standard → full 只多写 transactions/trades/signals）
    for info in infos:
        target = final / info.path
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staging / info.path, target)

    # ④ 合并登记：created_at 保留首次值（身份不变），档位只升不降
    existing_meta = pd.read_parquet(final / "meta.parquet").iloc[0].to_dict()
    merged_meta = {k: v for k, v in existing_meta.items()}
    for key, value in meta.items():
        merged_meta.setdefault(key, value)
    merged_meta["run_id"] = run_id
    merged_meta["kind"] = meta.get("kind", merged_meta.get("kind"))
    old_profile = str(existing_meta.get("save_profile", "minimal"))
    merged_meta["save_profile"] = (
        profile if _PROFILE_RANK.get(profile, 0) >= _PROFILE_RANK.get(old_profile, 0)
        else old_profile)

    merged_artifacts = _read_artifacts(final / "artifacts.parquet")
    known = {str(a["name"]) for a in merged_artifacts}
    merged_artifacts.extend(dict(i._asdict()) for i in infos if i.name not in known)

    registry.write_run(
        final.parent, run_id, merged_meta, {**existing_metrics, **new_metrics},
        [registry.ArtifactInfo(**a) for a in merged_artifacts],
    )

    # ⑤ 追加本轮 attempts（暂存目录里那一行），再清理暂存
    attempt_text = (staging / "attempts.jsonl").read_text(encoding="utf-8")
    with open(final / "attempts.jsonl", "a", encoding="utf-8") as f:
        f.write(attempt_text)
    shutil.rmtree(staging, ignore_errors=True)


def store_run(*, root: Path, run_id: str, kind: str, profile: str, meta: dict,
              metrics: dict, frames: dict[str, pd.DataFrame]) -> Path:
    """把一次运行的产物按档位写入 `{root}/{run_id}/`，返回 run 目录。

    参数
    ----
    root    : 登记根目录（生产为 `reports/runs`；测试传 tmp_path）
    run_id  : 内容寻址 id（`registry.run_identity` 的结果）
    kind    : backtest / cost / grid / ablation / assumption / oos …
    profile : minimal / standard / full
    meta    : 身份与参数元信息（params_json 可为 dict，会转 JSON 文本）
    metrics : 指标（必须全是数值）
    frames  : 逻辑名 → DataFrame；档位决定实际写哪些，传了档位外的键会被忽略，
              但**不认识的名字**直接报错（防拼写错误静默丢产物）
    """
    root = Path(root)
    if profile not in SAVE_PROFILES:
        raise ValueError(f"未知档位 {profile!r}，可选 {sorted(SAVE_PROFILES)}")
    unknown = set(frames) - set(SAVE_PROFILES["full"])
    if unknown:
        raise ValueError(f"未知产物名 {sorted(unknown)}，可选 {sorted(FILENAMES)}")

    names = [name for name in SAVE_PROFILES[profile] if name in frames]
    staging = root / ".staging" / run_id
    final = root / run_id
    try:
        # 残留的暂存目录（上次进程被杀）直接丢弃，避免把旧文件混进本次产物
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)

        write_frames(staging, names, frames)
        infos = [registry.ArtifactInfo(
            name=name, path=FILENAMES[name], sha256=_sha256(staging / FILENAMES[name]),
            bytes=(staging / FILENAMES[name]).stat().st_size,
            rows=int(len(frames[name])), cols=int(frames[name].shape[1]),
        ) for name in names]

        row_meta = dict(meta)
        row_meta["kind"] = kind
        row_meta["run_id"] = run_id
        row_meta["save_profile"] = profile
        row_meta.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        registry.write_run(staging.parent, run_id, row_meta, metrics, infos)

        if not final.exists():
            _append_attempt(staging, run_id, profile, "created")
            # 原子改名：读者要么看到完整目录，要么看不到（不会读到半个 run）
            os.rename(staging, final)
            return final

        # 已存在：先比对再补写；attempts 在合并成功后才落到正式目录
        _append_attempt(staging, run_id, profile, "upgraded")
        _merge_existing(staging, final, infos, metrics, row_meta, run_id, profile)
        return final
    except Exception:
        # 任何失败（含冲突）都清掉暂存，磁盘上不留半成品
        shutil.rmtree(staging, ignore_errors=True)
        raise


def latest_run_id(root: Path) -> str | None:
    """读 `root.parent/latest.json` 的 `run_id`；缺失/损坏/无该键返回 None。

    供镜像守卫判断「这次要镜像的 run 是不是 latest」，避免 `--run-id <旧 run>`
    把 `reports/derived/` 悄悄换成别的 run 的派生数据。
    """
    root = Path(root)
    latest = root.parent / "latest.json"
    if not latest.exists():
        return None
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rid = payload.get("run_id")
    return str(rid) if rid is not None else None


def resolve_run(root: Path, run_id: str | None = None) -> Path:
    """定位 run 目录：`run_id` 为空时读 `reports/latest.json`。

    找不到时抛 FileNotFoundError 并列出最近的 5 个可用 run_id，便于手工重跑。
    """
    root = Path(root)
    if run_id is None:
        latest = root.parent / "latest.json"
        if not latest.exists():
            raise FileNotFoundError(f"{latest} 不存在；请先跑一次 run_backtest 或显式给 --run-id")
        run_id = json.loads(latest.read_text(encoding="utf-8"))["run_id"]
    run_dir = root / run_id
    if not run_dir.is_dir():
        available = sorted(p.name for p in root.glob("*")
                           if p.is_dir() and not p.name.startswith("."))[:5]
        raise FileNotFoundError(f"run {run_id} 不存在于 {root}；可用 run_id: {available}")
    return run_dir


def mirror_latest(run_dir: Path, reports_dir: Path) -> None:
    """写 `reports/latest.json` 并把 run 产物映射为顶层兼容副本。

    latest.json 用临时文件 + `os.replace` 原子替换：并发读者不会读到半行 JSON。
    缺哪个产物就跳过哪个（档位不足时 trades/benchmark 允许不存在）。
    """
    run_dir, reports_dir = Path(run_dir), Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    meta = pd.read_parquet(run_dir / "meta.parquet").iloc[0].to_dict()

    family_id = meta.get("family_id")
    if family_id is None or (isinstance(family_id, float) and math.isnan(family_id)):
        family_id = None
    payload = {
        "run_id": meta.get("run_id"),
        "family_id": family_id,
        "kind": meta.get("kind"),
        "profile": meta.get("save_profile"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    latest = reports_dir / "latest.json"
    tmp = reports_dir / ".latest.json.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
                   encoding="utf-8")
    os.replace(tmp, latest)

    # CSV 镜像：日期索引统一写成 `ts` 列，保持旧脚本的读取口径不变
    for src_name, (dst_name, index_label) in _MIRROR_CSV.items():
        src = run_dir / src_name
        if not src.exists():
            continue
        df = pd.read_parquet(src)
        df.to_csv(reports_dir / dst_name, index=index_label is not None,
                  index_label=index_label, encoding="utf-8")
    for src_name in _MIRROR_COPY:
        src = run_dir / src_name
        if src.exists():
            shutil.copy2(src, reports_dir / src_name)

    # 指标：长表 → 宽表 JSON（NaN/Inf 一律 null，满足 allow_nan=False）
    metrics_path = run_dir / "metrics.parquet"
    if metrics_path.exists():
        met = pd.read_parquet(metrics_path)
        wide = {}
        for name, value in zip(met["metric"], met["value"]):
            value = float(value)
            wide[str(name)] = value if math.isfinite(value) else None
        (reports_dir / "metrics.json").write_text(
            json.dumps(wide, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    # 信号/决策快照
    signals = run_dir / "signals"
    if signals.is_dir():
        out = reports_dir / "signals"
        out.mkdir(parents=True, exist_ok=True)
        for src in sorted(signals.glob("*.parquet")):
            shutil.copy2(src, out / src.name)
