"""bt 框架内的 T+1 开盘成交 Algo：开盘成交 + 收盘估值，叠加跳空顺延与停牌跳过。

bt 标准 `Rebalance` 是「单价格模型」（成交与估值共用 bar 价），做不到
「T+1 开盘成交 + 收盘估值」。bt 底层 `Security.transact(q, price=open)` 留了
自定义成交价旁路（前置条件是 setup 时传了 `bidoffer`，哪怕全 0）。本模块复刻
`Rebalance` 的「权重差 → 数量 → 佣金闭环」，仅把成交价换成开盘价，NAV/现金/
费用/成交明细/统计仍全部由 bt 产出，不另起炉灶重写记账引擎。

成交价与估值的口径分离：
  成交价 = open_price[T+1]   —— 信号在 T 日收盘生成，T+1 开盘撮合
  估值价 = close_price[T+1]  —— 持仓当日按收盘价盯市
因此 T+1 当日的收益 = (close/open − 1) 计入 T+1，这正是「T 日信号、T+1 成交」的
无前视实现。

两条顺延（pending）规则：
  ① 跳空顺延：买入开盘涨幅 ≥ gap_delay_pct（默认 1%）→ 当日不追价，顺延次日再试
  ② 停牌跳过：当日无开盘价（停牌/无成交）→ 买入增量顺延，卖出照常
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import bt


class OpenRebalance(bt.algos.Algo):
    """按 T+1 开盘价成交、收盘价估值；买入高开顺延、停牌跳过。

    参数
    ----
    gap_delay_pct : float
        买入跳空顺延阈值。判据：op / close_{T} − 1 ≥ gap_delay_pct 时放弃当日成交，
        把该标的的目标权重挂入 `_pending`，等下一个交易日再试（避免在高开时追价，
        把「开盘价成交」这一研报口径扭曲成「开盘跳空溢价成交」）。

    内部状态
    --------
    _pending : dict[ticker -> float]
        待成交的目标权重。顺延标的先于新目标成交；pending 合计超过 1 时按比例
        归一化，其余目标再按剩余预算等比缩放，保证权重和不超过 1（不引入杠杆）。
    """

    def __init__(self, gap_delay_pct=0.01):
        """缓存跳空阈值并初始化顺延队列。

        参数
        ----
        gap_delay_pct : float
            买入跳空顺延阈值（默认 0.01，即开盘价较前收盘高开 ≥1% 就顺延）。
        """
        super().__init__()
        self.gap_delay_pct = gap_delay_pct
        self._pending = {}  # ticker -> 顺延买入的目标权重

    def __call__(self, target):
        """执行当日调仓：平仓 → 合并 pending → 按开盘价成交 → 记账。

        流程
        ----
        1) 归一化 pending（合计 > 1 时按比例缩放到 1），并入有效目标 eff；
        2) 非 pending 部分按剩余预算 remaining = max(0, 1 − p_total) 等比缩放：
           scale = min(1, remaining / non_total)；
        3) 清空不在 eff 内的持仓（目标已归零的标的先卖出）；
        4) 逐标的成交：停牌（open 价 NaN）或买入跳超阈值 → 顺延；
           否则按 `delta = w − 当前权重` 计算成交金额。
        """
        weights = target.temp.get("weights")
        if weights is None:
            return True
        open_px = target.get_data("open_price")
        close_px = target.get_data("close_price")
        now = target.now

        # 顺延买入优先成交：先并入 pending，再把其余权重按剩余预算等比缩放，
        # 避免「max 合并」在多资产下让目标权重和 > 1 而引入杠杆。
        pending_now = set(self._pending)
        p_total = sum(self._pending.values())
        if p_total > 1.0:
            for t in list(self._pending):
                self._pending[t] /= p_total
            p_total = 1.0
        eff = dict(weights)
        for t, w in self._pending.items():
            eff[t] = w
        non_pending = [t for t in eff if t not in pending_now]
        non_total = sum(eff[t] for t in non_pending)
        if non_total > 0:
            # 剩余预算分配：scale = min(1, (1 − p_total) / non_total)
            remaining = max(0.0, 1.0 - p_total)
            scale = min(1.0, remaining / non_total)
            for t in non_pending:
                eff[t] *= scale

        base = target.value

        # 平掉不在有效目标内的持仓（与标准 Rebalance 相同的顺序与语义）
        for cname in list(target.children):
            if cname in eff:
                continue
            c = target.children[cname]
            if c.value != 0.0 and not np.isnan(c.value):
                target.close(cname, update=False)

        if "cash" in target.temp and not target.fixed_income:
            base *= 1 - target.temp["cash"]

        for ticker, w in eff.items():
            op = open_px.loc[now, ticker]
            target._create_child_if_needed(ticker)
            c = target.children[ticker]
            is_pending = ticker in pending_now
            if pd.isna(op):
                # 停牌/无成交：当日不成交，买入增量顺延、次日再试
                if w > c.weight:
                    self._pending[ticker] = w
                continue
            # 权重差 → 成交金额：delta = 目标权重 − 当前权重
            delta = w - c.weight
            if delta > 0 and not is_pending:
                # 跳空顺延判据：op / close_{T−1} − 1 ≥ gap_delay_pct → 今日不追价
                pc = close_px.shift(1).loc[now, ticker]
                if pd.notna(pc) and op / pc - 1 >= self.gap_delay_pct:
                    self._pending[ticker] = w
                    continue
            self._transact_at(target, c, delta * base, op)
            if is_pending:
                self._pending.pop(ticker, None)

        target.root.update(now)
        return True

    def _transact_at(self, target, child, amount, price):
        """复刻 `SecurityBase.allocate` 的「权重差→数量→佣金闭环」，仅成交价换成开盘价。

        两步公式：
          ① 名义数量：q = amount/(price·multiplier)
             —— multiplier 为合约乘子（ETF = 1），amount 为含佣金的现金流出预算
          ② 佣金闭环：迭代逼近「完整现金流出 = amount」
             —— 佣金按比例收取，outlay(q) > amount，故需下调 q
             迭代式：q ← q − (outlay(q) − amount)/(price·multiplier)
             收敛判据：|outlay(q) − amount| ≤ TOL（bt.core.TOL）
        卖出到清仓（amount + 当前市值 = 0）时直接取 q = −当前持仓股数。
        """
        if bt.core.is_zero(amount):
            return
        if child._needupdate or child.now != target.now:
            child.update(target.now)
        if bt.core.is_zero(price) or np.isnan(price):
            raise ValueError(
                f"Cannot allocate capital to {child.name} because price is {price} "
                f"as of {target.now}"
            )
        if bt.core.is_zero(amount + child._value):
            q = -child._position
        else:
            q = amount / (price * child.multiplier)
        if bt.core.is_zero(q) or np.isnan(q):
            return
        # 比例佣金闭环：与 allocate 相同地迭代逼近「完整现金流出 = amount」
        if q != -child._position:
            full_outlay, _, _, _ = child.outlay(q, p=price)
            i = 0
            last_q = q
            last_amount_short = full_outlay - amount
            while not np.isclose(full_outlay, amount, rtol=bt.core.TOL) and q != 0:
                dq = (full_outlay - amount) / (price * child.multiplier)
                q = q - dq
                full_outlay, _, _, _ = child.outlay(q, p=price)
                i += 1
                if i > 1e4:
                    raise RuntimeError(
                        "Potentially infinite loop detected in OpenRebalance commission search"
                    )
                if last_q == q:
                    raise RuntimeError(
                        "Newton-like quantity search is stuck in OpenRebalance"
                    )
                last_q = q
                if np.abs(full_outlay - amount) > np.abs(last_amount_short):
                    raise RuntimeError(
                        "The difference between outlay and amount grew in OpenRebalance"
                    )
                last_amount_short = full_outlay - amount
        child.transact(q, update=False, update_self=False, price=price)
