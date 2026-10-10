from etf_rotation import config


def test_load_params_defaults():
    p = config.load_params()
    assert p["trend"]["windows"] == [21, 60]
    assert p["dedupe"]["corr_threshold"] == 0.80
    assert p["costs"]["one_side_bps"] == 8


def test_load_token_from_env(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "abc")
    assert config.load_token() == "abc"
