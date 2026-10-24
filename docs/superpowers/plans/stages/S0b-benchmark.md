# S0b 基准对齐（Task 6）

**worktree / branch**：`persist-s0b` / `feat/persist-s0b-benchmark`
**执行位置**：worktree
**前置**：Task 1（legacy 副本）

## 任务

主计划 Task 6。只改一个函数 + 新增一个模块。

## 独占文件

```
src/etf_rotation/pipeline.py::compute_benchmark     # 仅这一个函数
src/etf_rotation/evaluation/alignment.py
tests/test_alignment.py
```

`pipeline.py` 的其它部分不要动（S0a 在改 `run_backtest`，S3 之后才改 `_daily_target`）。

## 产出契约

- `alignment.lag_correlation(strategy, benchmark, max_lag=5) -> pd.Series`
- `compute_benchmark` 列不变（`benchmark`, `hs300`）；同日收益；**首日收益为 0**

## 验收

```powershell
. D:\project\quant_1\scripts\activate_data.ps1
$PY -m pytest tests/test_alignment.py -q
```

真实数据（不依赖 S0a 的镜像，直接调函数）：

```powershell
$PY -c "import pandas as pd; from etf_rotation import pipeline, config; from etf_rotation.evaluation.alignment import lag_correlation; p=config.load_params(); b=pipeline.compute_benchmark(p,'2019-01-01','2026-07-31'); b.to_csv('reports/benchmark_new.csv'); e=pd.read_csv(r'reports/legacy/v1.1.1/equity.csv',parse_dates=['ts']).set_index('ts'); print(lag_correlation(e['returns'], b['hs300'].pct_change()).round(3)); print('first-day nav', b['hs300'].iloc[0], b['benchmark'].iloc[0])"
```

预期：峰值在 `0`、`corr(0) ≈ 0.51`、首日净值 `1.0`。
再与 `reports/legacy/v1.1.1/benchmark.csv` 对比日期与量级，把差异写进提交说明（这是唯一允许的数值改动）。

## 不做

- 不改 `equity.csv` 的列（S0a 已加 `turnover/fees`）。
- 不改策略权重、净值、交易。
