# 并行执行编排（stages）

主计划：`docs/superpowers/plans/2026-10-24-etf-rotation-persistence-and-report-data.md`（下称「主计划」，任务正文在那里）。
本目录只放**薄 brief**：范围、独占文件、消费/产出契约、验收。不复制任务正文，避免两份真相。

## 会话与波次

| 波次 | 并发 | 工作流 | brief |
|---|---|---|---|
| W0 | 编排者 + 2 | Task 1（编排者，main）→ S0a ∥ S0b | `S0a-store.md`、`S0b-benchmark.md` |
| W1 | 2 | S1 ∥ C1 | `S1-report-core.md`、`C1-signal-family.md` |
| W2 | 4 | S2a ∥ S2b ∥ C2 ∥ D1 | `S2a-events-exec.md`、`S2b-costs-trips.md`、`C2-grid.md`、`D-finalize.md`（阶段 1） |
| W3 | 1 | S3 | `S3-stages.md` |
| W4 | 1 | C3（main，无 worktree） | `C3-rerun.md` |
| W5 | 1 | D2（D 的同一分支） | `D-finalize.md`（阶段 2） |
| W6 | 1 | X 清理旧 run（main，门禁后） | `X-cleanup.md` |

并发上限 4。W1 只有 2 路、W3 只有 1 路是依赖决定的，不为了凑数硬拆。

## 每个 worktree 的环境

```powershell
. D:\project\quant_1\scripts\activate_data.ps1
$PY -m pytest tests -q
```

- `reports/` 在 worktree 内独立；`data/` 通过 `ETF_*` 变量指向主仓库，**只读**。
- `activate_data.ps1` 会把主仓库的 `reports/legacy/v1.1.1/` 拷进当前 worktree，供「策略数值不变」的对照；缺了对照就先重跑一次脚本。
- `data/cache/signals/` 跨 worktree 共享，写入是 `tmp-{pid}` + rename；**不要手工清理**。
- worktree 只 checkout 已提交内容；编排者先提交主计划与本目录，再建 worktree。

## 产物归属（最重要的一条）

`reports/runs/`、`reports/families/`、`reports/derived/`、`reports/latest.json` 都被 `.gitignore` 排除。
因此：

- 各 stage 的真实数据验证在**自己的 worktree** 内跑一次，只把结论写进提交说明，产物不提交；
- **Task 20a / 20b 必须在 main 检出执行**（C3），否则合并后 `run_id` 指向不存在的目录；
- 子会话不提交 `reports/` 下任何生成物。

## 合并顺序（编排者执行）

```
S0b → S0a → S1 → {S2a, S2b, C2, D1} → S3 → C3 → D2
```

共用文件：`pipeline.py`（S0b → C1 → S3）、`run_backtest.py`（S0a → S3）、`registry.py`（S0a → C1）、`run_report.py`（S0a → D1）。
冲突时保留 main 侧契约（签名、meta 字段、目录布局），再补分支侧新增内容。

## 派发模板

```
你在 worktree <绝对路径>，分支 <branch>。
读：
1. docs/superpowers/plans/2026-10-24-etf-rotation-persistence-and-report-data.md
   （Global Constraints §2、Review Focus §3、你的 Task 编号）
2. docs/superpowers/plans/stages/<本 brief>

纪律：
- 只改本 brief「独占文件」列出的路径；需要别处改动就停下来说明。
- 每个 Task 走 TDD：失败测试 → 跑失败 → 实现 → 跑通过 → commit（message 用主计划里的）。
- 不 merge、不 rebase 到 main、不 push、不改主仓库 data/。
- 验证前先 . D:\project\quant_1\scripts\activate_data.ps1。
- 结束只回复：完成任务号、commit hash、验收命令的实际输出、未解决项。
```

## 完成定义

一个工作流完成 = 本 brief 的验收命令全部通过 + 每个 Task 一个 commit + 回复里贴了真实输出 + 未触碰独占文件之外的路径。
