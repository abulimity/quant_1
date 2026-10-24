# 回测报告派生数据（N1–N13）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为回测报告补齐 13 项派生计算（基准对齐、水下/回撤事件、相对指标、调仓事件、成本拖累、目标 vs 实际、单笔往返、阶段归因、极端日、滑点、容量、剔除防守相关性），并把结果落成前端可直接消费的 `reports/derived/*.json`。

**Architecture:** 新增 `etf_rotation.report` 包：`ReportContext` 一次性加载所有报告产物，`steps/` 下每个模块只负责一类派生指标，`runner` 自动发现并写 `reports/derived/<step>.json`，单步失败不拖垮其他步骤。派生层只读回测产物、不改变任何策略数值；唯一例外是 N1 修基准对齐（只改 `benchmark.csv`，不改净值/持仓/指标）。

**Tech Stack:** Python 3.10、pandas、numpy、ffn、scipy、pyarrow、pytest；不新增依赖。

**Spec:** `docs/superpowers/specs/2026-10-24-etf-rotation-report-content-spec.md`（§3.2 N1–N13、§5 图表 ID、§6 P0 详图）

## Global Constraints

- 环境：`.venv\Scripts\python.exe`；运行任何 Python 前 `$env:PYTHONIOENCODING="utf-8"`。
- 不改策略决策、不改回测引擎、不引入新依赖；派生层不得写回 `equity/weights/trades`。
- 时间纪律：T 日信号、T+1 成交；所有滚动统计只用 ≤ 当日信息（必要时 `.shift(1)`）。
- 指标唯一来源：绩效数字继续取 `metrics.json`（ffn/引擎口径），派生层只做展示性聚合，不重新定义年化/Sharpe。
- 年化统一用日历日 CAGR（`ffn.calc_cagr`）；波动/Sharpe 用 √252。
- 所有 JSON 输出必须能通过 `json.dumps(payload, allow_nan=False)`；NaN/Inf 一律转 `null`，日期一律 `YYYY-MM-DD`。
- 成交额 `amount` 的单位是 **元**（已核对 `513100.SH` 中位数约 1.03 亿元），容量计算直接用元。
- 新代码中文 docstring，公式显式写出；每个任务独立 commit（`feat(report): ...` / `fix(benchmark): ...`）。
- 每个任务结束跑：`.venv\Scripts\python.exe -m pytest tests/test_report_*.py tests/test_alignment.py -q`；全量回归在 Task 11。

## Review Focus

1. **基准日期对齐**：`compute_benchmark` 多一次 `shift` 就会把 corr 从 0.51 打到 0。任何涉及基准的改动，必须由 `lag_correlation` 的峰值在 0 守住（Task 1、Task 3 各有一条测试）。
2. **四套索引对齐**：`weights`（目标，T 日）、`holdings`（引擎实际，t 日）、`trades`（成交日）、`diary`（信号日）索引语义不同；join 必须显式 `reindex`，并且目标权重比较要 `shift(1)`（Task 6 测试覆盖日历不一致）。
3. **预热期 NaN**：前 80/250 个交易日信号为空。滚动指标不得 `fillna(0)` 制造虚假稳定期，必须显式剔除并在输出里给 `start_date`（Task 3 测试断言前 251 个值为 `null`）。
4. **FIFO 配对**：份额是分数、同一标的多批买卖、卖出可能跨多个批次；卖出必须按批次消耗、费用按比例摊（Task 7 测试覆盖一次卖出吃掉两个批次）。
5. **单位与序列化**：`amount` 为元、`capital` 为元；NaN/Inf 进入 JSON 会让前端 `JSON.parse` 直接失败（Task 10 与 Task 2 的 runner 测试各守一条）。

---

## File Structure

```
src/etf_rotation/
  evaluation/alignment.py        # 新增：lag_correlation（Task 1）
  pipeline.py                    # 修改：compute_benchmark 去双重 shift；trace 增加阶段快照（Task 1、Task 8）
  report/
    __init__.py                  # SCHEMA_VERSION = 1
    context.py                   # ReportContext.load
    serialize.py                 # records / series / clean
    runner.py                    # 自动发现 steps、逐步骤写 JSON、index.json
    steps/
      __init__.py
      alignment.py               # N1 自检（Task 1 之后、Task 2 建立骨架时接入）
      performance.py             # N2（Task 2）
      relative.py                # N3 + N9（Task 3）
      events.py                  # N4（Task 4）
      costs.py                   # N13（Task 5）
      execution.py               # N6 + N8（Task 6）
      roundtrips.py              # N7（Task 7）
      stages.py                  # N5（Task 8）
      extremes.py                # N12（Task 9）
      liquidity.py               # N10 + N11（Task 10）
scripts/
  build_report_data.py           # CLI：--only / --reports
  run_backtest.py                # 修改：equity.csv 增加 turnover、fees 列（Task 1）
reports/derived/                 # 生成物，加入 .gitignore（Task 2）
tests/
  test_alignment.py
  test_report_context.py
  test_report_runner.py
  test_report_performance.py
  test_report_relative.py
  test_report_events.py
  test_report_costs.py
  test_report_execution.py
  test_report_roundtrips.py
  test_report_stages.py
  test_report_extremes.py
  test_report_liquidity.py
```

**输出契约（前端只依赖这张表）：**

| 文件 | 章节 / 图表 ID | 内容 |
|---|---|---|
| `derived/index.json` | 全局 | 步骤状态、schema_version、生成时间 |
| `derived/alignment.json` | C9 / B06 | lag 扫描、峰值 lag、是否通过 |
| `derived/performance.json` | C1 V03/V04、C4 P01–P05 | 水下曲线、回撤事件、年度/月度 |
| `derived/relative.json` | C1 V02、C5 R02/R03、C6 B01–B05、C7 A06 | 相对指标、滚动、超额、剔除防守 |
| `derived/events.json` | C3 D01–D03 | 调仓事件表、触发规则、事后收益 |
| `derived/costs.json` | C7 A04、C8 X08 | 分年费用、拖累、盈亏平衡成本 |
| `derived/execution.json` | C8 X01/X02 | 目标 vs 实际、换手分解 |
| `derived/roundtrips.json` | C8 X07 | 单笔往返、持有期、盈亏 |
| `derived/stages.json` | C3 D09 | 事件阶段归因（瀑布） |
| `derived/extremes.json` | C5 R07 | 极端日 |
| `derived/liquidity.json` | C8 X09/X10 | 滑点、容量 |

---

## Task 1: 修基准对齐（N1）+ lag 扫描工具

**Files:**
- Modify: `src/etf_rotation/pipeline.py:674-706`（`compute_benchmark`）
- Modify: `scripts/run_backtest.py:67`（equity.csv 增加 `turnover`、`fees`）
- Create: `src/etf_rotation/evaluation/alignment.py`
- Test: `tests/test_alignment.py`

**Interfaces:**
- Produces: `alignment.lag_correlation(strategy: pd.Series, benchmark: pd.Series, max_lag: int = 5) -> pd.Series`，index=lag、values=相关系数。
- Produces: `pipeline.compute_benchmark(params: dict, start: str, end: str) -> pd.DataFrame`（列不变：`benchmark`、`hs300`；日期语义改为「t 日净值含 t 日收益」）。
- Produces: `reports/equity.csv` 新增 `turnover`、`fees` 两列（供 Task 3/5/6 用）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_alignment.py
import pandas as pd
from etf_rotation.evaluation.alignment import lag_correlation

def test_lag_correlation_peaks_at_zero_when_aligned():
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    b = pd.Series([0.01, -0.02, 0.03, 0.0, -0.01] * 12, index=idx)
    s = b * 0.8 + 0.001
    corr = lag_correlation(s, b)
    assert corr.idxmax() == 0
    assert corr.loc[0] > 0.99

def test_lag_correlation_detects_one_day_lag():
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    b = pd.Series([0.01, -0.02, 0.03, 0.0, -0.01] * 12, index=idx)
    s = b.shift(1).fillna(0.0)
    corr = lag_correlation(s, b)
    assert corr.idxmax() == -1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_alignment.py -q`
Expected: FAIL，`ModuleNotFoundError: etf_rotation.evaluation.alignment`

- [ ] **Step 3: 实现 `lag_correlation`**

```python
def lag_correlation(strategy: pd.Series, benchmark: pd.Series, max_lag: int = 5) -> pd.Series:
    """lag k 的相关系数：corr_k = Corr(s_t, b_{t-k})，k>0 表示基准领先策略。"""
```

对 `k in range(-max_lag, max_lag+1)`：`benchmark.shift(k)` 与 `strategy` 对齐后 `.corr()`；索引为 k，排序后返回。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_alignment.py -q` → PASS

- [ ] **Step 5: 写失败的基准对齐测试**

```python
# tests/test_alignment.py
import numpy as np
import pytest
from etf_rotation import pipeline

def test_compute_benchmark_uses_same_day_index_return(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=4, freq="B")
    hs = pd.Series([100.0, 110.0, 99.0, 108.9], index=idx)
    close = pd.DataFrame({"A": [10.0, 11.0, 9.9, 10.89]}, index=idx)
    amt = pd.DataFrame({"A": [1e8] * 4}, index=idx)
    fb = pd.DataFrame({"ts_code": ["A"]})
    monkeypatch.setattr(pipeline, "load_prices", lambda: (close, close, amt))
    monkeypatch.setattr(pipeline, "load_indices", lambda: {"000300.SH": hs})
    monkeypatch.setattr(pipeline, "load_fund_basic", lambda: fb)
    monkeypatch.setattr(pipeline.univ, "classify", lambda _: {"A": "risk"})
    monkeypatch.setattr(pipeline.calendar, "trading_days", lambda s, e: idx)
    out = pipeline.compute_benchmark({"universe": {"min_listed_days": 0, "min_avg_amount20": 0}}, "2024-01-01", "2024-01-04")
    got = out["hs300"].pct_change().iloc[1]
    assert got == pytest.approx(hs.pct_change().iloc[1])
```

- [ ] **Step 6: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_alignment.py::test_compute_benchmark_uses_same_day_index_return -q`
Expected: FAIL（当前 `got` 等于前一日收益 0.0）

- [ ] **Step 7: 去掉双重 shift 并补列**

`compute_benchmark` 中删掉 `bench_ret.shift(1)` 与 `hs_ret.shift(1)` 两行，docstring 公式改为「nav_t = Π(1+r_s)，r 取同日」，并说明策略净值已是 T+1 口径、基准不得再平移。
`scripts/run_backtest.py` 落盘 equity 时改为：

```python
pd.DataFrame({"nav": res.nav, "returns": res.returns, "cash": res.cash,
              "turnover": res.turnover, "fees": res.fees}).to_csv(out / "equity.csv")
```

- [ ] **Step 8: 跑测试确认通过并重跑回测**

Run: `.venv\Scripts\python.exe -m pytest tests/test_alignment.py tests/test_backtest.py -q` → PASS
Run: `$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31`
Run: `.venv\Scripts\python.exe -c "import pandas as pd; from etf_rotation.evaluation.alignment import lag_correlation; e=pd.read_csv('reports/equity.csv',parse_dates=['ts']).set_index('ts'); b=pd.read_csv('reports/benchmark.csv',parse_dates=['ts']).set_index('ts'); print(lag_correlation(e['returns'], b['hs300'].pct_change()).round(3))"`
Expected: 峰值在 `0`，`corr(0) ≈ 0.51`。

- [ ] **Step 9: 提交**

```bash
git add src/etf_rotation/pipeline.py src/etf_rotation/evaluation/alignment.py scripts/run_backtest.py tests/test_alignment.py
git commit -m "fix(benchmark): 去除基准收益的重复 shift 并对齐同日收益"
```

---

## Task 2: 报告数据骨架 + 水下/回撤事件（N2）

**Files:**
- Create: `src/etf_rotation/report/__init__.py`、`context.py`、`serialize.py`、`runner.py`、`steps/__init__.py`、`steps/alignment.py`、`steps/performance.py`
- Create: `scripts/build_report_data.py`
- Modify: `.gitignore`（增加 `reports/derived/`）
- Test: `tests/test_report_context.py`、`tests/test_report_runner.py`、`tests/test_report_performance.py`

**Interfaces:**
- Produces: `ReportContext.load(reports_dir: Path) -> ReportContext`，字段：`params, equity, benchmark, weights, diary, ticker_signals, trades, transactions, holdings, stages, classification, close, opn, amount`（`stages` 读 `reports/signals/stages.parquet`，缺失时为 `None`，由 Task 8 生成）。
- Produces: 每个 step 模块暴露 `NAME: str` 与 `build(ctx: ReportContext) -> dict`。
- Produces: `runner.run(reports_dir: Path, ctx: ReportContext, only: list[str] | None = None) -> dict[str, dict]`，写 `reports/derived/<NAME>.json` 与 `index.json`。
- Produces: `serialize.records(df, index: str | None = "date") -> list[dict]`、`serialize.series(s) -> {"dates": [...], "values": [...]}`、`serialize.clean(obj) -> Any`。

- [ ] **Step 1: 写 performance 失败测试**

```python
# tests/test_report_performance.py
import pandas as pd
from etf_rotation.report.steps import performance

def test_underwater_and_episode_bounds():
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    nav = pd.Series([1.0, 1.1, 0.9, 1.2, 1.0], index=idx)
    uw = performance.underwater(nav)
    assert uw.loc[idx[2]] == -0.18 - 1e-12 or abs(uw.loc[idx[2]] + 0.1818181818) < 1e-9
    ep = performance.episodes(nav, min_depth=0.02)
    assert len(ep) == 1
    row = ep.iloc[0]
    assert row["peak_date"] == "2024-01-02"
    assert row["trough_date"] == "2024-01-03"
    assert row["recovery_date"] == "2024-01-04"
    assert row["recovered"] is True
    assert row["duration_days"] == 1          # 交易日
    assert row["recovery_days"] == 1

def test_unrecovered_episode_has_null_recovery():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    ep = performance.episodes(pd.Series([1.0, 0.9, 0.8], index=idx))
    assert ep.iloc[0]["recovery_date"] is None
    assert ep.iloc[0]["recovered"] is False
```

- [ ] **Step 2: 跑测试确认失败** → `ModuleNotFoundError: etf_rotation.report`

- [ ] **Step 3: 实现骨架与 performance**

`context.py`：逐文件读取（`equity.csv` 用 `parse_dates=["ts"]`，`trades.csv` 用 `parse_dates=["date"]`，`transactions.csv` 用 `parse_dates=["Date"]`，`holdings.csv` 用 `index_col=0, parse_dates=True` 并把列名 `etf_rotation>XXX` 截成 `XXX`、丢弃 `etf_rotation` 根列；`stages.parquet` 存在则读、否则 `None`）；`classification = universe.classify(load_fund_basic())`；价格面板用 `pipeline.load_prices()` 一次加载。
`serialize.py`：`clean` 递归处理 `Timestamp→YYYY-MM-DD`、`numpy` 标量、`NaN/Inf→None`。
`runner.py`：`pkgutil.iter_modules(steps.__path__)` 发现模块；运行前删除旧输出；捕获异常写入 `index.json` 的 `error`，不中断其他步骤。
`steps/alignment.py`：调 `lag_correlation`，输出 `{"lags": [...], "corrs": [...], "peak_lag": int, "ok": bool}`（`ok = peak_lag == 0`）。
`steps/performance.py`：`underwater(nav)`、`episodes(nav, min_depth=0.02)`、`annual_table(equity)`、`monthly_table(returns)`、`longest_underwater(nav)`；`build` 汇总为 `{"underwater": series, "episodes": records, "annual": records, "monthly": records, "longest": {...}}`。
年度换手直接用 `equity["turnover"].groupby(year).sum()`；年度费用用 `equity["fees"].groupby(year).sum()`（引擎 `fees` 是逐日费用流水，`.sum()` 即该年费用，已核对 `strategy.fees.sum()` 等于 `metrics.total_fees`）。

- [ ] **Step 4: 跑 performance 测试 → PASS**

- [ ] **Step 5: 写 runner 失败测试**

```python
# tests/test_report_runner.py
import json
import pandas as pd
from etf_rotation.report import runner
from etf_rotation.report.context import ReportContext

def _ctx():
    return ReportContext(params={}, equity=pd.DataFrame({"nav": [1.0, 1.1], "returns": [0.0, 0.1],
        "cash": [1.0, 0.9], "turnover": [0.0, 0.1], "fees": [0.0, 0.0]},
        index=pd.to_datetime(["2024-01-01", "2024-01-02"])), benchmark=None, weights=None,
        diary=None, ticker_signals=None, trades=None, transactions=None, holdings=None,
        stages=None, classification={}, close=None, opn=None, amount=None)

def test_runner_writes_index_and_null_for_nan(tmp_path):
    out = runner.run(tmp_path, _ctx(), only=["performance"])
    idx = json.loads((tmp_path / "derived" / "index.json").read_text(encoding="utf-8"))
    assert idx["steps"]["performance"]["ok"] is True
    text = (tmp_path / "derived" / "performance.json").read_text(encoding="utf-8")
    assert "NaN" not in text and "Infinity" not in text
```

- [ ] **Step 6: 跑 runner 测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_runner.py -q`
Expected: FAIL，`runner`/`ReportContext` 不存在。

- [ ] **Step 7: 实现 serializer、runner 与 CLI**

`scripts/build_report_data.py`：`--reports` 默认 `reports`、`--only` 逗号分隔；打印每步 `ok/error`；有失败时 `sys.exit(1)`。

- [ ] **Step 8: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_runner.py tests/test_report_context.py -q` → PASS

- [ ] **Step 9: 真实数据跑通**

Run: `$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python.exe scripts\build_report_data.py`
Expected: `alignment` 与 `performance` 均 ok；`reports/derived/index.json` 中 `peak_lag == 0`。

- [ ] **Step 10: 提交**

```bash
git add src/etf_rotation/report scripts/build_report_data.py .gitignore tests/test_report_*.py
git commit -m "feat(report): 报告派生数据骨架与水下/回撤事件"
```

---

## Task 3: 相对指标 + 剔除防守相关性（N3 + N9）

**Files:**
- Create: `src/etf_rotation/report/steps/relative.py`
- Test: `tests/test_report_relative.py`

**Interfaces:**
- Consumes: `ReportContext.equity/benchmark/weights/close/classification`
- Produces: `relative_summary(strategy: pd.Series, benchmark: pd.Series) -> dict`、`rolling_relative(strategy, benchmark, window=252) -> pd.DataFrame`、`risk_sleeve_relative(equity_returns, weights, close, classification, benchmark) -> dict`

- [ ] **Step 1: 写失败测试**

```python
import numpy as np
import pandas as pd
import pytest
from etf_rotation.report.steps import relative

def test_relative_metrics_on_known_series():
    idx = pd.date_range("2020-01-01", periods=600, freq="B")
    b = pd.Series(np.sin(np.arange(600)) * 0.01, index=idx)
    s = 0.5 * b + 0.001
    m = relative.relative_summary(s, b)
    assert m["beta"] == pytest.approx(0.5, abs=1e-12)
    assert m["correlation"] == pytest.approx(1.0, abs=1e-12)

def test_tracking_error_zero_for_constant_offset():
    idx = pd.date_range("2020-01-01", periods=600, freq="B")
    b = pd.Series(np.sin(np.arange(600)) * 0.01, index=idx)
    m = relative.relative_summary(b + 0.0001, b)
    assert m["tracking_error"] == pytest.approx(0.0, abs=1e-12)

def test_rolling_relative_drops_warmup_instead_of_filling():
    idx = pd.date_range("2020-01-01", periods=300, freq="B")
    b = pd.Series(np.sin(np.arange(300)) * 0.01, index=idx)
    df = relative.rolling_relative(0.5 * b + 0.001, b, window=252)
    assert df["beta"].iloc[:251].isna().all()
    assert df["beta"].iloc[251:].notna().all()
```

- [ ] **Step 2: 跑测试确认失败**

- [ ] **Step 3: 实现**

`relative_summary` 键：`excess_cagr`（ffn CAGR 之差）、`excess_arith`（年化算术均值差）、`tracking_error`、`information_ratio`、`beta`、`correlation`、`up_capture`、`down_capture`、`monthly_win_rate`、`n_months`。分母为 0 时（如 TE=0、基准无上涨日）返回 `None`，禁止 `inf`/`nan`。
捕获率定义：`mean(r_s | r_b > 0) / mean(r_b | r_b > 0)`，下行同理（`r_b < 0`）。
`rolling_relative`：`excess`（252 日复合差）、`ir`（滚动均值差/滚动标准差×√252）、`beta`、`corr`，窗口不足返回 NaN。
`risk_sleeve_relative`：把 `weights` 中 `classification ∈ {bond, money}` 的列置 0，再按当日剩余权重和归一化，`r_risk = Σ w_norm·r`；输出 `corr_full/beta_full/corr_risk_sleeve/beta_risk_sleeve/mean_risk_weight`。
`build` 输出 `{"lag_scan": {"lags": [...], "corrs": [...], "peak_lag": int, "ok": bool}, "summary": {10 个键}, "rolling": {"dates": [...], "excess": [...], "ir": [...], "beta": [...], "corr": [...]}, "annual_excess": [{"year", "strategy", "benchmark", "excess"}], "ex_defensive": {"corr_full", "beta_full", "corr_risk_sleeve", "beta_risk_sleeve", "mean_risk_weight"}}`（lag 扫描复用 `alignment` 函数）。

- [ ] **Step 4: 跑测试 → PASS**

- [ ] **Step 5: 真实数据校验**

Run: `python scripts/build_report_data.py --only relative`
Expected: `corr_full ≈ 0.51`、`beta_full ≈ 0.31`、`information_ratio ≈ 0.15`、`ex_defensive.corr_risk_sleeve > corr_full`。

- [ ] **Step 6: 提交** `feat(report): 相对基准指标与剔除防守相关性`

---

## Task 4: 调仓事件表（N4）

**Files:**
- Create: `src/etf_rotation/report/steps/events.py`
- Test: `tests/test_report_events.py`

**Interfaces:**
- Consumes: `ReportContext.diary/weights/trades/equity`
- Produces: `rebalance_events(diary, weights, returns) -> pd.DataFrame`（列：`date, types, regime, turnover, top_changes, triggers, fwd_5d, fwd_20d`）
- Produces: `event_dates(diary, weights) -> pd.DatetimeIndex`（Task 8 复用同一套判定，避免两处规则漂移）

- [ ] **Step 1: 写失败测试**

```python
import pandas as pd
from etf_rotation.report.steps import events

def test_events_capture_switch_and_overheat():
    idx = pd.date_range("2024-01-01", periods=4, freq="B")
    diary = pd.DataFrame({
        "regime": ["bull"] * 4,
        "hysteresis_held": [True, False, True, True],
        "n_overheat_exits": [0, 0, 1, 0],
        "vol_cap_scale": [1.0, 1.0, 1.0, 0.9],
        "n_defensive": [2, 2, 2, 2],
    }, index=idx)
    weights = pd.DataFrame({"A": [0.6, 0.4, 0.0, 0.2], "B": [0.4, 0.6, 1.0, 0.8]}, index=idx)
    rets = pd.Series(0.001, index=idx)
    ev = events.rebalance_events(diary, weights, rets)
    assert set(ev["types"].explode()) == {"switch", "overheat", "vol_cap"}
    assert ev.loc[ev["types"].apply(lambda x: "switch" in x), "date"].iloc[0] == "2024-01-02"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_events.py -q`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现 `rebalance_events` 与 `event_dates`**

事件判定：`hysteresis_held == False` → `switch`；`n_overheat_exits > 0` → `overheat`；`vol_cap_scale < 1` → `vol_cap`；`n_defensive` 变化 → `defensive`；纳指/黄金权重变化 → `cross_asset`。当天多变体合并为 `types` 列表；`event_dates` 返回这些日期。
`top_changes`：`Δw = w_t − w_{t−1}`，取 |Δw| 最大 3 个，输出 `{ticker, before, after, delta}`。
`turnover = Σ|Δw| / 2`。`fwd_5d/fwd_20d = Π(1+r_{t+1..t+n}) − 1`（尾部不足 n 天时返回 `None`；标注事后）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_events.py -q` → PASS

- [ ] **Step 5: 真实数据**

Run: `python scripts/build_report_data.py --only events`
Expected: 事件数 300–800；`overheat` 出现日数与 `diary.n_overheat_exits > 0` 的日数一致。

- [ ] **Step 6: 提交** `feat(report): 调仓事件表与触发规则`

---

## Task 5: 成本拖累与盈亏平衡成本（N13）

**Files:**
- Create: `src/etf_rotation/report/steps/costs.py`
- Test: `tests/test_report_costs.py`

**Interfaces:**
- Consumes: `equity`（`nav/fees/turnover`）、`trades`
- Produces: `annual_cost_drag(equity, trades) -> pd.DataFrame`、`breakeven_bps(ann_return, ann_turnover, annual_drag) -> float`

- [ ] **Step 1: 写失败测试**

```python
import pandas as pd
import pytest
from etf_rotation.report.steps import costs

def test_breakeven_formula():
    # 年化 10%、年换手 12.5 倍、当前费用拖累 2% → 毛收益 12%，平衡点 12%/(2*12.5)=48bp
    assert costs.breakeven_bps(0.10, 12.5, 0.02) == pytest.approx(0.12 / (2 * 12.5) * 1e4, rel=1e-9)

def test_annual_drag_sums_daily_fee_flow():
    idx = pd.date_range("2024-01-01", "2024-12-31", freq="B")
    eq = pd.DataFrame({
        "nav": 1.0 + 0.0002 * range(len(idx)),
        "fees": [0.001] * len(idx),          # 引擎 fees 是逐日费用流水
        "turnover": 0.05,
    }, index=idx)
    out = costs.annual_cost_drag(eq, trades=None)
    assert out.iloc[0]["year"] == 2024
    assert out.iloc[0]["fees"] == pytest.approx(0.001 * len(idx))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_costs.py -q`
Expected: FAIL，`ModuleNotFoundError: etf_rotation.report.steps.costs`

- [ ] **Step 3: 实现 `annual_cost_drag` 与 `breakeven_bps`**

`annual_cost_drag`：按年 `fees` 求和（逐日流水）；`avg_nav` 取当年 nav 均值；`drag_pct = fees / avg_nav`；`return_pct = nav 年末/年初 − 1`；`cost_share_pct = fees / (return_pct × nav 年初 + fees)`。`breakeven_bps = (ann_return + annual_drag) / (2 × ann_turnover) × 1e4`，输出附 `assumptions` 说明「线性外推、不含冲击成本」。同时输出 `reconciliation`：`trades.cost.sum()` 与 `metrics.total_fees` 的差值和相对误差。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_costs.py -q` → PASS

- [ ] **Step 5: 真实数据** `--only costs` → 分年 drag 合计 ≈ `total_fees` 口径，平衡点落在 40–50bp。
- [ ] **Step 6: 提交** `feat(report): 分年成本拖累与盈亏平衡成本`

---

## Task 6: 目标 vs 实际 + 换手分解（N6 + N8）

**Files:**
- Create: `src/etf_rotation/report/steps/execution.py`
- Test: `tests/test_report_execution.py`

**Interfaces:**
- Consumes: `weights`、`holdings`、`diary`
- Produces: `target_vs_actual(weights, holdings) -> pd.DataFrame`、`turnover_split(diary, weights) -> pd.DataFrame`

- [ ] **Step 1: 写失败测试**

```python
import pandas as pd
import pytest
from etf_rotation.report.steps import execution

def test_target_vs_actual_aligns_by_calendar_and_shifts_target():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    weights = pd.DataFrame({"A": [0.5, 0.5, 0.6], "B": [0.5, 0.5, 0.4]}, index=idx)
    holdings = pd.DataFrame({"etf_rotation>A": [0.0, 0.5, 0.55],
                             "etf_rotation>B": [0.0, 0.5, 0.45]}, index=idx)
    out = execution.target_vs_actual(weights, holdings)
    assert out.loc[idx[1], "mean_abs"] == pytest.approx(0.0)   # 用 T-1 目标
    assert out.loc[idx[2], "mean_abs"] == pytest.approx(0.05)

def test_turnover_split_sums_to_total():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    weights = pd.DataFrame({"A": [0.5, 0.4, 0.3], "B": [0.5, 0.6, 0.7]}, index=idx)
    diary = pd.DataFrame({
        "hysteresis_held": [True, False, False],
        "n_overheat_exits": [0, 0, 1],
        "vol_cap_scale": [1.0, 1.0, 1.0],
        "n_defensive": [2, 2, 2],
    }, index=idx)
    split = execution.turnover_split(diary, weights)
    total = split[["switch", "overheat", "vol_cap", "defensive", "other"]].sum().sum()
    assert total == pytest.approx(0.2)      # 两日各 0.1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_execution.py -q`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现 `target_vs_actual` 与 `turnover_split`**

`target_vs_actual`：`target_eff = weights.shift(1).reindex(index=holdings.index, columns=holdings.columns).fillna(0)`；`mean_abs = |actual − target_eff|.sum(axis=1) / 2`；`max_abs` 取单标的最大绝对偏差。`turnover_split`：按日记主导事件归因当日 `Σ|Δw|/2`（`overheat > 0` → overheat；`vol_cap_scale < 1` → vol_cap；`hysteresis_held == False` → switch；`n_defensive` 变化 → defensive；其余 other），按年汇总，并附 `reconcile` 列（各分量之和 vs `equity.turnover` 年度和）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_execution.py -q` → PASS

- [ ] **Step 5: 真实数据** `--only execution` → `mean_abs` 中位数 < 0.5%，最大 < 10%。
- [ ] **Step 6: 提交** `feat(report): 目标与实际持仓偏差及换手分解`

---

## Task 7: 单笔往返（N7）

**Files:**
- Create: `src/etf_rotation/report/steps/roundtrips.py`
- Test: `tests/test_report_roundtrips.py`

**Interfaces:**
- Consumes: `trades`（date/ticker/side/price/quantity/notional/cost）、`ticker_signals`
- Produces: `match_round_trips(trades, signals) -> pd.DataFrame`

- [ ] **Step 1: 写失败测试**

```python
import pandas as pd
import pytest
from etf_rotation.report.steps import roundtrips

def test_fifo_sell_consumes_multiple_lots():
    trades = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-05", "2024-01-10"]),
        "ticker": ["A", "A", "A"], "side": ["买入", "买入", "卖出"],
        "price": [10.0, 12.0, 11.0], "quantity": [1.0, 1.0, 1.5],
        "notional": [10.0, 12.0, 16.5], "cost": [0.001, 0.001, 0.0],
    })
    out = roundtrips.match_round_trips(trades, signals=None)
    assert len(out) == 2
    assert out.iloc[0]["quantity"] == pytest.approx(1.0)
    assert out.iloc[1]["quantity"] == pytest.approx(0.5)
    assert out.iloc[0]["pnl"] == pytest.approx(1.0 - 0.001, abs=1e-9)   # (11−10)×1 − 入仓费
    assert out.iloc[1]["pnl"] == pytest.approx(-0.5 - 0.0005, abs=1e-9)  # (11−12)×0.5 − 分摊入仓费
    assert out.iloc[0]["holding_days"] == 9
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_roundtrips.py -q`
Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现 `match_round_trips`**

FIFO 批次：买入入队（qty、price、date、cost 按 qty 摊）；卖出按队列顺序消耗，跨批次生成多条往返，最后一批允许部分消耗并保留剩余。`pnl = qty × (sell_price − buy_price) − 分摊成本`；`holding_days = (exit_date − entry_date).days`。`entry_status` 取 `ticker_signals.loc[(entry_date, ticker), "status"]`；`exit_reason`：当日 `overheat_exit` → `overheat`，否则 `switch`，查不到 → `other`。`summary`：笔数、胜率、平均/中位持有天数、总盈亏、按 `exit_reason` 分组。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_roundtrips.py -q` → PASS

- [ ] **Step 5: 真实数据** `--only roundtrips` → 往返数 5,000–12,000；胜率 40–60%。
- [ ] **Step 6: 提交** `feat(report): 单笔往返配对与已实现盈亏`

---

## Task 8: 阶段归因（N5）

**Files:**
- Modify: `src/etf_rotation/pipeline.py:436-455`（`_daily_target` 四个阶段快照）、`pipeline.py:606-641`（`build_weights` 三个阶段快照）
- Modify: `src/etf_rotation/evaluation/observability.py`（新增 `build_stages`，`write` 增加可选 `stages` 参数）
- Modify: `scripts/run_backtest.py:79-80`（落盘 `reports/signals/stages.parquet`）
- Create: `src/etf_rotation/report/steps/stages.py`
- Test: `tests/test_report_stages.py`、`tests/test_observability.py`

**Interfaces:**
- Produces: `pipeline._stage_snapshot(weights: dict[str, float]) -> dict[str, float]`（丢弃 0 与负值）。
- Produces: `trace["stages"]: dict[str, dict[str, float]]`，键固定为 `candidate, overheat, cross_asset, defensive, phases, hysteresis, final`。
- Produces: `observability.build_stages(traces: list[dict], days: pd.DatetimeIndex) -> pd.DataFrame`，列 `date, ticker, stage, weight`。
- Consumes: `events.event_dates(diary, weights) -> pd.DatetimeIndex`（Task 4 产出）。
- Produces: `stages.stage_table(long: pd.DataFrame, event_dates: list[pd.Timestamp], top_n: int = 10) -> dict`：`{"stage_order": [...], "events": [{"date", "tickers", "weights"}], "totals": [{"date", "stage", "total_weight"}]}`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_stages.py
import pandas as pd
import pytest
from etf_rotation import pipeline
from etf_rotation.evaluation import observability
from etf_rotation.report.steps import stages

def test_stage_snapshot_filters_zero():
    assert pipeline._stage_snapshot({"A": 0.3, "B": 0.0, "C": -0.1}) == {"A": 0.3}

def test_build_stages_long_format():
    days = pd.date_range("2024-01-01", periods=2, freq="B")
    traces = [
        {"stages": {"candidate": {"A": 0.6}, "final": {"A": 0.5}}},
        {"stages": {"candidate": {"A": 0.4}, "final": {"A": 0.4}}},
    ]
    df = observability.build_stages(traces, days)
    assert set(df.columns) == {"date", "ticker", "stage", "weight"}
    assert len(df) == 4
    assert df.loc[df["date"] == days[0], "weight"].sum() == pytest.approx(1.1)

def test_stage_table_limits_to_top10_and_reports_totals():
    rows = []
    for i in range(12):
        for stg, w in [("candidate", 0.05), ("final", 0.04)]:
            rows.append({"date": pd.Timestamp("2024-01-02"), "ticker": f"T{i:02d}",
                         "stage": stg, "weight": w * (i + 1)})
    out = stages.stage_table(pd.DataFrame(rows), [pd.Timestamp("2024-01-02")], top_n=10)
    assert out["stage_order"] == ["candidate", "overheat", "cross_asset", "defensive",
                                  "phases", "hysteresis", "final"]
    assert len(out["events"][0]["tickers"]) == 10
    assert out["totals"][0]["date"] == "2024-01-02"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_stages.py -q`
Expected: FAIL，`_stage_snapshot` / `build_stages` / `stages` 不存在。

- [ ] **Step 3: 实现阶段快照与落盘**

`_daily_target` 按顺序记录：`candidate`（过热前，line 438 的 `pre_overheat`）、`overheat`（line 443 之后）、`cross_asset`（line 454 之后）、`defensive`（line 474 之后）；`build_weights` 记录 `phases`（line 612 之后）、`hysteresis`（line 618 之后）、`final`（line 627 之后）。全部经 `_stage_snapshot`，只在 `with_trace=True` 时写入 `trace["stages"]`。
`observability.build_stages` 把 `traces[i]["stages"]` 展成长表；`write(..., stages=None)` 在 `stages is not None` 时写 `signals/stages.parquet`；`run_backtest.py` 传入 `observability.build_stages(build.traces, build.days)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_stages.py tests/test_observability.py -q` → PASS

- [ ] **Step 5: 实现 `stages.stage_table` 并跑测试**

`stage_table`：对每个事件日，按 `max(weight)` 取前 `top_n` 个标的，输出 `tickers` 与 `weights`（行=标的、列=`stage_order`，缺失补 0）；`totals` 为各阶段总权重。

- [ ] **Step 6: 真实数据校验**

Run: `python scripts\run_backtest.py 2019-01-01 2026-07-31 && python scripts\build_report_data.py --only stages`
Expected: 每个事件 `sum(final) == diary.total_weight`，`sum(candidate) >= sum(final)`；`stages.parquet` 行数 = 事件日数 × 标的数 × 7 量级以内。

- [ ] **Step 7: 提交** `feat(report): 决策阶段快照与事件瀑布归因`

---

## Task 9: 极端日（N12）

**Files:**
- Create: `src/etf_rotation/report/steps/extremes.py`
- Test: `tests/test_report_extremes.py`

**Interfaces:**
- Consumes: `equity`、`weights`、`diary`、`close`、`classification`
- Produces: `extreme_days(returns, weights, diary, close, classification, top_n=10) -> pd.DataFrame`

- [ ] **Step 1: 写失败测试**

```python
import numpy as np
import pandas as pd
import pytest
from etf_rotation.report.steps import extremes

def test_extreme_days_returns_both_tails():
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    r = pd.Series(np.linspace(-0.02, 0.02, 30), index=idx)
    r.iloc[0] = 0.0                      # 首日无前一日权重，避免归因读空
    weights = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    diary = pd.DataFrame({"regime": "range", "total_weight": 1.0}, index=idx)
    close = pd.DataFrame({"A": 10 * (1 + r).cumprod(), "B": 10 * (1 + r).cumprod()}, index=idx)
    out = extremes.extreme_days(r, weights, diary, close, {"A": "risk", "B": "risk"}, top_n=10)
    assert len(out) == 20
    assert out["return"].iloc[0] == pytest.approx(r.min())
    assert out["return"].iloc[-1] == pytest.approx(r.max())
    assert out["class_contrib"].iloc[0]["risk"] == pytest.approx(r.min(), abs=1e-9)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_extremes.py -q` → FAIL，模块不存在。

- [ ] **Step 3: 实现 `extreme_days`**

`class_contrib` 用 `w_{t−1} × r_t` 按类别汇总（复用 `attribution.asset_class_contributions`，只取该日）；输出最差 `top_n` + 最好 `top_n`，按收益升序排列，每行含 `date, return, regime, total_weight, class_contrib`。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 真实数据** `--only extremes` → 最差日 `class_contrib` 之和 ≈ 当日组合收益（误差 < 1e-6）。
- [ ] **Step 6: 提交** `feat(report): 极端日与当日归因`

---

## Task 10: 滑点与容量（N10 + N11）

**Files:**
- Create: `src/etf_rotation/report/steps/liquidity.py`
- Test: `tests/test_report_liquidity.py`

**Interfaces:**
- Consumes: `transactions`、`close`、`opn`、`amount`、`weights`
- Produces: `slippage(transactions, close, opn) -> pd.DataFrame`（逐笔：`date, ticker, side, price, close, opn, vs_close_bps, vs_open_bps`）
- Produces: `capacity(weights, amount, capital=1e8, adv_window=20) -> pd.DataFrame`（逐持仓日：`date, ticker, weight, adv20, days`）

- [ ] **Step 1: 写失败测试**

```python
import pandas as pd
import pytest
from etf_rotation.report.steps import liquidity

def test_slippage_sign_is_side_adjusted():
    tx = pd.DataFrame({"Date": pd.to_datetime(["2024-01-02"]), "Security": ["A"],
                       "price": [10.1], "quantity": [100.0]})
    close = pd.DataFrame({"A": [10.0]}, index=tx["Date"])
    opn = pd.DataFrame({"A": [10.0]}, index=tx["Date"])
    out = liquidity.slippage(tx, close, opn)
    assert out.iloc[0]["vs_close_bps"] == pytest.approx(100.0)   # 买入贵 1% = 100bp

def test_capacity_uses_cny_amount():
    idx = pd.date_range("2024-01-01", periods=25, freq="B")
    weights = pd.DataFrame({"A": [1.0] * 25}, index=idx)     # 100% 权重
    amount = pd.DataFrame({"A": [1e8] * 25}, index=idx)      # 1 亿元 ADV
    out = liquidity.capacity(weights, amount, capital=1e8)
    assert out.iloc[-1]["days"] == pytest.approx(1.0)        # 1e8×1.0 / 1e8
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_report_liquidity.py -q` → FAIL，模块不存在。

- [ ] **Step 3: 实现 `slippage` 与 `capacity`**

滑点：`vs_close_bps = sign × (price/close − 1) × 1e4`，`sign = +1` 买、`−1` 卖；同时给 `vs_open_bps`。
容量：`value = weight × capital`；`adv20 = amount.rolling(20).mean()`；`days = value / adv20`；逐持仓日返回，`build()` 再按年汇总 p50/p95/max，并取最差 20 个 `(date, ticker, days)`。
`capital` 默认 1 亿元，写入输出 `assumptions`。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 真实数据** `--only liquidity` → `vs_open_bps` 中位数 ≈ 0（open 口径成交价即开盘价）；`vs_close_bps` 是开盘到收盘的缺口，中位数应在 ±20bp 内；容量 p95 清仓天数 < 5 天（1 亿规模）。
- [ ] **Step 6: 提交** `feat(report): 成交滑点与容量估算`

---

## Task 11: 全量验证、文档与待办收口

**Files:**
- Modify: `TODO.md`、`CHANGELOG.md`、`README.md`（仅补报告数据管线一行）
- Modify: `docs/superpowers/specs/2026-10-24-etf-rotation-report-content-spec.md` §3.2（把 N1–N13 标为已实现，并记录输出文件）

- [ ] **Step 1: 全量测试**

Run: `$env:PYTHONIOENCODING="utf-8"; .venv\Scripts\python.exe -m pytest tests -q`
Expected: 既有 96 条 + 新增全部 PASS。

- [ ] **Step 2: 重跑回测与派生数据**

Run: `python scripts\run_backtest.py 2019-01-01 2026-07-31`
Run: `python scripts\build_report_data.py`
Expected: `index.json` 中 10 个 step 全部 `ok`；`alignment.peak_lag == 0`。

- [ ] **Step 3: 跨文件一致性检查**

- `derived/performance.json` 的 `max_drawdown` 与 `metrics.json` 一致；
- `derived/costs.json` 的分年 fees 合计与 `metrics.total_fees` 相对误差 < 0.5%；
- `derived/events.json` 每个事件 `turnover` 之和与 `equity.turnover` 年度合计差 < 1%；
- 所有 JSON 均通过 `json.loads`，且 `json.dumps(..., allow_nan=False)` 成功。

- [ ] **Step 4: 更新文档**

`TODO.md` 勾掉基准对齐与报告 v2 的前置项，补「派生数据管线已落地，报告渲染待下一阶段」；`CHANGELOG.md` 增一条 `feat(report)`；spec §3.2 每行补「输出：`derived/xxx.json`」。

- [ ] **Step 5: 提交**

```bash
git add TODO.md CHANGELOG.md README.md docs/superpowers/specs/2026-10-24-etf-rotation-report-content-spec.md
git commit -m "docs: 收口报告派生数据管线"
```

---

## 前端设计对接说明

设计 agent 只需要 `reports/derived/*.json` 与 §输出契约表，不需要读代码。要点：

1. 每个 step 一个 JSON，字段即图表数据；`index.json` 给出哪些步骤成功、哪些失败（失败步骤前端应隐藏对应图表并显示原因）。
2. 所有日期为 `YYYY-MM-DD` 字符串，数值为浮点或 `null`；单位：收益/权重为小数（0.0961 = 9.61%），金额为元，滑点为 bp。
3. `events.json` 的 `types` 是数组，同一日期可能同时是换仓与过热；`top_changes` 只给前 3 大变动，完整明细在 `trades.csv`。
4. `stages.json` 的矩阵是「标的 × 阶段」，列为 `stage_order`；`totals` 用于画瀑布总量。
5. 大数据表（交易、持仓、决策日记）继续走 CSV/parquet，不进 JSON；前端以链接/下载方式提供。
6. 失败/缺失时按 spec §8 降级，不显示空图。

---

## 执行顺序与并行建议

| 波次 | 任务 | 说明 |
|---|---|---|
| 1 | Task 1 → Task 2 | Task 1 是全局前置；Task 2 建立骨架，必须串行 |
| 2 | Task 3、4、5、6、7 | 各自独立文件，可并行；都只读 Task 1/2 的产物 |
| 3 | Task 8、9、10 | Task 8 改 `pipeline.py`（与 Task 1 已合并，避免冲突）；9/10 独立 |
| 4 | Task 11 | 全量回归与文档收口 |

**每个任务的完成定义：** 新测试通过 + 既有测试不回归 + `build_report_data.py --only <step>` 在真实数据上产出非空 JSON + 已 commit。
