"""多重检验校正：Deflated Sharpe Ratio（Bailey–López de Prado 近似）。"""
import numpy as np
from scipy import stats


def deflated_sharpe(sharpes, n_trials: int) -> float:
    """给定一组候选年化 Sharpe 与试验总数，返回「观测最优高于零假设期望最优」
    的概率；>0.95 视为显著。注意非独立试验会低估校正。"""
    per = np.asarray(sharpes) / np.sqrt(252)
    euler = 0.5772156649
    sr_std = per.std(ddof=1)
    e_max = sr_std * (
        (1 - euler) * stats.norm.ppf(1 - 1 / n_trials)
        + euler * stats.norm.ppf(1 - 1 / (n_trials * np.e))
    )
    obs = per.max()
    sr_se = np.sqrt(1 / (len(per) - 1))
    return float(stats.norm.cdf((obs - e_max) / sr_se))

