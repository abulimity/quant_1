# X 清理旧 run（Task 23）

**执行位置：main 检出，不用 worktree。**
**门禁**：Task 20b 完成且 `verify_artifacts.py` 无输出、`reports/latest.json` 指向带 `meta.parquet` 的新 run。

## 要做的事

1. 列出 `reports/runs/` 下**没有 `meta.parquet`** 的目录（旧的 40 个），把名字写进 `reports/legacy/old-runs.txt`。
2. 只删这些目录；**不要** `Remove-Item reports\runs`（会连新 run 一起删）。
3. `DROP TABLE run_metrics, runs`。
4. 对照清理前后的 `registry.load_runs` 数量：必须一致（旧目录本来就不被查询）。

## 验收

```powershell
(Get-ChildItem reports\runs -Directory | Where-Object { $_.Name -ne '.staging' }).Count
$PY -c "from pathlib import Path; from etf_rotation.evaluation import registry; print(len(registry.load_runs(Path('reports/runs'))))"
$PY -c "import duckdb;print([r[0] for r in duckdb.connect('data/warehouse.duckdb').execute('show tables').fetchall()])"
```

预期：目录数 == `load_runs` 数量；表列表不含 `runs`/`run_metrics`。

## 注意

- 这一步只动数据，不动代码；提交内容只有 `reports/legacy/{README.md,old-runs.txt}`。
- 万一误删了新 run：从 `data_snapshot_id` 相同的参数重跑即可重建，不要手工恢复目录。
