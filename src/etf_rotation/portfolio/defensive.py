"""防守仓：债券+货币 ETF（剔除可转债），低波动 + 风险调整动量前 5 等权。

防守仓的定位：风险腿因市场状态/趋势约束而空出资金时，用低波动资产承接，
既减少闲置现金（现金只计息、不产生主动收益），又避免在熊市里被动全空。

选样思路：先按「低波动」筛掉风险资产，再用「风险调整动量」在剩下的债券/货币
ETF 里排序——货币基金动量恒为 0，只有债券 ETF 能在防守的同时贡献少量收益。
"""


def select(returns, vol60, category, top_n: int = 5,
           max_vol_60d: float = 0.03, momentum_window: int = 60) -> list:
    """从防守候选中按 60 日风险调整动量排序取前 5，同一大类最多 1 只。

    三步：
      ① 低波动过滤：vol60 < max_vol_60d（年化波动 < 3%）
      ② 类别过滤：只保留 category ∈ {bond, money}，可转债因含权波动大被排除
      ③ 排序取样：
         RAR_i = mean(r_i, 60日) / std(r_i, 60日)
         —— 风险调整动量：单位波动换来的平均收益（近似夏普比率）
         按 RAR 降序取前 top_n 只；同一大类（bond / money）最多取 1 只，
         避免防守仓全部押在同一类资产上。
    """
    cand = vol60[vol60 < max_vol_60d].index
    cand = [c for c in cand if category.get(c, "risk") in ("bond", "money")]
    # RAR_i = mean(r_i, 60日) / std(r_i, 60日)：风险调整动量（近似夏普）
    rar = returns[cand].iloc[-momentum_window:].mean() / returns[cand].iloc[-momentum_window:].std()
    rar = rar.sort_values(ascending=False)
    picked, seen = [], set()
    for c in rar.index:
        # 同一大类最多 1 只
        if category.get(c) not in seen:
            picked.append(c)
            seen.add(category.get(c))
        if len(picked) >= top_n:
            break
    return picked
