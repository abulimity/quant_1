import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]


def _real_run_dir() -> Path | None:
    """返回 reports/latest.json 指向的 run 目录；run 不存在返回 None。"""
    latest_path = ROOT / "reports" / "latest.json"
    if not latest_path.exists():
        return None
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    run_id = latest.get("run_id")
    if not run_id:
        return None
    run_dir = ROOT / "reports" / "runs" / run_id
    if not (run_dir / "meta.parquet").exists():
        return None
    return run_dir


@pytest.fixture
def builder(monkeypatch):
    """真实 run 的 DashboardBuilder；价格面板与分类打桩（200 万行，太慢）。

    fund_basic 打桩必须带 `name` 列：`DashboardBuilder.names()` 会读它，
    只给 `ts_code` 会抛 KeyError，让全量载荷用例连带变红。
    """
    import pandas as pd

    run_dir = _real_run_dir()
    if run_dir is None:
        pytest.skip("真实 run 缺失（reports/latest.json 无有效 run_id）")
    from etf_rotation import pipeline
    from etf_rotation.data import universe
    from etf_rotation.report.context import ReportContext
    from etf_rotation.report.dashboard import DashboardBuilder

    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    prices = pd.DataFrame({"A": [10.0, 10.1]}, index=idx)
    fund_basic = pd.DataFrame({"ts_code": ["A"], "name": ["测试A"]})
    monkeypatch.setattr(pipeline, "load_prices", lambda: (prices, prices, prices))
    monkeypatch.setattr(pipeline, "load_fund_basic", lambda: fund_basic)
    monkeypatch.setattr(universe, "classify", lambda _: {})
    ctx = ReportContext.load(run_dir)
    return DashboardBuilder(ctx, run_dir, run_dir.parent.parent)
