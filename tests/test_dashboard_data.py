"""单文件看板数据载荷（49 键）契约测试（计划收尾 Task 2）。

口径：
- `BUILD_ORDER` 恰好 49 项、无重复、顺序稳定（前端按此顺序渲染）；
- 每个键在 `DashboardBuilder` 里都有对应构建方法（`BUILDER_METHODS` 全映射）；
- `dumps()` 输出能被 `json.JSONDecoder().raw_decode` 完整解析，且不含 NaN/Infinity
  （`allow_nan=False`，NaN/Infinity 一律抛 ValueError）；
- 抽样键（meta/kpi/stats，轻量）与 run 直读结果一致：meta 的 run_id/git_sha 直读
  `meta.parquet`，kpi.s.sharpe 与 stats.cost.fees 直读 `metrics.parquet`。

纪律：不加载 design-data.json，不断言 49 键全量；真实 run 缺失时 `pytest.skip`。
价格面板与分类重（200 万行），沿用 test_report_context 的做法 monkeypatch 掉。
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from etf_rotation.report.dashboard import (
    BUILDER_METHODS,
    BUILD_ORDER,
    DashboardBuilder,
    dumps,
)


# ---------------------------------------------------------------- 静态契约


def test_build_order_49_unique_stable():
    assert len(BUILD_ORDER) == 49
    assert len(set(BUILD_ORDER)) == 49
    assert BUILD_ORDER == [
        "meta", "kpi", "kpiTable", "params", "paramSnapshot", "series", "monthly",
        "months", "annual", "drawdowns", "longest", "stats", "events", "candidates",
        "signals", "tickers", "topPnl", "trades", "diary", "holdingsTop",
        "top10Changes", "regimeIntervals", "budgetSegments", "stages", "stageOrder",
        "contribution", "turnoverDecomp", "costByYear", "sweeps", "grid2d",
        "costLadder", "dsr", "ablation", "assumption", "oos", "oosOverride",
        "regime", "attribution", "exposureSummary", "exDef", "dataQuality", "gap",
        "issues", "lagScan", "roundtrips", "slippage", "capacity", "dist", "names",
    ]


def test_every_key_has_builder_method():
    assert set(BUILDER_METHODS) == set(BUILD_ORDER)
    for key in BUILD_ORDER:
        method = BUILDER_METHODS[key]
        assert getattr(DashboardBuilder, method, None) is not None, f"{key} -> {method} 缺失"


# ---------------------------------------------------------------- dumps 契约


def test_dumps_raw_decode_roundtrip_and_rejects_nan():
    payload = {
        "a": np.float64(1.5),
        "b": [np.int64(2), {"c": np.bool_(True)}],
        "d": None,
        "e": "中文",
    }
    text = dumps(payload)
    obj, end = json.JSONDecoder().raw_decode(text)
    assert end == len(text)
    assert obj["a"] == 1.5
    assert obj["b"] == [2, {"c": True}]

    with pytest.raises(ValueError):
        dumps({"nan": float("nan")})
    with pytest.raises(ValueError):
        dumps({"inf": float("inf")})


# ---------------------------------------------------------------- 抽样键直读


def test_sampled_keys_match_direct_read(builder):
    payload = builder.build(only=["meta", "kpi", "stats"])

    meta = pd.read_parquet(builder.run_dir / "meta.parquet").iloc[0]
    mdf = pd.read_parquet(builder.run_dir / "metrics.parquet")
    metrics = dict(zip(mdf["metric"], mdf["value"]))

    assert payload["meta"]["run_id"] == str(meta["run_id"])
    assert payload["meta"]["git_sha"] == str(meta["git_sha"])
    assert payload["kpi"]["s"]["sharpe"] == pytest.approx(round(float(metrics["sharpe"]), 4))
    assert payload["stats"]["cost"]["fees"] == pytest.approx(round(float(metrics["total_fees"]), 8))


def test_full_payload_dumps_parses_cleanly(builder):
    text = dumps(builder.build())
    obj, end = json.JSONDecoder().raw_decode(text)
    assert end == len(text)
    assert "NaN" not in text
    assert "Infinity" not in text
