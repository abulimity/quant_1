# 信号与指标可观测化 Implementation Plan（下阶段）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in a single session。Steps use checkbox (`- [ ]`) syntax for tracking。

**Goal:** 在不改变策略数值的前提下，为回测链路补齐「信号 → 决策 → 交易」的可观测性：先收敛动量两套重复实现（TODO 3.2），再给 `pipeline` 加一层轻量决策轨迹采集，落盘成结构化信号快照（持仓 + 候选 + 关键决策点），最后在现有 plotly 报告里新增「信号与决策」章节，做到回测结束后能逐日看到每个信号的值与趋势、它如何影响策略判断、以及哪次信号变化触发了哪笔交易。

**Architecture:** 保持「pandas 预计算信号 → 目标权重面板 → bt 记账」整体架构不变。本计划只做三件事：① 把 `pipeline.momentum_panel`（向量化）收敛进 `signals/trend.py`，`momentum_score`（循环）降级为参考/薄封装并加等价性测试；② 在 `_daily_target` / `build_weights` 里采集每日决策轨迹（只读既有中间量，不改计算），新增 `evaluation/observability.py` 把轨迹拼成两张 parquet；③ 在 `evaluation/plots.py` 与 `scripts/run_report.py` 增加信号/决策图并接入报告。不接入任何会改变策略数值的新机制。

**Tech Stack:** Python 3.10 / pandas 2.3 / numpy 2.2 / bt 1.2.2 / plotly 7.1 / pytest。

**Spec:**
- `docs/superpowers/specs/2026-10-10-etf-rotation-design.md`（§2.2 趋势、§2.3 反转、§2.4 市场状态、§2.6 风控、§2.8 执行；信号 T 日、成交 T+1）
- `AGENTS.md`（先澄清再设计；滚动统计量 `.shift(1)`；一次只动一个维度；不改数值的重构先过 `IDENTICAL` 回归）
- `TODO.md`（3.2 动量收敛；阶段三其余与阶段四不属本计划）
- `reports/回测报告.md`（当前基线 close 11.83%/12.31%，作为观测层不改数值的对照）

## 前置决策（不阻塞本计划，但影响报告基线数字）

- ① `--execution` 默认是否从 `close` 切到 `open` 仍待用户决定；观测层记录的是「目标权重 + 信号」，与执行口径正交，切换执行口径不影响本计划的实现，只影响报告里并排展示的 NAV/交易数字。
- ② 最终候选参数是否写回 `config/params.yaml` 仍待用户决定；观测层按当前 `params.yaml`（默认参数）跑，或按 `--param` 覆盖后的参数跑，两者都支持。

## Global Constraints

- 所有 Python 统一用 `.venv\Scripts\python.exe`；运行前先 `$env:PYTHONIOENCODING="utf-8"`。
- 滚动统计量一律 `.shift(1)`；T 日信号、T+1 成交；禁止未来信息（观测层的轨迹采集只取 `_daily_target` 里当日已算出的量，不引入新前视）。
- **本计划全程不得改变策略数值**：每个任务结束前用 `pytest` + 基准回测回归，`weights.parquet` 与 `metrics.json` 必须与基线逐值一致（`IDENTICAL`）。
- 回测评估指标唯一来源 = bt 内置统计；观测层只旁路记录，不参与任何决策。
- `.env` 的 tushare token 不得打印/提交/写日志；`data/` 已被 gitignore；`reports/signals/` 为生成物，与 `reports/` 其他产物一致可 gitignore。
- 当前分支 `main`。

---

## Part 0：信号相关重复实现收敛（先行，不改变数值）

### Task 1: 动量两套实现收敛为一套 + 等价性测试（TODO 3.2）

**Files:**
- Modify: `src/etf_rotation/signals/trend.py`（向量化 `momentum_panel` 迁入，`ann` 参数化）
- Modify: `src/etf_rotation/pipeline.py`（改 import，删除本地 `momentum_panel` 定义）
- Test: `tests/test_trend.py`（新增等价性测试）

**Interfaces:**
- Produces: `signals/trend.momentum_panel(logp: pd.DataFrame, window: int, ann: int = 250) -> pd.DataFrame`（与现 `pipeline.momentum_panel` 公式一致，`ann` 从硬编码改为参数，默认 250 保持数值不变）。
- Produces: `signals/trend.momentum_score(close: pd.Series, window: int, ann: int = 250) -> pd.Series`，改为 `momentum_panel` 单列的薄封装（`momentum_panel(np.log(close).to_frame(), window, ann).iloc[:, 0]`）。
- 兼容：`pipeline.py` 顶部 `from etf_rotation.signals import trend` 后 `momentum_panel = trend.momentum_panel`（保留 `pipe.momentum_panel` 引用，避免改动 `tests/test_pipeline.py` 等既有调用点），或直接改调用点二选一，需在 commit 说明。

- [ ] **Step 1: 保存基线产物**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
Copy-Item reports\weights.parquet reports\weights.baseline.parquet
Copy-Item reports\metrics.json reports\metrics.baseline.json
```

- [ ] **Step 2: 写等价性测试**

`tests/test_trend.py`（新建或追加）：

```python
import numpy as np
import pandas as pd

from etf_rotation.signals import trend


def test_momentum_panel_matches_score_single_column():
    idx = pd.date_range("2023-01-01", periods=120, freq="B")
    rng = np.random.default_rng(0)
    close = pd.Series(np.cumprod(1 + rng.normal(0, 0.008, len(idx))), index=idx)
    w = 21
    via_score = trend.momentum_score(close, w)
    via_panel = trend.momentum_panel(np.log(close).to_frame(), w).iloc[:, 0]
    # 前 w-1 期两侧都是 NaN，其余应逐值一致（浮点误差用 allclose 容差）
    mask = via_score.notna()
    np.testing.assert_allclose(via_score[mask].values, via_panel[mask].values, rtol=1e-9, atol=1e-12)
```

- [ ] **Step 3: 运行确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_trend.py -q`
Expected: FAIL（`trend.momentum_panel` 不存在 / `momentum_score` 仍为循环实现）。

- [ ] **Step 4: 实现**

把 `pipeline.momentum_panel` 逐字迁入 `signals/trend.py`，加 `ann` 参数（原硬编码 `250` 改为 `ann`，`np.exp(250 * slope)` → `np.exp(ann * slope)`）；`momentum_score` 改为薄封装。`pipeline.py` 删除本地定义并 `from etf_rotation.signals import trend`，`momentum_panel = trend.momentum_panel`（`_precompute_signals` 内 `m21/m60` 自动走 `ann=250` 默认，数值不变）。

- [ ] **Step 5: pytest + 回归对比**

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
.venv\Scripts\python.exe -c "import pandas as pd, json; assert pd.read_parquet('reports/weights.parquet').equals(pd.read_parquet('reports/weights.baseline.parquet')); assert json.load(open('reports/metrics.json',encoding='utf-8'))==json.load(open('reports/metrics.baseline.json',encoding='utf-8')); print('IDENTICAL')"
```

Expected: pytest 全绿；`IDENTICAL`。

- [ ] **Step 6: Commit**

```powershell
git add src/etf_rotation/signals/trend.py src/etf_rotation/pipeline.py tests/test_trend.py
git commit -m "refactor: consolidate momentum_panel into signals/trend (param ann, equivalence test)"
```

---

## Part 1：信号/决策观测数据落盘

### Task 2: pipeline 采集每日决策轨迹（trace），不改变权重

**Files:**
- Modify: `src/etf_rotation/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `_precompute_signals` 返回 dict 增加 `comp`（三指数复合分，供报告画连续值，不再只有离散 regime）。
- Produces: `_daily_target(...)` 返回值从 5 元组扩展为 6 元组 `(target, last_def_update, current_defn, risk_score, keep, trace)`，`trace` 为当日决策轨迹 dict（只读既有中间量）。
- Produces: `pipeline.BuildResult`（`dataclass`，字段 `weights: pd.DataFrame`、`traces: list[dict]`、`days: pd.DatetimeIndex`）。
- Produces: `build_weights(..., with_trace: bool = False)`；`with_trace=False` 时行为与返回值完全不变（向后兼容 run_grid/run_sensitivity/run_heatmap/tests）；`True` 时返回 `BuildResult`。

`trace` dict 内容（portfolio 级 + 当日清单）：

```python
trace = {
    "comp_score": float(sig["comp"].loc[d]),          # 市场状态复合分
    "regime": str(regime.loc[d]),
    "cyb_below": bool(...), "cyb_drop": float(...), "cyb_vol": float(...),
    "risk_scale": float(rscale_base),                  # risk_scale 输出
    "vol_scale_risk": float(...),                      # 创业板波动缩放
    "risk_budget": float(risk_budget),
    "nas_mom": float(...), "gold_mom": float(...),
    "nas_vol": float(...), "gold_vol": float(...),
    "nasdaq_weight": float(target.get(nasdaq, 0.0)),
    "gold_weight": float(target.get(gold, 0.0)),
    "cands": list[str],                                # 去重前 top 3*max_holdings
    "keep": list[str],                                 # HRP 最终持仓
    "score": {t: float(v) for t, v in score[cands].items()},   # 候选当日排名分
    "overheat_exited": list[str],                      # 过热退出标的
    "defensive": list[str],                            # 当日防守持仓
}
```

`build_weights` 循环内在迟滞/波动上限后再补：

```python
trace["hysteresis_held"] = held                      # _apply_hysteresis 是否维持旧组合
trace["new_score"] = new_score
trace["old_score"] = old_score
trace["vol_cap_scale"] = scale
trace["total_weight"] = float(final.sum())
```

（`_apply_hysteresis` 需把「是否维持」与新旧得分一并返回，或在 `build_weights` 内重算比较逻辑；建议前者：让 `_apply_hysteresis` 返回 `(weights, held, new_score, old_score)`，纯函数、可单测。）

- [ ] **Step 1: 写失败测试**

`tests/test_pipeline.py` 追加：

```python
def test_build_weights_with_trace_keeps_weights_identical():
    p = config.load_params()
    base = pipe.build_weights(p, "2024-01-01", "2024-06-30")
    res = pipe.build_weights(p, "2024-01-01", "2024-06-30", with_trace=True)
    pd.testing.assert_frame_equal(res.weights, base)
    assert len(res.traces) == len(base.index)
    # 每行 trace 都含关键字段
    assert {"regime", "risk_budget", "cands", "keep", "hysteresis_held", "total_weight"} <= set(res.traces[0])
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -k with_trace -q`
Expected: FAIL（`with_trace` / `BuildResult` 不存在）。

- [ ] **Step 3: 实现**

按上述接口改造：`_precompute_signals` 增 `comp`；`_daily_target` 增 `trace`（在 `_apply_overheat` 前后快照 target keys 求 `overheat_exited`）；`_apply_hysteresis` 返回 `(weights, held, new, old)`；`build_weights` 加 `with_trace` 分支（循环内 append trace、循环外包成 `BuildResult`，`with_trace=False` 走原路径只返回 `weights`）。

- [ ] **Step 4: pytest + 回归对比**

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
.venv\Scripts\python.exe -c "import pandas as pd, json; assert pd.read_parquet('reports/weights.parquet').equals(pd.read_parquet('reports/weights.baseline.parquet')); print('IDENTICAL')"
```

Expected: pytest 全绿；`IDENTICAL`。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/pipeline.py tests/test_pipeline.py
git commit -m "feat: collect per-day decision trace in build_weights (weights unchanged)"
```

### Task 3: observability 模块落盘 decision_diary + ticker_signals

**Files:**
- Create: `src/etf_rotation/evaluation/observability.py`
- Modify: `scripts/run_backtest.py`
- Test: `tests/test_observability.py`

**Interfaces:**
- Produces: `observability.build_frames(days, traces, sig, params) -> tuple[pd.DataFrame, pd.DataFrame]`，返回 `(decision_diary, ticker_signals)`。
- Produces: `observability.write(reports_dir, decision_diary, ticker_signals)`，写 `reports/signals/decision_diary.parquet` 与 `reports/signals/ticker_signals.parquet`。

**数据模型（结构化快照，可查询、可复现）：**

`decision_diary.parquet`（index = 交易日，一行一天，portfolio 级）：

| 列 | 含义 |
|---|---|
| comp_score / regime | 三指数 LLT 复合分 / 牛熊震荡态 |
| cyb_below / cyb_drop / cyb_vol | A 股趋势约束三输入 |
| risk_scale / vol_scale_risk / risk_budget | 分层风控输出 |
| nas_mom / gold_mom / nas_vol / gold_vol | 纳指/黄金动量与波动 |
| nasdaq_weight / gold_weight | 纳指/黄金目标权重 |
| n_cands / n_kept / n_overheat_exits | 候选/持仓/过热退出计数 |
| hysteresis_held / new_score / old_score | 迟滞决策 |
| vol_cap_scale | 组合 34% 波动上限缩放 |
| n_defensive / defensive_weight | 防守仓 |
| total_weight / cash_weight | 总仓位 / 现金 |

`ticker_signals.parquet`（MultiIndex [date, ticker]，覆盖「持仓 + 候选 + 关键退出点 + 纳指/黄金/防守」）：

| 列 | 含义 |
|---|---|
| m21 / m60 | 双窗口动量 |
| score | 当日排名分（range 市含反转） |
| zbias / rev_active | 反转信号与激活 |
| close / llt80 / overheat_ratio | 价格 / 80 日 LLT / 过热比（close/llt80） |
| weight | 最终目标权重 |
| status | held_risk / candidate / overheat_exit / nasdaq / gold / defensive |

`build_frames` 用 `traces` 里的 `cands/keep/overheat_exited/score/defensive` 组装 ticker 子集，再从 `sig` 面板 `.loc[d, ticker]` 取 m21/m60/zbias/rev_active/close/llt80（无新计算，仅索引取数）。纳指/黄金/防守持仓单列 status 行。

`scripts/run_backtest.py`：`build_weights(p, start, end)` 改为 `res = build_weights(p, start, end, with_trace=True)`，`weights = res.weights`；随后 `observability.write(out, *observability.build_frames(res.days, res.traces, <sig 不可得，改为 build_frames 内部需要 sig>)`。

> 实现细节裁决：`ticker_signals` 需要 `sig` 面板（m21/m60/zbias/llt80），而 `sig` 目前是 `build_weights` 内部缓存。为避免重复预计算，`BuildResult` 增加 `sig: dict` 字段（`with_trace=True` 时携带），`build_frames` 从 `res.sig` 取面板；`run_backtest.py` 无需自己算信号。

- [ ] **Step 1: 写失败测试**

`tests/test_observability.py`：

```python
import numpy as np
import pandas as pd
from etf_rotation import config
from etf_rotation.evaluation import observability
from etf_rotation import pipeline as pipe


def test_build_frames_shapes_and_status():
    p = config.load_params()
    res = pipe.build_weights(p, "2024-01-01", "2024-06-30", with_trace=True)
    diary, tk = observability.build_frames(res.days, res.traces, res.sig, p)
    assert len(diary) == len(res.days)
    assert {"regime", "risk_budget", "total_weight", "cash_weight", "hysteresis_held"} <= set(diary.columns)
    assert set(tk.index.names) == {"date", "ticker"}
    assert {"m21", "m60", "score", "zbias", "weight", "status", "overheat_ratio"} <= set(tk.columns)
    # 持仓标的的 status 覆盖 held_risk / nasdaq / gold / defensive 中的至少一类
    assert not tk["status"].isna().all()


def test_ticker_signals_only_held_and_candidates():
    p = config.load_params()
    res = pipe.build_weights(p, "2024-01-01", "2024-06-30", with_trace=True)
    _, tk = observability.build_frames(res.days, res.traces, res.sig, p)
    # 任一日的 ticker 数不超过 候选上限(3*max_holdings) + 纳指/黄金 + 防守数
    assert tk.groupby(level="date").size().max() <= 3 * p["dedupe"]["max_holdings"] + 10
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_observability.py -q`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现**

按接口实现 `build_frames` / `write`；`run_backtest.py` 切 `with_trace=True` 并落盘（注意用 `warnings.catch_warnings()` 屏蔽宽表 PerformanceWarning，沿用现有写法）。

- [ ] **Step 4: pytest + 冒烟 + 回归**

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
.venv\Scripts\python.exe -c "import pandas as pd; d=pd.read_parquet('reports/signals/decision_diary.parquet'); t=pd.read_parquet('reports/signals/ticker_signals.parquet'); print('diary', d.shape, 'tickers', t.shape)"
.venv\Scripts\python.exe -c "import pandas as pd, json; assert pd.read_parquet('reports/weights.parquet').equals(pd.read_parquet('reports/weights.baseline.parquet')); assert json.load(open('reports/metrics.json',encoding='utf-8'))==json.load(open('reports/metrics.baseline.json',encoding='utf-8')); print('IDENTICAL')"
```

Expected: pytest 全绿；两张 parquet 生成且形状合理；`IDENTICAL`。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/evaluation/observability.py scripts/run_backtest.py tests/test_observability.py
git commit -m "feat: persist decision diary and per-ticker signal snapshot (held+candidates)"
```

---

## Part 2：可视化与报告集成

### Task 4: plots 新增信号/决策图

**Files:**
- Modify: `src/etf_rotation/evaluation/plots.py`
- Test: `tests/test_observability.py`（图对象冒烟：返回 `go.Figure` 且非空）

**Interfaces（均返回 `go.Figure`，复用 `_style`）：**
- `plots.market_state_timeline(diary: pd.DataFrame, nav: pd.Series) -> go.Figure`：背景按 regime 分色带（bull/range/bear）+ comp_score 折线 + ±0.30 阈值虚线，副轴叠加策略净值（观察「市场状态切换 → 风险预算变化 → 净值」的联动）。
- `plots.risk_budget_stack(diary: pd.DataFrame) -> go.Figure`：风险/纳指/黄金/防守/现金五类逐日堆叠面积图（`risk = total_weight - nasdaq - gold - defensive`，`cash = 1 - total_weight`），直观看到市场状态/风控如何把资金在五类间搬移。
- `plots.signal_trends(tk: pd.DataFrame, ticker: str) -> go.Figure`：单标的 5 行子图（m21/m60、score、zbias+rev_active 标记、close vs llt80 + overheat_ratio 与 1.2 阈值线、weight），用于逐标的信号趋势 drill-down。
- `plots.trade_triggers(diary: pd.DataFrame, trades: pd.DataFrame) -> go.Figure`：事件标记图——regime 切换点、`hysteresis_held=False`（换仓）点、`n_overheat_exits>0` 点、`vol_cap_scale<1` 点叠加在净值上，配合按日聚合的买入/卖出交易量（信号 T 日 → 成交 T+1，图上注明偏移）。

- [ ] **Step 1: 写冒烟测试**

```python
def test_signal_plot_figures_build():
    import plotly.graph_objects as go
    p = config.load_params()
    res = pipe.build_weights(p, "2024-01-01", "2024-06-30", with_trace=True)
    diary, tk = observability.build_frames(res.days, res.traces, res.sig, p)
    nav = pd.Series(1.0, index=res.days)  # 占位，仅测构造
    for fig in (plots.market_state_timeline(diary, nav),
                plots.risk_budget_stack(diary),
                plots.signal_trends(tk, tk.index.get_level_values("ticker")[0])):
        assert isinstance(fig, go.Figure) and len(fig.data) > 0
```

- [ ] **Step 2: 运行确认失败** → Run `-m pytest tests/test_observability.py -q`，Expected FAIL（函数不存在）。
- [ ] **Step 3: 实现** → 在 `plots.py` 追加四个函数，复用 `FONT`/`_style`/调色板。
- [ ] **Step 4: pytest + Commit**

```powershell
.venv\Scripts\python.exe -m pytest tests -q
git add src/etf_rotation/evaluation/plots.py tests/test_observability.py
git commit -m "feat: signal/decision plots (market state, risk budget, signal trend, trade triggers)"
```

### Task 5: run_report 集成「信号与决策」章节

**Files:**
- Modify: `scripts/run_report.py`
- Modify: `src/etf_rotation/evaluation/plots.py`（`write_report` 无需改，章节经 `sections` 列表注入）

**Interfaces:**
- `run_report.py` 在 `sections` 末尾追加两组图：市场状态/风险预算（用 `decision_diary.parquet`）、交易触发事件（用 `trades.csv` 聚合 + `decision_diary`）；并输出一份「信号趋势」多标的页（默认 top 持仓标的，附带结构化 parquet 路径说明）。
- 缺失 `reports/signals/*.parquet` 时优雅降级（打印 WARNING 并跳过该章节，不报错），保证旧产物下 `run_report.py` 仍可运行。

- [ ] **Step 1: 实现** → `run_report.py` 读 `decision_diary.parquet`、`ticker_signals.parquet`、`trades.csv`，构建章节；`_build_md` 在自动段落追加「信号快照」入口（`signals/decision_diary.parquet`、`signals/ticker_signals.parquet` 链接/说明）。
- [ ] **Step 2: 冒烟 + Commit**

```powershell
.venv\Scripts\python.exe scripts\run_report.py
git add scripts/run_report.py
git commit -m "feat: integrate signal/decision section into report"
```

Expected：`reports/可视化报告.html` 多出「市场状态与风险预算」「信号趋势」「交易触发事件」章节；`reports/回测报告.md` 自动段落多出信号快照入口；`reports/` 无 parquet 时仍可运行。

---

## 不在本计划范围（见 TODO.md）

- 阶段三代码卫生其余项（3.1 五相位、3.3 可投资池、3.4 `weights.shift` 抽公共、3.5 现金资产决策、3.6 持仓现金口径、3.7 run_id 执行口径、3.8 陈旧代码清理、3.9 其余硬编码参数接线）——不改变数值的小任务，排在可观测化之后。
- 阶段四文档维护（4.1 README 指标、4.2 分支名、4.3 重复文档、4.4 版本号）——排在可观测化之后；本计划落盘后 `reports/signals/` 说明可顺带写入 README（一并归入 4.1/4.4 处理）。
- 全市场全标的信号面板（用户已裁定范围 = 持仓+候选+关键决策点）；如需完整排名分布，后续把 `risk_score` 全池面板另存一份即可（本计划不存，控制体积）。

## 执行顺序与依赖

Task 1（收敛）→ Task 2（trace 采集）→ Task 3（落盘）→ Task 4（绘图）→ Task 5（集成）为顺序依赖：Task 3 依赖 Task 2 的 `BuildResult`；Task 4 依赖 Task 3 的两张 parquet 数据模型；Task 5 依赖 Task 4 的图函数。Task 1/2 为行为不变重构，完成后先确认 `IDENTICAL` 再进入落盘/绘图阶段。

## 最终验收 checklist（reviewer 用，不依赖执行过程）

- [ ] `.venv\Scripts\python.exe -m pytest tests -q` 全绿（含新增 `test_trend.py` 等价性、`test_observability.py`）。
- [ ] `.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31` 后 `weights.parquet`/`metrics.json` 与基线逐值一致（观测层未改变数值）。
- [ ] `reports/signals/decision_diary.parquet` 与 `ticker_signals.parquet` 生成，列符合数据模型；ticker 子集 = 持仓+候选+过热退出+纳指/黄金+防守。
- [ ] 无前视抽查：trace 只取 `_daily_target` 当日已算值；`zbias`/`llt80` 等面板在 `_precompute_signals` 内已 `.shift(1)`；`ticker_signals` 仅 `.loc[d, ticker]` 索引取数。
- [ ] `run_report.py` 生成的报告含「信号与决策」章节，且缺 parquet 时优雅降级。
- [ ] `.env` token 未打印/提交；`data/` 未入库；`reports/signals/` 与 `reports/` 其他生成物处理一致。
