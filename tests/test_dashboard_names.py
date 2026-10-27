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


def test_null_or_non_string_name_does_not_become_literal_nan():
    """缺名或非字符串名称必须变成空串，不能返回 "nan" 之类的字符串。

    只断言 "nan" not in out 太弱：None / NaN / N/A / nat 都能溜过去。
    改为精确断言返回值，再补一条覆盖所有常见「字符串化的空值」。
    """
    raw = pd.Series({"A.SH": None, "B.SZ": float("nan"), "C.SH": "正常名称", "D.SH": 12345})
    out = abbreviate(raw)
    assert out["A.SH"] == "", f"None 应变成空串，实际 {out['A.SH']!r}"
    assert out["B.SZ"] == "", f"NaN 应变成空串，实际 {out['B.SZ']!r}"
    assert out["D.SH"] == "", f"非字符串应变成空串，实际 {out['D.SH']!r}"
    assert out["C.SH"] == "正常名称"
    # 任何「字符串化的空值」都不允许出现，大小写与常见写法都覆盖
    bad = {"nan", "none", "nat", "null", "n/a", "na", "<na>"}
    leaked = [v for v in out if str(v).strip().lower() in bad]
    assert not leaked, f"出现了字符串化的空值：{leaked}"


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


# ---------------------------------------------------------------- names 载荷


def test_names_cover_every_code_in_payload(builder):
    payload = builder.build(only=["names", "signals", "tickers"])
    names = payload["names"]
    codes = set(payload["signals"]) | {r["t"] for r in payload["tickers"]}
    assert codes, "payload 里没有证券代码，测试前提不成立"
    assert codes <= set(names), f"缺简称：{sorted(codes - set(names))[:5]}"
    assert set(names) == codes, f"names 键多于 payload 引用：{sorted(set(names) - codes)[:5]}"
    assert all(isinstance(v, str) and v for v in names.values())


def test_names_is_last_key_in_build_order():
    from etf_rotation.report.dashboard import BUILDER_METHODS, BUILD_ORDER

    assert len(BUILD_ORDER) == 49
    assert len(set(BUILD_ORDER)) == 49
    assert BUILD_ORDER[-1] == "names"
    assert BUILDER_METHODS["names"] == "names"
