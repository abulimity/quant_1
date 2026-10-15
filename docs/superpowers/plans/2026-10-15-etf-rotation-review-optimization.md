# 代码审阅优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `docs/代码审阅意见.md` 的 12 条意见完成回测代码优化：行为不变的重构、以 bt 内置统计作为唯一回测评估来源、参数管理与实验登记、引擎化交易/持仓导出、数据 curation，以及敏感性与稳健性评估。

**Architecture:** 保持「信号在 pandas 预计算 → 目标权重面板 → bt 记账」的整体架构不变。优化集中在：pipeline 内部函数拆分、bt 算法链改用 `WeighTarget` + 独立现金计息 Algo、评估指标唯一取自 `bt.run().stats`、交易/换手唯一取自引擎、参数可覆盖并做内容寻址登记、复权价与交易日历从 bronze parquet curation 进 warehouse duckdb。

**Tech Stack:** Python 3.10 / pandas 2.3 / numpy 2.2 / duckdb 1.5 / bt 1.2.2 / ffn 1.4.1 / plotly 7.1 / pytest 9.1

**Spec:**
- `docs/代码审阅意见.md`（本次意见原文，权威目标）
- `docs/代码审阅手册.md`（补充背景与已修复项：§8.1/§8.2 已在 HEAD 修复）
- `docs/superpowers/specs/2026-10-10-etf-rotation-design.md`（策略机制与 H1–H10 口径）
- `AGENTS.md`（项目纪律与命令入口）

## Global Constraints

- Python 统一用 `.venv\Scripts\python.exe`；运行任何 Python 前先 `$env:PYTHONIOENCODING="utf-8"`
- 滚动统计量一律 `.shift(1)`；T 日信号、T+1 成交；禁止未来信息
- 一次只动一个维度，改完立刻重跑并对比 `reports/metrics.json`，否则无法归因
- 回测评估指标唯一来源 = bt 内置统计（ffn `Result.stats`），不再自行计算推导；年化仅固定 `×sqrt(252)`；VaR/CVaR 不再输出
- 交易明细、成本、换手以 bt 引擎结果（`get_transactions` / `Backtest.turnover`）为依据
- 数据源 tushare；`.env` 的 token 不得打印/提交/写日志；`data/` 已被 gitignore
- 改动按语义化 commit；当前分支 `main`
- 不适用 ML 训练类技能（walk-forward-CV / CPCV / 特征工程 / 模型集成 / 交叉验证策略），规则驱动用时间子区间 2019–2023 vs 2024–2026 近似
- 全量单测：`.venv\Scripts\python.exe -m pytest tests -q`
- 基准回测：`.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31`

---

## Task 1: 拆分 `build_weights`（行为不变重构）

**Files:**
- Modify: `src/etf_rotation/pipeline.py`
- Test: `tests/test_pipeline.py`（新建）

**Interfaces:**
- Produces:
  - `_precompute_signals(close, opn, amt, indices, params, cat) -> dict`
  - `_daily_target(i: int, d: pd.Timestamp, sig: dict, params: dict, last_def_update: int, current_defn: list[str]) -> tuple[dict, int, list[str]]`
  - `_combine_phases(phase_weights: list[pd.Series]) -> pd.Series`
- `build_weights(params, start, end) -> pd.DataFrame` 签名与返回值不变。

- [ ] **Step 1: 保存基准产物**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
Copy-Item reports\weights.parquet reports\weights.baseline.parquet
Copy-Item reports\metrics.json reports\metrics.baseline.json
```

- [ ] **Step 2: 写失败测试**

新建 `tests/test_pipeline.py`：

```python
import pandas as pd

from etf_rotation.pipeline import _combine_phases


def test_combine_phases_means_snapshots():
    a = pd.Series({"X": 1.0, "Y": 0.0})
    b = pd.Series({"X": 0.5, "Y": 0.5})
    out = _combine_phases([a, b, a, b, a])
    pd.testing.assert_series_equal(out, pd.Series({"X": 0.8, "Y": 0.2}))
```

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -q`
Expected: FAIL（`ImportError: cannot import name '_combine_phases'`）

- [ ] **Step 4: 抽取三个函数并重写循环**

在 `pipeline.py` 中：

1. 把现有 `build_weights` 里「信号预计算」整段（`logp = ...` 到 `def_tickers = [...]`）移入
   `_precompute_signals(close, opn, amt, indices, params, cat)`，返回 dict：

```python
def _precompute_signals(close, opn, amt, indices, params, cat):
    """全历史信号预计算（保证 2019 起点有 warmup，无前视）。"""
    logp = np.log(close)
    m21 = momentum_panel(logp, 21)
    m60 = momentum_panel(logp, 60)
    ret = close.pct_change(fill_method=None)
    vol60 = ret.rolling(60).std() * np.sqrt(252)
    n_days = close.notna().cumsum()
    avg20 = amt.rolling(20).mean()
    comp = ms.composite_score(
        {"sh": indices["000001.SH"], "zz2000": indices["932000.CSI"],
         "zzhl": indices["000922.CSI"]},
        alpha=params["market_state"]["alpha"],
    )
    regime = comp.map(
        lambda v: "bull" if v >= params["market_state"]["bull_threshold"]
        else ("bear" if v <= params["market_state"]["bear_threshold"] else "range")
    )
    nasdaq = params["nasdaq_etf"]
    gold = params["gold_etf"]
    nas_mom = trend.momentum_score(close[nasdaq], 60)
    gold_mom = trend.momentum_score(close[gold], 60)
    nas_vol = close[nasdaq].pct_change(fill_method=None).ewm(span=60).std() * np.sqrt(252)
    gold_vol = close[gold].pct_change(fill_method=None).ewm(span=60).std() * np.sqrt(252)
    cyb = indices["399006.SZ"]
    cyb_vol = cyb.pct_change(fill_method=None).ewm(span=60).std() * np.sqrt(252)
    cyb_llt = ms.llt(cyb, params["risk"]["llm80_alpha"])
    cyb_below = cyb < cyb_llt
    cyb_drop = cyb_llt.pct_change(20, fill_method=None)
    risk_tickers = [t for t, c in cat.items() if c == "risk" and t in close.columns]
    def_tickers = [t for t, c in cat.items() if c in ("bond", "money") and t in close.columns]
    return dict(m21=m21, m60=m60, ret=ret, vol60=vol60, n_days=n_days, avg20=avg20,
                regime=regime, nas_mom=nas_mom, gold_mom=gold_mom, nas_vol=nas_vol,
                gold_vol=gold_vol, cyb_vol=cyb_vol, cyb_llt=cyb_llt, cyb_below=cyb_below,
                cyb_drop=cyb_drop, risk_tickers=risk_tickers, def_tickers=def_tickers)
```

2. 把逐日循环体移入 `_daily_target(i, d, sig, params, last_def_update, current_defn)`，
   所有局部量改从 `sig` 读取，返回 `(target, last_def_update, current_defn)`。

3. 新增：

```python
def _combine_phases(phase_weights: list[pd.Series]) -> pd.Series:
    """五相位目标平滑：5 个相位等权汇总。"""
    return pd.concat(phase_weights, axis=1).mean(axis=1)
```

4. `build_weights` 收敛为编排层：

```python
def build_weights(params: dict, start: str, end: str) -> pd.DataFrame:
    """计算策略目标权重面板（index=回测交易日、columns=标的、每行和 ≤ 1）。"""
    close, opn, amt = load_prices()
    indices = load_indices()
    fb = load_fund_basic()
    cat = univ.classify(fb)
    days = calendar.trading_days(start, end)
    sig = _precompute_signals(close, opn, amt, indices, params, cat)

    nasdaq, gold = params["nasdaq_etf"], params["gold_etf"]
    cols = sorted(set([nasdaq, gold] + sig["risk_tickers"] + sig["def_tickers"]))
    phase_weights = [pd.Series(0.0, index=cols) for _ in range(5)]
    weights = pd.DataFrame(0.0, index=days, columns=cols)
    last_def_update = -10**9
    current_defn: list[str] = []

    for i, d in enumerate(days):
        target, last_def_update, current_defn = _daily_target(
            i, d, sig, params, last_def_update, current_defn)
        phase_weights[i % 5] = pd.Series(target).reindex(cols).fillna(0.0)
        weights.loc[d, cols] = _combine_phases(phase_weights).values

    return weights
```

注意：`_daily_target` 内的 `i >= 170`（风险池）与 `i >= 60`（防守仓）判断原样保留。

- [ ] **Step 5: 运行测试与回归对比**

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
.venv\Scripts\python.exe -c "import pandas as pd, json; assert pd.read_parquet('reports/weights.parquet').equals(pd.read_parquet('reports/weights.baseline.parquet')); assert json.load(open('reports/metrics.json')) == json.load(open('reports/metrics.baseline.json')); print('IDENTICAL')"
```

Expected: pytest 全绿，diff 输出 `IDENTICAL`。

- [ ] **Step 6: Commit**

```powershell
git add src/etf_rotation/pipeline.py tests/test_pipeline.py
git commit -m "refactor: split build_weights into precompute/daily/phase helpers"
```

---

## Task 2: 拆分 `_DailyWeights` 为现金计息 + `WeighTarget`

**Files:**
- Modify: `src/etf_rotation/backtest/run.py`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Removes: `_DailyWeights`
- Produces: `_CashInterest(bt.Algo)`；`run()` 内部算法链变为
  `[RunDaily(), _CashInterest(cash_rate), bt.algos.WeighTarget(w), bt.algos.Rebalance()]`

- [ ] **Step 1: 写失败测试**

在 `tests/test_backtest.py` 追加：

```python
def test_cash_interest_accrues():
    idx = pd.date_range("2024-01-01", periods=3)
    w = pd.DataFrame(0.0, index=idx, columns=["X"])
    close = pd.DataFrame([10.0, 10.0, 10.0], index=idx, columns=["X"])
    res = run.run(w, close, close, cost_bps=0, cash_rate=0.252)
    assert res["nav"].iloc[-1] > 1.0
    assert res["nav"].is_monotonic_increasing
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backtest.py -q`
Expected: FAIL（全现金但当前 `_DailyWeights` 只对 `target.capital` 计息一次/或断言不过）

- [ ] **Step 3: 实现**

将 `run.py` 中 `_DailyWeights` 替换为：

```python
class _CashInterest(bt.Algo):
    def __init__(self, cash_rate: float):
        super().__init__()
        self.daily = (1 + cash_rate) ** (1 / 252) - 1

    def __call__(self, target):
        if self.daily and not target.bankrupt:
            target.adjust(target.capital * self.daily, flow=False)
        return True
```

`run()` 中算法链改为：

```python
    strat = bt.Strategy(
        "etf_rotation",
        [bt.algos.RunDaily(), _CashInterest(cash_rate),
         bt.algos.WeighTarget(w), bt.algos.Rebalance()],
    )
```

其余（`ffill` / `reindex` / `mask(close_price.isna(), 0.0)` / 佣金回调 / 净值提取）保持不变。
说明：`WeighTarget` 设置 `temp['weights']`，`Rebalance` 按 `w_i × base` 分配、权重和 ≤1 的余额自动留现金，
与原先「归一化 + temp['cash']」等价；`w` 已 reindex 到 `close_price.index` 且 fillna(0)，故
`target.now in weights.index` 恒成立。

- [ ] **Step 4: 运行测试确认通过 + 回归**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_backtest.py -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
```

Expected: 测试全绿；`reports/metrics.json` 与 Task 1 后的基线一致（若已做 Task 3 前基线）。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/backtest/run.py tests/test_backtest.py
git commit -m "refactor: split cash interest from target-weight algo via WeighTarget"
```

---

## Task 3: 评估源切换为 bt 内置统计（唯一来源）

**Files:**
- Modify: `src/etf_rotation/backtest/run.py`、`src/etf_rotation/evaluation/metrics.py`
- Modify: `scripts/run_backtest.py`、`scripts/run_sensitivity.py`
- Test: `tests/test_metrics.py`、`tests/test_backtest.py`、`tests/test_integration.py`

**Interfaces:**
- Produces: `BacktestResult` dataclass（`nav, returns, stats, turnover, result`）
- Produces: `metrics.from_stats(stats: pd.Series) -> dict`
- Removes: `metrics.summary`

- [ ] **Step 1: 写失败测试**

将 `tests/test_metrics.py` 中的 `test_summary_known_series` 替换为：

```python
import math
import pandas as pd
import pytest

from etf_rotation.evaluation import metrics, overfitting


def test_from_stats_maps_bt_stats():
    a = math.sqrt(252)
    st = pd.Series({"cagr": 0.10, "daily_vol": 0.02, "daily_sharpe": 0.05,
                    "daily_sortino": 0.04, "max_drawdown": -0.20, "calmar": 0.5})
    s = metrics.from_stats(st)
    assert s["ann_return"] == 0.10
    assert s["ann_vol"] == pytest.approx(0.02 * a)
    assert s["sharpe"] == pytest.approx(0.05 * a)
    assert s["sortino"] == pytest.approx(0.04 * a)
    assert "var_95" not in s and "cvar_95" not in s


def test_dsr_high_for_many_bad_trials():
    p = overfitting.deflated_sharpe([0.5] * 100, 100)
    assert 0 <= p <= 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_metrics.py -q`
Expected: FAIL（`metrics` 无 `from_stats`）

- [ ] **Step 3: 实现 `from_stats` 与 `BacktestResult`**

`src/etf_rotation/evaluation/metrics.py` 整体替换为：

```python
"""回测指标：唯一来源是 bt/ffn 内置统计，不做自行推导。"""
from __future__ import annotations

import math

import pandas as pd


def from_stats(stats: pd.Series) -> dict:
    """bt Result.stats[name] → 报告口径。年化仅固定 ×sqrt(252)。"""
    a = math.sqrt(252)
    return {
        "ann_return": float(stats["cagr"]),
        "ann_vol": float(stats["daily_vol"]) * a,
        "sharpe": float(stats["daily_sharpe"]) * a,
        "sortino": float(stats["daily_sortino"]) * a,
        "max_drawdown": float(stats["max_drawdown"]),
        "calmar": float(stats["calmar"]),
    }
```

`src/etf_rotation/backtest/run.py` 顶部加：

```python
from dataclasses import dataclass


@dataclass
class BacktestResult:
    nav: pd.Series
    returns: pd.Series
    stats: pd.Series
    turnover: pd.Series
    result: bt.backtest.Result
```

`run()` 末尾改为：

```python
    backtest.run()
    result = bt.run(backtest)
    name = "etf_rotation"
    values = backtest.strategy.values.reindex(close_price.index).ffill()
    nav = values / values.iloc[0]
    returns = nav.pct_change(fill_method=None).fillna(nav.iloc[0] - 1)
    return BacktestResult(
        nav=nav, returns=returns,
        stats=result.stats[name], turnover=backtest.turnover, result=result,
    )
```

- [ ] **Step 4: 更新调用方**

`scripts/run_backtest.py`：

```python
    res = run.run(eff, opn, close,
                  cost_bps=p["costs"]["one_side_bps"],
                  cash_rate=p["costs"]["cash_rate_annual"])
    s = metrics.from_stats(res.stats)
    s["turnover"] = float(res.turnover.mean())
    ...
    pd.DataFrame({"nav": res.nav, "returns": res.returns}).to_csv(out / "equity.csv")
```

`scripts/run_sensitivity.py`：

```python
    for cost in [0, 8, 16, 24]:
        r = run.run(eff, opn, close, cost_bps=cost, cash_rate=0.018)
        s = metrics.from_stats(r.stats)
        sharpes.append(s["sharpe"])
        rows.append({"cost_bps": cost, "ann_return": s["ann_return"],
                     "max_drawdown": s["max_drawdown"], "sharpe": s["sharpe"],
                     "calmar": s["calmar"]})
```

`tests/test_backtest.py` 中 `res["nav"]` → `res.nav`；`tests/test_integration.py` 中
`res["nav"]`/`res["returns"]` → `res.nav`/`res.returns`，并把
`metrics.summary(res["returns"])` 改为 `metrics.from_stats(res.stats)`。

- [ ] **Step 5: 运行测试与基准回归**

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
.venv\Scripts\python.exe scripts\run_sensitivity.py
```

Expected: pytest 全绿；`metrics.json` 出现 `ann_return/ann_vol/sharpe/sortino/max_drawdown/calmar/turnover`，
不再有 `var_95/cvar_95`。记下新的 `sharpe/ann_vol` 数值（口径变为 `daily_* ×sqrt(252)`，见 Task 10 文档）。

- [ ] **Step 6: Commit**

```powershell
git add src/etf_rotation/backtest/run.py src/etf_rotation/evaluation/metrics.py scripts/run_backtest.py scripts/run_sensitivity.py tests/test_metrics.py tests/test_backtest.py tests/test_integration.py
git commit -m "refactor: use bt built-in stats as sole backtest metric source"
```

---

## Task 4: 参数覆盖与扁平化（1.1）

**Files:**
- Modify: `src/etf_rotation/config.py`、`scripts/run_backtest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.set_nested(params: dict, path: str, value: str) -> None`
- Produces: `config.flatten_params(params: dict) -> dict`

- [ ] **Step 1: 写失败测试**

`tests/test_config.py` 追加：

```python
def test_set_nested_and_flatten():
    p = config.load_params()
    config.set_nested(p, "dedupe.corr_threshold", "0.85")
    assert p["dedupe"]["corr_threshold"] == 0.85
    config.set_nested(p, "trend.windows", "[21, 63]")
    assert p["trend"]["windows"] == [21, 63]
    flat = config.flatten_params(p)
    assert flat["dedupe.corr_threshold"] == 0.85
    assert flat["trend.windows"] == [21, 63]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_config.py -q`
Expected: FAIL（`config` 无 `set_nested`）

- [ ] **Step 3: 实现**

`src/etf_rotation/config.py` 追加：

```python
def _coerce(value: str):
    """字符串值推断为 bool/int/float/list/dict，否则原样返回字符串。"""
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    if value[:1] in "[{":
        return yaml.safe_load(value)
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def set_nested(params: dict, path: str, value: str) -> None:
    """按 'a.b.c' 路径写入参数，自动推断类型。"""
    keys = path.split(".")
    node = params
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = _coerce(value)


def flatten_params(params: dict) -> dict:
    """平铺为点分键，便于 JSON 序列化与内容寻址。"""
    out = {}

    def walk(node: dict, prefix: str) -> None:
        for k, v in node.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                walk(v, key)
            else:
                out[key] = v

    walk(params, "")
    return out
```

`scripts/run_backtest.py` 改为 argparse：

```python
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("start", nargs="?", default="2019-01-01")
    parser.add_argument("end", nargs="?", default="2026-07-31")
    parser.add_argument("--param", action="append", default=[])
    args = parser.parse_args()

    p = config.load_params()
    for kv in args.param:
        k, v = kv.split("=", 1)
        config.set_nested(p, k, v)
    start, end = args.start, args.end
    ...
```

- [ ] **Step 4: 运行测试 + 冒烟**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_config.py -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --param dedupe.corr_threshold=0.85
```

Expected: 测试全绿；第二行不报错且打印出不同指标的 metrics（先观察是否运行成功，随后回滚到默认值不再深究）。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/config.py scripts/run_backtest.py tests/test_config.py
git commit -m "feat: add dotted-key param override and flatten_params"
```

---

## Task 5: 回测登记 registry（1.2，ml4t-registry-system）

**Files:**
- Create: `src/etf_rotation/evaluation/registry.py`
- Modify: `scripts/run_backtest.py`
- Test: `tests/test_registry.py`（新建）

**Interfaces:**
- Produces: `registry.config_hash(flat: dict) -> str`
- Produces: `registry.git_sha() -> str`
- Produces: `registry.register_run(db_path: Path, run_id: str, params: dict, metrics: dict, artifacts: dict) -> None`

- [ ] **Step 1: 写失败测试**

`tests/test_registry.py`：

```python
import json
from pathlib import Path

import duckdb

from etf_rotation.evaluation import registry


def test_config_hash_deterministic():
    assert registry.config_hash({"x": 1, "y": {"z": 2}}) == \
        registry.config_hash({"y": {"z": 2}, "x": 1})


def test_register_run_writes_rows(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = tmp_path / "r.duckdb"
    run_id = "abc123"
    report_root = tmp_path / "reports"
    registry.register_run(db, run_id, {"a": 1}, {"sharpe": 1.2},
                          {"equity": str(tmp_path / "e.csv")}, report_root=report_root)
    con = duckdb.connect(str(db))
    assert con.execute("SELECT count(*) FROM runs WHERE run_id=?", [run_id]).fetchone()[0] == 1
    assert con.execute("SELECT value FROM run_metrics WHERE run_id=? AND metric='sharpe'",
                       [run_id]).fetchone()[0] == 1.2
    con.close()
    manifest = json.loads((report_root / "runs" / run_id / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["equity"] == str(tmp_path / "e.csv")
```

说明：`register_run` 的 manifest 目录通过 `report_root` 参数传入（默认 `Path("reports")`），
测试用 `monkeypatch.chdir(tmp_path)` + 显式 `report_root` 隔离，避免污染仓库 `reports/`。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_registry.py -q`
Expected: FAIL（`registry` 模块不存在）

- [ ] **Step 3: 实现**

`src/etf_rotation/evaluation/registry.py`：

```python
"""回测登记：内容寻址 hash(params) → runs/run_metrics（ml4t-registry-system）。"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def config_hash(params: dict) -> str:
    blob = json.dumps(params, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def register_run(db_path: Path, run_id: str, params: dict, metrics: dict,
                 artifacts: dict, report_root: Path = Path("reports")) -> None:
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id VARCHAR PRIMARY KEY, spec_id VARCHAR NOT NULL, engine VARCHAR NOT NULL,
            origin VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL,
            data_snapshot_id VARCHAR NOT NULL, env_lock_hash VARCHAR NOT NULL,
            git_sha VARCHAR NOT NULL, params_json VARCHAR NOT NULL, status VARCHAR NOT NULL)
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS run_metrics (
            run_id VARCHAR NOT NULL, metric VARCHAR NOT NULL, value DOUBLE NOT NULL,
            PRIMARY KEY (run_id, metric))
    """)
    con.execute(
        "INSERT OR REPLACE INTO runs VALUES (?, 'etf-rotation', 'bt', 'run_backtest', ?, '', '', ?, ?, 'done')",
        [run_id, datetime.now(timezone.utc).isoformat(), git_sha(),
         json.dumps(params, sort_keys=True)],
    )
    for k, v in metrics.items():
        con.execute(
            "INSERT OR REPLACE INTO run_metrics (run_id, metric, value) VALUES (?, ?, ?)",
            [run_id, k, float(v)],
        )
    con.close()

    out = report_root / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "params": params, "metrics": metrics,
                    "artifacts": artifacts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
```

`scripts/run_backtest.py` 在写产物后登记：

```python
    from etf_rotation.evaluation import registry

    flat = config.flatten_params(p)
    flat["_start"], flat["_end"] = start, end
    run_id = registry.config_hash(flat)
    registry.register_run(
        ROOT / "data" / "warehouse.duckdb", run_id, flat, s,
        {"equity": str(out / "equity.csv"), "weights": str(out / "weights.parquet"),
         "benchmark": str(out / "benchmark.csv"), "metrics": str(out / "metrics.json")},
    )
    print(f"registered run {run_id}")
```

- [ ] **Step 4: 运行测试 + 两次登记验证**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_registry.py -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
.venv\Scripts\python.exe -c "import duckdb; con=duckdb.connect('data/warehouse.duckdb', read_only=True); print(con.execute('SELECT run_id, status FROM runs').fetchall()); print(con.execute('SELECT metric, value FROM run_metrics LIMIT 8').fetchall()); con.close()"
```

Expected: 测试全绿；`runs` 出现一行、`run_metrics` 出现本次各指标；`reports/runs/{run_id}/manifest.json` 存在。
再次运行相同命令，run_id 不变（幂等覆盖）。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/evaluation/registry.py scripts/run_backtest.py tests/test_registry.py
git commit -m "feat: add content-addressed run registry into warehouse duckdb"
```

---

## Task 6: 引擎化交易/持仓导出（run.1/2 + 1.3）

**Files:**
- Modify: `src/etf_rotation/evaluation/trades.py`、`scripts/run_backtest.py`、`scripts/run_report.py`
- Test: `tests/test_trades.py`、`tests/test_integration.py`

**Interfaces:**
- Produces: `trades.build_trade_table_from_engine(transactions: pd.DataFrame, cost_bps: float = 8.0) -> pd.DataFrame`
- Removes: `trades.build_trade_table`（权重差分的推导版）

- [ ] **Step 1: 写失败测试**

将 `tests/test_trades.py` 整体替换为：

```python
import pandas as pd
import pytest

from etf_rotation.evaluation import trades


def test_build_trade_table_from_engine():
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2024-01-02"), "A"), (pd.Timestamp("2024-01-02"), "B")],
        names=["Date", "Security"],
    )
    tx = pd.DataFrame({"price": [10.0, 20.0], "quantity": [1.0, -0.5]}, index=idx)
    t = trades.build_trade_table_from_engine(tx, cost_bps=8)
    assert len(t) == 2
    assert t.loc[t["ticker"] == "A", "side"].iloc[0] == "买入"
    assert t.loc[t["ticker"] == "B", "cost"].iloc[0] == pytest.approx(20.0 * 0.5 * 8 / 10000)
    assert set(t.columns) >= {"date", "ticker", "side", "price", "quantity", "notional", "cost"}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_trades.py -q`
Expected: FAIL（`build_trade_table_from_engine` 不存在）

- [ ] **Step 3: 实现**

`src/etf_rotation/evaluation/trades.py` 整体替换为：

```python
"""交易明细：以 bt 引擎 get_transactions() 为唯一依据。"""
from __future__ import annotations

import pandas as pd


def build_trade_table_from_engine(
    transactions: pd.DataFrame, cost_bps: float = 8.0
) -> pd.DataFrame:
    """bt get_transactions()（MultiIndex: Date×Security, cols=[price,quantity]）→ 交易明细。

    成本按引擎佣金回调同一公式 notional × bps / 10000 计算，与净值记账对得上。
    """
    tx = transactions.reset_index()
    tx.columns = ["date", "ticker", "price", "quantity"]
    tx["side"] = tx["quantity"].map(lambda q: "买入" if q > 0 else "卖出")
    tx["notional"] = (tx["price"] * tx["quantity"].abs()).round(6)
    tx["cost"] = (tx["notional"] * cost_bps / 10000.0).round(6)
    return tx[tx["quantity"].abs() > 0].reset_index(drop=True)[
        ["date", "ticker", "side", "price", "quantity", "notional", "cost"]
    ]
```

`scripts/run_backtest.py` 在 `res` 生成后落盘引擎产物：

```python
    res.result.get_transactions().reset_index().to_csv(out / "transactions.csv", index=False)
    res.result.get_weights().to_csv(out / "holdings.csv")
```

`scripts/run_report.py` 把 `t = trades.build_trade_table(weights, nav)` 改为：

```python
    tx = pd.read_csv(REPORTS / "transactions.csv", parse_dates=["Date"]).set_index(["Date", "Security"])
    t = trades.build_trade_table_from_engine(tx, cost_bps=params["costs"]["one_side_bps"])
```

`tests/test_integration.py` 把 `trades.build_trade_table(eff, res.nav)` 改为
`trades.build_trade_table_from_engine(res.result.get_transactions())`。

- [ ] **Step 4: 运行测试与全链路**

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
.venv\Scripts\python.exe scripts\run_report.py
```

Expected: 测试全绿；`reports/transactions.csv`、`reports/holdings.csv` 生成；
`reports/trades.csv` 的 `cost` 合计与 `回测报告.md` 中「合计成本」口径一致（引擎佣金同公式）。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/evaluation/trades.py scripts/run_backtest.py scripts/run_report.py tests/test_trades.py tests/test_integration.py
git commit -m "refactor: derive trades and holdings from bt engine results"
```

---

## Task 7: 数据 curation 进 warehouse（意见 1/2，阶段 2）

**Files:**
- Create: `scripts/curate_data.py`
- Modify: `src/etf_rotation/data/paths.py`、`src/etf_rotation/data/calendar.py`、`src/etf_rotation/pipeline.py`
- Test: `tests/test_calendar.py`（回退逻辑）、`tests/test_curate.py`

**Interfaces:**
- Produces: `paths.WAREHOUSE: Path`
- Produces: `curate.build_trading_calendar(bars: pd.DataFrame) -> pd.DataFrame`
- Produces: `pipeline._load_prices_from_bronze()`（原 `load_prices` 改名后的回退实现）
- `load_prices()` 优先读 warehouse，为空回退 bronze；`calendar.trading_days` 优先读 `trading_calendar`，为空回退 bars 去重。

- [ ] **Step 1: 写失败测试**

`tests/test_calendar.py` 追加：

```python
import duckdb
import pandas as pd

from etf_rotation.data import calendar


def test_trading_days_falls_back_when_warehouse_calendar_empty(tmp_path, monkeypatch):
    db = tmp_path / "w.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE trading_calendar (exchange VARCHAR, ts DATE, is_open BOOLEAN, "
                "session_close_utc TIMESTAMP, source VARCHAR, PRIMARY KEY (exchange, ts))")
    con.close()
    monkeypatch.setattr(calendar, "WAREHOUSE", db)
    days = calendar.trading_days("2024-01-02", "2024-01-05")
    assert isinstance(days, pd.DatetimeIndex)
    assert len(days) >= 1  # 回退到 bronze bars 去重
```

`tests/test_curate.py` 追加：

```python
def test_build_trading_calendar():
    bars = pd.DataFrame({"ts": pd.to_datetime(["2024-01-02", "2024-01-02", "2024-01-03"])})
    cal = curate.build_trading_calendar(bars)
    assert list(cal["ts"]) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert (cal["is_open"]).all()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_calendar.py tests/test_curate.py -q`
Expected: FAIL（`calendar.WAREHOUSE` / `curate.build_trading_calendar` 不存在）

- [ ] **Step 3: 实现**

`src/etf_rotation/data/paths.py` 追加：

```python
WAREHOUSE = _p("ETF_WAREHOUSE_DUCKDB", ROOT / "data/warehouse.duckdb")
```

`src/etf_rotation/data/curate.py` 追加：

```python
def build_trading_calendar(bars: pd.DataFrame) -> pd.DataFrame:
    ts = pd.Series(pd.to_datetime(bars["ts"]).dt.date.unique())
    return pd.DataFrame({
        "exchange": "SSE",
        "ts": pd.to_datetime(ts.sort_values()),
        "is_open": True,
        "session_close_utc": pd.NaT,
        "source": "tushare",
    })
```

`scripts/curate_data.py`（新建）核心逻辑：

```python
"""把 bronze parquet curation 进 warehouse（bars_daily / close_adj / trading_calendar / symbols）。"""
from __future__ import annotations
import duckdb
import pandas as pd
from etf_rotation.data import curate
from etf_rotation.data.paths import ADJ, BARS, SYMBOLS, WAREHOUSE


def _read(path):
    con = duckdb.connect()
    df = con.execute(f"SELECT * FROM read_parquet('{path.as_posix()}')").fetchdf()
    con.close()
    return df


def main(snapshot_id: str = "curated-1") -> None:
    bars = _read(BARS)
    adj = _read(ADJ)
    sym = _read(SYMBOLS)
    issues = curate.validate_ohlcv(bars)
    if any(v for v in issues.values()):
        print("WARNING data issues:", issues)

    m = bars.merge(adj, on=["symbol_id", "ts"], how="left")
    m["adj_factor"] = m.groupby("symbol_id")["adj_factor"].ffill().fillna(1.0)
    last = m.groupby("symbol_id")["adj_factor"].transform("last")
    m["close_adj"] = m["close"] * m["adj_factor"] / last
    m["amount"] = m["close"] * m["volume"] * 100

    con = duckdb.connect(str(WAREHOUSE))
    now = pd.Timestamp.now()
    bars_out = m[["symbol_id", "ts", "open", "high", "low", "close", "volume", "amount"]].copy()
    bars_out = bars_out.assign(currency="CNY", source="tushare", downloaded_at=now, snapshot_id=snapshot_id)
    close_out = m[["symbol_id", "ts", "close_adj", "adj_factor"]].copy()
    close_out = close_out.assign(method="backward-latest", available_utc=now, source="tushare", snapshot_id=snapshot_id)
    sym_out = sym[["symbol_id", "ticker"]].copy()
    sym_out = sym_out.assign(exchange="SSE", calendar="CN", currency="CNY")
    cal = curate.build_trading_calendar(bars)
    con.register("bars_out", bars_out); con.register("close_out", close_out)
    con.register("sym_out", sym_out); con.register("cal", cal)
    con.execute("DELETE FROM bars_daily WHERE snapshot_id=?", [snapshot_id])
    con.execute("DELETE FROM close_adj WHERE snapshot_id=?", [snapshot_id])
    con.execute("INSERT INTO bars_daily SELECT * FROM bars_out")
    con.execute("INSERT INTO close_adj SELECT * FROM close_out")
    con.execute("INSERT OR REPLACE INTO symbols (symbol_id, ticker, exchange, calendar, currency) "
                "SELECT symbol_id, ticker, exchange, calendar, currency FROM sym_out")
    con.execute("INSERT OR REPLACE INTO trading_calendar SELECT * FROM cal")
    con.close()
    print("curated", len(bars_out), "bars;", len(close_out), "close_adj")
```

`src/etf_rotation/pipeline.py`：把现有 `load_prices` 改名 `_load_prices_from_bronze`；新增：

```python
def load_prices():
    con = duckdb.connect(str(paths.WAREHOUSE))
    try:
        close_adj = con.execute(
            "SELECT s.ticker, c.ts, c.close_adj FROM close_adj c "
            "JOIN symbols s ON s.symbol_id = c.symbol_id").fetchdf()
        bars = con.execute(
            "SELECT s.ticker, b.ts, b.open, b.amount FROM bars_daily b "
            "JOIN symbols s ON s.symbol_id = b.symbol_id").fetchdf()
    finally:
        con.close()
    if close_adj.empty:
        return _load_prices_from_bronze()
    close = close_adj.pivot(index="ts", columns="ticker", values="close_adj").sort_index()
    opn = bars.pivot(index="ts", columns="ticker", values="open").sort_index()
    amt = bars.pivot(index="ts", columns="ticker", values="amount").sort_index()
    return close, opn, amt
```

注意在 `pipeline.py` 顶部补 `from etf_rotation.data import paths`。

`src/etf_rotation/data/calendar.py`：`trading_days` 先查 warehouse `trading_calendar`，空则回退原 bars 去重逻辑（把原实现移入 `_from_bars`）。
顶部加 `from etf_rotation.data.paths import WAREHOUSE`，并在 `trading_days` 内引用模块级 `WAREHOUSE`
（这样测试的 `monkeypatch.setattr(calendar, "WAREHOUSE", db)` 才能生效）。

- [ ] **Step 4: 运行 curation 与一致性核对**

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\curate_data.py
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
.venv\Scripts\python.exe -c "import pandas as pd, json; assert pd.read_parquet('reports/weights.parquet').equals(pd.read_parquet('reports/weights.baseline.parquet')); print('WEIGHTS IDENTICAL (bronze vs warehouse)')"
```

Expected: pytest 全绿；curation 打印行数；`weights.parquet` 与基线逐值一致。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/data/paths.py src/etf_rotation/data/curate.py src/etf_rotation/data/calendar.py src/etf_rotation/pipeline.py scripts/curate_data.py tests/test_calendar.py tests/test_curate.py
git commit -m "feat: curate bronze parquet into warehouse duckdb for prices/calendar"
```

---

## Task 8: 敏感性网格 + 稳健性分数 + 悬崖检测（3.1，ml4t-sensitivity-analysis）

**Files:**
- Modify: `src/etf_rotation/evaluation/sensitivity.py`
- Create: `scripts/run_grid.py`
- Test: `tests/test_sensitivity.py`（新建）

**Interfaces:**
- Produces: `sensitivity.robustness_score(results: pd.DataFrame, metric: str = "sharpe") -> float`
- Produces: `sensitivity.detect_cliffs(results: pd.DataFrame, params: list[str], metric: str = "sharpe") -> dict`

- [ ] **Step 1: 写失败测试**

`tests/test_sensitivity.py`：

```python
import pandas as pd

from etf_rotation.evaluation import sensitivity


def test_robustness_and_cliffs():
    r = pd.DataFrame({
        "lookback": [20, 21, 22, 20, 21, 22],
        "sharpe": [0.1, 1.5, 0.2, 0.3, 0.4, 0.5],
        "max_drawdown": [-0.1] * 6, "ann_return": [0.1] * 6, "calmar": [0.5] * 6,
    })
    assert sensitivity.robustness_score(r) == 1.0
    assert "lookback" in sensitivity.detect_cliffs(r, ["lookback"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_sensitivity.py -q`
Expected: FAIL（函数不存在）

- [ ] **Step 3: 实现**

`src/etf_rotation/evaluation/sensitivity.py` 追加：

```python
def robustness_score(results: pd.DataFrame, metric: str = "sharpe") -> float:
    """稳健性分数 = 网格中 metric > 0 的组合占比（ml4t-sensitivity-analysis）。"""
    return float((results[metric] > 0).mean())


def detect_cliffs(results: pd.DataFrame, params: list[str], metric: str = "sharpe") -> dict:
    """悬崖检测：相邻参数间 metric 变化 > 2×变化量标准差则标记（ml4t-sensitivity-analysis）。"""
    out = {}
    for p in params:
        s = results.sort_values(p)[metric]
        d = s.diff().abs()
        out[p] = {"cliff": bool(d.std() > 0 and d.max() > 2 * d.std()), "max_jump": float(d.max())}
    return out
```

`scripts/run_grid.py`（新建）：

```python
"""单参数网格敏感性：一次只变一个维度。用法示例：
scripts/run_grid.py --grid dedupe.corr_threshold=0.75,0.80,0.85
"""
from __future__ import annotations
import argparse, itertools, json
from pathlib import Path
from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.evaluation import metrics, overfitting, sensitivity
from etf_rotation.pipeline import build_weights, load_prices
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", action="append", required=True)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-07-31")
    args = ap.parse_args()

    grid = {}
    for spec in args.grid:
        k, v = spec.split("=", 1)
        grid[k] = [float(x) for x in v.split(",")]

    base = config.load_params()
    rows, sharpes = [], []
    for combo in itertools.product(*grid.values()):
        params = dict(zip(grid.keys(), combo))
        p = config.load_params()
        for k, val in params.items():
            config.set_nested(p, k, str(val))
        weights = build_weights(p, args.start, args.end)
        close, opn, _ = load_prices()
        close = close.reindex(index=weights.index, columns=weights.columns)
        opn = opn.reindex(index=weights.index, columns=weights.columns)
        eff = weights.shift(1).fillna(0.0)
        r = run.run(eff, opn, close,
                    cost_bps=p["costs"]["one_side_bps"],
                    cash_rate=p["costs"]["cash_rate_annual"])
        s = metrics.from_stats(r.stats)
        sharpes.append(s["sharpe"])
        rows.append({**params, "sharpe": s["sharpe"], "max_drawdown": s["max_drawdown"],
                     "ann_return": s["ann_return"], "calmar": s["calmar"]})

    n = len(rows)
    results = pd.DataFrame(rows)
    out = {
        "grid": grid, "results": rows, "n_trials": n,
        "robustness": sensitivity.robustness_score(results),
        "cliffs": sensitivity.detect_cliffs(results, list(grid)),
        "dsr": overfitting.deflated_sharpe(sharpes, n),
    }
    (ROOT / "reports" / "grid.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("n_trials", "robustness", "cliffs", "dsr")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试 + 单参数冒烟**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_sensitivity.py -q
.venv\Scripts\python.exe scripts\run_grid.py --grid dedupe.corr_threshold=0.75,0.80,0.85
```

Expected: 测试全绿；`reports/grid.json` 含 3 行结果 + robustness/cliffs/dsr。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/evaluation/sensitivity.py scripts/run_grid.py tests/test_sensitivity.py
git commit -m "feat: add grid sensitivity with robustness score and cliff detection"
```

---

## Task 9: 多重检验校正 + 样本外子区间（3.2，ml4t-backtest-overfitting）

**Files:**
- Modify: `src/etf_rotation/evaluation/overfitting.py`
- Test: `tests/test_metrics.py`（追加）

**Interfaces:**
- Produces: `overfitting.sharpe_haircut(sharpes: list[float]) -> dict`

- [ ] **Step 1: 写失败测试**

`tests/test_metrics.py` 追加：

```python
def test_sharpe_haircut_returns_expected_max():
    h = overfitting.sharpe_haircut([1.0, 1.1, 1.2, 1.3, 1.4])
    assert set(h) == {"observed_best", "expected_max", "haircut"}
    assert h["observed_best"] == pytest.approx(1.4)
    assert h["haircut"] == pytest.approx(h["observed_best"] - h["expected_max"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_metrics.py -q`
Expected: FAIL（`sharpe_haircut` 不存在）

- [ ] **Step 3: 实现**

`src/etf_rotation/evaluation/overfitting.py` 追加：

```python
def sharpe_haircut(sharpes) -> dict:
    """Sharpe 扣除选择上限（Bailey–López de Prado 近似）。年化口径。"""
    per = np.asarray(sharpes, dtype=float) / np.sqrt(252)
    n = len(per)
    euler = 0.5772156649
    sd = per.std(ddof=1)
    e_max_per = sd * (
        (1 - euler) * stats.norm.ppf(1 - 1 / n)
        + euler * stats.norm.ppf(1 - 1 / (n * np.e))
    )
    a = np.sqrt(252)
    observed = float(per.max() * a)
    expected = float(e_max_per * a)
    return {"observed_best": observed, "expected_max": expected, "haircut": observed - expected}
```

- [ ] **Step 4: 样本外子区间（命令步骤，不新增代码）**

选定时任一候选参数后，跑两个子区间（规则驱动无训练集，用时间子区间近似 OOS）：

```powershell
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2023-12-31
.venv\Scripts\python.exe scripts\run_backtest.py 2024-01-01 2026-07-31
```

记录两个子区间的 `sharpe/max_drawdown/calmar`，写入 Task 10 的 `reports/回测报告.md`。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/evaluation/overfitting.py tests/test_metrics.py
git commit -m "feat: add sharpe haircut for multiple-testing correction"
```

---

## Task 10: 文档与差异说明更新

**Files:**
- Modify: `reports/回测报告.md`、`TODO.md`（若存在待办清单）

- [ ] **Step 1: 更新 `reports/回测报告.md` 的「已知差异」**

新增/替换以下条目：

- 指标口径：Sharpe/Sortino/年化波动改为 bt 内置统计 `daily_* ×sqrt(252)`，CAGR/MaxDD/Calmar 直接用 ffn 值；不再输出 VaR/CVaR。
- 换手口径：由 bt `Backtest.turnover` 引擎序列取均值，替代原权重差分口径。
- 交易明细/成本：由 bt `get_transactions()` 引擎成交推导，成本与引擎佣金同公式。
- 技术指标：不引入 pandas-ta-classic，自定义动量分/LLT/EWMA 保持手写并单测（决策说明）。
- 五相位：明确为「目标平滑」（5 相位等权汇总、单账户），不使用 bt 策略树；若未来改为独立资金子账户再启用策略树。
- 未接入主线的反转/整组迟滞/跳空顺延/单 ETF 过热退出/34% 组合波动目标：保持已知简化，单独立项。

- [ ] **Step 2: 更新 `TODO.md`**

把「阶段 B 参数搜索」「执行精度（T+1 开盘 + 跳空 + 停牌）」按本计划状态勾选或标注「另立」。

- [ ] **Step 3: Commit**

```powershell
git add reports/回测报告.md TODO.md
git commit -m "docs: record metric-source change and outstanding simplifications"
```

---

## 执行顺序与依赖

Task 1 → 2 → 3（指标源切换）→ 4 → 5 → 6（引擎导出）→ 7（数据 curation）→ 8 → 9（敏感性）→ 10（文档）。
其中 Task 6 依赖 Task 3 的 `BacktestResult.result`；Task 5 依赖 Task 4 的 `flatten_params`；
Task 8/9 依赖 Task 3 的 `metrics.from_stats` 与 Task 4 的参数覆盖。Task 1/2/3 均为行为不变或仅口径变化的重构，
完成后先确认净值/权重与基线一致，再进入改变结果的阶段。
