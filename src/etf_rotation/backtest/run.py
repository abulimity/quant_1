"""基于 bt 引擎的仓位记账与净值仿真。

输入为「目标权重面板」（index=交易日、columns=标的）。bt 负责现金、持仓、
换手与净值记账；成本通过 bt 的比例佣金回调实现（单边 bps），闲置现金按年化
cash_rate 计息。默认执行价用 T+1 开盘价（OpenRebalance），等价于 T 日信号、
T+1 开盘成交；execution="close" 可选回退到收盘成交。

记账流水线（Algo 顺序即执行顺序，不可调换）：
    RunDaily       —— 逐日推进
    _CashInterest  —— 现金计息（计入净值，非资金流）
    WeighTarget    —— 把目标权重面板写进 target.temp["weights"]
    Rebalance / OpenRebalance —— 实际成交（买入/卖出/顺延）
"""
from __future__ import annotations

from dataclasses import dataclass
import warnings

import bt
import pandas as pd

from etf_rotation.backtest.open_rebalance import OpenRebalance


@dataclass
class BacktestResult:
    """回测输出容器。

    字段
    ----
    nav        : 归一化净值（起点 1.0），index = 交易日
    returns    : 日收益率序列（首日为 nav[0] − 1）
    stats      : bt 官方统计（年化收益/波动/Sharpe/最大回撤等）
    turnover   : 日换手率
    cash       : 现金余额（占组合比例）
    positions  : 各标的占总组合的权重（0~1），与目标权重同口径
    fees       : 累计交易费用
    result     : bt 原生 Result（成交明细、订单簿等原始记录）
    """
    nav: pd.Series
    returns: pd.Series
    stats: pd.Series
    turnover: pd.Series
    cash: pd.Series
    positions: pd.DataFrame
    fees: pd.Series
    result: bt.backtest.Result


def _flat_commission(cost_bps: float):
    """单边比例佣金回调：cost = |q|·p·bps/1e4。

    bt.Backtest 的 commissions 参数支持 callable（官方文档中的
    "original flat hook"）；本策略是规则驱动、名义本金归一、单边 bps 假设，
    无成交量/波动率冲击建模需求，故保留平铺回调，不引入 CostModel。
    公式：cost = |q| × p × bps / 1e4（q = 成交股数，p = 成交价）
    """
    def commission(q, p):
        """比例佣金回调：cost = |q| × p × bps / 1e4。

        q：成交股数（有符号，买入正 / 卖出负），取绝对值保证买卖同向计费；
        p：成交价（bt 从价格面板里取当日执行价，open 口径下即开盘价）。
        """
        return abs(q) * p * cost_bps / 10000.0

    return commission


class _CashInterest(bt.algos.Algo):
    """闲置现金按年化 cash_rate 日复利计息。

    决策（TODO 3.5）：维持「现金计息」而非「显式现金资产」（cash 列复利 + 权重补
    1-Σw）。当前口径下现金不占权重、只计息，等价于无风险利率的净值加成；若改为
    显式现金资产属改变数值，需回 Part 1 流程重新确立基线。留待后续评估。

    公式：daily = (1+r)^(1/252) − 1
      —— r 为年化 cash_rate，(1/252) 次方把年化利率折算为日复利，
         故 T 日利息 = capital × daily
    """

    def __init__(self, cash_rate: float):
        """把年化 cash_rate 折算成日利率并缓存，供每日 __call__ 复用。

        参数
        ----
        cash_rate : float
            年化现金利率（config/params.yaml 的 costs.cash_rate_annual）。
        """
        super().__init__()
        # 日利率：daily = (1+r)^(1/252) − 1
        self.daily = (1 + cash_rate) ** (1 / 252) - 1

    def __call__(self, target):
        """按日利率给组合注入利息，计入净值而非资金流。

        闲置现金按年化计息：adjust(flow=False) 是 bt 官方文档中
        "commission / dividend 类非资金流收入" 的记账原语，计入净值而非资金流。
        利息 = target.capital × daily（capital 为组合总资产）
        """
        if self.daily and not target.bankrupt:
            target.adjust(target.capital * self.daily, flow=False)
        return True


def run(weights, open_price, close_price, cost_bps=8, cash_rate=0.018,
        execution="open", gap_delay_pct=0.01):
    """把目标权重面板喂给 bt 记账，返回净值与日收益序列。

    默认 execution="open" 走自定义 `OpenRebalance`：按 T+1 开盘价成交、收盘价估值，
    叠加买入高开顺延与停牌跳过；execution="close" 沿用 bt 标准 `Rebalance`
    （单价格模型，成交/估值共用收盘价）。

    关键口径
    --------
    - 停牌日估值：close_price.ffill()，用前收价盯市，避免 bt 对 NaN 持仓报错
    - 缺失价日持仓：w.mask(close_price.isna(), 0.0)，不向 NaN 价格分配资金
    - 净值归一：nav = prices / prices.iloc[0]，起点恒为 1.0
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
        # 自定义 Algo：开盘成交 + 收盘估值，叠加跳空顺延与停牌跳过
        rebalance_algo = OpenRebalance(gap_delay_pct)
        additional = {
            "target_weights": w,
            # bidoffer 必须存在（全 0 即可），bt 才允许用自定义 price 成交
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
        # Algo 顺序：逐日推进 → 现金计息 → 写目标权重 → 成交
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
    # bt 的 Result.prices 可能缺失前导「纯现金」交易日（尤其 open 执行的顺延/停牌
    # 使首笔成交后移），此时 reindex 产生前导 NaN；用首有效值补齐再归一化，避免
    # 前导 NaN 经 prices.iloc[0] 把整条净值带成 NaN。
    prices = prices.ffill().bfill()
    # 归一化净值：nav_t = prices_t / prices_0（起点恒为 1.0）
    nav = prices / prices.iloc[0]
    # 日收益：首日用 nav_0 − 1 兜底（起点 1.0 时首日收益为 0）
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

