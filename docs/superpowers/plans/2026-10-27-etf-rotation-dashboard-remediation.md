# 看板审计整改 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 2026-10-27 第三方审计发现的 3 条 P1、2 条 P2、1 条 P3 收口，让 `reports/dashboard.html` 的页面文案与载荷一致，让派生目录与顶层 JSON 都绑到同一个 `run_id`，让看板契约测试在干净 clone 里也能真跑。

**Architecture:** 先修「读错数据」的底层护栏（派生目录归属校验），再修读者可见的文案（三处旧批次、T10 脚注、六份文档的三元组），再补产物身份（顶层 JSON 加 run 绑定与校验），然后把契约测试从「依赖真实 run 就跳过」换成「自带合成夹具」，最后修体积自证的单位错误并整体验收。所有文案由载荷驱动，不再在模板里写死数字。

**Tech Stack:** Python 3.10、pandas、pyarrow、pytest、Plotly 2.35.2（已内联）、原生 JS（无构建步骤）、无头 Chrome（渲染断言）。不新增依赖。

**Spec:** `docs/superpowers/audits/2026-10-27-etf-rotation-dashboard-audit.md`（213 行，基线 commit `e2c21ae`）。本计划只修该审计点名的条目，不改策略决策、不改回测引擎、不改 `config/params.yaml`。

## Global Constraints

- 环境：`.venv\Scripts\python.exe`；跑任何 Python 前 `$env:PYTHONIOENCODING="utf-8"`；PowerShell 读中文文件一律 `-Encoding UTF8`。
- 中文文档按 `.opencode/skills/zh-plain`：先结论、一句一事、主动语态、不用破折号和分号。
- 不改策略决策、不改回测引擎、不改 `pipeline.py` 与 `config/params.yaml`。基线净值必须零变化。
- 不新增依赖。JSON 必须能通过 `json.dumps(..., allow_nan=False)`。
- **键数纪律：** 本计划不新增也不删除载荷的顶层键。若 `2026-10-27-dashboard-ticker-names.md` 先落地（48 键变 49 键），断言改成「键数与本计划开工时相同」，不写字面 48。
- **串行纪律：** 本计划与 `2026-10-27-dashboard-ticker-names.md` 同时改 `reports/front-design/index.html`、`tests/test_dashboard_data.py`、`scripts/build_dashboard.py`，两份计划必须串行执行，不可并行。当前工作区已有该计划的未提交改动（`src/etf_rotation/data/universe.py`、`tests/test_dashboard_names.py`），开工前先确认它已提交或已 stash。
- **产物不入 git：** `reports/dashboard.html` 与 `reports/derived/` 仍被 `.gitignore` 忽略。只有 `reports/*.md`、`reports/front-design/*`、`tests/fixtures/**` 可提交。
- **不钉产物哈希：** `reports/dashboard.html` 现在是 15,663,630 字节，sha256 `933b118ce798b4bb5cc1571cd8c80375dff74afcba647fa11783a350c4bce775`。本次会改页面文案，哈希必然变，验收只断言文本与体积区间，不钉哈希值。
- 一个 Task 一个 commit。每个 Task 结束跑该 Task 的测试文件，Task 7 跑全量。
- 长任务用受管后台或前台分块。单次命令超过 10 分钟就拆。
- 读 `data/warehouse.duckdb` 必须 `read_only=True`。`.env` 的 tushare token 不得打印、提交、写日志。

## Review Focus

1. **`RuntimeError` 的面相：** Task 1 让 57 个没有自带 `derived/` 的 run 立刻报错。报错文案必须同时说清「哪个 run」「缺哪个目录」「跑哪条命令修」，否则读者会以为是代码坏了。这是本次唯一会让既有用法变红的改动。
2. **文案必须由载荷算出，不能再写死数字：** Task 2 与 Task 3 允许改模板，但禁止把 `1.039`、`0.877`、`2026-10-17`、`2.05` 这类数字换个地方写死。数字只能来自 `D.sweeps`、`D.meta`、`D.kpi`、`D.gap`。
3. **`grid2d.note` 已经是对的：** 审计确认 `dashboard.py` 早就生成了正确文案，只是渲染函数 `B.grid2d` 不读它。修法是让渲染读数据，不是新造一份文案。
4. **夹具必须小且能重建：** 合成 run 入库前逐目录看一眼体积。任何单个文件超过 200 KB 就是生成策略错了。生成器必须入库，别人能一条命令重造。
5. **顶层 JSON 加字段不能改数值：** Task 4 只加身份字段。改完必须逐字段比对旧值与新值，数值有任何变化就是写错了。
6. **`verify_reports` 的新检查不能误伤：** 新检查只针对 `attribution.json`、`exposure.json`、`data_quality.json` 三个文件。其它 `reports/*.json`（`ablation.json`、`oos_check.json`、`assumption_sensitivity.json`、`sensitivity_summary.json` 等）本次不加要求，因为它们的写盘脚本不在范围内。

## 任务与依赖

| 阶段 | Task | 预估 | 依赖 | 对应审计项 |
|---|---|---|---|---|
| 护栏 | 1 派生目录归属校验 | 1.5 h | 无 | P1-3 |
| 文案 | 2 三处旧批次改为载荷驱动 | 2.5 h | 1 | P1-1 |
| 文案 | 3 T10 脚注与六份文档三元组 | 1.5 h | 2 | P1-2 |
| 身份 | 4 顶层 JSON 加 run 绑定与校验 | 2.5 h | 1 | P2-1 |
| 测试 | 5 合成 run 夹具与 hermetic 契约测试 | 3.5 h | 1、4 | P2-2 |
| 体积 | 6 体积自证改字节并加恒等式 | 1.0 h | 无 | P3-1 |
| 收口 | 7 全量验收与文档回填 | 1.5 h | 全部 | 全部 |

合计约 14 h，串行执行 2 个工作日。

---

## Task 1: 派生目录归属校验

**Files:**
- Modify: `src/etf_rotation/report/dashboard.py:157-165`（`__init__`）
- Modify: `src/etf_rotation/report/dashboard.py:234-240`（`derived_json` / `report_json` 的报错文案）
- Create: `tests/test_dashboard_derived_binding.py`

**Interfaces:**
- Produces: `DashboardBuilder._resolve_derived() -> Path`。校验顺序固定：先看 `run_dir/derived`，缺则看 `reports/derived`，两者都不合格就抛 `RuntimeError`。
- Produces: `DashboardBuilder._check_derived_owner(path: Path) -> None`。读 `index.json`，要求 `derived_version == runner.DERIVED_VERSION` 且 `run_id == run_dir.name`，否则抛 `RuntimeError`。
- 行为变化：`DashboardBuilder(ctx, reports/runs/57ad104114db, reports)` 从「读到 4b303fe538c2 的派生数据」变成「构造时立刻抛 `RuntimeError`」。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_dashboard_derived_binding.py
"""派生目录归属校验：不许静默读到别的 run 的派生数据。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from etf_rotation.report.dashboard import DashboardBuilder


def _fake_run(root: Path, run_id: str, *, derived_run_id: str | None = None,
              derived_version: int = 2, own_derived: bool = True) -> Path:
    """造一个最小 run 目录。own_derived=False 时不写 run 自己的 derived/。"""
    run = root / "runs" / run_id
    run.mkdir(parents=True)
    pd.DataFrame([{
        "schema_version": 2, "run_id": run_id, "git_sha": "deadbee",
        "data_snapshot_id": "abc", "execution": "open", "version": "1.1.1",
        "signal_id": "s1", "created_at": "2026-10-25T00:00:00+00:00",
        "params_json": "{}",
    }]).to_parquet(run / "meta.parquet")
    pd.DataFrame({"metric": ["sharpe"], "value": [1.0]}).to_parquet(run / "metrics.parquet")
    if own_derived:
        (run / "derived").mkdir()
        (run / "derived" / "index.json").write_text(json.dumps({
            "derived_version": derived_version,
            "run_id": derived_run_id or run_id,
        }), encoding="utf-8")
    return run
```

三个用例分别钉死三条路径：

```python
def test_own_derived_is_used_and_owner_checked(tmp_path, monkeypatch):
    run = _fake_run(tmp_path / "reports", "aaaa")
    b = DashboardBuilder(_ctx(run, monkeypatch), run, tmp_path / "reports")
    assert b.derived == run / "derived"


def test_mirror_fallback_requires_matching_run_id(tmp_path, monkeypatch):
    run = _fake_run(tmp_path / "reports", "bbbb", own_derived=False)
    mirror = tmp_path / "reports" / "derived"
    mirror.mkdir()
    (mirror / "index.json").write_text(json.dumps(
        {"derived_version": 2, "run_id": "bbbb"}), encoding="utf-8")
    b = DashboardBuilder(_ctx(run, monkeypatch), run, tmp_path / "reports")
    assert b.derived == mirror


def test_mirror_of_another_run_raises(tmp_path, monkeypatch):
    run = _fake_run(tmp_path / "reports", "cccc", own_derived=False)
    mirror = tmp_path / "reports" / "derived"
    mirror.mkdir()
    (mirror / "index.json").write_text(json.dumps(
        {"derived_version": 2, "run_id": "other"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="cccc"):
        DashboardBuilder(_ctx(run, monkeypatch), run, tmp_path / "reports")


def test_stale_derived_version_raises(tmp_path, monkeypatch):
    run = _fake_run(tmp_path / "reports", "dddd", derived_version=1)
    with pytest.raises(RuntimeError, match="derived_version"):
        DashboardBuilder(_ctx(run, monkeypatch), run, tmp_path / "reports")


def test_no_derived_anywhere_raises(tmp_path, monkeypatch):
    run = _fake_run(tmp_path / "reports", "eeee", own_derived=False)
    with pytest.raises(RuntimeError, match="build_report_data"):
        DashboardBuilder(_ctx(run, monkeypatch), run, tmp_path / "reports")
```

`_ctx` 复刻 `tests/test_dashboard_data.py:57-62` 的打桩方式（monkeypatch `pipeline.load_prices`、`pipeline.load_fund_basic`、`universe.classify`），再 `ReportContext.load(run)`。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests\test_dashboard_derived_binding.py -q`
Expected: FAIL。`_ctx` 尚未定义要先补，`test_mirror_of_another_run_raises` 与 `test_no_derived_anywhere_raises` 会因为当前实现静默回退而不抛错。

- [ ] **Step 3: 实现**

把 `dashboard.py:157-165` 换成：

```python
    def __init__(self, ctx: ReportContext, run_dir: Path, reports_dir: Path):
        self.ctx = ctx
        self.run_dir = Path(run_dir)
        self.reports = Path(reports_dir)
        self.derived = self._resolve_derived()
        self._cache = {}

    def _resolve_derived(self) -> Path:
        """定位本 run 的派生目录。回退到镜像时必须证明镜像属于本 run。"""
        own = self.run_dir / "derived"
        if own.is_dir():
            self._check_derived_owner(own)
            return own
        mirror = self.reports / "derived"
        if mirror.is_dir():
            self._check_derived_owner(mirror)
            return mirror
        raise RuntimeError(
            f"run {self.run_dir.name} 缺少派生数据：{own} 与 {mirror} 都不存在。\n"
            f"先跑 `.venv\\Scripts\\python.exe scripts\\build_report_data.py "
            f"--run-id {self.run_dir.name}`")

    def _check_derived_owner(self, path: Path) -> None:
        """派生目录必须自证身份：run_id 与 derived_version 都要对得上。"""
        from etf_rotation.report import runner

        index = path / "index.json"
        if not index.exists():
            raise RuntimeError(f"{index} 缺失，无法证明派生数据属于 run {self.run_dir.name}")
        try:
            data = json.loads(index.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"{index} 不可解析：{exc}") from exc
        owner = str(data.get("run_id") or "")
        if owner != self.run_dir.name:
            raise RuntimeError(
                f"派生数据串台：{path} 属于 run {owner!r}，当前 run 是 {self.run_dir.name!r}。\n"
                f"不要用别的 run 的派生数据出图。先跑 "
                f"`scripts\\build_report_data.py --run-id {self.run_dir.name}`")
        version = data.get("derived_version")
        if version != runner.DERIVED_VERSION:
            raise RuntimeError(
                f"{path} 的 derived_version={version!r}，本版本只认 "
                f"{runner.DERIVED_VERSION}；先重跑 build_report_data.py")
```

同时把 `derived_json` / `report_json` 的 `FileNotFoundError` 换成带修复命令的 `RuntimeError`，因为 `report_json` 读的是顶层 JSON，缺文件时原始报错只说路径。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests\test_dashboard_derived_binding.py -q`
Expected: 5 passed。

- [ ] **Step 5: 真实数据对照**

Run:
```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe -c "import sys,pathlib; sys.path.insert(0,'src'); from etf_rotation.report.context import ReportContext; from etf_rotation.report.dashboard import DashboardBuilder; r=pathlib.Path('reports/runs/57ad104114db'); DashboardBuilder(ReportContext.load(r), r, pathlib.Path('reports'))"
```
Expected: 退出码非 0，`RuntimeError` 里含 `57ad104114db` 与 `build_report_data.py`。

再确认基线仍可构建：
```powershell
.venv\Scripts\python.exe scripts\build_dashboard.py --out reports\.tmp-check.html
```
Expected: `顶层键 : 48 / 48`，退出码 0。产出临时文件后删掉。

- [ ] **Step 6: 提交** `git commit -m "fix(report): 派生目录回退校验 run_id 与 derived_version"`

---

## Task 2: 三处旧批次文案改为载荷驱动

**Files:**
- Modify: `reports/front-design/index.html:500`（T05 面板注脚）、`:502`（T07 标题栏 hint）、`:1530`（`T.dsrCard` 后缀）、`:2122-2134`（`B.grid2d` 渲染 note）
- Modify: `src/etf_rotation/report/dashboard.py:1334-1345`（`batch` 拼装）、`:1349-1358`（`_sweep_batch_date` 加删死代码）、`:1387-1391`（`grid2d.note` 的日期）、`:1422-1432`（`dsr.sweep_batch`）
- Create: `tests/test_dashboard_wording.py`

**Interfaces:**
- Produces: 载荷 `sweeps[].batch` 的文案改为 `f"{batch_date} · {exec_label}口径"`，`exec_label` 来自 `self.ctx.meta.get("execution")`，取值 `open` 或 `close`，都不是时写 `未知`。
- Produces: `grid2d.note` 的日期来自 `families/<id>/summary.json` 的 `generated[:10]`，缺失时写 `生成时间未知`，不再写死 `2026-10-25`。
- Produces: `dsr` 字典新增 `sweep_batch` 字段，取 `reports/sensitivity/*.json` 中 `generated_at` 的最早日期。这是嵌套字段，顶层键数不变。
- Produces: 模板新增 `OD.batchNote()`，从 `D.sweeps`、`D.meta.execution`、`D.kpi.s.sharpe` 组装 T05 注脚文本，写入 `#sweepsNote`。
- 行为变化：页面不再出现 `旧批次`、`2026-10-17`、`1.039`。

- [ ] **Step 1: 写失败测试（渲染断言）**

```python
# tests/test_dashboard_wording.py
"""页面文案必须描述当前数据：不许出现旧批次字样，T10 脚注不许把 Calmar 叫 Sharpe。"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "reports" / "dashboard.html"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


@pytest.fixture(scope="module")
def dom() -> str:
    if not DASH.exists():
        pytest.skip("缺产物：先跑 scripts/build_dashboard.py")
    if shutil.which("chrome") is None and not CHROME.exists():
        pytest.skip("缺 Chrome，跳过渲染断言")
    exe = str(CHROME) if CHROME.exists() else "chrome"
    out = subprocess.run(
        [exe, "--headless=new", "--disable-gpu", "--allow-file-access-from-files",
         "--host-resolver-rules=MAP * ~NOTFOUND",
         "--virtual-time-budget=30000", "--dump-dom", DASH.as_uri()],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return out.stdout


def test_no_stale_batch_wording(dom):
    """只查静态文案。不要断言 `1.039` 不存在：这个数字在载荷数据里合法出现 82 次。"""
    assert "旧批次" not in dom
    assert "2026-10-17" not in dom
    assert "close 口径旧批次" not in dom


def test_sweeps_note_is_data_driven(dom):
    m = re.search(r'id="sweepsNote"[^>]*>(.*?)</div>', dom, re.S)
    assert m, "sweepsNote 容器缺失"
    text = m.group(1)
    assert "open" in text or "close" in text
    assert "口径" in text


def test_t10_footnote_labels_calmar(dom):
    m = re.search(r'id="gapNote"[^>]*>(.*?)</div>', dom, re.S)
    assert m, "gapNote 容器缺失"
    text = m.group(1)
    assert "1.94" in text, "研报 Sharpe 1.94 必须出现在脚注"
    assert "2.05" in text
    assert "Sharpe 2.05" not in text, "2.05 是 Calmar，不许标成 Sharpe"


def test_grid2d_note_is_rendered(dom):
    m = re.search(r'id="grid2dNote"[^>]*>(.*?)</div>', dom, re.S)
    assert m, "grid2dNote 容器缺失"
    assert "峰值 Sharpe" in m.group(1) or "热力图家族缺失" in m.group(1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe scripts\build_dashboard.py` 然后 `.venv\Scripts\python.exe -m pytest tests\test_dashboard_wording.py -q`
Expected: 4 failed。`test_no_stale_batch_wording` 命中 `旧批次`（当前产物里出现 3 次），另三条报容器缺失。

- [ ] **Step 3: 改 `dashboard.py`**

`_build_sweeps` 的 `batch` 改为：

```python
                "batch": f"{batch_date} · {self._exec_label()}口径",
```

新增两个辅助方法，放在 `_sweep_batch_date` 之前：

```python
    def _exec_label(self) -> str:
        """执行口径的中文短名，来自 meta 而不是写死。"""
        return {"open": "open", "close": "close"}.get(
            str(self.ctx.meta.get("execution") or ""), "未知")

    def _sweep_batch_date(self, data) -> str:
        fam = data.get("family_id")
        if fam:
            p = self.reports / "families" / fam / "summary.json"
            if p.exists():
                gen = json.loads(p.read_text(encoding="utf-8")).get("generated")
                if gen:
                    return str(gen)[:10]
        gen = data.get("generated_at")
        if gen:
            return str(gen)[:10]
        return self.dates[-1]
```

同时删掉 `dashboard.py:1357` 的死表达式（`if False else None`）。

`_build_grid2d` 的 note 改为：

```python
        gen = str(data.get("generated") or "")[:10] or "生成时间未知"
        if peak["sharpe"] is not None:
            note = (f"{gen} {self._exec_label()} 口径；峰值 Sharpe {peak['sharpe']:.4f}"
                    f"（相关性 {peak['corr']}，{peak['bps']:g}bp）")
        else:
            note = f"{gen} {self._exec_label()} 口径"
```

`_build_dsr` 增加 `sweep_batch`：

```python
        sweep_vals, sweep_dates = [], []
        for p in (self.reports / "sensitivity").glob("*.json"):
            d = json.loads(p.read_text(encoding="utf-8"))
            if d.get("dsr") is not None:
                sweep_vals.append(float(d["dsr"]))
            if d.get("generated_at"):
                sweep_dates.append(str(d["generated_at"])[:10])
        return {
            "value": _r(data.get("dsr_family"), 4),
            "threshold": 0.95,
            "haircut": data.get("sharpe_haircut"),
            "sweep": _r(min(sweep_vals) if sweep_vals else None, 4),
            "sweep_batch": min(sweep_dates) if sweep_dates else None,
        }
```

占位返回（family 缺失分支）也要带 `"sweep_batch": None`，否则前端读 `undefined`。

- [ ] **Step 4: 改模板**

`index.html:500` 的注脚换成空容器：

```html
<div class="panel-b" style="padding-top:0"><div class="note" id="sweepsNote"></div></div>
```

`index.html:502` 的 hint 去掉旧批次：

```html
<span class="tag warn">脏工作区 仅参考</span><span class="hint">corr × cost · Sharpe</span>
```

并在图表容器后加 note 容器：

```html
<div class="panel-b tight"><div class="chart" id="grid2d" style="height:360px"></div></div><div class="panel-b" style="padding-top:0"><div class="note" id="grid2dNote"></div></div>
```

`index.html:504` 的 T10 注脚换成空容器：

```html
<div class="panel-b" style="padding-top:0"><div class="note" id="gapNote"></div></div>
```

`T.dsrCard`（`index.html:1530`）的后缀改为读数据：

```js
" · sweep 口径 " + num(d.sweep, 4) + (d.sweep_batch ? "（" + esc(d.sweep_batch) + " 批次）" : "")
```

新增三个渲染函数，都挂在 `T` 上，插在 `T.gapTable`（`index.html:1552-1558`）之后、`T.cmdBlock` 之前。这三个函数返回 `null`，所以 `tableMounts()` 只会执行副作用，不会误触发 `Tbl()`：

```js
T.sweepsNote = function () {
  var h = el("sweepsNote");
  if (!h) return null;
  var batches = D.sweeps.map(function (s) { return s.batch; }).filter(Boolean);
  var uniq = batches.filter(function (b, i) { return batches.indexOf(b) === i; });
  var defs = D.sweeps.map(function (s) { return s.default_idx == null ? null : s.rows[s.default_idx]; })
    .filter(function (r) { return r && r.sharpe != null; });
  var cur = D.kpi.s.sharpe;
  var same = defs.length > 0 && defs.every(function (r) { return Math.abs(r.sharpe - cur) < 5e-4; });
  var txt = "参数扫描批次 " + (uniq.length ? uniq.join(" / ") : "未知") +
    "，默认点 Sharpe " + (defs.length ? num(defs[0].sharpe, 3) : "—") +
    "，本期 " + num(cur, 3) +
    (same ? "，同口径可直接比绝对值。" : "，口径不同只读 ΔSharpe 形状。");
  h.textContent = txt;
  return null;
};
T.grid2dNote = function () {
  var h = el("grid2dNote");
  if (h) h.textContent = D.grid2d.note || "";
  return null;
};
T.gapNote = function () {
  var h = el("gapNote");
  if (!h) return null;
  var by = {};
  D.gap.forEach(function (g) { by[g[0]] = g[1]; });
  h.textContent = "研报：" + (by["年化收益"] || "—") + " / " + (by["最大回撤"] || "—") +
    " / Sharpe " + (by["Sharpe"] || "—") + " · Calmar " + (by["Calmar"] || "—") +
    "。当前值与差值由报告产物计算，原因不在本报告范围内。";
  return null;
};
```

`B.grid2d` 本身不改。`T.grid2dNote` 已经通过 `tableMounts()` 把 `D.grid2d.note` 写进容器，再在渲染函数里写一次是重复逻辑。审计只要求「让 note 可见」，一处就够。

- [ ] **Step 5: 重建并跑测试确认通过**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\build_dashboard.py
.venv\Scripts\python.exe -m pytest tests\test_dashboard_wording.py -q
```
Expected: `顶层键 : 48 / 48`，4 passed。

- [ ] **Step 6: 人工看一眼页面文本**

```powershell
.venv\Scripts\python.exe -c "import re,pathlib; h=pathlib.Path('reports/dashboard.html').read_text(encoding='utf-8'); [print(m) for m in re.findall(r'(参数扫描批次[^\"]{0,120}|研报：[^\"]{0,120}|峰值 Sharpe[^\"]{0,80})', h)[:6]]"
```
Expected: 三行新文案，日期是 `2026-10-25`，口径是 `open`。

- [ ] **Step 7: 提交** `git commit -m "fix(report): 三处旧批次文案改为载荷驱动"`

---

## Task 3: T10 脚注与六份文档三元组

**Files:**
- Modify: `reports/回测报告.md:16`
- Modify: `reports/差距归因.md:4`
- Modify: `README.md:8`
- Modify: `TODO.md:3`
- Modify: `AGENTS.md:111`
- Modify: `docs/代码审阅手册.md:190`
- Modify: `reports/回测报告.md:100-104`（补一句键数来源，若 ticker-names 计划未落地则跳过）

**Interfaces:**
- 统一写法：`20.74% / -10.13% / Sharpe 1.94 / Calmar 2.05`。四处叙述句与两处表头说明都用这一串，顺序固定为年化、回撤、Sharpe、Calmar。
- `reports/回测报告.md:14` 的表格列头已经是 `研报 | 20.74% | — | -10.13% | 1.94 | 2.05`，列语义正确，不改表格，只改正文三元组。

- [ ] **Step 1: 确认六处原文**

Run:
```powershell
$env:PYTHONIOENCODING="utf-8"
foreach($f in @('reports\回测报告.md','reports\差距归因.md','README.md','TODO.md','AGENTS.md','docs\代码审阅手册.md')){ $i=0; Get-Content $f -Encoding UTF8 | ForEach-Object { $i++; if($_ -match '20\.74'){ "$f`:$i" } } }
```
Expected: 6 行命中，行号与上表一致。

- [ ] **Step 2: 逐处改串**

六处的替换都是把 `20.74% / -10.13% / 2.05` 或 `20.74% / −10.13% / 2.05` 换成 `20.74% / -10.13% / Sharpe 1.94 / Calmar 2.05`。注意 `reports/差距归因.md` 用的是 U+2212 减号，替换后保持该文件原有减号形式，不要统一改符号。

`reports/回测报告.md:16` 改后整句为：

> 自 v1.1.0 起默认执行口径改为 T+1 开盘成交（`OpenRebalance`），默认参数写回候选（`market_state.bull_threshold=0.30`、`dedupe.corr_threshold=0.85`）。默认基线为 9.61% / -15.79% / Sharpe 0.88 / Calmar 0.61；候选参数是在 close 口径下调出的，open 口径下回撤反而更深（-15.79% vs -14.47%），说明候选参数对执行口径不稳健，open 口径重新调参列为后续工作。与研报（20.74% / -10.13% / Sharpe 1.94 / Calmar 2.05）的差距归因见下阶段（`docs/superpowers/plans/2026-10-19-etf-rotation-next-phase.md` Part 3）。

- [ ] **Step 3: 自查没有新引入的错标**

Run:
```powershell
$env:PYTHONIOENCODING="utf-8"
Select-String -Path AGENTS.md,README.md,TODO.md,docs\代码审阅手册.md,reports\回测报告.md,reports\差距归因.md -Pattern 'Sharpe\s*2\.05' -Encoding UTF8
```
Expected: 无命中。

- [ ] **Step 4: 跑 T10 渲染断言**

Run: `.venv\Scripts\python.exe -m pytest tests\test_dashboard_wording.py -q`
Expected: 4 passed。`test_t10_footnote_labels_calmar` 是这一步的判据。

- [ ] **Step 5: 提交** `git commit -m "docs(report): 研报三元组补 Sharpe 1.94 与 Calmar 2.05 标签"`

---

## Task 4: 顶层 JSON 加 run 绑定与校验

**Files:**
- Modify: `scripts/run_attribution.py:80-90`
- Modify: `scripts/run_exposure.py:77-89`
- Modify: `scripts/audit_data_quality.py:29-37`
- Modify: `src/etf_rotation/evaluation/verify.py:360-423`（`verify_reports`）
- Modify: `tests/test_verify_artifacts.py`（追加用例）

**Interfaces:**
- Produces: 三个顶层 JSON 都带四个身份字段 `run_id`、`data_snapshot_id`、`git_sha`、`generated_at`。数值字段一个不改。
- Produces: `verify.verify_reports` 新增一条检查：`reports/{attribution,exposure,data_quality}.json` 必须存在，必须有 `run_id`，且等于 `latest.json` 的 `run_id`；有 `data_snapshot_id` 时必须等于该 run `meta.parquet` 的 `data_snapshot_id`。
- Produces: `audit_data_quality.py` 新增 `--run-id` 参数，默认读 `reports/latest.json`；写 `reports/runs/{run_id}/analysis/data_quality.json`，再镜像到 `reports/data_quality.json`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_verify_artifacts.py` 追加：

```python
def _report_json(path, **extra):
    payload = {"ok": 1, **extra}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_verify_reports_requires_bound_top_level_json(tmp_path):
    p = _store(tmp_path)
    (tmp_path / "latest.json").write_text('{"run_id": "r1"}', encoding="utf-8")
    _write_index(p, _artifact_hashes(p), run_id="r1")
    mirror = tmp_path / "derived"
    mirror.mkdir()
    shutil.copy(p / "derived/index.json", mirror / "index.json")
    problems = verify.verify_reports(tmp_path)
    assert any("attribution.json" in m for m in problems)
    assert any("exposure.json" in m for m in problems)
    assert any("data_quality.json" in m for m in problems)


def test_verify_reports_flags_top_level_json_of_other_run(tmp_path):
    p = _store(tmp_path)
    (tmp_path / "latest.json").write_text('{"run_id": "r1"}', encoding="utf-8")
    _write_index(p, _artifact_hashes(p), run_id="r1")
    mirror = tmp_path / "derived"
    mirror.mkdir()
    shutil.copy(p / "derived/index.json", mirror / "index.json")
    for name in ("attribution", "exposure", "data_quality"):
        _report_json(tmp_path / f"{name}.json", run_id="other")
    problems = verify.verify_reports(tmp_path)
    for name in ("attribution", "exposure", "data_quality"):
        assert any(name in m and "run_id" in m for m in problems)


def test_verify_reports_accepts_bound_top_level_json(tmp_path):
    p = _store(tmp_path)
    (tmp_path / "latest.json").write_text('{"run_id": "r1"}', encoding="utf-8")
    _write_index(p, _artifact_hashes(p), run_id="r1")
    mirror = tmp_path / "derived"
    mirror.mkdir()
    shutil.copy(p / "derived/index.json", mirror / "index.json")
    for name in ("attribution", "exposure", "data_quality"):
        _report_json(tmp_path / f"{name}.json", run_id="r1", data_snapshot_id=None)
    assert verify.verify_reports(tmp_path) == []
```

文件头需要补 `import shutil`（若还没有）。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests\test_verify_artifacts.py -q`
Expected: 3 failed（新增三条），其余 passed。

- [ ] **Step 3: 补齐既有用例的夹具，让它们继续断言「无问题」**

新检查会让两条既有用例变红，因为它们的 `tmp_path` 里没有那三个顶层 JSON：
`test_verify_reports_detects_stale_mirror` 与 `test_verify_reports_accepts...` 系列的 `assert verify.verify_reports(tmp_path) == []` 会返回三条「缺失」。

在 `tests/test_verify_artifacts.py` 加一个共用助手，并在 `test_verify_reports_detects_stale_mirror` 里调用：

```python
def _bind_reports(tmp_path, run_id="r1"):
    """写三份已绑定的顶层 JSON，供「应当无问题」的用例复用。"""
    for name in ("attribution", "exposure", "data_quality"):
        _report_json(tmp_path / f"{name}.json", run_id=run_id)
```

注意 `test_verify_reports_detects_mirror_run_id_mismatch` 只断言「含串台」，不受影响，不必改。

Run: `.venv\Scripts\python.exe -m pytest tests\test_verify_artifacts.py -q`
Expected: 全部 passed。

- [ ] **Step 4: 改三个写盘脚本**

`run_attribution.py` 与 `run_exposure.py` 在 `clean({...})` 外层包一层身份字段：

```python
    meta = pd.read_parquet(run_dir / "meta.parquet").iloc[0]
    out = clean({
        "run_id": run_dir.name,
        "data_snapshot_id": str(meta.get("data_snapshot_id") or ""),
        "git_sha": str(meta.get("git_sha") or ""),
        "generated_at": pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        # ... 原有业务字段原样保留 ...
    })
```

身份字段放在最前面，业务字段顺序不变，这样 diff 只出现在文件头。

`audit_data_quality.py` 加 `--run-id`：

```python
    parser = argparse.ArgumentParser(description="数据质量复核")
    parser.add_argument("--run-id", default=None, help="绑定到指定 run（默认 reports/latest.json）")
    args = parser.parse_args()
    run_dir = artifacts.resolve_run(ROOT / "reports" / "runs", args.run_id)
    meta = pd.read_parquet(run_dir / "meta.parquet").iloc[0]
```

输出字典加同样四个字段，并把 `write_text` 改成先写 `run_dir / "analysis" / "data_quality.json"`、再写 `reports/data_quality.json`，与另外两个脚本一致。

- [ ] **Step 5: 改 `verify_reports`**

在 `verify.py:413` 的 `analysis` 段之前插入：

```python
    for name in ("attribution", "exposure", "data_quality"):
        jp = reports_dir / f"{name}.json"
        if not jp.is_file():
            problems.append(f"{jp}: 缺失（请跑对应的生成脚本）")
            continue
        try:
            payload = json.loads(jp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            problems.append(f"{jp}: 不可解析")
            continue
        if "run_id" not in payload:
            problems.append(f"{jp}: 缺少 run_id（顶层 JSON 未做 run 绑定）")
        elif str(payload.get("run_id")) != run_id:
            problems.append(f"{jp}: run_id={payload.get('run_id')!r} 与 latest {run_id} 不一致")
        snap = payload.get("data_snapshot_id")
        if snap and meta_snapshot and str(snap) != meta_snapshot:
            problems.append(f"{jp}: data_snapshot_id={snap!r} 与 run 的 {meta_snapshot!r} 不一致")
```

`meta_snapshot` 在函数开头取：

```python
    meta_path = reports_dir / "runs" / run_id / "meta.parquet"
    meta_snapshot = None
    if meta_path.exists():
        row = pd.read_parquet(meta_path).iloc[0]
        meta_snapshot = str(row.get("data_snapshot_id") or "") or None
```

同时更新 `verify_reports` 的 docstring（现在只讲三个问题，要加成四个）。

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests\test_verify_artifacts.py -q`
Expected: 全部 passed。

- [ ] **Step 6: 重新生成三个文件并确认数值不变**

```powershell
$env:PYTHONIOENCODING="utf-8"
Copy-Item reports\attribution.json reports\.before-attr.json
Copy-Item reports\exposure.json reports\.before-expo.json
Copy-Item reports\data_quality.json reports\.before-dq.json
.venv\Scripts\python.exe scripts\run_attribution.py
.venv\Scripts\python.exe scripts\run_exposure.py
.venv\Scripts\python.exe scripts\audit_data_quality.py
.venv\Scripts\python.exe -c "
import json,pathlib
for old,new in (('.before-attr','attribution'),('.before-expo','exposure'),('.before-dq','data_quality')):
    a=json.loads((pathlib.Path('reports')/(old+'.json')).read_text(encoding='utf-8'))
    b=json.loads((pathlib.Path('reports')/(new+'.json')).read_text(encoding='utf-8'))
    diff=[k for k in a if a[k]!=b.get(k)]
    print(new,'数值差异',diff,'新字段',[k for k in b if k not in a])
"
```
Expected: 三个文件的「数值差异」都是 `[]`，新字段恰好是四个身份字段。之后删掉三份 `.before-*.json` 临时文件。

- [ ] **Step 7: 全量产物校验**

```powershell
.venv\Scripts\python.exe scripts\verify_artifacts.py
```
Expected: 退出码 0，无 `attribution.json`、`exposure.json`、`data_quality.json` 相关问题。

- [ ] **Step 8: 提交** `git commit -m "feat(report): 顶层 JSON 绑定 run_id 并纳入 verify"`

---

## Task 5: 合成 run 夹具与 hermetic 契约测试

**Files:**
- Create: `tests/fixtures/build_synthetic_run.py`（生成器）
- Create: `tests/fixtures/synthetic_run/**`（生成物，入库）
- Modify: `tests/test_dashboard_data.py:34-63`（换夹具）、`:11`（docstring）、`:129-134`（去掉对真实 run 的依赖）
- Create: `tests/test_dashboard_fixture.py`（夹具自检）

**Interfaces:**
- Produces: `tests/fixtures/synthetic_run/` 是一个假的 `reports/` 根。布局：
  ```
  synthetic_run/
    runs/syn000000001/{meta,metrics,equity,benchmark,weights,holdings,trades,transactions}.parquet
    runs/syn000000001/signals/{decision_diary,ticker_signals,stages}.parquet
    runs/syn000000001/derived/{index,performance,relative,events,stages,roundtrips,costs,liquidity}.json
    runs/syn000000001/analysis/{attribution,exposure,data_quality}.json
    latest.json
    derived/  -> 不入库（Task 1 的校验会拒），测试只用 run 自带的 derived
    {attribution,exposure,data_quality,ablation,assumption_sensitivity,oos_check}.json
    sensitivity/trend_windows.json
    families/{00d0a6f0e9f8,abc468e90e83,f42d16191378}/summary.json
  ```
- Produces: `tests/fixtures/build_synthetic_run.py` 可重复执行，`--out` 默认自己所在目录，运行两次字节级一致（JSON `sort_keys` 加固定 `generated` 时间戳）。
- Produces: 夹具里的 `derived/index.json` 必须写 `{"run_id": "syn000000001", "derived_version": 2}`，否则 Task 1 的归属校验会拒绝它。
- Produces: `tests/conftest.py` 新增 `synthetic_reports() -> Path` fixture，返回 `tests/fixtures/synthetic_run`。
- 行为变化：`tests/test_dashboard_data.py` 的两条重用例不再 `pytest.skip`，在任何环境下都真跑 48 键全量构建。

- [ ] **Step 1: 写生成器骨架**

生成器要含一张结构清单，逐个键填最小可用数据。以 `equity` 为例：

```python
def _equity(n=6) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-02", periods=n)
    nav = pd.Series([1.0, 1.012, 1.004, 1.02, 1.015, 1.031], index=idx)
    return pd.DataFrame({
        "nav": nav,
        "returns": nav.pct_change(fill_method=None).fillna(0.0),
        "cash": 0.05, "turnover": 0.01,
        "fees": pd.Series([0.0, 0.001, 0.0, 0.0, 0.0, 0.0], index=idx),
    })
```

其余面板按 `dashboard.py` 的属性契约造：`benchmark` 需要 `benchmark` 与 `hs300` 两列，`weights`/`holdings` 用两个标的 `A`/`B`，`trades` 需要 `date/ticker/side/price/quantity/notional/cost`，`transactions` 需要 `Date/Security/price/quantity`，`decision_diary` 需要 `comp_score/risk_scale/vol_scale_risk/risk_budget/n_cands/n_kept/regime/total_weight`，`ticker_signals` 用 `MultiIndex(date, ticker)`，`stages` 需要 4 列。

- [ ] **Step 2: 逐键生成，直到 48 键全通**

循环执行下面的命令，每次报 `KeyError` 或 `TypeError` 就把缺的结构补进生成器：

```powershell
$env:PYTHONIOENCODING="utf-8"
$env:PYTHONPATH="D:\project\quant_1\src"
.venv\Scripts\python.exe -c "
import pathlib
from etf_rotation.report.context import ReportContext
from etf_rotation.report.dashboard import DashboardBuilder, dumps
from etf_rotation import pipeline
from etf_rotation.data import universe
import pandas as pd
idx=pd.bdate_range('2024-01-02',periods=6)
px=pd.DataFrame({'A':[10.0]*6,'B':[5.0]*6},index=idx)
pipeline.load_prices=lambda:(px,px,px)
pipeline.load_fund_basic=lambda: pd.DataFrame({'ts_code':['A','B'],'name':['甲乙ETF','丙丁ETF']})
universe.classify=lambda _: {'A':'risk','B':'bond'}
root=pathlib.Path('tests/fixtures/synthetic_run')
run=root/'runs'/'syn000000001'
b=DashboardBuilder(ReportContext.load(run), run, root)
p=b.build()
print('顶层键', len(p), 'chars', len(dumps(p)))
"
```

Expected: 最后打印 `顶层键 <n> chars <数>` 且无异常，`n` 与 `BUILD_ORDER` 长度相同（当前 48）。这个循环可能要改三四轮，每轮把新缺的结构写进生成器而不是手改 JSON。

- [ ] **Step 3: 控制体积**

Run: `Get-ChildItem tests\fixtures\synthetic_run -Recurse -File | Measure-Object Length -Sum`
Expected: 合计 < 400 KB，最大单文件 < 200 KB。超了就减行数，不要减字段。

- [ ] **Step 4: 换 `tests/test_dashboard_data.py` 的夹具**

```python
@pytest.fixture
def builder(monkeypatch) -> DashboardBuilder:
    """合成 run 夹具：不依赖 reports/，干净 clone 里也能真跑。"""
    root = Path(__file__).resolve().parent / "fixtures" / "synthetic_run"
    run_dir = root / "runs" / "syn000000001"
    if not run_dir.exists():
        pytest.fail("合成夹具缺失：跑 python tests/fixtures/build_synthetic_run.py")
    _patch_heavy(monkeypatch)
    return DashboardBuilder(ReportContext.load(run_dir), run_dir, root)
```

`_patch_heavy` 是原来 fixture 里的三行 monkeypatch，抽成模块级函数供两个测试文件共用。

同时把模块 docstring 里的「真实 run 缺失时 `pytest.skip`」改成「夹具固定为 `tests/fixtures/synthetic_run`，缺夹具直接 fail」。

- [ ] **Step 5: 保留一条真实 run 的可选用例**

追加一条，允许 skip，因为它验证的是真实数据而不是契约：

```python
def test_real_run_sampled_keys_when_available(monkeypatch):
    """真实 run 存在时再核一次抽样键（干净 clone 下 skip，不影响契约）。"""
    run_dir = _real_run_dir()
    if run_dir is None:
        pytest.skip("无真实 run")
    _patch_heavy(monkeypatch)
    b = DashboardBuilder(ReportContext.load(run_dir), run_dir, run_dir.parent.parent)
    payload = b.build(only=["meta", "kpi", "stats"])
    mdf = pd.read_parquet(run_dir / "metrics.parquet")
    metrics = dict(zip(mdf["metric"], mdf["value"]))
    assert payload["kpi"]["s"]["sharpe"] == pytest.approx(round(float(metrics["sharpe"]), 4))
```

- [ ] **Step 6: 跑测试确认通过且无 skip**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe -m pytest tests\test_dashboard_data.py -q -rs
```
Expected: 6 passed，`-rs` 输出里没有 `SKIPPED`（真实 run 存在时）。

再模拟干净 clone：
```powershell
.venv\Scripts\python.exe -m pytest tests\test_dashboard_data.py -q -rs --deselect tests/test_dashboard_data.py::test_real_run_sampled_keys_when_available
```
Expected: 5 passed。

- [ ] **Step 7: 提交** `git commit -m "test(dashboard): 合成 run 夹具替代真实 run 依赖"`

---

## Task 6: 体积自证改字节并加恒等式

**Files:**
- Modify: `scripts/build_dashboard.py:108-117`
- Create: `tests/test_build_dashboard_sizes.py`（`tests/test_build_dashboard.py` 不存在，别往它上面追加）
- Modify: `reports/回测报告.md`（若其中抄了 `9.85 MB + 4.56 MB` 的算法，一并改）

**Interfaces:**
- Produces: `scripts/build_dashboard.py` 新增模块级函数 `size_lines(template: str, data_json: str, plotly: str, written: bytes) -> tuple[list[str], bool]`，返回打印行与恒等式是否成立。
- 恒等式：`len(data_json.encode()) + len(plotly.encode()) + shell_bytes == len(written)`。`shell_bytes` 由 `len(written) - 数据字节 - plotly 字节` 反推没有意义，必须正向算：`shell = 模板字节 - 数据块字节 - CDN script 字节`。
- 行为变化：脚本打印的单位从「字符 MB」变成「字节 MB」，并多一行「自证：通过/不通过」。不通过时 `sys.exit(1)`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_build_dashboard_sizes.py
"""体积自证必须按字节算账，且恒等式成立。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_dashboard import size_lines  # noqa: E402


def test_size_lines_uses_bytes_not_chars():
    data = '{"a":"中文"}'
    plotly = "var x = 1;"
    lines, ok = size_lines("<html></html>", data, plotly, b"x" * 1000)
    joined = "\n".join(lines)
    assert "B" in joined or "字节" in joined
    assert str(len(data.encode("utf-8"))) in joined


def test_size_lines_reports_mismatch():
    lines, ok = size_lines("<html></html>", '{"a":1}', "p", b"x" * 7)
    assert ok is False
    assert any("不通过" in line for line in lines)


def test_size_lines_accepts_consistent_input():
    data, plotly, shell = '{"a":1}', "p", "<html></html>"
    total = len(shell.encode()) + len(data.encode()) + len(plotly.encode())
    lines, ok = size_lines(shell, data, plotly, b"x" * total)
    assert ok is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv\Scripts\python.exe -m pytest tests\test_build_dashboard_sizes.py -q`
Expected: `ImportError: cannot import name 'size_lines'`。

- [ ] **Step 3: 实现 `size_lines` 并接入 `main`**

```python
def size_lines(template: str, data_json: str, plotly: str, written: bytes) -> tuple[list[str], bool]:
    """按字节给产物体积算账，并校验三块之和等于总字节。

    单位是 UTF-8 字节，不是字符。中文与 U+2212 占多字节，按字符算会对不上。
    """
    data_b = len(data_json.encode("utf-8"))
    plotly_b = len(plotly.encode("utf-8"))
    shell_b = len(template.encode("utf-8"))
    total_b = len(written)
    ok = data_b + plotly_b + shell_b == total_b
    lines = [
        f"数据   : {data_b / 1e6:.2f} MB（{data_b} B）",
        f"plotly : {plotly_b / 1e6:.2f} MB（{plotly_b} B）",
        f"外壳   : {shell_b / 1e6:.2f} MB（{shell_b} B）",
        f"合计   : {total_b / 1e6:.2f} MB（{total_b} B，实测 {len(written)} B）",
        f"自证   : {'通过' if ok else '不通过'}",
    ]
    return lines, ok
```

`main` 里把 `:108-116` 的打印换成调用它，`ok` 为假时 `print(..., file=sys.stderr)` 并 `sys.exit(1)`。注意 `shell_b` 用的是模板字符数，但产物里的数据块与 plotly 都被替换过，模板原始长度不等于外壳长度，所以要先从模板里扣掉原数据块与 CDN script 的长度再算外壳：

```python
    shell_len = len(template.encode("utf-8")) - len(body.encode("utf-8")) \
        - sum(len(m) for m in CDN_RE.findall(template)) + len("<script></script>")
```

把扣后的 `shell_len` 传给 `size_lines`（函数签名第二段改成接收 `shell_bytes: int` 更直接，测试里的三处调用相应传整数）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv\Scripts\python.exe -m pytest tests\test_build_dashboard_sizes.py -q`
Expected: 3 passed。

- [ ] **Step 5: 真实构建验算**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\build_dashboard.py
```
Expected: 五行体积数字，`自证   : 通过`，退出码 0。把五行贴进 Task 7 的验收记录。

- [ ] **Step 6: 提交** `git commit -m "fix(report): 体积自证改按字节并加恒等式"`

---

## Task 7: 全量验收与文档回填

**Files:**
- Modify: `reports/回测报告.md`（看板数据口径一节补一句批次来源与体积数字）
- Modify: `TODO.md`（把本次没修的 P3 记账）
- Modify: `docs/superpowers/plans/2026-10-27-etf-rotation-dashboard-remediation.md`（回填执行结果）

- [ ] **Step 1: 重建产物**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\build_report_data.py
.venv\Scripts\python.exe scripts\build_dashboard.py
```
Expected: `顶层键 : 48 / 48`，`自证   : 通过`。

- [ ] **Step 2: 全量单测**

```powershell
.venv\Scripts\python.exe -m pytest tests -q -rs
```
Expected: 基线 281 passed（`e2c21ae` 实测）加本次新增用例，无 failed，无因缺 run 产生的 SKIPPED。

- [ ] **Step 3: 逐键比对**

```powershell
.venv\Scripts\python.exe .superpowers\sdd\dashboard\cmp_dashboard.py
```
Expected: 汇总行 `意外差异 0 条`，退出码 0。`sweeps`、`grid2d`、`dsr` 三处已在 `KNOWN_RULES` 里，本次改动不新增意外差异。若新增，先看是不是 `batch` 与 `sweep_batch` 变了，把原因补进 `KNOWN_RULES` 再重跑。

- [ ] **Step 4: 离线渲染验收**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe -m pytest tests\test_dashboard_wording.py -q
.venv\Scripts\python.exe -c "import re,pathlib; h=pathlib.Path('reports/dashboard.html').read_text(encoding='utf-8'); print('外部引用', len(re.findall(r'<(?:script|link)[^>]*(?:src|href)=.https?://', h))); print('字节', len(h.encode()))"
```
Expected: 4 passed，`外部引用 0`，字节数在 15.5 MB 到 16.0 MB 之间。

- [ ] **Step 5: 回填文档**

`reports/回测报告.md` 的「看板数据口径」一节，在三条差异之后补一段：

> 页面上的批次、口径、峰值、研报对照数字全部由载荷计算，模板不再写死。参数扫描批次取自 `families/<id>/summary.json` 的 `generated` 与 run 的 `execution`，所以换口径或重跑批次后页面文案会跟着变。

`TODO.md` 追加一小节，把本次不修的审计项记账：

```markdown
## 看板审计遗留（2026-10-27，本次不修）

- P3-2：`build_dashboard_data.py` 拆分仍未做；本机 `http.server` 8765/8766/8777 仍在 LISTEN；`reports/.offline-control.html` 与 `.superpowers/sdd/dashboard/offline_ctrl.py` 仍在磁盘。
- P3-3：`.superpowers/sdd/dashboard/progress.md` 只记了 `Task 1: complete`，与「7 个 Task 全部完成」不匹配。
- P3-4：三个硬编码 family id（`00d0a6f0e9f8`、`abc468e90e83`、`f42d16191378`）仍在 `dashboard.py` 里，换批次需要改代码。
```

- [ ] **Step 6: 提交**

```powershell
git add -A
git commit -m "chore(dashboard): 审计整改验收与遗留记账"
```

---

## 验收清单

全部打勾才算收口。

- [ ] `DashboardBuilder` 对没有自带 `derived/` 的 run 抛 `RuntimeError`，报错含 run_id 与修复命令
- [ ] 页面搜不到 `旧批次` 与 `2026-10-17`
- [ ] T05 注脚、T07 note、DSR 后缀都由载荷算出
- [ ] T10 脚注写 `Sharpe 1.94` 与 `Calmar 2.05`
- [ ] 六份文档的三元组都补了 Sharpe 与 Calmar 标签
- [ ] 三个顶层 JSON 带 `run_id`、`data_snapshot_id`、`git_sha`、`generated_at`
- [ ] `verify_reports` 能发现未绑定与错绑定的顶层 JSON
- [ ] 三个顶层 JSON 重算后数值零变化
- [ ] `tests/test_dashboard_data.py` 在无 `reports/` 的目录下也真跑 48 键全量构建
- [ ] 合成夹具合计 < 400 KB，生成器入库且可重跑
- [ ] `scripts/build_dashboard.py` 打印字节数并给出「自证 通过」
- [ ] 全量单测无 failed
- [ ] `cmp_dashboard.py` 报「意外差异 0 条」
- [ ] 产物外部引用 0 处

## 记账但不修（按已确认的范围裁决）

以下审计项本次只记录，不改代码，条目已在上面的 Task 7 Step 5 写进 `TODO.md`。

| 审计项 | 本次处置 |
|---|---|
| P3-2 计划遗留项与磁盘残留 | 记账。三个 `http.server` 端口与两个临时文件属于本机清理，不在代码范围 |
| P3-3 SDD ledger 只记了一条 | 记账。补 ledger 属于过程记录，不影响交付物 |
| P3-4 硬编码 family id 与死代码 | 记账。死代码 `if False` 那行随 Task 2 重写 `_sweep_batch_date` 顺带删掉，三个 family id 保留 |
| 热力图 12 个成员 run 全脏 | 不在本次范围。要重跑得在干净工作区生成新 family，会更换 family id 与页面数字，属于独立决策 |

## 风险与回退

- **Task 1 会让既有用法变红。** 任何 `--run-id <非 latest>` 的出图流程会立刻报错。回退方式是把 `_resolve_derived` 的 `raise` 改回 `return mirror`，但不建议，因为那就是审计点名的缺陷。
- **Task 2 改模板会动产物哈希。** 不影响任何验收，因为本计划不钉哈希。若 `cmp_dashboard.py` 新增意外差异，先确认差异只落在 `sweeps`、`grid2d`、`dsr` 三处。
- **Task 4 重跑 `run_attribution.py` 与 `run_exposure.py` 会读真实价格面板。** 约 200 万行，耗时数分钟。跑之前确认 `data/` 完整，跑完确认三个文件数值零变化。
- **Task 4 让「镜像纪律」变得可检测。** 三个脚本目前无论 `--run-id` 指向哪个 run 都覆盖顶层镜像。加完 run 绑定后，用非 latest 的 `--run-id` 跑一次就会让 `verify_reports` 报不一致。本计划不改这个行为（属于既有设计），只在 `reports/回测报告.md` 与脚本 docstring 里写明：顶层镜像只对 latest run 有意义。要根治得给三个脚本加 `should_mirror` 守卫，那是独立任务。
- **Task 5 夹具可能被误认为证据。** 目录名定为 `synthetic_run`，且放在 `tests/fixtures` 下，不参与 `reports/` 的任何流程。生成器里写清「这是测试夹具，不是回测结果」。

## 执行建议

推荐 subagent-driven-development：Task 1、4、6 互不依赖可并行，Task 2 依赖 Task 1，Task 5 依赖 Task 1 与 4。若用 executing-plans 串行执行，按 Task 1 到 7 的顺序即可。

开工前必须先确认 `2026-10-27-dashboard-ticker-names.md` 的未提交改动已处理，否则两份计划会改同一批文件。
