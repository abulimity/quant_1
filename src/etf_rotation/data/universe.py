"""标的池：ETF 分类（风险/债券/货币/可转债）+ point-in-time 可投资过滤。

分类口径（关键词 + tushare 大类，判定顺序固定）：
    转债关键词 → 货币 → 债券 → risk（其余一律归入风险池）
「先判转债」是必要的：可转债名称里往往同时含「债」字，若先判债券就会被
误归为纯债，而可转债含权、波动大，会污染防守池的低波动筛选。
"""
from __future__ import annotations

import re

import pandas as pd

# 可转债关键词（含「转债」的基金，波动大且含权，不入防守池）
CONVERTIBLE_KW = ["转债"]
# 货币基金类关键词（低波动，典型防守资产）
MONEY_KW = ["货币", "现金", "理财", "保证金"]
# 债券基金类关键词（防守池主力）
BOND_KW = ["债", "国债", "国开", "政金", "短融", "存单", "信用"]


def classify(fund_basic: pd.DataFrame) -> pd.Series:
    """按名称关键词 + fund_type 大类划分 risk/bond/money/convertible。

    实测 tushare fund_basic：fund_type 为资产大类（股票型/债券型/货币型/REITs/其他），
    invest_type 为更细策略标签，故优先用 fund_type。该口径是对研报分类的近似（H8）。

    判定顺序：转债关键词 → 货币 → 债券 → risk
      ① 名称含「转债」→ convertible（先判，避免被下面的「债」字命中）
      ② fund_type ∈ {货币型, 货币市场型} 或名称含货币类关键词 → money
      ③ fund_type == 债券型 或名称含债券类关键词 → bond
      ④ 其余 → risk（股票型/REITs/其他都视为风险资产）

    返回以 ts_code 为索引的 category 序列。
    """
    type_col = "fund_type" if "fund_type" in fund_basic.columns else "invest_type"

    def _one(row):
        """单只 ETF 的分类判定：转债关键词 → 货币 → 债券 → risk。"""
        name = str(row["name"])
        ft = str(row.get(type_col, ""))
        if any(k in name for k in CONVERTIBLE_KW):
            return "convertible"
        if ft in ("货币型", "货币市场型") or any(k in name for k in MONEY_KW):
            return "money"
        if ft == "债券型" or any(k in name for k in BOND_KW):
            return "bond"
        return "risk"

    out = fund_basic.apply(_one, axis=1)
    out.index = fund_basic["ts_code"]
    return out.rename("category")


# 名称里可丢弃的份额/渠道后缀。顺序有意义：(QDII-LOF-FOF) 必须先于 (QDII)。
_ABBR_SUFFIXES = ("(QDII-LOF-FOF)", "(QDII-LOF)", "(QDII)", "(LOF)")


def abbreviate(names: pd.Series) -> pd.Series:
    """把 fund_basic 的正式名称裁成简称。

    只剥后缀与结尾的 `-CNY`，不截断、不改主体。剥完为空则退回原名。
    非字符串（None/NaN 等）一律返回空串，绝不返回 `str(raw)`：`str(nan)` 是
    非空的 "nan"，会绕过空值兜底，让看板原样显示 nan 且不报错。
    实测 971 个标的按此规则无重名，截断到 12 字则会撞出 14 组，故不做截断。
    """
    def _one(raw) -> str:
        if not isinstance(raw, str):
            return ""
        text = raw
        for suffix in _ABBR_SUFFIXES:
            text = text.replace(suffix, "")
        text = re.sub(r"-CNY$", "", text)
        return text.strip() or raw

    return names.map(_one).rename("abbr")
