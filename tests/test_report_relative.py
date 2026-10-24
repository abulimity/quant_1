"""相对指标与剔除防守相关性（N3 + N9）契约（计划 Task 9）。

口径：
- beta = cov(r_s, r_b) / var(r_b)，correlation 为同日 Pearson 相关；
- excess_cagr 用日历日 CAGR 之差（ffn.calc_cagr，净值端点口径）；
- excess_arith 为年化算术超额 `(mean_s − mean_b) × 252`；
- tracking_error = std(r_s − r_b) × √252，information_ratio = excess_arith / TE；
- 分母为 0 一律返回 None（禁止 inf/nan，JSON 必须过 allow_nan=False）；
- 滚动窗口不足 252 天必须是 NaN（不许 fillna 制造虚假稳定期）；
- 剔除防守：把 bond/money 权重置 0，按平均风险暴露归一化后再比基准。
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from etf_rotation.report import serialize
from etf_rotation.report.context import ReportContext
from etf_rotation.report.steps import relative


def test_relative_summary_on_known_series():
    idx = pd.date_range("2020-01-01", periods=600, freq="B")
    b = pd.Series(np.sin(np.arange(600)) * 0.01, index=idx)
    m = relative.relative_summary(0.5 * b + 0.001, b)
    assert m["beta"] == pytest.approx(0.5, abs=1e-12)
    assert m["correlation"] == pytest.approx(1.0, abs=1e-12)


def test_tracking_error_zero_for_constant_offset():
    idx = pd.date_range("2020-01-01", periods=600, freq="B")
    b = pd.Series(np.sin(np.arange(600)) * 0.01, index=idx)
    assert relative.relative_summary(b + 0.0001, b)["tracking_error"] == pytest.approx(0.0, abs=1e-12)


def test_rolling_relative_drops_warmup_instead_of_filling():
    idx = pd.date_range("2020-01-01", periods=300, freq="B")
    b = pd.Series(np.sin(np.arange(300)) * 0.01, index=idx)
    df = relative.rolling_relative(0.5 * b + 0.001, b, window=252)
    assert df["beta"].iloc[:251].isna().all() and df["beta"].iloc[251:].notna().all()


def test_beta_scaling_preserves_average_exposure():
    idx = pd.date_range("2020-01-01", periods=300, freq="B")
    b = pd.Series(np.sin(np.arange(300)) * 0.01, index=idx)
    weights = pd.DataFrame({"A": 0.5}, index=idx)      # 恒定 50% 风险仓
    close = pd.DataFrame({"A": 10 * (1 + b).cumprod()}, index=idx)
    out = relative.risk_sleeve_relative(b, weights, close, {"A": "risk"}, b)
    assert out["beta_risk_sleeve"] == pytest.approx(1.0, abs=1e-9)   # 按 mean_risk_weight 缩放
    assert out["beta_scaling"] == pytest.approx(0.5)


def test_defensive_columns_are_zeroed_out():
    """bond/money 列不参与风险仓：只有 risk 列决定剔除防守后的相关性。"""
    idx = pd.date_range("2020-01-01", periods=60, freq="B")
    b = pd.Series(np.sin(np.arange(60)) * 0.01, index=idx)
    weights = pd.DataFrame({"A": 0.4, "B": 0.6}, index=idx)
    close = pd.DataFrame({"A": 10 * (1 + b).cumprod(),
                          "B": 10 * (1 - b).cumprod()}, index=idx)
    out = relative.risk_sleeve_relative(
        b, weights, close, {"A": "risk", "B": "bond"}, b)
    assert out["mean_risk_weight"] == pytest.approx(0.4)
    assert out["corr_risk_sleeve"] == pytest.approx(1.0, abs=1e-9)


def test_zero_variance_returns_none_not_inf():
    idx = pd.date_range("2020-01-01", periods=30, freq="B")
    flat = pd.Series(0.001, index=idx)
    m = relative.relative_summary(flat + 0.0001, flat)
    assert m["tracking_error"] == pytest.approx(0.0, abs=1e-15)
    assert m["information_ratio"] is None
    assert m["beta"] is None
    assert m["correlation"] is None


def _ctx():
    idx = pd.date_range("2020-01-01", periods=600, freq="B")
    b = pd.Series(np.sin(np.arange(600)) * 0.01, index=idx)
    return ReportContext(run_id="r1", meta={"data_snapshot_id": "d1"}, params={},
                         equity=pd.DataFrame({"nav": (1 + b).cumprod(), "returns": b}, index=idx),
                         benchmark=pd.DataFrame({"hs300": (1 + b).cumprod()}, index=idx),
                         weights=pd.DataFrame({"A": 0.5}, index=idx),
                         holdings=None, trades=None, transactions=None, diary=None,
                         ticker_signals=None, stages=None, classification={"A": "risk"},
                         close=pd.DataFrame({"A": 10 * (1 + b).cumprod()}, index=idx),
                         opn=None, amount=None)


def test_build_outputs_json_safe_payload():
    out = relative.build(_ctx())
    assert {"summary", "rolling", "annual_excess", "ex_defensive", "lag_scan"} <= set(out)
    assert out["lag_scan"]["lags"] == sorted(out["lag_scan"]["lags"])
    assert out["ex_defensive"]["beta_scaling"] == pytest.approx(0.5)
    json.dumps(serialize.clean(out), allow_nan=False)   # 不允许 NaN/Inf 混进派生 JSON
