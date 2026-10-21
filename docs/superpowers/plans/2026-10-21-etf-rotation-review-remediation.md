# 审查整改计划：修正 DSR 公式 / 补齐登记与报告 / 统一文档

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依据 2026-10-21 第三方审查发现（H1/H2、M1–M4、L1–L8），修正统计口径、补齐归因过程的登记与暴露报告、统一文档测试数与基线数字，且不改变策略数值（不采纳任何新参数入默认）。

**Architecture:** 保持现有「pandas 信号 → 权重面板 → bt 记账」架构与默认参数（open + bull 0.30 / corr 0.85）完全不变。分三部分：① 统计与方法论修正（修 DSR 标准误、重算多重检验 + H1/H7 OOS 复核）；② 基础设施补齐（机制 ablation 入 registry、暴露报告、Hydra 口径收敛、registry 加 execution 列 + superseded 状态）；③ 文档一致性收尾（回测报告刷新、TODO/代码审阅手册更新、测试数统一 + 版本 bump）。

**Tech Stack:** Python 3.10 / pandas 2.3 / numpy 2.2 / bt 1.2.2 / duckdb / pytest / scipy / Hydra。

**Spec:** 本计划的依据是 2026-10-21 第三方审查结论（H1/H2、M1–M4、L1–L8，摘要见下）。上游文档：
- `docs/superpowers/plans/2026-10-19-etf-rotation-next-phase.md`（被审查的计划）
- `docs/superpowers/specs/2026-10-19-etf-rotation-attribution-and-infra-design.md`（设计，含反目标「过 DSR / 子区间一致性 / 前视防护三道关」）
- `reports/差距归因.md`、`reports/回测报告.md`（待修正的结论载体）

### 审查发现摘要（本计划的 Spec）

| ID | 问题 | 类型 |
|---|---|---|
| H1 | `overfitting.deflated_sharpe` 标准误用「候选数 N」当「观测数 T」，DSR 恒≈0.5，报告里「DSR 0.54~0.55」是公式 bug 伪影 | 代码 bug |
| H2 | H1-exp / H7-(-0.05) 从 18 变体中挑出，未过多重检验门、未做 OOS 子区间复核，即写入「能显著逼近」 | 方法论 |
| M1 | 机制 ablation 变体未登记 registry（duckdb 33 条 run 中 0 条 `mechanisms.*=false`），违反计划 Review Focus | 缺口 |
| M2 | Task 17「暴露报告」未产出（无 `run_exposure.py`/`reports/exposure.json`，差距归因 §5 为散文） | 缺口 |
| M3 | Task 19 Step 2「更新 DSR/子区间一致性核验」未落地（差距归因.md 无 DSR、无 open 子区间表） | 缺口 |
| M4 | `config/hydra/grid.yaml` 默认 `execution: close`，与全局 open 默认矛盾（run_grid.py vs run_grid_hydra.py 口径相反） | 不一致 |
| L1 | 测试数三处矛盾：README「87」/ CHANGELOG「83」/ 计划「93」，实测 93 总数 | 文档 |
| L2 | `v1.1.0` tag 打在最终评审修复（23fe10d）之前，不含修复 | 文档 |
| L3 | 回测报告「成本敏感性」「样本外稳健性」「执行精度」仍为 close/旧 open 数字，与 open 基线 9.61% 矛盾 | 文档 |
| L4 | TODO.md 阶段一~四全部未勾选，与「全部收口」矛盾 | 文档 |
| L5 | 代码审阅手册引用已删除的 `execution/phases.py` 等，并称参数「未接入主线」 | 文档 |
| L6 | registry `runs` 表无 execution/signal_version 列，close/open 不可查回 | 缺口 |
| L7 | `register_run` 未实现「superseded 状态」；`run_metrics` 用 `INSERT OR REPLACE` | 缺口 |
| L8 | 计划自认的 5 个 Minor（bear 阈值线 -0.30、env_lock_hash 未填、data_snapshot_id 不含 warehouse 等） | 已知 |

> 本计划覆盖 H1/H2/M1–M4/L1–L7。L8 为计划已披露的 Minor，本计划不重做，仅在 Task 8 的「代码审阅手册」更新中顺带标注为「已知遗留」。

## Global Constraints

- 所有 Python 统一用 `.venv\Scripts\python.exe`；运行前先 `$env:PYTHONIOENCODING="utf-8"`。
- 滚动统计量一律 `.shift(1)`；T 日信号、T+1 成交；禁止未来信息。
- **本计划不改变任何策略数值**：默认参数保持 open + `bull_threshold=0.30` + `corr_threshold=0.85`；Part 0/2/4 类改动每任务以全量 `pytest` + `IDENTICAL` 回归收口（对照现有基线 9.61% / -15.79% / 0.88 / 0.61）。
- 成本单边 8bp、现金年化 1.8%；`.env` token 不得打印/提交/写日志；`data/` 与 `reports/` 生成物按既有约定 gitignore。
- 一次只动一个维度；本计划不采纳 H1-exp / H7-(-0.05) 入默认——仅复核并产出结论，采纳属后续独立决策（见「不在本计划范围」）。
- 当前分支 `main`，改动按语义化 commit。

## Review Focus

| 输入/失效模式 | 期望行为 | 归属任务 |
|---|---|---|
| DSR 仍用候选数当观测数 | 修复后 SE 基于 `n_obs`；大观测数下显著 DSR>0.95 | Task 1 |
| 假设敏感性结论仍无多重检验/OOS | 报告含 18 变体 DSR + haircut + H1/H7 子区间表，且据结果降级措辞 | Task 2 |
| 机制 ablation 仍未登记 | 跑完脚本后 duckdb 出现 ≥5 条 `mechanisms.*=false` 的 run | Task 3 |
| Hydra 网格仍 close | `grid.yaml` execution==open，测试锁定 | Task 5 |
| 文档测试数仍不一致 | README/CHANGELOG 统一 96，grep 无 83/87 残留 | Task 9 |

---

## Part 1：统计与方法论修正（不改数值）

### Task 1: 修 `deflated_sharpe` 标准误（H1）

**Files:**
- Modify: `src/etf_rotation/evaluation/overfitting.py:6-18`（`deflated_sharpe`）
- Modify: `scripts/run_grid.py:62`、`scripts/run_sensitivity.py:40`（调用点）
- Test: `tests/test_metrics.py`

**Interfaces:**
- Produces: `deflated_sharpe(sharpes: list[float], n_trials: int, n_obs: int) -> float`。
  `n_obs` 为回测窗口内的日收益观测数（≈1838，2019-01-02 ~ 2026-07-31）。
  标准误改为 `np.sqrt(1 / (n_obs - 1))`（正态近似；偏度/峰度项留待需要时再加，docstring 注明）。
  `sharpe_haircut` 不改（其 `n = len(sharpes)` 是「N 次试验的期望最大值」，本就正确）。

- [ ] **Step 1: 写失败测试**

```python
def test_deflated_sharpe_significant_with_large_n_obs():
    # 三个候选 Sharpe 均远高于零、观测数足够大时，DSR 应显著（>0.95）。
    # 当前实现 sr_se=sqrt(1/(3-1))=0.707，得约 0.55；修复后约 1.0。
    p = overfitting.deflated_sharpe([1.5, 1.5, 1.5], 3, n_obs=2000)
    assert p > 0.95
```

- [ ] **Step 2: 运行确认失败** — `pytest tests/test_metrics.py::test_deflated_sharpe_significant_with_large_n_obs -v`，Expected: FAIL（当前 ≈0.55）。

- [ ] **Step 3: 实现** — 改签名加 `n_obs: int`；`sr_se = np.sqrt(1 / (n_obs - 1))`；更新 docstring 说明「SE 基于观测数 T，非候选数 N」；既有 `test_dsr_high_for_many_bad_trials` 同步传 `n_obs`（如 `n_obs=1900`）。

- [ ] **Step 4: 更新调用点** — `run_grid.py`：`deflated_sharpe(sharpes, n, n_obs=int(r.returns.notna().sum()))`（在循环外取一次，所有网格点同长）；`run_sensitivity.py`：`deflated_sharpe(sharpes, len(sharpes), n_obs=int(r.returns.notna().sum()))`。

- [ ] **Step 5: pytest** — 全量 `pytest tests -q` 全绿；`python -c "from etf_rotation.evaluation.overfitting import deflated_sharpe as d; print(d([1.5]*3, 3, 2000))"` 输出 >0.95。

- [ ] **Step 6: Commit** — `git commit -m "fix: deflated_sharpe uses observation count for standard error"`。

### Task 2: 重算假设敏感性 DSR + H1/H7 OOS 复核，改写结论（H2 / M3）

**Files:**
- Modify: `scripts/run_assumption_sensitivity.py`（输出 DSR / sharpe_haircut）
- Create: `scripts/run_oos_check.py`
- Modify: `reports/差距归因.md`（§6 / §7）

**Interfaces:**
- Produces: `run_assumption_sensitivity.py` 在写盘前对**全部 18 个变体**的 `sharpe` 序列计算
  `overfitting.deflated_sharpe(all_sharpes, n_trials=len(all_sharpes), n_obs=...)` 与
  `overfitting.sharpe_haircut(all_sharpes)`，写进 `reports/assumption_sensitivity.json` 顶层键 `"dsr"`、`"sharpe_haircut"`。
- Produces: `run_oos_check.py --param a.b=v`（可重复）→ 对给定覆盖，在
  `2019-01-01..2023-12-31` 与 `2024-01-01..2026-07-31` 两个子区间各跑 `build_weights` + `run.run`（open），
  打印并落 `reports/oos_check.json`：`{param_overrides, subperiods: {区间: {ann_return, max_drawdown, sharpe, calmar}}}`。

- [ ] **Step 1:** 在 `run_assumption_sensitivity.py` 加 DSR/haircut 汇总（复用 Task 1 修复后的函数），重跑并确认 `assumption_sensitivity.json` 顶层出现 `"dsr"` 与 `"sharpe_haircut"`。

- [ ] **Step 2:** 创建 `run_oos_check.py`（复用 `shift_weights` / `load_context` / `run.run`，两个子区间硬编码常量）。

- [ ] **Step 3:** 跑两个候选的子区间复核：`run_oos_check.py --param trend.weighting=exp` 与 `--param multi_asset.nasdaq_exit_threshold=-0.05`，得到各子区间指标。

- [ ] **Step 4:** 据结果改写 `差距归因.md`：① §6 补 DSR 数字 + 「18 变体多重检验」说明；② 新增 H1/H7 的 2019–2023 / 2024–2026 子区间表；③ §7 若 DSR 不显著或子区间方向不一致，把「能显著逼近」降级为「候选 / 待进一步验证」，并删除未实测的「叠加 → ~11%」外推或明确标注为「未实测的假设」。

- [ ] **Step 5: Commit** — `git commit -m "docs: re-validate H1/H7 with corrected DSR and OOS sub-intervals"`。

---

## Part 2：基础设施补齐（不改数值）

### Task 3: 机制 ablation 变体登记 registry（M1）

**Files:**
- Modify: `scripts/run_mechanism_ablation.py`

**Interfaces:**
- Consumes: `registry.run_identity` / `registry.register_run`（复用 `run_assumption_sensitivity.py` 的 `_run_one` 内登记写法：`flat = config.flatten_params(p)` + `data_snapshot_id` + `git_sha`，run_id 唯一含 `mechanisms.*` 状态）。

- [ ] **Step 1:** 在 `_run` 回测后接 `registry.register_run`（`ROOT / "data" / "warehouse.duckdb"`，metrics 用 `s`，artifacts 传 `{}`），使 baseline 与每个 off 变体都登记。

- [ ] **Step 2: 冒烟 + 验收** — 跑 `scripts/run_mechanism_ablation.py`，然后查 duckdb：`SELECT count(*) FROM runs WHERE params_json LIKE '%"mechanisms.phases": false%'`（或解析 json）应 ≥5 条 off 变体；且 `reports/ablation.json` 数字与现有基线一致（baseline 仍 9.61%/-15.79%/0.88/0.61，证明未改数值）。

- [ ] **Step 3: Commit** — `git commit -m "fix: register mechanism ablation variants to registry"`。

### Task 4: 暴露分析报告脚本（M2）

**Files:**
- Create: `scripts/run_exposure.py`
- Modify: `reports/差距归因.md`（§5）

**Interfaces:**
- Consumes: `evaluation/exposure.py` 的 `concentration_series` / `asset_class_exposure`（已有测试覆盖）。
- Produces: `reports/exposure.json`：`{hhi_mean, effective_n_mean, hhi_max, effective_n_min, asset_class_exposure_mean}`（`exposure.concentration_series` 与 `asset_class_exposure` 的全区间均值 + 极值）。

- [ ] **Step 1:** 创建 `run_exposure.py`：读 `reports/weights.parquet` + `load_fund_basic`/`univ.classify`（纳指/黄金/防守/风险分类与 `run_attribution.py` 同口径），调用 exposure 两函数，写 `reports/exposure.json`。

- [ ] **Step 2:** 运行并确认 `reports/exposure.json` 生成、含 hhi/effective_n/asset_class_exposure 数字。

- [ ] **Step 3:** 改 `差距归因.md` §5：用实际 HHI / 有效持仓数 / 资产类暴露均值替换散文，并声明「无意外集中押注」与否的依据。

- [ ] **Step 4: Commit** — `git commit -m "feat: exposure report (HHI / effective-N / asset-class exposure)"`。

### Task 5: Hydra 网格执行口径 close → open（M4）

**Files:**
- Modify: `config/hydra/grid.yaml:9`（`execution: close` → `open`）
- Modify: `tests/test_config.py:78-86`（`test_hydra_grid_config_loads`）

- [ ] **Step 1: 写失败测试** — 把 `test_hydra_grid_config_loads` 的 `assert cfg["execution"] == "close"` 改为 `assert cfg["execution"] == "open"`，Expected: FAIL。

- [ ] **Step 2: 实现** — `grid.yaml` 的 `execution` 改 `open`；确认 `run_grid_hydra.py` 的 `_run_one` 已透传 `cfg.execution`（无需改代码）。

- [ ] **Step 3: pytest** — `pytest tests/test_config.py -q` 全绿；全量 `pytest -q` 全绿。

- [ ] **Step 4: Commit** — `git commit -m "fix: hydra grid default execution to open (match global default)"`。

### Task 6: registry 加 execution 列 + superseded 状态（L6 / L7）

**Files:**
- Modify: `src/etf_rotation/evaluation/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces: `register_run(..., execution: str = "close")`；`runs` 表新增 `execution VARCHAR NOT NULL` 列；
  重复 run_id 时 `UPDATE runs SET status='superseded'`（不覆写 metrics，仍返回原 run_id）；
  `run_metrics` 由 `INSERT OR REPLACE` 改为 `INSERT`（run_id 幂等，metric 冲突时忽略）。
- 迁移：既有 `data/warehouse.duckdb` 的 `runs` 表缺 execution 列，`register_run` 在建表后追加
  `ALTER TABLE runs ADD COLUMN IF NOT EXISTS execution VARCHAR`（duckdb 语法）以兼容旧库。

- [ ] **Step 1: 写失败测试** — `test_registry.py` 新增：
  ```python
  def test_register_run_stores_execution_column(tmp_path, monkeypatch):
      monkeypatch.chdir(tmp_path); db = tmp_path / "r.duckdb"
      registry.register_run(db, "a", {"x": 1}, {"sharpe": 1.0}, {}, execution="open", report_root=tmp_path/"reports")
      assert duckdb.connect(str(db)).execute("SELECT execution FROM runs WHERE run_id='a'").fetchone()[0] == "open"
  ```
  与 `test_register_run_marks_superseded`（二次同 id 登记后 `status=='superseded'` 且 metrics 不变）。

- [ ] **Step 2: 运行确认失败** — `pytest tests/test_registry.py -q`，Expected: FAIL（无 execution 列、无 superseded）。

- [ ] **Step 3: 实现** — 按接口改 `register_run`：建表含 execution 列 + `ALTER TABLE ADD COLUMN IF NOT EXISTS`；重复 run_id 分支写 superseded；`run_metrics` 改 `INSERT`（用 `ON CONFLICT DO NOTHING` 或先查再插）。同步更新 `run_backtest.py` / `run_assumption_sensitivity.py` / `run_grid_hydra.py` 的 `register_run` 调用传 `execution=`。

- [ ] **Step 4: pytest** — 全量 `pytest -q` 全绿。

- [ ] **Step 5: Commit** — `git commit -m "fix: store execution column and superseded status in registry"`。

---

## Part 3：文档一致性收尾（不改数值）

### Task 7: 回测报告数字刷新为 open 口径（L3）

**Files:**
- Modify: `reports/回测报告.md`（§成本敏感性、§样本外稳健性、§执行精度、§参数调优）

- [ ] **Step 1:** 用 `reports/sensitivity.json` 的 open 数字（0/8/16/24bp = 11.93% / 9.61% / 7.33% / 5.10%）替换「成本敏感性」表的 close 数字。

- [ ] **Step 2:** 「执行精度」表 open 行改为 9.61% / -15.79% / 0.88 / 0.61（与结果概览一致），并注明该行为「open + 候选参数」；close 行保留但标注「close 默认参数对照」。

- [ ] **Step 3:** 「样本外稳健性」表改为 open 口径子区间（重跑 `run_oos_check.py` 默认参数得到，或若未跑则以 Task 2 的默认行替代），删除或标注旧的 close 候选数字。

- [ ] **Step 4:** 通读全篇，消除「默认 close」残余表述（§结论「是否切 open 由用户决定」等旧话术改为「已切 open」）。

- [ ] **Step 5: Commit** — `git commit -m "docs: refresh backtest report cost/OOS/execution tables to open baseline"`。

### Task 8: TODO.md 勾选 + 代码审阅手册更新（L4 / L5）

**Files:**
- Modify: `TODO.md`
- Modify: `docs/代码审阅手册.md`

- [ ] **Step 1:** `TODO.md` 阶段一~四已完成的条目（1.1–1.5、2.1–2.8、3.1–3.9、4.1–4.4）勾选为 `- [x]`，并把本计划新发现但未决的项（如 H1/H7 采纳决策、L8 的 5 个 Minor）追加到「后续待办」。

- [ ] **Step 2:** `代码审阅手册.md`：删除/改写对 `execution/phases.py`、`hysteresis.py`、`gap_delay.py` 的引用，改为「已并入 `pipeline._combine_phases` / `_apply_hysteresis` / `OpenRebalance`」；把「`hysteresis_improve`/`gap_delay_pct` 未接入主线」更正为「已接入」；顺带标注 L8 的 5 个已知 Minor。

- [ ] **Step 3: Commit** — `git commit -m "docs: tick off TODO items; update code-review manual to converged structure"`。

### Task 9: 测试数统一 + 版本 bump v1.1.1（L1 / L2）

**Files:**
- Modify: `README.md`（测试数）
- Modify: `CHANGELOG.md`（v1.1.1 条目）
- Modify: `src/etf_rotation/__init__.py`（`__version__`）

- [ ] **Step 1:** `README.md`「测试：87 passed（另有 3 个慢测…）」改为「测试：96 passed」。`CHANGELOG.md` 顶部加 `## v1.1.1 (2026-10-21)` 条目，列出 H1–L7 修复要点，测试数写 96。

- [ ] **Step 2:** `__init__.py` 的 `__version__` 改 `"1.1.1"`。

- [ ] **Step 3:** 全量 `pytest -q` 全绿后 commit，并在该 commit 打 tag：
  ```bash
  git commit -m "docs: unify test count to 96; bump v1.1.1"
  git tag v1.1.1
  ```
  （`v1.1.0` 不动，避免移动可能已推送的 tag；v1.1.1 覆盖从 Task 1 起的全部整改。）

- [ ] **Step 4: 校验** — `grep -rn "83 passed\|87 passed" README.md CHANGELOG.md` 无残留；`git tag` 含 `v1.1.1`；`git rev-parse v1.1.1` == HEAD。

---

## 执行顺序与依赖

Task 1（DSR 修复）→ Task 2（复用修复后的 DSR 重算）为强依赖，须先做。Part 2 的 Task 3/4/5/6 相互独立，可并行。Part 3 的 Task 7/8 依赖 Task 2/4 的产物数字；Task 9（版本 bump）必须在所有代码与文档改动完成后最后执行。全计划不改变策略数值：唯一改变「报告数字」的是 DSR 统计量（修复后不再是 0.54~0.55），以及 Task 7 把报告表格从 close 刷新为 open——两者都不是策略参数/权重的变化，`weights.parquet`/`metrics.json` 应保持与 `*.baseline.*` 一致。

## 不在本计划范围（后续决策门）

- **H1-exp / H7-(-0.05) 是否采纳入默认**：本计划只复核 + 出结论。若 Task 2 复核通过且用户决定采纳，属「改变数值」的独立改动，须走 Part 1 流程（逐任务 commit + 重立基线 + 刷新报告），不在本计划内。
- L8 的 5 个已知 Minor（bear 阈值线 -0.30、env_lock_hash 未填、data_snapshot_id 不含 warehouse.duckdb 等）仅标注，不改。
- `data_snapshot_id` 覆盖 `warehouse.duckdb` 的同步不变式强化（L8 第 4 条），留待需要「数据版本与回测输入严格一致」时再做。

## 最终验收 checklist（reviewer 用）

- [ ] 全量 `pytest -q` 全绿（含新增 DSR/registry 测试），测试数统一 96。
- [ ] `deflated_sharpe` 标准误基于 `n_obs`；`python -c "...deflated_sharpe([1.5]*3,3,2000)"` >0.95。
- [ ] `reports/差距归因.md` 含 18 变体 DSR + haircut + H1/H7 OOS 子区间表，且措辞与结果一致（显著才说显著）。
- [ ] 机制 ablation 变体在 `data/warehouse.duckdb` 可查（≥5 条 `mechanisms.*=false`）。
- [ ] `reports/exposure.json` 生成，§5 有实际 HHI/有效持仓数数字。
- [ ] `config/hydra/grid.yaml` 默认 `execution: open`，测试锁定。
- [ ] registry `runs` 表含 `execution` 列；二次登记同 run_id 记 `superseded` 且不覆写 metrics。
- [ ] `回测报告.md` 成本/OOS/执行精度均为 open 口径；README/CHANGELOG 测试数 96；`v1.1.1` 已打 tag 且指向 HEAD。
- [ ] `weights.parquet` 与 `weights.baseline.parquet` 逐值一致（本计划未改数值）。
