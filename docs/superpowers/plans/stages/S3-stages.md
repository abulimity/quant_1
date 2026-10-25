# S3 决策阶段归因（Task 14）

**worktree / branch**：`persist-s3` / `feat/persist-s3-stages`
**执行位置**：worktree
**前置**：S2a 已合并（需要 `events.event_dates`）、C1 已合并（同文件顺序）

## 任务

主计划 Task 14。唯一一个改 `pipeline._daily_target` / `build_weights` 的任务。

## 独占文件

```
src/etf_rotation/pipeline.py::_stage_snapshot, _daily_target, build_weights
src/etf_rotation/evaluation/observability.py
scripts/run_backtest.py
src/etf_rotation/report/steps/stages.py
tests/test_report_stages.py
tests/test_observability.py
```

`compute_benchmark`（S0b）与 `_precompute_signals`（C1）不要动。

## 消费契约

- `events.event_dates(diary, weights)`（S2a）
- `ReportContext`（S1）
- `artifacts.store_run` 的 `frames["stages"]`（S0a）

## 产出契约

- `pipeline._stage_snapshot(weights) -> dict`
- `trace["stages"]`，键固定 `candidate, overheat, cross_asset, defensive, phases, hysteresis, final`
- `observability.build_stages(traces, days)`，列 `date, ticker, stage, weight`
- `observability.write(..., stages=None)` 写 `signals/stages.parquet`
- `run_backtest` 把 stages 放进 `frames`（只有 full 档落盘）

## 验收

```powershell
. D:\project\quant_1\scripts\activate_data.ps1
& $env:PY -m pytest tests/test_report_stages.py tests/test_observability.py -q

& $env:PY scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
& $env:PY scripts\build_report_data.py --only stages
```

预期：测试全绿；`signals/stages.parquet` 存在；每个事件 `Σfinal == diary.total_weight`；`Σphases ≥ Σfinal` 且 `Σhysteresis ≥ Σfinal`（**不要断言 `Σcandidate ≥ Σfinal`**：candidate 只是风险腿预算，defensive 会补到 ~1.0）；`nav` 与 `reports/legacy/v1.1.1/equity.csv` 完全一致（本任务不得改变任何数值）。

## 注意

- 阶段快照只在 `with_trace=True` 时写入；不得影响 `target` 与 `final` 的计算。
- 记录顺序是语义的一部分：`candidate → overheat → cross_asset → defensive → phases → hysteresis → final`。
- `trace` 里新增字段不能让 `observability._diary_row` 报 KeyError（S2a 的 `build_frames` 会用 traces）。
