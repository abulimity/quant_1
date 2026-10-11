"""端到端流水线：数据 → 信号 → 组合 → 执行 → 回测。"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from etf_rotation import config
from etf_rotation.data import calendar, universe as univ
from etf_rotation.portfolio import defensive as defn
from etf_rotation.portfolio import dedupe, hrp, multi_asset, risk_layers
from etf_rotation.signals import market_state as ms
from etf_rotation.signals import trend

ROOT = Path(__file__).resolve().parents[2]
BARS = ROOT / "data/bronze/tushare/tushare-f4f7c81a15b5779c/bars_daily.parquet"
ADJ = ROOT / "data/bronze/tushare/tushare-f4f7c81a15b5779c/fund_adj.parquet"
SYMBOLS = ROOT / "data/bronze/tushare/tushare-f4f7c81a15b5779c/symbols.parquet"
IDX = ROOT / "data/bronze/tushare/tushare_index-86318b52ea0fbe04/index_daily.parquet"
FETCHED = ROOT / "data/bronze/tushare/etf_rotation"


def _read_parquet(path: Path) -> pd.DataFrame:
    con = duckdb.connect()
    df = con.execute(f"SELECT * FROM read_parquet('{path.as_posix()}')").fetchdf()
    con.close()
    return df


def load_prices() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bars = _read_parquet(BARS)
    adj = _read_parquet(ADJ)
    sym = _read_parquet(SYMBOLS)
    m = bars.merge(adj, on=["symbol_id", "ts"], how="left")
    m["adj_factor"] = m.groupby("symbol_id")["adj_factor"].ffill().fillna(1.0)
    last = m.groupby("symbol_id")["adj_factor"].transform("last")
    m["close_adj"] = m["close"] * m["adj_factor"] / last
    ticker = sym.set_index("symbol_id")["ticker"]
    m["ticker"] = m["symbol_id"].map(ticker)
    m = m.dropna(subset=["ticker"])
    close = m.pivot(index="ts", columns="ticker", values="close_adj").sort_index()
    opn = m.pivot(index="ts", columns="ticker", values="open").sort_index()
    amount = (m["close"] * m["volume"] * 100).rename("amount")
    amt = pd.concat([m[["ts", "ticker"]], amount], axis=1).pivot(
        index="ts", columns="ticker", values="amount"
    ).sort_index()
    return close, opn, amt


def load_indices() -> dict[str, pd.Series]:
    idx = _read_parquet(IDX)
    out = {}
    for code in ["000001.SH", "399006.SZ", "000300.SH"]:
        s = idx[idx["ts_code"] == code].set_index("ts")["close"].sort_index()
        out[code] = s
    for code in ["932000.CSI", "000922.CSI"]:
        s = _read_parquet(FETCHED / f"{code}.parquet").set_index("ts")["close"].sort_index()
        out[code] = s
    return out


def load_fund_basic() -> pd.DataFrame:
    return _read_parquet(FETCHED / "fund_basic.parquet")


def momentum_panel(logp: pd.DataFrame, window: int) -> pd.DataFrame:
    """向量化的时间加权回归趋势分面板（列=ticker）。"""
    x = np.arange(1, window + 1, dtype=float)
    w = x / x.sum()
    xw = (w * x).sum()
    denom = (w * (x - xw) ** 2).sum()
    arr = logp.to_numpy()
    n, m = arr.shape
    out = np.full((n, m), np.nan)
    chunk = 128
    for c in range(0, m, chunk):
        sub = arr[:, c : c + chunk]
        y = np.lib.stride_tricks.sliding_window_view(sub, window, axis=0)  # (n-w+1, k, w)
        yw = np.tensordot(y, w, axes=([2], [0]))
        slope = np.tensordot(y, w * (x - xw), axes=([2], [0])) / denom
        yhat = slope[..., None] * x + (yw - slope * xw)[..., None]
        ss_res = np.tensordot((y - yhat) ** 2, w, axes=([2], [0]))
        ss_tot = np.tensordot((y - yw[..., None]) ** 2, w, axes=([2], [0]))
        r2 = 1 - ss_res / np.where(ss_tot > 0, ss_tot, 1.0)
        r2 = np.where(ss_tot > 0, r2, 0.0)
        mom = (np.exp(250 * slope) - 1) * r2
        out[window - 1 :, c : c + chunk] = mom
    return pd.DataFrame(out, index=logp.index, columns=logp.columns)


def build_weights(params: dict, start: str, end: str) -> pd.DataFrame:
    close, opn, amt = load_prices()
    indices = load_indices()
    fb = load_fund_basic()
    cat = univ.classify(fb)

    days = calendar.trading_days(start, end)

    logp = np.log(close)
    m21 = momentum_panel(logp, 21)
    m60 = momentum_panel(logp, 60)
    ret = close.pct_change(fill_method=None)
    vol60 = ret.rolling(60).std() * np.sqrt(252)
    n_days = close.notna().cumsum()
    avg20 = amt.rolling(20).mean()

    # 市场状态
    comp = ms.composite_score(
        {"sh": indices["000001.SH"],
         "zz2000": indices["932000.CSI"],
         "zzhl": indices["000922.CSI"]},
        alpha=params["market_state"]["alpha"],
    )
    regime = comp.map(
        lambda v: "bull" if v >= params["market_state"]["bull_threshold"]
        else ("bear" if v <= params["market_state"]["bear_threshold"] else "range")
    )

    nasdaq = params["nasdaq_etf"]
    gold = params["gold_etf"]
    nas_mom = trend.momentum_score(close[nasdaq], 60)
    gold_mom = trend.momentum_score(close[gold], 60)
    nas_vol = close[nasdaq].pct_change(fill_method=None).ewm(span=60).std() * np.sqrt(252)
    gold_vol = close[gold].pct_change(fill_method=None).ewm(span=60).std() * np.sqrt(252)

    # A 股趋势约束（创业板 80 日 LLT）
    cyb = indices["399006.SZ"]
    cyb_vol = cyb.pct_change(fill_method=None).ewm(span=60).std() * np.sqrt(252)
    cyb_llt = ms.llt(cyb, params["risk"]["llm80_alpha"])
    cyb_below = cyb < cyb_llt
    cyb_drop = cyb_llt.pct_change(20, fill_method=None)

    # 风险池与防守池（逐日 point-in-time 资格）
    risk_tickers = [t for t, c in cat.items() if c == "risk" and t in close.columns]
    def_tickers = [t for t, c in cat.items() if c in ("bond", "money") and t in close.columns]

    # 逐日计算目标权重（五相位：每日仅 1 相位更新）
    phase_weights = [pd.Series(0.0, index=[nasdaq, gold]) for _ in range(5)]
    cols = sorted(set([nasdaq, gold] + risk_tickers + def_tickers))
    weights = pd.DataFrame(0.0, index=days, columns=cols)
    last_def_update = -10**9
    current_defn: list[str] = []

    for i, d in enumerate(days):
        phase = i % 5
        base = multi_asset.base_weights(regime.iloc[i], nas_mom.iloc[i], gold_mom.iloc[i])
        rscale = risk_layers.risk_scale(
            regime.loc[d],
            bool(cyb_below.loc[d]) is False if pd.notna(cyb_below.loc[d]) else True,
            float(cyb_drop.loc[d]) if pd.notna(cyb_drop.loc[d]) else 0.0,
        )
        if pd.notna(cyb_vol.loc[d]):
            rscale *= risk_layers.vol_scale(float(cyb_vol.loc[d]),
                                            params["risk"]["vol_target_risk"])
        risk_budget = base["risk"] * rscale

        target = {}
        if risk_budget > 0 and i >= 170:
            elig = [
                t for t in risk_tickers
                if n_days.loc[d, t] >= params["universe"]["min_listed_days"]
                and pd.notna(avg20.loc[d, t])
                and avg20.loc[d, t] >= params["universe"]["min_avg_amount20"]
                and pd.notna(m21.loc[d, t]) and pd.notna(m60.loc[d, t])
            ]
            if elig:
                m = 0.7 * m21.loc[d, elig].rank(pct=True) + 0.3 * m60.loc[d, elig].rank(pct=True)
                m = m[m21.loc[d, elig] > 0].sort_values(ascending=False)
                cands = list(m.index[: 3 * params["dedupe"]["max_holdings"]])
                corr = ret[cands].loc[:d].tail(250).corr()
                keep = dedupe.dedupe(cands, corr, params["dedupe"]["corr_threshold"],
                                     params["dedupe"]["max_holdings"])
                keep = [t for t in keep
                        if ret[t].loc[:d].tail(250).notna().sum() >= 100]
                if len(keep) >= 2:
                    r = ret[keep].loc[:d].tail(250).dropna(axis=1)
                    w = hrp.hrp_weights(r)
                    for t, v in w.items():
                        target[t] = float(v) * risk_budget
                elif len(keep) == 1:
                    target[keep[0]] = risk_budget
        if base["nasdaq"] > 0:
            v = risk_layers.vol_scale(float(nas_vol.loc[d]) if pd.notna(nas_vol.loc[d]) else 0.0,
                                      params["risk"]["vol_target_nasdaq"])
            target[nasdaq] = base["nasdaq"] * v
        if base["gold"] > 0:
            v = risk_layers.vol_scale(float(gold_vol.loc[d]) if pd.notna(gold_vol.loc[d]) else 0.0,
                                      params["risk"]["vol_target_gold"])
            target[gold] = base["gold"] * v

        # 防守资金
        allocated = sum(target.values())
        if allocated < 1.0 and i >= 60:
            if i - last_def_update >= params["defensive"]["rebalance_days"]:
                current_defn = defn.select(
                    ret[def_tickers].loc[:d].tail(250),
                    vol60.loc[d, def_tickers].dropna(),
                    {t: cat.get(t, "risk") for t in def_tickers},
                )
                last_def_update = i
            if current_defn:
                w = (1.0 - allocated) / len(current_defn)
                for t in current_defn:
                    target[t] = target.get(t, 0.0) + w

        phase_weights[phase] = pd.Series(target).reindex(cols).fillna(0.0)
        combined = pd.concat(phase_weights, axis=1).mean(axis=1)
        weights.loc[d, combined.index] = combined.values

    return weights


def market_regime(start: str, end: str) -> pd.Series:
    """按三指数 LLT 复合分划分 bull/range/bear（与策略一致）。"""
    indices = load_indices()
    days = calendar.trading_days(start, end)
    comp = ms.composite_score(
        {
            "sh": indices["000001.SH"],
            "zz2000": indices["932000.CSI"],
            "zzhl": indices["000922.CSI"],
        }
    ).reindex(days)
    return comp.map(
        lambda v: "bull" if v >= 0.35 else ("bear" if v <= -0.35 else "range")
    )


def compute_benchmark(params: dict, start: str, end: str) -> pd.DataFrame:
    """等权持有可投资风险池（每日再平衡）与沪深300 的归一化净值。"""
    close, _, amt = load_prices()
    indices = load_indices()
    fb = load_fund_basic()
    cat = univ.classify(fb)
    days = calendar.trading_days(start, end)

    ret = close.pct_change(fill_method=None)
    n_days = close.notna().cumsum()
    avg20 = amt.rolling(20).mean()
    risk = [t for t, c in cat.items() if c == "risk" and t in close.columns]

    elig = (n_days[risk] >= params["universe"]["min_listed_days"]) & (
        avg20[risk] >= params["universe"]["min_avg_amount20"]
    )
    r_risk = ret[risk].where(elig, np.nan)
    bench_ret = r_risk.mean(axis=1, skipna=True).reindex(days).fillna(0.0)
    bench_ret = bench_ret.shift(1).fillna(0.0)  # 对齐策略：T 日持仓、T+1 起计收益
    bench_nav = (1 + bench_ret).cumprod()

    hs = indices.get("000300.SH")
    hs_ret = hs.reindex(days).pct_change(fill_method=None).fillna(0.0)
    hs_ret = hs_ret.shift(1).fillna(0.0)
    hs_nav = (1 + hs_ret).cumprod()
    return pd.DataFrame({"benchmark": bench_nav, "hs300": hs_nav}, index=days)

