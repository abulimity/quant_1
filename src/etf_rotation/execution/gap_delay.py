def delay_orders(orders, open_, close, pct):
    out = orders.copy()
    buy = orders > 0
    prev_close = close.shift(1)
    gap = open_ / prev_close - 1
    delayed = buy & (gap >= pct)
    shifted = orders.where(delayed).shift(1).fillna(0.0)
    out = orders.where(~delayed, 0.0) + shifted
    return out

