# 多资产 ETF 轮动策略复现 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 复现浙商证券多资产 ETF 轮动策略，产出可复现回测代码库与评估报告。

**Architecture:** 数据（tushare → bronze parquet → duckdb）→ 信号（趋势/反转/市场状态）→ 组合（去重/HRP/多资产/风控/防守）→ 执行（五相位/迟滞/T+1）→ 回测（bt 引擎）→ 评估（quantstats/敏感性/多重检验）。信号与权重全在 pandas/numpy 计算，bt 只做仓位记账。

**Tech Stack:** Python 3.10、pandas、numpy、pyarrow、duckdb、tushare、TA-Lib、PyPortfolioOpt、bt、quantstats、pytest。

**Spec:** `docs/superpowers/specs/2026-10-10-etf-rotation-design.md`

## Global Constraints

- Python 3.10，项目虚拟环境 `.venv`（用 `uv` 创建）。
- 依赖安装走官方 PyPI 或代理 `http://127.0.0.1:7897`；本机阿里云镜像对部分新 wheel 有滞后（404），不要用镜像。
- tushare token 只存 `.env`（已 gitignore），任何代码不得打印、提交或写入日志。
- 禁止商业量化平台/商业数据 SDK；数据源仅 tushare，parquet 存储，duckdb 查询。
- 回测纪律（ml4t）：所有滚动统计量 `.shift(1)`；T 日信号 T+1 开盘成交；无未来信息。
- 每个 Task 独立可测、独立 commit；遵循 TDD（先写失败测试再实现）。
- 文件编码 UTF-8；PowerShell 下运行 Python 时设 `$env:PYTHONIOENCODING="utf-8"`。

---

## 文件结构（本计划将创建）

```
requirements.txt
pyproject.toml
config/params.yaml
src/etf_rotation/__init__.py
src/etf_rotation/config.py
src/etf_rotation/data/__init__.py
src/etf_rotation/data/calendar.py
src/etf_rotation/data/ingest.py
src/etf_rotation/data/curate.py
src/etf_rotation/data/universe.py
src/etf_rotation/signals/__init__.py
src/etf_rotation/signals/trend.py
src/etf_rotation/signals/reversal.py
src/etf_rotation/signals/market_state.py
src/etf_rotation/portfolio/__init__.py
src/etf_rotation/portfolio/dedupe.py
src/etf_rotation/portfolio/hrp.py
src/etf_rotation/portfolio/multi_asset.py
src/etf_rotation/portfolio/risk_layers.py
src/etf_rotation/portfolio/defensive.py
src/etf_rotation/execution/__init__.py
src/etf_rotation/execution/phases.py
src/etf_rotation/execution/hysteresis.py
src/etf_rotation/execution/gap_delay.py
src/etf_rotation/backtest/__init__.py
src/etf_rotation/backtest/run.py
src/etf_rotation/evaluation/__init__.py
src/etf_rotation/evaluation/metrics.py
src/etf_rotation/evaluation/sensitivity.py
src/etf_rotation/evaluation/overfitting.py
scripts/fetch_data.py
scripts/run_backtest.py
tests/conftest.py
tests/test_config.py
tests/test_calendar.py
tests/test_curate.py
tests/test_universe.py
tests/test_trend.py
tests/test_reversal.py
tests/test_market_state.py
tests/test_hrp.py
tests/test_dedupe.py
tests/test_phases.py
tests/test_hysteresis.py
tests/test_gap_delay.py
tests/test_backtest.py
tests/test_metrics.py
```

## 关键接口约定（跨 Task 一致，不得改名）

- 价格面板统一为 `DataFrame`：index=`ts`(datetime)、columns=`ticker`。
- 复权价列名 `close_adj`；开盘价列名 `open`。
- 权重面板 `DataFrame`：index=`ts`、columns=`ticker`，每行和为 1（或 <1 时其余为现金）。
- 收益统一为日收益（小数，非百分比）。

---

### Task 1: 项目脚手架与配置加载

**Files:**
- Create: `pyproject.toml`、`src/etf_rotation/__init__.py`、`src/etf_rotation/config.py`、`config/params.yaml`、`tests/conftest.py`、`tests/test_config.py`

**Interfaces:**
- Produces: `config.load_params(path=None) -> dict`；`config.load_token() -> str`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_config.py
from etf_rotation import config

def test_load_params_defaults():
    p = config.load_params()
    assert p["trend"]["windows"] == [21, 60]
    assert p["dedupe"]["corr_threshold"] == 0.80
    assert p["costs"]["one_side_bps"] == 8

def test_load_token_from_env(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "abc")
    assert config.load_token() == "abc"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'etf_rotation'` 或 `ImportError`）

- [ ] **Step 3: 实现**

```yaml
# config/params.yaml
trend:
  windows: [21, 60]
  rank_weights: [0.7, 0.3]
  ann_factor: 250
reversal:
  ema_span: 14
  z_window: 170
  zbias_threshold: -0.5
  repair_lookback: 3
market_state:
  alpha: 0.10
  slope_window: 8
  bull_threshold: 0.35
  bear_threshold: -0.35
  slope_up: 1.005
  slope_down: 0.995
dedupe:
  corr_threshold: 0.80
  max_holdings: 10
multi_asset:
  risk: 0.50
  nasdaq: 0.375
  gold: 0.125
risk:
  llm80_alpha: 0.0247          # H3：80 日等价平滑
  index_drop_20d: -0.03
  overheat_pct: 0.20
  vol_target_risk: 0.26
  vol_target_nasdaq: 0.18
  vol_target_gold: 0.18
  vol_target_portfolio: 0.34
  vol_window: 60
  port_vol_window: 20
defensive:
  rebalance_days: 120
  top_n: 5
  max_vol_60d: 0.03
  momentum_window: 60
execution:
  phases: 5
  phase_interval: 5
  hysteresis_improve: 0.02   # H4
  gap_delay_pct: 0.01
costs:
  one_side_bps: 8
  cash_rate_annual: 0.018
universe:
  min_listed_days: 126
  min_avg_amount20: 5_000_000
hrp:
  window: 250
nasdaq_etf: "513100.SH"     # H10
gold_etf: "518880.SH"       # H10
```

```python
# pyproject.toml
[build-system]
requires = ["setuptools>=65"]
build-backend = "setuptools.build_meta"

[project]
name = "etf-rotation"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "pandas>=2.0", "numpy>=1.24", "pyarrow>=14", "duckdb>=0.10",
  "tushare>=1.4", "TA-Lib>=0.6", "PyPortfolioOpt>=1.5",
  "bt>=1.0", "quantstats>=0.0.62", "scipy>=1.10", "PyYAML>=6.0",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
```

```python
# src/etf_rotation/config.py
from __future__ import annotations
import os
from pathlib import Path
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT = _ROOT / "config" / "params.yaml"

def load_params(path=None) -> dict:
    p = Path(path) if path else _DEFAULT
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_token() -> str:
    return os.environ.get("TUSHARE_TOKEN", "").strip()
```

```python
# tests/conftest.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: 创建环境并提交**

```powershell
uv venv .venv --python 3.10
$env:UV_INDEX_URL="https://pypi.org/simple"
$env:HTTP_PROXY="http://127.0.0.1:7897"; $env:HTTPS_PROXY="http://127.0.0.1:7897"
uv pip install --python ".venv\Scripts\python.exe" -e ".[dev]"
uv pip freeze --python ".venv\Scripts\python.exe" | Out-File -Encoding utf8 requirements.txt
git add -A; git commit -m "feat: project scaffold and config"
```

注：`-e .[dev]` 需在 `pyproject.toml` 增加 `[project.optional-dependencies] dev = ["pytest>=8"]`；如安装报依赖冲突，退化为逐个安装并在 `requirements.txt` 手写冻结版本。

---

### Task 2: 交易日历

**Files:**
- Create: `src/etf_rotation/data/__init__.py`、`src/etf_rotation/data/calendar.py`、`tests/test_calendar.py`

**Interfaces:**
- Consumes: 无
- Produces: `calendar.trading_days(start: str, end: str) -> pd.DatetimeIndex`；`calendar.shift_by_trading_days(dates: pd.Series, n: int) -> pd.Series`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_calendar.py
import pandas as pd
from etf_rotation.data import calendar

def test_trading_days_excludes_weekend():
    days = calendar.trading_days("2024-01-01", "2024-01-10")
    assert len(days) > 0
    assert all(d.dayofweek < 5 for d in days)

def test_shift_by_trading_days():
    days = pd.Series(pd.to_datetime(["2024-01-02"]))
    out = calendar.shift_by_trading_days(days, 1)
    assert (out == pd.Timestamp("2024-01-03")).all()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_calendar.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现**

```python
# src/etf_rotation/data/calendar.py
from __future__ import annotations
import duckdb
import pandas as pd

_DB = "D:/project/quant_1/data/warehouse.duckdb"

def trading_days(start: str, end: str) -> pd.DatetimeIndex:
    con = duckdb.connect(_DB, read_only=True)
    df = con.execute(
        "SELECT ts FROM trading_calendar "
        "WHERE exchange='XSHG' AND is_open AND ts BETWEEN ? AND ? ORDER BY ts",
        [start, end],
    ).fetchdf()
    con.close()
    return pd.DatetimeIndex(df["ts"])

def shift_by_trading_days(dates: pd.Series, n: int) -> pd.Series:
    cal = trading_days(str(dates.min().date()), str(dates.max().date()))
    pos = pd.Series(pd.RangeIndex(len(cal)), index=cal)
    idx = pos.reindex(dates.dt.normalize()).astype("Int64")
    shifted = cal.take((idx + n).clip(lower=0, upper=len(cal)-1).fillna(0).astype(int))
    return pd.Series(pd.to_datetime(shifted), index=dates.index)
```

注：若 `trading_calendar` 表为空（gold 层未灌数据），改为从 bronze 的 bars_daily 去重得到交易日，并在 Task 3 统一灌入。实现时以「先查表、为空则回退 bars 去重」处理。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_calendar.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add -A; git commit -m "feat: trading calendar utilities"
```

---

### Task 3: 数据校验与复权价

**Files:**
- Create: `src/etf_rotation/data/curate.py`、`tests/test_curate.py`

**Interfaces:**
- Consumes: bronze parquet（`symbol_id, ts, open/high/low/close, volume`；`symbol_id, ts, adj_factor`）
- Produces: `curate.validate_ohlcv(bars: pd.DataFrame) -> dict`；`curate.adjusted_close(bars: pd.DataFrame, adj: pd.DataFrame) -> pd.DataFrame`（列：`symbol_id, ts, close_adj`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_curate.py
import pandas as pd
from etf_rotation.data import curate

def _bars():
    return pd.DataFrame({
        "symbol_id": [1, 1, 1],
        "ts": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        "open": [1.0, 1.1, 1.2], "high": [1.2, 1.3, 1.4],
        "low": [0.9, 1.0, 1.1], "close": [1.0, 1.1, 1.2], "volume": [100, 100, 100],
    })

def test_validate_flags_bad_ohlc():
    b = _bars(); b.loc[1, "high"] = 0.5
    issues = curate.validate_ohlcv(b)
    assert issues["high_lt_low"] >= 1

def test_adjusted_close():
    b = _bars()
    adj = pd.DataFrame({"symbol_id": [1, 1, 1],
        "ts": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
        "adj_factor": [2.0, 2.0, 1.0]})
    out = curate.adjusted_close(b, adj)
    assert out.loc[out.ts == "2024-01-04", "close_adj"].iloc[0] == 1.2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_curate.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现**

```python
# src/etf_rotation/data/curate.py
from __future__ import annotations
import pandas as pd

def validate_ohlcv(bars: pd.DataFrame) -> dict:
    issues = {}
    issues["high_lt_low"] = int((bars["high"] < bars["low"]).sum())
    issues["close_outside_hl"] = int(
        ((bars["close"] > bars["high"]) | (bars["close"] < bars["low"])).sum())
    issues["null_close"] = int(bars["close"].isna().sum())
    issues["duplicates"] = int(bars.duplicated(["symbol_id", "ts"]).sum())
    return issues

def adjusted_close(bars: pd.DataFrame, adj: pd.DataFrame) -> pd.DataFrame:
    m = bars.merge(adj, on=["symbol_id", "ts"], how="left")
    m["adj_factor"] = m["adj_factor"].ffill().fillna(1.0)
    # 以最近一期复权因子为基准，后复权
    last = m.groupby("symbol_id")["adj_factor"].transform("last")
    m["close_adj"] = m["close"] * m["adj_factor"] / last
    return m[["symbol_id", "ts", "close_adj"]]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_curate.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add -A; git commit -m "feat: data validation and adjusted close"
```

---

### Task 4: tushare 数据补充（指数与 fund_basic）

**Files:**
- Create: `src/etf_rotation/data/ingest.py`、`scripts/fetch_data.py`

**Interfaces:**
- Consumes: `config.load_token()`
- Produces: `ingest.fetch_index_daily(token, ts_code, start, end) -> pd.DataFrame`；`ingest.fetch_fund_basic(token) -> pd.DataFrame`；保存 parquet 到 `data/bronze/tushare/etf_rotation/`

- [ ] **Step 1: 写失败测试（用 monkeypatch 打桩 tushare，不实际联网）**

```python
# tests/test_ingest.py
import pandas as pd
from etf_rotation.data import ingest

def test_fetch_index_daily_renames(tmp_path, monkeypatch):
    class FakePro:
        def index_daily(self, **kw):
            return pd.DataFrame({"ts_code": ["932000.CSI"]*2, "trade_date": ["20240102", "20240103"],
                                 "close": [100, 101]})
    monkeypatch.setattr(ingest.ts, "pro_api", lambda token: FakePro())
    df = ingest.fetch_index_daily("tok", "932000.CSI", "2024-01-01", "2024-01-03")
    assert list(df.columns) == ["ts_code", "ts", "close"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_ingest.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现**

```python
# src/etf_rotation/data/ingest.py
from __future__ import annotations
import pandas as pd
import tushare as ts

def fetch_index_daily(token: str, ts_code: str, start: str, end: str) -> pd.DataFrame:
    pro = ts.pro_api(token)
    df = pro.index_daily(ts_code=ts_code, start_date=start.replace("-", ""),
                         end_date=end.replace("-", ""))
    df = df.sort_values("trade_date")
    df["ts"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    return df[["ts_code", "ts", "close"]]

def fetch_fund_basic(token: str) -> pd.DataFrame:
    pro = ts.pro_api(token)
    fields = "ts_code,name,fund_type,list_date,delist_date"
    df = pro.fund_basic(market="E", fields=fields)
    df["list_date"] = pd.to_datetime(df["list_date"], format="%Y%m%d", errors="coerce")
    return df
```

```python
# scripts/fetch_data.py
import os
from dotenv import load_dotenv
from etf_rotation.config import load_token
from etf_rotation.data import ingest

def main():
    load_dotenv()
    token = load_token()
    if not token:
        raise SystemExit("TUSHARE_TOKEN missing in .env")
    for code in ["932000.CSI", "000922.CSI"]:
        df = ingest.fetch_index_daily(token, code, "2015-01-01", "2026-07-31")
        df.to_parquet(f"data/bronze/tushare/etf_rotation/{code}.parquet", index=False)
    fb = ingest.fetch_fund_basic(token)
    fb.to_parquet("data/bronze/tushare/etf_rotation/fund_basic.parquet", index=False)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_ingest.py -v`
Expected: PASS

- [ ] **Step 5: 运行补充脚本并提交**

```powershell
$env:HTTP_PROXY="http://127.0.0.1:7897"; $env:HTTPS_PROXY="http://127.0.0.1:7897"
.venv\Scripts\python.exe scripts/fetch_data.py
git add -A; git commit -m "feat: tushare ingest for indices and fund_basic"
```

注：`python-dotenv` 加入依赖；tushare 调用加简单重试（3 次、指数退避）。

---

### Task 5: 标的池（point-in-time universe 与分类）

**Files:**
- Create: `src/etf_rotation/data/universe.py`、`tests/test_universe.py`

**Interfaces:**
- Consumes: bars（`symbol_id, ts, close, volume, amount` 或 `close*volume` 近似）、fund_basic
- Produces: `universe.classify(fund_basic) -> pd.Series`（值域 {risk, bond, money, convertible, exclude}）；`universe.build_pool(bars, meta, as_of) -> pd.DataFrame`（列：`symbol_id, ticker, listed_days, avg_amount20, category`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_universe.py
import pandas as pd
from etf_rotation.data import universe

def test_classify():
    fb = pd.DataFrame({"ts_code": ["511880.SH", "511010.SH", "511380.SH", "518880.SH"],
        "name": ["银华日利", "国债ETF", "可转债ETF", "黄金ETF"],
        "fund_type": ["货币市场型", "债券型", "债券型", "商品型"]})
    c = universe.classify(fb)
    assert c["511880.SH"] == "money"
    assert c["511380.SH"] == "convertible"
    assert c["518880.SH"] == "risk"

def test_build_pool_filters_liquidity():
    bars = pd.DataFrame({"symbol_id": [1]*3, "ts": pd.to_datetime(["2024-01-02"]*3),
        "close": [1.0]*3, "volume": [1000]*3, "amount": [1e6]*3})
    meta = pd.DataFrame({"symbol_id": [1], "ticker": ["159999.SZ"],
        "listed_on": [pd.Timestamp("2023-01-01")], "category": ["risk"]})
    pool = universe.build_pool(bars, meta, pd.Timestamp("2024-01-02"))
    assert len(pool) == 0   # 上市 <126 日
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_universe.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现**

```python
# src/etf_rotation/data/universe.py
from __future__ import annotations
import pandas as pd

CONVERTIBLE_KW = ["转债"]
MONEY_KW = ["货币", "现金", "理财", "保证金"]
BOND_KW = ["债", "国债", "国开", "政金", "短融", "存单", "信用"]

def classify(fund_basic: pd.DataFrame) -> pd.Series:
    def _one(row):
        name = str(row["name"]); ft = str(row["fund_type"])
        if any(k in name for k in CONVERTIBLE_KW):
            return "convertible"
        if ft in ("货币市场型",) or any(k in name for k in MONEY_KW):
            return "money"
        if ft == "债券型" or any(k in name for k in BOND_KW):
            return "bond"
        return "risk"
    return fund_basic.apply(_one, axis=1).rename("category")

def build_pool(bars: pd.DataFrame, meta: pd.DataFrame, as_of: pd.Timestamp,
               min_days: int = 126, min_amount: float = 5_000_000) -> pd.DataFrame:
    recent = bars[bars["ts"] <= as_of]
    agg = recent.groupby("symbol_id").agg(
        listed_days=("ts", "nunique"),
        avg_amount20=("amount", lambda s: s.tail(20).mean()),
    ).reset_index()
    pool = agg[(agg["listed_days"] >= min_days) & (agg["avg_amount20"] >= min_amount)]
    return pool.merge(meta, on="symbol_id", how="left")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_universe.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add -A; git commit -m "feat: point-in-time universe and ETF classification"
```

---

### Task 6: 趋势得分（时间加权回归）

**Files:**
- Create: `src/etf_rotation/signals/__init__.py`、`src/etf_rotation/signals/trend.py`、`tests/test_trend.py`

**Interfaces:**
- Consumes: 复权价 Series
- Produces: `trend.momentum_score(close: pd.Series, window: int) -> pd.Series`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_trend.py
import numpy as np
import pandas as pd
from etf_rotation.signals import trend

def test_flat_series_zero_score():
    s = pd.Series(np.linspace(1, 1, 80), index=pd.date_range("2024-01-01", periods=80))
    m = trend.momentum_score(s, 21)
    assert abs(m.iloc[-1]) < 1e-9

def test_uptrend_positive_and_downtrend_negative():
    up = pd.Series(np.exp(np.linspace(0, 0.1, 40)), index=pd.date_range("2024-01-01", periods=40))
    down = pd.Series(np.exp(np.linspace(0.1, 0, 40)), index=pd.date_range("2024-01-01", periods=40))
    assert trend.momentum_score(up, 21).iloc[-1] > 0
    assert trend.momentum_score(down, 21).iloc[-1] < 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_trend.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现**

```python
# src/etf_rotation/signals/trend.py
from __future__ import annotations
import numpy as np
import pandas as pd

def momentum_score(close: pd.Series, window: int, ann: int = 250) -> pd.Series:
    logp = np.log(close)
    out = pd.Series(index=close.index, dtype=float)
    for i in range(window, len(close) + 1):
        y = logp.iloc[i - window:i].to_numpy()
        x = np.arange(1, window + 1, dtype=float)
        w = x / x.sum()                      # H1：线性时间权重
        xw = (w * x).sum(); yw = (w * y).sum()
        slope = (w * (x - xw) * (y - yw)).sum() / (w * (x - xw) ** 2).sum()
        yhat = slope * x + (yw - slope * xw)
        ss_res = (w * (y - yhat) ** 2).sum()
        ss_tot = (w * (y - yw) ** 2).sum()
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        out.iloc[i - 1] = (np.exp(ann * slope) - 1) * r2
    return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_trend.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add -A; git commit -m "feat: time-weighted regression momentum score"
```

---

### Task 7: 反转信号与市场状态（LLT）

**Files:**
- Create: `src/etf_rotation/signals/reversal.py`、`src/etf_rotation/signals/market_state.py`、`tests/test_reversal.py`、`tests/test_market_state.py`

**Interfaces:**
- Consumes: 复权价 Series；三指数复权价 DataFrame
- Produces: `reversal.zbias(close: pd.Series) -> pd.Series`；`reversal.active(close) -> pd.Series(bool)`；`market_state.llt(close: pd.Series, alpha: float) -> pd.Series`；`market_state.composite_score(indexes: dict[str, pd.Series], alpha=0.10) -> pd.Series`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_reversal.py
import numpy as np
import pandas as pd
from etf_rotation.signals import reversal

def test_zbias_centered():
    rng = np.random.default_rng(0)
    s = pd.Series(100 + np.cumsum(rng.normal(0, 0.1, 400)),
                  index=pd.date_range("2022-01-01", periods=400))
    z = reversal.zbias(s)
    assert abs(z.iloc[-200:].mean()) < 0.5
```

```python
# tests/test_market_state.py
import numpy as np
import pandas as pd
from etf_rotation.signals import market_state

def test_llt_lags_less_than_ema():
    t = pd.Series(np.arange(100.0), index=pd.date_range("2023-01-01", periods=100))
    l = market_state.llt(t, alpha=0.10)
    assert l.iloc[-1] < t.iloc[-1]
    assert l.iloc[-1] > t.iloc[-1] - 20

def test_composite_score_bounds():
    idx = pd.date_range("2023-01-01", periods=200)
    up = pd.Series(np.linspace(100, 120, 200), index=idx)
    down = pd.Series(np.linspace(100, 80, 200), index=idx)
    flat = pd.Series(100.0, index=idx)
    score = market_state.composite_score({"a": up, "b": down, "c": flat})
    assert score.between(-1, 1).all()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_reversal.py tests/test_market_state.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现**

```python
# src/etf_rotation/signals/reversal.py
from __future__ import annotations
import numpy as np
import pandas as pd

def zbias(close: pd.Series, ema_span: int = 14, z_window: int = 170) -> pd.Series:
    ema = close.ewm(span=ema_span, adjust=False).mean()
    logbias = np.log(close / ema)
    mu = logbias.rolling(z_window).mean().shift(1)
    sd = logbias.rolling(z_window).std().shift(1)
    return (logbias - mu) / sd

def active(close: pd.Series, threshold: float = -0.5, lookback: int = 3) -> pd.Series:
    z = zbias(close)
    return (z <= threshold) & (z > z.shift(lookback))
```

```python
# src/etf_rotation/signals/market_state.py
from __future__ import annotations
import pandas as pd

def llt(close: pd.Series, alpha: float) -> pd.Series:
    # Ehlers Low-Lag Filter（H2）
    a = alpha
    c = [a - a*a/4, a*a/2, -(a - 3*a*a/4), 2*(1-a), -(1-a)**2]
    y = pd.Series(index=close.index, dtype=float)
    y.iloc[:2] = close.iloc[:2]
    x = close.to_numpy()
    for i in range(2, len(close)):
        y.iloc[i] = c[0]*x[i] + c[1]*x[i-1] + c[2]*x[i-2] + c[3]*y.iloc[i-1] + c[4]*y.iloc[i-2]
    return y

def composite_score(indexes: dict, alpha: float = 0.10, win: int = 8) -> pd.Series:
    states = pd.DataFrame({k: _slope_state(v, alpha, win) for k, v in indexes.items()})
    return states.mean(axis=1)

def _slope_state(close: pd.Series, alpha: float, win: int) -> pd.Series:
    l = llt(close, alpha)
    slope = l / l.shift(win)
    out = pd.Series(0.0, index=close.index)
    out.loc[slope > 1.005] = 1.0
    out.loc[slope < 0.995] = -1.0
    return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_reversal.py tests/test_market_state.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add -A; git commit -m "feat: reversal signal and LLT market state"
```

---

### Task 8: 去重与 HRP

**Files:**
- Create: `src/etf_rotation/portfolio/__init__.py`、`src/etf_rotation/portfolio/dedupe.py`、`src/etf_rotation/portfolio/hrp.py`、`tests/test_dedupe.py`、`tests/test_hrp.py`

**Interfaces:**
- Consumes: 候选 ticker 列表、收益面板
- Produces: `dedupe.dedupe(candidates: list[str], corr: pd.DataFrame, threshold: float, max_n: int) -> list[str]`；`hrp.hrp_weights(returns: pd.DataFrame) -> pd.Series`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_dedupe.py
import pandas as pd
from etf_rotation.portfolio import dedupe

def test_dedupe_removes_high_corr():
    corr = pd.DataFrame({"A": [1, .9, .3], "B": [.9, 1, .2], "C": [.3, .2, 1]},
                        index=["A", "B", "C"])
    out = dedupe.dedupe(["A", "B", "C"], corr, 0.8, 10)
    assert "A" in out and "C" in out and len(out) == 2
```

```python
# tests/test_hrp.py
import numpy as np
import pandas as pd
from etf_rotation.portfolio import hrp

def test_hrp_weights_sum_to_one():
    rng = np.random.default_rng(1)
    ret = pd.DataFrame(rng.normal(0, 0.01, (300, 5)),
        columns=list("ABCDE"), index=pd.date_range("2023-01-01", periods=300))
    w = hrp.hrp_weights(ret)
    assert abs(w.sum() - 1) < 1e-6
    assert (w >= 0).all()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_dedupe.py tests/test_hrp.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现**

```python
# src/etf_rotation/portfolio/dedupe.py
def dedupe(candidates, corr, threshold, max_n):
    order = list(candidates)
    keep = []
    for c in order:
        if all(abs(corr.loc[c, k]) < threshold for k in keep):
            keep.append(c)
        if len(keep) >= max_n:
            break
    return keep
```

```python
# src/etf_rotation/portfolio/hrp.py
import pandas as pd
from pypfopt import risk_models
from pypfopt.hierarchical_portfolio import HRPOpt

def hrp_weights(returns: pd.DataFrame) -> pd.Series:
    cov = risk_models.sample_cov(returns, returns_data=True)
    hrp = HRPOpt(returns=returns, cov_matrix=cov)
    return pd.Series(hrp.optimize(linkage_method="single"), index=returns.columns)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_dedupe.py tests/test_hrp.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add -A; git commit -m "feat: correlation dedupe and HRP weighting"
```

---

### Task 9: 多资产底仓与分层风控、防守仓

**Files:**
- Create: `src/etf_rotation/portfolio/multi_asset.py`、`src/etf_rotation/portfolio/risk_layers.py`、`src/etf_rotation/portfolio/defensive.py`、`tests/test_risk_layers.py`

**Interfaces:**
- Consumes: 市场状态 Series、波动率、收益
- Produces:
  - `multi_asset.base_weights(market: str, nasdaq_signal: float, gold_signal: float) -> dict`
  - `risk_layers.risk_scale(market: str, idx_above_llt: bool, idx_drop_20d: float) -> float`
  - `risk_layers.vol_scale(realized_vol: float, target_vol: float) -> float`
  - `risk_layers.overheat_mask(close: pd.Series, llt80: pd.Series, pct: float) -> bool`
  - `defensive.select(returns: pd.DataFrame, vol60: pd.Series, category: pd.Series) -> list[str]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_risk_layers.py
from etf_rotation.portfolio import multi_asset, risk_layers

def test_base_weights_bull():
    w = multi_asset.base_weights("bull", 1.0, 1.0)
    assert w == {"risk": 0.50, "nasdaq": 0.375, "gold": 0.125}

def test_base_weights_bear():
    w = multi_asset.base_weights("bear", 1.0, 1.0)
    assert w["risk"] == 0.0

def test_risk_scale_weakness():
    assert risk_layers.risk_scale("bull", True, -0.01) == 1.0
    assert risk_layers.risk_scale("bull", False, -0.04) == 0.05
    assert risk_layers.risk_scale("bear", True, -0.01) == 0.0

def test_vol_scale_only_shrinks():
    assert risk_layers.vol_scale(0.20, 0.26) == 1.0
    assert abs(risk_layers.vol_scale(0.52, 0.26) - 0.5) < 1e-9
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_risk_layers.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现**

```python
# src/etf_rotation/portfolio/multi_asset.py
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
```

```python
# src/etf_rotation/portfolio/risk_layers.py
def risk_scale(market: str, idx_above_llt: bool, idx_drop_20d: float) -> float:
    if market == "bear":
        return 0.0
    if market == "range":
        base = 0.95
    else:
        base = 1.0
    if (not idx_above_llt) and idx_drop_20d < -0.03:
        return 0.05
    return base

def vol_scale(realized_vol: float, target_vol: float) -> float:
    if realized_vol <= target_vol:
        return 1.0
    return target_vol / realized_vol

def overheat_mask(close, llt80, pct: float) -> bool:
    return close.iloc[-1] >= llt80.iloc[-1] * (1 + pct)
```

```python
# src/etf_rotation/portfolio/defensive.py
def select(returns, vol60, category) -> list:
    cand = vol60[vol60 < 0.03].index
    cand = [c for c in cand if category.get(c, "risk") in ("bond", "money")]
    rar = returns[cand].iloc[-60:].mean() / returns[cand].iloc[-60:].std()
    rar = rar.sort_values(ascending=False)
    picked, seen = [], set()
    for c in rar.index:
        if category.get(c) not in seen:
            picked.append(c); seen.add(category.get(c))
        if len(picked) >= 5:
            break
    return picked
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_risk_layers.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add -A; git commit -m "feat: multi-asset base weights, risk layers, defensive pool"
```

---

### Task 10: 五相位、迟滞与 T+1 跳空执行

**Files:**
- Create: `src/etf_rotation/execution/__init__.py`、`src/etf_rotation/execution/phases.py`、`src/etf_rotation/execution/hysteresis.py`、`src/etf_rotation/execution/gap_delay.py`、`tests/test_phases.py`、`tests/test_hysteresis.py`、`tests/test_gap_delay.py`

**Interfaces:**
- Consumes: 单相位目标权重、旧持仓、得分
- Produces:
  - `phases.combine(targets: list[pd.DataFrame], schedule: list[int]) -> pd.DataFrame`
  - `hysteresis.apply(old: pd.Series, new: pd.Series, score_old: float, score_new: float, min_improve: float) -> pd.Series`
  - `gap_delay.delay_orders(orders: pd.DataFrame, open_: pd.DataFrame, close: pd.DataFrame, pct: float) -> pd.DataFrame`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_phases.py
import pandas as pd
from etf_rotation.execution import phases

def test_combine_averages_staggered():
    idx = pd.date_range("2024-01-01", periods=10)
    a = pd.DataFrame(1.0, index=idx, columns=["X"])
    b = pd.DataFrame(0.0, index=idx, columns=["X"])
    out = phases.combine([a, b], [0, 1])
    assert out["X"].iloc[0] == 0.5   # 两相位等权
```

```python
# tests/test_hysteresis.py
import pandas as pd
from etf_rotation.execution import hysteresis

def test_hysteresis_keeps_old_when_no_improvement():
    old = pd.Series({"A": 1.0}); new = pd.Series({"B": 1.0})
    out = hysteresis.apply(old, new, score_old=0.8, score_new=0.8, min_improve=0.02)
    assert out.equals(old)
```

```python
# tests/test_gap_delay.py
import pandas as pd
from etf_rotation.execution import gap_delay

def test_buy_delayed_on_gap_up():
    idx = pd.date_range("2024-01-01", periods=2)
    orders = pd.DataFrame([[0.0, 1.0], [0.0, 0.0]], index=idx, columns=["A", "B"])
    open_ = pd.DataFrame([[1.0, 1.02], [1.0, 1.0]], index=idx, columns=["A", "B"])
    close = pd.DataFrame([[1.0, 1.0], [1.0, 1.0]], index=idx, columns=["A", "B"])
    out = gap_delay.delay_orders(orders, open_, close, 0.01)
    assert out["B"].iloc[0] == 0.0 and out["B"].iloc[1] == 1.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_phases.py tests/test_hysteresis.py tests/test_gap_delay.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现**

```python
# src/etf_rotation/execution/phases.py
import pandas as pd

def combine(targets, schedule):
    out = pd.DataFrame(0.0, index=targets[0].index, columns=targets[0].columns)
    for i, t in enumerate(targets):
        active = t.index.day % 5 == schedule[i]
        # 每个相位在非调仓日延续自身上一目标，调仓日更新
        held = t.copy()
        held[~active] = held[~active].shift(1, fill_value=0.0)
        out += held / len(targets)
    return out
```

```python
# src/etf_rotation/execution/hysteresis.py
def apply(old, new, score_old, score_new, min_improve):
    if score_new <= score_old * (1 + min_improve):
        return old
    return new
```

```python
# src/etf_rotation/execution/gap_delay.py
def delay_orders(orders, open_, close, pct):
    out = orders.copy()
    buy = orders > 0
    gap = open_ / close.shift(1) - 1
    delayed = (buy & (gap >= pct))
    shifted = orders.where(delayed).shift(1).fillna(0.0)
    out = orders.where(~delayed, 0.0) + shifted
    return out
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_phases.py tests/test_hysteresis.py tests/test_gap_delay.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add -A; git commit -m "feat: five-phase, hysteresis and gap-delay execution"
```

---

### Task 11: bt 回测引擎封装

**Files:**
- Create: `src/etf_rotation/backtest/__init__.py`、`src/etf_rotation/backtest/run.py`、`tests/test_backtest.py`

**Interfaces:**
- Consumes: 权重面板、开盘/收盘价面板、成本、现金利率
- Produces: `run.run(weights, open_price, close_price, cost_bps, cash_rate) -> pd.DataFrame`（列：`returns, nav`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_backtest.py
import pandas as pd
from etf_rotation.backtest import run

def test_buy_and_hold_nav_matches_price():
    idx = pd.date_range("2024-01-01", periods=4)
    w = pd.DataFrame(1.0, index=idx, columns=["X"])
    close = pd.DataFrame([10, 11, 12, 13], index=idx, columns=["X"], dtype=float)
    open_ = close.shift(1).fillna(10.0)
    res = run.run(w, open_, close, cost_bps=0, cash_rate=0)
    assert abs(res["nav"].iloc[-1] - 1.3) < 1e-9
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_backtest.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现**

```python
# src/etf_rotation/backtest/run.py
import numpy as np
import pandas as pd

def run(weights, open_price, close_price, cost_bps=8, cash_rate=0.018):
    w = weights.reindex(columns=close_price.columns).fillna(0.0)
    ret = close_price.pct_change().fillna(0.0)
    nav = 1.0
    navs, prev = [], pd.Series(0.0, index=w.columns)
    cash_w = 1.0
    daily_cash = (1 + cash_rate) ** (1/252) - 1
    for t in range(len(w)):
        target = w.iloc[t]
        if t > 0:
            trade = (target - prev).abs().sum()
            cost = trade * cost_bps / 10000
            nav *= (1 - cost)
        gross = (target * ret.iloc[t]).sum()
        nav *= (1 + gross + (1 - target.sum()) * daily_cash)
        prev = target
        navs.append(nav)
    nav_s = pd.Series(navs, index=w.index)
    return pd.DataFrame({"nav": nav_s, "returns": nav_s.pct_change().fillna(nav_s.iloc[0]-1)})
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_backtest.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```powershell
git add -A; git commit -m "feat: bt-style portfolio simulator"
```

注：本封装先按 pandas 向量化实现以保证可测性；若后续发现换手/现金口径需要事件级精度，再替换为 `bt` 的 `AlgoStack`（`Rebalance`/`WeighTarget`）实现，接口 `run.run(...)` 保持不变。

---

### Task 12: 绩效、敏感性、多重检验与端到端入口

**Files:**
- Create: `src/etf_rotation/evaluation/__init__.py`、`src/etf_rotation/evaluation/metrics.py`、`src/etf_rotation/evaluation/sensitivity.py`、`src/etf_rotation/evaluation/overfitting.py`、`scripts/run_backtest.py`、`tests/test_metrics.py`

**Interfaces:**
- Consumes: 日收益 Series
- Produces: `metrics.summary(returns, periods=252) -> dict`；`sensitivity.sweep(run_fn, grid) -> pd.DataFrame`；`overfitting.deflated_sharpe(sharpes, n_trials) -> float`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_metrics.py
import pandas as pd
import pytest
from etf_rotation.evaluation import metrics, overfitting

def test_summary_known_series():
    r = pd.Series([0.01, -0.005, 0.02], dtype=float)
    s = metrics.summary(r)
    expected = (1.01 * 0.995 * 1.02) ** (252 / 3) - 1
    assert s["ann_return"] == pytest.approx(expected)
    assert "max_drawdown" in s and "sharpe" in s

def test_dsr_high_for_many_bad_trials():
    p = overfitting.deflated_sharpe([0.5]*100, 100)
    assert 0 <= p <= 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_metrics.py -v`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: 实现**

```python
# src/etf_rotation/evaluation/metrics.py
import numpy as np
import pandas as pd

def summary(returns: pd.Series, periods: int = 252) -> dict:
    r = returns.dropna()
    cum = (1 + r).cumprod()
    dd = (cum / cum.cummax() - 1)
    ann = (1 + r).prod() ** (periods / len(r)) - 1
    vol = r.std() * np.sqrt(periods)
    sharpe = r.mean() / r.std() * np.sqrt(periods) if r.std() > 0 else 0.0
    downside = np.minimum(r, 0)
    sortino = r.mean() / downside.std() * np.sqrt(periods) if downside.std() > 0 else 0.0
    max_dd = dd.min()
    calmar = ann / abs(max_dd) if max_dd < 0 else 0.0
    return {"ann_return": ann, "ann_vol": vol, "sharpe": sharpe, "sortino": sortino,
            "max_drawdown": max_dd, "calmar": calmar,
            "var_95": r.quantile(0.05), "cvar_95": r[r <= r.quantile(0.05)].mean()}
```

```python
# src/etf_rotation/evaluation/sensitivity.py
import itertools
import pandas as pd

def sweep(run_fn, grid: dict) -> pd.DataFrame:
    rows = []
    keys = list(grid)
    for combo in itertools.product(*grid.values()):
        params = dict(zip(keys, combo))
        res = run_fn(**params)
        rows.append({**params, "sharpe": res["sharpe"], "max_drawdown": res["max_drawdown"],
                     "ann_return": res["ann_return"], "calmar": res["calmar"]})
    return pd.DataFrame(rows)
```

```python
# src/etf_rotation/evaluation/overfitting.py
import numpy as np
from scipy import stats

def deflated_sharpe(sharpes, n_trials: int) -> float:
    per = np.asarray(sharpes) / np.sqrt(252)
    euler = 0.5772156649
    sr_std = per.std(ddof=1)
    e_max = sr_std * ((1 - euler) * stats.norm.ppf(1 - 1/n_trials)
                      + euler * stats.norm.ppf(1 - 1/(n_trials*np.e)))
    obs = per.max()
    sr_se = np.sqrt(1 / (len(per) - 1))
    return stats.norm.cdf((obs - e_max) / sr_se)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_metrics.py -v`
Expected: PASS

- [ ] **Step 5: 编写端到端入口并提交**

```python
# scripts/run_backtest.py（骨架，后续接入 Task 6–11 的信号/组合/执行）
import duckdb, pandas as pd
from etf_rotation.backtest import run
from etf_rotation.evaluation import metrics

def main():
    # 1) 从 duckdb/parquet 读复权价面板  2) 算信号  3) 算目标权重  4) run()
    ...
    print(metrics.summary(returns))

if __name__ == "__main__":
    main()
```

```powershell
git add -A; git commit -m "feat: performance metrics, sensitivity and DSR"
```

---

### Task 13: 全流程串联与报告生成

**Files:**
- Modify: `scripts/run_backtest.py`（把 Task 6–11 各模块串成完整流水线）
- Create: `scripts/run_sensitivity.py`、`reports/` 输出、`README.md`

**Interfaces:**
- Consumes: Task 6–12 全部产物
- Produces: 基准回测净值/指标、敏感性表、`reports/` 报告文件

- [ ] **Step 1: 组装流水线**（数据→信号→组合→执行→回测→评估，顺序调用，无新算法）
- [ ] **Step 2: 跑通基准回测**，记录 2019-01~2026-07 年化/回撤/Calmar，与报告 20.74%/10.13%/2.05 对比
- [ ] **Step 3: 跑敏感性网格**（动量窗口、相关性阈值、过热阈值、波动率目标、成本 1x/2x/3x、LLT 参数）
- [ ] **Step 4: 算 DSR/PSR**，记录试验总数
- [ ] **Step 5: 写 README**（环境、安装、数据准备、运行命令、复现假设 H1–H10、差异说明）
- [ ] **Step 6: 提交**

```powershell
git add -A; git commit -m "feat: end-to-end pipeline and reports"
```

---

## Self-Review 记录

- Spec 覆盖：§2 策略机制 → Task 6–11；§3 假设 H1–H10 → 参数 yaml 与各实现注释；§4 技术栈 → Task 1；§5 目录 → 文件结构；§6 数据层 → Task 2–5；§7 信号 → Task 6–7；§8 组合 → Task 8–9；§9 执行 → Task 10–11；§10 评估 → Task 12–13；§11 ml4t 映射 → Global Constraints；§12 测试 → 各 Task 测试；§13 交付物 → Task 13。
- 类型一致性：价格/权重面板约定、`metrics.summary`/`run.run`/`momentum_score` 等签名在定义处与引用处一致。
- 无占位符：`run_backtest.py` 的 `...` 为 Task 13 明确要填的串联步骤，不属 TBD 占位。

