"""JSON 安全序列化：所有派生 JSON 的唯一出口（计划 Task 7）。

规则（全局约束 §2）：
- NaN/Inf → None，保证 `json.dumps(payload, allow_nan=False)` 不抛错；
- 日期一律 `YYYY-MM-DD`（Timestamp/date/datetime 都转字符串）；
- numpy 标量转原生 Python 标量，避免 json 不认 `np.float64`。
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

_DATE_FORMAT = "%Y-%m-%d"


def clean(obj: Any) -> Any:
    """递归清洗：日期→`YYYY-MM-DD`、numpy 标量→原生、NaN/Inf→None。"""
    if obj is None or obj is pd.NaT or obj is pd.NA:
        return None
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.strftime(_DATE_FORMAT)
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        value = float(obj)
        return value if math.isfinite(value) else None
    if isinstance(obj, str):
        return obj
    if isinstance(obj, pd.Series):
        return [clean(v) for v in obj.tolist()]
    if isinstance(obj, pd.DataFrame):
        return records(obj)
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [clean(v) for v in obj.tolist()]
    return obj


def records(df: pd.DataFrame, index: str = "date") -> list[dict]:
    """DataFrame → list[dict]：索引转成 `index` 列，日期格式化，值全部清洗。

    `index=None` 时保留原样（调用方自己保证列里没有索引信息）。
    """
    if df is None:
        return []
    out = df.reset_index() if index is not None else df.copy()
    if index is not None and "index" in out.columns:
        out = out.rename(columns={"index": index})
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime(_DATE_FORMAT)
    return [{str(k): clean(v) for k, v in row.items()} for row in out.to_dict("records")]


def series(s: pd.Series | None, name: str = "values") -> dict:
    """Series → `{"dates": [...], "values": [...]}`。

    日期为 NaT 的点整点丢弃；数值 NaN 保留为 None（横轴不能因为缺值而错位）。
    """
    if s is None:
        return {"dates": [], name: []}
    s = pd.Series(s)
    dates = pd.Index(s.index)
    if isinstance(dates, pd.DatetimeIndex):
        keep = ~dates.isna()
        return {
            "dates": [d.strftime(_DATE_FORMAT) for d in dates[keep]],
            name: [clean(v) for v in s.to_numpy()[keep]],
        }
    return {"dates": [clean(d) for d in dates], name: [clean(v) for v in s.to_list()]}
