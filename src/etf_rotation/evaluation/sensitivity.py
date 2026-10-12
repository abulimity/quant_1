"""参数敏感性：通用网格扫描（当前仅成本维度实际调用）。"""
import itertools

import pandas as pd


def sweep(run_fn, grid: dict) -> pd.DataFrame:
    """对参数网格逐点跑 run_fn，返回含 Sharpe/回撤/年化/Calmar 的结果表。"""
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

