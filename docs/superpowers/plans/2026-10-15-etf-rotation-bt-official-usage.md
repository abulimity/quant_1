# bt 官方用法收敛 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把回测层中绕过 bt 官方接口、或未按推荐写法使用的部分收敛到框架内，数值上尽量保持现状（同量级、可复现），并补齐 cash/positions/fees 的可审计口径。

**Architecture:** 保持“策略目标权重在 bt 外预计算、喂给 `WeighTarget`”的既有模式不变；本次只整改回测记账、结果读取、费用口径与基准记账。策略/信号/组合层（LLT、动量、去重、HRP、五相位等）bt 不提供对应原语，维持自研不动。

**Tech Stack:** Python 3.10、bt 1.2.2（`<=1.2.2` 已锁定）、pandas、pytest、ffn（随 bt 内置）。

**Spec:** `docs/superpowers/specs/2026-10-10-etf-rotation-design.md`（策略设计）；整改依据为对 bt 官方文档与源码的核查结论（见本轮对话审计）。

## Global Constraints

- 所有 Python 统一用 `.venv\Scripts\python.exe` 运行。
- 运行任何 Python 前先 `$env:PYTHONIOENCODING="utf-8"`（Windows GBK）。
- bt 版本锁定 `bt>=1.0,<=1.2.2`；不改依赖版本，不加新依赖。
- 回测引擎用 bt，不满足策略需求时才允许自研；本次只收敛“bt 已提供但被绕过/误用”的部分。
- T 日信号、T+1 成交；滚动统计量一律 `.shift(1)`；禁止未来信息。
- 每次调整后跑 `.venv\Scripts\python.exe -m pytest tests -q`，没跑命令不下结论（verification-before-completion）。
- `.env` 的 tushare token 不得打印/提交/写日志。
- 一次只动一个维度；本计划是“口径/用法收敛”，不改变策略参数。
- 当前分支 master，按语义化 commit；任务边界就是提交边界。

---

## 任务依赖与执行顺序

任务 1 → 2 → 3 → 4 → 5 → 6 顺序执行。任务 1–5 都改 `src/etf_rotation/backtest/run.py`，必须按序应用；任务 6 会把 `run` 拆成 `_run_backtest` + `run_panel`，并改 `pipeline.py` 与 `scripts/run_backtest.py`。

说明：任务 1/3/4 属于“行为不变的纯重构”，TDD 用“特征化/回归测试”锁定现状，先绿后改，不强行伪造红；任务 2/5/6 含新接口或新行为，先写会失败的测试。

### Task 1: 回测入口收敛（单次 bt.run + 佣金抽函数 + 名称不硬编码）

**Files:**
- Modify: `src/etf_rotation/backtest/run.py:45-69`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Produces: `_flat_commission(cost_bps: float) -> Callable[[float, float], float]`，供后续任务与 `_run_backtest` 复用。

- [ ] **Step 1: 写失败测试**

在 `tests/test_backtest.py` 顶部把 import 改为：

```python
import pandas as pd
import pytest

from etf_rotation.backtest import run
from etf_rotation.backtest.run import _flat_commission
```

文件末尾新增：

```python
def test_flat_commission_formula():
    fn = _flat_commission(8)
    assert fn(100, 2.0) == pytest.approx(100 * 2.0 * 8 / 10000.0)
    assert fn(-100, 2.0) == pytest.approx(100 * 2.0 * 8 / 10000.0)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backtest.py::test_flat_commission_formula -v`
Expected: FAIL，`ImportError: cannot import name '_flat_commission'`。

- [ ] **Step 3: 实现 `_flat_commission` 并收敛入口**

在 `src/etf_rotation/backtest/run.py` 的 `BacktestResult` 之后新增：

```python
def _flat_commission(cost_bps: float):
    """单边比例佣金回调：|q| * p * bps / 1e4。

    bt.Backtest 的 commissions 参数支持 callable（官方文档中的
    "original flat hook"）；本策略是规则驱动、名义本金归一、单边 bps 假设，
    无成交量/波动率冲击建模需求，故保留平铺回调，不引入 CostModel。
    """
    def commission(q, p):
        return abs(q) * p * cost_bps / 10000.0

    return commission
```

把 `run()` 中的策略构造段改为：

```python
    strat = bt.Strategy(
        "etf_rotation",
        [bt.algos.RunDaily(), _CashInterest(cash_rate),
         bt.algos.WeighTarget(w), bt.algos.Rebalance()],
    )
    backtest = bt.Backtest(
        strat,
        close_price,
        initial_capital=1.0,
        commissions=_flat_commission(cost_bps),
        integer_positions=False,
        progress_bar=False,
    )
    result = bt.run(backtest)
    name = backtest.name
```

删除原来的 `commission = lambda q, p: ...` 行、`backtest.run()` 行，并把硬编码的 `name = "etf_rotation"` 删除（上面已用 `backtest.name` 代替）。

同时把 `_CashInterest.__call__` 的注释补一句官方语义引用：

```python
        # 闲置现金按年化计息：adjust(flow=False) 是 bt 官方文档中
        # "commission / dividend 类非资金流收入" 的记账原语，计入净值而非资金流。
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backtest.py -q`
Expected: PASS（`test_flat_commission_formula` 及既有两个测试全绿）。

- [ ] **Step 5: Commit**

```bash
git add src/etf_rotation/backtest/run.py tests/test_backtest.py
git commit -m "refactor: single bt.run entry, extract flat commission, use backtest.name"
```

### Task 2: BacktestResult 暴露引擎 cash / positions / fees

**Files:**
- Modify: `src/etf_rotation/backtest/run.py:18-24`（dataclass）与 `run()` 返回值
- Test: `tests/test_backtest.py`

**Interfaces:**
- Produces: `BacktestResult.cash: pd.Series`、`BacktestResult.positions: pd.DataFrame`、`BacktestResult.fees: pd.Series`，索引均对齐到真实交易日。

- [ ] **Step 1: 写失败测试**

`tests/test_backtest.py` 新增：

```python
def test_result_exposes_engine_cash_positions_fees():
    idx = pd.date_range("2024-01-01", periods=30)
    w = pd.DataFrame({"X": 0.5, "Y": 0.5}, index=idx)
    close = pd.DataFrame(
        {"X": pd.Series(10.0, index=idx) + pd.Series(range(30), index=idx) * 0.1,
         "Y": 20.0 - pd.Series(range(30), index=idx) * 0.05},
        index=idx,
    )
    res = run.run(w, close, close, cost_bps=8, cash_rate=0.018)
    assert res.cash.index.equals(close.index)
    assert res.positions.index.equals(close.index)
    assert res.fees.index.equals(close.index)
    assert set(res.positions.columns) == {"X", "Y"}
    assert res.fees.sum() > 0
    assert (res.cash >= 0).all()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backtest.py::test_result_exposes_engine_cash_positions_fees -v`
Expected: FAIL，`AttributeError: 'BacktestResult' object has no attribute 'cash'`。

- [ ] **Step 3: 扩展 dataclass 并填充字段**

`BacktestResult` 改为：

```python
@dataclass
class BacktestResult:
    nav: pd.Series
    returns: pd.Series
    stats: pd.Series
    turnover: pd.Series
    cash: pd.Series
    positions: pd.DataFrame
    fees: pd.Series
    result: bt.backtest.Result
```

`run()` 末尾 return 前增加对齐（`trading_index` 即真实交易日，用于去掉 bt 注入的 t0-1 bootstrap 行）：

```python
    trading_index = close_price.index
    cash = backtest.strategy.cash.reindex(trading_index)
    fees = backtest.strategy.fees.reindex(trading_index)
    positions = backtest.positions.reindex(trading_index)
```

return 改为：

```python
    return BacktestResult(
        nav=nav,
        returns=returns,
        stats=result.stats[name],
        turnover=turnover,
        cash=cash,
        positions=positions,
        fees=fees,
        result=result,
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backtest.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/etf_rotation/backtest/run.py tests/test_backtest.py
git commit -m "feat: expose engine cash, positions and fees in BacktestResult"
```

### Task 3: 净值/收益改用 Result.prices

**Files:**
- Modify: `src/etf_rotation/backtest/run.py:71-73`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `bt.backtest.Result.prices`（ffn GroupStats 的价格指数，起点 PAR=100）。
- Produces: `BacktestResult.nav`、`BacktestResult.returns`，行为与现状一致，但来源统一为 `result.prices`。

- [ ] **Step 1: 加特征化测试锁定现状**

在 `tests/test_backtest.py` 顶部 import 区加入：

```python
import numpy as np
```

`tests/test_backtest.py` 新增：

```python
def test_nav_uses_result_prices():
    idx = pd.date_range("2024-01-01", periods=60)
    rng = np.random.default_rng(0)
    close = pd.DataFrame(
        {"A": np.cumprod(1 + rng.normal(0, 0.008, 60)),
         "B": np.cumprod(1 + rng.normal(0, 0.006, 60))},
        index=idx,
    )
    w = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    eff = w.shift(1).fillna(0.0)
    res = run.run(eff, close, close, cost_bps=8, cash_rate=0.018)
    official = res.result.prices["etf_rotation"].reindex(close.index)
    pd.testing.assert_series_equal(res.nav, official / official.iloc[0], rtol=1e-12, atol=1e-12)
```

- [ ] **Step 2: 运行确认基线绿**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backtest.py::test_nav_uses_result_prices -v`
Expected: PASS（本测试在现状下也应通过，只用于锁定等价性）。

- [ ] **Step 3: 替换自算净值**

把 `run()` 中这三行：

```python
    values = backtest.strategy.values.reindex(close_price.index).ffill()
    nav = values / values.iloc[0]
    returns = nav.pct_change(fill_method=None).fillna(nav.iloc[0] - 1)
```

替换为：

```python
    # 官方净值曲线：Result.prices 即 ffn GroupStats 的价格指数（起点 PAR=100）。
    # 只丢弃 bt 在 t0-1 注入的 bootstrap 行，保持输出索引与真实交易日一致。
    prices = result.prices[name].reindex(close_price.index)
    nav = prices / prices.iloc[0]
    returns = nav.pct_change(fill_method=None).fillna(nav.iloc[0] - 1)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backtest.py tests/test_integration.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/etf_rotation/backtest/run.py tests/test_backtest.py
git commit -m "refactor: derive nav and returns from Result.prices"
```

### Task 4: WeighTarget 改为传名 + additional_data

**Files:**
- Modify: `src/etf_rotation/backtest/run.py:52-66`
- Test: `tests/test_backtest.py`

**Interfaces:**
- Consumes: `bt.algos.WeighTarget("target_weights")` 经 `target.get_data("target_weights")` 读取。
- Produces: `bt.Backtest(..., additional_data={"target_weights": w})`。

- [ ] **Step 1: 加特征化测试锁定等价性**

`tests/test_backtest.py` 新增：

```python
def test_weigh_target_binds_by_name():
    idx = pd.date_range("2024-01-01", periods=5)
    w = pd.DataFrame(1.0, index=idx, columns=["X"])
    close = pd.DataFrame({"X": [10.0, 11.0, 12.0, 13.0, 14.0]}, index=idx)
    res = run.run(w.shift(1).fillna(0.0), close, close, cost_bps=0, cash_rate=0)
    assert abs(res.nav.iloc[-1] - 14.0 / 11.0) < 1e-9
```

- [ ] **Step 2: 运行确认基线绿**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backtest.py::test_weigh_target_binds_by_name -v`
Expected: PASS（现状下应通过）。

- [ ] **Step 3: 改为按名传数**

把：

```python
         bt.algos.WeighTarget(w), bt.algos.Rebalance()],
```

改为：

```python
         bt.algos.WeighTarget("target_weights"), bt.algos.Rebalance()],
```

并在 `bt.Backtest(...)` 增加：

```python
        additional_data={"target_weights": w},
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backtest.py tests/test_integration.py -q`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/etf_rotation/backtest/run.py tests/test_backtest.py
git commit -m "refactor: pass target weights to WeighTarget by name"
```

### Task 5: 交易成本以引擎 fees 为权威口径

**Files:**
- Modify: `src/etf_rotation/evaluation/trades.py:14-18`
- Modify: `scripts/run_backtest.py:42-44`（写 `total_fees`）
- Modify: `scripts/run_report.py:94-97`（报告合计成本读 fees）
- Test: `tests/test_backtest.py`、`tests/test_trades.py`

**Interfaces:**
- Consumes: `BacktestResult.fees`（Task 2）。
- Produces: `trades.build_trade_table_from_engine` 的 `cost` 不再逐行 round，能与 `fees.sum()` 精确对账；`metrics.json` 增加 `total_fees`。

- [ ] **Step 1: 写失败测试**

`tests/test_backtest.py` 新增：

```python
from etf_rotation.evaluation import trades

def test_trade_cost_reconciles_with_engine_fees():
    idx = pd.date_range("2024-01-01", periods=60)
    rng = np.random.default_rng(0)
    close = pd.DataFrame(
        {"A": np.cumprod(1 + rng.normal(0, 0.008, 60)),
         "B": np.cumprod(1 + rng.normal(0, 0.006, 60))},
        index=idx,
    )
    w = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    eff = w.shift(1).fillna(0.0)
    res = run.run(eff, close, close, cost_bps=8, cash_rate=0.018)
    t = trades.build_trade_table_from_engine(res.result.get_transactions(), cost_bps=8)
    assert t["cost"].sum() == pytest.approx(res.fees.sum(), abs=1e-9)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backtest.py::test_trade_cost_reconciles_with_engine_fees -v`
Expected: FAIL（现状逐行 `round(6)` 造成约 1e-7 的累计漂移）。

- [ ] **Step 3: 取消逐行舍入**

把 `trades.py` 中：

```python
    tx["notional"] = (tx["price"] * tx["quantity"].abs()).round(6)
    tx["cost"] = (tx["notional"] * cost_bps / 10000.0).round(6)
```

改为：

```python
    tx["notional"] = tx["price"] * tx["quantity"].abs()
    tx["cost"] = tx["notional"] * cost_bps / 10000.0
```

- [ ] **Step 4: 在 metrics 中落 total_fees**

`scripts/run_backtest.py` 中，在 `s["turnover"] = ...` 之后加：

```python
    s["total_fees"] = float(res.fees.sum())
```

- [ ] **Step 5: 报告合计成本读引擎 fees**

`scripts/run_report.py` 的 `_build_md` 中，把“合计成本”行改为读 `metrics`：

```python
    fees = metrics.get("total_fees")
```

并把：

```python
        f"- [交易明细 CSV](trades.csv)：共 {len(t)} 笔，买入 {(t['side'] == '买入').sum()} 笔 / "
        f"卖出 {(t['side'] == '卖出').sum()} 笔，合计成本 {t['cost'].sum():.4f}（引擎成交口径）",
```

改为：

```python
        f"- [交易明细 CSV](trades.csv)：共 {len(t)} 笔，买入 {(t['side'] == '买入').sum()} 笔 / "
        f"卖出 {(t['side'] == '卖出').sum()} 笔，合计成本 {fees:.4f}（引擎 fees 口径，"
        f"逐笔估算合计 {t['cost'].sum():.4f}）",
```

- [ ] **Step 6: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backtest.py tests/test_trades.py -q`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add src/etf_rotation/evaluation/trades.py scripts/run_backtest.py scripts/run_report.py tests/test_backtest.py tests/test_trades.py
git commit -m "refactor: reconcile trade costs against engine fees"
```

### Task 6: 基准与沪深300 改由 bt 引擎记账

**Files:**
- Modify: `src/etf_rotation/backtest/run.py`（拆出 `_run_backtest`，新增 `run_panel`）
- Modify: `src/etf_rotation/pipeline.py:309-333`（`compute_benchmark` → `build_benchmark_panels`）
- Modify: `scripts/run_backtest.py:48-49`（基准经引擎产出）
- Test: `tests/test_backtest.py`、`tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 1–5 的 `run.py`。
- Produces: `run.run_panel(name: str, weights: pd.DataFrame, close_price: pd.DataFrame, cost_bps: float = 0.0, cash_rate: float = 0.0) -> BacktestResult`；`pipeline.build_benchmark_panels(params: dict, start: str, end: str) -> dict[str, pd.DataFrame]`，键为 `bench_weights`、`bench_close`、`hs300_weights`、`hs300_close`。

- [ ] **Step 1: 写失败测试**

`tests/test_backtest.py` 新增：

```python
def test_run_panel_single_security():
    idx = pd.date_range("2024-01-01", periods=4)
    w = pd.DataFrame(1.0, index=idx, columns=["X"])
    close = pd.DataFrame({"X": [10.0, 11.0, 12.0, 13.0]}, index=idx)
    res = run.run_panel("benchmark", w.shift(1).fillna(0.0), close)
    assert res.result.backtest_list[0].name == "benchmark"
    assert abs(res.nav.iloc[-1] - 13.0 / 11.0) < 1e-9
```

`tests/test_pipeline.py` 新增：

```python
import numpy as np
import pandas as pd

import etf_rotation.pipeline as pipe


def test_build_benchmark_panels_equal_weight(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=25)
    base = pd.Series(np.linspace(10, 12, 25), index=idx)
    close = pd.DataFrame({"A": base, "B": base * 2}, index=idx)
    amt = pd.DataFrame({"A": 1e7, "B": 1e7}, index=idx)
    monkeypatch.setattr(pipe, "load_prices", lambda: (close, close.shift(1), amt))
    monkeypatch.setattr(pipe, "load_indices",
                        lambda: {"000300.SH": pd.Series(np.linspace(3000, 3030, 25), index=idx)})
    fb = pd.DataFrame({"ts_code": ["A", "B"], "name": ["x", "y"],
                       "fund_type": ["股票型", "股票型"]})
    monkeypatch.setattr(pipe, "load_fund_basic", lambda: fb)
    monkeypatch.setattr(pipe.calendar, "trading_days", lambda s, e: idx)
    params = {"universe": {"min_listed_days": 1, "min_avg_amount20": 1_000_000}}
    out = pipe.build_benchmark_panels(params, "2024-01-01", "2024-01-24")
    assert out["bench_weights"].iloc[-1].round(6).tolist() == [0.5, 0.5]
    assert out["hs300_weights"].columns.tolist() == ["000300.SH"]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backtest.py::test_run_panel_single_security tests/test_pipeline.py::test_build_benchmark_panels_equal_weight -v`
Expected: FAIL（`run_panel` 不存在；`build_benchmark_panels` 不存在）。

- [ ] **Step 3: run.py 拆出 `_run_backtest` 与 `run_panel`**

把 `run()` 的主体逻辑移入私有函数，最终 `src/etf_rotation/backtest/run.py` 的关键部分为：

```python
def _run_backtest(name: str, weights: pd.DataFrame, close_price: pd.DataFrame,
                  cost_bps: float, cash_rate: float) -> BacktestResult:
    close_price = close_price.ffill()
    w = weights.reindex(index=close_price.index, columns=close_price.columns).fillna(0.0)
    w = w.mask(close_price.isna(), 0.0)
    active = w.columns[(w > 0).any(axis=0)]
    w = w[active]
    close_price = close_price[active]
    strat = bt.Strategy(
        name,
        [bt.algos.RunDaily(), _CashInterest(cash_rate),
         bt.algos.WeighTarget("target_weights"), bt.algos.Rebalance()],
    )
    backtest = bt.Backtest(
        strat,
        close_price,
        initial_capital=1.0,
        commissions=_flat_commission(cost_bps),
        integer_positions=False,
        progress_bar=False,
        additional_data={"target_weights": w},
    )
    result = bt.run(backtest)
    name = backtest.name
    prices = result.prices[name].reindex(close_price.index)
    nav = prices / prices.iloc[0]
    returns = nav.pct_change(fill_method=None).fillna(nav.iloc[0] - 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
        turnover = backtest.turnover
    return BacktestResult(
        nav=nav,
        returns=returns,
        stats=result.stats[name],
        turnover=turnover,
        cash=backtest.strategy.cash.reindex(close_price.index),
        positions=backtest.positions.reindex(close_price.index),
        fees=backtest.strategy.fees.reindex(close_price.index),
        result=result,
    )


def run(weights, open_price, close_price, cost_bps=8, cash_rate=0.018):
    """策略回测入口。open_price 为预留形参（见 TODO 8.3，T+1 开盘未接入）。"""
    return _run_backtest("etf_rotation", weights, close_price, cost_bps, cash_rate)


def run_panel(name, weights, close_price, cost_bps=0.0, cash_rate=0.0):
    """通用单面板回测（基准/指数等），复用与策略相同的 bt 记账与费用语义。"""
    return _run_backtest(name, weights, close_price, cost_bps, cash_rate)
```

- [ ] **Step 4: pipeline 改为产出基准面板**

把 `src/etf_rotation/pipeline.py` 的 `compute_benchmark` 整体替换为：

```python
def build_benchmark_panels(params: dict, start: str, end: str) -> dict:
    """产出等权可投资风险池与沪深300 的目标权重面板 + 收盘价面板。

    面板交给 run.run_panel（cost_bps=0, cash_rate=0）记账，T+1 生效由调用方
    `weights.shift(1)` 完成，与策略同口径。
    """
    close, _, amt = load_prices()
    indices = load_indices()
    fb = load_fund_basic()
    cat = univ.classify(fb)
    days = calendar.trading_days(start, end)

    n_days = close.notna().cumsum()
    avg20 = amt.rolling(20).mean()
    risk = [t for t, c in cat.items() if c == "risk" and t in close.columns]

    elig = (n_days[risk] >= params["universe"]["min_listed_days"]) & (
        avg20[risk] >= params["universe"]["min_avg_amount20"]
    )
    denom = elig.sum(axis=1)
    bench_weights = elig.div(denom, axis=0).where(denom > 0, 0.0)
    bench_weights = bench_weights.reindex(days).fillna(0.0)
    bench_close = close[risk].reindex(days)

    hs = indices.get("000300.SH").reindex(days)
    hs300_weights = pd.DataFrame(1.0, index=days, columns=["000300.SH"])
    hs300_close = hs.to_frame("000300.SH")
    return {
        "bench_weights": bench_weights,
        "bench_close": bench_close,
        "hs300_weights": hs300_weights,
        "hs300_close": hs300_close,
    }
```

- [ ] **Step 5: run_backtest 经引擎写基准**

`scripts/run_backtest.py` 顶部把 `compute_benchmark` 替换为 `build_benchmark_panels`：

```python
from etf_rotation.pipeline import build_benchmark_panels, build_weights, load_prices
```

把：

```python
    compute_benchmark(p, start, end).to_csv(out / "benchmark.csv")
```

替换为：

```python
    panels = build_benchmark_panels(p, start, end)
    bench_res = run.run_panel(
        "benchmark",
        panels["bench_weights"].shift(1).fillna(0.0),
        panels["bench_close"],
        cost_bps=0.0,
        cash_rate=0.0,
    )
    hs300_res = run.run_panel(
        "hs300",
        panels["hs300_weights"].shift(1).fillna(0.0),
        panels["hs300_close"],
        cost_bps=0.0,
        cash_rate=0.0,
    )
    pd.DataFrame({"benchmark": bench_res.nav, "hs300": hs300_res.nav}).to_csv(out / "benchmark.csv")
```

- [ ] **Step 6: 运行测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_backtest.py tests/test_pipeline.py -q`
Expected: PASS。

- [ ] **Step 7: 全量回归**

Run: `.venv\Scripts\python.exe -m pytest tests -q`
Expected: PASS；如 `test_integration.py` 或其他测试引用了 `compute_benchmark`，同步改为新接口后再跑。

- [ ] **Step 8: 基准回测冒烟**

Run:

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
```

Expected: 正常产出 `reports/metrics.json`、`reports/equity.csv`、`reports/benchmark.csv`；`metrics.json` 中出现 `total_fees`，`benchmark.csv` 含 `benchmark`、`hs300` 两列。

- [ ] **Step 9: Commit**

```bash
git add src/etf_rotation/backtest/run.py src/etf_rotation/pipeline.py scripts/run_backtest.py tests/test_backtest.py tests/test_pipeline.py
git commit -m "refactor: run benchmark and hs300 through the bt engine"
```

---

## 不在本次执行范围（单列后续计划）

这些项要么会改变策略数值、要么是纯内部重复/死代码清理，和本次“bt 官方用法收敛”不是同一评审单位，建议单独立项：

- 现金计息是否改为“现金资产”（`cash` 列价格按 `(1+rf/252)` 日复利、权重补 `1-Σw`）：当前保留 `_CashInterest`（官方 `adjust(flow=False)` 原语）并已导出 `cash`；若要严格框架化再单独评估，避免为形式引入现金侧换手噪声。
- 持仓可视化现金口径改为引擎 `backtest.strategy.cash / nav`：本次已把 `cash` 导出到 `BacktestResult`（Task 2），但 `plots.holdings_distribution` 仍用 `1 - w.sum(axis=1)` 从目标权重推断现金；图表层接入引擎现金单独做，避免本次计划同时改图接口。
- 组合 34% 目标波动接入主线：使用 `bt.algos.TargetVol`（lookback/lag/covar_method/annualization_factor），不再自研组合层缩放；现有 `risk_layers.vol_scale` 是“只缩不放”封顶语义，需先和设计文档确认目标波动是“目标”还是“上限”。
- 五相位两套实现：`pipeline._combine_phases` 与 `execution/phases.combine`（未接入）二选一。
- 动量两套实现：`signals/trend.momentum_score`（循环）与 `pipeline.momentum_panel`（向量化）收敛为一套，并加等价性测试。
- `universe.build_pool` 与 `pipeline._daily_target` 内联的可投资池过滤重复，二选一。
- `weights.shift(1).fillna(0)` 在 `run_backtest.py`/`run_sensitivity.py`/`run_grid.py` 三处重复，抽到 `execution` 公共函数。
- 已写未接线的 `hysteresis`/`gap_delay`/`reversal`/`overheat_mask`：标记为“待接线”，并补齐接入计划或删除。

## 执行结果（2026-10-16）

执行方式：Subagent-Driven Development；审查子代理不可用后，审查由 controller 直接完成。执行与裁定记录见
`.superpowers/sdd/2026-10-15-etf-rotation-bt-official-usage/progress.md`（gitignored，不随分支提交）。

- Task 1 完成：`311cd87` refactor: single bt.run entry, extract flat commission, use backtest.name。
- Task 2 完成：`4758571` feat: expose engine cash, positions and fees in BacktestResult；后续 `f6272f0` 屏蔽 positions 碎片化警告。
- Task 3 完成：`35fa003` refactor: derive nav and returns from Result.prices。
- Task 4 完成：`97f3620` refactor: pass target weights to WeighTarget by name。
- Task 5 完成：`0850576` refactor: reconcile trade costs against engine fees（`metrics.json` 新增 `total_fees`）。
- Task 6 否决并回退：基准/沪深300 经 bt 引擎记账实测出现严重性能回退与 `PerformanceWarning` 洪水（7 分钟未完成，旧向量化秒级），保留向量化 `compute_benchmark`。
- 验证：全量 `pytest tests -q` 46 passed；`scripts/run_backtest.py 2019-01-01 2026-07-31` 成功，指标与基线一致（年化 12.48%、total_fees 0.2414）。
