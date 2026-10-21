"""多资产底仓：风险资产 50% / 纳指 37.5% / 黄金 12.5%。

三层资产的角色分工：
  risk    — A 股风险 ETF 池（动量选股），承担主要收益弹性
  nasdaq  — 纳指 ETF，对冲 A 股系统性风险，兼作「海外科技成长」敞口
  gold   — 黄金 ETF，避险与抗通胀，在 A 股与纳指同时下跌时提供缓冲

三腿合计 100%，任何时刻至少有一腿在场（由各自的退出条件决定）。
"""


def base_weights(market: str, nasdaq_signal: float, gold_signal: float,
                 nasdaq_exit_threshold: float = 0.0, gold_exit_threshold: float = 0.0) -> dict:
    """基础权重；市场状态缩放（震荡 95%、危险 0）由 risk_layers 统一应用，
    避免在两层重复扣减（曾出现 0.95×0.95 的 bug，见代码审阅手册 §8.2）。
    纳指/黄金各自动量低于退出阈值（H7，默认 0）即退。

    公式（底仓三腿）：
      底仓 risk/nasdaq/gold = 0.50 / 0.375 / 0.125
      w["risk"]    = 0.50（bull 或 range）或 0.0（bear）
      w["nasdaq"]  = 0.375，条件：nasdaq_signal ≥ nasdaq_exit_threshold，否则 0
      w["gold"]    = 0.125，条件：gold_signal ≥ gold_exit_threshold，否则 0

    注意：震荡市 0.95 的缩放不在这里做，而由 risk_layers.risk_scale 统一应用一次；
    若两层都扣，会出现 0.95 × 0.95 = 0.9025 的重复扣减。
    """
    w = {"risk": 0.50, "nasdaq": 0.375, "gold": 0.125}
    if market == "bull":
        w["risk"] = 0.50
    elif market == "range":
        w["risk"] = 0.50  # 震荡 95% 由 risk_layers.risk_scale 统一应用一次
    else:
        w["risk"] = 0.0
    # 纳指/黄金动量跌破退出阈值 → 该腿清零，资金回落到风险腿之外（成现金）
    if nasdaq_signal < nasdaq_exit_threshold:
        w["nasdaq"] = 0.0
    if gold_signal < gold_exit_threshold:
        w["gold"] = 0.0
    return w
