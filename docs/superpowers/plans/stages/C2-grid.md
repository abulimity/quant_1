# C2 网格统一（Task 19）

**worktree / branch**：`persist-c2` / `feat/persist-c2-grid`
**执行位置**：worktree
**前置**：S0a + C1 已合并

## 任务

主计划 Task 19。一个大任务，含 `sweep.py`、7 个脚本、`collect_runs.py` 与注入式测试。

## 独占文件

```
src/etf_rotation/evaluation/sweep.py
scripts/collect_runs.py
scripts/run_grid.py
scripts/run_grid_hydra.py
scripts/run_heatmap.py
scripts/run_sensitivity.py
scripts/run_assumption_sensitivity.py
scripts/run_mechanism_ablation.py
scripts/run_oos_check.py
tests/test_sweep.py
```

## 消费契约

- `artifacts.store_run / resolve_run`（S0a）
- `registry.run_identity / family_id / write_family_member / load_family`（S0a + C1）
- `overfitting.campaign_trials / deflated_sharpe`（C1）

## 产出契约（C3 依赖）

- `sweep.iter_points(grid)`、`sweep.run_sweep(..., runs_root, families_root, ...)` → `{family_id, n_trials, run_ids}`
- `collect_runs.family_summary(families_root, runs_root, fid)`；CLI `--family` / `--campaign`
- 7 个脚本统一支持 `--campaign`、`--save-profile`；`kind` 分别为 `grid/cost/assumption/ablation/oos`
- `families/{fid}/summary.json` 含 `dsr_family` 与 `dsr_campaign`
- `grid.json` 变成派生镜像（带 `generated` 标记），不再手写

## 验收

```powershell
. D:\project\quant_1\scripts\activate_data.ps1
& $env:PY -m pytest tests/test_sweep.py tests/test_families.py -q

& $env:PY scripts\run_grid.py --grid defensive.max_vol_60d=0.03,0.04 --save-profile minimal --campaign demo
& $env:PY scripts\collect_runs.py --family <上一步输出的 family_id>
& $env:PY -c "import json;print(json.load(open('reports/families/<fid>/summary.json',encoding='utf-8'))['n_trials'])"
```

预期：测试全绿；2 个 run 目录；family `n_trials == 2`；`reports/latest.json` 未被网格覆盖。

## 注意

- **DuckDB 单写锁**：不要在 worker 里写任何共享 DB；每个 run 只写自己的目录，family 成员一人一个 JSON。
- Hydra 的 `family_id` 必须由 cfg 确定性算出，worker 之间不通信。
- 所有脚本里旧的 `registry.register_run(db_path, ...)` 调用要删掉。
- `n_obs` 从 `r.returns.notna().sum()` 传入 meta。
