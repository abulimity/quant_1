import pytest

from etf_rotation import config
from etf_rotation.config_schema import ConfigError, validate_params


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


def test_validate_params_rejects_out_of_range():
    p = config.load_params()
    p["market_state"]["bull_threshold"] = 2.0
    with pytest.raises(ConfigError):
        validate_params(p)


def test_validate_params_rejects_negative_holdings():
    p = config.load_params()
    p["dedupe"]["max_holdings"] = -1
    with pytest.raises(ConfigError):
        validate_params(p)


def test_validate_params_rejects_unknown_key():
    p = config.load_params()
    p["nope"] = {"x": 1}
    with pytest.raises(ConfigError):
        validate_params(p)


def test_load_params_validates_defaults():
    p = config.load_params()
    assert p["dedupe"]["corr_threshold"] == 0.80
    assert p["market_state"]["bull_threshold"] == 0.35
