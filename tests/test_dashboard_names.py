"""证券简称裁剪规则与 names 载荷契约。

口径：
- 剥掉 `(QDII-LOF-FOF)` / `(QDII-LOF)` / `(QDII)` / `(LOF)` 后缀，以及结尾的 `-CNY`；
- 剥完为空就退回原名，不能返回空串；
- 只做后缀剥离，不截断；
- 看板用到的 971 个标的的简称必须互不重复（全量 fund_basic 允许重名）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etf_rotation.data.universe import abbreviate

ROOT = Path(__file__).resolve().parents[1]


def test_strips_qdii_lof_suffixes():
    raw = pd.Series(
        {
            "513100.SH": "国泰纳斯达克100ETF(QDII)",
            "501225.SH": "景顺长城全球半导体芯片产业股票(QDII-LOF)-A-CNY",
            "162703.SZ": "广发小盘成长混合(LOF)-A",
            "161129.SZ": "易方达原油(QDII-LOF-FOF)-A-CNY",
            "518880.SH": "华安易富黄金ETF",
        }
    )
    out = abbreviate(raw)
    assert out["513100.SH"] == "国泰纳斯达克100ETF"
    assert out["501225.SH"] == "景顺长城全球半导体芯片产业股票-A"
    assert out["162703.SZ"] == "广发小盘成长混合-A"
    assert out["161129.SZ"] == "易方达原油-A"
    assert out["518880.SH"] == "华安易富黄金ETF"


def test_never_returns_empty_and_keeps_index():
    raw = pd.Series({"A.SH": "(QDII)", "B.SZ": "(LOF)-CNY", "C.SH": "正常名称"})
    out = abbreviate(raw)
    assert list(out.index) == ["A.SH", "B.SZ", "C.SH"]
    assert (out.str.len() > 0).all()
    assert out["A.SH"] == "(QDII)"
    assert out["B.SZ"] == "(LOF)-CNY"
    assert out["C.SH"] == "正常名称"


def test_abbreviations_unique_within_dashboard_universe():
    """简称只需在看板用到的代码里唯一，全量 fund_basic 允许重名。

    实测全量 2971 个代码里有 34 个落在 17 组重名（如 159073.SZ 与 159319.SZ
    都叫「汇添富国证粮食产业ETF」）。看板载荷只含 971 个代码，其中 0 组重名。
    """
    path = ROOT / "data" / "bronze" / "tushare" / "etf_rotation" / "fund_basic.parquet"
    payload = ROOT / "reports" / "dashboard.html"
    if not path.exists():
        pytest.skip(f"缺 fund_basic：{path}")
    if not payload.exists():
        pytest.skip(f"缺看板产物：{payload}")

    import json

    fb = pd.read_parquet(path)[["ts_code", "name"]]
    names = fb.set_index("ts_code")["name"]
    html = payload.read_text(encoding="utf-8")
    start = html.find("window.__REPORT_DATA__ = ") + len("window.__REPORT_DATA__ = ")
    data = json.loads(html[start:html.find("</script>", start)].rstrip().rstrip(";"))
    codes = sorted(data["signals"])
    assert codes, "载荷里没有证券代码，测试前提不成立"

    abbr = abbreviate(names.reindex(codes))
    assert abbr.notna().all(), f"有代码查不到名称：{abbr[abbr.isna()].index[:5].tolist()}"
    dup = abbr[abbr.duplicated(keep=False)]
    assert dup.empty, f"看板内简称重复：{sorted(dup.items())[:5]}"
