import pandas as pd

from etf_rotation.portfolio import dedupe


def test_dedupe_removes_high_corr():
    corr = pd.DataFrame({"A": [1, .9, .3], "B": [.9, 1, .2], "C": [.3, .2, 1]},
                        index=["A", "B", "C"])
    out = dedupe.dedupe(["A", "B", "C"], corr, 0.8, 10)
    assert "A" in out and "C" in out and len(out) == 2

