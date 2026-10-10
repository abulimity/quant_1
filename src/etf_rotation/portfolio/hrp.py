import pandas as pd
from pypfopt import risk_models
from pypfopt.hierarchical_portfolio import HRPOpt


def hrp_weights(returns: pd.DataFrame) -> pd.Series:
    cov = risk_models.sample_cov(returns, returns_data=True)
    hrp = HRPOpt(returns=returns, cov_matrix=cov)
    return pd.Series(hrp.optimize(linkage_method="single"), index=returns.columns)

