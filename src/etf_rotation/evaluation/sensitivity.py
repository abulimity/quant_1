import itertools

import pandas as pd


def sweep(run_fn, grid: dict) -> pd.DataFrame:
    rows = []
    keys = list(grid)
    for combo in itertools.product(*grid.values()):
        params = dict(zip(keys, combo))
        res = run_fn(**params)
        rows.append({
            **params,
            "sharpe": res["sharpe"], "max_drawdown": res["max_drawdown"],
            "ann_return": res["ann_return"], "calmar": res["calmar"],
        })
    return pd.DataFrame(rows)

