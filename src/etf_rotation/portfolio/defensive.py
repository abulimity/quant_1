"""防守仓：债券+货币 ETF（剔除可转债），低波动 + 风险调整动量前 5 等权。"""


def select(returns, vol60, category, top_n: int = 5,
           max_vol_60d: float = 0.03, momentum_window: int = 60) -> list:
    """从防守候选中按 60 日风险调整动量排序取前 5，同一大类最多 1 只。"""
    cand = vol60[vol60 < max_vol_60d].index
    cand = [c for c in cand if category.get(c, "risk") in ("bond", "money")]
    rar = returns[cand].iloc[-momentum_window:].mean() / returns[cand].iloc[-momentum_window:].std()
    rar = rar.sort_values(ascending=False)
    picked, seen = [], set()
    for c in rar.index:
        if category.get(c) not in seen:
            picked.append(c)
            seen.add(category.get(c))
        if len(picked) >= top_n:
            break
    return picked

