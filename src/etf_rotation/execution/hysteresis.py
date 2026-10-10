def apply(old, new, score_old, score_new, min_improve):
    if score_new <= score_old * (1 + min_improve):
        return old
    return new

