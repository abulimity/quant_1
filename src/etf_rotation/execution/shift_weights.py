"""权重时序对齐：T 日信号 → T+1 生效（shift(1) + fillna(0)）。"""
from __future__ import annotations

import pandas as pd


def shift_weights(weights: pd.DataFrame) -> pd.DataFrame:
    """目标权重面板整体前移一期（T 日信号、T+1 成交），缺失日补 0。"""
    return weights.shift(1).fillna(0.0)
