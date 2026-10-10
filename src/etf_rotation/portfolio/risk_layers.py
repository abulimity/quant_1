def risk_scale(market: str, idx_above_llt: bool, idx_drop_20d: float) -> float:
    if market == "bear":
        return 0.0
    base = 0.95 if market == "range" else 1.0
    if (not idx_above_llt) and idx_drop_20d < -0.03:
        return 0.05
    return base


def vol_scale(realized_vol: float, target_vol: float) -> float:
    if realized_vol <= target_vol:
        return 1.0
    return target_vol / realized_vol


def overheat_mask(close, llt80, pct: float) -> bool:
    return close.iloc[-1] >= llt80.iloc[-1] * (1 + pct)

