"""`ReportContext`：run 目录的只读视图（计划 Task 7 消费契约）。

一次加载，后续所有 step 只读内存对象，不再碰文件系统：
    meta/metrics ← `meta.parquet` / `metrics.parquet`
    params       ← meta["params_json"]（registry 落盘时已转 JSON 文本）
    产物面板     ← artifacts.FILENAMES 对应的 parquet（缺则 None）
    价格面板     ← `pipeline.load_prices()` 一次加载（close/opn/amount）
    分类         ← `universe.classify(pipeline.load_fund_basic())`

校验顺序固定：先读 meta → 校验 `schema_version` → （strict 时）校验
`data_snapshot_id` → 再加载产物。校验放在前面，避免拿错版本的 meta 去解释产物。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from etf_rotation import pipeline
from etf_rotation.data import snapshot, universe
from etf_rotation.evaluation import artifacts

# 本模块能解释的 meta schema。比它新的 meta 可能带未知语义，一律拒绝而不是猜。
SUPPORTED_SCHEMA_VERSIONS = (2,)


@dataclass
class ReportContext:
    """一个 run 的报告上下文（字段与计划 Task 7 的 Produces 清单一致）。"""

    run_id: str
    meta: dict
    params: dict
    equity: pd.DataFrame | None
    benchmark: pd.DataFrame | None
    weights: pd.DataFrame | None
    holdings: pd.DataFrame | None
    trades: pd.DataFrame | None
    transactions: pd.DataFrame | None
    diary: pd.DataFrame | None
    ticker_signals: pd.DataFrame | None
    stages: pd.DataFrame | None
    classification: dict
    close: pd.DataFrame | None
    opn: pd.DataFrame | None
    amount: pd.DataFrame | None
    # 契约补充（main b84c8d5）：Task 11 reconciliation 需要 metrics["total_fees"]
    metrics: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, run_dir: Path, *, strict_snapshot: bool = False) -> "ReportContext":
        """从 `reports/runs/{run_id}/` 加载上下文。

        参数
        ----
        run_dir        : run 目录（不是登记根目录）
        strict_snapshot: True 时要求 meta 的 `data_snapshot_id` 与当前数据指纹一致，
                         用于防止「拿旧 run 的出图脚本对新数据出报告」

        缺产物（standard 档没有 trades、minimal 档连 equity 都没有）时字段为 None；
        缺 `meta.parquet` 抛 FileNotFoundError。
        """
        run_dir = Path(run_dir)
        meta_path = run_dir / "meta.parquet"
        if not meta_path.exists():
            raise FileNotFoundError(f"{meta_path} 不存在；请确认传入的是 reports/runs/<run_id> 目录")

        meta = {k: _json_scalar(v) for k, v in pd.read_parquet(meta_path).iloc[0].to_dict().items()}
        schema = int(meta.get("schema_version", 0) or 0)
        if schema not in SUPPORTED_SCHEMA_VERSIONS:
            raise RuntimeError(
                f"run {meta.get('run_id')!r} 的 schema_version={schema} 不受支持，"
                f"本版本只认 {SUPPORTED_SCHEMA_VERSIONS}")

        run_id = str(meta.get("run_id") or run_dir.name)
        if strict_snapshot:
            current = snapshot.data_snapshot_id()
            recorded = meta.get("data_snapshot_id")
            if recorded != current:
                raise RuntimeError(
                    f"run {run_id} 的数据快照 {recorded!r} 与当前数据 {current!r} 不一致；"
                    f"请用当前数据重跑回测，或去掉 strict_snapshot")

        params = _params(meta.get("params_json"))
        frames = {name: _read_frame(run_dir, name) for name in artifacts.FILENAMES}

        # 价格面板一次加载（约 200 万行），避免每个 step 各读一遍
        close, opn, amount = pipeline.load_prices()
        classification = {
            str(k): str(v) for k, v in universe.classify(pipeline.load_fund_basic()).items()
        }

        return cls(
            run_id=run_id,
            meta=meta,
            params=params,
            equity=frames["equity"],
            benchmark=frames["benchmark"],
            weights=frames["weights"],
            holdings=frames["holdings"],
            trades=frames["trades"],
            transactions=frames["transactions"],
            diary=frames["diary"],
            ticker_signals=frames["ticker_signals"],
            stages=frames["stages"],
            classification=classification,
            close=close,
            opn=opn,
            amount=amount,
            metrics=_read_metrics(run_dir / "metrics.parquet"),
        )


def _json_scalar(value):
    """parquet 单元格 → Python 标量：NaN → None，numpy 标量转原生类型。"""
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except Exception:
            return value
    if isinstance(value, float) and value != value:   # NaN
        return None
    return value


def _params(raw) -> dict:
    """meta["params_json"] → dict（registry 落盘为 JSON 文本；也容忍已是 dict 的调用方）。"""
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        return json.loads(raw)
    return {}


def _read_frame(run_dir: Path, name: str) -> pd.DataFrame | None:
    """按 artifacts.FILENAMES 读一个产物；不存在返回 None（档位不足是合法状态）。"""
    path = run_dir / artifacts.FILENAMES[name]
    if not path.exists():
        return None
    return pd.read_parquet(path)


def _read_metrics(path: Path) -> dict[str, float]:
    """metrics.parquet（长表 metric→value）→ dict；文件缺失返回空 dict。"""
    if not path.exists():
        return {}
    df = pd.read_parquet(path)
    return {str(m): float(v) for m, v in zip(df["metric"], df["value"])}
