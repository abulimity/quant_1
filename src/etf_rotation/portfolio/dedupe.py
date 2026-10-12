"""相关性去重：按历史收益相关性贪心剔除高度同质标的。"""


def dedupe(candidates, corr, threshold, max_n):
    """按给定顺序贪心保留：与已保留标的相关性均 < threshold 才入选，至多 max_n 只。"""
    keep = []
    for c in candidates:
        if all(abs(corr.loc[c, k]) < threshold for k in keep):
            keep.append(c)
        if len(keep) >= max_n:
            break
    return keep

