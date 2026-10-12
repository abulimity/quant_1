"""五相位调仓：5 个相位每隔 5 个交易日错开更新，最终持仓等权汇总。"""
import numpy as np
import pandas as pd


def combine(targets, schedule):
    """将 5 个相位的目标权重按各自调仓日合并：非调仓日前向填充持有值。"""
    idx = targets[0].index
    cols = targets[0].columns
    out = pd.DataFrame(0.0, index=idx, columns=cols)
    n = len(targets)
    for t, sched in zip(targets, schedule):
        active = (idx.day % 5 == sched)
        held = t.where(np.asarray(active).reshape(-1, 1), np.nan).ffill().bfill()
        out += held / n
    return out

