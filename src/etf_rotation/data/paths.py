"""数据路径解析：默认指向本地 bronze 快照，可用环境变量覆盖。

目录分层（data/ 被 git 忽略）：
    data/bronze/tushare/<snapshot_id>/  —— tushare 原始落盘（只读输入）
    data/bronze/tushare/etf_rotation/   —— 补充拉取的单文件（指数、fund_basic）
    data/warehouse.duckdb               —— 派生产物（curate 后的面板 + 日历）

⚠️ 同步要求：路径里硬编码了 tushare 快照目录名 `tushare-f4f7c81a15b5779c`。
   换数据目录（如重新拉取产生新的 snapshot_id）时，必须同步修改本文件与
   `data/calendar.py`、`data/pipeline.py` 中的同一路径，否则会读到不存在的文件。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]   # 仓库根目录（src/etf_rotation/data → 上溯三级）


def _p(name: str, default: Path) -> Path:
    """解析数据路径：优先取环境变量覆盖值，未设置时退回仓库内默认路径。

    覆盖方式（便于在不改代码的前提下指向别处的数据快照）：
        ETF_BARS_PARQUET / ETF_ADJ_PARQUET / ETF_SYMBOLS_PARQUET /
        ETF_INDEX_PARQUET / ETF_FETCHED_DIR / ETF_WAREHOUSE_DUCKDB
    """
    v = os.environ.get(name)
    return Path(v) if v else default


# ETF 日线行情（bronze 原始表：symbol_id, ts, open, high, low, close, volume, amount）
BARS = _p("ETF_BARS_PARQUET", ROOT / "data/bronze/tushare/tushare-f4f7c81a15b5779c/bars_daily.parquet")
# ETF 复权因子表（symbol_id, ts, adj_factor）
ADJ = _p("ETF_ADJ_PARQUET", ROOT / "data/bronze/tushare/tushare-f4f7c81a15b5779c/fund_adj.parquet")
# 标的映射表（symbol_id → ticker、名称等）
SYMBOLS = _p("ETF_SYMBOLS_PARQUET", ROOT / "data/bronze/tushare/tushare-f4f7c81a15b5779c/symbols.parquet")
# 指数日线全量表（含全部指数，用于取未单独拉取的指数）
IDX = _p("ETF_INDEX_PARQUET", ROOT / "data/bronze/tushare/tushare_index-86318b52ea0fbe04/index_daily.parquet")
# 补充拉取目录：单指数文件（000001.SH / 399006.SZ / 000300.SH / 932000.CSI / 000922.CSI）与 fund_basic
FETCHED = _p("ETF_FETCHED_DIR", ROOT / "data/bronze/tushare/etf_rotation")
# 仓库（duckdb）：curate 后的 close_adj / bars_daily / trading_calendar 等
WAREHOUSE = _p("ETF_WAREHOUSE_DUCKDB", ROOT / "data/warehouse.duckdb")
