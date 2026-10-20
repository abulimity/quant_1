"""参数 schema 校验（ml4t-canonical-schema）：类型 + 范围 + 未知键检查。"""
from __future__ import annotations


class ConfigError(ValueError):
    """参数配置错误：未知键、类型不符或越界。"""


# 叶子参数校验规则：(type, min, max)；min/max 为 None 表示不约束该端。
# 类型：int 不接受 bool；float 接受 int/float；list/str 见 _check_type。
SCHEMA = {
    "trend.windows": (list, None, None),
    "trend.rank_weights": (list, None, None),
    "trend.ann_factor": (int, 1, 10000),
    "trend.weighting": (str, None, None),
    "reversal.ema_span": (int, 1, 1000),
    "reversal.z_window": (int, 1, 1000),
    "reversal.zbias_threshold": (float, -100, 100),
    "reversal.repair_lookback": (int, 1, 100),
    "reversal.momentum_weight": (float, 0, 1),
    "market_state.alpha": (float, 0, 1),
    "market_state.slope_window": (int, 1, 100),
    "market_state.bull_threshold": (float, -1, 1),
    "market_state.bear_threshold": (float, -1, 1),
    "market_state.slope_up": (float, 0, 10),
    "market_state.slope_down": (float, 0, 10),
    "dedupe.corr_threshold": (float, 0, 1),
    "dedupe.max_holdings": (int, 1, 100),
    "multi_asset.risk": (float, 0, 1),
    "multi_asset.nasdaq": (float, 0, 1),
    "multi_asset.gold": (float, 0, 1),
    "multi_asset.nasdaq_exit_threshold": (float, -1, 1),
    "multi_asset.gold_exit_threshold": (float, -1, 1),
    "risk.llm80_alpha": (float, 0, 1),
    "risk.index_drop_20d": (float, -1, 0),
    "risk.overheat_pct": (float, 0, 10),
    "risk.vol_target_risk": (float, 0, 1),
    "risk.vol_target_nasdaq": (float, 0, 1),
    "risk.vol_target_gold": (float, 0, 1),
    "risk.vol_target_portfolio": (float, 0, 1),
    "risk.vol_window": (int, 1, 1000),
    "risk.port_vol_window": (int, 1, 1000),
    "defensive.rebalance_days": (int, 1, 1000),
    "defensive.top_n": (int, 1, 100),
    "defensive.max_vol_60d": (float, 0, 1),
    "defensive.momentum_window": (int, 1, 1000),
    "execution.phases": (int, 1, 100),
    "execution.phase_interval": (int, 1, 100),
    "execution.hysteresis_improve": (float, 0, 1),
    "execution.gap_delay_pct": (float, 0, 1),
    "costs.one_side_bps": (int, 0, 1000),
    "costs.cash_rate_annual": (float, 0, 1),
    "universe.min_listed_days": (int, 1, 10000),
    "universe.min_avg_amount20": (int, 0, 10**12),
    "hrp.window": (int, 1, 1000),
    "nasdaq_etf": (str, None, None),
    "gold_etf": (str, None, None),
}


def _flatten(node: dict, prefix: str = "") -> dict:
    """把嵌套参数树平铺为点分键。"""
    out = {}
    for k, v in node.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _check_type(typ: type, val) -> bool:
    if typ is int:
        return isinstance(val, int) and not isinstance(val, bool)
    if typ is float:
        return isinstance(val, (int, float)) and not isinstance(val, bool)
    if typ is list:
        return isinstance(val, list)
    if typ is str:
        return isinstance(val, str)
    return False


def validate_params(params: dict) -> dict:
    """校验参数树：未知键、类型、范围；失败抛 ConfigError（含字段路径）。"""
    for key, val in _flatten(params).items():
        if key not in SCHEMA:
            raise ConfigError(f"unknown param: {key}")
        typ, lo, hi = SCHEMA[key]
        if not _check_type(typ, val):
            raise ConfigError(f"{key}: expected {typ.__name__}, got {type(val).__name__}")
        if lo is not None and val < lo:
            raise ConfigError(f"{key}={val} below min {lo}")
        if hi is not None and val > hi:
            raise ConfigError(f"{key}={val} above max {hi}")
    return params
