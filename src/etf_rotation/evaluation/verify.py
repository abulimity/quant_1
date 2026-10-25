"""run 产物校验：哈希、跨文件对账、派生数据溯源（计划 Task 21）。

三层检查，逐条收集问题，全部通过才返回空列表：

① **清点（哈希是唯一判据）**
   `artifacts.parquet` 每行登记了产物落盘时的 sha256 与字节数；重算磁盘文件的
   sha256 逐个比对。改一个字节、换一个文件都会被点名。`rows/cols` 不再复算：
   parquet 一旦被改写，哈希必然先变，解析损坏文件只会多一条噪声。

② **对账（跨文件一致性）**
   - `total_fees`（引擎 fees 汇总）vs `trades.cost.sum()`（逐笔 notional·bps/1e4）：
     相对误差必须 < 0.5%，超了就是错，不是警告；
   - 指标的 `ann_return`/`sharpe` 必须与 `equity.nav` 的 ffn 重算值一致
     （指标唯一来源是 ffn，写出后被改动就意味着登记与产物脱节）。

③ **溯源（派生数据不串台）**
   `derived/index.json` 的 `inputs` 记录了「这份派生数据是哪批产物算出来的」；
   必须与当前产物的实测哈希逐项相等，`run_id` 必须等于本 run。

清理过的 run（`meta.pruned=TRUE`）另作处理：大产物是**按计划删掉**的，
不是丢失，因此跳过「产物缺失」判定，派生数据的 inputs 只比对仍存在的产物。
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import ffn
import pandas as pd

from etf_rotation.evaluation.artifacts import FILENAMES
from etf_rotation.evaluation import registry

# `total_fees` 与逐笔成本合计的允许相对误差（计划 Task 21：< 0.5%）
FEES_RTOL = 0.005
# 指标与净值重算值的允许相对误差：bt 的 GroupStats 与「从 equity 重算」走两条
# 代码路径（前者用 result.prices，后者用 reindex/ffill 后的 nav），短窗口下
# CAGR 可能差到 1e-3 量级。这个检查的目的是发现「指标被改过/与产物脱节」，
# 不是逐位复现，所以用 0.5%：改一个 5% 的指标仍会被点名。
RECOMPUTE_RTOL = 0.005
# ffn 的日频年化因子（与 bt 的 GroupStats 默认一致）
_PERIODS_PER_YEAR = 252


def _sha256(path: Path) -> str:
    """重算单个产物的 sha256（与 artifacts/registry 同一算法）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_meta(run_dir: Path) -> dict | None:
    """读 meta.parquet 单行 → dict；缺失或损坏返回 None。"""
    path = run_dir / "meta.parquet"
    if not path.exists():
        return None
    try:
        return {str(k): v for k, v in pd.read_parquet(path).iloc[0].to_dict().items()}
    except Exception:
        return None


def _read_metrics(run_dir: Path) -> dict[str, float]:
    """读 metrics.parquet 长表 → {指标名: 值}；缺失或损坏返回空 dict。"""
    path = run_dir / "metrics.parquet"
    if not path.exists():
        return {}
    try:
        df = pd.read_parquet(path)
        return {str(m): float(v) for m, v in zip(df["metric"], df["value"])}
    except Exception:
        return {}


def _read_artifacts(run_dir: Path) -> list[dict]:
    """读 artifacts.parquet → 产物记录列表；缺失或损坏返回空列表。"""
    path = run_dir / "artifacts.parquet"
    if not path.exists():
        return []
    try:
        return [dict(row) for row in pd.read_parquet(path).to_dict("records")]
    except Exception:
        return []


def _truthy(value) -> bool:
    """meta 标记的宽松解析：True / "TRUE" / "1" / "yes" 都算真。"""
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return str(value).strip().upper() in ("TRUE", "1", "YES", "Y")


def _close(a: float, b: float, rtol: float) -> bool:
    """相对比较：NaN 与 NaN 视为相等，分母取 max(1, |a|, |b|)。"""
    if math.isnan(a) and math.isnan(b):
        return True
    if math.isnan(a) or math.isnan(b):
        return False
    return abs(a - b) <= rtol * max(1.0, abs(a), abs(b))


def _relative_error(a: float, b: float) -> float:
    """两个金额的相对误差：分母取较大的绝对值（都为 0 时视为 0）。"""
    denom = max(abs(a), abs(b))
    if denom == 0.0:
        return 0.0
    return abs(a - b) / denom


def verify(root: Path, run_id: str | None = None) -> list[str]:
    """校验 run 产物，返回问题清单（空列表 = 通过）。

    参数
    ----
    root   : 登记根目录（生产为 `reports/runs`）
    run_id : 只校验该 run；为 None 时校验 root 下所有非隐藏 run

    每条问题都以 `<run_id>: ` 开头，便于在输出里定位到具体 run。
    """
    root = Path(root)
    if not root.is_dir():
        return [f"{root}: 登记根目录不存在"]
    if run_id is not None:
        run_dir = root / run_id
        if not run_dir.is_dir():
            return [f"{run_id}: run 目录不存在于 {root}"]
        runs = [run_dir]
    else:
        # 只校验 v2 登记（有 meta.parquet）。pre-v2 的旧 run 只有 manifest.json，
        # 在 Task 23 清理前一直留在磁盘上，不能因此让 verify 整体失败。
        # 有 artifacts.parquet 却没有 meta.parquet 的目录仍会被点名（真损坏）。
        runs = sorted(p for p in root.glob("*")
                      if p.is_dir() and not p.name.startswith(".")
                      and ((p / "meta.parquet").exists() or (p / "artifacts.parquet").exists()))

    problems: list[str] = []
    for run_dir in runs:
        problems.extend(_verify_run(run_dir))
    return problems


def _verify_run(run_dir: Path) -> list[str]:
    """单个 run 的三层检查。"""
    rid = run_dir.name
    meta = _read_meta(run_dir)
    if meta is None:
        return [f"{rid}: meta.parquet 缺失或不可读（无法确认 run 身份）"]

    problems: list[str] = []
    if str(meta.get("run_id") or "") != rid:
        problems.append(f"{rid}: meta.run_id={meta.get('run_id')!r} 与目录名不一致")

    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        problems.append(f"{rid}: manifest.json 缺失（登记镜像不完整）")
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if str(manifest.get("run_id")) != rid:
                problems.append(f"{rid}: manifest.json 的 run_id 与目录名不一致")
        except (OSError, ValueError):
            problems.append(f"{rid}: manifest.json 不可解析")

    pruned = _truthy(meta.get("pruned"))
    profile = str(meta.get("save_profile") or "")
    current, intact = _check_artifacts(run_dir, rid, pruned, problems,
                                       allow_empty=(profile == "minimal"))

    metrics = _read_metrics(run_dir)
    if not metrics:
        problems.append(f"{rid}: metrics.parquet 缺失或无指标记录")

    _check_equity_warmup(run_dir, rid, problems)
    _check_fees(run_dir, rid, meta, metrics, intact, problems)
    _check_metrics_vs_equity(run_dir, rid, metrics, intact, problems)
    _check_derived(run_dir, rid, current, pruned, problems)
    return problems


def _check_artifacts(run_dir: Path, rid: str, pruned: bool,
                     problems: list[str], allow_empty: bool = False
                     ) -> tuple[dict[str, str], set[str]]:
    """逐产物重算哈希；返回（现存产物 name→sha256，哈希一致的 name 集合）。

    `allow_empty=True` 用于 minimal 档：那里本来就只有 meta/metrics/manifest，
    没有产物记录是契约的一部分，不是缺失。
    """
    rows = _read_artifacts(run_dir)
    if not rows:
        if not allow_empty:
            problems.append(f"{rid}: artifacts.parquet 缺失或没有产物记录")
        return {}, set()

    current: dict[str, str] = {}
    intact: set[str] = set()
    for row in rows:
        name, rel = str(row.get("name")), str(row.get("path"))
        path = run_dir / rel
        if not path.exists():
            # 清理过的 run：大产物按计划删掉，不算问题（artifacts 保留原始审计）
            if not pruned:
                problems.append(f"{rid}: 产物 {rel} 缺失（artifacts.parquet 有登记）")
            continue
        digest = _sha256(path)
        current[name] = digest
        if digest != str(row.get("sha256")):
            problems.append(f"{rid}: 产物 {rel} 的 sha256 与登记不符（文件被改动）")
            continue
        # 哈希已一致时字节数必然一致；走到这里说明 artifacts.parquet 自己被动过
        if path.stat().st_size != int(row.get("bytes", -1)):
            problems.append(f"{rid}: artifacts.parquet 里 {rel} 的字节数与磁盘不符")
            continue
        intact.add(name)
    return current, intact


def _check_equity_warmup(run_dir: Path, rid: str, problems: list[str]) -> None:
    """equity 首行 nav=NaN 是早期代码把 bt bootstrap 行并进索引的遗留，仅告警。"""
    path = run_dir / FILENAMES["equity"]
    if not path.exists():
        return
    try:
        equity = pd.read_parquet(path)
    except Exception:
        return
    if "nav" in equity.columns and len(equity) and pd.isna(equity["nav"].iloc[0]):
        problems.append(f"WARN {rid}: equity 首行 nav=NaN（bt bootstrap 行，早期代码版本）")


def _check_fees(run_dir: Path, rid: str, meta: dict, metrics: dict[str, float],
                intact: set[str], problems: list[str]) -> None:
    """`total_fees` 与 `trades.cost.sum()` 对账（相对误差 < 0.5%）。"""
    if "total_fees" not in metrics:
        return
    path = run_dir / FILENAMES["trades"]
    if "trades" not in intact:
        # full 档承诺逐笔明细：有 total_fees 却读不到逐笔，等于对账链断了
        profile = str(meta.get("save_profile") or "")
        if profile == "full" and not _truthy(meta.get("pruned")):
            problems.append(f"{rid}: full 档缺少 {FILENAMES['trades']}，无法与 total_fees 对账")
        return
    trades = pd.read_parquet(path)
    if "cost" not in trades.columns:
        problems.append(f"{rid}: {FILENAMES['trades']} 缺少 cost 列，无法与 total_fees 对账")
        return
    total_fees = float(metrics["total_fees"])
    cost_sum = float(trades["cost"].sum())
    rel = _relative_error(total_fees, cost_sum)
    if rel >= FEES_RTOL:
        problems.append(
            f"{rid}: total_fees={total_fees:.6f} 与 trades.cost.sum()={cost_sum:.6f} "
            f"相对误差 {rel:.4%} 超过 {FEES_RTOL:.1%}")


def _check_metrics_vs_equity(run_dir: Path, rid: str, metrics: dict[str, float],
                             intact: set[str], problems: list[str]) -> None:
    """`ann_return`/`sharpe` 与 equity 净值用 ffn 重算值比对。

    只在 equity 哈希校验通过时重算：被篡改的文件由哈希层点名，
    再叠加一条「重算不符」只会让输出更吵。
    """
    if "equity" not in intact:
        return
    equity = pd.read_parquet(run_dir / FILENAMES["equity"])
    if "nav" not in equity.columns:
        problems.append(f"{rid}: {FILENAMES['equity']} 缺少 nav 列")
        return
    nav = equity["nav"].astype(float)
    if len(nav.dropna()) < 2:
        return
    returns = nav.pct_change(fill_method=None).dropna()
    recomputed = {
        "ann_return": float(ffn.calc_cagr(nav)),
        "sharpe": float(ffn.calc_sharpe(returns, rf=0.0, nperiods=_PERIODS_PER_YEAR)),
    }
    for key, value in recomputed.items():
        if key not in metrics:
            continue
        recorded = float(metrics[key])
        if not _close(recorded, value, RECOMPUTE_RTOL):
            problems.append(
                f"{rid}: 指标 {key}={recorded:.6f} 与 equity 重算值 {value:.6f} 不一致"
                f"（容差 {RECOMPUTE_RTOL:g}）")


def _check_derived(run_dir: Path, rid: str, current: dict[str, str], pruned: bool,
                   problems: list[str]) -> None:
    """`derived/index.json` 必须是「本 run + 当前这批产物」算出来的。"""
    path = run_dir / "derived" / "index.json"
    if not path.exists():
        return   # 还没跑派生数据：合法的中间状态
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        problems.append(f"{rid}: derived/index.json 不可解析")
        return

    if str(index.get("run_id")) != rid:
        problems.append(
            f"{rid}: derived/index.json 的 run_id={index.get('run_id')!r} 与本 run 不一致"
            f"（派生数据串台）")

    recorded = {str(k): str(v) for k, v in (index.get("inputs") or {}).items()}
    # 当前有、派生没记 → 派生数据漏了新产物（或产物被换过一代）
    unrecorded = sorted(set(current) - set(recorded))
    # 双方都有但哈希不同 → 产物变了、派生没重算
    stale = sorted(k for k in recorded if k in current and recorded[k] != current[k])
    # 派生记了、磁盘上没有 → 未清理的 run 意味着产物丢失
    orphan = [] if pruned else sorted(set(recorded) - set(current))
    if unrecorded or stale or orphan:
        detail = []
        if stale:
            detail.append(f"哈希不一致 {stale}")
        if unrecorded:
            detail.append(f"派生未覆盖 {unrecorded}")
        if orphan:
            detail.append(f"产物已不在 {orphan}")
        problems.append(
            f"{rid}: derived/index.json 的 inputs 与当前产物不符（{'；'.join(detail)}）；"
            f"请重跑 build_report_data.py")


def has_errors(problems: list[str]) -> bool:
    """`WARN ` 前缀的行不算失败（证据纯度告警，不阻塞），其余都是真错误。"""
    return any(not message.startswith("WARN ") for message in problems)


def verify_reports(reports_dir: Path) -> list[str]:
    """校验 `reports/` 顶层一致性：latest ↔ derived 镜像 ↔ 该 run 的 analysis 身份。

    只回答三个问题：latest.json 可解析、镜像的 index.json.run_id == latest、
    镜像与 `runs/{latest}/derived` 的文件集合与内容完全一致（防串台/防残影）。
    analysis/*.json 若带了 run_id，必须等于 latest（不要求必须有，Task 6 才补字段）。
    """
    reports_dir = Path(reports_dir)
    latest_path = reports_dir / "latest.json"
    if not latest_path.exists():
        return [f"{latest_path}: latest.json 缺失"]
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"{latest_path}: latest.json 不可解析"]
    run_id = latest.get("run_id")
    if run_id is None:
        return [f"{latest_path}: 缺少 run_id"]
    run_id = str(run_id)

    problems: list[str] = []
    mirror = reports_dir / "derived"
    run_derived = reports_dir / "runs" / run_id / "derived"
    if not mirror.is_dir():
        return [f"{mirror}: 派生镜像缺失（请跑 build_report_data.py）"]
    if not run_derived.is_dir():
        return [f"{run_derived}: 该 run 的 derived 缺失"]

    mirror_index = mirror / "index.json"
    if mirror_index.exists():
        try:
            idx = json.loads(mirror_index.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problems.append(f"{mirror_index}: 不可解析")
        else:
            if str(idx.get("run_id")) != run_id:
                problems.append(
                    f"{mirror_index}: run_id={idx.get('run_id')!r} 与 latest {run_id} 不一致（派生串台）")
    else:
        problems.append(f"{mirror_index}: 缺失")

    mirror_files = {p.name for p in mirror.iterdir() if p.is_file()}
    run_files = {p.name for p in run_derived.iterdir() if p.is_file()}
    only_mirror = sorted(mirror_files - run_files)
    only_run = sorted(run_files - mirror_files)
    if only_mirror or only_run:
        problems.append(
            f"mirror 与 run 的 derived 文件集合不一致："
            f"仅镜像有 {only_mirror}，仅 run 有 {only_run}")
    for name in sorted(mirror_files & run_files):
        if _sha256(mirror / name) != _sha256(run_derived / name):
            problems.append(f"mirror/{name}: 内容与 run 的 derived 不一致")

    analysis = reports_dir / "runs" / run_id / "analysis"
    if analysis.is_dir():
        for jp in sorted(analysis.glob("*.json")):
            try:
                payload = json.loads(jp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                problems.append(f"{jp}: 不可解析")
                continue
            if "run_id" in payload and str(payload.get("run_id")) != run_id:
                problems.append(f"{jp}: run_id={payload.get('run_id')!r} 与 latest 不一致")
    return problems


def verify_families(families_root: Path, runs_root: Path,
                    campaign_id: str | None = None) -> list[str]:
    """校验 family 成员与 run 的身份一致性。

    - 成员 run 的 meta.parquet 必须存在；
    - 成员的 git_sha / data_snapshot_id / execution 与 family.json 不一致时打 WARN；
    - family 或成员标 git_dirty 时打 WARN（证据纯度告警，不阻塞）。

    WARN 行以 `WARN ` 前缀标识，`has_errors` 会滤掉它们；缺失/损坏是 ERROR。
    """
    families_root, runs_root = Path(families_root), Path(runs_root)
    if not families_root.exists():
        return []
    problems: list[str] = []
    for fam_dir in sorted(p for p in families_root.glob("*")
                          if p.is_dir() and ((p / "family.json").exists()
                                             or (p / "members").is_dir())):
        fam = registry.load_family(families_root, fam_dir.name)
        if campaign_id is not None and (fam.get("campaign_id") or "") != campaign_id:
            continue
        fid = fam["family_id"]
        fam_gsha = fam.get("git_sha")
        fam_snap = fam.get("data_snapshot_id")
        if fam.get("git_dirty"):
            problems.append(
                f"WARN {fid}: family 标 git_dirty（dirty_hash={fam.get('dirty_hash')!r}），"
                f"证据须在干净工作区生成")
        for member in fam["members"]:
            rid = str(member["run_id"])
            run_dir = runs_root / rid
            if not (run_dir / "meta.parquet").exists():
                problems.append(f"{fid}: 成员 {rid} 的 run 目录或 meta.parquet 缺失")
                continue
            meta = _read_meta(run_dir)
            if meta is None:
                problems.append(f"{fid}: 成员 {rid} 的 meta.parquet 不可读")
                continue
            if meta.get("git_dirty"):
                problems.append(f"WARN {fid}: 成员 {rid} git_dirty=True（不可复现）")
            if fam_gsha and meta.get("git_sha") != fam_gsha:
                problems.append(
                    f"WARN {fid}: 成员 {rid} git_sha={meta.get('git_sha')!r} "
                    f"与 family {fam_gsha} 不一致")
            if fam_snap and meta.get("data_snapshot_id") != fam_snap:
                problems.append(f"WARN {fid}: 成员 {rid} data_snapshot_id 与 family 不一致")
    return problems
