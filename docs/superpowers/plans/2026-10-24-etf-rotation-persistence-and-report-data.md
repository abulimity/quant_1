# 回测/网格持久化与报告派生数据（合并版）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每一次回测、每一个网格点的「身份 / 参数 / 指标 / 信号 / 产物」都可寻址、可校验、可重建；在此之上补齐可视化报告需要的 13 项派生数据，并把派生结果绑定到具体的 `run_id`。

**Architecture:** 三级内容寻址：`data_snapshot_id`（数据）→ `signal_id`（信号集）→ `run_id`（参数+代码+数据+执行口径+信号），外加 `family_id`/`campaign_id` 聚合扫描与调参轮次。写入只有一个入口 `store_run()`：按档位写 `reports/runs/{run_id}/` 下的 parquet + json，暂存目录 → 校验 → 原子改名；**不写任何共享数据库文件**，因此并行安全。读取用 DuckDB 内存库对显式 parquet 文件列表建视图。报告派生层 `etf_rotation.report` 只读某个 run 目录，输出 `runs/{run_id}/derived/*.json` 并镜像到 `reports/derived/`。

**Tech Stack:** Python 3.10、pandas、numpy、ffn、scipy、pyarrow、duckdb、bt、hydra、pytest；不新增依赖。

**Spec:** `docs/superpowers/specs/2026-10-24-etf-rotation-report-content-spec.md`（§3.2 N1–N13、§5 图表 ID、§6 P0 详图）。持久化部分没有独立 spec，设计决策见本文件 §1。

**Supersedes:** `docs/superpowers/plans/2026-10-24-etf-rotation-report-derived-data.md`（其 N1–N13 任务已并入本计划 Stage B，路径与数据来源有改动，请勿再执行旧文件）。

**编排：** 24 个任务项（Task 20 拆成 20a/20b）按 12 个工作流拆到独立 worktree 并行，最多 4 路并发；子会话 brief 见 `docs/superpowers/plans/stages/`，波次、合并顺序、派发模板与检查点见 §6。

---

## 0. 对原报告计划的评估

### 采纳的部分

- TDD 步骤、每个 step 一个 JSON、单步失败不拖垮全局的 runner 设计。
- 「指标唯一来源是 `metrics.json`，派生层只做展示性聚合」的纪律。
- Review Focus 里对四套索引语义（weights / holdings / trades / diary）、预热期 NaN、FIFO 分批配对的强调。
- N1 用 `lag_correlation` 守「峰值在 0」的做法——这是唯一能自动发现基准错位的测试。

### 必须修正的 7 处

1. **派生数据与 run 身份脱钩。** 原计划所有输入都是 `reports/equity.csv` 等固定路径，输出 `reports/derived/*.json`，`index.json` 里没有 `run_id`。重跑一次回测，前端看到的派生数据就会悄悄换成另一套参数的结果。合并版：输入改为 `reports/runs/{run_id}/`，输出写进同一 run 目录，`index.json` 必须含 `run_id` + 输入产物 sha256。
2. **`trades.csv` 的生产者错位。** 原计划 `ReportContext.load` 依赖 `trades.csv`，但该文件由 `scripts/run_report.py:114` 生成，而 `build_report_data.py` 应在 `run_backtest` 之后直接可跑。合并版：交易明细表（`trades.build_trade_table_from_engine`）上移为 `run_backtest` 的 `full` 档产物，`run_report.py` 只读不写。
3. **N1 去掉 `shift(1)` 后首日没有对齐。** 策略首日 `returns[0] = 0`，基准首日会带上当天收益，`excess_cagr` 因此多一个约 0.5% 的虚假项。合并版：`bench_ret.iloc[0] = 0`、`hs_ret.iloc[0] = 0`，并加 `test_benchmark_first_day_is_flat`。
4. **`equity` 增加 `turnover`/`fees` 列没有版本标记。** 旧 run 的 equity 少两列，`ReportContext` 会 `KeyError`。合并版：`meta.schema_version` 由 `ReportContext` 校验（不匹配直接报错）；旧 run 延后到 Task 23 清理，新读取层只扫 `meta.parquet`，旧目录不参与查询。
5. **`stages.parquet` 依赖 `with_trace=True`。** 网格点不采集 trace，所以 stages 只有 `full` 档有。合并版：profile 矩阵里明确 stages 属于 full，`ReportContext.stages` 允许为 `None`（原计划已考虑，这里只是把它写进档位语义）。
6. **N12 极端日「贡献之和 ≈ 当日收益」只在合成数据成立。** 真实数据里 `Σ w_{t-1}·r_t` 不含现金利息与执行偏差（`attribution` 模块注释已说明）。合并版：验收改为「与 `equity.returns` 对账，给出 `residual` 字段和容差」，不假装精确相等。
7. **N9 剔除防守后归一化会让 beta 不可比。** 把风险腿权重归一化到 1，等于把平均 70% 的风险暴露放大到 100%，`beta_risk_sleeve` 会被系统性放大。合并版：`corr` 用归一化权重（尺度无关），`beta` 用「按平均风险权重缩放」的权重，并在输出里同时给 `mean_risk_weight` 与 `beta_scaling`，测试钉死这个选择。

### 顺序上的变化

原计划把 Task 1（基准修复）当全局前置，其余直接读 `reports/`。合并版必须先有「按 run 写盘」再谈派生，否则派生层写完就要返工。因此 Stage 顺序为：**基础设施 → 报告派生 → 信号缓存 → 网格 → 收口**；基准修复放在基础设施末尾、派生层之前。

---

## 1. 设计决策（持久化）

### 1.1 身份

```
data_snapshot_id = sha256( bronze 文件哈希 + warehouse 表指纹 )[ :12 ]
signal_id        = sha256( 信号代码哈希 + data_snapshot_id + _SIGNAL_KEYS 取值 )[ :12 ]
run_id           = sha256( params + git_sha(+dirty_hash) + data_snapshot_id
                          + execution + signal_id )[ :12 ]
family_id        = sha256( kind + grid_spec + base_params + start + end
                          + execution + git_sha + data_snapshot_id + campaign_id )[ :12 ]
```

- 不做 v1 兼容：旧 40 个 run 延后到 Task 23 清理；期间保留在磁盘上但不参与新查询，`run_id` 直接采用上式，`schema_version = 2`。
- 工作区有未提交改动时，`run_id` 追加 `dirty_hash = sha256(git diff -- . ':(exclude)reports' ':(exclude)data')[:8]`，并写 `git_dirty = TRUE`。排除 `reports/`、`data/` 是必须的：镜像与产物本身就是流程写出来的，计入会让同一份代码重跑必换 id。
- `signal_id` 不含 `git_sha`，只含**信号相关代码**的哈希（`signals/trend.py`、`signals/market_state.py`、`signals/reversal.py`、`portfolio/risk_layers.py`、`pipeline._precompute_signals` 源码）。因此改报告、改脚本不会让信号缓存失效。

### 1.2 写入

- 唯一入口 `evaluation.artifacts.store_run()`。
- 暂存目录 `reports/runs/.staging/{run_id}/`，校验通过后 `os.rename` 到 `reports/runs/{run_id}/`。读取层不靠通配符，而是先在 Python 里收集 `*/meta.parquet` 并跳过以 `.` 开头的目录，因此暂存目录永远不会被查询到。
- 目录已存在时的幂等规则：
  - 重名产物逐个比对 sha256：全部相同 → 只补写缺失产物（档位升级）、追加 `attempts.jsonl`、返回；
  - 任一重名产物不同、或同名指标差异超过 `1e-9` → 抛 `ArtifactConflictError`，不覆盖；
  - 指标比较用相对容差，避免浮点噪声误报。
- `created_at`、`generated_at`、绝对路径**不参与**内容哈希。
- `derived/` 目录不参与 run 的内容哈希，单独用 `derived_version` + 输入哈希记录（否则重算派生会让 run「变得不确定」）。
- 并行安全靠「每个 run 只写自己的目录 + 每个 family 成员只写自己的一个文件」，没有任何进程写共享文件。

### 1.3 读取

```python
files = [str(p) for p in root.glob("*/meta.parquet") if not p.parent.name.startswith(".")]
literal = "[" + ",".join("'" + f.replace("'", "''") + "'" for f in files) + "]"
con = duckdb.connect()  # 内存库，不落盘
con.execute(f"CREATE VIEW runs AS SELECT * FROM read_parquet({literal}, union_by_name=true)")
```

`registry.load_runs(root)` 返回「meta 宽表 + 指标透视」，`load_metrics(root)` 返回长表。`root` 为空目录或只有暂存目录时返回空 DataFrame，不抛错。

### 1.4 档位

| `--save-profile` | 产物 | 默认用于 |
|---|---|---|
| `minimal` | `meta.parquet`、`metrics.parquet`、`manifest.json` | 成本敏感性、只看数字的扫描 |
| `standard` | + `equity.parquet`、`weights.parquet`、`holdings.parquet`、`benchmark.parquet` | **全局默认**；网格、消融、假设、OOS |
| `full` | + `transactions.parquet`、`trades.parquet`、`signals/decision_diary.parquet`、`signals/ticker_signals.parquet`、`signals/stages.parquet` | 基准回测、出报告、逐笔对账 |

档位写入 `meta.save_profile`。`run_report.py` / `build_report_data.py` 需要 full，档位不足时**报错并打印重跑命令**，不静默降级。

### 1.5 旧数据处理

- 先把当前顶层产物拷贝到 `reports/legacy/v1.1.1/` 作为回归基准（只做数值对照，不登记）。
- **暂不删除**：旧 run 与 registry 表保留到 Task 23（新机制重跑并校验通过后）。
- 旧的 `grid.json`、`sensitivity*.json`、`ablation.json`、`assumption_sensitivity.json`、`oos_check.json` 拷贝到 `reports/legacy/` 并写明「pre-v2，无 run_id，不可回溯」。这些结论在 Task 20a 重跑后才有证据链。

### 1.6 信号缓存

- `data/cache/signals/{signal_id}/`（锚在 warehouse 同级，可用 `ETF_SIGNAL_CACHE_DIR` 覆盖），每个字段一个 parquet，另加 `scalars.parquet` 与 `manifest.json`。**dtype 原样保存，不降精度**：float32 会改变数值，违反「只允许 N1 一个数值改动」。
- 写入必须原子：先写 `.tmp-{pid}-{rand}/`，校验后 `os.rename` 成正式目录；已存在且 manifest 一致则直接复用，内容不一致则报错不覆盖。这样多个并行会话/进程不会读到半成品，也不会互相污染。
- manifest 记 `price_hash`（价格面板指纹）：合成数据或换数据目录撞了同一 `signal_id` 时按未命中处理。
- 落盘字段：`m21`、`m60`、`vol60`、`zbias`、`rev_active`、`llt80` + `regime`/`comp`/`nas_mom`/`gold_mom`/`nas_vol`/`gold_vol`/`cyb_*` 标量列。
- 明确声明为「派生、不落盘」：`close`、`ret`、`n_days`、`avg20`（可由 warehouse 廉价重算）。
- `ETF_SIGNAL_CACHE=off` 只关闭**读取**（强制重算，用于计时与校验），算完仍写盘供下次热跑；不设置或其它值表示读写都启用。测试进程默认不写共享缓存（除非显式设 `ETF_SIGNAL_CACHE_DIR`）。

---

## 2. 全局约束

- 环境：`.venv\Scripts\python.exe`；运行任何 Python 前 `$env:PYTHONIOENCODING="utf-8"`。
- 不改策略决策、不改回测引擎、不引入新依赖。**唯一允许的数值改动是 N1 基准对齐**，且只改 `benchmark`，不得改 `nav/returns/holdings/trades/metrics`（Task 6 有对照命令）。
- 时间纪律：T 日信号、T+1 成交；所有滚动统计只用 ≤ 当日信息（必要时 `.shift(1)`）。
- 指标唯一来源：绩效数字取 ffn/引擎口径，派生层只做展示性聚合。
- 年化统一用日历日 CAGR（`ffn.calc_cagr`）；波动/Sharpe 用 √252。
- 所有 JSON 输出必须能通过 `json.dumps(payload, allow_nan=False)`；NaN/Inf 一律 `null`，日期一律 `YYYY-MM-DD`。
- 成交额 `amount` 单位是**元**（已核对 `513100.SH` 中位数约 1.03 亿元）。
- 新代码中文 docstring，公式显式写出；每个任务独立 commit。
- 每个任务结束跑：`.venv\Scripts\python.exe -m pytest tests/<该任务的测试文件> -q`；全量回归在 Task 21。
- 新增产物一律 parquet（`compression="zstd"`）；JSON 只用于 manifest/派生数据这类小文件。

---

## 3. Review Focus

1. **确定性**：同一 commit、同参数、同数据，两次运行必须得到同一 `run_id` 与逐字节相同的产物（`created_at` 除外）。任何「把时间戳/绝对路径写进内容哈希」的实现都会让这条失效。
2. **索引语义**：`weights`（目标，T 日）、`holdings`（引擎实际，t 日）、`trades`（成交日）、`diary`（信号日）四套索引不同；join 必须显式 `reindex`，目标权重比较必须 `shift(1)`。
3. **并行写**：Hydra multirun 下任何进程写共享文件（含 DuckDB 文件、summary.json）都会撞锁或互相覆盖；family 汇总只能由单进程 `collect_runs.py` 生成。
4. **预热期 NaN**：前 80/250 个交易日信号为空，滚动指标不得 `fillna(0)` 制造虚假稳定期，必须剔除并给出 `start_date`。
5. **基准对齐**：基准任何一次多余的 `shift` 都会把 `corr` 从 0.51 打到 0；且首日必须与策略一样为零收益。
6. **派生数据串台**：`derived/*.json` 必须能从 `index.json` 的 `run_id` + 输入哈希判断「是不是这份产物的派生」。

---

## 4. 文件结构

```
src/etf_rotation/
  evaluation/
    artifacts.py        # 新增：store_run、SAVE_PROFILES、resolve_run、镜像
    registry.py         # 重写：parquet 登记（meta/metrics/artifacts/families/trials）
    alignment.py        # 新增：lag_correlation
    sweep.py            # 新增：网格点迭代 + 统一扫描驱动（Task 19）
    verify.py           # 新增：产物哈希与跨文件一致性（Task 21）
    prune.py            # 新增：清理大产物（Task 21）
    observability.py    # 修改：build_stages、write(stages=...)
    overfitting.py      # 修改：campaign 级试验数（Task 18）
  signals/
    cache.py            # 新增：signal_id、落盘/读取
  report/
    __init__.py         # SCHEMA_VERSION = 1
    context.py          # ReportContext.load(run_dir)
    serialize.py        # records / series / clean
    runner.py           # 发现 steps、写 derived/*.json + index.json + 镜像
    steps/
      __init__.py
      alignment.py      # N1 自检
      performance.py    # N2
      relative.py       # N3 + N9
      events.py         # N4（event_dates 供 stages 复用）
      costs.py          # N13
      execution.py      # N6 + N8
      roundtrips.py     # N7
      stages.py         # N5
      extremes.py       # N12
      liquidity.py      # N10 + N11
  pipeline.py           # 修改：compute_benchmark（Task 6）、stages 快照（Task 14）、信号缓存（Task 17）
  data/snapshot.py      # 修改：warehouse 指纹
scripts/
  run_backtest.py       # 修改：store_run + 档位 + 镜像
  build_report_data.py  # 新增：--run-id/--latest/--only
  run_grid.py           # 修改：family + store_run
  run_grid_hydra.py     # 修改：family_id 确定性 + store_run（不写库）
  run_heatmap.py        # 修改：store_run + results.json
  run_sensitivity.py    # 修改：store_run(kind="cost")
  run_assumption_sensitivity.py  # 修改：store_run(kind="assumption")
  run_mechanism_ablation.py      # 修改：store_run(kind="ablation")
  run_oos_check.py      # 修改：store_run(kind="oos")
  collect_runs.py       # 新增：family 汇总、index.md
  verify_artifacts.py   # 新增：哈希与跨文件一致性
  prune_runs.py         # 新增：清理大产物
  run_attribution.py / run_exposure.py / run_report.py  # 修改：--run-id
tests/
  test_snapshot_ledger.py
  test_registry_parquet.py
  test_artifacts.py
  test_run_backtest_artifacts.py
  test_alignment.py
  test_report_context.py
  test_report_runner.py
  test_report_performance.py
  test_report_relative.py
  test_report_events.py
  test_report_costs.py
  test_report_execution.py
  test_report_roundtrips.py
  test_report_stages.py
  test_report_extremes.py
  test_report_liquidity.py
  test_signal_cache.py
  test_families.py
  test_sweep.py
  test_verify_artifacts.py
```

---

## 5. 输出契约（前端只依赖这张表）

| 文件 | 章节 / 图表 ID | 内容 |
|---|---|---|
| `derived/index.json` | 全局 | `run_id`、`derived_version`、`generated_at`、`data_snapshot_id`、`inputs{文件:sha256}`、步骤状态 |
| `derived/alignment.json` | C9 / B06 | lag 扫描、峰值 lag、是否通过 |
| `derived/performance.json` | C1 V03/V04、C4 P01–P05 | 水下曲线、回撤事件、年度/月度 |
| `derived/relative.json` | C1 V02、C5 R02/R03、C6 B01–B05、C7 A06 | 相对指标、滚动、超额、剔除防守 |
| `derived/events.json` | C3 D01–D03 | 调仓事件表、触发规则、事后收益 |
| `derived/costs.json` | C7 A04、C8 X08 | 分年费用、拖累、盈亏平衡成本 |
| `derived/execution.json` | C8 X01/X02 | 目标 vs 实际、换手分解 |
| `derived/roundtrips.json` | C8 X07 | 单笔往返、持有期、盈亏 |
| `derived/stages.json` | C3 D09 | 事件阶段归因（瀑布） |
| `derived/extremes.json` | C5 R07 | 极端日 |
| `derived/liquidity.json` | C8 X09/X10 | 滑点、容量 |

前端读法不变；`index.json.run_id` 是新增的必需字段，前端应在标题处展示，便于确认看的是哪次回测。

---

# Stage A：基础设施（不改策略数值）

## Task 1: 冻结基线、归档旧记录（不删除）

**Files:**
- Create: `reports/legacy/README.md`（说明 pre-v2 不可回溯）
- Move: 旧 JSON → `reports/legacy/`
- Delete: `reports/runs/`、`warehouse.duckdb` 的 `runs`/`run_metrics`
- Copy: 当前产物 → `reports/legacy/v1.1.1/`

**Interfaces:**
- Produces: `reports/legacy/v1.1.1/{equity.csv,weights.parquet,metrics.json,transactions.csv,holdings.csv,benchmark.csv,signals/*.parquet}`，供后续任务做「策略数值不变」对照。

- [ ] **Step 1: 冻结当前产物**

```powershell
$env:PYTHONIOENCODING="utf-8"
New-Item -ItemType Directory -Force reports\legacy\v1.1.1\signals | Out-Null
Copy-Item reports\equity.csv,reports\weights.parquet,reports\metrics.json,reports\transactions.csv,reports\holdings.csv,reports\benchmark.csv reports\legacy\v1.1.1\
Copy-Item reports\signals\decision_diary.parquet,reports\signals\ticker_signals.parquet reports\legacy\v1.1.1\signals\
```

- [ ] **Step 2: 归档旧汇总 JSON**

```powershell
Copy-Item reports\grid.json,reports\sensitivity_summary.json,reports\ablation.json,reports\assumption_sensitivity.json,reports\oos_check.json,reports\sensitivity.json reports\legacy\
New-Item -ItemType Directory -Force reports\legacy\sensitivity | Out-Null
Copy-Item reports\sensitivity\*.json reports\legacy\sensitivity\
```

- [ ] **Step 3: 写 `reports/legacy/README.md`、放行 git、生成 worktree 数据环境脚本**

README 内容固定为三行：这些文件产生于 v1.1.1；没有 `run_id`，无法关联代码/数据版本；结论需在 Task 20a 重跑后引用。
`.gitignore` 末尾追加：

```
reports/legacy/**
!reports/legacy/README.md
```

新建 `scripts/activate_data.ps1`（供并行 worktree 复用主仓库的数据与虚拟环境）：

```powershell
param([string]$DataRoot = "D:\project\quant_1")

# Reuse the main checkout's data and virtualenv from a git worktree.
# NOTE: keep this file ASCII-only. PowerShell 5.1 reads BOM-less .ps1 as ANSI,
# and a multi-byte CJK comment can swallow the following newline.
$env:PYTHONIOENCODING = "utf-8"
$env:ETF_BARS_PARQUET    = "$DataRoot\data\bronze\tushare\tushare-f4f7c81a15b5779c\bars_daily.parquet"
$env:ETF_ADJ_PARQUET     = "$DataRoot\data\bronze\tushare\tushare-f4f7c81a15b5779c\fund_adj.parquet"
$env:ETF_SYMBOLS_PARQUET = "$DataRoot\data\bronze\tushare\tushare-f4f7c81a15b5779c\symbols.parquet"
$env:ETF_INDEX_PARQUET   = "$DataRoot\data\bronze\tushare\tushare_index-86318b52ea0fbe04\index_daily.parquet"
$env:ETF_FETCHED_DIR     = "$DataRoot\data\bronze\tushare\etf_rotation"
$env:ETF_WAREHOUSE_DUCKDB= "$DataRoot\data\warehouse.duckdb"
$env:PY = "$DataRoot\.venv\Scripts\python.exe"

# Worktrees do not get the gitignored reports/ tree: copy the baseline reference in.
$legacyDst = Join-Path (Get-Location) "reports\legacy"
if (-not (Test-Path "$legacyDst\v1.1.1")) {
    New-Item -ItemType Directory -Force $legacyDst | Out-Null
    Copy-Item "$DataRoot\reports\legacy\v1.1.1" $legacyDst -Recurse -Force
}
```

- [ ] **Step 4: 暂留旧数据（删除延后到 Task 23）**

不要删除 `reports/runs/`，也不要 `DROP` 仓库里的 `runs`/`run_metrics`。新读取层只扫 `*/meta.parquet`，旧目录没有这个文件，不会被查询到；保留它们是为了在 S0–C3 期间随时和旧结果对照。

删除的触发条件是 Task 20b 的基线重跑 + `verify_artifacts` 通过，见 Task 23。

- [ ] **Step 5: 验证**

Run: `Get-ChildItem reports\legacy\v1.1.1 -Recurse | Measure-Object`
Expected: 至少 8 个文件。
Run: `(Get-ChildItem reports\runs -Directory).Count`
Expected: `40`（旧 run 原样保留）。
Run: `.venv\Scripts\python.exe -c "import duckdb;print([r[0] for r in duckdb.connect('data/warehouse.duckdb').execute('show tables').fetchall()])"`
Expected: 仍含 `runs`/`run_metrics`（暂留，Task 23 再删）。
Run: `.venv\Scripts\python.exe -m pytest tests -q`
Expected: 全部 PASS（本任务未改代码）。

- [ ] **Step 6: 提交**

```bash
git add .gitignore reports/legacy/README.md scripts/activate_data.ps1
git commit -m "chore: 归档 v1.1.1 产物与 worktree 环境脚本"
```

> `reports/` 下的大文件被 `.gitignore` 忽略，本次只提交 `.gitignore`、README 与环境脚本。

---

## Task 2: 数据快照与环境标识

**Files:**
- Modify: `src/etf_rotation/data/snapshot.py`
- Create: `tests/test_snapshot_ledger.py`
- Modify: `src/etf_rotation/evaluation/registry.py`（只加 `env_lock_hash`、`git_info`）

**Interfaces:**
- Produces: `snapshot.warehouse_fingerprint(con) -> dict[str, dict]`，键为表名，值为 `{"rows": int, "ts_min": str, "ts_max": str, "hash": int}`。
- Produces: `snapshot.data_snapshot_id() -> str`（bronze 文件哈希 + `warehouse.manifest.json` 的哈希，`[:12]`）。
- Produces: `snapshot.verify_warehouse(strict: bool = False) -> None`，指纹不一致时抛 `RuntimeError`。
- Produces: `registry.env_lock_hash() -> str`、`registry.git_info() -> tuple[str, str]`（`sha`, `dirty_hash`，干净时 `dirty_hash=""`）。
- Produces: `signals.cache.signal_id(params: dict, data_snapshot_id: str) -> str`（纯函数，Task 5 计算 `run_id` 时就要用，Task 17 才加缓存读写）。
- Consumes: `data/paths.WAREHOUSE`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_snapshot_ledger.py
import duckdb
import pytest
from etf_rotation.data import snapshot

def test_fingerprint_changes_when_row_changes(tmp_path):
    db = tmp_path / "w.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE close_adj (symbol_id INT, ts DATE, close_adj DOUBLE)")
    con.execute("INSERT INTO close_adj VALUES (1, DATE '2024-01-02', 10.0)")
    a = snapshot.warehouse_fingerprint(con)
    con.execute("INSERT INTO close_adj VALUES (1, DATE '2024-01-03', 11.0)")
    b = snapshot.warehouse_fingerprint(con)
    assert a["close_adj"]["hash"] != b["close_adj"]["hash"]
    assert b["close_adj"]["rows"] == 2

def test_fingerprint_is_stable(tmp_path):
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    con.execute("CREATE TABLE bars_daily (symbol_id INT, ts DATE, open DOUBLE, high DOUBLE,"
                " low DOUBLE, close DOUBLE, volume BIGINT, amount DOUBLE)")
    con.execute("INSERT INTO bars_daily VALUES (1, DATE '2024-01-02', 1, 1, 1, 1, 100, 1000)")
    assert snapshot.warehouse_fingerprint(con) == snapshot.warehouse_fingerprint(con)

def test_verify_raises_on_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "load_manifest", lambda: {"close_adj": {"rows": 1, "hash": 0}})
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    con.execute("CREATE TABLE close_adj (symbol_id INT, ts DATE, close_adj DOUBLE)")
    con.execute("INSERT INTO close_adj VALUES (1, DATE '2024-01-02', 10.0)")
    with pytest.raises(RuntimeError):
        snapshot.verify_warehouse(con=con, strict=True)

def test_signal_id_ignores_non_signal_params():
    from etf_rotation.signals import cache
    p = {"trend": {"windows": [21, 60], "weighting": "linear"},
         "risk": {"vol_window": 60}, "dedupe": {"corr_threshold": 0.8}}
    a = cache.signal_id(p, "d1")
    p["dedupe"]["corr_threshold"] = 0.75
    assert cache.signal_id(p, "d1") == a
    p["trend"]["windows"] = [20, 60]
    assert cache.signal_id(p, "d1") != a
    assert cache.signal_id(p, "d2") != cache.signal_id(p, "d1")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_snapshot_ledger.py -q`
Expected: FAIL，`warehouse_fingerprint` 不存在。

- [ ] **Step 3: 实现指纹**

固定列清单（与 `curate_data.py` 写入的表一致）：

```python
_TABLES = {
    "close_adj": ("symbol_id", "ts", "close_adj"),
    "bars_daily": ("symbol_id", "ts", "open", "high", "low", "close", "volume", "amount"),
    "symbols": ("symbol_id", "ticker"),
}
```

每表执行 `SELECT count(*) AS rows, min(ts), max(ts), sum(hash(<列...>)) AS hash FROM <表>`；表不存在时跳过并记录 `missing`。结果写 `data/warehouse.manifest.json`（在 `curate_data.py` 末尾调用一次），`verify_warehouse` 比对当前指纹与 manifest。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_snapshot_ledger.py -q` → PASS

- [ ] **Step 5: 实现 env_lock_hash、git_info 与 signal_id**

`env_lock_hash = sha256(requirements.txt 字节 + sys.version + bt/pandas/numpy/duckdb/pyarrow/ffn 的 __version__)[:12]`。
`git_info`：`git rev-parse --short HEAD` 与 `git status --porcelain --untracked-files=no -- . ':(exclude)reports' ':(exclude)data'`；非空时 `dirty_hash = sha256(git diff 同 pathspec)[:8]`。`reports/`、`data/` 是运行期产物，必须排除（否则重跑换 id）。
`signal_id`：`sha256(data_snapshot_id + json(signal_cache_key(params)) + code_hash)[:12]`，其中 `code_hash` 对 §1.1 列出的信号文件与 `pipeline._precompute_signals` 源码（`inspect.getsource`）取哈希；**不含 git_sha**。

- [ ] **Step 6: 验证真实数据**

Run: `.venv\Scripts\python.exe -c "from etf_rotation.data import snapshot; print(snapshot.data_snapshot_id())"`
Expected: 12 位十六进制；连续两次调用相同。
Run: `.venv\Scripts\python.exe -c "from etf_rotation.evaluation import registry; print(registry.env_lock_hash(), registry.git_info())"`
Expected: 12 位哈希 + `(sha, '')`（工作区干净时）。

- [ ] **Step 7: 提交**

```bash
git add src/etf_rotation/data/snapshot.py src/etf_rotation/evaluation/registry.py src/etf_rotation/signals/cache.py tests/test_snapshot_ledger.py scripts/curate_data.py
git commit -m "feat(registry): 数据快照指纹、环境标识与 signal_id"
```

---

## Task 3: parquet 登记层

**Files:**
- Rewrite: `src/etf_rotation/evaluation/registry.py`
- Create: `tests/test_registry_parquet.py`
- Delete from: `tests/test_registry.py`（旧 duckdb 断言，改为新文件覆盖）

**Interfaces:**
- Produces: `registry.RUNS_DIR`、`registry.FAMILIES_DIR`、`registry.STAGING_DIR`（均为 `Path`，默认 `reports/runs`、`reports/families`、`reports/runs/.staging`）。
- Produces: `registry.run_identity(params: dict, *, git_sha: str, dirty_hash: str, data_snapshot_id: str, execution: str, signal_id: str) -> str`（按 §1.1 公式；`dirty_hash` 非空时并入哈希）。
- Produces: `registry.ArtifactInfo = namedtuple("ArtifactInfo", "name path sha256 bytes rows cols")`。
- Produces: `registry.write_run(root: Path, run_id: str, meta: dict, metrics: dict, artifacts: list[ArtifactInfo]) -> Path`：写 `meta.parquet`（单行）、`metrics.parquet`（长表 `run_id, metric, value`）、`artifacts.parquet`、`manifest.json`。
- Produces: `registry.load_runs(root: Path) -> pd.DataFrame`（meta 列 + 指标透视列）、`registry.load_metrics(root: Path) -> pd.DataFrame`（长表）。
- Produces: `registry.content_hash(meta: dict, metrics: dict, artifact_hashes: dict[str, str]) -> str`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_registry_parquet.py
import pandas as pd
from etf_rotation.evaluation import registry

def test_write_and_load_roundtrip(tmp_path):
    art = registry.ArtifactInfo("weights", "weights.parquet", "abc", 10, 3, 2)
    registry.write_run(tmp_path, "r1", {"kind": "backtest", "schema_version": 2,
                       "created_at": "2026-10-24T00:00:00Z"}, {"sharpe": 1.1, "ann_return": 0.1}, [art])
    runs = registry.load_runs(tmp_path)
    assert runs.loc[0, "run_id"] == "r1"
    assert runs.loc[0, "sharpe"] == 1.1
    assert runs.loc[0, "kind"] == "backtest"

def test_empty_root_returns_empty(tmp_path):
    assert registry.load_runs(tmp_path).empty

def test_content_hash_ignores_timestamp(tmp_path):
    a = registry.content_hash({"x": 1, "created_at": "A"}, {"s": 1.0}, {"w": "h"})
    b = registry.content_hash({"created_at": "B", "x": 1}, {"s": 1.0}, {"w": "h"})
    assert a == b
    c = registry.content_hash({"x": 2, "created_at": "A"}, {"s": 1.0}, {"w": "h"})
    assert a != c
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_registry_parquet.py -q`
Expected: FAIL。

- [ ] **Step 3: 实现**

`write_run`：`meta` 除 `params_json` 外全部转成标量列；`run_id` 以参数为准（`{"run_id": run_id, **meta}` 中参数优先）；`created_at` 由调用方传入；`metrics` 的每个值 `float(v)`，非数值抛 `TypeError`。
`load_runs`：先收集 `[p for p in root.glob("*/meta.parquet") if not p.parent.name.startswith(".")]`，为空则返回空表；用 `duckdb.connect()` 对**显式文件列表**建 `meta`、`pivot` 两个视图（列表拼成 SQL 字面量，路径做单引号转义），`LEFT JOIN` 后返回。
`content_hash`：`json.dumps({k: v for k, v in meta.items() if k not in ("created_at", "path")}, sort_keys=True)` + 按 key 排序的 metrics 与 artifact 哈希，拼成一个 blob 后 sha256。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 删除旧的 duckdb 测试**

`tests/test_registry.py` 中依赖 `runs` 表的用例删除；`run_identity` 的用例保留并移到 `tests/test_registry_parquet.py`，断言「参数/数据/执行口径/signal_id 任一变化 → id 变化」。

- [ ] **Step 6: 提交**

```bash
git add src/etf_rotation/evaluation/registry.py tests/test_registry_parquet.py tests/test_registry.py
git commit -m "refactor(registry): 登记层改为 parquet + duckdb 只读查询"
```

---

## Task 4: `store_run` 唯一写入口与档位

**Files:**
- Create: `src/etf_rotation/evaluation/artifacts.py`
- Create: `tests/test_artifacts.py`

**Interfaces:**
- Produces: `artifacts.SAVE_PROFILES = {"minimal": (), "standard": ("equity", "weights", "holdings", "benchmark"), "full": ("equity", "weights", "holdings", "benchmark", "transactions", "trades", "diary", "ticker_signals", "stages")}`。
- Produces: `artifacts.store_run(*, root: Path, run_id: str, kind: str, profile: str, meta: dict, metrics: dict, frames: dict[str, pd.DataFrame]) -> Path`。
  - `frames` 的键必须属于 `SAVE_PROFILES["full"]`；档位决定实际写哪些，`frames` 可以是档位的子集（该 run 没有的产物就不传）。
  - 文件名映射：`equity→equity.parquet`、`weights→weights.parquet`、`holdings→holdings.parquet`、`benchmark→benchmark.parquet`、`transactions→transactions.parquet`、`trades→trades.parquet`、`diary→signals/decision_diary.parquet`、`ticker_signals→signals/ticker_signals.parquet`、`stages→signals/stages.parquet`。
- Produces: `artifacts.resolve_run(root: Path, run_id: str | None = None) -> Path`（`None` 读 `reports/latest.json`）。
- Produces: `artifacts.mirror_latest(run_dir: Path, reports_dir: Path) -> None`（写 `latest.json` + 顶层兼容副本）。
- Produces: `artifacts.ArtifactConflictError(RuntimeError)`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_artifacts.py
import pandas as pd
import pytest
from etf_rotation.evaluation import artifacts

def _frames():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    return {"equity": pd.DataFrame({"nav": [1.0, 1.01]}, index=idx),
            "weights": pd.DataFrame({"A": [0.5, 0.5]}, index=idx),
            "holdings": pd.DataFrame({"A": [0.5, 0.5]}, index=idx),
            "transactions": pd.DataFrame({"Date": idx, "Security": ["A", "A"],
                                          "price": [1.0, 1.0], "quantity": [0.5, 0.5]})}

def _store(tmp_path, profile, frames=None, sharpe=1.0):
    return artifacts.store_run(root=tmp_path, run_id="r1", kind="backtest", profile=profile,
                               meta={"kind": "backtest", "schema_version": 2,
                                     "created_at": "2026-10-24T00:00:00Z"},
                               metrics={"sharpe": sharpe}, frames=frames or _frames())

def test_profile_contents(tmp_path):
    p = _store(tmp_path, "minimal")
    assert (p / "meta.parquet").exists() and not (p / "equity.parquet").exists()
    p = artifacts.store_run(root=tmp_path, run_id="r2", kind="backtest", profile="standard",
                            meta={"kind": "backtest", "schema_version": 2, "created_at": "x"},
                            metrics={"sharpe": 1.0}, frames=_frames())
    assert (p / "equity.parquet").exists() and not (p / "transactions.parquet").exists()

def test_upgrade_profile_is_idempotent(tmp_path):
    _store(tmp_path, "standard")
    p = _store(tmp_path, "full")
    assert (p / "transactions.parquet").exists()
    assert (p / "attempts.jsonl").read_text(encoding="utf-8").count("\n") == 2

def test_conflict_raises_and_keeps_original(tmp_path):
    _store(tmp_path, "standard")
    bad = _frames()
    bad["equity"] = bad["equity"] * 1.5
    with pytest.raises(artifacts.ArtifactConflictError):
        _store(tmp_path, "standard", frames=bad)
    assert not list((tmp_path / "r1").glob("*.tmp"))

def test_failure_leaves_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "write_frames", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        _store(tmp_path, "standard")
    assert not (tmp_path / "r1").exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_artifacts.py -q`
Expected: FAIL，`artifacts` 不存在。

- [ ] **Step 3: 实现**

要点（顺序不可换）：
1. 校验 `profile` 与 `frames` 键；`root/.staging/{run_id}` 必须为空目录。
2. `write_frames(staging, names, frames)`：每个 DataFrame `to_parquet(path, compression="zstd")`，`signals/` 子目录按需建。
3. 计算每个文件的 sha256/bytes/rows/cols → `ArtifactInfo`。
4. `registry.write_run(staging, ...)` 写 meta/metrics/artifacts/manifest；`meta` 补 `save_profile=profile`、`run_id`，缺 `created_at` 时用 `datetime.now(timezone.utc).isoformat()`。
5. 目标目录不存在 → `os.rename(staging, final)`；存在 → 逐产物比对（见 §1.2），升级则补写，冲突抛错；无论哪种都追加 `attempts.jsonl`。
6. 任何异常都 `shutil.rmtree(staging, ignore_errors=True)` 后重新抛出。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 实现 `resolve_run` 与 `mirror_latest`**

`resolve_run`：`run_id` 为 `None` 时读 `reports/latest.json` 的 `run_id`；目录不存在抛 `FileNotFoundError` 并提示可用的 5 个 run_id。
`mirror_latest`：写 `latest.json`（`{"run_id", "family_id", "kind", "profile", "updated_at"}`，临时文件 + `os.replace`）；把 `equity.parquet → reports/equity.csv`、`weights.parquet → reports/weights.parquet`、`holdings.parquet → reports/holdings.csv`、`transactions.parquet → reports/transactions.csv`、`benchmark.parquet → reports/benchmark.csv`、`metrics.parquet → reports/metrics.json`（宽表）、`signals/* → reports/signals/*`；缺哪个跳过哪个。

- [ ] **Step 6: 提交**

```bash
git add src/etf_rotation/evaluation/artifacts.py tests/test_artifacts.py
git commit -m "feat(artifacts): store_run 唯一写入口与档位"
```

---

## Task 5: `run_backtest` 接入 + 交易明细上移 + 顶层镜像

**Files:**
- Modify: `scripts/run_backtest.py`
- Modify: `src/etf_rotation/evaluation/metrics.py`（`from_stats` 保留，另加 `all_stats`）
- Modify: `scripts/run_report.py`（改读镜像，不再写 `trades.csv`）
- Create: `tests/test_run_backtest_artifacts.py`

**Interfaces:**
- Produces: `metrics.all_stats(stats: pd.Series) -> dict[str, float]`（保留全部数值型 ffn 统计）。
- Produces: `metrics.build_equity_frame(nav, returns, cash, turnover, fees) -> pd.DataFrame`（列固定 `nav/returns/cash/turnover/fees`）。
- Produces: `run_backtest.py --save-profile {minimal,standard,full}`（默认 `standard`）。
- Produces: run 目录内容按档位；`equity` 固定含五列。
- Consumes: `artifacts.store_run`、`artifacts.mirror_latest`、`trades.build_trade_table_from_engine`、`cache.signal_id`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_run_backtest_artifacts.py
import pandas as pd
from etf_rotation.evaluation import metrics

def test_all_stats_keeps_extra_ffn_columns():
    s = pd.Series({"cagr": 0.1, "daily_sharpe": 1.0, "daily_sortino": 1.2,
                   "max_drawdown": -0.1, "calmar": 1.0, "daily_vol": 0.1,
                   "monthly_sharpe": 0.9, "some_text": "x"})
    out = metrics.all_stats(s)
    assert out["sharpe"] == 1.0
    assert out["monthly_sharpe"] == 0.9
    assert "some_text" not in out

def test_equity_frame_has_turnover_and_fees():
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    nav = pd.Series([1.0, 1.01], index=idx)
    out = metrics.build_equity_frame(nav, nav.pct_change().fillna(0.0),
                                     pd.Series([1.0, 0.9], index=idx),
                                     pd.Series([0.0, 0.1], index=idx),
                                     pd.Series([0.0, 0.001], index=idx))
    assert list(out.columns) == ["nav", "returns", "cash", "turnover", "fees"]
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

- `metrics.all_stats`：遍历 `stats.items()`，只保留 `isinstance(v, (int, float))` 且非 bool 的项；`sharpe/sortino/max_drawdown/calmar/ann_return/ann_vol` 做键名映射，其余同名保留。
- `metrics.build_equity_frame(...)`：纯函数，拼五列。
- `main()` 里：`s = {**metrics.all_stats(res.stats), "turnover": float(res.turnover.mean()), "total_fees": float(res.fees.sum())}`；`frames` 组装 `equity/weights/holdings/benchmark/transactions/trades/diary/ticker_signals`（`stages` 由 Task 14 加入）；`meta` 至少含 `kind="backtest"、schema_version=2、run_id、signal_id、data_snapshot_id、git_sha、git_dirty、dirty_hash、env_lock_hash、execution、start、end、n_obs=int(res.returns.notna().sum())、save_profile、params_json、created_at`；`run_id` 用 `registry.run_identity(...)`；`store_run(profile=args.save_profile)`；`mirror_latest`；删除原来的 `to_csv/to_parquet` 块。
- `run_report.py` 的 `tx = ...` 改为读 `reports/transactions.csv`，`t = pd.read_csv(REPORTS / "trades.csv")`，删除 `t.to_csv` 块；开头读 `reports/latest.json`，`profile != "full"` 时 `sys.exit("最新 run 档位是 standard，请重跑：... --save-profile full")`。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 重跑并对照策略数值**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
.venv\Scripts\python.exe -c "import pandas as pd; a=pd.read_csv('reports/legacy/v1.1.1/equity.csv',parse_dates=['ts']).set_index('ts'); b=pd.read_csv('reports/equity.csv',parse_dates=['ts']).set_index('ts'); print('max nav diff', (a['nav']-b['nav']).abs().max()); print('max ret diff', (a['returns']-b['returns']).abs().max())"
```
Expected: 两个差值均为 0（Task 6 之前）。

- [ ] **Step 6: 检查目录内容**

Run: `Get-ChildItem reports\runs -Recurse -File | Select-Object Name`
Expected: 含 `meta.parquet`、`metrics.parquet`、`artifacts.parquet`、`manifest.json`、`equity/weights/holdings/benchmark/transactions/trades.parquet`、`signals/decision_diary.parquet`、`signals/ticker_signals.parquet`。

- [ ] **Step 7: 提交**

```bash
git add scripts/run_backtest.py scripts/run_report.py src/etf_rotation/evaluation/metrics.py tests/test_run_backtest_artifacts.py
git commit -m "feat(run): 回测产物按 run 落盘并新增档位与交易明细"
```

---

## Task 6: 修基准对齐（N1）+ lag 扫描

**Files:**
- Modify: `src/etf_rotation/pipeline.py:674-706`（`compute_benchmark`）
- Create: `src/etf_rotation/evaluation/alignment.py`
- Test: `tests/test_alignment.py`

**Interfaces:**
- Produces: `alignment.lag_correlation(strategy: pd.Series, benchmark: pd.Series, max_lag: int = 5) -> pd.Series`（index=lag；`corr_k = Corr(s_t, b_{t+k})`，k 为策略相对基准的滞后，`k=-1` 表示策略晚一天；索引按 `|lag|` 升序返回，保证周期样本出现并列峰值时 `idxmax` 命中 0）。
- Produces: `compute_benchmark` 列不变，日期语义为「t 日净值含 t 日收益」，且第 1 个交易日收益为 0。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_alignment.py
import numpy as np
import pandas as pd
import pytest
from etf_rotation import pipeline
from etf_rotation.evaluation.alignment import lag_correlation

def test_lag_correlation_peaks_at_zero_when_aligned():
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    b = pd.Series([0.01, -0.02, 0.03, 0.0, -0.01] * 12, index=idx)
    corr = lag_correlation(b * 0.8 + 0.001, b)
    assert corr.idxmax() == 0 and corr.loc[0] > 0.99

def test_lag_correlation_detects_one_day_lag():
    idx = pd.date_range("2024-01-01", periods=60, freq="B")
    b = pd.Series([0.01, -0.02, 0.03, 0.0, -0.01] * 12, index=idx)
    assert lag_correlation(b.shift(1).fillna(0.0), b).idxmax() == -1

def test_benchmark_uses_same_day_return(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=4, freq="B")
    hs = pd.Series([100.0, 110.0, 99.0, 108.9], index=idx)
    close = pd.DataFrame({"A": [10.0, 11.0, 9.9, 10.89]}, index=idx)
    amt = pd.DataFrame({"A": [1e8] * 4}, index=idx)
    fb = pd.DataFrame({"ts_code": ["A"]})
    monkeypatch.setattr(pipeline, "load_prices", lambda: (close, close, amt))
    monkeypatch.setattr(pipeline, "load_indices", lambda: {"000300.SH": hs})
    monkeypatch.setattr(pipeline, "load_fund_basic", lambda: fb)
    monkeypatch.setattr(pipeline.univ, "classify", lambda _: {"A": "risk"})
    monkeypatch.setattr(pipeline.calendar, "trading_days", lambda s, e: idx)
    out = pipeline.compute_benchmark(
        {"universe": {"min_listed_days": 0, "min_avg_amount20": 0}}, "2024-01-01", "2024-01-04")
    assert out["hs300"].pct_change().iloc[1] == pytest.approx(hs.pct_change().iloc[1])

def test_benchmark_first_day_is_flat(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    hs = pd.Series([100.0, 110.0, 99.0], index=idx)
    close = pd.DataFrame({"A": [10.0, 11.0, 9.9]}, index=idx)
    amt = pd.DataFrame({"A": [1e8] * 3}, index=idx)
    monkeypatch.setattr(pipeline, "load_prices", lambda: (close, close, amt))
    monkeypatch.setattr(pipeline, "load_indices", lambda: {"000300.SH": hs})
    monkeypatch.setattr(pipeline, "load_fund_basic", lambda: pd.DataFrame({"ts_code": ["A"]}))
    monkeypatch.setattr(pipeline.univ, "classify", lambda _: {"A": "risk"})
    monkeypatch.setattr(pipeline.calendar, "trading_days", lambda s, e: idx)
    out = pipeline.compute_benchmark(
        {"universe": {"min_listed_days": 0, "min_avg_amount20": 0}}, "2024-01-01", "2024-01-03")
    assert out["hs300"].iloc[0] == pytest.approx(1.0)
    assert out["benchmark"].iloc[0] == pytest.approx(1.0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests/test_alignment.py -q`
Expected: FAIL（模块不存在 / 首日不为 1）。

- [ ] **Step 3: 实现**

`compute_benchmark`：删掉 `bench_ret.shift(1)`、`hs_ret.shift(1)`；`reindex(days)` 后立刻 `iloc[0] = 0.0`，注释写明「策略首日建仓无收益，基准首日同样置零，避免超额收益带虚假首日项」。
`lag_correlation`：`for k in range(-max_lag, max_lag+1): strategy.corr(benchmark.shift(k))`。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 真实数据验证**

```powershell
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
.venv\Scripts\python.exe -c "import pandas as pd; from etf_rotation.evaluation.alignment import lag_correlation; e=pd.read_csv('reports/equity.csv',parse_dates=['ts']).set_index('ts'); b=pd.read_csv('reports/benchmark.csv',parse_dates=['ts']).set_index('ts'); print(lag_correlation(e['returns'], b['hs300'].pct_change()).round(3))"
```
Expected: 峰值在 `0`，`corr(0) ≈ 0.51`。
Run: 与 `reports/legacy/v1.1.1/equity.csv` 比较 `nav`
Expected: 差值 0（基准修复不得影响策略净值）。

- [ ] **Step 6: 提交**

```bash
git add src/etf_rotation/pipeline.py src/etf_rotation/evaluation/alignment.py tests/test_alignment.py
git commit -m "fix(benchmark): 基准改用同日收益并对齐首日"
```

---

# Stage B：报告派生数据（N1–N13）

> 以下每个任务的产物都写到 `reports/runs/{run_id}/derived/<step>.json`，并由 runner 镜像到 `reports/derived/`。所有 step 只读 `ReportContext`，不碰文件系统。

## Task 7: 报告骨架（context / serialize / runner / CLI）

**Files:**
- Create: `src/etf_rotation/report/__init__.py`、`context.py`、`serialize.py`、`runner.py`、`steps/__init__.py`、`steps/alignment.py`
- Create: `scripts/build_report_data.py`
- Create: `tests/test_report_context.py`、`tests/test_report_runner.py`

**Interfaces:**
- Produces: `ReportContext.load(run_dir: Path, *, strict_snapshot: bool = False) -> ReportContext`，字段：`run_id, meta, params, metrics, equity, benchmark, weights, holdings, trades, transactions, diary, ticker_signals, stages, classification, close, opn, amount`。`metrics` 是 `{指标名: float}`（来自 `metrics.parquet`；NaN 指标会被 `all_stats` 丢掉，取值方必须容忍缺键）。
- Produces: step 模块暴露 `NAME: str` 与 `build(ctx: ReportContext) -> dict`。
- Produces: `runner.run(run_dir: Path, ctx: ReportContext, only: list[str] | None = None, mirror_to: Path | None = None) -> dict[str, dict]`。
- Produces: `serialize.records(df, index="date") -> list[dict]`、`serialize.series(s) -> {"dates": [...], "values": [...]}`、`serialize.clean(obj) -> Any`。
- Produces: `index.json` 字段：`schema_version, derived_version, run_id, generated_at, data_snapshot_id, inputs{name: sha256}, steps{name: {ok, duration_ms, error}}`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_context.py
import pandas as pd
import pytest
from etf_rotation.report.context import ReportContext

def _make_run(tmp_path):
    from etf_rotation.evaluation import artifacts
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    frames = {"equity": pd.DataFrame({"nav": [1.0, 1.01], "returns": [0.0, 0.01],
                                      "cash": [1.0, 0.99], "turnover": [0.0, 0.0],
                                      "fees": [0.0, 0.0]}, index=idx),
              "weights": pd.DataFrame({"A": [1.0, 1.0]}, index=idx)}
    return artifacts.store_run(root=tmp_path, run_id="r1", kind="backtest", profile="standard",
                               meta={"kind": "backtest", "schema_version": 2,
                                     "data_snapshot_id": "d1", "run_id": "r1",
                                     "created_at": "2026-10-24T00:00:00Z"},
                               metrics={"sharpe": 1.0}, frames=frames)

def test_load_reads_run_dir_and_meta(tmp_path, monkeypatch):
    from etf_rotation import pipeline
    from etf_rotation.data import universe
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    prices = pd.DataFrame({"A": [10.0, 10.1]}, index=idx)
    monkeypatch.setattr(pipeline, "load_prices", lambda: (prices, prices, prices))
    monkeypatch.setattr(pipeline, "load_fund_basic", lambda: pd.DataFrame({"ts_code": ["A"]}))
    monkeypatch.setattr(universe, "classify", lambda _: {"A": "risk"})
    ctx = ReportContext.load(_make_run(tmp_path), strict_snapshot=False)
    assert ctx.run_id == "r1"
    assert ctx.equity["nav"].iloc[-1] == 1.01
    assert ctx.stages is None

def test_missing_meta_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ReportContext.load(tmp_path / "nope")

def test_strict_snapshot_rejects_mismatch(tmp_path, monkeypatch):
    from etf_rotation.data import snapshot
    monkeypatch.setattr(snapshot, "data_snapshot_id", lambda: "other")
    with pytest.raises(RuntimeError):
        ReportContext.load(_make_run(tmp_path), strict_snapshot=True)
```

```python
# tests/test_report_runner.py
import json
import numpy as np
import pandas as pd
from etf_rotation.report import runner
from etf_rotation.report.context import ReportContext

def test_index_has_run_id_and_inputs(tmp_path):
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    b = pd.Series(np.sin(np.arange(30)) * 0.01, index=idx)
    ctx = ReportContext(run_id="r1", meta={"data_snapshot_id": "d1"}, params={},
                        equity=pd.DataFrame({"nav": (1 + b).cumprod(), "returns": b}, index=idx),
                        benchmark=pd.DataFrame({"hs300": (1 + b).cumprod()}, index=idx),
                        weights=None, holdings=None, trades=None,
                        transactions=None, diary=None, ticker_signals=None, stages=None,
                        classification={}, close=None, opn=None, amount=None)
    out = runner.run(tmp_path, ctx, only=["alignment"], mirror_to=None)
    idx_json = json.loads((tmp_path / "derived" / "index.json").read_text(encoding="utf-8"))
    assert idx_json["run_id"] == "r1"
    assert idx_json["steps"]["alignment"]["ok"] is True
    assert "inputs" in idx_json
    assert "NaN" not in (tmp_path / "derived" / "alignment.json").read_text(encoding="utf-8")
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

- `context.py`：读 `meta.parquet` 单行 → `meta`，**先**校验 `schema_version` 与（`strict_snapshot=True` 时）`data_snapshot_id`，再加载产物；`params = json.loads(meta["params_json"])`；按 §1.4 读已有产物（缺则 `None`）；`classification = universe.classify(load_fund_basic())`；价格面板 `load_prices()` 一次加载。
- `serialize.py`：`clean` 递归处理 `Timestamp→YYYY-MM-DD`、numpy 标量、`NaN/Inf→None`；`records` 先把 index 转成列并格式化日期；`series` 丢掉 NaN 日期但保留 `None` 值。
- `runner.py`：`pkgutil.iter_modules(steps.__path__)` 发现模块；先写临时目录，全部成功后改名；`index.json` 的 `inputs` 取自 `artifacts.parquet` 的 `name→sha256`，该文件不存在时写空 dict；任一步异常只写 `ok=False, error=str(exc)`；`mirror_to` 时 `copytree` 覆盖。
- `steps/alignment.py`：`lag_correlation(ctx.equity["returns"], ctx.benchmark["hs300"].pct_change())`，输出 `{"lags", "corrs", "peak_lag", "ok"}`；`lags/corrs` 必须按 lag 数值升序（函数返回的是 `|lag|` 序，直接序列化会让前端横轴变成 0,1,-1,2…），`peak_lag` 在原始序列上取 `idxmax`；`benchmark is None` 时抛 `RuntimeError("benchmark 缺失")`。
- `scripts/build_report_data.py`：`--run-id`/`--latest`/`--only`；`resolve_run` 定位；`meta.save_profile != "full"` 时报错并提示重跑命令；失败 `sys.exit(1)`。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 真实数据跑通**

Run: `.venv\Scripts\python.exe scripts\build_report_data.py --only alignment`
Expected: `reports/derived/index.json` 中 `peak_lag == 0`、`run_id` 与 `reports/latest.json` 一致。

- [ ] **Step 6: 提交**

```bash
git add src/etf_rotation/report scripts/build_report_data.py tests/test_report_context.py tests/test_report_runner.py
git commit -m "feat(report): 派生数据骨架并绑定 run_id"
```

---

## Task 8: 水下曲线与回撤事件（N2）

**Files:**
- Create: `src/etf_rotation/report/steps/performance.py`
- Test: `tests/test_report_performance.py`

**Interfaces:**
- Produces: `underwater(nav) -> pd.Series`、`episodes(nav, min_depth=0.02) -> pd.DataFrame`（列 `peak_date, trough_date, recovery_date, recovered, depth, duration_days, recovery_days`）、`annual_table(equity) -> pd.DataFrame`、`monthly_table(returns) -> pd.DataFrame`、`longest_underwater(nav) -> dict`。
- `build` 输出 `{"underwater": series, "episodes": records, "annual": records, "monthly": records, "longest": {...}}`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_performance.py
import pandas as pd
from etf_rotation.report.steps import performance

def test_underwater_and_episode_bounds():
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    nav = pd.Series([1.0, 1.1, 0.9, 1.2, 1.0], index=idx)
    assert abs(performance.underwater(nav).loc[idx[2]] + 0.1818181818) < 1e-9
    row = performance.episodes(nav, min_depth=0.02).iloc[0]
    assert (row["peak_date"], row["trough_date"], row["recovery_date"]) == ("2024-01-02", "2024-01-03", "2024-01-04")
    assert row["recovered"] is True and row["duration_days"] == 1 and row["recovery_days"] == 1

def test_unrecovered_episode_has_null_recovery():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    ep = performance.episodes(pd.Series([1.0, 0.9, 0.8], index=idx))
    assert ep.iloc[0]["recovery_date"] is None and ep.iloc[0]["recovered"] is False
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

`underwater = nav / nav.cummax() - 1`；`episodes` 以「回到前高」为界切段，`duration_days = (trough − peak).days`，`recovery_days = (recovery − trough).days`，未恢复给 `None`。年度/月度表用净值与收益计算，年度换手取 `equity["turnover"].groupby(year).sum()`，年度费用取 `equity["fees"]` 同年求和。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add src/etf_rotation/report/steps/performance.py tests/test_report_performance.py
git commit -m "feat(report): 水下曲线与回撤事件"
```

---

## Task 9: 相对指标 + 剔除防守相关性（N3 + N9）

**Files:**
- Create: `src/etf_rotation/report/steps/relative.py`
- Test: `tests/test_report_relative.py`

**Interfaces:**
- Produces: `relative_summary(strategy, benchmark) -> dict`（`excess_cagr, excess_arith, tracking_error, information_ratio, beta, correlation, up_capture, down_capture, monthly_win_rate, n_months`）。
- Produces: `rolling_relative(strategy, benchmark, window=252) -> pd.DataFrame`（`excess, ir, beta, corr`）。
- Produces: `risk_sleeve_relative(equity_returns, weights, close, classification, benchmark) -> dict`（`corr_full, beta_full, corr_risk_sleeve, beta_risk_sleeve, beta_scaling, mean_risk_weight`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_relative.py
import numpy as np
import pandas as pd
import pytest
from etf_rotation.report.steps import relative

def test_relative_summary_on_known_series():
    idx = pd.date_range("2020-01-01", periods=600, freq="B")
    b = pd.Series(np.sin(np.arange(600)) * 0.01, index=idx)
    m = relative.relative_summary(0.5 * b + 0.001, b)
    assert m["beta"] == pytest.approx(0.5, abs=1e-12)
    assert m["correlation"] == pytest.approx(1.0, abs=1e-12)

def test_tracking_error_zero_for_constant_offset():
    idx = pd.date_range("2020-01-01", periods=600, freq="B")
    b = pd.Series(np.sin(np.arange(600)) * 0.01, index=idx)
    assert relative.relative_summary(b + 0.0001, b)["tracking_error"] == pytest.approx(0.0, abs=1e-12)

def test_rolling_relative_drops_warmup_instead_of_filling():
    idx = pd.date_range("2020-01-01", periods=300, freq="B")
    b = pd.Series(np.sin(np.arange(300)) * 0.01, index=idx)
    df = relative.rolling_relative(0.5 * b + 0.001, b, window=252)
    assert df["beta"].iloc[:251].isna().all() and df["beta"].iloc[251:].notna().all()

def test_beta_scaling_preserves_average_exposure():
    idx = pd.date_range("2020-01-01", periods=300, freq="B")
    b = pd.Series(np.sin(np.arange(300)) * 0.01, index=idx)
    weights = pd.DataFrame({"A": 0.5}, index=idx)      # 恒定 50% 风险仓
    close = pd.DataFrame({"A": 10 * (1 + b).cumprod()}, index=idx)
    out = relative.risk_sleeve_relative(b, weights, close, {"A": "risk"}, b)
    assert out["beta_risk_sleeve"] == pytest.approx(1.0, abs=1e-9)   # 按 mean_risk_weight 缩放
    assert out["beta_scaling"] == pytest.approx(0.5)
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

`relative_summary` 分母为 0 时返回 `None`，禁止 `inf`/`nan`。捕获率 `mean(r_s | r_b > 0) / mean(r_b | r_b > 0)`。
`risk_sleeve_relative`：`w_risk = weights` 把 `bond/money` 列置 0；`mean_risk_weight = w_risk.sum(axis=1).mean()`；`beta_scaling = mean_risk_weight`；`beta_risk_sleeve` 用 `w_risk / mean_risk_weight` 计算（平均暴露回到 1，与基准可比），`corr_risk_sleeve` 用归一化到 1 的权重（尺度无关）。三者都写进输出。
`build` 除 summary/rolling/annual_excess/ex_defensive 外，还要给 `lag_scan`（复用 `alignment.lag_correlation`）；**`lags/corrs` 序列化前按 lag 数值升序重排**，函数本身的 `|lag|` 索引只用于让 `idxmax` 在并列时命中 0。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 真实数据**

Run: `.venv\Scripts\python.exe scripts\build_report_data.py --only relative`
Expected: `corr_full ≈ 0.51`、`beta_full ≈ 0.31`、`information_ratio ≈ 0.15`、`corr_risk_sleeve > corr_full`。

- [ ] **Step 6: 提交**

```bash
git add src/etf_rotation/report/steps/relative.py tests/test_report_relative.py
git commit -m "feat(report): 相对基准指标与剔除防守相关性"
```

---

## Task 10: 调仓事件表（N4）

**Files:**
- Create: `src/etf_rotation/report/steps/events.py`
- Test: `tests/test_report_events.py`

**Interfaces:**
- Produces: `rebalance_events(diary, weights, returns) -> pd.DataFrame`（列 `date, types, regime, turnover, top_changes, triggers, fwd_5d, fwd_20d`）。
- Produces: `event_dates(diary, weights) -> pd.DatetimeIndex`（Task 14 复用，避免规则漂移）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_events.py
import pandas as pd
from etf_rotation.report.steps import events

def test_events_capture_switch_and_overheat():
    idx = pd.date_range("2024-01-01", periods=4, freq="B")
    diary = pd.DataFrame({"regime": ["bull"] * 4,
                          "hysteresis_held": [True, True, True, True],
                          "n_overheat_exits": [0, 0, 1, 0],
                          "vol_cap_scale": [1.0, 1.0, 1.0, 0.9],
                          "n_defensive": [2, 2, 2, 2]}, index=idx)
    # 01-02 持仓集合 {A,B} → 01-03 {B}（A 归零）= switch；01-04 仍 {B}
    weights = pd.DataFrame({"A": [0.6, 0.0, 0.0, 0.2], "B": [0.4, 1.0, 1.0, 0.8]}, index=idx)
    ev = events.rebalance_events(diary, weights, pd.Series(0.001, index=idx))
    assert {"switch", "overheat", "vol_cap"} <= set(ev["types"].explode())
    assert ev.loc[ev["date"] == "2024-01-03", "types"].iloc[0] == ["switch"]
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

判定：`switch` = **核心持仓变化**（在 `w ≥ 0.5%` 的标的里按权重取前 3 名，前 3 名集合与前一交易日不同；`hysteresis_held` 只作为触发快照保留在 `triggers` 里）。为什么不是全持仓集合：实测全集合变化有 935–1310 天（占 1838 天的 51%–71%），等于「每天都在换仓」；top-3 是 297 天，符合报告「核心持仓轮动」的语义。`n_overheat_exits > 0 → overheat`；`vol_cap_scale < 1 → vol_cap`；`n_defensive` 变化 → defensive；纳指/黄金权重变化 → cross_asset。`top_changes` 取 `|Δw|` 前 3；`turnover = Σ|Δw|/2`；`fwd_5d/fwd_20d = Π(1+r_{t+1..t+n}) − 1`，尾部不足给 `None`。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 真实数据**

Run: `.venv\Scripts\python.exe scripts\build_report_data.py --only events`
Expected: 事件数 300–800（若 `switch` 换成「持仓集合变化」后仍显著超出，把 `n_by_type` 分布贴回来，不要靠调阈值硬凑）；`overheat` 天数与 `diary.n_overheat_exits > 0` 的天数一致；同一持仓集合连续多日不重复计 switch。

- [ ] **Step 6: 提交**

```bash
git add src/etf_rotation/report/steps/events.py tests/test_report_events.py
git commit -m "feat(report): 调仓事件表与触发规则"
```

---

## Task 11: 成本拖累与盈亏平衡成本（N13）

**Files:**
- Create: `src/etf_rotation/report/steps/costs.py`
- Test: `tests/test_report_costs.py`

**Interfaces:**
- Produces: `annual_cost_drag(equity, trades) -> pd.DataFrame`（`year, fees, avg_nav, drag_pct, return_pct, cost_share_pct`）。
- Produces: `breakeven_bps(ann_return, ann_one_side_turnover, annual_drag) -> float`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_costs.py
import pandas as pd
import pytest
from etf_rotation.report.steps import costs

def test_breakeven_formula():
    assert costs.breakeven_bps(0.10, 12.5, 0.02) == pytest.approx(0.12 / (2 * 12.5) * 1e4, rel=1e-9)

def test_annual_drag_sums_daily_fee_flow():
    idx = pd.date_range("2024-01-01", "2024-12-31", freq="B")
    eq = pd.DataFrame({"nav": 1.0 + 0.0002 * range(len(idx)),
                       "fees": [0.001] * len(idx), "turnover": 0.05}, index=idx)
    out = costs.annual_cost_drag(eq, trades=None)
    assert out.iloc[0]["year"] == 2024
    assert out.iloc[0]["fees"] == pytest.approx(0.001 * len(idx))
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

`annual_cost_drag`：按年 `fees.sum()`；`avg_nav` 取当年 `nav` 均值；`drag_pct = fees / avg_nav`；`return_pct = nav_末/nav_初 − 1`；`cost_share_pct = fees / (return_pct × nav_初 + fees)`。
`ann_one_side_turnover` 的口径必须与 `equity["turnover"]` 一致。**对账对象是 `weights.diff().abs().sum(axis=1)/2`，不是 `trades.notional/(2×nav)`**：后者在单边成交日会系统性偏高（实测 +8.29%），因为 bt 的 turnover 是单边口径。`breakeven_bps = (ann_return + annual_drag) / (2 × ann_one_side_turnover) × 1e4`，输出 `assumptions`。
同时输出 `reconciliation`：`trades.cost.sum()` 与 `metrics.total_fees` 的差值与相对误差。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 真实数据**

Run: `.venv\Scripts\python.exe scripts\build_report_data.py --only costs`
Expected: 分年 drag 合计与 `total_fees` 同量级；平衡点落在 40–50bp；`reconciliation.relative_error < 0.005`。

- [ ] **Step 6: 提交**

```bash
git add src/etf_rotation/report/steps/costs.py tests/test_report_costs.py
git commit -m "feat(report): 分年成本拖累与盈亏平衡成本"
```

---

## Task 12: 目标 vs 实际 + 换手分解（N6 + N8）

**Files:**
- Create: `src/etf_rotation/report/steps/execution.py`
- Test: `tests/test_report_execution.py`

**Interfaces:**
- Produces: `target_vs_actual(weights, holdings) -> pd.DataFrame`（`date, mean_abs, max_abs`）。
- Produces: `turnover_split(diary, weights) -> pd.DataFrame`（按年：`switch, overheat, vol_cap, defensive, other, reconcile`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_execution.py
import pandas as pd
import pytest
from etf_rotation.report.steps import execution

def test_target_vs_actual_aligns_by_calendar_and_shifts_target():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    weights = pd.DataFrame({"A": [0.5, 0.5, 0.6], "B": [0.5, 0.5, 0.4]}, index=idx)
    holdings = pd.DataFrame({"A": [0.0, 0.5, 0.55], "B": [0.0, 0.5, 0.45]}, index=idx)
    out = execution.target_vs_actual(weights, holdings)
    assert out.loc[idx[1], "mean_abs"] == pytest.approx(0.0)
    assert out.loc[idx[2], "mean_abs"] == pytest.approx(0.05)

def test_turnover_split_sums_to_total():
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    weights = pd.DataFrame({"A": [0.5, 0.4, 0.3], "B": [0.5, 0.6, 0.7]}, index=idx)
    diary = pd.DataFrame({"hysteresis_held": [True, False, False],
                          "n_overheat_exits": [0, 0, 1], "vol_cap_scale": 1.0,
                          "n_defensive": 2}, index=idx)
    split = execution.turnover_split(diary, weights)
    assert split[["switch", "overheat", "vol_cap", "defensive", "other"]].sum().sum() == pytest.approx(0.2)
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

`target_eff = weights.shift(1).reindex(index=holdings.index, columns=holdings.columns).fillna(0)`；`mean_abs = |actual − target_eff|.sum(axis=1)/2`。
`turnover_split` 按日记主事件归因当日 `Σ|Δw|/2`（优先级：overheat → vol_cap → switch → defensive → other），按年汇总并给 `reconcile = 分量合计 − equity.turnover 年合计`。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 真实数据**

Run: `.venv\Scripts\python.exe scripts\build_report_data.py --only execution`
Expected: `mean_abs` 中位数 < 0.5%；最大值允许 > 10%，但必须能定位到停牌/跳空顺延（提交说明里给出最差 3 天的标的与原因）。

- [ ] **Step 6: 提交**

```bash
git add src/etf_rotation/report/steps/execution.py tests/test_report_execution.py
git commit -m "feat(report): 目标与实际持仓偏差及换手分解"
```

---

## Task 13: 单笔往返（N7）

**Files:**
- Create: `src/etf_rotation/report/steps/roundtrips.py`
- Test: `tests/test_report_roundtrips.py`

**Interfaces:**
- Produces: `match_round_trips(trades, signals) -> pd.DataFrame`（`ticker, entry_date, exit_date, quantity, entry_price, exit_price, pnl, holding_days, entry_status, exit_reason`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_roundtrips.py
import pandas as pd
import pytest
from etf_rotation.report.steps import roundtrips

def test_fifo_sell_consumes_multiple_lots():
    trades = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-05", "2024-01-10"]),
        "ticker": ["A"] * 3, "side": ["买入", "买入", "卖出"],
        "price": [10.0, 12.0, 11.0], "quantity": [1.0, 1.0, 1.5],
        "notional": [10.0, 12.0, 16.5], "cost": [0.001, 0.001, 0.0]})
    out = roundtrips.match_round_trips(trades, signals=None)
    assert len(out) == 2
    assert out.iloc[0]["quantity"] == pytest.approx(1.0)
    assert out.iloc[1]["quantity"] == pytest.approx(0.5)
    assert out.iloc[0]["pnl"] == pytest.approx(1.0 - 0.001, abs=1e-9)
    assert out.iloc[1]["pnl"] == pytest.approx(-0.5 - 0.0005, abs=1e-9)
    assert out.iloc[0]["holding_days"] == 9
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

买入入队（qty、price、date、cost 按 qty 摊）；卖出按 FIFO 消耗，跨批次生成多行，末批允许部分消耗并保留剩余。`pnl = qty × (sell − buy) − 分摊成本`；`holding_days = (exit − entry).days`；`entry_status` 查 `ticker_signals`；`exit_reason`：当日 `overheat_exit` → `overheat`，否则 `switch`，查不到 → `other`。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 真实数据**

Run: `.venv\Scripts\python.exe scripts\build_report_data.py --only roundtrips`
Expected: 往返数 10,000–25,000（FIFO 按批次展开；22,433 笔成交对应 20,722 笔往返属正常）；胜率 40–60%；`Σpnl + 未平仓成本` 与 `(nav_末 − 1)` 的差值可由现金利息解释（写入 `summary.residual`）。

- [ ] **Step 6: 提交**

```bash
git add src/etf_rotation/report/steps/roundtrips.py tests/test_report_roundtrips.py
git commit -m "feat(report): 单笔往返配对与已实现盈亏"
```

---

## Task 14: 决策阶段快照与归因（N5）

**Files:**
- Modify: `src/etf_rotation/pipeline.py:436-455`、`pipeline.py:606-641`
- Modify: `src/etf_rotation/evaluation/observability.py`
- Modify: `scripts/run_backtest.py`（传 `stages`）
- Create: `src/etf_rotation/report/steps/stages.py`
- Test: `tests/test_report_stages.py`、`tests/test_observability.py`

**Interfaces:**
- Produces: `pipeline._stage_snapshot(weights: dict[str, float]) -> dict[str, float]`（丢弃 0 与负值）。
- Produces: `trace["stages"]`，键固定 `candidate, overheat, cross_asset, defensive, phases, hysteresis, final`。
- Produces: `observability.build_stages(traces, days) -> pd.DataFrame`（列 `date, ticker, stage, weight`）。
- Produces: `observability.write(..., stages=None)` 写 `signals/stages.parquet`。
- Produces: `stages.stage_table(long, event_dates, top_n=10) -> dict`。
- Consumes: `events.event_dates`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_stages.py
import pandas as pd
import pytest
from etf_rotation import pipeline
from etf_rotation.evaluation import observability
from etf_rotation.report.steps import stages

def test_stage_snapshot_filters_zero():
    assert pipeline._stage_snapshot({"A": 0.3, "B": 0.0, "C": -0.1}) == {"A": 0.3}

def test_build_stages_long_format():
    days = pd.date_range("2024-01-01", periods=2, freq="B")
    traces = [{"stages": {"candidate": {"A": 0.6}, "final": {"A": 0.5}}},
              {"stages": {"candidate": {"A": 0.4}, "final": {"A": 0.4}}}]
    df = observability.build_stages(traces, days)
    assert set(df.columns) == {"date", "ticker", "stage", "weight"}
    assert len(df) == 4 and df.loc[df["date"] == days[0], "weight"].sum() == pytest.approx(1.1)

def test_stage_table_limits_to_top10():
    rows = [{"date": pd.Timestamp("2024-01-02"), "ticker": f"T{i:02d}", "stage": stg, "weight": w * (i + 1)}
            for i in range(12) for stg, w in [("candidate", 0.05), ("final", 0.04)]]
    out = stages.stage_table(pd.DataFrame(rows), [pd.Timestamp("2024-01-02")], top_n=10)
    assert out["stage_order"] == ["candidate", "overheat", "cross_asset", "defensive",
                                  "phases", "hysteresis", "final"]
    assert len(out["events"][0]["tickers"]) == 10
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

`_daily_target` 依次记录 `candidate`（`pre_overheat`）、`overheat`、`cross_asset`、`defensive`；`build_weights` 记录 `phases`、`hysteresis`、`final`；只在 `with_trace=True` 时写入。`observability.write` 增加可选 `stages` 参数。`run_backtest` 把 `build_stages(build.traces, build.days)` 放进 `frames["stages"]`（仅 full 档会写）。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 真实数据**

```powershell
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
.venv\Scripts\python.exe scripts\build_report_data.py --only stages
```
Expected: 每个事件 `Σfinal == diary.total_weight`；`Σphases ≥ Σfinal` 且 `Σhysteresis ≥ Σfinal`（这两步只减不加）。**不要断言 `Σcandidate ≥ Σfinal`**：`candidate` 是过热前的风险腿预算（中位数约 0.40），defensive 会把仓位补到约 1.0，差值是防守仓，不是漏算。

- [ ] **Step 6: 提交**

```bash
git add src/etf_rotation/pipeline.py src/etf_rotation/evaluation/observability.py scripts/run_backtest.py src/etf_rotation/report/steps/stages.py tests/test_report_stages.py tests/test_observability.py
git commit -m "feat(report): 决策阶段快照与事件瀑布归因"
```

---

## Task 15: 极端日（N12）

**Files:**
- Create: `src/etf_rotation/report/steps/extremes.py`
- Test: `tests/test_report_extremes.py`

**Interfaces:**
- Produces: `extreme_days(returns, weights, diary, close, classification, top_n=10) -> pd.DataFrame`（`date, return, regime, total_weight, class_contrib, residual`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_extremes.py
import numpy as np
import pandas as pd
import pytest
from etf_rotation.report.steps import extremes

def test_extreme_days_returns_both_tails():
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    r = pd.Series(np.linspace(-0.02, 0.02, 30), index=idx)
    r.iloc[0] = 0.0
    weights = pd.DataFrame({"A": 0.5, "B": 0.5}, index=idx)
    diary = pd.DataFrame({"regime": "range", "total_weight": 1.0}, index=idx)
    close = pd.DataFrame({"A": 10 * (1 + r).cumprod(), "B": 10 * (1 + r).cumprod()}, index=idx)
    out = extremes.extreme_days(r, weights, diary, close, {"A": "risk", "B": "risk"}, top_n=10)
    assert len(out) == 20
    assert out["return"].iloc[0] == pytest.approx(r.min())
    assert out["class_contrib"].iloc[0]["risk"] == pytest.approx(r.min(), abs=1e-9)
    assert abs(out["residual"].iloc[0]) < 1e-9
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

`class_contrib` 用 `w_{t−1} × r_t` 按类别汇总（复用 `attribution.asset_class_contributions` 的当日切片）；`residual = return − Σclass_contrib`（真实数据里是现金利息与执行偏差，不强行归零）；输出最差/最好各 `top_n`，按收益升序。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 真实数据**

Run: `.venv\Scripts\python.exe scripts\build_report_data.py --only extremes`
Expected: `|residual|` 中位数 < 20bp、最大 < 100bp（open 执行下隔夜跳空只能用前一日权重归因，天然带残差）；超出时在 `extremes.json` 写 warnings，不静默丢弃。

- [ ] **Step 6: 提交**

```bash
git add src/etf_rotation/report/steps/extremes.py tests/test_report_extremes.py
git commit -m "feat(report): 极端日与当日归因"
```

---

## Task 16: 滑点与容量（N10 + N11）

**Files:**
- Create: `src/etf_rotation/report/steps/liquidity.py`
- Test: `tests/test_report_liquidity.py`

**Interfaces:**
- Produces: `slippage(transactions, trades, close, opn) -> pd.DataFrame`（`date, ticker, side, price, close, opn, vs_close_bps, vs_open_bps`）。
- Produces: `capacity(weights, amount, capital=1e8, adv_window=20) -> pd.DataFrame`（`date, ticker, weight, adv20, days`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_liquidity.py
import pandas as pd
import pytest
from etf_rotation.report.steps import liquidity

def test_slippage_sign_is_side_adjusted():
    tx = pd.DataFrame({"Date": pd.to_datetime(["2024-01-02"]), "Security": ["A"],
                       "price": [10.1], "quantity": [100.0]})
    trades = pd.DataFrame({"date": pd.to_datetime(["2024-01-02"]), "ticker": ["A"],
                           "side": ["买入"]})
    close = pd.DataFrame({"A": [10.0]}, index=tx["Date"])
    opn = pd.DataFrame({"A": [10.0]}, index=tx["Date"])
    assert liquidity.slippage(tx, trades, close, opn).iloc[0]["vs_close_bps"] == pytest.approx(100.0)

def test_capacity_uses_cny_amount():
    idx = pd.date_range("2024-01-01", periods=25, freq="B")
    weights = pd.DataFrame({"A": [1.0] * 25}, index=idx)
    amount = pd.DataFrame({"A": [1e8] * 25}, index=idx)
    assert liquidity.capacity(weights, amount, capital=1e8).iloc[-1]["days"] == pytest.approx(1.0)
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

滑点：`vs_close_bps = sign × (price/close − 1) × 1e4`，买 `+1`、卖 `−1`，同时给 `vs_open_bps`。
容量：`value = weight × capital`；`adv20 = amount.rolling(20).mean()`；`days = value/adv20`；`build` 按年汇总 p50/p95/max 并给最差 20 个 `(date, ticker, days)`。`capital` 写入 `assumptions`。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 真实数据**

Run: `.venv\Scripts\python.exe scripts\build_report_data.py --only liquidity`
Expected: `vs_open_bps` 中位数 ≈ 0；`vs_close_bps` 中位数在 ±20bp 内；**整体**容量 p95 清仓天数 < 5 天；2019–2021 可能因小 ETF 流动性超过 5 天（2019 年 p95 87 天），按年给出并解释，不设统一上限。

- [ ] **Step 6: 提交**

```bash
git add src/etf_rotation/report/steps/liquidity.py tests/test_report_liquidity.py
git commit -m "feat(report): 成交滑点与容量估算"
```

---

# Stage C：信号缓存与网格

## Task 17: 信号缓存（signal_id + read-through）

**Files:**
- Create: `src/etf_rotation/signals/cache.py`
- Modify: `src/etf_rotation/pipeline.py::_precompute_signals`、`::signal_cache_key`
- Test: `tests/test_signal_cache.py`

**Interfaces:**
- Consumes: `cache.signal_id(params, data_snapshot_id)`（Task 2 已实现）。
- Produces: `cache.SIGNAL_KEYS`（tuple，信号参数白名单的唯一来源；`pipeline.signal_cache_key` 直接用它，不得复制第二份）。
- Produces: `cache.PANEL_FIELDS = ("m21", "m60", "vol60", "zbias", "llt80", "rev_active")`、`cache.SCALAR_FIELDS = ("comp", "nas_mom", "gold_mom", "nas_vol", "gold_vol", "cyb_vol", "cyb_below", "cyb_drop")`。
- Produces: `cache.save(panels: dict, scalars: pd.DataFrame, sid: str, root: Path, meta: dict) -> Path`、`cache.load(sid: str, root: Path, *, price_hash: str) -> dict | None`、`cache.cache_root() -> Path`。
- Produces: `_precompute_signals` 命中缓存时跳过 `momentum_panel`/`llt`，并补齐 `close/ret/n_days/avg20` 四个派生字段。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_signal_cache.py
import pandas as pd
from etf_rotation.signals import cache

def test_roundtrip_is_exact(tmp_path):
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    panel = pd.DataFrame({"A": [0.1, 0.2]}, index=idx, dtype="float32")
    scalars = pd.DataFrame({"comp": [0.3, 0.4]}, index=idx, dtype="float32")
    cache.save({"m21": panel}, scalars, "s1", tmp_path, {"fields": ["m21"]})
    got = cache.load("s1", tmp_path)
    pd.testing.assert_frame_equal(got["m21"], panel)
    pd.testing.assert_frame_equal(got["scalars"], scalars)

def test_load_returns_none_when_missing(tmp_path):
    assert cache.load("nope", tmp_path) is None
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

`save`：每个面板写 `{field}.parquet`（`float32`，`zstd`）；`scalars.parquet`；`manifest.json` 记 `fields, dtypes, tickers, date_min, date_max, bytes, created_at, code_hash, data_snapshot_id`（`code_hash` 复用 Task 2 的实现）。
`load`：`manifest.json` 不存在返回 `None`；存在则逐字段读回并校验 `tickers/date range` 与 manifest 一致，不一致抛 `RuntimeError`（缓存被手工改过）。
`_precompute_signals`：先算 `sid`，命中就直接返回缓存 dict + 补 `close/ret/n_days/avg20`；未命中则照旧计算，随后 `cache.save`（`ETF_SIGNAL_CACHE != "off"` 时）。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 真实数据测速**

```powershell
$env:ETF_SIGNAL_CACHE="off"; Measure-Command { .venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 }
Measure-Command { .venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 }
```
Expected: 第二次比第一次快 ≥ 4 分钟；两次 `equity.nav` 完全一致；`data/cache/signals/<sid>/` 只生成一个目录。

- [ ] **Step 6: 提交**

```bash
git add src/etf_rotation/signals/cache.py src/etf_rotation/pipeline.py tests/test_signal_cache.py
git commit -m "feat(signals): 信号面板内容寻址缓存"
```

---

## Task 18: families / trials 与累计 DSR

**Files:**
- Modify: `src/etf_rotation/evaluation/registry.py`
- Modify: `src/etf_rotation/evaluation/overfitting.py`
- Create: `tests/test_families.py`

**Interfaces:**
- Produces: `registry.family_id(kind, spec: dict, base_params: dict, start, end, execution, git_sha, data_snapshot_id, campaign_id: str = "") -> str`。
- Produces: `registry.write_family_member(root, fid, run_id, variant: dict, campaign_id: str = "", family: dict | None = None) -> None`（写 `families/{fid}/members/{run_id}.json`；`family={"kind":..., "spec":...}` 用于生成 `family.json`，不传则 `load_family` 的 `kind=None/spec={}`）。
- Produces: `registry.load_family(root, fid) -> dict`（`fid, kind, spec, members[], n_trials`）。
- Produces: `overfitting.campaign_trials(root, campaign_id) -> int`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_families.py
from etf_rotation.evaluation import registry, overfitting

def test_family_members_and_trial_count(tmp_path):
    fid = registry.family_id("grid", {"dedupe.corr_threshold": [0.8, 0.85]}, {}, "2024-01-01",
                             "2024-12-31", "open", "abc", "d1", "c1")
    for i in range(3):
        registry.write_family_member(tmp_path, fid, f"r{i}", {"p": i})
    fam = registry.load_family(tmp_path, fid)
    assert fam["n_trials"] == 3 and len(fam["members"]) == 3

def test_campaign_trials_sums_across_families(tmp_path):
    for f in ("f1", "f2"):
        for i in range(2):
            registry.write_family_member(tmp_path, f, f"{f}-r{i}", {}, campaign_id="c1")
    assert overfitting.campaign_trials(tmp_path, "c1") == 4
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

`write_family_member` 的 `campaign_id` 写入成员文件的 `campaign_id` 字段；写入前 `members/` 目录按需创建；`load_family` 用 glob 收集并补 `n_trials`；`campaign_trials` 统计同 `campaign_id` 的成员文件数。**`n_trials` 按去重后的 run 计**（同一配置被多个维度重复选中算一次），逐点明细由 `sweep` 的 `trials` 保留。`family_id` 不含 `dirty_hash`，所以只有干净工作区生成的 family 才能作为证据（C3 在 main 干净状态下跑）；脏工作区的 family 只用于冒烟。
`overfitting.deflated_sharpe(sharpes, n_trials, n_obs)` 签名不变，新增调用方式在 Task 19。

- [ ] **Step 4: 跑测试确认通过** → PASS

- [ ] **Step 5: 提交**

```bash
git add src/etf_rotation/evaluation/registry.py src/etf_rotation/evaluation/overfitting.py tests/test_families.py
git commit -m "feat(registry): family/trial 登记与累计试验数"
```

---

## Task 19: 网格脚本统一到 store_run

**Files:**
- Create: `src/etf_rotation/evaluation/sweep.py`
- Modify: `scripts/run_grid.py`、`run_grid_hydra.py`、`run_heatmap.py`、`run_sensitivity.py`、`run_assumption_sensitivity.py`、`run_mechanism_ablation.py`、`run_oos_check.py`
- Create: `scripts/collect_runs.py`
- Test: `tests/test_sweep.py`

**Interfaces:**
- Produces: `sweep.iter_points(grid: dict) -> Iterator[dict]`（笛卡尔积，按 key 排序保证稳定）。
- Produces: `sweep.run_sweep(*, points, run_one, kind, profile, campaign_id, tag, runs_root, families_root, git_sha, data_snapshot_id, start, end, execution) -> dict`：每个点算 `run_id` → `run_one(params)` 返回 `(meta, metrics, frames)` → `store_run` → `write_family_member`；返回 `{"family_id", "n_trials", "run_ids"}`。
- Produces: `collect_runs.family_summary(families_root, runs_root, fid) -> dict`（读成员 + metrics，算 robustness/cliffs/DSR，写 `families/{fid}/summary.json`）；CLI 支持 `--family`、`--campaign`。
- Produces: 所有脚本支持 `--save-profile`、`--campaign`、`--tag`；`run_grid.py` 输出 `families/{fid}/summary.json`；`heatmap` 额外写 `families/{fid}/results.json`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sweep.py
from etf_rotation.evaluation import sweep

def test_run_sweep_writes_runs_and_family(tmp_path):
    points = [{"p": 1}, {"p": 2}]
    def run_one(point):
        return ({"schema_version": 2, "created_at": "2026-10-24T00:00:00Z", "n_obs": 10},
                {"sharpe": float(point["p"])}, {})
    runs_root, fam_root = tmp_path / "runs", tmp_path / "families"
    out = sweep.run_sweep(points=points, run_one=run_one, kind="grid",
                          profile="minimal", campaign_id="c1", tag="t",
                          runs_root=runs_root, families_root=fam_root,
                          git_sha="abc", data_snapshot_id="d1",
                          start="2024-01-01", end="2024-12-31", execution="open")
    assert out["n_trials"] == 2
    assert len(out["run_ids"]) == 2
    from etf_rotation.evaluation import registry
    fam = registry.load_family(fam_root, out["family_id"])
    assert fam["n_trials"] == 2

def test_family_id_is_order_independent():
    a = sweep.iter_points({"x": [1, 2], "y": [3, 4]})
    b = sweep.iter_points({"y": [3, 4], "x": [1, 2]})
    assert list(a) == list(b)
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现 `sweep.py` 与 `collect_runs.py`**

`run_sweep` 内部按 §1.1 计算 `family_id`（`spec` 传原始 grid），逐点 `params` 覆写后调用注入的 `run_one`；`run_one` 负责 build/backtest 并返回三件套；`sweep` 负责身份、存盘、登记成员，并在 `meta` 里注入 `kind/family_id/campaign_id/save_profile`（覆盖 `run_one` 返回的同名键）。测试用注入函数，不跑真实回测。

- [ ] **Step 4: 改造脚本**

- `run_grid.py`：`run_one` = 建权 → 回测 → 指标 → frames；每个点 `kind="grid"`；循环后 `collect_runs.family_summary` 写 summary；`grid.json` 改为从 summary 复制的兼容镜像（标注 `generated`）。
- `run_grid_hydra.py`：`family_id` 由 cfg 的 `param_key/values/start/end/execution` 确定性算出；worker 只 `store_run` + 写成员，不写 summary；`register_run` 的旧调用删除。
- `run_heatmap.py`：逐点 `store_run`；`results.json` 写进 family 目录；HTML 仍写 `reports/heatmap_<x>_<y>.html`。
- 其余四个脚本：`run_one` 包一层 `store_run`，`kind` 分别为 `cost/assumption/ablation/oos`；`oos_check` 每个子区间一个 run。

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests/test_sweep.py tests/test_families.py -q` → PASS

- [ ] **Step 6: 小规模真实验证**

```powershell
.venv\Scripts\python.exe scripts\run_grid.py --grid defensive.max_vol_60d=0.03,0.04 --save-profile minimal --campaign demo
.venv\Scripts\python.exe scripts\collect_runs.py --family <上一步打印的 family_id>
```
Expected: 2 个 run 目录；`families/<fid>/summary.json` 的 `n_trials == 2`；`reports/latest.json` 未被网格覆盖（网格不写 latest）。

- [ ] **Step 7: 提交**

```bash
git add src/etf_rotation/evaluation/sweep.py scripts/run_grid.py scripts/run_grid_hydra.py scripts/run_heatmap.py scripts/run_sensitivity.py scripts/run_assumption_sensitivity.py scripts/run_mechanism_ablation.py scripts/run_oos_check.py scripts/collect_runs.py tests/test_sweep.py
git commit -m "feat(grid): 网格脚本统一按 run 落盘并登记 family"
```

---

## Task 20a: 重跑调参与稳健性扫描（产物流水线，在 main 检出执行）

**Files:**
- Modify: `reports/调参记录.md`、`reports/index.md`
- No code.

**Interfaces:**
- Consumes: `run_grid.py`、`run_assumption_sensitivity.py`、`run_mechanism_ablation.py`、`run_oos_check.py`、`run_sensitivity.py`、`collect_runs.py`。
- **执行位置：主检出（main），不在 worktree**。这些脚本的产物在 `reports/runs/`、`reports/families/`，被 `.gitignore` 排除，worktree 里跑完无法随分支合并回来。

- [ ] **Step 1: 重跑 8 个单参数维度**

```powershell
$env:PYTHONIOENCODING="utf-8"
$dims = @(
 "dedupe.corr_threshold=0.75,0.80,0.85",
 "trend.windows=[15,60],[21,60],[30,90]",
 "dedupe.max_holdings=5,8,10",
 "market_state.bull_threshold=0.15,0.20,0.25",
 "market_state.alpha=0.05,0.10,0.15",
 "risk.vol_target_risk=0.15,0.20,0.25",
 "defensive.top_n=1,2,3",
 "defensive.max_vol_60d=0.02,0.03,0.04")
foreach ($d in $dims) { .venv\Scripts\python.exe scripts\run_grid.py --grid $d --campaign tuning-2026-10 --save-profile standard }
```

- [ ] **Step 2: 重跑消融、假设、OOS、成本**

```powershell
.venv\Scripts\python.exe scripts\run_mechanism_ablation.py --campaign tuning-2026-10 --save-profile standard
.venv\Scripts\python.exe scripts\run_assumption_sensitivity.py --campaign tuning-2026-10 --save-profile standard
.venv\Scripts\python.exe scripts\run_oos_check.py --campaign tuning-2026-10 --save-profile standard
.venv\Scripts\python.exe scripts\run_sensitivity.py --campaign tuning-2026-10 --save-profile minimal
```

- [ ] **Step 3: 用累计试验数重算 DSR**

Run: `.venv\Scripts\python.exe scripts\collect_runs.py --campaign tuning-2026-10`
Expected: `reports/index.md` 列出所有 family 与总试验数（约 40）；每个 family 的 `summary.json` 同时给 `dsr_family` 与 `dsr_campaign`，并注明后者是结论口径。

- [ ] **Step 4: 更新 `reports/调参记录.md`**

每个维度表格增加 `run_id` 列；DSR 数字更新，旧值标注「v1.1.1，已废弃（无 run_id）」；`选参建议` 一节写明依据的 campaign 与 `family_id`。

- [ ] **Step 5: 验证**

Run: `.venv\Scripts\python.exe scripts\collect_runs.py --campaign tuning-2026-10`
Expected: 每个成员 run 在 `reports/runs/` 下都有目录与 `meta.parquet`；缺目录的成员被列在输出末尾（哈希级校验在 Task 21 落地）。

- [ ] **Step 6: 提交**

```bash
git add reports/调参记录.md reports/index.md
git commit -m "docs: 在新登记体系下重跑调参与稳健性扫描"
```

---

## Task 20b: 重建基线并重算派生数据（产物流水线，在 main 检出执行）

**Files:**
- Modify: `reports/回测报告.md`
- No code.

**Interfaces:**
- Consumes: `run_backtest.py --save-profile full`、`build_report_data.py`、`run_report.py`、`collect_runs.py`。
- **执行位置：主检出（main）**，理由同 Task 20a：`reports/runs/`、`reports/derived/` 不入 git。

- [ ] **Step 1: 重建基线（含 stages）**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
```
Expected: 新 `run_id`；`meta.save_profile == "full"`；`signals/stages.parquet` 存在。

- [ ] **Step 2: 重算 10 个派生 JSON**

Run: `.venv\Scripts\python.exe scripts\build_report_data.py --latest`
Expected: `derived/index.json` 的 10 个 step 全部 `ok`；`run_id` 与 `latest.json` 一致；`alignment.peak_lag == 0`。

- [ ] **Step 3: 重生成可视化报告**

Run: `.venv\Scripts\python.exe scripts\run_report.py`
Expected: `可视化报告.html` 更新；`回测报告.md` 的自动段落带新 `run_id`。

- [ ] **Step 4: 更新 `reports/回测报告.md` 手写部分**

基线数字旁标注 `run_id`；「已知差异」一节补一句「基准口径改为同日收益，benchmark/hs300 数值与 v1.1.1 不同，策略净值不变」。

- [ ] **Step 5: 验证**

Run: `.venv\Scripts\python.exe scripts\verify_artifacts.py`
Expected: 无输出（Task 21 引入；若尚未合并则跳过，由 Task 21 补跑）。
Run: `.venv\Scripts\python.exe -c "import pandas as pd; a=pd.read_csv('reports/legacy/v1.1.1/equity.csv',parse_dates=['ts']).set_index('ts'); b=pd.read_csv('reports/equity.csv',parse_dates=['ts']).set_index('ts'); print((a['nav']-b['nav']).abs().max())"`
Expected: `0.0`（N1 只改基准，不改净值）。

- [ ] **Step 6: 提交**

```bash
git add reports/回测报告.md
git commit -m "docs: 基线重建并接入派生数据"
```

---

# Stage D：收口

## Task 21: 下游 `--run-id`、校验与清理

**Files:**
- Modify: `scripts/run_attribution.py`、`run_exposure.py`、`run_report.py`
- Create: `src/etf_rotation/evaluation/verify.py`、`src/etf_rotation/evaluation/prune.py`
- Create: `scripts/verify_artifacts.py`、`scripts/prune_runs.py`（薄 CLI）
- Test: `tests/test_verify_artifacts.py`

**Interfaces:**
- Produces: `verify.verify(root: Path, run_id: str | None = None) -> list[str]`，返回问题列表；空列表表示通过。
- Produces: `prune.prune(root: Path, *, keep_profiles=("full",), older_than_days=90, dry_run=True) -> list[str]`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_verify_artifacts.py
import pandas as pd
import pytest

def test_verify_detects_tampering(tmp_path):
    from etf_rotation.evaluation import artifacts, verify
    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    p = artifacts.store_run(root=tmp_path, run_id="r1", kind="backtest", profile="standard",
                            meta={"schema_version": 2, "created_at": "x"},
                            metrics={"sharpe": 1.0},
                            frames={"equity": pd.DataFrame({"nav": [1.0, 1.01]}, index=idx),
                                    "weights": pd.DataFrame({"A": [1.0, 1.0]}, index=idx)})
    assert verify.verify(tmp_path, "r1") == []
    (p / "equity.parquet").write_bytes(b"broken")
    assert any("equity" in msg for msg in verify.verify(tmp_path, "r1"))
```

- [ ] **Step 2: 跑测试确认失败** → FAIL

- [ ] **Step 3: 实现**

`verify`：比对 `artifacts.parquet` 的 sha256；交叉检查 `metrics.parquet` 的 `sharpe/ann_return` 与 `equity` 重算值（用 ffn）；`total_fees` 与 `trades.cost.sum()` 相对误差 < 0.5%；`derived` 存在时检查 `index.json.inputs` 的哈希与当前产物一致。
`prune`：只删 `standard` 档的 `equity/holdings` 与 `full` 档的 `transactions/trades/signals`，保留 `meta/metrics/manifest`，并在 `meta` 里追加 `pruned=TRUE`（重写 meta.parquet 单行，属可控覆盖）。

- [ ] **Step 4: 改造下游脚本**

`run_attribution.py`/`run_exposure.py`/`run_report.py`：用 `artifacts.resolve_run(ROOT/"reports", args.run_id)` 取目录，读 `equity.parquet`/`weights.parquet`；输出写到该 run 目录的 `analysis/` 子目录，并镜像到顶层（保持现有报告链接有效）。

- [ ] **Step 5: 跑测试确认通过** → PASS

- [ ] **Step 6: 全量回归**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
.venv\Scripts\python.exe scripts\build_report_data.py --latest
.venv\Scripts\python.exe scripts\run_report.py
.venv\Scripts\python.exe scripts\verify_artifacts.py
```
Expected: 测试全 PASS；`build_report_data.py` 10 个 step 全 `ok`；`verify_artifacts` 无输出；`回测报告.md` 的自动段落已更新。

- [ ] **Step 7: 提交**

```bash
git add scripts src/etf_rotation/evaluation tests/test_verify_artifacts.py
git commit -m "feat: 下游按 run_id 分析并补齐产物校验与清理"
```

---

## Task 22: 文档收口

**Files:**
- Modify: `TODO.md`、`CHANGELOG.md`、`README.md`、`AGENTS.md`、`docs/代码审阅手册.md`
- Modify: `docs/superpowers/specs/2026-10-24-etf-rotation-report-content-spec.md` §3.2

- [ ] **Step 1: 文档更新**

- `AGENTS.md`「数据与已知差异」：补「回测产物按 `reports/runs/{run_id}/` 保存，档位 `--save-profile` 默认 standard，报告需 full；`reports/latest.json` 指向最新 run」。
- `docs/代码审阅手册.md`：把 `reports/signals/*` 的说明改成 run 目录；补 `store_run`/`signal_id`/`family_id` 三个概念。
- `CHANGELOG.md`：一条 `feat(registry)` + 一条 `feat(report)`；注明「基准口径修正，benchmark/hs300 数值与 v1.1.1 不同，策略净值不变」。
- `TODO.md`：勾掉「指标未落盘」「data_snapshot_id 与 warehouse 不一致」两条；新增「`env_lock_hash` 已填充」「派生数据管线已落地，前端渲染待下一阶段」。
- spec §3.2：N1–N13 每行补「输出：`derived/xxx.json`」。

- [ ] **Step 2: 验证**

Run: `.venv\Scripts\python.exe scripts\verify_artifacts.py`
Expected: 无输出。
Run: `git status --porcelain`
Expected: 只有文档改动。

- [ ] **Step 3: 提交**

```bash
git add TODO.md CHANGELOG.md README.md AGENTS.md docs/
git commit -m "docs: 收口持久化与报告派生数据管线"
```

---

## Task 23: 清理旧登记与旧 run（门禁：Task 20b 通过）

**Files:**
- Modify: `reports/legacy/README.md`（记录清理日期与旧 run_id 清单）
- Delete: `reports/runs/` 下**没有 `meta.parquet`** 的目录、`warehouse.duckdb` 的 `runs`/`run_metrics`
- No code.

**门禁（三条全满足才执行）：**
1. Task 20b 的 `run_backtest --save-profile full` 成功，`reports/latest.json` 指向新 `run_id`；
2. `scripts/verify_artifacts.py` 对全部新 run 无输出；
3. `reports/runs/` 里新 run 的数量 ≥ 1，且每个都有 `meta.parquet`。

- [ ] **Step 1: 确认门禁**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\verify_artifacts.py
.venv\Scripts\python.exe -c "import json;print(json.load(open('reports/latest.json',encoding='utf-8')))"
```

Expected: verify 无输出；latest 指向的目录存在且含 `meta.parquet`。

- [ ] **Step 2: 记录旧 run 清单**

```powershell
$old = Get-ChildItem reports\runs -Directory | Where-Object { $_.Name -ne '.staging' -and -not (Test-Path (Join-Path $_.FullName 'meta.parquet')) }
$old | Select-Object -ExpandProperty Name | Set-Content reports\legacy\old-runs.txt
$old.Count
```

Expected: `40`。

- [ ] **Step 3: 只删旧目录（不要整目录删）**

```powershell
$old | ForEach-Object { Remove-Item -Recurse -Force $_.FullName }
.venv\Scripts\python.exe -c "import duckdb; c=duckdb.connect('data/warehouse.duckdb'); c.execute('DROP TABLE IF EXISTS run_metrics'); c.execute('DROP TABLE IF EXISTS runs'); c.close()"
```

- [ ] **Step 4: 验证**

```powershell
(Get-ChildItem reports\runs -Directory | Where-Object { $_.Name -ne '.staging' }).Count
.venv\Scripts\python.exe -c "from pathlib import Path; from etf_rotation.evaluation import registry; print(len(registry.load_runs(Path('reports/runs'))))"
.venv\Scripts\python.exe -c "import duckdb;print([r[0] for r in duckdb.connect('data/warehouse.duckdb').execute('show tables').fetchall()])"
```

Expected: 目录数 = 新 run 数；`load_runs` 数量一致；表列表中不再有 `runs`/`run_metrics`。

- [ ] **Step 5: 更新 README 并提交**

`reports/legacy/README.md` 追加一行：`YYYY-MM-DD 清理旧 run 与 registry 表，清单见 old-runs.txt`。

```bash
git add reports/legacy/README.md reports/legacy/old-runs.txt
git commit -m "chore: 新登记体系验证通过后清理旧 run"
```

---

## 6. 并行执行编排（由编排会话用 OpenChamber 创建与管理）

### 6.1 会话模型与上限

- 编排方式：**编排会话（本会话）不写代码**，只做「Task 1 → 建 worktree → 派发 → 合并 → 检查点验证」。每个工作流一个子会话，绑定独立 worktree 与分支；子会话不 merge、不 rebase 到 main、不改别人的文件。
- **并发上限 4**。理由：① 共用文件只有 4 个，4 路以上合并面扩大而收益递减；② 每路 stage ≤3 个任务，reviewer 能在单次上下文里审完；③ 每个真实回测进程约占 1–2GB，4 路以上内存与信号预计算会互相拖慢。
- 波次内不满 4 路时不强行凑数：依赖决定并行度，不是并发数决定依赖。

### 6.2 工作流与分支

| 工作流 | 任务 | 分支 / worktree | 执行位置 | 前置 |
|---|---|---|---|---|
| S0a 身份与写盘 | 2–5 | `feat/persist-s0a-store` / `persist-s0a` | worktree | Task 1（编排者执行） |
| S0b 基准对齐 | 6 | `feat/persist-s0b-benchmark` / `persist-s0b` | worktree | Task 1 + legacy 副本 |
| S1 报告骨架 | 7–9 | `feat/persist-s1-report-core` / `persist-s1` | worktree | S0a 合并 |
| C1 信号与 family | 17–18 | `feat/persist-c1-signal-family` / `persist-c1` | worktree | S0a 合并 |
| S2a 事件与执行 | 10、12、15 | `feat/persist-s2a-events-exec` / `persist-s2a` | worktree | S1 合并 |
| S2b 成本与往返 | 11、13、16 | `feat/persist-s2b-costs-trips` / `persist-s2b` | worktree | S1 合并 |
| C2 网格统一 | 19 | `feat/persist-c2-grid` / `persist-c2` | worktree | C1 合并 |
| D1 校验与下游 | 21 | `feat/persist-d1-d2` / `persist-d1` | worktree | S1 合并（需要 `derived/index.json`） |
| S3 阶段归因 | 14 | `feat/persist-s3-stages` / `persist-s3` | worktree | S2a 合并 + C1 合并 |
| C3 重跑与基线 | 20a、20b | 无 worktree | **main 检出** | S3 + C2 合并 |
| D2 文档收口 | 22 | `feat/persist-d1-d2` / `persist-d1` | worktree | C3 完成 |
| X 清理旧数据 | 23 | 无 worktree | **main 检出** | C3 + D2 完成、verify 通过 |

### 6.3 波次

| 波次 | 并发 | 内容 |
|---|---|---|
| W0 | 编排者 + 2 | 编排者在 main 执行 Task 1 并提交；随后 S0a ∥ S0b |
| W1 | 2 | S1 ∥ C1 |
| W2 | 4 | S2a ∥ S2b ∥ C2 ∥ D1 |
| W3 | 1 | S3（等 S2a、C1 都在 main 上） |
| W4 | 1 | C3 在 main 跑 20a → 20b |
| W5 | 1 | D2 文档 |
| W6 | 1 | X：Task 23 清理旧 run 与 registry（门禁通过后） |

关键路径：S0a → C1 → C2 → C3。缩短它才有意义；S1/S2 的 9 个 step 不是瓶颈，所以不再拆。

### 6.4 共用文件与合并顺序

| 文件 | 被谁改 | 合并顺序 |
|---|---|---|
| `pipeline.py` | S0b（compute_benchmark）、C1（_precompute_signals）、S3（stage 快照） | S0b → C1 → S3 |
| `run_backtest.py` | S0a（Task 5）、S3（Task 14） | S0a → S3 |
| `registry.py` | S0a（重写）、C1（追加 family 函数） | S0a → C1 |
| `run_report.py` | S0a（改读镜像）、D1（加 `--run-id`） | S0a → D1 |
| `metrics.py` | S0a | — |
| `report/*` | S1 建骨架，S2a/S2b/S3 各加自己的 step 文件 | S1 先合并，其余无交集 |
| `scripts/*` | S0a（run_backtest/run_report）、S1（build_report_data）、C2（7 个网格脚本）、D1（4 个下游脚本） | S0a → S1 → C2 → D1 |

合并由编排者执行，顺序按上表；出现冲突一律保留 main 侧的契约（函数签名、meta 字段、目录布局），再补分支侧的新增内容。

### 6.5 worktree 环境

每个 worktree 里先执行：

```powershell
. D:\project\quant_1\scripts\activate_data.ps1
& $env:PY -m pytest tests -q
```

- `reports/` 在 worktree 内独立，`latest.json`、顶层镜像、`runs/` 不会跨会话互相覆盖。`activate_data.ps1` 会把主仓库的 `reports/legacy/v1.1.1/` 拷进来，供数值对照。
- `activate_data.ps1` 会设 `PYTHONPATH=<当前 worktree>\src`：venv 是 editable 安装、默认指向主仓库，不设这项会让 worktree 里的测试**静默跑主仓库代码**。
- `data/` 通过 `ETF_*` 环境变量指向主仓库；**只读使用**，不要在主仓库的 `data/` 里手工删改。
- `data/cache/signals/` 是跨 worktree 共享的：写入已按 §1.6 要求做成 `tmp-{pid}` + rename，子会话**不要**手工清理该目录。
- `scripts/activate_data.ps1` 必须保持 **ASCII 注释**：PowerShell 5.1 把无 BOM 的 `.ps1` 当 ANSI 读，中文注释末尾的多字节字符会吞掉换行，把下一行代码并进注释。
- worktree 只 checkout 已提交内容：**编排者必须先提交计划文档与 `docs/superpowers/plans/stages/`，再创建 worktree**。

### 6.6 产物归属

- **代码与测试**：在 worktree 里写、在分支上提交、由编排者合并。
- **回测产物**（`reports/runs/`、`reports/families/`、`reports/derived/`、`reports/latest.json`）：全部被 `.gitignore` 排除，**只能出现在 main 检出**。因此：
  - 各 stage 的真实数据验证在自己 worktree 内跑一次即可（约 6 分钟，产物不留），结论写进提交说明；
  - Task 20a/20b 是产物流水线，必须在 main 检出执行，否则合并后 run 目录不存在，`run_id` 会指向不存在的产物；
  - Task 21 的 `verify_artifacts.py` 真实校验也只在 main 上跑。
- 子会话**不要**在验证后提交 `reports/` 下任何文件（除 `reports/调参记录.md`、`reports/回测报告.md` 这类手写 markdown）。

### 6.7 派发模板

每个子会话的 prompt 固定为：

```
你在 worktree <绝对路径>，分支 <branch>。
读两份文档：
1. docs/superpowers/plans/2026-10-24-etf-rotation-persistence-and-report-data.md
   （只读 Global Constraints、Review Focus §3、你的 Task 编号）
2. docs/superpowers/plans/stages/<stage 文件>.md

纪律：
- 只改该 stage 文件“独占文件”列出的路径；需要别处的改动就停下来说明。
- 按任务内 Step 顺序做 TDD：先写失败测试 → 跑失败 → 实现 → 跑通过 → 提交。
- 一个 Task 一个 commit，message 用计划里给的。
- 不 merge、不 rebase 到 main、不 push、不改 main 上的数据。
- 验证命令先 `. D:\project\quant_1\scripts\activate_data.ps1`，再用 `& $env:PY ...`（`$PY` 不是可执行变量，必须加 `&`）。
- 结束回复只给：完成的任务号、每个 commit 的 hash、验收命令的实际输出、未解决项。
```

### 6.8 编排者职责与检查点

1. **W0 前**：执行 Task 1（清场、归档、`activate_data.ps1`），提交计划与 stages 文档，确认 `git status` 干净。
2. **每个波次开始**：按 §6.4 的合并顺序把上一波分支合进 main，跑一次 `pytest tests -q`（快速回归），再创建下一波 worktree 与会话。
3. **每个波次结束**：检查子会话回复里的验收输出；不一致就让它继续，不要自己改它的代码。
4. **C3 前后**：C3 在 main 上跑，编排者负责在 20a 与 20b 之间确认 `verify_artifacts` 可用（Task 21 已合并）。
5. **收口**：D2 合并后跑 §7 全部验收项；任何一项失败都回到对应工作流修，而不是在 main 上直接改。
6. **最后**：§7 全绿后才执行 Task 23 清理旧 run 与 registry；清理前后各跑一次 `load_runs` 数量对照。

### 6.9 失败与重试

- 子会话说“契约不足/需要改共用文件” → 编排者裁决：补进主计划再派发，禁止子会话自行扩权。
- 测试失败但产物合理 → 让子会话按 systematic-debugging 找根因，不合并。
- 同一任务两次失败 → 编排者接管该任务，或换更细的任务拆分；不叠加第三次重试。
- 合并冲突 → 保留 main 侧契约（§6.4），把冲突点记录到 `reports/调参记录.md` 的「工程备注」一节，避免其他会话重复踩。

## 7. 验收清单

- [ ] 同 commit、同参数、同数据跑两次 → `run_id` 相同、产物 sha256 相同（`created_at` 除外）。
- [ ] 只改 `costs.one_side_bps` → `run_id` 变、`signal_id` 不变、信号缓存命中。
- [ ] Hydra 3 个变体并行 → 无锁错误、无产物覆盖、3 个 run + 1 个 family。
- [ ] `reports/runs/{id}/` 自洽：`verify_artifacts` 无输出。
- [ ] `build_report_data.py --run-id <旧 run>` 能对历史 run 重建 10 个 JSON，且 `index.json.run_id` 正确。
- [ ] `derived/performance.json` 的 `max_drawdown` 与 `meta`/`metrics` 一致。
- [ ] `derived/alignment.json.peak_lag == 0`。
- [ ] 网格 family 的 `summary.json` 同时给 `dsr_family` 与 `dsr_campaign`，后者用累计试验数。
- [ ] `reports/latest.json` 只被基准回测更新，网格不覆盖。
- [ ] `reports/legacy/v1.1.1/equity.csv` 与当前 `nav` 完全一致（N1 只改基准）。
- [ ] 每个波次合并后 main 上 `pytest tests -q` 全绿，且 `git status --porcelain` 不含 `reports/runs/`（产物从未被提交）。
- [ ] `reports/runs/` 里的每个 `run_id` 都由 **main 检出**产生（C3 之后 `verify_artifacts` 能全部找到目录）。
- [ ] 合并顺序符合 §6.4；`pipeline.py` 的最终版本同时含 `compute_benchmark` 修复、信号缓存读取、`trace["stages"]`。
- [ ] Task 23 清理后：`reports/runs/` 只剩新 run，`registry.load_runs` 数量与清理前一致，`warehouse.duckdb` 不再有 `runs`/`run_metrics`。

## 8. 自检记录

- **Spec 覆盖**：N1→Task 6、N2→8、N3→9、N4→10、N5→14、N6→12、N7→13、N8→12、N9→9、N10→16、N11→16、N12→15、N13→11。
- **持久化缺口覆盖**：全量信号→Task 17；日度 turnover/fees→Task 5；全量 stats→Task 5；历史产物覆盖→Task 4/5/19；DSR 少算→Task 18/20a；基准错位→Task 6。
- **并行编排覆盖**：worktree 环境→§6.5；产物归属→§6.6；共用文件合并顺序→§6.4；失败处理→§6.9。
- **类型一致性**：`store_run` 的 `frames` 键、`ReportContext` 字段、`index.json` 字段在各任务间一致；`event_dates` 在 Task 10 产出、Task 14 消费。
- **已知取舍**：`stages` 只在 full 档；网格默认 standard 不存逐笔交易（可由 transactions + weights 重算）；信号缓存不含 `close/ret/n_days/avg20`（声明为派生）。
