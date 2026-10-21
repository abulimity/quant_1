"""数据质量复核：幸存者偏差 / point-in-time / 源口径（有界 proxy，见设计 D7）。"""
from __future__ import annotations

import json
from pathlib import Path

from etf_rotation.data import universe as univ
from etf_rotation.pipeline import load_fund_basic

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """数据质量复核：分类计数 + 幸存者偏差说明，落盘 reports/data_quality.json。

    输出三部分：
      ① classification_counts —— 四类标的（risk/bond/money/convertible）的数量分布
      ② n_etfs / n_delisted  —— 标的总数与已退市数量（退市标的是幸存者偏差的直接来源）
      ③ survivorship / source_gap —— 两条**声明**：说明 point-in-time 过滤如何降低
         幸存者偏差，以及 tushare vs Wind 口径差异无法精确量化的边界

    纪律：本脚本给的是「有界 proxy + 明确声明不可精确归因」（设计 D7），
    不把 proxy 包装成精确结论。
    """
    fb = load_fund_basic()
    cat = univ.classify(fb)
    counts = {c: int((cat == c).sum()) for c in ("risk", "bond", "money", "convertible", "exclude")}
    delisted = fb[fb["delist_date"].notna()] if "delist_date" in fb.columns else None
    out = {
        "classification_counts": counts,
        "n_etfs": int(len(cat)),
        "n_delisted": int(len(delisted)) if delisted is not None else 0,
        "survivorship": "point-in-time 过滤（listed_days>=126 + avg_amount20>=500万）保证退市后不入池；无 Wind 无法精确量化幸存者偏差",
        "source_gap": "tushare vs Wind 复权/指数口径差异无 Wind 无法精确量化（设计 D7：有界 proxy + 声明不可精确归因）",
    }
    (ROOT / "reports" / "data_quality.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
