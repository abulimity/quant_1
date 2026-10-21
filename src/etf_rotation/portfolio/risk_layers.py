"""分层风控：市场状态 / A 股趋势 / 单标的过热 / 波动率控制。

四层风控的共同语义是「只减不加」：任何一层触发都只会缩小风险敞口，
不会放大仓位。这样做的原因有两点：
  ① 放大仓位等于加杠杆，与「轮动择时」的低风险定位冲突；
  ② 单向调整让每一层的阈值都有明确方向，便于做敏感性分析与归因。

四层作用对象：
  risk_scale       — 风险腿整体缩放（市场状态 × A 股趋势）
  vol_scale        — 任意一腿按波动率缩放（风险腿 / 纳指 / 黄金 / 组合整体）
  overheat_mask    — 单只风险 ETF 过热时单独清零
  （第四层「组合波动上限」在 pipeline._apply_portfolio_vol_cap 实现）
"""


def risk_scale(market: str, idx_above_llt: bool, idx_drop_20d: float,
               drop_threshold: float = -0.03) -> float:
    """风险资产基础缩放：危险=0，震荡=0.95，其余 1.0；
    创业板跌破 80 日 LLT 且 LLT 20 日跌超 3% 时降至 0.05。

    公式（状态缩放）：
      bear → 0；range → 0.95；bull → 1.0
    公式（趋势叠加，优先级高于状态缩放）：
      若「创业板指已跌破 80 日 LLT」且 LLT₂₀日变化 < −3% → 0.05
      —— 趋势崩塌时把风险腿压到近乎清空（保留 5% 以免完全空仓导致手续费与
         重新建仓的滑点放大），这一档覆盖上面三种状态缩放。
    """
    if market == "bear":
        return 0.0
    base = 0.95 if market == "range" else 1.0
    # A 股趋势崩塌：跌破 80 日 LLT 且 LLT 自身 20 日跌幅超阈值
    if (not idx_above_llt) and idx_drop_20d < drop_threshold:
        return 0.05
    return base


def vol_scale(realized_vol: float, target_vol: float) -> float:
    """波动率缩放：超目标同比缩减，低于目标不放大（只减不加）。

    公式：scale = min(1, v_target / v_realized)
      —— realized_vol ≤ target_vol → scale = 1.0（不放大）
      —— 否则 scale = v_target / v_realized，等比缩减到目标波动
    """
    if realized_vol <= target_vol:
        return 1.0
    return target_vol / realized_vol


def overheat_mask(close, llt80, pct: float) -> bool:
    """单标的过热：价格高于自身 80 日 LLT 达 pct（20%）→ 权重归零。

    判据：P_t ≥ LLT₈₀,t·(1+pct)
      —— 相对自身趋势线偏离过大，视为「趋势已过热」，清仓该标的。

    注意：主流水线已在 pipeline._apply_overheat 接入过热退出；本函数保留为
    单标的判定参考，未被主流水线调用。
    """
    return close.iloc[-1] >= llt80.iloc[-1] * (1 + pct)
