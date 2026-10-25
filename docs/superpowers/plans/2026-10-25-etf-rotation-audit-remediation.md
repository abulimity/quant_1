# 审计整改 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 2026-10-25 第三方审计发现的「证据链纯度 / 派生串台 / 计划尾巴 / 文档一致性」四类问题收口，让 campaign DSR、派生数据、报告引用三者都能从同一个 `run_id` 与同一份干净代码追溯。

**Architecture:** 先修"记账与守门"（trial 去重、dirty 证据标记、镜像守卫、verify 扩展），再修"契约与并发"（performance 契约、同 run_id 写锁），再补"计划尾巴"（index.md、heatmap、prune、确定性），最后在**单一干净 commit** 上重跑整轮 campaign 并重建基线，旧 run 整体归档到 `reports/legacy/pre-remediation/`。文档在最后统一按新 run_id 刷新，避免中途反复改数字。

**Tech Stack:** Python 3.10、pandas、pyarrow、duckdb、pytest、PowerShell（仅运维步骤）；不新增依赖。

**Spec:** `docs/superpowers/plans/2026-10-24-etf-rotation-persistence-and-report-data.md` §1–§7 与本次审计结论（2026-10-25，会话记录）。持久化契约以该计划 §1 为准；本计划只改它的实现缺口，不改策略决策。

## Global Constraints

- 环境：`.venv\Scripts\python.exe`；运行任何 Python 前 `$env:PYTHONIOENCODING="utf-8"`；PowerShell 读中文文件一律 `-Encoding UTF8`。
- 不改策略决策、不改回测引擎、不改 `pipeline.py` 与 `config/params.yaml`；**基线净值必须与 `reports/legacy/v1.1.1/equity.csv` 零差异**（Task 10 验收项）。
- 不新增依赖；JSON 必须能通过 `json.dumps(..., allow_nan=False)`；日期一律 `YYYY-MM-DD`。
- 指标唯一来源仍是 `metrics.parquet`；派生层只做展示性聚合，不得重算绩效口径。
- `reports/` 下产物不入 git；只有 `reports/*.md`、`reports/legacy/README.md`、`reports/legacy/old-runs.txt` 可提交。
- 一个 Task 一个 commit（message 见各 Task 末步）；每个 Task 结束跑该 Task 的测试文件，最终 Task 13 跑全量。
- 时间纪律：T 日信号、T+1 成交；滚动统计只用 ≤ 当日信息。
- 长任务用受管后台或前台分块，不用 `Start-Process`；单次命令超过 10 分钟就拆。
- **序列化约束：** Task 1、2、7、8 都改 `scripts/collect_runs.py`，必须按序执行，不可并行。

## Review Focus

1. **run_id 一致性**：Task 10 重跑后，磁盘上不存在旧 run_id，而文档仍引用旧 id —— 任何文档改动都必须以新 `meta.parquet` 为唯一来源，不能用旧文本手改数字。
2. **派生串台**：`build_report_data --run-id <非 latest>` 不得改动 `reports/derived/`；镜像必须原子替换，且 `verify` 能发现 mirror 与 latest 不一致。
3. **证据链纯度**：campaign 的 `n_trials` 必须是 unique `run_id`；`git_dirty=TRUE` 的 run 不得进入 DSR 分母，且 `family.json` 必须记录 dirty 状态。
4. **不可逆操作**：Task 10 会移动 52 个 run 与 14 个 family 目录；移动前必须 `verify_artifacts` 全绿并写清单，移动后旧目录只读保留在 `reports/legacy/pre-remediation/`。
5. **并发写**：同一个 `run_id` 的档位升级路径会重写 `meta/metrics/artifacts`；Hydra 重复候选值下必须串行化，不能靠"每个 run 写自己目录"糊过去。

## 执行时间评估

| 阶段 | Task | 预估（agent 墙钟） | 依赖 |
|---|---|---|---|
| 记账与守门 | 1 trial 去重 | 0.75 h | — |
| | 2 dirty 证据 | 1.5 h | 1 |
| | 3 镜像守卫 | 1.5 h | — |
| | 4 verify 扩展 | 2.0 h | 3、5 |
| 契约与并发 | 5 derived 契约 | 1.25 h | — |
| | 6 同 run 写锁 | 1.25 h | — |
| 计划尾巴（代码） | 7 index.md | 1.5 h | 1、2 |
| | 8 成本敏感性绑定 | 2.0 h | 7 |
| | 9 网格契约对齐 | 0.75 h | — |
| 证据重建（运维） | 10 全量 campaign + 基线 | 2.0 h | 1–9 合并、代码冻结 |
| 尾巴验收（运维） | 11 heatmap / prune / 确定性 | 1.5 h | 10 |
| 文档 | 12 文档收口 | 3.0 h | 10、11 |
| 收口 | 13 最终验收 | 1.0 h | 全部 |
| **合计** | | **≈ 20 h（2.5–3 个工作日）** | |

- 串行执行最稳（推荐）：约 2.5–3 个工作日。
- 若把 Task 3、5、6、9 与 1→2→7→8 两条链并行：约 1.5–2 个工作日，但 `artifacts.py` / `runner.py` 有交叉，合并成本会吃掉一半收益。
- **最小路径**（跳过 Task 10，只把旧 run 标 `superseded` 并保留现有数字）：约 14 h，但 28 个旧 run 的 NaN 首行与 5 个 dirty run 仍在证据链里，审计缺口未真正关闭。
- 未计入：人工决策等待（3 个 gate）、H1/H7 是否采纳（独立决策，不在本计划）。

## 决策门（执行前必须由用户裁决）

- **G1 全量重跑**（Task 10）：会生成全新 `run_id`/`family_id`，`reports/*.md` 中 25 处旧 id 全部失效。推荐接受，否则证据链无法真正一致。
- **G2 网格默认档位**（Task 9）：改为 `standard`（符合计划 §1.4，每个网格点多约 2.4 MB），或保留 `minimal` 并在计划里写明偏离。
- **G3 未跟踪文件**：`docs/superpowers/specs/2026-10-25-*frontend*.md` 两个文件提交还是忽略。

---

## Task 1: campaign trial 按 run_id 去重

**Files:**
- Modify: `scripts/collect_runs.py:95-120`（`_search_pool`）、`scripts/collect_runs.py:130-230`（`family_summary`）
- Modify: `src/etf_rotation/evaluation/overfitting.py:14`（`campaign_trials`）
- Create: `tests/test_collect_runs.py`

**Interfaces:**
- Produces: `collect_runs.search_pool(families_root: Path, runs_root: Path, campaign_id: str) -> tuple[list[float], int | None]` —— 按 `run_id` 去重后的 Sharpe 列表与 `n_obs`；保留 `_search_pool` 为同名薄别名，避免外部调用断掉。
- Produces: `overfitting.campaign_trials(root, campaign_id) -> int` —— 改为 unique `run_id` 计数（跨 family 同 id 只算一次）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_collect_runs.py
import json
from pathlib import Path

import pandas as pd

from etf_rotation.evaluation import registry
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import collect_runs


def _run(runs_root, run_id, sharpe, n_obs=100):
    d = runs_root / run_id
    d.mkdir(parents=True)
    pd.DataFrame({"metric": ["sharpe"], "value": [sharpe]}).to_parquet(d / "metrics.parquet")
    pd.DataFrame({"n_obs": [n_obs]}).to_parquet(d / "meta.parquet")


def test_search_pool_dedupes_run_shared_by_two_families(tmp_path):
    runs, fams = tmp_path / "runs", tmp_path / "families"
    _run(runs, "base", 0.9)
    _run(runs, "a", 0.8)
    _run(runs, "b", 1.0)
    for fid, members in (("f1", ["base", "a"]), ("f2", ["base", "b"])):
        for rid in members:
            registry.write_family_member(fams, fid, rid, {}, campaign_id="c1")
    sharpes, _ = collect_runs.search_pool(fams, runs, "c1")
    assert len(sharpes) == 3            # base 只算一次
    assert sorted(sharpes) == [0.8, 0.9, 1.0]
```

```python
# tests/test_families.py（追加）
def test_campaign_trials_dedupes_same_run_across_families(tmp_path):
    registry.write_family_member(tmp_path, "f1", "shared", {}, campaign_id="c1")
    registry.write_family_member(tmp_path, "f1", "a", {}, campaign_id="c1")
    registry.write_family_member(tmp_path, "f2", "shared", {}, campaign_id="c1")
    assert overfitting.campaign_trials(tmp_path, "c1") == 2
```

- [ ] **Step 2: 跑测试确认失败** → `pytest tests/test_collect_runs.py tests/test_families.py -q`，Expected: FAIL（`search_pool` 不存在 / 计数为 3）。

- [ ] **Step 3: 实现**
  - `search_pool`：先 `{run_id: sharpe}` 收集（同 id 后写覆盖前写，值应相同），再按 id 排序返回 `list(values)`；`n_obs` 仍取全窗口最大。
  - `family_summary` 里 `n_campaign = len(campaign_sharpes)`，不再用成员文件数兜底（仅在池为空时回退 `n_family`）。
  - `campaign_trials`：遍历成员文件，用 `set` 收集 `run_id`。

- [ ] **Step 4: 跑测试确认通过** → 同上命令 PASS。

- [ ] **Step 5: 真实数据对照（不改文件）**

Run: `.venv\Scripts\python.exe scripts\collect_runs.py --campaign tuning-2026-10`
Expected: 输出里 `n_campaign_trials` 从 49 变为 **43**（当前 49 个成员位 = 43 个唯一 run）；`dsr_campaign` 略高于 0.9918。把实际值贴进 Task 12 的输入清单。

- [ ] **Step 6: 提交** `git commit -m "fix(campaign): trial 计数按 run_id 去重"`

---

## Task 2: dirty 证据记录与排除

**Files:**
- Modify: `src/etf_rotation/evaluation/registry.py:356-431`（family json 字段、`load_family` 返回）
- Modify: `src/etf_rotation/evaluation/sweep.py:106-141`（`run_sweep` 增加 `dirty_hash`）
- Modify: `scripts/run_grid.py:106-114`、`scripts/run_grid_hydra.py:106-113`
- Modify: `scripts/collect_runs.py:95-120`（污染 family 不进搜索池）、`family_summary` 输出字段
- Test: `tests/test_families.py`、`tests/test_collect_runs.py`

**Interfaces:**
- Produces: `registry.write_family_member(..., family={"git_dirty": bool, "dirty_hash": str, ...})`，`family.json` 持久化这两个键，已存在时不覆盖。
- Produces: `registry.load_family(...)` 返回新增键 `git_sha, git_dirty, dirty_hash, data_snapshot_id`（缺省 `None/False/""`）。
- Produces: `sweep.run_sweep(..., dirty_hash: str = "")`。
- Produces: `collect_runs.search_pool` 跳过 `family.git_dirty` 为真的 family 以及成员 `meta.git_dirty` 为真的 family。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_families.py（追加）
def test_family_records_dirty_state(tmp_path):
    fid = _fid()
    registry.write_family_member(
        tmp_path, fid, "r0", {}, campaign_id="c1",
        family={"kind": "grid", "spec": {"x": [1]}, "git_dirty": True,
                "dirty_hash": "abc12345"})
    fam = registry.load_family(tmp_path, fid)
    assert fam["git_dirty"] is True and fam["dirty_hash"] == "abc12345"
```

```python
# tests/test_collect_runs.py（追加）
def test_search_pool_skips_dirty_family(tmp_path):
    runs, fams = tmp_path / "runs", tmp_path / "families"
    _run(runs, "dirty1", 0.9)
    registry.write_family_member(fams, "fd", "dirty1", {}, campaign_id="c1",
        family={"kind": "grid", "git_dirty": True, "dirty_hash": "h"})
    _run(runs, "clean1", 0.8)
    registry.write_family_member(fams, "fc", "clean1", {}, campaign_id="c1",
        family={"kind": "grid", "git_dirty": False})
    sharpes, _ = collect_runs.search_pool(fams, runs, "c1")
    assert sharpes == [0.8]
```

- [ ] **Step 2: 跑测试确认失败** → FAIL（`fam["git_dirty"]` KeyError；池里仍有 0.9）。

- [ ] **Step 3: 实现**
  - `write_family_member` 的 `for key in (...)` 元组加入 `git_dirty`、`dirty_hash`，并用 `bool`/`str` 归一。
  - `load_family` 返回值补四项，类型缺省见 Interfaces。
  - `run_sweep` 签名尾追加 `dirty_hash: str = ""`，写进 `family` 字典；`run_grid.py` 传 `dirty_hash=dirty_hash`（已有变量），`run_grid_hydra.py` 传自己的 `dirty_hash`。
  - `search_pool`：`if fam.get("git_dirty"): continue`；再检查 `_read_meta(run_dir).get("git_dirty")`，任一成员为真则跳过该 family。

- [ ] **Step 4: 跑测试确认通过** → `pytest tests/test_families.py tests/test_collect_runs.py -q` PASS。

- [ ] **Step 5: 真实数据预演（不写盘）**

Run: `.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'scripts'); from pathlib import Path; import collect_runs; print(collect_runs.search_pool(Path('reports/families'), Path('reports/runs'), 'tuning-2026-10'))"`
Expected: 仍返回 43 个（旧 family.json 没有 `git_dirty`，所以靠成员 meta 排除 5 个 dirty run → 43 减 5 ≈ 38；记录实际值，Task 10 重建后应等于唯一 clean run 数）。

- [ ] **Step 6: 提交** `git commit -m "feat(evidence): family 记录并排除脏工作区 run"`

---

## Task 3: 派生镜像防串台（守卫 + 原子替换）

**Files:**
- Modify: `src/etf_rotation/evaluation/artifacts.py:246-262`（新增 `latest_run_id`）
- Modify: `src/etf_rotation/report/runner.py:36-133`（`should_mirror`、`mirror_derived`）
- Modify: `scripts/build_report_data.py:27-67`（`--mirror auto|always|never`）
- Test: `tests/test_artifacts.py`、`tests/test_report_runner.py`

**Interfaces:**
- Produces: `artifacts.latest_run_id(root: Path) -> str | None` —— 读 `root.parent/latest.json`；缺失/损坏/无 `run_id` 返回 `None`。
- Produces: `runner.should_mirror(run_id: str, latest_id: str | None, force: bool = False) -> bool` —— 真值表：`force` 为真 → True；`latest_id` 为 None → False；否则 `run_id == latest_id`。
- Produces: `runner.mirror_derived(derived: Path, mirror_to: Path) -> None` —— 先复制到 `mirror_to.parent/f".{mirror_to.name}.tmp-{pid}"`，再删旧目录、`os.replace` 换名。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_runner.py（追加）
from etf_rotation.report import runner

def test_should_mirror_only_for_latest():
    assert runner.should_mirror("r1", "r1") is True
    assert runner.should_mirror("r0", "r1") is False
    assert runner.should_mirror("r0", "r1", force=True) is True
    assert runner.should_mirror("r0", None) is False

def test_mirror_derived_removes_stale_files(tmp_path):
    derived = tmp_path / "run" / "derived"
    mirror = tmp_path / "derived"
    derived.mkdir(parents=True)
    mirror.mkdir()
    (derived / "index.json").write_text("{}", encoding="utf-8")
    (mirror / "old_step.json").write_text("{}", encoding="utf-8")
    runner.mirror_derived(derived, mirror)
    assert (mirror / "index.json").exists()
    assert not (mirror / "old_step.json").exists()
```

```python
# tests/test_artifacts.py（追加）
def test_latest_run_id_reads_and_tolerates_bad_json(tmp_path):
    (tmp_path / "latest.json").write_text('{"run_id": "abc"}', encoding="utf-8")
    assert artifacts.latest_run_id(tmp_path / "runs") == "abc"
    (tmp_path / "latest.json").write_text("not-json", encoding="utf-8")
    assert artifacts.latest_run_id(tmp_path / "runs") is None
```

- [ ] **Step 2: 跑测试确认失败** → FAIL（函数不存在）。

- [ ] **Step 3: 实现**
  - `artifacts.latest_run_id`：`root = Path(root)`，路径 `root.parent / "latest.json"`；`try json.loads ... except (OSError, ValueError): return None`。
  - `runner.should_mirror` / `runner.mirror_derived` 按 Interfaces；`mirror_derived` 不保留旧文件。
  - `runner.run(..., mirror_to=...)` 内部改调 `mirror_derived`（签名不变）。
  - `build_report_data.py`：`--mirror {auto,always,never}` 默认 `auto`；`latest = artifacts.latest_run_id(RUNS_DIR)`；`do_mirror = should_mirror(run_dir.name, latest, force=args.mirror=="always") and args.mirror!="never"`；打印一行 `mirror: 更新/跳过（原因）`。

- [ ] **Step 4: 跑测试确认通过** → `pytest tests/test_report_runner.py tests/test_artifacts.py -q` PASS。

- [ ] **Step 5: 真实验证（只读）**

Run: `.venv\Scripts\python.exe scripts\build_report_data.py --run-id 5d5a64c88b30 --only alignment`
Expected: `reports/derived/index.json` 的 `run_id` 仍是 `e925fa0ee0d5`（mirror 被跳过）；该旧 run 的 `derived/alignment.json` 正常生成。

- [ ] **Step 6: 提交** `git commit -m "fix(report): 派生镜像只跟随 latest 并原子替换"`

---

## Task 4: verify 扩展（mirror / family / analysis 身份）

**Files:**
- Modify: `src/etf_rotation/evaluation/verify.py`（新增三个函数）
- Modify: `scripts/verify_artifacts.py:21-43`（调用新函数与参数）
- Test: `tests/test_verify_artifacts.py`

**Interfaces:**
- Produces: `verify.verify_reports(reports_dir: Path) -> list[str]` —— 检查 `latest.json` 可解析、`derived/index.json.run_id == latest`、mirror 与 `runs/{latest}/derived` 文件集合与 sha256 完全一致、`runs/{latest}/analysis/*.json`（若存在）内含 `run_id == latest`。
- Produces: `verify.verify_families(families_root: Path, runs_root: Path, campaign_id: str | None = None) -> list[str]` —— 成员 run 目录与 `meta.parquet` 存在；成员的 `git_sha/data_snapshot_id/execution` 与 `family.json` 一致；member/file 数与 `load_family` 一致；`family.git_dirty` 或成员 `git_dirty` 为真时输出 `WARN` 行（以 `'WARN '` 前缀，不算失败）。
- Produces: `verify.has_errors(problems: list[str]) -> bool` —— 过滤掉 `WARN ` 前缀后判断是否有真错误（CLI 用它决定退出码）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_verify_artifacts.py（追加）
def test_verify_reports_detects_stale_mirror(tmp_path):
    p = _store(tmp_path)
    (tmp_path / "latest.json").write_text('{"run_id": "r1"}', encoding="utf-8")
    _write_index(p, _artifact_hashes(p), run_id="r1")
    mirror = tmp_path / "derived"
    mirror.mkdir()
    (mirror / "index.json").write_text((p / "derived/index.json").read_text(encoding="utf-8"))
    assert verify.verify_reports(tmp_path) == []
    (mirror / "stale_step.json").write_text("{}", encoding="utf-8")
    assert any("mirror" in msg for msg in verify.verify_reports(tmp_path))


def test_verify_families_flags_missing_member_run(tmp_path):
    from etf_rotation.evaluation import registry
    registry.write_family_member(tmp_path / "families", "f1", "gone", {}, campaign_id="c1")
    problems = verify.verify_families(tmp_path / "families", tmp_path / "runs")
    assert any("gone" in msg for msg in problems)
```

- [ ] **Step 2: 跑测试确认失败** → FAIL（`verify_reports` 不存在）。

- [ ] **Step 3: 实现**
  - `verify_reports`：先读 latest；mirror 文件集合用 `{p.name for p in dir.iterdir() if p.is_file()}` 比较；逐文件 sha256 比对（复用 `_sha256`）；analysis 只检查含 `run_id` 的文件。
  - `verify_families`：`registry.load_family` 逐个；成员 run meta 字段比对，不一致写 `WARN`（避免旧 family 立刻让 CI 红）；缺目录/缺 meta 写错误。
  - `verify_artifacts.py`：新增 `--families-root`、`--reports-dir`、`--campaign`；依次合并三组结果，`has_errors` 为真才 `sys.exit(1)`。

- [ ] **Step 4: 跑测试确认通过** → `pytest tests/test_verify_artifacts.py -q` PASS。

- [ ] **Step 5: 真实数据预演**

Run: `.venv\Scripts\python.exe scripts/verify_artifacts.py`
Expected: 出现若干 `WARN`（5 个 dirty 成员、25 个 NaN 首行旧 run）；**不出现** mirror 错误；退出码 0。把 WARN 数量记进 Task 10 的门禁。

- [ ] **Step 6: 提交** `git commit -m "feat(verify): 校验镜像、family 与 analysis 身份"`

---

## Task 5: derived 契约（performance 加 summary）+ 增量版本判断

**Files:**
- Modify: `src/etf_rotation/report/steps/performance.py:159-172`
- Modify: `src/etf_rotation/report/runner.py:36`（`DERIVED_VERSION`）、`runner.py:147`（`_same_run`）
- Modify: `src/etf_rotation/evaluation/verify.py`（`_check_derived` 增加 metrics 对账）
- Test: `tests/test_report_performance.py`、`tests/test_report_runner.py`、`tests/test_verify_artifacts.py`

**Interfaces:**
- Produces: `performance.build(ctx)` 顶层新增 `"summary": {"max_drawdown": float, "n_days": int}`；`max_drawdown` 用 `underwater(nav).min()`（负数，与 `metrics["max_drawdown"]` 同号同量级）。
- Produces: `runner.DERIVED_VERSION = 2`；`runner._same_run(index, run_id, inputs)` 额外要求 `index["derived_version"] == DERIVED_VERSION`。
- Produces: `verify` 读 `derived/performance.json` 的 `summary.max_drawdown`，与 `metrics["max_drawdown"]` 绝对误差 `> 1e-6` 时报错。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_report_performance.py（追加）
def test_build_reports_max_drawdown_summary():
    ctx = _ctx()          # 复用文件内已有 helper；若无则用 5 日 nav 构造
    out = performance.build(ctx)
    assert out["summary"]["max_drawdown"] == pytest.approx(-0.181818, abs=1e-6)
```

```python
# tests/test_report_runner.py（追加）
def test_only_does_not_carry_old_derived_version(tmp_path):
    ...  # 写一份 derived/index.json（derived_version=1，inputs 与当前一致）
    ...  # runner.run(..., only=["alignment"]) 后，非 alignment 的旧 step 文件不得继承
    assert not (tmp_path / "derived" / "old_step.json").exists()
```

```python
# tests/test_verify_artifacts.py（追加）
def test_verify_flags_derived_max_drawdown_mismatch(tmp_path):
    p = _store(tmp_path)
    _write_index(p, _artifact_hashes(p))
    (p / "derived/performance.json").write_text(
        '{"summary": {"max_drawdown": -0.5, "n_days": 6}}', encoding="utf-8")
    # 在 metrics 里补 max_drawdown 供对账
    ...
    assert any("max_drawdown" in msg for msg in verify.verify(tmp_path / "runs", "r1"))
```

- [ ] **Step 2: 跑测试确认失败** → FAIL（KeyError `summary` / 旧 step 被继承 / 无对账）。

- [ ] **Step 3: 实现**
  - `performance.build` 返回字典加 `summary`。
  - `DERIVED_VERSION = 2`；`_same_run` 比较 `derived_version`。
  - `verify` 新增 `_check_derived_performance`：文件缺失时跳过（`--only` 未跑 performance 属合法），存在时比对；`metrics` 缺 `max_drawdown` 时跳过。

- [ ] **Step 4: 跑测试确认通过** → 三个测试文件 PASS。

- [ ] **Step 5: 真实数据（旧 run 上验证不破坏）**

Run: `.venv\Scripts\python.exe scripts\build_report_data.py --latest --only performance`
Expected: `reports/derived/performance.json` 出现 `summary.max_drawdown == -0.157884334824393`（与 metrics 一致）；`verify_artifacts` 不新增错误。

- [ ] **Step 6: 提交** `git commit -m "feat(report): performance 契约补充最大回撤并对账"`

---

## Task 6: 同一个 run_id 的并发写锁

**Files:**
- Modify: `src/etf_rotation/evaluation/artifacts.py:185-243`（`store_run`）
- Test: `tests/test_artifacts.py`

**Interfaces:**
- Produces: `artifacts._run_lock(path: Path, timeout: float = 30.0)` —— `contextlib.contextmanager`；`os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY)` 建锁并写 pid；`FileExistsError` 时每 0.05 s 重试，超过 `timeout` 抛 `TimeoutError`；锁文件 mtime 超过 600 s 视为残留并删除；退出时 `unlink(missing_ok=True)`。
- Produces: `store_run` 在「判断 final 是否存在 → rename / merge」整段外面持锁；锁路径 `root/.staging/{run_id}.lock`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_artifacts.py（追加）
def test_concurrent_same_run_id_is_serialized(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    def call():
        return _store(tmp_path, "standard")

    with ThreadPoolExecutor(max_workers=2) as pool:
        paths = list(pool.map(lambda _: call(), range(2)))
    assert len({p for p in paths}) == 1
    assert (tmp_path / "r1" / "attempts.jsonl").read_text(encoding="utf-8").count("\n") == 2
    assert not list((tmp_path / ".staging").glob("*.lock"))
```

- [ ] **Step 2: 跑测试确认失败** → FAIL（断言 2 行常为 1 行，或 rename 抛 `FileExistsError`）。

- [ ] **Step 3: 实现**
  - `_run_lock` 用 `time.monotonic()` 控制超时；Windows 上 `os.open` 对已存在文件抛 `FileExistsError`，行为一致。
  - `store_run` 把 `if not final.exists(): rename else: merge` 包进 `with _run_lock(root / ".staging" / f"{run_id}.lock")`；`staging` 的创建与 `write_frames` 放在锁外（不同进程各写各的 `.staging/{run_id}` 会互删，所以**实际应把整个函数体放进锁内**——按此实现，锁覆盖 `staging.rmtree` 到 rename/merge 结束）。
  - 异常路径确保 `finally` 清锁与暂存目录。

- [ ] **Step 4: 跑测试确认通过** → `pytest tests/test_artifacts.py -q` PASS（含原有 4 个用例）。

- [ ] **Step 5: 提交** `git commit -m "fix(artifacts): 同一 run_id 的写入串行化"`

---

## Task 7: `reports/index.md` 全局索引

**Files:**
- Modify: `scripts/collect_runs.py`（新增三个函数 + `main` 写文件）
- Test: `tests/test_collect_runs.py`

**Interfaces:**
- Produces: `collect_runs.index_rows(families_root: Path, runs_root: Path, campaign_id: str | None = None) -> list[dict]` —— 每 family 一行：`family_id, kind, campaign_id, n_trials, n_campaign_trials, dsr_family, dsr_campaign, best_sharpe, git_dirty, missing_members`。
- Produces: `collect_runs.render_index(rows: list[dict], generated_at: str) -> str` —— Markdown：标题 + 一句口径说明 + 表格 + `missing_members` 明细清单（无则 "无"）。
- Produces: `collect_runs.write_index(families_root: Path, runs_root: Path, path: Path, campaign_id: str | None = None) -> Path`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_collect_runs.py（追加）
def test_render_index_lists_families_and_missing(tmp_path):
    rows = [{"family_id": "f1", "kind": "grid", "campaign_id": "c1",
             "n_trials": 3, "n_campaign_trials": 43, "dsr_family": 0.99,
             "dsr_campaign": 0.98, "best_sharpe": 1.0, "git_dirty": False,
             "missing_members": []},
            {"family_id": "f2", "kind": "cost", "campaign_id": "c1",
             "n_trials": 4, "n_campaign_trials": 43, "dsr_family": None,
             "dsr_campaign": None, "best_sharpe": 0.9, "git_dirty": True,
             "missing_members": ["gone"]}]
    text = collect_runs.render_index(rows, "2026-10-25T00:00:00+00:00")
    assert "| family_id |" in text and "f1" in text and "f2" in text
    assert "43" in text and "gone" in text and "dirty" in text.lower()
```

- [ ] **Step 2: 跑测试确认失败** → FAIL（`render_index` 不存在）。

- [ ] **Step 3: 实现**
  - `index_rows` 复用 Task 1 的 `search_pool` 与 `family_summary` 的字段；`missing_members` 用 `[m["run_id"] for m in fam["members"] if not (runs_root/m["run_id"]/"meta.parquet").exists()]`。
  - `render_index`：表格列固定顺序；`None` 显示 `—`；`git_dirty` 显示 `⚠ dirty`。
  - `main`：所有 summary 写完后调用 `write_index(..., ROOT/"reports"/"index.md")`；新增 `--no-index` 与 `--index-path`。

- [ ] **Step 4: 跑测试确认通过** → PASS。

- [ ] **Step 5: 真实验证**

Run: `.venv\Scripts\python.exe scripts\collect_runs.py --campaign tuning-2026-10`
Expected: `reports/index.md` 生成；14 行 family；`n_campaign_trials` 为 Task 1 的 43（或 Task 2 的 clean 数）；末尾 `missing_members: 无`。

- [ ] **Step 6: 提交** `git commit -m "feat(campaign): 生成 reports/index.md 全局索引"`

---

## Task 8: 成本敏感性绑定到 run/family

**Files:**
- Modify: `scripts/collect_runs.py`（新增 `latest_family`、`cost_rows`）
- Modify: `scripts/run_report.py:74-79`（读 family；fallback 才读顶层）
- Test: `tests/test_collect_runs.py`

**Interfaces:**
- Produces: `collect_runs.latest_family(families_root: Path, kind: str) -> str | None` —— 按 `family.json.created_at` 取最新一个 kind 匹配的 family。
- Produces: `collect_runs.cost_rows(families_root: Path, runs_root: Path, family_id: str) -> list[dict]` —— 读 members 的 variant 与 metrics，返回按 `costs.one_side_bps` 升序的 `[{one_side_bps, sharpe, ann_return, max_drawdown, calmar, total_fees, run_id}]`。
- Produces: `run_report.py --sensitivity-family <fid>`；默认 `latest_family(..., "cost")`；找不到时回退顶层 `reports/sensitivity.json` 并打印 `WARNING 成本敏感性来自顶层 campaign 文件（未绑定 run）`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_collect_runs.py（追加）
def test_cost_rows_reads_family_members_sorted(tmp_path):
    runs, fams = tmp_path / "runs", tmp_path / "families"
    _run(runs, "c16", 0.5); _run(runs, "c0", 1.0)
    registry.write_family_member(fams, "fc", "c16", {"costs.one_side_bps": 16},
                                 campaign_id="c1", family={"kind": "cost"})
    registry.write_family_member(fams, "fc", "c0", {"costs.one_side_bps": 0},
                                 campaign_id="c1", family={"kind": "cost"})
    rows = collect_runs.cost_rows(fams, runs, "fc")
    assert [r["one_side_bps"] for r in rows] == [0, 16]
    assert collect_runs.latest_family(fams, "cost") == "fc"
```

- [ ] **Step 2: 跑测试确认失败** → FAIL。

- [ ] **Step 3: 实现** 按 Interfaces；`run_report.py` 用 `cost_rows` 构造 `sens_df`，列名映射到它当前需要的字段；`--sensitivity-family` 显式优先。

- [ ] **Step 4: 跑测试确认通过** → PASS。

- [ ] **Step 5: 真实验证**

Run: `.venv\Scripts\python.exe scripts/run_report.py --run-id e925fa0ee0d5 --sensitivity-family 669941891d87`
Expected: 报告成本章节数值与 `reports/调参记录.md` 的 0/8/16/24bp 表一致；不再读顶层文件。

- [ ] **Step 6: 提交** `git commit -m "fix(report): 成本敏感性从成本 family 读取"`

---

## Task 9: 网格契约对齐（默认档位 + benchmark）

**Files:**
- Modify: `scripts/run_grid.py:46-47,98-104`
- Modify: `scripts/run_grid_hydra.py:98-105,123`
- Modify: `docs/superpowers/plans/2026-10-24-etf-rotation-persistence-and-report-data.md`（仅在保留 minimal 时记录偏离）

**Interfaces:**
- 默认 `--save-profile standard`；`frames` 追加 `"benchmark": bench`，`bench` 在循环外算一次（`compute_benchmark(base, start, end)`）。
- 保留 `minimal` 显式可选；`--save-profile` 帮助文本注明"网格默认 standard，只为数值扫描时可显式 minimal"。

- [ ] **Step 1: 决定并写下来（G2）**：默认 standard（推荐）。若选 minimal，本 Task 只改文档，不改代码。

- [ ] **Step 2: 真实验证（小网格）**

Run: `.venv\Scripts\python.exe scripts\run_grid.py --grid defensive.max_vol_60d=0.03,0.04 --campaign audit-smoke --save-profile standard`
Expected: 打印 family_id；`reports/runs/{id}/benchmark.parquet` 存在；`meta.save_profile == "standard"`；`reports/latest.json` 未被改写。

- [ ] **Step 3: 清理冒烟产物**（`reports/runs/{2 个 id}`、`reports/families/{fid}`、对应 members；不要动 campaign `tuning-2026-10`）。

- [ ] **Step 4: 提交** `git commit -m "feat(grid): 网格默认 standard 档并落 benchmark"`

---

## Task 10: 证据重建（干净 HEAD 全量 campaign + 基线）

**Gate：** G1 已确认；Task 1–9 已合并到同一 commit，`git status` 干净，`pytest tests -q` 全绿。

**Files:**
- Move: `reports/runs/*`（除 `.staging`）→ `reports/legacy/pre-remediation/runs/`
- Move: `reports/families/*` → `reports/legacy/pre-remediation/families/`
- Create: `reports/legacy/pre-remediation/README.md`（旧 id 清单、原因、日期）
- Modify: `reports/legacy/README.md`（追加一行）

- [ ] **Step 1: 归档旧证据**

```powershell
$env:PYTHONIOENCODING="utf-8"
$dst = "reports\legacy\pre-remediation"
New-Item -ItemType Directory -Force "$dst\runs","$dst\families" | Out-Null
Get-ChildItem reports\runs -Directory | Where-Object { $_.Name -ne '.staging' } | Move-Item -Destination "$dst\runs"
Get-ChildItem reports\families -Directory | Move-Item -Destination "$dst\families"
Get-ChildItem "$dst\runs" -Directory | Select-Object -ExpandProperty Name | Set-Content "$dst\old-run-ids.txt"
Get-ChildItem "$dst\families" -Directory | Select-Object -ExpandProperty Name | Set-Content "$dst\old-family-ids.txt"
```

- [ ] **Step 2: 单维度重跑（一个维度一个 family，值域必须含默认值）**

```powershell
$dims = @(
 "dedupe.corr_threshold=0.75,0.80,0.85",
 "trend.windows=[[15,60],[21,60],[30,90]]",
 "dedupe.max_holdings=5,8,10",
 "market_state.bull_threshold=0.15,0.20,0.25,0.30,0.35",
 "market_state.alpha=0.05,0.10,0.15",
 "risk.vol_target_risk=0.15,0.20,0.22,0.25,0.26,0.30",
 "defensive.top_n=1,2,3,5",
 "defensive.max_vol_60d=0.02,0.03,0.04")
foreach ($d in $dims) { .venv\Scripts\python.exe scripts\run_grid.py --grid $d --campaign tuning-2026-10 --save-profile standard }
```

- [ ] **Step 3: 消融 / 假设 / 成本 / OOS**

```powershell
.venv\Scripts\python.exe scripts\run_mechanism_ablation.py --campaign tuning-2026-10 --save-profile standard
.venv\Scripts\python.exe scripts\run_assumption_sensitivity.py --campaign tuning-2026-10 --save-profile standard
.venv\Scripts\python.exe scripts\run_sensitivity.py --campaign tuning-2026-10 --save-profile minimal
.venv\Scripts\python.exe scripts\run_oos_check.py --campaign tuning-2026-10 --save-profile standard
```

- [ ] **Step 4: 汇总 + 基线 + 派生 + 报告**

```powershell
.venv\Scripts\python.exe scripts\collect_runs.py --campaign tuning-2026-10
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
.venv\Scripts\python.exe scripts\build_report_data.py --latest
.venv\Scripts\python.exe scripts\run_report.py
.venv\Scripts\python.exe scripts\verify_artifacts.py
```

- [ ] **Step 5: 验收（全部必须成立）**
  - 新基线 `run_id` 与 `reports/latest.json` 一致；`signals/stages.parquet` 存在。
  - `derived/index.json` 10 个 step 全 `ok`，`peak_lag == 0`。
  - `reports/runs/{new}` 的 `nav` 与 `reports/legacy/v1.1.1/equity.csv` **差值 0.0**。
  - 新基线 `metrics.parquet` 的 `ann_return/sharpe/max_drawdown/calmar/total_fees` 与 `e925fa0ee0d5` 逐项相对误差 `< 1e-9`。
  - `verify_artifacts.py` 无 `ERROR`（允许 0 条 WARN；若有 WARN，逐条记录原因）。
  - campaign 的 `n_campaign_trials` = unique run 数；与 `reports/index.md` 一致。

- [ ] **Step 6: 记录新 id 清单**（写进 `reports/legacy/pre-remediation/README.md` 与 Task 12 的输入变量：`NEW_BASE_ID`、`NEW_CAMPAIGN_TRIALS`、`NEW_DSR`、每个 family 的 id）。

- [ ] **Step 7: 提交**（只提交 legacy README 与清单）`git commit -m "chore(evidence): 干净代码重跑 campaign 并归档旧 run"`

---

## Task 11: 尾巴验收（heatmap / prune / 确定性）

**Files:** 无代码改动（Prune 若发现 bug 回 Task 4/6 修）。

- [ ] **Step 1: heatmap 重跑**

```powershell
.venv\Scripts\python.exe scripts\run_heatmap.py --grid dedupe.corr_threshold=0.75,0.80,0.85 --grid costs.one_side_bps=0,8,16,24 --campaign tuning-2026-10 --save-profile standard
```
Expected: `reports/families/{fid}/results.json` 存在（12 行）；`reports/heatmap_*.html` 新时间戳；`verify_artifacts` 仍 0 ERROR。

- [ ] **Step 2: prune 真跑（复制，不跑新回测）**

```powershell
$env:PYTHONIOENCODING="utf-8"
$src = (Get-Content reports\latest.json -Raw | ConvertFrom-Json).run_id
Copy-Item "reports\runs\$src" "reports\runs\prune-test" -Recurse
.venv\Scripts\python.exe -c "import pandas as pd; p='reports/runs/prune-test/meta.parquet'; d=pd.read_parquet(p); d.loc[0,'created_at']='2026-01-01T00:00:00+00:00'; d.loc[0,'save_profile']='standard'; d.to_parquet(p, compression='zstd', index=False)"
.venv\Scripts\python.exe scripts\prune_runs.py --dry-run
.venv\Scripts\python.exe scripts\prune_runs.py --execute
.venv\Scripts\python.exe scripts\verify_artifacts.py --run-id prune-test
Remove-Item reports\runs\prune-test -Recurse -Force
```
Expected: dry-run 列出 `prune-test`；执行后 `equity/holdings` 删除、`weights/meta/metrics/artifacts/manifest` 保留、`meta.pruned=TRUE`；`verify` 无输出；删除后 `reports/runs` 数量回到基线。

- [ ] **Step 3: 确定性两跑**

```powershell
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
```
Expected: 两次打印**同一个 run_id**；第二次不抛 `ArtifactConflictError`；`attempts.jsonl` 追加第 2 行（`action=upgraded`）。把两条输出贴进 Task 12。

- [ ] **Step 4: 决定 G3 并清理**

```powershell
git status --porcelain
```
Expected: 处理两个 `2026-10-25-*frontend*.md`（提交或加入 `.gitignore`）；删除 `reports/metrics.baseline.json`、`reports/weights.baseline.parquet`；`git status` 只剩预期的文档改动。

---

## Task 12: 文档收口

**Files:**
- Modify: `AGENTS.md`（新增「持久化与证据链」小节：trial 去重、dirty 证据、镜像只跟随 latest、`Get-Content -Encoding UTF8`）
- Modify: `TODO.md`（勾掉已完成；新增：前端渲染、H1/H7 裁决、`hash_files` 相对路径、frontend spec 去留）
- Modify: `docs/superpowers/plans/2026-10-24-etf-rotation-persistence-and-report-data.md`（勾选已完成 Task；文末追加 §10「审计整改结果」：新 run id、新 DSR、Task 10 归档位置）
- Modify: `docs/superpowers/plans/2026-10-24-etf-rotation-report-derived-data.md`（首行加 `> **SUPERSEDED**：见 2026-10-24-...persistence-and-report-data.md`）
- Modify: `reports/调参记录.md`（全部 22 处旧 run id → 新 id；`49` → 新唯一数；DSR 数字以 `summary.json` 为准；末尾追加「2026-10-25 审计后重建」说明）
- Modify: `reports/回测报告.md`（基线 run id；「参数调优（阶段二）」整节改为 campaign 口径，删除 DSR 0.54~0.55 的旧结论或标注废弃）
- Modify: `reports/差距归因.md`（补 `run_id` 表；DSR 三个口径并列说明：0.54 旧伪影 / 0.9934 单 family 18 变体 / 新 campaign 值）
- Modify: `CHANGELOG.md`（新增审计整改条目；把 249 改 251）

- [ ] **Step 1: 用脚本生成新 id 清单，禁止手抄**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe -c "import json,pandas as pd; from pathlib import Path; f=json.load(open('reports/latest.json',encoding='utf-8')); print(f['run_id']); print(open('reports/index.md',encoding='utf-8').read())"
```
Expected: 拿到 `NEW_BASE_ID` 与每个 family 的 id/DSR；后续 markdown 编辑只从这份输出复制。

- [ ] **Step 2: 逐文件改并对照**
  - 每个新 id 必须在 `reports/runs/{id}/meta.parquet` 存在；用 `grep -o "[0-9a-f]\{12\}" reports/*.md` 检查没有残留旧 id（旧 id 允许出现在「已归档」段落且带 `pre-remediation` 前缀）。
  - `AGENTS.md` 的坑位写「规则 + 症状 + 对应修复 commit」，不写故事。

- [ ] **Step 3: 自检**

Run: `.venv\Scripts\python.exe scripts\verify_artifacts.py` → 无 ERROR。
Run: `git status --porcelain` → 只有文档改动。
Run: `.venv\Scripts\python.exe -m pytest tests -q` → 全 PASS。

- [ ] **Step 4: 提交** `git commit -m "docs: 审计整改结果与口径收口"`

---

## Task 13: 最终验收

**Files:** 无（只跑命令、记录输出）。

- [ ] **Step 1: 全量回归**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe scripts\verify_artifacts.py
.venv\Scripts\python.exe scripts\collect_runs.py --campaign tuning-2026-10
.venv\Scripts\python.exe scripts\build_report_data.py --latest
.venv\Scripts\python.exe scripts\run_report.py
.venv\Scripts\python.exe scripts\verify_artifacts.py
```
Expected: 测试全 PASS；两次 verify 均无 ERROR；`build_report_data` 的 10 个 step 全 `ok`；`reports/index.md` 与 `latest` 一致。

- [ ] **Step 2: 七项审计指标逐条打勾**

| 指标 | 通过条件 |
|---|---|
| trial 计数 | `n_campaign_trials` == unique run 数（`load_runs` 计数） |
| 证据纯度 | `search_pool` 排除后 == `load_runs(kind in search).git_dirty==False` 的 unique 数 |
| 镜像身份 | `derived/index.json.run_id == latest.run_id`，mirror 文件集合与 sha 全等 |
| 基线一致 | 新基线 nav 与 `legacy/v1.1.1/equity.csv` diff == 0 |
| dirty | 新 campaign 0 个 `git_dirty=TRUE` |
| 旧 run | `reports/runs` 只剩新 campaign；旧 id 仅在 `legacy/pre-remediation/` |
| 计划 | 2026-10-24 计划勾选与 §10 记录一致 |

- [ ] **Step 3: 若有失败** → 回到所属 Task 修（不在 main 上直接改数字）；修完重跑本 Task。

---

## 不做（Out of scope）

- 采纳 H1 `trend.weighting=exp` / H7 `nasdaq_exit_threshold=-0.05`：会改变策略数值，属独立决策与独立计划。
- 报告前端渲染层（spec C0–C11、74 项图表）。
- `snapshot.hash_files` 改为相对路径排序：会改变 `data_snapshot_id`，使全部现有身份失效；单独立项，先补 `snapshot_version` 再迁移。
- 修改 `pipeline.py` / 回测引擎 / 参数默认值。
- 逐个重跑 28 个旧 run 来消除 NaN 首行：Task 10 的全量重建已覆盖，旧 run 只归档不修。

## Self-Review

- **Spec 覆盖**：审计 P0（trial 去重 → Task 1；dirty → 2；镜像 → 3；报告输入 → 8）、P1（verify → 4；确定性 → 11；写锁 → 6；网格契约 → 9）、计划尾巴（index → 7；heatmap/prune → 11；performance → 5）、文档（→ 12）均有对应 Task。
- **类型一致性**：`search_pool` / `cost_rows` / `index_rows` / `should_mirror` / `mirror_derived` / `latest_run_id` / `verify_reports` / `verify_families` / `_run_lock` 在 Task 1–8 中命名与签名一致；`DERIVED_VERSION=2` 只在 Task 5 定义、Task 4 的 verify 依赖其产物。
- **Review Focus 落点**：run_id 一致性 → Task 10 Step 5 + Task 12 Step 2；派生串台 → Task 3/4；证据纯度 → Task 1/2 + Task 13 表；不可逆 → Task 10 Step 1+6；并发 → Task 6。
- **比例**：Task 1–9 为代码与测试（约 12 h），Task 10–11 为运维（3.5 h），Task 12 为文档（3 h），与审计结论的 20 h 量级一致。
