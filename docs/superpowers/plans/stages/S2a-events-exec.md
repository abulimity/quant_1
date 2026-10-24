# S2a 事件 / 执行 / 极端日（Task 10、12、15）

**worktree / branch**：`persist-s2a` / `feat/persist-s2a-events-exec`
**执行位置**：worktree
**前置**：S1 已合并、S0a 已合并

## 任务

主计划 Task 10 → 12 → 15（顺序只影响提交顺序，彼此独立）。

## 独占文件

```
src/etf_rotation/report/steps/events.py
src/etf_rotation/report/steps/execution.py
src/etf_rotation/report/steps/extremes.py
tests/test_report_events.py
tests/test_report_execution.py
tests/test_report_extremes.py
```

不要动 `runner.py`、`context.py`、其它 step 文件。

## 消费契约

- `ReportContext`（S1）：`.diary` `.weights` `.holdings` `.equity` `.close` `.classification`
- `serialize.records / series`（S1）
- `.trades`（Task 13 才实现 roundtrips，但 artifacts 里有 `trades.parquet`）

## 产出契约（S3 / D 依赖）

- `events.rebalance_events(diary, weights, returns)`、`events.event_dates(diary, weights)` ← **S3 会调用**
- `execution.target_vs_actual(weights, holdings)`、`execution.turnover_split(diary, weights)`
- `extremes.extreme_days(returns, weights, diary, close, classification, top_n=10)`
- 每个模块暴露 `NAME` 与 `build(ctx)`

## 验收

```powershell
. D:\project\quant_1\scripts\activate_data.ps1
$PY -m pytest tests/test_report_events.py tests/test_report_execution.py tests/test_report_extremes.py -q

$PY scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
$PY scripts\build_report_data.py --only events,execution,extremes
```

预期：测试全绿；三个 step `ok`；事件数 300–800；`mean_abs` 中位数 < 0.5%；`extremes` 的 `|residual|` 中位数 < 5bp。

## 注意

- `event_dates` 的判定规则必须与 `rebalance_events` 共用同一函数，禁止两处各写一套。
- 极端日不要断言"贡献之和等于当日收益"；真实数据有现金利息与执行偏差，用 `residual` 字段承载。
- `fwd_5d/fwd_20d` 是事后信息，字段名与注释都要标注。
