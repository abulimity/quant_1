"""T+1 跳空顺延：买入标的 T+1 高开 ≥ pct 时，该笔买入顺延一个交易日。"""


def delay_orders(orders, open_, close, pct):
    """缺口 = T+1 开盘 / T 收盘 − 1；高开达阈值则把当日买单平移到下一日。"""
    out = orders.copy()
    buy = orders > 0
    prev_close = close.shift(1)
    gap = open_ / prev_close - 1
    delayed = buy & (gap >= pct)
    shifted = orders.where(delayed).shift(1).fillna(0.0)
    out = orders.where(~delayed, 0.0) + shifted
    return out

