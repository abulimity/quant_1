import pandas as pd

from etf_rotation.data import universe


def test_classify():
    fb = pd.DataFrame(
        {
            "ts_code": ["511880.SH", "511010.SH", "511380.SH", "518880.SH"],
            "name": ["银华日利", "国债ETF", "可转债ETF", "黄金ETF"],
            "fund_type": ["货币型", "债券型", "债券型", "其他"],
        }
    )
    c = universe.classify(fb)
    assert c["511880.SH"] == "money"
    assert c["511380.SH"] == "convertible"
    assert c["518880.SH"] == "risk"

