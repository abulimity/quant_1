# 调参与稳健性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **依赖与顺序：** 本计划是阶段二，必须在 `docs/superpowers/plans/2026-10-16-etf-rotation-mechanisms.md`（机制补全）完成并验证后再执行；机制补全会改变策略数值，调参基线以机制补全后的 `reports/metrics.json` 为准，不是 12.48% 的 v1.0.1 旧基线。

**Goal:** 在机制补全后的新基线上完成阶段二「调参与稳健性」：先把未生效参数接线，再提速，然后跑单参数敏感性与二维热力图，做参数组合调试、样本外 re-验证与成本敏感性，最后把结果落盘进报告。

**Architecture:** 保持「pandas 预计算信号 → 目标权重面板 → bt 记账」的整体架构不变。本计划只做三件事：让 `params.yaml` 里已声明但 pipeline 硬编码的参数真正生效（默认值下数值不变）、给信号预计算加缓存以降网格耗时、把敏感性结果（稳健性分数/悬崖/DSR/热力图）落盘并接入报告。不接入任何会改变策略数值的新机制（反转/迟滞/34%/过热/执行精度在 TODO 阶段二）。

**Tech Stack:** Python 3.10 / pandas 2.3 / numpy 2.2 / bt 1.2.2 / plotly 7.1 / PyYAML / pytest。

**Spec:**
- `docs/superpowers/specs/2026-10-10-etf-rotation-design.md`（策略机制、H1–H10、§10 敏感性）
- `AGENTS.md`（阶段目标 1–5、调参纪律：一次只动一个维度、滚动统计量 `.shift(1)`）
- `reports/回测报告.md`（当前基准 12.48% / -12.98% / 0.96）

## Global Constraints

- 所有 Python 统一用 `.venv\Scripts\python.exe`；运行前先 `$env:PYTHONIOENCODING="utf-8"`（Windows GBK）。
- 滚动统计量一律 `.shift(1)`；T 日信号、T+1 成交；禁止未来信息。
- 一次只动一个维度；改完立刻重跑并对比 `reports/metrics.json`，否则无法归因。
- 回测评估指标唯一来源 = bt 内置统计（ffn `Result.stats`），交易/成本/换手以引擎结果为依据。
- 本计划是「调参/提速/落盘」，不得改变默认参数下的策略数值；每个任务结束前用 `pytest` 与基准回测回归。
- `.env` 的 tushare token 不得打印/提交/写日志；`data/` 已被 gitignore。
- 全量单测：`.venv\Scripts\python.exe -m pytest tests -q`；基准回测：`.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31`。
- 当前分支 `main`（AGENTS.md 写 `master` 属陈旧，见 TODO 4.2，不在本计划处理）。

---

## Task 1: 参数接线（默认值下数值不变）

**Files:**
- Modify: `src/etf_rotation/pipeline.py`
- Modify: `src/etf_rotation/portfolio/risk_layers.py`
- Modify: `src/etf_rotation/portfolio/defensive.py`
- Test: `tests/test_pipeline.py`、`tests/test_risk_layers.py`

**Interfaces:**
- Produces: `_precompute_signals` 读取 `params["trend"]["windows"]`、`params["market_state"]["slope_window"]`、`params["risk"]["vol_window"]`。
- Produces: `_daily_target` 读取 `params["trend"]["rank_weights"]`、`params["hrp"]["window"]`。
- Produces: `risk_layers.risk_scale(market, idx_above_llt, idx_drop_20d, drop_threshold=-0.03)`。
- Produces: `defensive.select(returns, vol60, category, top_n=5, max_vol_60d=0.03, momentum_window=60)`。

- [ ] **Step 1: 保存基准产物**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
Copy-Item reports\weights.parquet reports\weights.baseline.parquet
Copy-Item reports\metrics.json reports\metrics.baseline.json
```

- [ ] **Step 2: 写失败测试**

`tests/test_pipeline.py` 追加：

```python
import numpy as np
import pandas as pd

import etf_rotation.pipeline as pipe
from etf_rotation import config


def _synthetic_panels():
    idx = pd.date_range("2023-01-01", periods=140, freq="B")
    a = np.linspace(1.0, 1.4, len(idx))
    b = np.linspace(1.0, 0.9, len(idx))
    close = pd.DataFrame({"513100.SH": a, "518880.SH": b}, index=idx)
    indices = {
        "000001.SH": pd.Series(np.linspace(3000, 3100, len(idx)), index=idx),
        "932000.CSI": pd.Series(np.linspace(2000, 2050, len(idx)), index=idx),
        "000922.CSI": pd.Series(np.linspace(5000, 5050, len(idx)), index=idx),
        "399006.SZ": pd.Series(np.linspace(1800, 1820, len(idx)), index=idx),
    }
    return close, indices


def test_precompute_signals_respects_trend_windows():
    close, indices = _synthetic_panels()
    params = config.load_params()
    params["nasdaq_etf"], params["gold_etf"] = "513100.SH", "518880.SH"
    params["trend"]["windows"] = [21, 63]
    sig = pipe._precompute_signals(
        close, close, close * 1e7, indices, params,
        {"513100.SH": "risk", "518880.SH": "gold"})
    m63 = pipe.momentum_panel(np.log(close), 63)
    pd.testing.assert_frame_equal(sig["m60"], m63)
```

`tests/test_risk_layers.py` 追加（先确认 `risk_layers.risk_scale` 与 `defensive.select` 的默认值等价）：

```python
import pandas as pd
import numpy as np
from etf_rotation.portfolio import risk_layers, defensive


def test_risk_scale_custom_drop_threshold():
    assert risk_layers.risk_scale("bull", False, -0.02, drop_threshold=-0.03) == 1.0
    assert risk_layers.risk_scale("bull", False, -0.04, drop_threshold=-0.03) == 0.05


def test_defensive_select_respects_top_n():
    idx = pd.date_range("2023-01-01", periods=120, freq="B")
    ret = pd.DataFrame(np.random.default_rng(0).normal(0, 0.01, (120, 6)),
                       index=idx, columns=list("ABCDEF"))
    vol = pd.Series([0.01] * 6, index=list("ABCDEF"))
    cat = pd.Series({"A": "bond", "B": "bond", "C": "bond",
                     "D": "bond", "E": "bond", "F": "bond"})
    picked = defensive.select(ret, vol, cat, top_n=3)
    assert len(picked) == 3
```

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py::test_precompute_signals_respects_trend_windows tests/test_risk_layers.py -q`
Expected: FAIL（`risk_scale`/`defensive.select` 无新参数；`_precompute_signals` 仍硬编码 21/60）。

- [ ] **Step 4: 实现**

`pipeline._precompute_signals`：把 `m21 = momentum_panel(logp, 21)`、`m60 = momentum_panel(logp, 60)` 改为：

```python
    w_short, w_long = params["trend"]["windows"]
    m21 = momentum_panel(logp, w_short)
    m60 = momentum_panel(logp, w_long)
```

`vol60` 与三处 60 日 EWMA 波动改为读 `params["risk"]["vol_window"]`（变量 `vw = params["risk"]["vol_window"]`）：

```python
    vol60 = ret.rolling(vw).std() * np.sqrt(252)
    ...
    nas_vol = close[nasdaq].pct_change(fill_method=None).ewm(span=vw).std() * np.sqrt(252)
    gold_vol = close[gold].pct_change(fill_method=None).ewm(span=vw).std() * np.sqrt(252)
    cyb_vol = cyb.pct_change(fill_method=None).ewm(span=vw).std() * np.sqrt(252)
```

市场状态传入 `win=params["market_state"]["slope_window"]`：

```python
    comp = ms.composite_score(
        {"sh": indices["000001.SH"],
         "zz2000": indices["932000.CSI"],
         "zzhl": indices["000922.CSI"]},
        alpha=params["market_state"]["alpha"],
        win=params["market_state"]["slope_window"],
    )
```

`pipeline._daily_target`：把 `0.7 * m21... + 0.3 * m60...` 与 `m[m21 > 0]` 改为读 `params["trend"]["rank_weights"]`；把 `ret[cands].loc[:d].tail(250)` 与 `ret[keep].loc[:d].tail(250)` 的 `250` 改为 `params["hrp"]["window"]`（`w_hrp`）；把 `risk_layers.risk_scale(regime.loc[d], ...)` 加 `drop_threshold=params["risk"]["index_drop_20d"]`；把 `defn.select(ret[def_tickers].loc[:d].tail(250), vol60.loc[d, def_tickers].dropna(), {...})` 改为：

```python
            current_defn = defn.select(
                ret[def_tickers].loc[:d].tail(250),
                vol60.loc[d, def_tickers].dropna(),
                {t: cat.get(t, "risk") for t in def_tickers},
                top_n=params["defensive"]["top_n"],
                max_vol_60d=params["defensive"]["max_vol_60d"],
                momentum_window=params["defensive"]["momentum_window"],
            )
```

`risk_layers.risk_scale` 签名与实现：

```python
def risk_scale(market: str, idx_above_llt: bool, idx_drop_20d: float,
               drop_threshold: float = -0.03) -> float:
    if market == "bear":
        return 0.0
    base = 0.95 if market == "range" else 1.0
    if (not idx_above_llt) and idx_drop_20d < drop_threshold:
        return 0.05
    return base
```

`defensive.select` 签名与实现（把 `0.03`/`5`/`-60` 换成参数）：

```python
def select(returns, vol60, category, top_n: int = 5,
           max_vol_60d: float = 0.03, momentum_window: int = 60) -> list:
    cand = vol60[vol60 < max_vol_60d].index
    cand = [c for c in cand if category.get(c, "risk") in ("bond", "money")]
    rar = returns[cand].iloc[-momentum_window:].mean() / returns[cand].iloc[-momentum_window:].std()
    rar = rar.sort_values(ascending=False)
    picked, seen = [], set()
    for c in rar.index:
        if category.get(c) not in seen:
            picked.append(c)
            seen.add(category.get(c))
        if len(picked) >= top_n:
            break
    return picked
```

- [ ] **Step 5: 运行测试与回归对比**

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
.venv\Scripts\python.exe -c "import pandas as pd, json; assert pd.read_parquet('reports/weights.parquet').equals(pd.read_parquet('reports/weights.baseline.parquet')); assert json.load(open('reports/metrics.json', encoding='utf-8')) == json.load(open('reports/metrics.baseline.json', encoding='utf-8')); print('IDENTICAL')"
```

Expected: pytest 全绿；diff 输出 `IDENTICAL`。

- [ ] **Step 6: Commit**

```powershell
git add src/etf_rotation/pipeline.py src/etf_rotation/portfolio/risk_layers.py src/etf_rotation/portfolio/defensive.py tests/test_pipeline.py tests/test_risk_layers.py
git commit -m "refactor: wire trend/market-state/risk/defensive/hrp params into pipeline"
```

---

## Task 2: 信号预计算缓存（不改数值）

**Files:**
- Modify: `src/etf_rotation/pipeline.py`
- Modify: `scripts/run_grid.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `pipeline.signal_cache_key(params: dict) -> tuple`（只包含影响信号预计算的参数子集）。
- Produces: `pipeline.load_context() -> dict`（模块级缓存 close/opn/amt/indices/fb/cat，重复调用返回同一对象）。
- Modifies: `build_weights(params, start, end, context=None)` 复用缓存后的 `_precompute_signals`。

- [ ] **Step 1: 写失败测试**

`tests/test_pipeline.py` 追加：

```python
def test_signal_cache_key_ignores_cost_and_dedupe():
    p1 = config.load_params()
    p2 = config.load_params()
    p2["costs"]["one_side_bps"] = 16
    p2["dedupe"]["corr_threshold"] = 0.85
    assert pipe.signal_cache_key(p1) == pipe.signal_cache_key(p2)


def test_signal_cache_key_changes_with_window():
    p1 = config.load_params()
    p2 = config.load_params()
    p2["trend"]["windows"] = [21, 63]
    assert pipe.signal_cache_key(p1) != pipe.signal_cache_key(p2)


def test_load_context_is_cached():
    assert pipe.load_context() is pipe.load_context()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pipeline.py -q -k signal_cache_key`
Expected: FAIL（`signal_cache_key` / `load_context` 不存在）。

- [ ] **Step 3: 实现**

`pipeline.py` 顶部新增模块级缓存与两个函数：

```python
_SIGNAL_KEYS = (
    "trend.windows",
    "market_state.alpha",
    "market_state.slope_window",
    "risk.vol_window",
    "risk.llm80_alpha",
    "nasdaq_etf",
    "gold_etf",
)
_CONTEXT_CACHE: dict | None = None
_SIGNAL_CACHE: dict = {}


def signal_cache_key(params: dict) -> tuple:
    """信号预计算只依赖这些参数；其余参数变化不触发重算。"""
    return tuple(_nested(params, k) for k in _SIGNAL_KEYS)


def _nested(params: dict, dotted: str):
    node = params
    for part in dotted.split("."):
        node = node[part]
    return tuple(node) if isinstance(node, list) else node


def load_context() -> dict:
    """一次性加载并缓存价格/指数/基础信息/分类，供 build_weights 复用。"""
    global _CONTEXT_CACHE
    if _CONTEXT_CACHE is None:
        close, opn, amt = load_prices()
        indices = load_indices()
        fb = load_fund_basic()
        cat = univ.classify(fb)
        _CONTEXT_CACHE = {"close": close, "opn": opn, "amt": amt,
                          "indices": indices, "fb": fb, "cat": cat}
    return _CONTEXT_CACHE
```

`build_weights` 改为：

```python
def build_weights(params: dict, start: str, end: str, context: dict | None = None) -> pd.DataFrame:
    ctx = context or load_context()
    close, opn, amt = ctx["close"], ctx["opn"], ctx["amt"]
    indices, cat = ctx["indices"], ctx["cat"]
    days = calendar.trading_days(start, end)
    key = signal_cache_key(params)
    sig = _SIGNAL_CACHE.get(key)
    if sig is None:
        sig = _precompute_signals(close, opn, amt, indices, params, cat)
        _SIGNAL_CACHE[key] = sig
    ...  # 循环部分原样保留
```

`scripts/run_grid.py`：在循环外 `ctx = load_context()`，循环内 `weights = build_weights(p, args.start, args.end, context=ctx)`；把循环外 `close, opn, _ = load_prices()` 换成从 `ctx` 取，避免每个网格点重复读库。

- [ ] **Step 4: 运行测试与回归**

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
.venv\Scripts\python.exe -c "import pandas as pd; assert pd.read_parquet('reports/weights.parquet').equals(pd.read_parquet('reports/weights.baseline.parquet')); print('IDENTICAL')"
```

Expected: pytest 全绿；`IDENTICAL`。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/pipeline.py scripts/run_grid.py tests/test_pipeline.py
git commit -m "perf: cache signal precompute and price context across grid points"
```

---

## Task 3: run_grid 支持列表参数与分维度落盘

**Files:**
- Modify: `src/etf_rotation/evaluation/sensitivity.py`
- Modify: `scripts/run_grid.py`
- Test: `tests/test_sensitivity.py`

**Interfaces:**
- Produces: `sensitivity.parse_grid_spec(spec: str) -> tuple[str, list]`。
- Produces: `run_grid` 每次运行写入 `reports/sensitivity/{key}.json` 与 `reports/sensitivity_summary.json`（保留 `reports/grid.json` 兼容）。

- [ ] **Step 1: 写失败测试**

`tests/test_sensitivity.py` 追加：

```python
def test_parse_grid_spec():
    k, v = sensitivity.parse_grid_spec("dedupe.corr_threshold=0.75,0.80,0.85")
    assert k == "dedupe.corr_threshold" and v == [0.75, 0.80, 0.85]
    k2, v2 = sensitivity.parse_grid_spec("trend.windows=[[21,60],[21,63]]")
    assert k2 == "trend.windows" and v2 == [[21, 60], [21, 63]]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_sensitivity.py::test_parse_grid_spec -q`
Expected: FAIL（函数不存在）。

- [ ] **Step 3: 实现**

`sensitivity.py` 顶部 `import yaml`，新增：

```python
def parse_grid_spec(spec: str) -> tuple[str, list]:
    """--grid 参数解析：标量逗号分隔，或以 [ ... ] 表示的列表参数。"""
    key, raw = spec.split("=", 1)
    raw = raw.strip()
    if raw.startswith("["):
        return key, yaml.safe_load(raw)
    return key, [float(x) for x in raw.split(",")]
```

`scripts/run_grid.py`：用 `sensitivity.parse_grid_spec(spec)` 替换现有 `spec.split("=", 1)` + `[float(x) ...]` 解析；复用 Task 2 的 `load_context()`；结果除写 `reports/grid.json` 外，按维度写：

```python
    sens_dir = ROOT / "reports" / "sensitivity"
    sens_dir.mkdir(exist_ok=True)
    key = list(grid)[0]
    (sens_dir / f"{key.replace('.', '_')}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path = ROOT / "reports" / "sensitivity_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    summary[key] = {"n_trials": n, "robustness": out["robustness"],
                    "cliffs": out["cliffs"], "dsr": out["dsr"],
                    "sharpe_haircut": overfitting.sharpe_haircut(sharpes)}
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: 运行测试与单参数冒烟**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_sensitivity.py -q
.venv\Scripts\python.exe scripts\run_grid.py --grid dedupe.corr_threshold=0.75,0.80,0.85
```

Expected: 测试全绿；`reports/sensitivity/dedupe.corr_threshold.json` 与 `reports/sensitivity_summary.json` 生成，含 3 行结果。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/evaluation/sensitivity.py scripts/run_grid.py tests/test_sensitivity.py
git commit -m "feat: support list-valued grid params and per-dimension sensitivity output"
```

---

## Task 4: 二维热力图（孤岛/高原检测）

**Files:**
- Modify: `src/etf_rotation/evaluation/sensitivity.py`
- Create: `scripts/run_heatmap.py`
- Modify: `scripts/run_report.py`
- Test: `tests/test_sensitivity.py`

**Interfaces:**
- Produces: `sensitivity.pivot_heatmap(results: pd.DataFrame, x: str, y: str, metric: str = "sharpe") -> pd.DataFrame`。
- Produces: `scripts/run_heatmap.py --x a.b --y c.d`，写 `reports/heatmap_{x}_{y}.html`。

- [ ] **Step 1: 写失败测试**

`tests/test_sensitivity.py` 追加：

```python
def test_pivot_heatmap():
    r = pd.DataFrame({
        "corr": [0.75, 0.75, 0.85, 0.85],
        "cost": [0, 8, 0, 8],
        "sharpe": [1.0, 0.9, 1.1, 1.0],
    })
    h = sensitivity.pivot_heatmap(r, "corr", "cost", "sharpe")
    assert h.loc[0.75, 0] == 1.0
    assert h.loc[0.85, 8] == 1.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_sensitivity.py::test_pivot_heatmap -q`
Expected: FAIL（函数不存在）。

- [ ] **Step 3: 实现**

`sensitivity.py` 新增：

```python
def pivot_heatmap(results: pd.DataFrame, x: str, y: str,
                  metric: str = "sharpe") -> pd.DataFrame:
    """把两个参数维度的网格结果透视成 (x × y) 的 metric 矩阵，用于孤岛/高原检测。"""
    return results.pivot_table(index=y, columns=x, values=metric, aggfunc="mean")
```

`scripts/run_heatmap.py`（新建）：基于 Task 2/3 的缓存与解析，跑 `--grid` 给的两个维度笛卡尔积，得到 `results` 后调 `sensitivity.pivot_heatmap`，用 `plotly` 输出注释热力图：

```python
"""二维参数热力图。用法：scripts/run_heatmap.py --grid dedupe.corr_threshold=0.75,0.80,0.85 --grid costs.one_side_bps=0,8,16"""
from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import pandas as pd
import plotly.express as px

from etf_rotation import config
from etf_rotation.backtest import run
from etf_rotation.evaluation import metrics, sensitivity
from etf_rotation.pipeline import build_weights, load_context

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", action="append", required=True)
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default="2026-07-31")
    ap.add_argument("--metric", default="sharpe")
    args = ap.parse_args()

    grid = {k: v for k, v in (sensitivity.parse_grid_spec(s) for s in args.grid)}
    assert len(grid) == 2, "heatmap needs exactly two --grid dimensions"
    ctx = load_context()
    rows = []
    for combo in itertools.product(*grid.values()):
        params = dict(zip(grid.keys(), combo))
        p = config.load_params()
        for k, val in params.items():
            config.set_nested(p, k, str(val))
        weights = build_weights(p, args.start, args.end, context=ctx)
        close = ctx["close"].reindex(index=weights.index, columns=weights.columns)
        opn = ctx["opn"].reindex(index=weights.index, columns=weights.columns)
        eff = weights.shift(1).fillna(0.0)
        r = run.run(eff, opn, close, cost_bps=p["costs"]["one_side_bps"],
                    cash_rate=p["costs"]["cash_rate_annual"])
        s = metrics.from_stats(r.stats)
        rows.append({**params, args.metric: s[args.metric],
                     "max_drawdown": s["max_drawdown"], "calmar": s["calmar"]})

    results = pd.DataFrame(rows)
    mat = sensitivity.pivot_heatmap(results, *grid, args.metric)
    fig = px.imshow(mat, text_auto=".2f", aspect="auto", color_continuous_scale="RdYlGn")
    out = ROOT / "reports" / f"heatmap_{'_x_'.join(grid)}.html"
    fig.write_html(out)
    print(json.dumps({"saved": str(out), "shape": list(mat.shape),
                      "rows": rows}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
```

`scripts/run_report.py`：在生成 HTML 报告时，若 `reports/heatmap_*.html` 存在，在报告里追加「参数敏感性热力图」入口链接（不改数值、不重建策略）。

- [ ] **Step 4: 运行测试与冒烟**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_sensitivity.py -q
.venv\Scripts\python.exe scripts\run_heatmap.py --grid dedupe.corr_threshold=0.75,0.80,0.85 --grid costs.one_side_bps=0,8,16
```

Expected: 测试全绿；`reports/heatmap_dedupe.corr_threshold_x_costs.one_side_bps.html` 生成且可离线打开。

- [ ] **Step 5: Commit**

```powershell
git add src/etf_rotation/evaluation/sensitivity.py scripts/run_heatmap.py scripts/run_report.py tests/test_sensitivity.py
git commit -m "feat: add two-parameter sensitivity heatmap"
```

---

## Task 5: 单参数敏感性执行与记录（实验，不新增算法）

在 Task 1–4 完成后，逐维度跑 `run_grid.py`（一次只动一个维度），把结果积累进 `reports/sensitivity_summary.json`。

- [ ] **Step 1: 趋势窗口**

```powershell
.venv\Scripts\python.exe scripts\run_grid.py --grid trend.windows=[[14,60],[21,60],[34,60],[21,90]]
```

- [ ] **Step 2: 相关性阈值与持仓上限**

```powershell
.venv\Scripts\python.exe scripts\run_grid.py --grid dedupe.corr_threshold=0.70,0.75,0.80,0.85,0.90
.venv\Scripts\python.exe scripts\run_grid.py --grid dedupe.max_holdings=6,8,10,12
```

- [ ] **Step 3: 市场状态阈值与 LLT α**

```powershell
.venv\Scripts\python.exe scripts\run_grid.py --grid market_state.bull_threshold=0.25,0.30,0.35,0.40
.venv\Scripts\python.exe scripts\run_grid.py --grid market_state.alpha=0.05,0.08,0.10,0.12,0.15
```

- [ ] **Step 4: 波动率目标与防守仓**

```powershell
.venv\Scripts\python.exe scripts\run_grid.py --grid risk.vol_target_risk=0.22,0.26,0.30,0.34
.venv\Scripts\python.exe scripts\run_grid.py --grid defensive.top_n=3,5,8
.venv\Scripts\python.exe scripts\run_grid.py --grid defensive.max_vol_60d=0.02,0.03,0.04
```

- [ ] **Step 5: 成本（并入已有敏感性口径）**

`run_sensitivity.py` 已覆盖 0/8/16/24bp；如需更细，跑：

```powershell
.venv\Scripts\python.exe scripts\run_heatmap.py --grid dedupe.corr_threshold=0.75,0.80,0.85 --grid costs.one_side_bps=0,4,8,12,16,24
```

- [ ] **Step 6: 汇总判读**

检查每个维度的 `robustness`（是否绝大多数组合 Sharpe>0）、`cliffs`（是否存在相邻参数剧烈跳变）、`dsr` 与 `sharpe_haircut`。悬崖/孤岛所在维度标记为「不稳定，不作为最终参数」。把判读结论写入 `reports/调参记录.md`（新增）。

验收：每个维度有独立 JSON + `sensitivity_summary.json` 汇总；`reports/调参记录.md` 记录每个维度的候选区间与排除理由。

---

## Task 6: 参数组合调试 + 样本外 re-验证 + 报告同步

- [ ] **Step 1: 组合调试**

在 Task 5 确定的「非悬崖、稳健」区间内，用 `run_backtest.py --param a.b=值` 一次只动一个维度，逐步逼近：

```powershell
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --param dedupe.corr_threshold=0.85
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --param risk.vol_target_risk=0.30
```

每一步对比 `reports/metrics.json`（年化/回撤/Sharpe/Calmar/换手/total_fees），并把「参数 → 指标」追加进 `reports/调参记录.md`。禁止在同一步同时改两个参数。

- [ ] **Step 2: 样本外 re-验证**

对最终候选参数跑两个子区间：

```powershell
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2023-12-31 --param <最终参数>
.venv\Scripts\python.exe scripts\run_backtest.py 2024-01-01 2026-07-31 --param <最终参数>
```

选「子区间表现一致、全区间非单点最优」的组合；若某参数只在单边子区间占优，判为不稳健并回退。

- [ ] **Step 3: 成本敏感性 re-跑**

```powershell
.venv\Scripts\python.exe scripts\run_sensitivity.py
```

确认最终参数下成本 0/8/16/24bp 的收益/回撤/Calmar 仍稳健（不过度依赖低换手假象）。

- [ ] **Step 4: 更新报告与文档**

```powershell
.venv\Scripts\python.exe scripts\run_report.py
```

更新 `reports/回测报告.md`：基准指标、参数敏感性结论、样本外子区间、最终参数建议、与研报差异说明；同步 `README.md` 的基准数字与测试数（TODO 4.1）。

- [ ] **Step 5: Commit**

```powershell
git add reports/回测报告.md reports/调参记录.md reports/sensitivity_summary.json README.md
git commit -m "docs: record tuning results, OOS re-validation and final params"
```

---

## 不在本计划范围（见 TODO.md）

- 阶段一机制补全（1.1–1.5：34% 组合波动上限、反转、整组迟滞、单 ETF 过热、T+1 开盘/跳空/停牌）——已由 `docs/superpowers/plans/2026-10-16-etf-rotation-mechanisms.md` 承接，在本计划之前完成。
- 阶段三代码卫生（3.1–3.6）与阶段四文档维护（4.2/4.3）——不改变数值，独立小任务。

## 执行顺序与依赖

Task 1 → 2 → 3 → 4 是顺序依赖（后两者复用前两者的缓存与参数解析）；Task 5 依赖 Task 4；Task 6 依赖 Task 5。Task 1/2 为行为不变重构，完成后先确认 `weights.parquet` 与 `metrics.json` 与基线逐值一致，再进入改变结果的阶段。

---

## 执行结果记录（2026-10-16 至 2026-10-17）

**结论：计划全部执行完毕。** 全量单测 67 通过，工作树干净；`main` 上新增 7 个提交，尚未推送远端。

### 执行与验证

- Task 1 参数接线后，`weights.parquet` 与 `metrics.json` 与基线逐值一致（`IDENTICAL`）。
- Task 2 信号/上下文缓存后，`weights.parquet` 与基线逐值一致（`IDENTICAL`）。
- Task 3/4 冒烟通过：`reports/sensitivity/dedupe_corr_threshold.json`、`reports/sensitivity_summary.json`、`reports/heatmap_dedupe.corr_threshold_x_costs.one_side_bps.html` 均生成。
- Task 5 八个维度单参数网格全部跑完，`robustness` 均为 1.0，DSR 落在 0.54–0.55（低于 0.95，调参结论只作候选不作统计显著结论）。
- Task 6 组合调试、样本外 re-验证、成本敏感性、报告与 README 同步全部完成。

### 关键结果（close 口径，2019-01 ~ 2026-07，单边 8bp）

| 口径 | 年化 | 最大回撤 | Sharpe | Calmar | 换手 | total_fees |
|---|---|---|---|---|---|---|
| 机制补全后默认参数 | 11.83% | -12.72% | 1.039 | 0.930 | 5.42% | 0.2313 |
| 最终候选 | 12.31% | -12.21% | 1.073 | 1.008 | 5.37% | 0.2306 |

最终候选参数：`market_state.bull_threshold=0.30`、`dedupe.corr_threshold=0.85`，其余维持默认。

样本外子区间：2019–2023 为 7.18% / -12.21% / 0.710 / 0.589；2024–2026 为 24.92% / -7.19% / 1.832 / 3.464。两个子区间均为正收益，最终候选未出现「只在单边子区间占优」，但前半段仍显著偏弱，策略的市场状态依赖依然存在。

成本敏感性（最终候选）：0bp 14.69% / -11.26% / 1.256 / 1.304；8bp 12.31% / -12.21% / 1.073 / 1.008；16bp 9.97% / -15.04% / 0.889 / 0.663；24bp 7.69% / -17.82% / 0.706 / 0.431。策略仍高度依赖低换手假设。

### 执行中的偏离与修复（均已单测验证并提交）

1. `test_defensive_select_respects_top_n` 计划用例与「同一大类最多 1 只」语义冲突，改为 bond/money 两类下 `top_n=2` 返回 2、`top_n=1` 返回 1。
2. `test_pivot_heatmap` 计划用例索引顺序与 `pivot_heatmap` 实现（index=y, columns=x）相反，修正为 `h.loc[0, 0.75]`、`h.loc[8, 0.85]`。
3. `parse_grid_spec` 标量分支强制转 float，导致 `dedupe.max_holdings=6,8,10,12` 的 `3*6.0` 成为 float 切片下标而崩溃；改为逐值 `yaml.safe_load` 保留 int。
4. `signal_cache_key` 遗漏 `market_state.bull_threshold` / `market_state.bear_threshold` / `reversal.*`，导致 bull_threshold 网格全部复用首个 regime；补全键集并重跑该维度。
5. Task 5 Step 5 的 18 点更细成本热力图未跑：已有 `run_sensitivity.py` 的 0/8/16/24bp 与 Task 4 的 3×3 corr×cost 热力图覆盖，按「如需更细」跳过。

### 提交记录

- `322442d` refactor: wire trend/market-state/risk/defensive/hrp params into pipeline
- `62caddf` perf: cache signal precompute and price context across grid points
- `4a5fa51` feat: support list-valued grid params and per-dimension sensitivity output
- `c1bc600` feat: add two-parameter sensitivity heatmap
- `3526a65` fix: preserve integer grid values in parse_grid_spec
- `8d96713` fix: include all signal-affecting params in signal cache key
- `f5d714a` docs: record tuning results, OOS re-validation and final params

### 遗留待用户决定

- 是否把最终候选参数写回 `config/params.yaml` 作为新默认（本次未改默认参数文件）。
- 是否将 `main` 推送至 `origin/main`，或另建评审分支开 PR（本次仅本地提交）。
