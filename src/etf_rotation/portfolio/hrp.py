import pandas as pd
from pypfopt import risk_models
from pypfopt.hierarchical_portfolio import HRPOpt


def hrp_weights(returns: pd.DataFrame) -> pd.Series:
    returns = returns.dropna(axis=1)
    if returns.shape[1] == 0:
        return pd.Series(dtype=float)
    if returns.shape[1] == 1:
        return pd.Series(1.0, index=returns.columns)
    cov = risk_models.sample_cov(returns, returns_data=True)
    hrp = HRPOpt(returns=returns, cov_matrix=cov)
    return pd.Series(hrp.optimize(linkage_method="single"), index=returns.columns)

