def select(returns, vol60, category) -> list:
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

