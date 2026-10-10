def base_weights(market: str, nasdaq_signal: float, gold_signal: float) -> dict:
    w = {"risk": 0.50, "nasdaq": 0.375, "gold": 0.125}
    if market == "bull":
        w["risk"] = 0.50
    elif market == "range":
        w["risk"] = 0.50 * 0.95
    else:
        w["risk"] = 0.0
    if nasdaq_signal < 0:
        w["nasdaq"] = 0.0
    if gold_signal < 0:
        w["gold"] = 0.0
    return w

