"""层次风险平价（HRP）权重：PyPortfolioOpt 薄封装。

HRP 的直觉：与其做「最小方差优化」（对协方差估计误差极敏感），
不如用层次聚类把标的按相关性分组，再在组内按逆方差分配、组间二分递归。
这样得到的权重天然分散、不依赖对协方差矩阵的精确估计。
"""
import pandas as pd
from pypfopt import risk_models
from pypfopt.hierarchical_portfolio import HRPOpt


def hrp_weights(returns: pd.DataFrame) -> pd.Series:
    """250 日收益 → 协方差 → 相关系数 → 距离矩阵 → single-linkage 聚类
    → 递归二分 + 组内逆方差 → 归一化权重（研报 §3.2 的 HRP 流程）。

    步骤与公式：
      ① 协方差 Σ：sample_cov 用 Ledoit-Wolf 收缩估计
         —— 样本短（250 日）、标的多时，样本协方差矩阵噪声大，
            收缩可把估计向结构化目标（等相关 + 对角）拉近，显著更稳健
      ② 相关性矩阵 ρ = Σ_ij / (σ_i·σ_j)
      ③ 距离矩阵 d_ij = √(0.5·(1 − ρ_ij))   （0 = 完全正相关，1 = 零相关）
      ④ 层次聚类：single-linkage（单连接）
         —— 选单连接而非平均/完全连接：单连接对「链条式」的高相关群体更敏感，
            能把同主题的一串标的聚成紧簇，避免在簇内重复配置
      ⑤ 递归二分：对每个簇按距离用准 Diou 指标切成两半，递归到单资产
      ⑥ 组内逆方差配权：w_i ∝ 1/σ_i，再在簇层面做同样的二分配权
      ⑦ 归一化：Σw = 1（HRPOpt.optimize 已保证）

    边界：只剩 1 只标的时直接给权重 1.0（HRP 在单资产上无定义）。
    """
    returns = returns.dropna(axis=1)
    if returns.shape[1] == 0:
        return pd.Series(dtype=float)
    if returns.shape[1] == 1:
        return pd.Series(1.0, index=returns.columns)
    # PyPortfolioOpt 默认用 Ledoit-Wolf 收缩估计协方差，样本短、标的多时更稳健。
    cov = risk_models.sample_cov(returns, returns_data=True)
    hrp = HRPOpt(returns=returns, cov_matrix=cov)
    # 聚类方式：single-linkage（单连接）
    return pd.Series(hrp.optimize(linkage_method="single"), index=returns.columns)
