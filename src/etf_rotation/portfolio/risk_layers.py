"""分层风控：市场状态 / A 股趋势 / 单标的过热 / 波动率控制。"""


def risk_scale(market: str, idx_above_llt: bool, idx_drop_20d: float) -> float:
    """风险资产基础缩放：危险=0，震荡=0.95，其余 1.0；
    创业板跌破 80 日 LLT 且 LLT 20 日跌超 3% 时降至 0.05。"""
    if market == "bear":
        return 0.0
    base = 0.95 if market == "range" else 1.0
    if (not idx_above_llt) and idx_drop_20d < -0.03:
        return 0.05
    return base


def vol_scale(realized_vol: float, target_vol: float) -> float:
    """波动率缩放：超目标同比缩减，低于目标不放大（只减不加）。"""
    if realized_vol <= target_vol:
        return 1.0
    return target_vol / realized_vol


def overheat_mask(close, llt80, pct: float) -> bool:
    """单标的过热：价格高于自身 80 日 LLT 达 pct（20%）→ 权重归零。"""
    return close.iloc[-1] >= llt80.iloc[-1] * (1 + pct)

