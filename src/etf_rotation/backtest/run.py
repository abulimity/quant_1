"""基于 bt 引擎的仓位记账与净值仿真。

输入为「目标权重面板」（index=交易日、columns=标的）。bt 负责现金、持仓、
换手与净值记账；成本通过 bt 的比例佣金回调实现（单边 bps），闲置现金按年化
cash_rate 计息。执行价用当日收盘价（bt 单一价格模型），等价于 T 日信号、
T+1 收盘成交的日度近似。
"""
from __future__ import annotations

import bt
import pandas as pd


class _DailyWeights(bt.algos.Algo):
    def __init__(self, weights: pd.DataFrame, cash_rate: float):
        super().__init__()
        self.weights = weights
        self.daily = (1 + cash_rate) ** (1 / 252) - 1

    def __call__(self, target):
        # 闲置现金按年化计息：adjust(flow=False) 表示计入净值的收入而非资金流
        if self.daily and not target.bankrupt:
            target.adjust(target.capital * self.daily, flow=False)

        now = target.now
        if now in self.weights.index:
            w = self.weights.loc[now]
            invested = float(w.sum())
            # 把「总权重 ≤1」拆成 bt 语义：temp['weights'] 之和为 1，
            # temp['cash'] 为留存现金比例（Rebalance 据此分配）
            if invested > 0:
                tw = {c: float(v) / invested for c, v in w.items() if v > 0}
            else:
                tw = {}
            target.temp["weights"] = tw
            target.temp["cash"] = max(0.0, 1.0 - invested)
        else:
            target.temp["weights"] = {}
            target.temp["cash"] = 1.0
        return True


def run(weights, open_price, close_price, cost_bps=8, cash_rate=0.018):
    """把目标权重面板喂给 bt 记账，返回净值与日收益序列。

    open_price 为预留形参（bt 单价格模型用 close_price 成交，等价 T+1 收盘），
    未接入 T+1 开盘 + 跳空顺延（见 TODO.md）。
    """
    close_price = close_price.ffill()  # 停牌日以前收价估值，避免 bt 对 NaN 持仓报错
    w = weights.reindex(index=close_price.index, columns=close_price.columns).fillna(0.0)
    # 停牌/缺失价日的持仓按现金处理，避免向 NaN 价格分配资金
    w = w.mask(close_price.isna(), 0.0)
    # 只把「实际持有过」的标的交给 bt，缩小记账树
    active = w.columns[(w > 0).any(axis=0)]
    w = w[active]
    close_price = close_price[active]
    # 比例佣金：每笔成交额 × 单边 bps（买卖各计一侧）
    commission = lambda q, p: abs(q) * p * cost_bps / 10000.0  # noqa: E731
    strat = bt.Strategy(
        "etf_rotation",
        [bt.algos.RunDaily(), _DailyWeights(w, cash_rate), bt.algos.Rebalance()],
    )
    backtest = bt.Backtest(
        strat,
        close_price,
        initial_capital=1.0,
        commissions=commission,
        integer_positions=False,
        progress_bar=False,
    )
    backtest.run()
    values = backtest.strategy.values.reindex(close_price.index).ffill()
    nav = values / values.iloc[0]
    returns = nav.pct_change(fill_method=None).fillna(nav.iloc[0] - 1)
    return pd.DataFrame({"nav": nav, "returns": returns})

