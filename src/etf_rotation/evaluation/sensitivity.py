"""参数敏感性：通用网格扫描（当前仅成本维度实际调用）。

三个分析维度：
  ① 网格扫描   —— sweep：逐点跑回测，产出「参数组合 → 指标」的结果表
  ② 稳健性评分 —— robustness_score：多少比例的组合指标为正（越高越稳）
  ③ 悬崖检测   —— detect_cliffs：参数小幅变动导致指标骤降的位置（过拟合信号）
"""
import itertools

import pandas as pd
import yaml


def parse_grid_spec(spec: str) -> tuple[str, list]:
    """--grid 参数解析：标量逗号分隔，或以 [ ... ] 表示的列表参数。

    例：
      "risk.vol_target_portfolio=0.2,0.3,0.4"     → ("risk.vol_target_portfolio", [0.2, 0.3, 0.4])
      "trend.windows=[21,30],[60,90]"              → ("trend.windows", [[21,30],[60,90]])
    """
    key, raw = spec.split("=", 1)
    raw = raw.strip()
    if raw.startswith("["):
        # 列表型参数：整个方括号内容按 yaml 解析，元素本身可以是列表
        return key, yaml.safe_load(raw)
    return key, [yaml.safe_load(x) for x in raw.split(",")]


def sweep(run_fn, grid: dict) -> pd.DataFrame:
    """对参数网格逐点跑 run_fn，返回含 Sharpe/回撤/年化/Calmar 的结果表。

    笛卡尔积遍历：itertools.product(*grid.values()) 逐组参数调用 run_fn(**params)，
    把参数与四个核心指标一起存成一行。
    """
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
    """稳健性分数 = 网格中 metric > 0 的组合占比（ml4t-sensitivity-analysis）。

    公式：robustness = #{i : metric_i > 0} / N
    读法：0.9 表示 90% 的参数组合夏普为正，说明策略不依赖特定参数取值。
    """
    return float((results[metric] > 0).mean())


def detect_cliffs(results: pd.DataFrame, params: list[str], metric: str = "sharpe") -> dict:
    """悬崖检测：相邻参数间 metric 变化 > 2×变化量标准差则标记（ml4t-sensitivity-analysis）。

    公式（对每个参数 p 单独沿该维度排序后计算）：
      Δmetric_i = |metric_i − metric_{i−1}|     （相邻取值的变化幅度）
      判据：max|Δmetric| > 2·std(Δmetric) → 标记为 cliff
    含义：若相邻参数的变化幅度远超一般变化幅度，说明此处存在「悬崖」——
    参数再动一点点绩效就崩掉，是典型的过拟合迹象。
    """
    out = {}
    for p in params:
        s = results.sort_values(p)[metric]
        d = s.diff().abs()
        out[p] = {
            "cliff": bool(d.std() > 0 and d.max() > 2 * d.std()),
            "max_jump": float(d.max()),
        }
    return out


def pivot_heatmap(results: pd.DataFrame, x: str, y: str,
                  metric: str = "sharpe") -> pd.DataFrame:
    """把两个参数维度的网格结果透视成 (x × y) 的 metric 矩阵，用于孤岛/高原检测。"""
    return results.pivot_table(index=y, columns=x, values=metric, aggfunc="mean")
