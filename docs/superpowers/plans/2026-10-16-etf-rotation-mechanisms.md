# 机制补全 Implementation Plan（先补机制，再调参）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task in a single session（不建议 subagent-driven，见文末「审核验证」）。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把设计文档里已实现但尚未接入主流水线的四个权重面板机制（组合 34% 波动上限、反转、单 ETF 过热退出、整组迟滞）逐个接入 `pipeline.build_weights`，再在 bt 框架内用一个自定义 `OpenRebalance` Algo 补齐 T+1 开盘/跳空/停牌的执行精度；每个机制单独验证、单独 commit、记录指标增量，最后形成可审计的「机制 → 数值变化」归因表。

**Architecture:** 四个权重面板机制只改 `pipeline.py` 的目标权重计算，不动 bt 引擎；执行精度用 bt 框架内的自定义 Algo 实现（标准 `Rebalance` 是单价格模型，成交与估值共用同一价格，无法「开盘成交 + 收盘估值」，但 `Security.transact(q, price=open)` 留了自定义成交价的旁路）。所有滚动统计量 `.shift(1)`，T 日信号、T+1 成交，禁止未来信息。

**Tech Stack:** Python 3.10 / pandas 2.3 / numpy 2.2 / bt 1.2.2 / pytest。

**Spec:**
- `docs/superpowers/specs/2026-10-10-etf-rotation-design.md`（§2.3 反转、§2.6 波动率、§2.7 过热、§2.8 执行、H4/H5/H6）
- `AGENTS.md`（先补机制再调参的用户决定；回测纪律）
- `reports/回测报告.md`（当前基准 12.48% / -12.98% / 0.96，作为机制接入前的基线）
- `TODO.md`（阶段一 = 本计划）

## Global Constraints

- 所有 Python 统一用 `.venv\Scripts\python.exe`；运行前先 `$env:PYTHONIOENCODING="utf-8"`。
- 滚动统计量一律 `.shift(1)`；T 日信号、T+1 成交；禁止未来信息。
- 每个机制一次只动一个；接入后立刻跑 `.venv\Scripts\python.exe -m pytest tests -q` 与 `scripts\run_backtest.py 2019-01-01 2026-07-31`，并把 `reports/metrics.json` 变化写进 commit message。
- 本计划会改变策略数值（这是目的）；「数值不变」约束只适用于每个任务内部的抽取/重构步骤——先锁定基线、再开关机制。
- 回测评估指标唯一来源 = bt 内置统计；执行精度的自定义 Algo 仍由 bt 产出 NAV/现金/费用/成交明细/统计，不另起炉灶重写记账引擎。
- `.env` 的 tushare token 不得打印/提交/写日志；`data/` 已被 gitignore。
- 当前分支 `main`。

---

## Part A：四个权重面板机制（顺序执行）

顺序：Task 1 组合 34% 波动上限 → Task 2 单 ETF 过热退出 → Task 3 反转接入 → Task 4 整组迟滞。前者不依赖排名分，后者依赖 Task 3 引入的 `score`，故放在最后。

每个 Task 都遵循同一节奏：锁基线 → 写失败测试（纯函数）→ 实现并接线 → pytest 全绿 + 全量回归 + 记录指标增量 → commit（commit message 含增量）。

### Task 1: 组合 34% 波动上限（只减不加）

**Files:**
- Modify: `src/etf_rotation/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `pipeline._apply_portfolio_vol_cap(candidate: pd.Series, port_rets: list[float], params: dict) -> tuple[pd.Series, float]`。
- 语义：组合 20 日 EWMA 波动超过 34% 时，把当日目标权重整体等比缩减（差额转现金）；低于 34% 不放大。与设计 §2.6「超目标同比缩减，只减不加」一致。**不用 `bt.algos.TargetVol`**（其是双向目标，会把低于目标的组合放大，与设计冲突）。

- [ ] **Step 1: 锁基线**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
Copy-Item reports\metrics.json reports\metrics.before_task1.json
```

- [ ] **Step 2: 写失败测试**

`tests/test_pipeline.py` 追加：

```python
import numpy as np
import pandas as pd

import etf_rotation.pipeline as pipe
from etf_rotation import config


def test_portfolio_vol_cap_only_shrinks():
    params = config.load_params()
    cand = pd.Series({"A": 0.5, "B": 0.3})
    rets_high = [0.05, -0.05, 0.06, -0.06] * 5
    out_high, scale_high = pipe._apply_portfolio_vol_cap(cand, rets_high, params)
    assert scale_high < 1.0 and (out_high <= cand).all()
    rets_low = [0.0001, -0.0001] * 5
    out_low, scale_low = pipe._apply_portfolio_vol_cap(cand, rets_low, params)
    assert scale_low == 1.0 and (out_low == cand).all()
```

- [ ] **Step 3: 运行确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py::test_portfolio_vol_cap_only_shrinks -q`
Expected: FAIL（`_apply_portfolio_vol_cap` 不存在）。

- [ ] **Step 4: 实现**

`pipeline.py` 新增：

```python
def _apply_portfolio_vol_cap(candidate, port_rets, params):
    """组合 20 日 EWMA 波动上限（只减不加）：超 34% 时整体等比缩减。"""
    target = params["risk"]["vol_target_portfolio"]
    span = params["risk"]["port_vol_window"]
    vol = 0.0
    if port_rets:
        vol = float(pd.Series(port_rets).ewm(span=span, adjust=False).std().iloc[-1] * np.sqrt(252))
    scale = risk_layers.vol_scale(vol, target) if pd.notna(vol) and vol > 0 else 1.0
    return candidate * scale, scale
```

改 `build_weights` 的循环（无前视说明：`port_rets` 每次 append 的是「上一日权重 × 当日收益」，只用 ≤d 的信息）：

```python
    prev_final = pd.Series(0.0, index=cols)
    port_rets: list[float] = []
    for i, d in enumerate(days):
        target, last_def_update, current_defn = _daily_target(
            i, d, sig, params, last_def_update, current_defn)
        phase_weights[i % 5] = pd.Series(target).reindex(cols).fillna(0.0)
        candidate = _combine_phases(phase_weights)
        if i > 0:
            prev_ret = float((prev_final * sig["ret"].loc[d, cols].fillna(0.0)).sum())
            port_rets.append(prev_ret)
        final, _ = _apply_portfolio_vol_cap(candidate, port_rets, params)
        weights.loc[d, final.index] = final.values
        prev_final = final
```

- [ ] **Step 5: pytest + 全量回归 + 记录增量**

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
.venv\Scripts\python.exe -c "import json; a=json.load(open('reports/metrics.before_task1.json',encoding='utf-8')); b=json.load(open('reports/metrics.json',encoding='utf-8')); print({k: (a.get(k), b.get(k)) for k in ['ann_return','max_drawdown','sharpe','calmar','turnover','total_fees']})"
```

Expected: pytest 全绿；打印 Task 1 前后指标对比。把对比写入 commit message。

- [ ] **Step 6: Commit**

```powershell
git add src/etf_rotation/pipeline.py tests/test_pipeline.py
git commit -m "feat: portfolio 34% vol cap (shrink-only) [ann_return X->Y, maxDD ...]"
```

### Task 2: 单 ETF 过热退出

**Files:**
- Modify: `src/etf_rotation/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `pipeline._apply_overheat(target: dict, close_d: pd.Series, llt80_d: pd.Series, pct: float) -> dict`。
- 语义：风险 ETF 收盘价 ≥ 自身 80 日 LLT × (1 + 20%) 时，该 ETF 权重归零（与 `risk_layers.overheat_mask` 的 `>=` 一致）。

- [ ] **Step 1: 写失败测试**

`tests/test_pipeline.py` 追加：

```python
def test_apply_overheat_removes_overheated():
    target = {"A": 0.3, "B": 0.2}
    close_d = pd.Series({"A": 12.0, "B": 10.0})
    llt80_d = pd.Series({"A": 10.0, "B": 10.0})
    out = pipe._apply_overheat(target, close_d, llt80_d, 0.2)
    assert "A" not in out and out["B"] == 0.2
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py::test_apply_overheat_removes_overheated -q`
Expected: FAIL（函数不存在）。

- [ ] **Step 3: 实现**

`_precompute_signals` 增加每只风险 ETF 的 80 日 LLT（列式 apply，性能交给阶段二的缓存；复用既有 `ms.llt` 与 `params["risk"]["llm80_alpha"]`），并把 `close` 一并放进 sig：

```python
    llt80 = close[risk_tickers].apply(lambda s: ms.llt(s, params["risk"]["llm80_alpha"]))
    ...
    return dict(..., llt80=llt80, close=close)
```

`pipeline.py` 新增：

```python
def _apply_overheat(target, close_d, llt80_d, pct):
    out = dict(target)
    for t in list(out):
        c, l = close_d.get(t), llt80_d.get(t)
        if pd.notna(c) and pd.notna(l) and c >= l * (1 + pct):
            out.pop(t, None)
    return out
```

`_daily_target` 在风险资产 HRP 配权块结束后、纳指/黄金块之前调用：

```python
    target = _apply_overheat(
        target, sig["close"].loc[d], sig["llt80"].loc[d],
        params["risk"]["overheat_pct"])
```

- [ ] **Step 4: pytest + 全量回归 + 记录增量**

同 Task 1 Step 5 的节奏（基线为 Task 1 后的 `reports/metrics.json`）。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/pipeline.py tests/test_pipeline.py
git commit -m "feat: per-ETF overheat exit (80d LLT x 1.2) [ann_return X->Y, ...]"
```

### Task 3: 反转信号接入主线

**Files:**
- Modify: `src/etf_rotation/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `pipeline._range_score(mom_rank: pd.Series, zbias: pd.Series, active: pd.Series) -> pd.Series`（动量分/反转分各自横截面 z-score 后 50/50 相加，H5）。
- 语义：仅震荡市（range）用反转；`反转分 = -ZBias` 且只在激活（ZBias ≤ -0.5 且负偏离较 3 日前收窄）时非零，其余为 0（H6）；21 日动量为负仍先剔除。

- [ ] **Step 1: 写失败测试**

`tests/test_pipeline.py` 追加：

```python
def test_range_score_boosts_active_oversold():
    mom = pd.Series({"A": 0.5, "B": 0.5})
    zbias = pd.Series({"A": -1.0, "B": 0.0})
    active = pd.Series({"A": True, "B": False})
    score = pipe._range_score(mom, zbias, active)
    assert score["A"] > score["B"]


def test_range_score_no_active_falls_back_to_momentum_order():
    mom = pd.Series({"A": 0.9, "B": 0.1})
    zbias = pd.Series({"A": 0.0, "B": 0.0})
    active = pd.Series({"A": False, "B": False})
    score = pipe._range_score(mom, zbias, active)
    assert score["A"] > score["B"]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -k range_score -q`
Expected: FAIL（函数不存在）。

- [ ] **Step 3: 实现**

`_precompute_signals` 增加向量化 ZBias 面板与激活面板（不做列式 apply，直接用 pandas 面板运算）：

```python
    ema = close[risk_tickers].ewm(span=params["reversal"]["ema_span"], adjust=False).mean()
    logbias = np.log(close[risk_tickers] / ema)
    mu = logbias.rolling(params["reversal"]["z_window"]).mean().shift(1)
    sd = logbias.rolling(params["reversal"]["z_window"]).std().shift(1)
    zbias = (logbias - mu) / sd
    rev_active = (zbias <= params["reversal"]["zbias_threshold"]) & (
        zbias > zbias.shift(params["reversal"]["repair_lookback"]))
```

`return dict(..., zbias=zbias, rev_active=rev_active)`。

`pipeline.py` 新增：

```python
def _zscore(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=0)
    return (s - s.mean()) / sd if sd > 0 else pd.Series(0.0, index=s.index)


def _range_score(mom_rank, zbias, active):
    rev = (-zbias).where(active, 0.0)
    return _zscore(mom_rank) + _zscore(rev)
```

`_daily_target` 的横截面排名段改为：

```python
            mom = 0.7 * m21.loc[d, elig].rank(pct=True) + 0.3 * m60.loc[d, elig].rank(pct=True)
            mom = mom[m21.loc[d, elig] > 0]
            if regime.loc[d] == "range":
                score = _range_score(mom, sig["zbias"].loc[d, mom.index],
                                     sig["rev_active"].loc[d, mom.index])
            else:
                score = mom
            cands = list(score.sort_values(ascending=False).index[: 3 * params["dedupe"]["max_holdings"]])
```

（原变量名 `m` 改为 `score`，后续 `cands` 来源同步改为 `score`。）

- [ ] **Step 4: pytest + 全量回归 + 记录增量**

同 Task 1 Step 5 节奏（基线为 Task 2 后）。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/pipeline.py tests/test_pipeline.py
git commit -m "feat: wire reversal signal into range-market ranking [ann_return X->Y, ...]"
```

### Task 4: 整组迟滞

**Files:**
- Modify: `src/etf_rotation/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `pipeline._apply_hysteresis(candidate: pd.Series, prev_final: pd.Series, score: pd.Series, risk_tickers: list[str], improve: float) -> pd.Series`。
- 语义（H4）：以「风险轮动组」为迟滞口径。`score` 为当日风险池横截面排名分；新组合得分 = 候选组合中风险标的的 score 之和，旧组合得分 = 当前持仓中风险标的的 score 之和。新得分 ≤ 旧得分 × 1.02 且原风险持仓仍有效（都在当日 score 索引中）时维持旧组合，否则切换。

- [ ] **Step 1: 写失败测试**

`tests/test_pipeline.py` 追加：

```python
def test_hysteresis_holds_when_no_improvement():
    candidate = pd.Series({"B": 1.0})
    prev = pd.Series({"A": 1.0})
    score = pd.Series({"A": 0.80, "B": 0.81})
    out = pipe._apply_hysteresis(candidate, prev, score, ["A", "B"], 0.02)
    pd.testing.assert_series_equal(out, prev)


def test_hysteresis_switches_when_improves():
    candidate = pd.Series({"B": 1.0})
    prev = pd.Series({"A": 1.0})
    score = pd.Series({"A": 0.80, "B": 0.90})
    out = pipe._apply_hysteresis(candidate, prev, score, ["A", "B"], 0.02)
    pd.testing.assert_series_equal(out, candidate)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -k hysteresis -q`
Expected: FAIL（函数不存在）。

- [ ] **Step 3: 实现**

`pipeline.py` 新增：

```python
def _apply_hysteresis(candidate, prev_final, score, risk_tickers, improve):
    held_risk = [t for t in prev_final.index if prev_final[t] > 0 and t in risk_tickers]
    if not held_risk or not all(pd.notna(score.get(t)) for t in held_risk):
        return candidate
    new_score = float(score.reindex(candidate[candidate > 0].index).dropna().sum())
    old_score = float(score.reindex(held_risk).sum())
    if new_score <= old_score * (1 + improve):
        return prev_final
    return candidate
```

`_daily_target` 返回值扩展为 `(target, last_def_update, current_defn, score, keep)`：`score` 为覆盖 `risk_tickers` 的当日排名分（可投资且 m21>0 者填值，否则 NaN），`keep` 为最终入选风险标的列表。`build_weights` 调用点与循环改为：

```python
    prev_final = pd.Series(0.0, index=cols)
    port_rets: list[float] = []
    improve = params["execution"]["hysteresis_improve"]
    for i, d in enumerate(days):
        target, last_def_update, current_defn, score, keep = _daily_target(
            i, d, sig, params, last_def_update, current_defn)
        phase_weights[i % 5] = pd.Series(target).reindex(cols).fillna(0.0)
        candidate = _combine_phases(phase_weights)
        candidate = _apply_hysteresis(
            candidate, prev_final, score, sig["risk_tickers"], improve)
        if i > 0:
            prev_ret = float((prev_final * sig["ret"].loc[d, cols].fillna(0.0)).sum())
            port_rets.append(prev_ret)
        final, _ = _apply_portfolio_vol_cap(candidate, port_rets, params)
        weights.loc[d, final.index] = final.values
        prev_final = final
```

- [ ] **Step 4: pytest + 全量回归 + 记录增量**

同 Task 1 Step 5 节奏（基线为 Task 3 后）。跑完后把四个机制的累计变化写入 `reports/回测报告.md` 的「机制接入归因」小节（新增表格：机制 / 年化 / 回撤 / Sharpe / Calmar / 换手 / total_fees）。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/pipeline.py tests/test_pipeline.py reports/回测报告.md
git commit -m "feat: group-level hysteresis on risk rotation [ann_return X->Y, ...]"
```

---

## Part B：执行精度（bt 框架内自定义 OpenRebalance，不自研记账引擎）

bt 的标准 `Rebalance` 是「单价格模型」：每标的每根 bar 只有一个价格，成交与估值共用它，所以官方算法链只能「开盘成交 + 开盘估值」或「收盘成交 + 收盘估值」，做不到「开盘成交 + 收盘估值」。但 bt 底层留了旁路：`Security.transact(q, price=open)` 支持自定义成交价（前置条件是 setup 时传了 `bidoffer`，哪怕全 0），现金按自定义价结算、持仓仍按 bar 价（收盘）估值。因此正确做法是写一个自定义 `bt.algos.Algo`（OpenRebalance）替代标准 `Rebalance`，叠加跳空顺延与停牌状态；NAV/现金/费用/成交明细/统计仍全部由 bt 产出（「评估指标唯一来源=bt」不变）。不另起炉灶重写记账引擎。

**Files:**
- Create: `src/etf_rotation/backtest/open_rebalance.py`
- Modify: `src/etf_rotation/backtest/run.py`（`run(..., execution="close"|"open")`；open 模式换 `OpenRebalance` 并传 `bidoffer` 零矩阵 + `open_price`）
- Modify: `scripts/run_backtest.py`（`--execution close|open`，默认 `close`）
- Test: `tests/test_open_rebalance.py`

**Interfaces:**
- Produces: `open_rebalance.OpenRebalance(gap_delay_pct=0.01)`。
- 成交规则（T 日信号、T+1 成交）：按 T+1 开盘价成交；买入增量满足 `open[T+1]/close[T] - 1 >= gap_delay_pct` 时该笔买入顺延一日；`open[T+1]` 为 NaN（停牌/无成交）时该标的当日不成交、顺延；卖出不受跳空影响；成交后按收盘价估值。
- 安全网（等价性）：`execution="open"` 且 `open_price == close_price` 时，nav/fees 必须与 `execution="close"`（标准 Rebalance）一致（容差 1e-9；若浮点漂移可放宽到 1e-6，但必须先查清来源，不得只放宽不管）。

### Task 5: OpenRebalance 骨架 + close 等价性

- [ ] **Step 1: 写失败测试**

`tests/test_open_rebalance.py`：

```python
import numpy as np
import pandas as pd

from etf_rotation.backtest import run


def test_open_rebalance_matches_close_when_open_equals_close():
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    rng = np.random.default_rng(0)
    close = pd.DataFrame({
        "A": np.cumprod(1 + rng.normal(0, 0.008, len(idx))),
        "B": np.cumprod(1 + rng.normal(0, 0.006, len(idx))),
    }, index=idx)
    w = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    eff = w.shift(1).fillna(0.0)
    base = run.run(eff, close, close, cost_bps=8, cash_rate=0.018, execution="close")
    opn = run.run(eff, close, close, cost_bps=8, cash_rate=0.018, execution="open")
    pd.testing.assert_series_equal(base.nav, opn.nav, rtol=1e-9, atol=1e-9)
    assert abs(base.fees.sum() - opn.fees.sum()) < 1e-9
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_open_rebalance.py -q`
Expected: FAIL（`run` 无 `execution` 参数 / `OpenRebalance` 不存在）。

- [ ] **Step 3: 实现**

`open_rebalance.py` 核心（参照 `bt.core.SecurityBase.allocate` 的「权重差 → 数量 → 佣金闭环」，只是成交价换成开盘价；务必复刻佣金闭环，不能简单 `q = amount / price`，否则比例佣金会差一点现金）：

```python
import numpy as np
import pandas as pd
import bt


class OpenRebalance(bt.algos.Algo):
    def __init__(self, gap_delay_pct=0.01):
        super().__init__()
        self.gap_delay_pct = gap_delay_pct
        self._pending = {}  # ticker -> 顺延买入的权重

    def __call__(self, target):
        weights = target.temp.get("weights")
        if weights is None:
            return True
        open_px = target.get_data("open_price")
        close_px = target.get_data("close_price")
        now = target.now
        base = target.value
        if "cash" in target.temp and not target.fixed_income:
            base *= 1 - target.temp["cash"]
        # 平掉不在目标内的持仓（与 Rebalance 相同）
        for cname in list(target.children):
            if cname in weights:
                continue
            c = target.children[cname]
            if c.value != 0.0 and not np.isnan(c.value):
                target.close(cname, update=False)
        # 合并顺延买入
        merged = dict(weights)
        for t, w in list(self._pending.items()):
            merged[t] = max(merged.get(t, 0.0), w)
            self._pending.pop(t, None)
        for ticker, w in merged.items():
            op = open_px.loc[now, ticker]
            target._create_child_if_needed(ticker)
            c = target.children[ticker]
            if pd.isna(op):
                if w > c.weight:
                    self._pending[ticker] = w
                continue
            delta = w - c.weight
            if delta > 0:
                pc = close_px.shift(1).loc[now, ticker]
                if pd.notna(pc) and op / pc - 1 >= self.gap_delay_pct:
                    self._pending[ticker] = w
                    continue
            self._transact_at(target, c, delta * base, op)
        target.root.update(now)
        return True

    def _transact_at(self, target, child, amount, price):
        # 佣金闭环：参照 SecurityBase.allocate，把成交价换成开盘价后求 q
        q = amount / (price * child.multiplier)
        child.transact(q, update=False, price=price)
```

`run.py`：`run(..., execution="close")` 用现有算法链；`execution="open"` 时把 `bt.algos.Rebalance()` 换成 `OpenRebalance(params["execution"]["gap_delay_pct"])`，并在 `additional_data` 里加 `"bidoffer": pd.DataFrame(0.0, index=close_price.index, columns=close_price.columns)` 与 `"open_price": open_price`、`"close_price": close_price`（三者都与 bt 预处理后的 universe 同 index/columns）。注意 `_transact_at` 里的简化 `q` 需替换为与 `allocate` 相同的佣金闭环（比例佣金闭式解：买入 `q = amount / (price*(1+rate))`、卖出 `q = amount / (price*(1-rate))`），以等价性测试通过为准。

- [ ] **Step 4: 跑通等价性测试**

Run: `.venv\Scripts\python.exe -m pytest tests/test_open_rebalance.py -q`
Expected: PASS。若 nav/fees 有 1e-6 级漂移，追到佣金闭环或子节点创建差异并修正；不得只放宽容差。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/backtest/open_rebalance.py src/etf_rotation/backtest/run.py tests/test_open_rebalance.py
git commit -m "feat: OpenRebalance algo matching bt Rebalance when open==close"
```

### Task 6: T+1 开盘成交

- [ ] **Step 1: 写失败测试**

```python
def test_open_fill_differs_from_close_fill():
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    w = pd.DataFrame({"X": [0.0, 1.0]}, index=idx)
    opn = pd.DataFrame({"X": [10.0, 11.0]}, index=idx)
    close = pd.DataFrame({"X": [10.0, 10.0]}, index=idx)
    res = run.run(w, opn, close, cost_bps=0, cash_rate=0, execution="open")
    # 第 2 日以 11.0 买入、收盘 10.0 估值，净值应 < 1
    assert res.nav.iloc[-1] < 1.0
```

- [ ] **Step 2: 实现**

确认 `run(..., execution="open")` 传入真实开盘价：成交用 open、估值用 close（bt 按 universe 收盘价估值，本任务只需把 open 正确传进 `additional_data` 供 Algo 读取）。

- [ ] **Step 3: pytest + commit**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_open_rebalance.py -q
git add src/etf_rotation/backtest/open_rebalance.py src/etf_rotation/backtest/run.py tests/test_open_rebalance.py
git commit -m "feat: fill at T+1 open with close marking"
```

### Task 7: 跳空顺延与停牌

- [ ] **Step 1: 写失败测试**

```python
def test_gap_delay_postpones_buy():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    w = pd.DataFrame({"X": [0.0, 1.0, 1.0]}, index=idx)
    opn = pd.DataFrame({"X": [10.0, 10.2, 10.2]}, index=idx)
    close = pd.DataFrame({"X": [10.0, 10.0, 10.0]}, index=idx)
    res = run.run(w, opn, close, cost_bps=0, cash_rate=0, execution="open")
    assert res.positions["X"].iloc[1] == 0.0
    assert res.positions["X"].iloc[2] == 1.0


def test_suspended_skips_fill():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    w = pd.DataFrame({"X": [0.0, 1.0, 1.0]}, index=idx)
    opn = pd.DataFrame({"X": [10.0, np.nan, 10.5]}, index=idx)
    close = pd.DataFrame({"X": [10.0, 10.0, 10.5]}, index=idx)
    res = run.run(w, opn, close, cost_bps=0, cash_rate=0, execution="open")
    assert res.positions["X"].iloc[1] == 0.0
    assert res.positions["X"].iloc[2] == 1.0
```

- [ ] **Step 2: 实现**

OpenRebalance 已在 Task 5 内置 `_pending`；本任务验证并完善：跳空顺延只延「买入增量」，卖出照常；停牌（open NaN）当日跳过、次日再试；`volume=0` 若数据含 volume 则同样视作停牌。

- [ ] **Step 3: 全量回归 + 切换开关**

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --execution open
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --execution close
```

把 `open` 与 `close` 两种执行的指标差写入 `reports/回测报告.md`；验证通过后由用户决定是否把 `--execution` 默认值切到 `open`。

- [ ] **Step 4: Commit**

```powershell
git add src/etf_rotation/backtest/open_rebalance.py src/etf_rotation/backtest/run.py scripts/run_backtest.py tests/test_open_rebalance.py reports/回测报告.md
git commit -m "feat: gap delay and suspension in OpenRebalance"
```

---

## Part C：机制补全完成后 → 进入调参

Part A/B 全部完成并验证后，按 `docs/superpowers/plans/2026-10-16-etf-rotation-tuning.md` 执行阶段二「调参与稳健性」。注意：调参前先重跑一遍基线（机制已变，原 12.48% 基线作废，以机制补全后的 `metrics.json` 为新基线）。

## 最终验收 checklist（reviewer 用，不依赖执行过程）

- [ ] `.venv\Scripts\python.exe -m pytest tests -q` 全绿。
- [ ] `.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31` 可复现，且与计划/报告记录的最终指标一致。
- [ ] `git log --oneline` 每个机制一个 commit，commit message 含「机制 → 指标增量」。
- [ ] 无前视抽查：`pipeline.py` 中 `_apply_portfolio_vol_cap` 的 `port_rets` 只用 ≤T 数据；`zbias` 的均值/标准差 `.shift(1)`；信号取数用 `.loc[d]`。
- [ ] 34% 是「只减不加」上限（不是双向目标）；反转只进 range 市；迟滞只在原风险持仓仍有效时维持。
- [ ] `OpenRebalance` 通过 `tests/test_open_rebalance.py` 的 close 等价性测试（open==close 时 nav/fees 1e-9）。
- [ ] `reports/回测报告.md` 含「机制接入归因」表与更新后的差异说明。
- [ ] `.env` token 未打印/提交；`data/` 未入库。

## 执行顺序与依赖

Part A：Task 1 → 2 → 3 → 4 顺序执行，每步结束都有独立 commit 与指标增量。Part B：Task 5 → 6 → 7，Task 5 的 close 等价性是 6/7 的前置门槛。Part A 与 Part B 相互独立，可各自独立开会话执行；都完成后才进入 Part C（调参）。
