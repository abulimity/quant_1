"""一次性引导：从 tushare 拉取 ETF 日线 + 复权因子 + 标的表，存为 bronze parquet。

用法：python scripts/fetch_etf_bars.py [START] [END] [--out DIR] [--no-env]
默认区间 2015-01-01 ~ 2026-07-31，按交易日逐日调用 fund_daily / fund_adj，
速率受 tushare 限制，全量约需数十分钟；请勿频繁重跑。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
import tushare as ts
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data/bronze/tushare/etf_rotation"


def _retry(fn, tries=4, wait=1.5):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(wait * (2 ** i))
    return None


def _write_env(out: Path) -> None:
    envp = ROOT / ".env"
    lines = envp.read_text(encoding="utf-8").splitlines() if envp.exists() else []
    updates = {
        "ETF_BARS_PARQUET": (out / "bars_daily.parquet").as_posix(),
        "ETF_ADJ_PARQUET": (out / "fund_adj.parquet").as_posix(),
        "ETF_SYMBOLS_PARQUET": (out / "symbols.parquet").as_posix(),
    }
    lines = [l for l in lines if not any(l.startswith(k + "=") for k in updates)]
    lines += [f"{k}={v}" for k, v in updates.items()]
    envp.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("start", nargs="?", default="2015-01-01")
    ap.add_argument("end", nargs="?", default="2026-07-31")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-env", action="store_true")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        raise SystemExit("TUSHARE_TOKEN missing in .env")

    out = Path(args.out) if args.out else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    pro = ts.pro_api(token)

    fb = _retry(lambda: pro.fund_basic(
        market="E", fields="ts_code,name,fund_type,invest_type,list_date,delist_date"))
    fb = fb.dropna(subset=["ts_code"]).drop_duplicates("ts_code")
    sym = pd.DataFrame({"symbol_id": range(len(fb)), "ticker": fb["ts_code"].values})
    sym["exchange"] = ["XSHG" if t.endswith(".SH") else "XSHE" for t in sym["ticker"]]
    sym["calendar"] = sym["exchange"]
    sym["currency"] = "CNY"
    sym["isin"] = None
    sym["lot_size"] = 100
    sym["listed_on"] = pd.to_datetime(fb["list_date"], format="%Y%m%d", errors="coerce")
    sym["delisted_on"] = pd.NaT
    tick2id = dict(zip(sym["ticker"], sym["symbol_id"]))
    sym.to_parquet(out / "symbols.parquet", index=False)

    cal = _retry(lambda: pro.trade_cal(
        exchange="SSE", start_date=args.start.replace("-", ""),
        end_date=args.end.replace("-", ""), is_open="1"))
    days = list(cal["cal_date"])
    bars_parts, adj_parts = [], []
    for i, d in enumerate(days):
        df = _retry(lambda: pro.fund_daily(trade_date=d))
        if df is not None and not df.empty:
            df = df.dropna(subset=["close"]).copy()
            df["symbol_id"] = df["ts_code"].map(tick2id)
            df = df[df["symbol_id"].notna()]
            df["ts"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
            df = df[["symbol_id", "ts", "open", "high", "low", "close", "vol"]]
            df = df.rename(columns={"vol": "volume"})
            df["currency"] = "CNY"
            bars_parts.append(df)
        af = _retry(lambda: pro.fund_adj(trade_date=d))
        if af is not None and not af.empty:
            af = af.copy()
            af["symbol_id"] = af["ts_code"].map(tick2id)
            af = af[af["symbol_id"].notna()]
            af["ts"] = pd.to_datetime(af["trade_date"], format="%Y%m%d")
            adj_parts.append(af[["symbol_id", "ts", "adj_factor"]])
        if (i + 1) % 50 == 0:
            print(f"{i + 1}/{len(days)} days", flush=True)
        time.sleep(0.12)

    bars = pd.concat(bars_parts, ignore_index=True) if bars_parts else pd.DataFrame(
        columns=["symbol_id", "ts", "open", "high", "low", "close", "volume", "currency"])
    bars.to_parquet(out / "bars_daily.parquet", index=False)
    adj = pd.concat(adj_parts, ignore_index=True) if adj_parts else pd.DataFrame(
        columns=["symbol_id", "ts", "adj_factor"])
    adj.to_parquet(out / "fund_adj.parquet", index=False)

    if not args.no_env and args.out is None:
        _write_env(out)
        print("已写入 .env 的 ETF_BARS/ADJ/SYMBOLS 路径覆盖")
    print(f"done: {len(sym)} symbols, {len(bars)} bar rows, {len(adj)} adj rows -> {out}")


if __name__ == "__main__":
    main()

