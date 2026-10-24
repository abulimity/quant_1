# S1 报告骨架 + 性能/相对（Task 7–9）

**worktree / branch**：`persist-s1` / `feat/persist-s1-report-core`
**执行位置**：worktree
**前置**：S0a 已合并（需要 run 目录结构与 full 档产物）

## 任务

主计划 Task 7 → 8 → 9。Task 7 是 B 组的硬门，必须先完成。

## 独占文件

```
src/etf_rotation/report/__init__.py
src/etf_rotation/report/context.py
src/etf_rotation/report/serialize.py
src/etf_rotation/report/runner.py
src/etf_rotation/report/steps/__init__.py
src/etf_rotation/report/steps/alignment.py
src/etf_rotation/report/steps/performance.py
src/etf_rotation/report/steps/relative.py
scripts/build_report_data.py
tests/test_report_context.py
tests/test_report_runner.py
tests/test_report_performance.py
tests/test_report_relative.py
```

不要创建其它 step 文件（S2a/S2b/S3 各自负责）。

## 消费契约

- `reports/runs/{run_id}/` 下：`meta.parquet`（含 `run_id/schema_version/save_profile/data_snapshot_id/params_json`）、`equity.parquet`（五列）、`benchmark.parquet`、`weights.parquet`、`holdings.parquet`、`artifacts.parquet`（`name→sha256`）
- `artifacts.resolve_run(root, None)` 读 `reports/latest.json`

## 产出契约（S2a/S2b/S3/D 都依赖）

- `ReportContext.load(run_dir, *, strict_snapshot=False)`，字段名与主计划 Task 7 一致
- `runner.run(run_dir, ctx, only=None, mirror_to=None)`
- `serialize.records / series / clean`
- `derived/index.json`：`schema_version, derived_version, run_id, generated_at, data_snapshot_id, inputs{name:sha256}, steps{name:{ok,duration_ms,error}}`
- `scripts/build_report_data.py --run-id/--latest/--only`

## 验收

```powershell
. D:\project\quant_1\scripts\activate_data.ps1
& $env:PY -m pytest tests/test_report_context.py tests/test_report_runner.py tests/test_report_performance.py tests/test_report_relative.py -q

& $env:PY scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
& $env:PY scripts\build_report_data.py --latest
& $env:PY -c "import json;d=json.load(open('reports/derived/index.json',encoding='utf-8'));print(d['run_id'], {k:v['ok'] for k,v in d['steps'].items()})"
```

预期：测试全绿；`alignment`/`performance`/`relative` 三个 step 为 `True`；`peak_lag == 0`；`corr_full ≈ 0.51`、`beta_full ≈ 0.31`。

## 注意

- `ReportContext` 加载价格用 `pipeline.load_prices()`；单测必须 monkeypatch，不能读真实数据。
- `lag_correlation` 的索引是 `|lag|` 序（0, ±1, ±2…），**写 JSON 前必须按 lag 数值升序重排**，否则前端横轴是 0,1,-1,2…；`peak_lag` 在原始序列上取 `idxmax`。
- `runner` 单步失败不抛异常，只写 `ok=False`；`index.json` 永远写成功。
- 派生 JSON 必须能通过 `json.dumps(..., allow_nan=False)`。
