"""补充 tushare 数据：中证2000/中证红利指数 + ETF fund_basic。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from etf_rotation.config import load_token
from etf_rotation.data import ingest

OUT = Path("data/bronze/tushare/etf_rotation")


def main() -> None:
    """补充拉取指数日线（中证2000/中证红利/上证/创业板/沪深300）与 ETF 基础信息。

    逐标的容错：单个失败只打印、不中断整个脚本。
    """
    load_dotenv()
    token = load_token()
    if not token:
        raise SystemExit("TUSHARE_TOKEN missing in .env")
    OUT.mkdir(parents=True, exist_ok=True)
    # 前两个是市场状态所需的中证指数，后三个用于基准（沪深300）与 A 股风控（创业板）
    for code in ["932000.CSI", "000922.CSI", "000001.SH", "399006.SZ", "000300.SH"]:
        try:
            df = ingest.fetch_index_daily(token, code, "2015-01-01", "2026-07-31")
            df.to_parquet(OUT / f"{code}.parquet", index=False)
            print(f"{code}: {len(df)} rows")
        except Exception as e:  # noqa: BLE001
            print(f"{code}: FAILED {e}")
    try:
        fb = ingest.fetch_fund_basic(token)
        fb.to_parquet(OUT / "fund_basic.parquet", index=False)
        print(f"fund_basic: {len(fb)} rows")
    except Exception as e:  # noqa: BLE001
        print(f"fund_basic: FAILED {e}")


if __name__ == "__main__":
    main()

