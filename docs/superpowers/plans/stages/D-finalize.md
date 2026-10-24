# D 收口（Task 21 → 22）

**worktree / branch**：`persist-d1` / `feat/persist-d1-d2`
**执行位置**：worktree（两个阶段同一个分支）
**前置**：阶段 1 需要 S0a + S1 已合并；阶段 2 等 C3 完成

## 阶段 1：校验、清理、下游 `--run-id`（Task 21，波次 W2）

### 独占文件

```
src/etf_rotation/evaluation/verify.py
src/etf_rotation/evaluation/prune.py
scripts/verify_artifacts.py
scripts/prune_runs.py
scripts/run_attribution.py
scripts/run_exposure.py
scripts/run_report.py
tests/test_verify_artifacts.py
```

`run_sensitivity.py` 归 C2，不要动。

### 消费契约

- run 目录 + `artifacts.parquet`（S0a）
- `derived/index.json` 的 `inputs`（S1）
- `families/`（C2，可选；缺失时跳过 family 校验）

### 验收

```powershell
. D:\project\quant_1\scripts\activate_data.ps1
& $env:PY -m pytest tests/test_verify_artifacts.py -q

& $env:PY scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
& $env:PY scripts\build_report_data.py --only alignment,performance
& $env:PY scripts\verify_artifacts.py
& $env:PY scripts\run_attribution.py --run-id <上一步 latest.json 的 run_id>
```

预期：测试全绿；`verify_artifacts` 无输出；`run_attribution` 把结果写进该 run 目录的 `analysis/`，同时更新顶层镜像；改动一个产物字节后 verify 能报出文件名。

### 注意

- `verify` 里 `total_fees` 与 `trades.cost.sum()` 的容差 0.5%，超了要报错而不是警告。
- `prune` 默认 `dry_run=True`，只删档位允许删的大文件，保留 `meta/metrics/manifest`，并在 meta 追加 `pruned=TRUE`。
- 下游脚本默认 `--run-id None` → 读 `reports/latest.json`；不存在时报错并列出可用 id。

## 阶段 2：文档收口（Task 22，波次 W5）

**前置**：C3 已把 20a/20b 跑完并合并。

### 独占文件

```
TODO.md
CHANGELOG.md
README.md
AGENTS.md
docs/代码审阅手册.md
docs/superpowers/specs/2026-10-24-etf-rotation-report-content-spec.md
```

### 验收

```powershell
& $env:PY scripts\verify_artifacts.py
git status --porcelain
git log --oneline -5
```

预期：verify 无输出；`git status` 只有文档；提交信息为 `docs: 收口持久化与报告派生数据管线`。

### 注意

- 文档里所有数字都必须来自 C3 生成的 `run_id`，不要沿用 v1.1.1 的旧值。
- `AGENTS.md` 只补数据约定，不改方法论章节。
