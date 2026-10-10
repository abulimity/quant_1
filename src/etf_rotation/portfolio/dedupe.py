def dedupe(candidates, corr, threshold, max_n):
    keep = []
    for c in candidates:
        if all(abs(corr.loc[c, k]) < threshold for k in keep):
            keep.append(c)
        if len(keep) >= max_n:
            break
    return keep

