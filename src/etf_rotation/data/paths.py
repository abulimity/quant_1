"""数据路径解析：默认指向本地 bronze 快照，可用环境变量覆盖。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _p(name: str, default: Path) -> Path:
    """解析数据路径：优先取环境变量覆盖值，未设置时退回仓库内默认路径。"""
    v = os.environ.get(name)
    return Path(v) if v else default


BARS = _p("ETF_BARS_PARQUET", ROOT / "data/bronze/tushare/tushare-f4f7c81a15b5779c/bars_daily.parquet")
ADJ = _p("ETF_ADJ_PARQUET", ROOT / "data/bronze/tushare/tushare-f4f7c81a15b5779c/fund_adj.parquet")
SYMBOLS = _p("ETF_SYMBOLS_PARQUET", ROOT / "data/bronze/tushare/tushare-f4f7c81a15b5779c/symbols.parquet")
IDX = _p("ETF_INDEX_PARQUET", ROOT / "data/bronze/tushare/tushare_index-86318b52ea0fbe04/index_daily.parquet")
FETCHED = _p("ETF_FETCHED_DIR", ROOT / "data/bronze/tushare/etf_rotation")
WAREHOUSE = _p("ETF_WAREHOUSE_DUCKDB", ROOT / "data/warehouse.duckdb")
