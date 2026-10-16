"""基于 bt 引擎的仓位记账与净值仿真。

输入为「目标权重面板」（index=交易日、columns=标的）。bt 负责现金、持仓、
换手与净值记账；成本通过 bt 的比例佣金回调实现（单边 bps），闲置现金按年化
cash_rate 计息。执行价用当日收盘价（bt 单一价格模型），等价于 T 日信号、
T+1 收盘成交的日度近似。
"""
from __future__ import annotations

from dataclasses import dataclass
import warnings

import bt
import pandas as pd

from etf_rotation.backtest.open_rebalance import OpenRebalance


@dataclass
class BacktestResult:
    nav: pd.Series
    returns: pd.Series
    stats: pd.Series
    turnover: pd.Series
    cash: pd.Series
    positions: pd.DataFrame
    fees: pd.Series
    result: bt.backtest.Result


def _flat_commission(cost_bps: float):
    """单边比例佣金回调：|q| * p * bps / 1e4。

    bt.Backtest 的 commissions 参数支持 callable（官方文档中的
    "original flat hook"）；本策略是规则驱动、名义本金归一、单边 bps 假设，
    无成交量/波动率冲击建模需求，故保留平铺回调，不引入 CostModel。
    """
    def commission(q, p):
        return abs(q) * p * cost_bps / 10000.0

    return commission


class _CashInterest(bt.algos.Algo):
    def __init__(self, cash_rate: float):
        super().__init__()
        self.daily = (1 + cash_rate) ** (1 / 252) - 1

    def __call__(self, target):
        # 闲置现金按年化计息：adjust(flow=False) 是 bt 官方文档中
        # "commission / dividend 类非资金流收入" 的记账原语，计入净值而非资金流。
        if self.daily and not target.bankrupt:
            target.adjust(target.capital * self.daily, flow=False)
        return True


def run(weights, open_price, close_price, cost_bps=8, cash_rate=0.018,
        execution="close", gap_delay_pct=0.01):
    """把目标权重面板喂给 bt 记账，返回净值与日收益序列。

    execution="close" 沿用 bt 标准 `Rebalance`（单价格模型，成交/估值共用收盘价）；
    execution="open" 换成自定义 `OpenRebalance`：按 T+1 开盘价成交、收盘价估值，
    叠加买入高开顺延与停牌跳过。
    """
    close_price = close_price.ffill()  # 停牌日以前收价估值，避免 bt 对 NaN 持仓报错
    # 统一索引 dtype 为 datetime64[ns]：bt 预处理后的 universe 索引是 ns，而
    # tushare 日历索引可能是 us，二者 dtype 不一致会触发 bidoffer 的 setup 校验。
    idx = pd.DatetimeIndex(close_price.index).astype("datetime64[ns]")
    close_price = close_price.set_axis(idx)
    open_price = open_price.reindex(index=idx, columns=close_price.columns)
    w = weights.reindex(index=idx, columns=close_price.columns).fillna(0.0)
    # 停牌/缺失价日的持仓按现金处理，避免向 NaN 价格分配资金
    w = w.mask(close_price.isna(), 0.0)
    # 只把「实际持有过」的标的交给 bt，缩小记账树
    active = w.columns[(w > 0).any(axis=0)]
    w = w[active]
    close_price = close_price[active]
    open_price = open_price[active]

    if execution == "open":
        rebalance_algo = OpenRebalance(gap_delay_pct)
        additional = {
            "target_weights": w,
            "bidoffer": pd.DataFrame(0.0, index=close_price.index, columns=close_price.columns),
            "open_price": open_price,
            "close_price": close_price,
        }
    elif execution == "close":
        rebalance_algo = bt.algos.Rebalance()
        additional = {"target_weights": w}
    else:
        raise ValueError(f"unknown execution mode: {execution!r} (expected 'close' or 'open')")

    strat = bt.Strategy(
        "etf_rotation",
        [bt.algos.RunDaily(), _CashInterest(cash_rate),
         bt.algos.WeighTarget("target_weights"), rebalance_algo],
    )
    backtest = bt.Backtest(
        strat,
        close_price,
        initial_capital=1.0,
        commissions=_flat_commission(cost_bps),
        integer_positions=False,
        progress_bar=False,
        additional_data=additional,
    )
    result = bt.run(backtest)
    name = backtest.name
    # 官方净值曲线：Result.prices 即 ffn GroupStats 的价格指数（起点 PAR=100）。
    # 只丢弃 bt 在 t0-1 注入的 bootstrap 行，保持输出索引与真实交易日一致。
    prices = result.prices[name].reindex(close_price.index)
    nav = prices / prices.iloc[0]
    returns = nav.pct_change(fill_method=None).fillna(nav.iloc[0] - 1)
    with warnings.catch_warnings():
        # bt 在访问 outlays / positions 时会对多标的宽表逐列 insert，触发 pandas
        # 的 PerformanceWarning（性能提示，非正确性问题），这里只在该访问点屏蔽。
        warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
        turnover = backtest.turnover
        # positions 采用各标的占总组合的权重（0~1），与目标权重同口径，便于检查
        # 延迟/停牌是否按目标权重成交（引擎 share 数量口径对使用者不直观）。
        positions = backtest.security_weights.reindex(close_price.index)
    cash = backtest.strategy.cash.reindex(close_price.index)
    fees = backtest.strategy.fees.reindex(close_price.index)
    return BacktestResult(
        nav=nav,
        returns=returns,
        stats=result.stats[name],
        turnover=turnover,
        cash=cash,
        positions=positions,
        fees=fees,
        result=result,
    )

