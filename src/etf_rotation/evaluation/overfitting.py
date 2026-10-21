"""多重检验校正：Deflated Sharpe Ratio（Bailey–López de Prado 近似）。

要解决的问题：扫描了 N 组参数，挑出最好的那组，它的 Sharpe 里有多少是
「选择偏差」而非真实 alpha？DSR 回答「观测到的最优值超过零假设下的期望最优值」
的概率有多大。

零假设：所有 N 个候选策略的真实 Sharpe 都来自同一分布（无技巧的随机结果）。
此时最大值的期望位置 e_max 由候选间的标准差 σ 与候选数 N 决定。
"""
import numpy as np
from scipy import stats


def deflated_sharpe(sharpes, n_trials: int, n_obs: int) -> float:
    """给定一组候选年化 Sharpe、试验总数与观测数（回测窗口内的日收益样本数），
    返回「观测最优高于零假设期望最优」的概率；>0.95 视为显著。

    标准误基于观测数 T（sqrt(1/(T-1))），而非候选数 N；候选数只进入期望最大值
    e_max。非独立试验会低估校正。

    公式（四步）：
      ① 折算为日频：per_i = SR_i/√252
      ② 零假设下期望最大值：e_max = σ_per·[(1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e))]
         —— γ = 欧拉-马斯克罗尼常数 0.5772156649；
            第二项修正「最大值的期望不只是正态分位数」的偏差
      ③ 观测最优：obs = max(per)
      ④ 标准误与 DSR：
         sr_se = √(1/(T−1))
         DSR = Φ((max(per) − e_max)/sr_se)
         —— Φ 为标准正态 CDF；值 > 0.95 意味着「即便考虑了多重检验，
            仍以 95% 置信度认为观测到的最优 Sharpe 高于随机挑选的期望水平」
    """
    per = np.asarray(sharpes) / np.sqrt(252)   # per_i = SR_i/√252
    euler = 0.5772156649
    sr_std = per.std(ddof=1)
    # e_max = σ_per·[(1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e))]
    e_max = sr_std * (
        (1 - euler) * stats.norm.ppf(1 - 1 / n_trials)
        + euler * stats.norm.ppf(1 - 1 / (n_trials * np.e))
    )
    obs = per.max()
    # sr_se = √(1/(T−1))：标准误来自回测样本长度 T（n_obs），不是候选数
    sr_se = np.sqrt(1 / (n_obs - 1))
    # DSR = Φ((max(per) − e_max)/sr_se)
    return float(stats.norm.cdf((obs - e_max) / sr_se))


def sharpe_haircut(sharpes) -> dict:
    """Sharpe 扣除选择上限（Bailey–López de Prado 近似）。年化口径。

    公式：
      per_i = SR_i/√252（折日频）
      e_max_per = σ_per·[(1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e))]（零假设期望最大值，日频）
      observed = max(per)·√252    （年化观测最优）
      expected = e_max_per·√252  （年化期望最优）
      haircut = observed − expected
    haircut 即「按选择偏差应扣除的 Sharpe」，数值越大说明选择偏差越强。
    """
    per = np.asarray(sharpes, dtype=float) / np.sqrt(252)
    n = len(per)
    euler = 0.5772156649
    sd = per.std(ddof=1)
    e_max_per = sd * (
        (1 - euler) * stats.norm.ppf(1 - 1 / n)
        + euler * stats.norm.ppf(1 - 1 / (n * np.e))
    )
    a = np.sqrt(252)                  # 日频 → 年化的换算因子
    observed = float(per.max() * a)
    expected = float(e_max_per * a)
    return {"observed_best": observed, "expected_max": expected, "haircut": observed - expected}
