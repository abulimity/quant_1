import numpy as np
import pandas as pd


def combine(targets, schedule):
    idx = targets[0].index
    cols = targets[0].columns
    out = pd.DataFrame(0.0, index=idx, columns=cols)
    n = len(targets)
    for t, sched in zip(targets, schedule):
        active = (idx.day % 5 == sched)
        held = t.where(np.asarray(active).reshape(-1, 1), np.nan).ffill().bfill()
        out += held / n
    return out

