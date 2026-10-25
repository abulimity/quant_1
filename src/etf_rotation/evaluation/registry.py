"""回测登记：内容寻址与 parquet 只读登记层（ml4t-registry-system）。

一次 run 的登记信息拆成四个文件，写在 `reports/runs/{run_id}/` 下：

    meta.parquet       —— 单行宽表：身份/代码/数据/执行口径/参数/时间
    metrics.parquet    —— 长表 (run_id, metric, value)，便于跨 run 做分布比较
    artifacts.parquet  —— 产物清单 (name, path, sha256, bytes, rows, cols)
    manifest.json      —— 上述内容的人类可读镜像（不参与内容哈希）

为什么不再写共享 duckdb：Hydra multirun / 多会话并行时，任何共享库文件都会
撞锁或互相覆盖。改成「每个 run 只写自己的目录」后，并行天然安全；读取时用
DuckDB 内存库对**显式 parquet 文件列表**建视图，不落盘、不加锁。
"""
from __future__ import annotations

import hashlib
import json
import math
import numbers
import subprocess
import sys
from collections import namedtuple
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]   # 仓库根（src/etf_rotation/evaluation → 上溯三级）

# 登记根目录（默认布局；调用方可传自己的 root，测试全部走 tmp_path）
RUNS_DIR = ROOT / "reports" / "runs"
FAMILIES_DIR = ROOT / "reports" / "families"
# 暂存目录放在 runs 下面：读取层跳过 `.` 开头的目录，暂存内容永远不会被查询到
STAGING_DIR = RUNS_DIR / ".staging"

_REQUIREMENTS = ROOT / "requirements.txt"
_ENV_PACKAGES = ("bt", "pandas", "numpy", "duckdb", "pyarrow", "ffn")

# dirty_hash 的排除目录：本流程自己会写的产物（reports/、data/）。
# 不排除会形成反馈回路：run_backtest 镜像覆盖 reports/metrics.json → git diff 变
# → dirty_hash 变 → 同一个回测第二次跑出新的 run_id，内容寻址失效。
_DIRTY_EXCLUDES = ("reports", "data")

# 一条产物记录：name 是逻辑名（equity/trades/…），path 是 run 目录内的相对路径
ArtifactInfo = namedtuple("ArtifactInfo", "name path sha256 bytes rows cols")


def run_identity(params: dict, *, git_sha: str = "", dirty_hash: str = "",
                 data_snapshot_id: str = "", execution: str = "close",
                 signal_id: str = "") -> str:
    """确定性 run 身份哈希：参数 + 代码 + 数据 + 执行口径 + 信号集。

    公式（计划 §1.1）：
        run_id = sha256(json({params, git_sha, dirty_hash, data_snapshot_id,
                              execution, signal_id}, sort_keys=True))[:12]
    `sort_keys=True` 保证参数键序不同也得到同一个 id（内容寻址）。
    `dirty_hash` 为空串表示工作区干净；非空时把「脏工作区」的差异也纳入身份，
    避免两次不同的未提交改动撞 id。
    """
    blob = json.dumps(
        {"params": params, "git_sha": git_sha, "dirty_hash": dirty_hash,
         "data_snapshot_id": data_snapshot_id, "execution": execution,
         "signal_id": signal_id},
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def git_sha() -> str:
    """当前提交短哈希，用于登记回测对应的代码版本；git 不可用时返回 'unknown'。"""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def git_info() -> tuple[str, str]:
    """返回 `(sha, dirty_hash)`：干净工作区 `dirty_hash` 为空串。

    公式：dirty_hash = sha256(git diff 输出)[:8]（仅当工作区有**已跟踪文件**改动）
    纪律：
    - `git status` 加 `--untracked-files=no`：data/、reports/ 里的新增文件是运行期
      产物，不能算「脏」，否则每次跑完回测都会得到新的 run_id。
    - diff 排除 `reports/`、`data/`：这两个目录里的**已跟踪**文件
      （如基线 `reports/metrics.json`）会被回测镜像覆盖，若计入指纹，同一份代码 +
      同一组参数重跑就会得到新 run_id —— 违反「内容寻址必须确定」。
    """
    sha = git_sha()
    spec = [".", *[f":(exclude){p}" for p in _DIRTY_EXCLUDES]]
    try:
        status = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no", "--", *spec],
            text=True, cwd=ROOT, stderr=subprocess.DEVNULL).strip()
        if not status:
            return sha, ""
        diff = subprocess.check_output(
            ["git", "diff", "--", *spec], cwd=ROOT, stderr=subprocess.DEVNULL)
    except Exception:
        # git 不可用（源码包/容器内）：无法判定脏，按干净处理，dirty_hash 留空
        return sha, ""
    return sha, hashlib.sha256(diff).hexdigest()[:8]


def env_lock_hash() -> str:
    """运行环境标识：依赖清单 + Python 版本 + 关键库版本，取 sha256 前 12 位。

    公式：sha256( requirements.txt 字节 + sys.version
                  + 各库 __version__（按固定顺序） )[:12]
    用途：解释器/库升级会改变数值口径（例如 pandas 的 pct_change 默认值），
    run 登记必须能查出「这个结果是哪套环境跑出来的」。
    """
    h = hashlib.sha256()
    h.update(_REQUIREMENTS.read_bytes() if _REQUIREMENTS.exists() else b"")
    h.update(sys.version.encode("utf-8"))
    for name in _ENV_PACKAGES:
        try:
            module = __import__(name)
            version = getattr(module, "__version__", "")
        except Exception:
            version = "missing"
        h.update(f"{name}=={version}\n".encode("utf-8"))
    return h.hexdigest()[:12]


def _jsonable(value):
    """把 meta 值转成 JSON 可序列化的标量（NaN/Inf → None，日期 → ISO 字符串）。"""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def _scalar(value):
    """meta 落 parquet 用的标量：容器转 JSON 文本，numpy 标量转 Python 标量。"""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def write_run(root: Path, run_id: str, meta: dict, metrics: dict,
              artifacts: list[ArtifactInfo]) -> Path:
    """写一个 run 的登记文件到 `{root}/{run_id}/`，返回该目录。

    - `meta` 的容器值一律转 JSON 文本落列（parquet 列类型必须稳定）；`run_id`
      以函数参数为准（meta 里残留的旧值不覆盖）；
    - `metrics` 的每个值必须是数值（bool 不算），否则 TypeError —— 指标表只放
      数字，文本/状态放 meta，避免下游聚合时出现混合类型列；
    - manifest.json 是同一份内容的人类可读镜像，不参与内容哈希。
    """
    out = Path(root) / run_id
    out.mkdir(parents=True, exist_ok=True)

    row = {k: _scalar(v) for k, v in meta.items()}
    row["run_id"] = run_id          # 参数优先：防调用方 meta 里带旧 run_id 串号
    pd.DataFrame([row]).to_parquet(out / "meta.parquet", compression="zstd", index=False)

    values = {}
    for key, value in metrics.items():
        # numbers.Real 含 numpy 浮点；bool 是 Integral 的子类，需显式排除
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            raise TypeError(f"metric {key!r} 必须是数值，得到 {type(value).__name__}")
        values[key] = float(value)
    pd.DataFrame({
        "run_id": [run_id] * len(values),
        "metric": list(values),
        "value": list(values.values()),
    }).to_parquet(out / "metrics.parquet", compression="zstd", index=False)

    pd.DataFrame(
        [dict(a._asdict()) for a in artifacts],
        columns=list(ArtifactInfo._fields),
    ).to_parquet(out / "artifacts.parquet", compression="zstd", index=False)

    manifest = {
        "run_id": run_id,
        "meta": {k: _jsonable(v) for k, v in row.items()},
        "metrics": values,
        "artifacts": [dict(a._asdict()) for a in artifacts],
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return out


def _meta_files(root: Path) -> list[Path]:
    """收集登记文件：`*/meta.parquet`，跳过 `.` 开头的目录（暂存/隐藏目录）。"""
    root = Path(root)
    if not root.exists():
        return []
    return sorted(p for p in root.glob("*/meta.parquet") if not p.parent.name.startswith("."))


def _sql_list(files: list[Path]) -> str:
    """把文件列表拼成 read_parquet 的 SQL 字面量（路径走 posix 形式并转义单引号）。"""
    parts = []
    for f in files:
        p = str(Path(f).as_posix()).replace("'", "''")
        parts.append("'" + p + "'")
    return "[" + ", ".join(parts) + "]"


def load_runs(root: Path) -> pd.DataFrame:
    """扫描 root 下所有 run，返回「meta 宽表 + 指标透视列」。

    空目录（或只有暂存目录）返回空 DataFrame，不抛错 —— 首次运行前必须可用。
    实现：对显式文件列表建 meta / metric 两个视图，取出后用 pandas 透视合并
    （指标名 -> 列名），这样同一 run 的多个指标与 meta 处在同一行。
    """
    files = _meta_files(root)
    if not files:
        return pd.DataFrame()
    metric_files = [p.parent / "metrics.parquet" for p in files
                    if (p.parent / "metrics.parquet").exists()]

    con = duckdb.connect()   # 内存库：不落盘、不加锁
    try:
        con.execute(
            f"CREATE VIEW meta AS SELECT * FROM read_parquet({_sql_list(files)}, union_by_name=true)")
        meta_df = con.execute("SELECT * FROM meta").df()
        if metric_files:
            con.execute(
                f"CREATE VIEW metric AS SELECT * FROM read_parquet("
                f"{_sql_list(metric_files)}, union_by_name=true)")
            met = con.execute("SELECT run_id, metric, value FROM metric").df()
            if not met.empty:
                pivot = met.pivot_table(index="run_id", columns="metric", values="value",
                                        aggfunc="first")
                pivot.columns.name = None
                meta_df = meta_df.merge(pivot, left_on="run_id", right_index=True, how="left")
    finally:
        con.close()
    return meta_df.reset_index(drop=True)


def load_metrics(root: Path) -> pd.DataFrame:
    """扫描 root 下所有 run，返回指标长表 (run_id, metric, value)。"""
    files = [p.parent / "metrics.parquet" for p in _meta_files(root)
             if (p.parent / "metrics.parquet").exists()]
    if not files:
        return pd.DataFrame(columns=["run_id", "metric", "value"])
    con = duckdb.connect()
    try:
        con.execute(
            f"CREATE VIEW metric AS SELECT * FROM read_parquet("
            f"{_sql_list(files)}, union_by_name=true)")
        return con.execute("SELECT run_id, metric, value FROM metric").df()
    finally:
        con.close()


def content_hash(meta: dict, metrics: dict, artifact_hashes: dict[str, str]) -> str:
    """一次 run 的内容哈希：{meta（去掉时间戳/绝对路径）, 指标, 产物哈希} → sha256[:12]。

    `created_at` 与 `path` 必须排除：它们描述「什么时候落盘/落在哪」，
    与「跑了什么」无关；把它们算进去会让同一结果每次重跑都得到新哈希。
    """
    payload = {
        "meta": {k: _scalar(v) for k, v in sorted(meta.items())
                 if k not in ("created_at", "path")},
        "metrics": {k: float(metrics[k]) for k in sorted(metrics)},
        "artifacts": {k: artifact_hashes[k] for k in sorted(artifact_hashes)},
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def utc_now() -> str:
    """当前 UTC 时间（ISO 8601），供 created_at / updated_at 使用。"""
    return datetime.now(timezone.utc).isoformat()


# ── family / trial 登记（主计划 Task 18）──────────────────────────────────
# 一次「调参族」= 同一份网格 spec + 同一批基准参数 + 同一窗口/口径/代码/数据。
# 每个成员 run 写自己的 `members/{run_id}.json`，没有任何共享汇总文件：
# Hydra multirun / 多会话并行时不会互相覆盖；family 级汇总（summary.json）
# 只能由单进程 collect_runs 生成。

def _json_safe(value):
    """递归转成可 `json.dumps(..., allow_nan=False)` 的结构（NaN/Inf → None）。"""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        return _json_safe(value.item())
    return str(value)


def family_id(kind: str, spec: dict, base_params: dict, start, end, execution: str,
              git_sha: str, data_snapshot_id: str, campaign_id: str = "") -> str:
    """调参族身份：`sha256(json({kind, spec, base_params, start, end, execution,
    git_sha, data_snapshot_id, campaign_id}, sort_keys=True))[:12]`。

    `sort_keys=True` 让 dict 键序不同也得到同一个 id（内容寻址）；`spec` 传原始
    网格（参数名 → 候选值），`base_params` 传未参与网格的基准参数——两者都在
    身份里，避免「同名网格、不同底参」的两批结果被当成一族。
    """
    payload = {
        "kind": kind,
        "spec": _json_safe(spec),
        "base_params": _json_safe(base_params),
        "start": _json_safe(start),
        "end": _json_safe(end),
        "execution": execution,
        "git_sha": git_sha,
        "data_snapshot_id": data_snapshot_id,
        "campaign_id": campaign_id,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      allow_nan=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def _write_json_atomic(path: Path, payload: dict) -> None:
    """原子写小 JSON：先写同目录 `.tmp-{pid}-{rand}`，再 `os.replace` 覆盖。

    成员文件按 run_id 命名，同一路径不会被两个 run 写；但 collect_runs 可能并发
    重建 summary，`os.replace` 保证读者永远看到完整 JSON（不会读到半截文件）。
    """
    import os
    import uuid

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
                   encoding="utf-8")
    os.replace(tmp, path)


def write_family_member(root: Path, fid: str, run_id: str, variant: dict,
                        campaign_id: str = "", family: dict | None = None) -> None:
    """登记一个成员 run：写 `{root}/{fid}/members/{run_id}.json`（一个成员一个文件）。

    `family`（可选）用于首次写入时补 `family.json` 的 kind/spec：成员文件只描述
    「哪个 run、什么变体」，族的定义（kind/spec/窗口/口径）放在 family.json。
    已存在的 family.json 只补缺失键、不覆盖已有值（多进程并行时先写者为准）。
    """
    out = Path(root) / fid
    row = {
        "family_id": fid,
        "run_id": run_id,
        "variant": _json_safe(variant),
        "campaign_id": campaign_id,
        "created_at": utc_now(),
    }
    _write_json_atomic(out / "members" / f"{run_id}.json", row)

    meta_path = out / "family.json"
    if family is not None:
        meta = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
        meta.setdefault("family_id", fid)
        for key in ("kind", "spec", "start", "end", "execution", "git_sha",
                    "data_snapshot_id", "campaign_id", "git_dirty", "dirty_hash"):
            value = family.get(key)
            if value is not None and key not in meta:
                meta[key] = _json_safe(value)
        meta.setdefault("campaign_id", campaign_id)
        meta.setdefault("created_at", utc_now())
        _write_json_atomic(meta_path, meta)


def load_family(root: Path, fid: str) -> dict:
    """读回一个族的定义与成员：`{fid, kind, spec, campaign_id, members[], n_trials}`。

    - 成员按 run_id 排序（确定性输出，不受文件系统枚举顺序影响）；
    - 目录/成员不存在时返回空族（`n_trials=0`），不抛错——首次运行时必须可用；
    - 跳过 `.` 开头的临时文件，避免读到写了一半的 JSON。
    """
    out = Path(root) / fid
    meta = {}
    if (out / "family.json").exists():
        try:
            meta = json.loads((out / "family.json").read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    members = []
    members_dir = out / "members"
    if members_dir.exists():
        for path in sorted(members_dir.glob("*.json")):
            if path.name.startswith("."):
                continue
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            row.setdefault("run_id", path.stem)
            row.setdefault("family_id", fid)
            members.append(row)
    members.sort(key=lambda r: str(r.get("run_id")))

    return {
        "family_id": fid,
        "kind": meta.get("kind"),
        "spec": meta.get("spec", {}),
        "campaign_id": meta.get("campaign_id", ""),
        "members": members,
        "n_trials": len(members),
        "created_at": meta.get("created_at"),
        "git_sha": meta.get("git_sha"),
        "data_snapshot_id": meta.get("data_snapshot_id"),
        "git_dirty": bool(meta.get("git_dirty")),
        "dirty_hash": meta.get("dirty_hash", ""),
    }
