"""回测指标：唯一来源是 bt/ffn 内置统计，不做自行推导。

纪律：所有报告里的绩效数字都直接取 ffn 的统计量，不在这里二次实现
（年化/Sharpe/Sortino/Calmar 的口径差异很容易造成「报告与代码对不上」）。
本模块只做「键名映射」，把 ffn 的列名翻译成报告口径。
"""
from __future__ import annotations

import numbers

import pandas as pd

# ffn 统计列名 → 报告口径（只做键名翻译，绝不二次推导数值）
_KEY_MAP = {
    "cagr": "ann_return",
    "daily_vol": "ann_vol",
    "daily_sharpe": "sharpe",
    "daily_sortino": "sortino",
    "max_drawdown": "max_drawdown",
    "calmar": "calmar",
}


def from_stats(stats: pd.Series) -> dict:
    """bt Result.stats[name] → 报告口径（直接取 ffn 值，已是年化口径）。

    映射关系（全部是 ffn 的现成列，无自行推导）：
      ann_return   ← cagr          —— 年化复合收益率
      ann_vol      ← daily_vol     —— 日波动（ffn 口径已年化）
      sharpe       ← daily_sharpe  —— 日频夏普（ffn 口径已年化）
      sortino      ← daily_sortino —— 日频索提诺（ffn 口径已年化）
      max_drawdown ← max_drawdown  —— 最大回撤（负值）
      calmar       ← calmar        —— 年化收益 / |最大回撤|

    注意：本函数不含 VaR / CVaR —— 研报报告里的这两个指标在本项目未复现，
    对标时只比较「同量级」的核心指标（见 reports/回测报告.md）。
    """
    return {
        "ann_return": float(stats["cagr"]),
        "ann_vol": float(stats["daily_vol"]),
        "sharpe": float(stats["daily_sharpe"]),
        "sortino": float(stats["daily_sortino"]),
        "max_drawdown": float(stats["max_drawdown"]),
        "calmar": float(stats["calmar"]),
    }


def all_stats(stats: pd.Series) -> dict:
    """把 ffn 的全部数值统计原样转成 dict，只做键名映射（供 run 登记持久化）。

    与 `from_stats` 的区别：这里保留 `monthly_sharpe`、`ytd` 等扩展列，派生层
    才能取到完整指标；文本/布尔字段（例如 `some_text`）不进指标表——指标表的
    值必须是数值（registry 写入时强校验）。

    公式：全部数值直接来自 ffn/引擎，不做任何重算或补全。
    """
    out: dict[str, float] = {}
    for key, value in stats.items():
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            continue
        if pd.isna(value):
            # NaN 如实保留（例如样本太短导致 sortino 无定义），由序列化层转 null
            continue
        out[_KEY_MAP.get(str(key), str(key))] = float(value)
    return out


def build_equity_frame(nav: pd.Series, returns: pd.Series, cash: pd.Series,
                       turnover: pd.Series, fees: pd.Series) -> pd.DataFrame:
    """拼回测净值表：列固定 `nav/returns/cash/turnover/fees`（顺序即契约）。

    五列全部与 bt 引擎同源：nav 为归一化净值、returns 为日收益、cash 为现金余额、
    turnover 为日换手、fees 为当日费用。派生层（水下曲线/成本/换手）只依赖
    equity 而不回读引擎，因此列集合必须稳定 —— 缺列即 schema 不兼容。
    """
    return pd.DataFrame({
        "nav": nav,
        "returns": returns,
        "cash": cash,
        "turnover": turnover,
        "fees": fees,
    })
