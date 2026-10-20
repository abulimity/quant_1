"""数据质量复核：幸存者偏差 / point-in-time / 源口径（有界 proxy，见设计 D7）。"""
from __future__ import annotations

import json
from pathlib import Path

from etf_rotation.data import universe as univ
from etf_rotation.pipeline import load_fund_basic

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
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
