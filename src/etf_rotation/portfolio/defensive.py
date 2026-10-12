"""防守仓：债券+货币 ETF（剔除可转债），低波动 + 风险调整动量前 5 等权。"""


def select(returns, vol60, category) -> list:
    """从防守候选中按 60 日风险调整动量排序取前 5，同一大类最多 1 只。"""
    cand = vol60[vol60 < 0.03].index
    cand = [c for c in cand if category.get(c, "risk") in ("bond", "money")]
    rar = returns[cand].iloc[-60:].mean() / returns[cand].iloc[-60:].std()
    rar = rar.sort_values(ascending=False)
    picked, seen = [], set()
    for c in rar.index:
        if category.get(c) not in seen:
            picked.append(c)
            seen.add(category.get(c))
        if len(picked) >= 5:
            break
    return picked

