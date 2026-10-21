"""相关性去重：按历史收益相关性贪心剔除高度同质标的。

为什么需要：风险池里常见「同一主题的多个 ETF」（如多只宽基、多个行业龙头），
它们的收益相关性极高，同时持有不会分散风险，只会重复暴露。HRP 配权对高相关
标的会给出接近的权重，等于隐性加杠杆，所以必须在配权前先去重。
"""


def dedupe(candidates, corr, threshold, max_n):
    """按给定顺序贪心保留：与已保留标的相关性均 < threshold 才入选，至多 max_n 只。

    判据：|corr(c, k)| < threshold（对所有已保留的 k ∈ keep）
      —— 取绝对值是因为相关性为负也代表同向暴露（负相关 = 涨跌同步），
         用绝对值可同时拦住「同涨同跌」的两类同质标的。

    贪心顺序即入参顺序（candidates 由横截面排名从高到低给出），
    因此「先到先得」等价于「优先保留排名更高的标的」。
    """
    keep = []
    for c in candidates:
        # 与所有已保留标的的相关性绝对值都低于阈值才入选
        if all(abs(corr.loc[c, k]) < threshold for k in keep):
            keep.append(c)
        if len(keep) >= max_n:   # 持仓数量上限
            break
    return keep
