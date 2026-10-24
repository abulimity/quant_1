# C3 重跑与基线重建（Task 20a、20b）

**执行位置：main 检出，不用 worktree。**
**前置**：S3 与 C2 都已合并到 main，`git status` 干净，`pytest tests -q` 全绿。

> 原因：本 stage 的产物是 `reports/runs/`、`reports/families/`、`reports/derived/`，全部被 `.gitignore` 排除；在 worktree 里跑完无法随分支合并，`run_id` 会指向不存在的目录。

## 任务

主计划 Task 20a → 20b。**顺序固定**：先扫描（20a），再重建基线（20b）。

## 触摸的文件

```
reports/调参记录.md        # 20a
reports/回测报告.md        # 20b
reports/index.md           # 20a 生成
```

只有这两个 markdown 会进 git；其余产物留在磁盘。

## 前置检查

```powershell
. D:\project\quant_1\scripts\activate_data.ps1
& $env:PY -m pytest tests -q
& $env:PY scripts\verify_artifacts.py   # Task 21 已合并时应可用
```

## 验收

20a：

```powershell
& $env:PY scripts\collect_runs.py --campaign tuning-2026-10
```

预期：`reports/index.md` 列出所有 family，总试验数约 40；每个 `summary.json` 有 `dsr_family` 与 `dsr_campaign`；`reports/runs/` 下每个成员都能找到目录。

20b：

```powershell
& $env:PY scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
& $env:PY scripts\build_report_data.py --latest
& $env:PY scripts\run_report.py
& $env:PY scripts\verify_artifacts.py
& $env:PY -c "import pandas as pd; a=pd.read_csv('reports/legacy/v1.1.1/equity.csv',parse_dates=['ts']).set_index('ts'); b=pd.read_csv('reports/equity.csv',parse_dates=['ts']).set_index('ts'); print((a['nav']-b['nav']).abs().max())"
```

预期：派生 10 个 step 全 `ok`；`verify_artifacts` 无输出；`nav` 差值 `0.0`；`回测报告.md` 的自动段落带新 `run_id`。

## 注意

- 20a 与 20b 之间不要重跑 `run_backtest`（20a 不需要它，20b 才建基线）。
- 有信号缓存后 8 个维度的总耗时应 < 15 分钟；若明显更慢，先查缓存是否命中（`data/cache/signals/` 只有一个目录）。
- 不要手工编辑 `reports/index.md`（生成物）。
