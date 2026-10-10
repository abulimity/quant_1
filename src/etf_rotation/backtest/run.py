import pandas as pd


def run(weights, open_price, close_price, cost_bps=8, cash_rate=0.018):
    w = weights.reindex(columns=close_price.columns).fillna(0.0)
    ret = close_price.pct_change().fillna(0.0)
    nav = 1.0
    navs = []
    prev = pd.Series(0.0, index=w.columns)
    daily_cash = (1 + cash_rate) ** (1 / 252) - 1
    for t in range(len(w)):
        target = w.iloc[t]
        if t > 0:
            trade = (target - prev).abs().sum()
            nav *= 1 - trade * cost_bps / 10000
        gross = (target * ret.iloc[t]).sum()
        nav *= 1 + gross + (1 - target.sum()) * daily_cash
        prev = target
        navs.append(nav)
    nav_s = pd.Series(navs, index=w.index)
    return pd.DataFrame({"nav": nav_s, "returns": nav_s.pct_change().fillna(nav_s.iloc[0] - 1)})

