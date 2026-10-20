"""多资产底仓：风险资产 50% / 纳指 37.5% / 黄金 12.5%。"""


def base_weights(market: str, nasdaq_signal: float, gold_signal: float,
                 nasdaq_exit_threshold: float = 0.0, gold_exit_threshold: float = 0.0) -> dict:
    """基础权重；市场状态缩放（震荡 95%、危险 0）由 risk_layers 统一应用，
    避免在两层重复扣减（曾出现 0.95×0.95 的 bug，见代码审阅手册 §8.2）。
    纳指/黄金各自动量低于退出阈值（H7，默认 0）即退。"""
    w = {"risk": 0.50, "nasdaq": 0.375, "gold": 0.125}
    if market == "bull":
        w["risk"] = 0.50
    elif market == "range":
        w["risk"] = 0.50  # 震荡 95% 由 risk_layers.risk_scale 统一应用一次
    else:
        w["risk"] = 0.0
    if nasdaq_signal < nasdaq_exit_threshold:
        w["nasdaq"] = 0.0
    if gold_signal < gold_exit_threshold:
        w["gold"] = 0.0
    return w

