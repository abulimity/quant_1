"""参数敏感性：通用网格扫描（当前仅成本维度实际调用）。"""
import itertools

import pandas as pd
import yaml


def parse_grid_spec(spec: str) -> tuple[str, list]:
    """--grid 参数解析：标量逗号分隔，或以 [ ... ] 表示的列表参数。"""
    key, raw = spec.split("=", 1)
    raw = raw.strip()
    if raw.startswith("["):
        return key, yaml.safe_load(raw)
    return key, [float(x) for x in raw.split(",")]


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


def robustness_score(results: pd.DataFrame, metric: str = "sharpe") -> float:
    """稳健性分数 = 网格中 metric > 0 的组合占比（ml4t-sensitivity-analysis）。"""
    return float((results[metric] > 0).mean())


def detect_cliffs(results: pd.DataFrame, params: list[str], metric: str = "sharpe") -> dict:
    """悬崖检测：相邻参数间 metric 变化 > 2×变化量标准差则标记（ml4t-sensitivity-analysis）。"""
    out = {}
    for p in params:
        s = results.sort_values(p)[metric]
        d = s.diff().abs()
        out[p] = {
            "cliff": bool(d.std() > 0 and d.max() > 2 * d.std()),
            "max_jump": float(d.max()),
        }
    return out

