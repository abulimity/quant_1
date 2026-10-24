# S0a 身份与写盘（Task 2–5）

**worktree / branch**：`persist-s0a` / `feat/persist-s0a-store`
**执行位置**：worktree
**前置**：Task 1 已由编排者在 main 执行并提交

## 任务

主计划 Task 2 → 3 → 4 → 5，严格按序。

## 独占文件

```
src/etf_rotation/data/snapshot.py
src/etf_rotation/evaluation/registry.py
src/etf_rotation/evaluation/artifacts.py
src/etf_rotation/evaluation/metrics.py
src/etf_rotation/signals/cache.py        # 仅 signal_id（Task 17 才加 save/load）
scripts/run_backtest.py
scripts/run_report.py
scripts/curate_data.py
tests/test_snapshot_ledger.py
tests/test_registry_parquet.py
tests/test_registry.py
tests/test_artifacts.py
tests/test_run_backtest_artifacts.py
```

## 产出契约（后续所有 stage 依赖）

- `snapshot.data_snapshot_id() / warehouse_fingerprint(con) / verify_warehouse(con, strict)`
- `registry.env_lock_hash() / git_info() / run_identity(...)`
- `registry.write_run / load_runs / load_metrics / content_hash`
- `artifacts.store_run / SAVE_PROFILES / resolve_run / mirror_latest / ArtifactConflictError`
- `metrics.all_stats / build_equity_frame`
- `run_backtest.py --save-profile {minimal,standard,full}`，默认 standard
- run 目录：`meta.parquet / metrics.parquet / artifacts.parquet / manifest.json` + 档位产物
- `reports/latest.json` 结构：`{run_id, family_id, kind, profile, updated_at}`

## 验收

```powershell
. D:\project\quant_1\scripts\activate_data.ps1
& $env:PY -m pytest tests/test_snapshot_ledger.py tests/test_registry_parquet.py tests/test_artifacts.py tests/test_run_backtest_artifacts.py -q

& $env:PY scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
Get-ChildItem reports\runs -Recurse -File | Select-Object Name
& $env:PY -c "import pandas as pd; a=pd.read_csv('reports/legacy/v1.1.1/equity.csv',parse_dates=['ts']).set_index('ts'); b=pd.read_csv('reports/equity.csv',parse_dates=['ts']).set_index('ts'); print((a['nav']-b['nav']).abs().max())"
```

预期：测试全绿；目录含 9 类产物；`nav` 差值 `0.0`。

再跑一次同命令，预期 `run_id` 不变、`attempts.jsonl` 两行、无 `ArtifactConflictError`。

## 不做

- 不碰 `pipeline.compute_benchmark`（S0b 负责）。
- 不实现 family/trial（C1 负责）。
- 不实现信号缓存读写（C1 负责，本 stage 只给 `signal_id`）。
