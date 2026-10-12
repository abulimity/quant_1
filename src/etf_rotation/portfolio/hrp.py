"""层次风险平价（HRP）权重：PyPortfolioOpt 薄封装。"""
import pandas as pd
from pypfopt import risk_models
from pypfopt.hierarchical_portfolio import HRPOpt


def hrp_weights(returns: pd.DataFrame) -> pd.Series:
    """250 日收益 → 协方差 → 相关系数 → 距离矩阵 → single-linkage 聚类
    → 递归二分 + 组内逆方差 → 归一化权重（研报 §3.2 的 HRP 流程）。"""
    returns = returns.dropna(axis=1)
    if returns.shape[1] == 0:
        return pd.Series(dtype=float)
    if returns.shape[1] == 1:
        return pd.Series(1.0, index=returns.columns)
    cov = risk_models.sample_cov(returns, returns_data=True)
    hrp = HRPOpt(returns=returns, cov_matrix=cov)
    return pd.Series(hrp.optimize(linkage_method="single"), index=returns.columns)

