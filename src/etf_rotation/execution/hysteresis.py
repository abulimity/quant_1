"""整组迟滞：新组合得分改善不足时不换仓，降低排名临界位波动造成的无效交易。"""


def apply(old, new, score_old, score_new, min_improve):
    """新组合得分需较旧组合改善 ≥ min_improve 才采纳，否则维持原持仓。"""
    if score_new <= score_old * (1 + min_improve):
        return old
    return new

