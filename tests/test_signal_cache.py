"""信号缓存测试：内容寻址落盘/读取、原子写入、manifest 校验、命中路径。

覆盖的契约（C1 stage / 主计划 Task 17）：
1. `save`/`load` 往返逐值相等（float32 输入不得被提升/截断成别的值）；
2. 目录不存在时 `load` 返回 None；
3. manifest 记录 fields/dtypes/tickers/date_min/date_max/bytes/created_at/
   code_hash/data_snapshot_id；
4. 写入原子：先写 `.tmp-*` 再 rename，成功后不留暂存目录；
5. 已存在且 manifest 一致 → 复用（不重写文件、不改 mtime）；
6. 同一 sid 下内容不一致 → 只告警、保留原目录（共享缓存不删不覆盖）；
7. manifest 与实际内容不一致（被手工改过）→ `load` 抛 RuntimeError；
8. manifest 记录的价格面板指纹与当前面板不一致 → `load` 按未命中返回 None；
9. `_precompute_signals` 命中缓存时跳过动量/LLT 计算，并补齐
   close/ret/n_days/avg20 四个派生字段。
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from etf_rotation.signals import cache


def _idx(n: int = 2) -> pd.DatetimeIndex:
    # 与真实数据一致：索引不带 freq（parquet 不保存 freq，带 freq 会让比较失真）
    return pd.DatetimeIndex(pd.bdate_range("2024-01-02", periods=n).values)


def _panel(data, dtype="float64") -> pd.DataFrame:
    return pd.DataFrame(data, index=_idx()).astype(dtype)


def test_roundtrip_is_exact(tmp_path):
    panel = _panel({"A": [0.1, 0.2]}, dtype="float32")
    scalars = pd.DataFrame({"comp": [0.3, 0.4]}, index=_idx(), dtype="float32")
    cache.save({"m21": panel}, scalars, "s1", tmp_path, {"fields": ["m21"]})
    got = cache.load("s1", tmp_path)
    pd.testing.assert_frame_equal(got["m21"], panel)
    pd.testing.assert_frame_equal(got["scalars"], scalars)


def test_load_returns_none_when_missing(tmp_path):
    assert cache.load("nope", tmp_path) is None


def test_manifest_records_contract_fields(tmp_path):
    panel = _panel({"A": [0.1, 0.3], "B": [0.2, 0.4]})
    scalars = pd.DataFrame(
        {"comp": [0.5, 0.6], "regime": ["bull", "range"]}, index=_idx())
    cache.save({"m21": panel}, scalars, "s2", tmp_path,
               {"code_hash": "abc123", "data_snapshot_id": "d1"})

    manifest = json.loads((tmp_path / "s2" / "manifest.json").read_text(encoding="utf-8"))
    for key in ("fields", "dtypes", "tickers", "date_min", "date_max", "bytes",
                "created_at", "code_hash", "data_snapshot_id"):
        assert key in manifest
    assert manifest["tickers"] == ["A", "B"]
    assert manifest["date_min"] == "2024-01-02"
    assert manifest["date_max"] == "2024-01-03"
    assert manifest["code_hash"] == "abc123"
    assert manifest["data_snapshot_id"] == "d1"
    assert manifest["dtypes"]["m21"] == "float64"
    assert manifest["dtypes"]["comp"] == "float64"
    assert manifest["bytes"] > 0
    assert set(manifest["fields"]) == {"m21", "comp", "regime"}


def test_save_is_atomic_and_leaves_no_tmp(tmp_path):
    cache.save({"m21": _panel({"A": [0.1, 0.2]})}, pd.DataFrame(index=_idx()),
               "s3", tmp_path, {})
    entries = sorted(p.name for p in tmp_path.iterdir())
    assert entries == ["s3"]


def test_save_reuses_existing_manifest_match(tmp_path):
    panel = _panel({"A": [0.1, 0.2]})
    scalars = pd.DataFrame({"comp": [0.3, 0.4]}, index=_idx())
    cache.save({"m21": panel}, scalars, "s4", tmp_path, {"code_hash": "h1"})
    stamps = {p.name: p.stat().st_mtime_ns for p in (tmp_path / "s4").iterdir()}

    cache.save({"m21": panel}, scalars, "s4", tmp_path, {"code_hash": "h1"})

    after = {p.name: p.stat().st_mtime_ns for p in (tmp_path / "s4").iterdir()}
    assert after == stamps                      # 复用：一个字节都没重写
    assert sorted(p.name for p in tmp_path.iterdir()) == ["s4"]


def test_save_keeps_existing_on_conflict(tmp_path):
    """同一 sid 内容不一致：保留原目录（共享缓存不删不覆盖），本次不落盘。"""
    cache.save({"m21": _panel({"A": [0.1, 0.2]})}, pd.DataFrame(index=_idx()),
               "s5", tmp_path, {})
    other = _panel({"A": [0.1, 0.2], "Z": [0.3, 0.4]})
    with pytest.warns(RuntimeWarning):
        cache.save({"m21": other}, pd.DataFrame(index=_idx()), "s5", tmp_path, {})
    kept = cache.load("s5", tmp_path)
    assert list(kept["m21"].columns) == ["A"]        # 原内容没被覆盖
    assert sorted(p.name for p in tmp_path.iterdir()) == ["s5"]


def test_load_treats_price_hash_mismatch_as_miss(tmp_path):
    """价格面板指纹不一致（撞 sid 的合成数据）→ 按未命中处理，不抛错。"""
    cache.save({"m21": _panel({"A": [0.1, 0.2]})}, pd.DataFrame(index=_idx()),
               "s8", tmp_path, {"price_hash": "other"})
    assert cache.load("s8", tmp_path, price_hash="mine") is None
    assert cache.load("s8", tmp_path, price_hash="other") is not None


def test_load_rejects_tampered_manifest(tmp_path):
    cache.save({"m21": _panel({"A": [0.1, 0.2]})}, pd.DataFrame(index=_idx()),
               "s6", tmp_path, {})
    path = tmp_path / "s6" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["tickers"] = ["A", "B"]        # 手工改过：与 parquet 实际列不一致
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError):
        cache.load("s6", tmp_path)


def test_roundtrip_keeps_bool_and_regime_columns(tmp_path):
    panel = _panel({"A": [True, False]}, dtype="bool")     # rev_active 是 bool 面板
    scalars = pd.DataFrame(
        {"comp": [0.5, np.nan], "cyb_below": [True, False],
         "regime": ["bull", np.nan]}, index=_idx())
    cache.save({"rev_active": panel}, scalars, "s7", tmp_path, {})
    got = cache.load("s7", tmp_path)
    pd.testing.assert_frame_equal(got["rev_active"], panel)
    assert got["scalars"]["cyb_below"].tolist() == [True, False]
    assert got["scalars"]["regime"].tolist()[0] == "bull"
    # 缺失值统一成 NaN（parquet 读回的 None 不归一会被下游当成有效字符串）
    assert pd.isna(got["scalars"]["regime"].iloc[1])
    assert pd.isna(got["scalars"]["comp"].iloc[1])


def test_cache_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ETF_SIGNAL_CACHE_DIR", str(tmp_path))
    assert cache.cache_root() == tmp_path


def test_signal_keys_single_source():
    """键清单只有一个来源：进程内 _SIGNAL_CACHE 与磁盘 signal_id 用同一份键。"""
    from etf_rotation import config, pipeline

    assert pipeline._SIGNAL_KEYS is cache.SIGNAL_KEYS
    assert tuple(cache.signal_cache_key(config.load_params())) == cache.SIGNAL_KEYS
    # pipeline 侧返回的是「按同一份键取到的值序列」，长度必须与键数一致
    assert len(pipeline.signal_cache_key(config.load_params())) == len(cache.SIGNAL_KEYS)
    assert len(cache.SIGNAL_KEYS) == 16


def test_precompute_hit_skips_heavy_panels(monkeypatch, tmp_path):
    """命中缓存：不跑 momentum_panel/llt，仍返回完整 dict。"""
    from etf_rotation import pipeline

    idx = _idx(6)
    tickers = ["A", "B"]
    close = pd.DataFrame(1.0, index=idx, columns=tickers)
    amt = pd.DataFrame(1e8, index=idx, columns=tickers)

    def _boom(*args, **kwargs):        # 命中后绝不允许再算动量
        raise AssertionError("cache hit should skip momentum_panel")

    monkeypatch.setattr(pipeline, "momentum_panel", _boom)
    monkeypatch.setattr("etf_rotation.data.snapshot.data_snapshot_id", lambda: "d1")
    monkeypatch.setattr(cache, "signal_id", lambda params, snap: "sid")

    panels = {
        "m21": pd.DataFrame(0.1, index=idx, columns=tickers),
        "m60": pd.DataFrame(0.2, index=idx, columns=tickers),
        "vol60": pd.DataFrame(0.3, index=idx, columns=tickers),
        "zbias": pd.DataFrame(-0.5, index=idx, columns=tickers),
        "llt80": pd.DataFrame(1.0, index=idx, columns=tickers),
        "rev_active": pd.DataFrame(False, index=idx, columns=tickers),
    }
    scalars = pd.DataFrame(
        {"comp": 0.0, "regime": "range", "nas_mom": 0.1, "gold_mom": 0.1,
         "nas_vol": 0.2, "gold_vol": 0.2, "cyb_vol": 0.3,
         "cyb_below": False, "cyb_drop": 0.0}, index=idx)
    cache.save(panels, scalars, "sid", tmp_path, {"code_hash": "h", "data_snapshot_id": "d1"})
    monkeypatch.setattr(cache, "cache_root", lambda: tmp_path)

    sig = pipeline._precompute_signals(
        close, close, amt, {}, {"nasdaq_etf": "A", "gold_etf": "B",
                                "risk": {"vol_window": 60, "llm80_alpha": 0.02},
                                "trend": {"windows": [21, 60], "weighting": "linear"},
                                "reversal": {"ema_span": 14, "z_window": 170,
                                             "zbias_threshold": -1.5,
                                             "repair_lookback": 5},
                                "market_state": {"alpha": 0.1, "slope_window": 8,
                                                 "slope_up": 0.5, "slope_down": -0.5,
                                                 "bull_threshold": 0.3,
                                                 "bear_threshold": -0.3}},
        {"A": "risk", "B": "bond"})

    expected = {"m21", "m60", "ret", "vol60", "n_days", "avg20", "regime", "comp",
                "nas_mom", "gold_mom", "nas_vol", "gold_vol", "cyb_vol", "cyb_below",
                "cyb_drop", "llt80", "close", "zbias", "rev_active", "risk_tickers",
                "def_tickers", "cat"}
    assert set(sig) == expected
    # 派生字段回来时必须与现算一致（不落盘，由 close/amt 廉价重算）
    pd.testing.assert_frame_equal(sig["ret"], close.pct_change(fill_method=None))
    pd.testing.assert_frame_equal(sig["n_days"], close.notna().cumsum())
    pd.testing.assert_frame_equal(sig["avg20"], amt.rolling(20).mean())
    pd.testing.assert_frame_equal(sig["close"], close)
    assert sig["risk_tickers"] == ["A"]
    assert sig["def_tickers"] == ["B"]
    assert sig["m21"].equals(panels["m21"])
    assert sig["regime"].iloc[0] == "range"


def test_precompute_miss_writes_cache_and_second_call_hits(monkeypatch, tmp_path):
    """未命中：照旧计算并落盘；第二次调用命中，数值一致。"""
    from etf_rotation import pipeline

    idx = _idx(80)
    tickers = ["A", "B"]
    close = pd.DataFrame(
        np.linspace(1.0, 1.4, len(idx) * 2).reshape(len(idx), 2), index=idx,
        columns=tickers)
    amt = pd.DataFrame(1e8, index=idx, columns=tickers)
    indices = {code: pd.Series(np.linspace(3000, 3200, len(idx)), index=idx)
               for code in ("000001.SH", "932000.CSI", "000922.CSI", "399006.SZ")}
    params = {"nasdaq_etf": "A", "gold_etf": "B",
              "risk": {"vol_window": 10, "llm80_alpha": 0.02},
              "trend": {"windows": [3, 5], "weighting": "linear"},
              "reversal": {"ema_span": 3, "z_window": 10,
                           "zbias_threshold": -1.5, "repair_lookback": 2},
              "market_state": {"alpha": 0.1, "slope_window": 8, "slope_up": 0.5,
                               "slope_down": -0.5, "bull_threshold": 0.3,
                               "bear_threshold": -0.3}}

    monkeypatch.setenv("ETF_SIGNAL_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("etf_rotation.data.snapshot.data_snapshot_id", lambda: "d1")
    monkeypatch.setattr(cache, "signal_id", lambda params, snap: "sid")

    first = pipeline._precompute_signals(close, close, amt, indices, params,
                                         {"A": "risk", "B": "bond"})
    assert (tmp_path / "sid" / "manifest.json").exists()
    assert not any(p.name.startswith(".tmp") for p in tmp_path.iterdir())

    # 第二次：把动量面板换成炸弹，证明真的走了缓存
    def _boom(*args, **kwargs):
        raise AssertionError("second call should hit cache")

    monkeypatch.setattr(pipeline, "momentum_panel", _boom)
    second = pipeline._precompute_signals(close, close, amt, indices, params,
                                          {"A": "risk", "B": "bond"})

    pd.testing.assert_frame_equal(first["m21"], second["m21"])
    pd.testing.assert_frame_equal(first["vol60"], second["vol60"])
    pd.testing.assert_frame_equal(first["ret"], second["ret"])
    pd.testing.assert_series_equal(first["regime"], second["regime"], check_names=False)
    assert set(first) == set(second)
