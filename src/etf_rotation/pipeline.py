"""端到端流水线：数据 → 信号 → 组合 → 执行 → 回测。"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from etf_rotation import config
from etf_rotation.data import calendar, universe as univ
from etf_rotation.data.paths import ADJ, BARS, FETCHED, IDX, SYMBOLS, WAREHOUSE
from etf_rotation.portfolio import defensive as defn
from etf_rotation.portfolio import dedupe, hrp, multi_asset, risk_layers
from etf_rotation.signals import market_state as ms
from etf_rotation.signals import trend

def _read_parquet(path: Path) -> pd.DataFrame:
    """用 duckdb 读 parquet（比 pandas 读更快、省内存）。"""
    con = duckdb.connect()
    df = con.execute(f"SELECT * FROM read_parquet('{path.as_posix()}')").fetchdf()
    con.close()
    return df


def load_prices() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """优先读 warehouse（close_adj + bars_daily），为空回退 bronze 复权重算。"""
    con = duckdb.connect(str(WAREHOUSE))
    try:
        close_adj = con.execute(
            "SELECT s.ticker, c.ts, c.close_adj FROM close_adj c "
            "JOIN symbols s ON s.symbol_id = c.symbol_id").fetchdf()
        bars = con.execute(
        "SELECT s.ticker, b.ts, b.open, b.close, b.amount FROM bars_daily b "
            "JOIN symbols s ON s.symbol_id = b.symbol_id").fetchdf()
    finally:
        con.close()
    if close_adj.empty:
        return _load_prices_from_bronze()
    close = close_adj.pivot(index="ts", columns="ticker", values="close_adj").sort_index()
    # 开盘价按「收盘复权比例」做后复权，与 close_adj 保持同一量纲（否则除权/拆分日
    # 的原始开盘价与后复权收盘价跨量纲，T+1 开盘成交会产生虚假的超额买卖）。
    m = bars.merge(close_adj, on=["ticker", "ts"], how="left")
    m["open_adj"] = np.where(m["close"] != 0, m["open"] * m["close_adj"] / m["close"], np.nan)
    opn = m.pivot(index="ts", columns="ticker", values="open_adj").sort_index()
    amt = m.pivot(index="ts", columns="ticker", values="amount").sort_index()
    return close, opn, amt


def _load_prices_from_bronze() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """加载复权收盘价、开盘价、成交额三个「交易日 × 标的」面板。

    复权口径：后复权（各标的以自身最新一期复权因子为基准），
    与研报 Wind 口径有差异，属 H9 假设。成交额按 close × volume × 100 估算
    （volume 单位为手）。
    """
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
    m["open_adj"] = np.where(m["close"] != 0, m["open"] * m["close_adj"] / m["close"], np.nan)
    opn = m.pivot(index="ts", columns="ticker", values="open_adj").sort_index()
    amount = (m["close"] * m["volume"] * 100).rename("amount")
    amt = pd.concat([m[["ts", "ticker"]], amount], axis=1).pivot(
        index="ts", columns="ticker", values="amount"
    ).sort_index()
    return close, opn, amt


def load_indices() -> dict[str, pd.Series]:
    """加载市场指数：上证/创业板/沪深300（优先取已拉取文件）+ 中证2000/中证红利。"""
    idx = _read_parquet(IDX)
    out = {}
    for code in ["000001.SH", "399006.SZ", "000300.SH"]:
        p = FETCHED / f"{code}.parquet"
        if p.exists():
            s = _read_parquet(p).set_index("ts")["close"].sort_index()
        else:
            s = idx[idx["ts_code"] == code].set_index("ts")["close"].sort_index()
        out[code] = s
    for code in ["932000.CSI", "000922.CSI"]:
        s = _read_parquet(FETCHED / f"{code}.parquet").set_index("ts")["close"].sort_index()
        out[code] = s
    return out


def load_fund_basic() -> pd.DataFrame:
    """读取 ETF 基础信息表（名称/类型/上市日期），用于标的分类与 point-in-time 池。"""
    return _read_parquet(FETCHED / "fund_basic.parquet")


def momentum_panel(logp: pd.DataFrame, window: int) -> pd.DataFrame:
    """向量化的时间加权回归趋势分面板（列 = ticker，与 trend.momentum_score 同公式）。

    对每个标的的对数价序列，用最近 window 期做时间加权最小二乘：
    Slope 是回归斜率（年化 250 日后经 exp 映射为动量），R² 是拟合优度折扣因子；
    最终 Momentum = (exp(250·Slope) − 1) · R²。此处用滑动窗口视图一次算完全列
    （按 chunk 分批以控制内存），替代 trend.momentum_score 的逐标的循环。
    """
    x = np.arange(1, window + 1, dtype=float)  # 时间序号 1..window
    w = x / x.sum()  # H1：线性时间权重，越近权重越大
    xw = (w * x).sum()  # 时间序号的加权均值
    denom = (w * (x - xw) ** 2).sum()  # 时间序号的加权方差（斜率的分母）
    arr = logp.to_numpy()
    n, m = arr.shape
    out = np.full((n, m), np.nan)  # 前 window-1 期没有回归结果，保持 NaN
    chunk = 128  # 按列分批，避免一次性构造 (n, 全列, window) 的三维张量撑爆内存
    for c in range(0, m, chunk):
        sub = arr[:, c : c + chunk]
        # 滑动窗口视图 shape (n-w+1, k, w)：每行是长度为 w 的滚动对数价窗口
        y = np.lib.stride_tricks.sliding_window_view(sub, window, axis=0)
        yw = np.tensordot(y, w, axes=([2], [0]))  # 加权均值（回归截距项）
        slope = np.tensordot(y, w * (x - xw), axes=([2], [0])) / denom  # 加权最小二乘斜率
        yhat = slope[..., None] * x + (yw - slope * xw)[..., None]  # 回归拟合线
        ss_res = np.tensordot((y - yhat) ** 2, w, axes=([2], [0]))  # 加权残差平方和
        ss_tot = np.tensordot((y - yw[..., None]) ** 2, w, axes=([2], [0]))  # 加权总平方和
        r2 = 1 - ss_res / np.where(ss_tot > 0, ss_tot, 1.0)  # 拟合优度（除零保护）
        r2 = np.where(ss_tot > 0, r2, 0.0)  # 总平方和为 0（无波动）时 R² 记为 0
        mom = (np.exp(250 * slope) - 1) * r2  # 250 日年化斜率 → 动量，乘 R² 折扣
        out[window - 1 :, c : c + chunk] = mom  # 窗口右端对齐，第 window 日才有值
    return pd.DataFrame(out, index=logp.index, columns=logp.columns)


def _precompute_signals(close, opn, amt, indices, params, cat) -> dict:
    """全历史信号预计算（保证 2019 起点也有足够 warmup；无前视）。"""
    logp = np.log(close)
    m21 = momentum_panel(logp, 21)
    m60 = momentum_panel(logp, 60)
    ret = close.pct_change(fill_method=None)
    vol60 = ret.rolling(60).std() * np.sqrt(252)
    n_days = close.notna().cumsum()
    avg20 = amt.rolling(20).mean()

    # 市场状态：三指数 LLT 复合分 → bull/range/bear
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

    # 纳指/黄金：各自 60 日动量（转负即退）与 60 日 EWMA 波动
    nasdaq = params["nasdaq_etf"]
    gold = params["gold_etf"]
    nas_mom = trend.momentum_score(close[nasdaq], 60)
    gold_mom = trend.momentum_score(close[gold], 60)
    nas_vol = close[nasdaq].pct_change(fill_method=None).ewm(span=60).std() * np.sqrt(252)
    gold_vol = close[gold].pct_change(fill_method=None).ewm(span=60).std() * np.sqrt(252)

    # A 股趋势约束：创业板指跌破 80 日 LLT 且 LLT 20 日跌超 3% → 风险仓降至 5%
    cyb = indices["399006.SZ"]
    cyb_vol = cyb.pct_change(fill_method=None).ewm(span=60).std() * np.sqrt(252)
    cyb_llt = ms.llt(cyb, params["risk"]["llm80_alpha"])
    cyb_below = cyb < cyb_llt
    cyb_drop = cyb_llt.pct_change(20, fill_method=None)

    # 风险池与防守池（逐日 point-in-time 资格）
    risk_tickers = [t for t, c in cat.items() if c == "risk" and t in close.columns]
    def_tickers = [t for t, c in cat.items() if c in ("bond", "money") and t in close.columns]
    # 每只风险 ETF 的 80 日 LLT（列式 apply，用于单 ETF 过热退出）
    llt80 = close[risk_tickers].apply(lambda s: ms.llt(s, params["risk"]["llm80_alpha"]))
    # 反转面板：14 日 EMA 偏离经 170 日滚动 z-score（均值/标准差 .shift(1) 防前视）
    ema = close[risk_tickers].ewm(span=params["reversal"]["ema_span"], adjust=False).mean()
    logbias = np.log(close[risk_tickers] / ema)
    mu = logbias.rolling(params["reversal"]["z_window"]).mean().shift(1)
    sd = logbias.rolling(params["reversal"]["z_window"]).std().shift(1)
    zbias = (logbias - mu) / sd
    rev_active = (zbias <= params["reversal"]["zbias_threshold"]) & (
        zbias > zbias.shift(params["reversal"]["repair_lookback"]))

    return dict(
        m21=m21, m60=m60, ret=ret, vol60=vol60, n_days=n_days, avg20=avg20,
        regime=regime, nas_mom=nas_mom, gold_mom=gold_mom, nas_vol=nas_vol,
        gold_vol=gold_vol, cyb_vol=cyb_vol, cyb_below=cyb_below, cyb_drop=cyb_drop,
        llt80=llt80, close=close, zbias=zbias, rev_active=rev_active,
        risk_tickers=risk_tickers, def_tickers=def_tickers, cat=cat,
    )


def _zscore(s: pd.Series) -> pd.Series:
    """横截面 z-score（ddof=0）；无波动时返回全零，保持排序稳定。"""
    sd = s.std(ddof=0)
    return (s - s.mean()) / sd if sd > 0 else pd.Series(0.0, index=s.index)


def _range_score(mom_rank, zbias, active):
    """震荡市综合分：动量分与反转分各自横截面 z-score 后 50/50 相加（H5/H6）。"""
    rev = (-zbias).where(active, 0.0)
    return _zscore(mom_rank) + _zscore(rev)


def _apply_overheat(target, close_d, llt80_d, pct):
    """单 ETF 过热退出：收盘价 ≥ 自身 80 日 LLT × (1+pct) 时权重归零。"""
    out = dict(target)
    for t in list(out):
        c, l = close_d.get(t), llt80_d.get(t)
        if pd.notna(c) and pd.notna(l) and c >= l * (1 + pct):
            out.pop(t, None)
    return out


def _daily_target(i: int, d, sig: dict, params: dict,
                  last_def_update: int, current_defn: list[str]) -> tuple:
    """计算单日目标权重（T 日信号），返回
    (target, last_def_update, current_defn, risk_score, keep)。
    risk_score 覆盖风险池全量 ticker（可投资且 m21>0 者填当日排名分，其余 NaN）。"""
    nasdaq = params["nasdaq_etf"]
    gold = params["gold_etf"]
    regime = sig["regime"]
    nas_mom, gold_mom = sig["nas_mom"], sig["gold_mom"]
    nas_vol, gold_vol = sig["nas_vol"], sig["gold_vol"]
    cyb_below, cyb_drop, cyb_vol = sig["cyb_below"], sig["cyb_drop"], sig["cyb_vol"]
    m21, m60 = sig["m21"], sig["m60"]
    ret, vol60 = sig["ret"], sig["vol60"]
    n_days, avg20 = sig["n_days"], sig["avg20"]
    risk_tickers, def_tickers = sig["risk_tickers"], sig["def_tickers"]
    cat = sig["cat"]

    # 日期对齐取当日信号（勿用 .iloc[i]，见 build_weights 顶部说明）
    nas_sig = float(nas_mom.loc[d]) if pd.notna(nas_mom.loc[d]) else 0.0
    gold_sig = float(gold_mom.loc[d]) if pd.notna(gold_mom.loc[d]) else 0.0
    base = multi_asset.base_weights(regime.loc[d], nas_sig, gold_sig)
    # 分层风控：市场状态 × A 股趋势 × 波动率控制，共同缩放风险预算
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
    risk_score = pd.Series(np.nan, index=risk_tickers)
    keep: list[str] = []
    # 预热门限（既有设定）：回测起点后前 170 个交易日不建风险仓。
    if risk_budget > 0 and i >= 170:
        # point-in-time 可投资风险池：上市天数 + 20 日均成交额过滤
        elig = [
            t for t in risk_tickers
            if n_days.loc[d, t] >= params["universe"]["min_listed_days"]
            and pd.notna(avg20.loc[d, t])
            and avg20.loc[d, t] >= params["universe"]["min_avg_amount20"]
            and pd.notna(m21.loc[d, t]) and pd.notna(m60.loc[d, t])
        ]
        if elig:
            # 横截面排名：21 日动量 70% + 60 日动量 30%；21 日动量为负剔除
            mom = 0.7 * m21.loc[d, elig].rank(pct=True) + 0.3 * m60.loc[d, elig].rank(pct=True)
            mom = mom[m21.loc[d, elig] > 0]
            # 震荡市叠加反转分（H5/H6），其余市场状态沿用纯动量排名
            if regime.loc[d] == "range":
                score = _range_score(mom, sig["zbias"].loc[d, mom.index],
                                     sig["rev_active"].loc[d, mom.index])
            else:
                score = mom
            risk_score.loc[score.index] = score
            cands = list(score.sort_values(ascending=False).index[: 3 * params["dedupe"]["max_holdings"]])
            # 相关性去重（0.80）→ 持仓上限 10 → HRP 配权
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
    # 单 ETF 过热退出：风险资产 HRP 配权后、纳指/黄金之前归零过热标的
    target = _apply_overheat(
        target, sig["close"].loc[d], sig["llt80"].loc[d],
        params["risk"]["overheat_pct"])
    if base["nasdaq"] > 0:
        # 纳指按 60 日波动向 18% 目标缩放（只减不加）
        v = risk_layers.vol_scale(float(nas_vol.loc[d]) if pd.notna(nas_vol.loc[d]) else 0.0,
                                  params["risk"]["vol_target_nasdaq"])
        target[nasdaq] = base["nasdaq"] * v
    if base["gold"] > 0:
        # 黄金按 60 日波动向 18% 目标缩放（只减不加）
        v = risk_layers.vol_scale(float(gold_vol.loc[d]) if pd.notna(gold_vol.loc[d]) else 0.0,
                                  params["risk"]["vol_target_gold"])
        target[gold] = base["gold"] * v

    # 防守仓预热 60 个交易日后才启用；仅在风险仓未满配（有剩余资金）时承接，每 120 日重选
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

    return target, last_def_update, current_defn, risk_score, keep


def _combine_phases(phase_weights: list[pd.Series]) -> pd.Series:
    """五相位目标平滑：5 个相位等权汇总。

    每天只有 1 个相位重新计算，其余 4 个相位沿用旧值；等权平均后，
    任一相位的变化只影响组合权重的 1/5，从而摊薄单日调仓冲击与换手。
    """
    return pd.concat(phase_weights, axis=1).mean(axis=1)


def _apply_portfolio_vol_cap(candidate, port_rets, params):
    """组合 20 日 EWMA 波动上限（只减不加）：超 34% 时整体等比缩减。

    与研报 §2.6「超目标同比缩减，只减不加」一致：波动低于目标时不放大，
    只有超过目标时才把候选权重整体等比缩减（差额转现金）。不使用
    `bt.algos.TargetVol`（其是双向目标，会把低波动组合放大）。
    """
    target = params["risk"]["vol_target_portfolio"]
    span = params["risk"]["port_vol_window"]
    vol = 0.0
    if port_rets:
        vol = float(
            pd.Series(port_rets).ewm(span=span, adjust=False).std().iloc[-1]
            * np.sqrt(252)
        )
    scale = risk_layers.vol_scale(vol, target) if pd.notna(vol) and vol > 0 else 1.0
    return candidate * scale, scale


def _apply_hysteresis(candidate, prev_final, score, risk_tickers, improve):
    """整组迟滞（H4）：新风险组合得分未较旧组合明显改善时维持旧组合。

    score 为当日风险池横截面排名分；新得分 = 候选组合中风险标的 score 之和，
    旧得分 = 当前持仓中风险标的 score 之和。新得分 ≤ 旧得分×(1+improve) 且
    原风险持仓仍有效（都在当日 score 索引中）时维持旧组合，否则切换。
    """
    held_risk = [t for t in prev_final.index if prev_final[t] > 0 and t in risk_tickers]
    if not held_risk or not all(pd.notna(score.get(t)) for t in held_risk):
        return candidate
    new_score = float(score.reindex(candidate[candidate > 0].index).dropna().sum())
    old_score = float(score.reindex(held_risk).sum())
    if new_score <= old_score * (1 + improve):
        return prev_final
    return candidate


def build_weights(params: dict, start: str, end: str) -> pd.DataFrame:
    """计算策略目标权重面板（index=回测交易日、columns=标的、每行和 ≤ 1）。

    主线：市场状态定基础风险预算 → 风险池横截面动量排名 + 去重 + HRP 配权
    → 纳指/黄金各自波动缩放 → 防守仓承接剩余资金 → 五相位（每日仅 1 相位更新）。

    注意：信号相关序列（regime/nas_mom/...）都在全历史（2015 起）上计算，
    回测循环按日期 d 用 `.loc[d]` 取当日值；严禁用 `.iloc[i]` 按位置取
    （全历史序列与回测窗口错位约 4 年，曾导致前视错位 bug，见代码审阅手册 §8.1）。
    """
    close, opn, amt = load_prices()
    indices = load_indices()
    fb = load_fund_basic()
    cat = univ.classify(fb)
    days = calendar.trading_days(start, end)
    sig = _precompute_signals(close, opn, amt, indices, params, cat)

    nasdaq, gold = params["nasdaq_etf"], params["gold_etf"]
    cols = sorted(set([nasdaq, gold] + sig["risk_tickers"] + sig["def_tickers"]))
    phase_weights = [pd.Series(0.0, index=cols) for _ in range(5)]
    weights = pd.DataFrame(0.0, index=days, columns=cols)
    last_def_update = -10**9
    current_defn: list[str] = []
    prev_final = pd.Series(0.0, index=cols)
    port_rets: list[float] = []
    improve = params["execution"]["hysteresis_improve"]

    for i, d in enumerate(days):
        target, last_def_update, current_defn, score, keep = _daily_target(
            i, d, sig, params, last_def_update, current_defn)
        phase_weights[i % 5] = pd.Series(target).reindex(cols).fillna(0.0)
        candidate = _combine_phases(phase_weights)
        candidate = _apply_hysteresis(
            candidate, prev_final, score, sig["risk_tickers"], improve)
        # port_rets 只 append「上一日最终权重 × 当日收益」，只用 ≤d 的信息（无前视）。
        if i > 0:
            prev_ret = float((prev_final * sig["ret"].loc[d, cols].fillna(0.0)).sum())
            port_rets.append(prev_ret)
        final, _ = _apply_portfolio_vol_cap(candidate, port_rets, params)
        weights.loc[d, final.index] = final.values
        prev_final = final

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

