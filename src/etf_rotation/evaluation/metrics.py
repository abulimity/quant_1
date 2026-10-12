"""绩效/风险指标（ml4t-tearsheet / ml4t-risk-metrics 公式，numpy 手算）。"""
import numpy as np


def summary(returns, periods: int = 252) -> dict:
    """日收益 → 年化收益/波动、Sharpe、Sortino、最大回撤、Calmar、VaR/CVaR。"""
    r = returns.dropna()
    cum = (1 + r).cumprod()
    dd = cum / cum.cummax() - 1
    ann = (1 + r).prod() ** (periods / len(r)) - 1
    vol = r.std() * np.sqrt(periods)
    sharpe = r.mean() / r.std() * np.sqrt(periods) if r.std() > 0 else 0.0
    downside = np.minimum(r, 0)
    sortino = r.mean() / downside.std() * np.sqrt(periods) if downside.std() > 0 else 0.0
    max_dd = dd.min()
    calmar = ann / abs(max_dd) if max_dd < 0 else 0.0
    var = r.quantile(0.05)
    return {
        "ann_return": ann, "ann_vol": vol, "sharpe": sharpe, "sortino": sortino,
        "max_drawdown": max_dd, "calmar": calmar,
        "var_95": var, "cvar_95": r[r <= var].mean(),
    }

