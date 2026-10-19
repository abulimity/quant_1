# 下阶段实施计划：工程化基础设施 + 前置决策 + 可观测化 + 差距归因 + 收尾

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立轻量但专业的实验基础设施（参数/假设/信号/结果可版本化、唯一对应），补齐「信号 → 决策 → 交易」可观测性，并在此基础上系统归因并尽量逼近与研报的约 6 个点差距；同时落地两项前置决策与 TODO.md 全部收尾。

**Architecture:** 保持「pandas 预计算信号 → 目标权重面板 → bt 记账」整体架构与 bt 引擎不变。分五部分顺序推进：① 工程化基础设施（修 registry 到 ml4t 标准、参数 schema、H1–H10 参数化、Hydra 网格、数据快照哈希，均不改数值）；② 前置决策（默认执行 open、候选参数写回，改变数值并重立基线）；③ 可观测化（决策轨迹采集 + 落盘 + 报告，不改数值）；④ 差距归因与假设/机制敏感性（资产类别/区间归因、机制开关、H1–H10 网格、集中度、数据质量复核）；⑤ 阶段三/四收尾。②③⑤相对②之后的新基线 `IDENTICAL`。

**Tech Stack:** Python 3.10 / pandas 2.3 / numpy 2.2 / bt 1.2.2 / plotly 7.1 / pytest / Hydra / duckdb。

**Spec:**
- `docs/superpowers/specs/2026-10-10-etf-rotation-design.md`（策略机制与 H1–H10）
- `docs/superpowers/specs/2026-10-19-etf-rotation-attribution-and-infra-design.md`（本计划的上游设计）
- `docs/superpowers/plans/2026-10-18-etf-rotation-observability.md`（Part 3 可观测化的数据模型与图接口）
- `TODO.md`（阶段三 3.1–3.9、阶段四 4.1–4.4；3.2 并入 Task 9）
- `AGENTS.md`（ml4t 适用性清单、`.shift(1)` 纪律、一次只动一个维度、`IDENTICAL` 回归）

## Global Constraints

- 所有 Python 统一用 `.venv\Scripts\python.exe`；运行前先 `$env:PYTHONIOENCODING="utf-8"`。
- 滚动统计量一律 `.shift(1)`；T 日信号、T+1 成交；禁止未来信息。
- **Part 1 之后**，默认执行口径 = `open`（T+1 开盘成交 + 高开≥1% 顺延 + 停牌跳过）；默认参数 = `bull_threshold=0.30`、`corr_threshold=0.85`。
- **Part 0/2/4 不得改变策略数值**：每任务以全量 `pytest` + `IDENTICAL` 回归（对照 Part 1 之后的新基线）收口。
- 回测评估指标唯一来源 = bt 内置统计；观测层只旁路记录，不参与决策。
- 一次只动一个维度；数值变化的改动（Task 6/7）逐任务单独 commit 便于归因。
- 成本单边 8bp、现金年化 1.8%；`.env` token 不得打印/提交/写日志；`data/` 与 `reports/` 生成物按既有约定 gitignore。
- 基础设施复用开源件：Hydra、DVC 或轻量 manifest、现有 registry 修到 ml4t-registry-system 标准；不引入 MLflow/wandb。
- 当前分支 `main`。

## Review Focus

| 输入/失效模式 | 期望行为 | 归属任务 |
|---|---|---|
| run_id 维度不全 | close/open、不同代码、不同数据快照、不同信号版本 → 不同 run_id，不互相覆盖 | Task 1 |
| 参数越界/幽灵参数 | schema 校验失败即报错；「声明但未接线」的参数显式标注，改 yaml 必生效 | Task 2/3 |
| 观测层不引入前视 | trace 只取 `_daily_target` 当日已算值；面板在 `_precompute_signals` 内已 `.shift(1)` | Task 10/11 |
| 观测层缺失降级 | `run_report.py` 无 `reports/signals/*.parquet` 时打印 WARNING 跳过章节 | Task 13 |
| 归因过程产生大量变体 run | 每个变体（机制开关/假设网格）都登记到 registry，可回查、可 diff | Task 14–16 |

---

## Part 0：工程化基础设施（不改数值，先做）

### Task 1: registry 修到 ml4t-registry-system 标准

**Files:**
- Modify: `src/etf_rotation/evaluation/registry.py`
- Modify: `scripts/run_backtest.py`（登记处传入 code/data/execution 信息）
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces: `config_hash` 改为 `run_identity(params, *, git_sha, data_snapshot_id, execution, signal_version) -> str`（`sha256` 于 `sort_keys` JSON 拼接，取前 12）。
- Produces: `register_run` 改 append-only：`INSERT`（非 `INSERT OR REPLACE`），重复 run_id 不覆写、记 `superseded` 状态。
- Produces: `data_snapshot_id` 与 `env_lock_hash` 不再空字符串（Task 5 填真值）。
- 网格结果（Task 14–16 与 `run_grid.py`）写入同一 registry 的 `run_metrics`。

- [ ] **Step 1: 写失败测试** — `test_registry.py`：不同 `execution`、不同 `git_sha`、不同 `data_snapshot_id` 各产生不同 run_id；相同身份二次 `register_run` 不覆盖、返回 superseded。
- [ ] **Step 2: 运行确认失败** — `pytest tests/test_registry.py -q`，Expected: FAIL（现 run_id 只哈希 params、`INSERT OR REPLACE` 覆写）。
- [ ] **Step 3: 实现** — 按接口改 `registry.py`；`run_backtest.py` 传 `git_sha`（复用 `registry.git_sha()`）、`data_snapshot_id`（Task 5 提供）、`execution`、`signal_version`（本次先用 git_sha 近似）。
- [ ] **Step 4: pytest + 冒烟** — 全量 `pytest -q` 全绿；`run_backtest.py`（默认）后 duckdb 中 run_id 正确、`data_snapshot_id` 非空。
- [ ] **Step 5: Commit** — `git commit -m "fix: run identity includes code/data/execution; append-only registry"`。

### Task 2: 参数 schema + 命名版本（ml4t-canonical-schema）

**Files:**
- Create: `src/etf_rotation/config_schema.py`（pydantic 或 dataclass schema：类型/范围/单位/默认）
- Modify: `src/etf_rotation/config.py`（`load_params` 返回经 schema 校验的字典；越界/未知键报错）
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `validate_params(dict) -> dict`（类型推断 + 范围校验，失败抛 `ConfigError` 含字段路径）。
- 命名参数集：`config/params.yaml`（默认）+ 可选 `config/paramsets/<name>.yaml` 覆盖层，diff 用 `flatten_params`。

- [ ] **Step 1: 写失败测试** — `test_config.py`：非法值（如 `bull_threshold=2.0`、`dedupe.max_holdings=-1`）抛错；未知键抛错；合法默认通过。
- [ ] **Step 2: 运行确认失败** — `pytest tests/test_config.py -q`，Expected: FAIL（现 `load_params` 无校验）。
- [ ] **Step 3: 实现** — 定义 schema（对齐 `params.yaml` 全部键）；`load_params` 末尾接校验。
- [ ] **Step 4: pytest + 冒烟** — 全量 `pytest -q`；`run_backtest.py` 默认跑通（默认值合法）。
- [ ] **Step 5: Commit** — `git commit -m "feat: typed params schema with range validation"`。

### Task 3: H1–H10 参数化 + 假设账本

**Files:**
- Modify: `src/etf_rotation/signals/trend.py`（H1 时间权重 `weighting: linear|exp` 参数化，默认 linear）
- Modify: `src/etf_rotation/signals/market_state.py`（H2 LLT variant 参数化；`slope_up/slope_down` 接线）
- Modify: `src/etf_rotation/portfolio/multi_asset.py`、`pipeline.py`（H5 反转权重、H7 纳指黄金退出阈值等接线）
- Create: `docs/assumptions.md`（假设账本：H# → 代码位置 → 当前值 → 候选 → 敏感性状态）
- Modify: `config/params.yaml`（新增假设开关键，默认值保持现值）
- Test: `tests/test_trend.py`、`tests/test_market_state.py` 等

**Interfaces:**
- 每个 H 假设对应一个 params 键（如 `trend.weighting=linear`、`reversal.momentum_weight=0.5`、`multi_asset.nasdaq_exit_threshold=0.0`）；默认值下数值与现状逐值一致。

- [ ] **Step 1: 写等价性测试** — 对新参数化项：默认值下的输出与旧实现 `assert_allclose` 逐值一致。
- [ ] **Step 2: 运行确认失败** — 视实现进展：新键未接线则测试失败。
- [ ] **Step 3: 实现** — 逐项参数化 + 接线，默认值不变；写 `docs/assumptions.md` 账本。
- [ ] **Step 4: pytest + 回归** — 全量 `pytest -q`；`run_backtest.py` 后 `weights/metrics` 与基线 `IDENTICAL`。
- [ ] **Step 5: Commit** — `git commit -m "feat: parameterize H1-H10 assumptions with ledger (defaults unchanged)"`。

### Task 4: Hydra 配置 + multirun 网格

**Files:**
- Create: `scripts/run_grid_hydra.py`（`@hydra.main`，config 组合 + `-m` multirun）
- Modify: `scripts/run_grid.py` 与 `run_heatmap.py`（改为 Hydra 驱动或保留为薄封装）
- Modify: `requirements.txt`（加 `hydra-core`）
- Test: `tests/test_config.py`（Hydra config 加载冒烟）

**Interfaces:**
- `scripts/run_grid_hydra.py --multirun grid=corr_threshold grid=...` 一键并行扫多维度，每个组合登记到 registry（复用 Task 1）。

- [ ] **Step 1: 写冒烟测试** — Hydra 配置可加载、`multirun` 产出与现有 `run_grid` 相同的结果集。
- [ ] **Step 2: 运行确认失败** — Hydra 未装/未接入则失败。
- [ ] **Step 3: 实现** — 装 `hydra-core`，把网格/热力图迁到 Hydra（或 Hydra 薄封装调现有函数），结果进 registry。
- [ ] **Step 4: pytest + 冒烟** — 全量 `pytest -q`；Hydra multirun 跑一个 2×2 网格验证结果落 registry。
- [ ] **Step 5: Commit** — `git commit -m "feat: hydra-based multirun grid with registry persistence"`。

### Task 5: 数据快照哈希入 run_id

**Files:**
- Create: `src/etf_rotation/data/snapshot.py`（bronze parquet 内容 sha256 → `data_snapshot_id`）
- Modify: `scripts/run_backtest.py`（传入 `data_snapshot_id`）
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces: `snapshot.data_snapshot_id() -> str`（对 `data/bronze/...` 快照文件做内容哈希；或轻量 manifest 记录文件清单 + sha256）。

- [ ] **Step 1: 写失败测试** — 同数据两次调用返回同 id；改动一个 bronze 文件后 id 变化。
- [ ] **Step 2: 运行确认失败** — 函数不存在。
- [ ] **Step 3: 实现** — 计算数据快照哈希，接入 `run_backtest.py`。
- [ ] **Step 4: pytest + 冒烟** — 全量 `pytest -q`；`run_backtest.py` 后 registry 的 `data_snapshot_id` 非空且稳定。
- [ ] **Step 5: Commit** — `git commit -m "feat: data snapshot hash into run identity"`。

---

## Part 1：前置决策（改变数值，逐任务 commit + 重立基线）

### Task 6: 执行口径默认 close → open

**Files:**
- Modify: `src/etf_rotation/backtest/run.py:57-58`（`execution="close"` → `"open"`；更新 docstring）
- Modify: `scripts/run_backtest.py:29-30`（argparse 默认 `"open"`；更新 `main()` docstring）
- Test: `tests/test_backtest.py`

- [ ] **Step 1: 写失败测试** — `test_run_defaults_to_open_execution`：缺省 execution 与 `execution="open"` 的 nav 一致、与 `"close"` 不同。
- [ ] **Step 2: 运行确认失败** — `pytest tests/test_backtest.py -q`，Expected: FAIL。
- [ ] **Step 3: 实现** — 改两处默认 + docstring；`run.run` 缺省 `execution="open"`。
- [ ] **Step 4: pytest + 冒烟** — 全量 `pytest -q` 全绿；`run_backtest.py`（默认参数，不带 `--execution`）打印指标 ≈ open 行 **9.52% / -14.47% / 0.87 / 0.66**。
- [ ] **Step 5: Commit** — `git commit -m "feat: default execution to T+1 open (OpenRebalance), keep --execution close"`。

### Task 7: 候选参数写回 params.yaml

**Files:**
- Modify: `config/params.yaml:13,18`（`bull_threshold` 0.35→0.30；`corr_threshold` 0.80→0.85）
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试** — `test_load_params_defaults` 断言 0.30 / 0.85（现第 7 行硬编码 0.80）。
- [ ] **Step 2: 运行确认失败** — `pytest tests/test_config.py -q`，Expected: FAIL。
- [ ] **Step 3: 实现** — 改 params.yaml 两处；grep tests 中其它旧默认断言并同步修正。
- [ ] **Step 4: pytest + 冒烟** — 全量 `pytest -q`；`run_backtest.py`（默认 open + 候选）跑通并记录新基线数字。
- [ ] **Step 5: Commit** — `git commit -m "feat: write tuned candidate params (bull 0.30 / corr 0.85) into defaults"`。

### Task 8: 重新确立基线 + 刷新文档

**Files:** Regenerate `reports/`；Modify `reports/回测报告.md`、`README.md`、`CHANGELOG.md`。

- [ ] **Step 1: 重跑基准** — `run_backtest.py 2019-01-01 2026-07-31`（默认 open+候选），记录新基线。
- [ ] **Step 2: 重跑成本敏感性** — `run_sensitivity.py`（`run.run` 默认已 open），刷新 `sensitivity.json`。
- [ ] **Step 3: 重跑报告** — `run_report.py`。
- [ ] **Step 4: 手改叙事** — `回测报告.md`「执行精度」改为默认 open、「结果概览」补 open+候选；README/CHANGELOG 记 v1.1.0。
- [ ] **Step 5: 留存新基线快照** — 复制 `weights.parquet`/`metrics.json` 为 `*.baseline.*`，作为 Part 2/4 的 `IDENTICAL` 对照。
- [ ] **Step 6: Commit** — 提交并记录新基线数字。

---

## Part 2：可观测化（不改数值，相对 Part 1 新基线 IDENTICAL）

### Task 9: 动量两套实现收敛（TODO 3.2）

**Files:** Modify `src/etf_rotation/signals/trend.py`、`src/etf_rotation/pipeline.py`；Test `tests/test_trend.py`。

- [ ] **Step 1:** 写等价性测试 `test_momentum_panel_matches_score_single_column`。
- [ ] **Step 2:** `pytest tests/test_trend.py -q` FAIL（`trend.momentum_panel` 不存在）。
- [ ] **Step 3:** 迁 `momentum_panel` 入 `trend.py`（`ann` 参数化）、`momentum_score` 改薄封装、`pipeline.py` 改 import。
- [ ] **Step 4:** 全量 `pytest` + `IDENTICAL`。
- [ ] **Step 5:** `git commit -m "refactor: consolidate momentum_panel into signals/trend (param ann, equivalence test)"`。

### Task 10: pipeline 采集每日决策轨迹（trace）

**Files:** Modify `src/etf_rotation/pipeline.py`；Test `tests/test_pipeline.py`。

**Interfaces:** `_precompute_signals` 增 `comp`；`_daily_target` 返回 6 元组含 `trace`；`build_weights(..., with_trace=False)`，`True` 返回 `BuildResult(weights, traces, days, sig)`；`_apply_hysteresis` 返回 `(weights, held, new, old)`。trace 含 portfolio 级字段与 `cands/keep/score/overheat_exited/defensive/hysteresis_held/new_score/old_score/vol_cap_scale/total_weight`。

- [ ] **Step 1:** 写 `test_build_weights_with_trace_keeps_weights_identical`。
- [ ] **Step 2:** `pytest -k with_trace` FAIL。
- [ ] **Step 3:** 按接口实现（trace 只读中间量）。
- [ ] **Step 4:** 全量 `pytest` + `IDENTICAL`。
- [ ] **Step 5:** `git commit -m "feat: collect per-day decision trace in build_weights (weights unchanged)"`。

### Task 11: observability 落盘 decision_diary + ticker_signals

**Files:** Create `src/etf_rotation/evaluation/observability.py`；Modify `scripts/run_backtest.py`；Test `tests/test_observability.py`。

**Interfaces:** `observability.build_frames(days, traces, sig, params) -> (decision_diary, ticker_signals)`；`observability.write(reports_dir, diary, tk)`。列模型见 `docs/superpowers/plans/2026-10-18-etf-rotation-observability.md` §数据模型。

- [ ] **Step 1:** 写 `test_build_frames_shapes_and_status`、`test_ticker_signals_only_held_and_candidates`。
- [ ] **Step 2:** `pytest tests/test_observability.py -q` FAIL。
- [ ] **Step 3:** 实现；`run_backtest.py` 切 `with_trace=True` 并落盘。
- [ ] **Step 4:** 全量 `pytest` + 冒烟（两张 parquet 生成）+ `IDENTICAL`。
- [ ] **Step 5:** `git commit -m "feat: persist decision diary and per-ticker signal snapshot"`。

### Task 12: plots 信号/决策图

**Files:** Modify `src/etf_rotation/evaluation/plots.py`；Test `tests/test_observability.py`。

**Interfaces:** `market_state_timeline(diary, nav)`、`risk_budget_stack(diary)`、`signal_trends(tk, ticker)`、`trade_triggers(diary, trades)`，均返回 `go.Figure`。

- [ ] **Step 1:** 写 `test_signal_plot_figures_build` 冒烟。
- [ ] **Step 2:** FAIL（函数不存在）。
- [ ] **Step 3:** 实现四个函数。
- [ ] **Step 4:** 全量 `pytest`；Commit `feat: signal/decision plots`。

### Task 13: run_report 集成「信号与决策」章节

**Files:** Modify `scripts/run_report.py`。

- [ ] **Step 1:** 读 `decision_diary`/`ticker_signals`/`trades.csv` 构建章节；缺文件降级（WARNING + 跳过）。
- [ ] **Step 2:** `run_report.py` 冒烟；Commit `feat: integrate signal/decision section into report`。

---

## Part 3：差距归因 + 假设/机制敏感性（研究阶段，产出归因结论）

> 本部分为研究型任务：每个任务的交付物是「可复现的分析脚本 + 结果进 registry + 结论」。变体 run 都登记到 Task 1 的账本，便于回查与 diff。所有分析基于 Part 1 之后的新基线（open+候选）。

### Task 14: 资产类别 / 区间收益归因

**Files:** Create `src/etf_rotation/evaluation/attribution.py`；Create `scripts/run_attribution.py`；Test `tests/test_attribution.py`。

- [ ] **Step 1:** 写测试 — `attribution.asset_class_contributions(weights, close, classification) -> DataFrame` 分桶（风险/纳指/黄金/防守/现金）贡献与总和守恒；`period_contributions` 分年度。
- [ ] **Step 2:** FAIL（模块不存在）。
- [ ] **Step 3:** 实现 + 脚本落盘 `reports/attribution/*.json` 并进 registry。
- [ ] **Step 4:** `pytest` + 运行脚本，产出「每桶贡献」表。
- [ ] **Step 5:** Commit `feat: asset-class and period return attribution`。

### Task 15: 机制开关对照

**Files:** Create `scripts/run_mechanism_ablation.py`；Test `tests/test_pipeline.py`（开关不影响其它默认路径）。

- [ ] **Step 1:** 为每个机制（五相位/迟滞/反转/过热/34% 波动）加开关（默认 on，off 时走绕过路径），默认下数值不变。
- [ ] **Step 2:** 脚本逐项 off → 跑 → 登记，产出「机制 on/off 增量」表。
- [ ] **Step 3:** `pytest` + `IDENTICAL`（默认全 on 不变）。
- [ ] **Step 4:** Commit `feat: mechanism ablation harness`。

### Task 16: 假设敏感性网格（H1–H10）

**Files:** Modify `config/params.yaml`（假设键已由 Task 3 接入）；Create `scripts/run_assumption_sensitivity.py`；复用 Task 4 Hydra multirun。

- [ ] **Step 1:** 定义 H1–H10 每项的候选取值（如 H1 linear|exp、H5 30/50/70、H7 0|±5%）。
- [ ] **Step 2:** Hydra multirun 扫假设网格，每组合进 registry，输出稳健性分数 + 悬崖 + DSR。
- [ ] **Step 3:** 产出「假设敏感性」表，标出哪些假设显著影响结果。
- [ ] **Step 4:** Commit `feat: assumption (H1-H10) sensitivity grid`。

### Task 17: 集中度 / 暴露分析

**Files:** Create `src/etf_rotation/evaluation/exposure.py`；Test `tests/test_exposure.py`。

- [ ] **Step 1:** 写测试 — HHI / 有效持仓数、资产类暴露时间序列、滚动暴露漂移。
- [ ] **Step 2:** FAIL → 实现 → `pytest`。
- [ ] **Step 3:** 产出暴露报告，确认无意外集中押注。
- [ ] **Step 4:** Commit `feat: concentration and exposure analysis`。

### Task 18: 数据质量复核（幸存者偏差 / point-in-time / 口径）

**Files:** Create `scripts/audit_data_quality.py`；Test `tests/test_universe.py`。

- [ ] **Step 1:** 审计：退市/清盘 ETF 是否漏入池（幸存者偏差）；point-in-time 池子无前视；tushare vs Wind 复权/指数口径差异（无 Wind，改用复权口径敏感性 + 中证2000 回补口径做有界上界）。
- [ ] **Step 2:** 产出数据质量报告，给出「数据源/标的池」两桶的有界上界（proxy），并声明无法精确归因的部分。
- [ ] **Step 3:** Commit `feat: data quality audit (survivorship / point-in-time / source gap)`。

### Task 19: 归因结论报告

**Files:** Modify `reports/回测报告.md`（新增「差距归因」章节）；Create `reports/差距归因.md`（或并入调参记录）。

- [ ] **Step 1:** 汇总 Task 14–18 结论，按「固定顺序 waterfall + 显式残差桶」（信号/组合/执行实测，数据源/标的池有界上界）把 6 点归到五桶，给出「逼近 vs 不可逼近」判断。
- [ ] **Step 2:** 更新 DSR/子区间一致性核验，确认未过拟合。
- [ ] **Step 3:** Commit `docs: gap attribution report`。

---

## Part 4：阶段三/四收尾（不改数值）

> gate = 全量 `pytest` + `IDENTICAL`；每任务一个 commit。决策类（Task 23、26）在 commit 说明裁决。

### Task 20: 五相位两套实现收敛（TODO 3.1）

保留主线 `pipeline._combine_phases`；`execution/phases.combine` 二选一（删除或薄封装）+ 等价性测试。Commit `refactor: converge five-phase combine`。

### Task 21: 可投资池过滤重复收敛（TODO 3.3）

`universe.build_pool` 与 `pipeline._daily_target` 内联过滤二选一 + 等价性测试。Commit `refactor: converge investable-pool filter`。

### Task 22: `weights.shift(1).fillna(0)` 抽公共（TODO 3.4）

新建 `execution/shift_weights.py::shift_weights(weights)`，替换三处脚本调用 + 小测试。Commit `refactor: extract shared weights.shift(1).fillna(0)`。

### Task 23: 现金资产决策（TODO 3.5）

维持 `_CashInterest`（现金按 `(1+rf/252)` 日复利、不作独立权重资产），docstring 注明「现金资产建模」留待后续；若改属改变数值需回 Part 1 流程。Commit `docs: record cash-asset modeling decision`。

### Task 24: 持仓可视化现金口径（TODO 3.6）

`plots.holdings_distribution` 用引擎 `backtest.strategy.cash/nav` 替换 `1 - w.sum(axis=1)`。Commit `fix: use engine cash/nav for holdings cash leg`。

### Task 25: 陈旧/遗留代码清理（TODO 3.8）

`overheat_mask` 改 docstring；`execution/hysteresis.py`、`gap_delay.py` 及老测试若被主线替代则删除（先 grep 引用）。Commit `chore: remove legacy duplicate execution helpers`。

### Task 26: 剩余硬编码参数接线（TODO 3.9）

接线 `slope_up/slope_down`、`trend.ann_factor`、`multi_asset.*`、`execution.phases/phase_interval`、`run_sensitivity.py` 的 `cash_rate`，或显式标注为「研报固定常量」。Commit `refactor: wire remaining declared params`。

### Task 27: 文档维护（TODO 4.1–4.4）

README 基线/测试数同步；`docs/deepseek_hand_book.md` 与「分步实现路线」二选一删除；版本号统一 1.1.0 + `git tag v1.1.0`。Commit `docs: sync README, dedupe docs, bump v1.1.0`。

---

## 执行顺序与依赖

Part 0（Task 1→2→3→4→5）为基础设施，须先做且不改数值；其中 Task 1（registry）与 Task 5（数据快照）互为依赖，Task 2/3（schema + 参数化）为 Task 16（假设网格）前置，Task 4（Hydra）为 Task 14–16 的搜索底座。Part 1（Task 6→7→8）改变数值、顺序依赖，产出新基线。Part 2（Task 9→10→11→12→13）顺序依赖，不改数值。Part 3（Task 14–19）依赖 Part 0/1/2 产出，Task 14–18 可部分并行，Task 19 汇总。Part 4（Task 20–27）相互独立，收尾。Part 0/2/4 每任务须过 `IDENTICAL`（对照 Part 1 新基线）。

## 不在本计划范围（后续可选）

- open 口径下重新调参（候选参数为 close 口径调出，本计划直接采纳）。
- 全市场全标的信号面板（范围 = 持仓+候选+关键退出点）。
- 更真实执行建模（滑点/冲击成本/涨跌停/ETF 折溢价）。
- 若归因证明差距主因是数据源口径，再评估「换数据源或对齐 Wind 口径」的可行性。

## 最终验收 checklist（reviewer 用）

- [ ] `.venv\Scripts\python.exe -m pytest tests -q` 全绿（含新增 registry/config/trend/observability/exposure/attribution 测试）。
- [ ] `run_backtest.py`（默认 open + 候选）跑通，registry 中 run_id 唯一对应参数+代码+数据+执行+信号版本，`data_snapshot_id` 非空。
- [ ] `weights.parquet`/`metrics.json` 与 `*.baseline.*` 逐值一致（Part 0/2/4 未改数值）。
- [ ] `reports/signals/*.parquet` 生成、列符合数据模型；`run_report.py` 含「信号与决策」章节，缺文件优雅降级。
- [ ] H1–H10 全部参数化且有假设账本；`docs/assumptions.md` 每条假设可追溯到代码位置。
- [ ] 归因报告把约 6 点差距归到五桶并量化；假设/机制敏感性结果进 registry 可回查。
- [ ] 阶段三/四全部收口或显式裁决；版本号 v1.1.0 并打 tag。
- [ ] `.env` token 未泄露；`data/` 未入库；`reports/` 生成物处理与既有约定一致。
