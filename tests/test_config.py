from etf_rotation import config


def test_load_params_defaults():
    p = config.load_params()
    assert p["trend"]["windows"] == [21, 60]
    assert p["dedupe"]["corr_threshold"] == 0.80
    assert p["costs"]["one_side_bps"] == 8


def test_load_token_from_env(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "abc")
    assert config.load_token() == "abc"


def test_set_nested_and_flatten():
    p = config.load_params()
    config.set_nested(p, "dedupe.corr_threshold", "0.85")
    assert p["dedupe"]["corr_threshold"] == 0.85
    config.set_nested(p, "trend.windows", "[21, 63]")
    assert p["trend"]["windows"] == [21, 63]
    flat = config.flatten_params(p)
    assert flat["dedupe.corr_threshold"] == 0.85
    assert flat["trend.windows"] == [21, 63]
