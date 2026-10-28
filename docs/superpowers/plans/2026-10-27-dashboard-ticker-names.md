# 看板证券代码显示简称 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `reports/dashboard.html` 里每一处显示证券代码的地方都同时或优先显示证券简称，没有空间的地方把代码移到悬浮提示里。

**Architecture:** 新增第 49 个载荷键 `names`（`{code: 简称}`），由 `DashboardBuilder.names()` 从 `pipeline.load_fund_basic()` 的 `name` 列按固定规则裁剪生成。前端在模板 `reports/front-design/index.html` 里新增一个 `OD.nm(code)` 查表函数，所有渲染点改为查表。表格单元格用原生 `title` 属性承载代码，Plotly 图用 `hovertemplate` 承载。

**Tech Stack:** Python 3.10、pandas、Plotly 2.35.2（已内联）、原生 JS（无构建步骤）、pytest。

**Spec:** 本次无独立 spec 文档。需求来自 2026-10-27 会话中的三点已确认决策：
- 简称口径：剥掉 `(QDII-LOF-FOF)` / `(QDII-LOF)` / `(QDII)` / `(LOF)` 后缀与结尾 `-CNY`，保留主体。
- 载荷契约：新增顶层键 `names`，48 键变 49 键。
- 悬浮实现：表格用原生 `title` 属性，图表用 `hovertemplate`。

## Global Constraints

- Windows PowerShell，Python 3.10，一律 `.venv\Scripts\python.exe`。
- 跑任何 Python 前先 `$env:PYTHONIOENCODING="utf-8"`。
- 中文输出按 `.opencode/skills/zh-plain`：先结论、一句一事、主动语态、不用破折号和分号。
- 产物 `reports/dashboard.html` 必须仍然 0 处外部引用、离线可开、字节级可复现。
- 模板 `reports/front-design/index.html` 已入库（`git ls-files` 可见），本次要改它，这推翻了旧计划第 7 行「骨架一律不改」的约束。改动范围仅限证券代码显示，样式、布局、其它渲染逻辑不动。
- `tests/test_dashboard_data.py::test_build_order_48_unique_stable` 硬断言 48 项。加键必须同步改这条测试的名字与断言。
- 简称规则必须无重名。已实测：按上述规则，971 个标的简称互不重复。
- 不做截断。实测 971 个简称长度 min 4 / 中位 13 / max 22，截断到 12 字会产生 14 组重名，所以窄列改用「替换 + 悬浮」而不是截断。

## Review Focus

- **`fund_basic` 里查不到代码**：`names` 必须对 payload 里出现的每个代码都有值。查不到时回落成代码本身，不能输出 `null` 或空串，否则表格会出现 `undefined`。任务 1 的测试钉死这一点。
- **简称含 HTML 特殊字符**：`fund_basic` 名称里有 `(TMT)`、`&` 等。表格单元格走 `esc()`，`title` 属性也必须过 `esc()`，否则 `title="..."` 被提前闭合。
- **CSV 导出**：`csv()` 用 `c.fmt` 的结果剥掉标签。如果只在 `fmt` 里塞简称，导出会丢代码。任务 4 的测试钉死 CSV 必须同时有简称和代码。
- **`panoramaTable` 搜索框**：`Tbl.filtered()` 用列的原始值做匹配。改成简称后，用户输入代码搜不到。任务 4 的测试钉死按代码仍可搜到。
- **Plotly 类别轴标签过长**：`topPnlChart` 图宽 589px，当前 y 轴标签最宽 42px、`margin.l=74`。换成中位 13 字的简称后约 150px，会挤掉绘图区。任务 5 必须实测图表宽度，不接受「应该够」。

---

## 文件结构

| 文件 | 职责 | 本次改动 |
| --- | --- | --- |
| `src/etf_rotation/data/universe.py` | 已有：名称 → 风险分类 | 新增 `abbreviate(names)` 纯函数，与 `classify` 并列 |
| `src/etf_rotation/report/dashboard.py` | 48 键载荷构建 | 新增 `names()` 方法与 `BUILD_ORDER`/`BUILDER_METHODS` 条目（→ 49） |
| `reports/front-design/index.html` | 单文件看板外壳与全部渲染逻辑 | 新增 `OD.nm()` 查表函数 + 9 处渲染点改写 |
| `tests/test_dashboard_names.py` | 新建：简称规则与载荷契约 | 全部新增 |
| `tests/test_dashboard_data.py` | 48 键断言 | 改为 49 键 |
| `.superpowers/sdd/dashboard/cmp_dashboard.py` | 逐键比对 | `KNOWN_RULES` 加 `names` 豁免，并修 `hit()` 的顶层键路径（原本对顶层键无效） |

`names` 放在 `universe.py` 而不是 `dashboard.py`，因为裁剪规则属于标的元数据口径，与 `classify` 同类。`dashboard.py` 只负责把它塞进载荷。

---

### Task 1: 简称裁剪规则

**Files:**
- Modify: `src/etf_rotation/data/universe.py`（在 `classify` 之后追加）
- Test: `tests/test_dashboard_names.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces: `abbreviate(names: pd.Series) -> pd.Series`。入参是以 `ts_code` 为索引、值为 `fund_basic["name"]` 的 Series。返回同索引 Series，值为裁剪后的简称。

- [ ] **Step 1: 写失败的测试**

新建 `tests/test_dashboard_names.py`：

```python
"""证券简称裁剪规则与 names 载荷契约。

口径：
- 剥掉 `(QDII-LOF-FOF)` / `(QDII-LOF)` / `(QDII)` / `(LOF)` 后缀，以及结尾的 `-CNY`；
- 剥完为空就退回原名，不能返回空串；
- 只做后缀剥离，不截断；
- 看板载荷里的 971 个标的，简称必须互不重复（全量 fund_basic 允许重名，见最后一条用例）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from etf_rotation.data.universe import abbreviate

ROOT = Path(__file__).resolve().parents[1]


def test_strips_qdii_lof_suffixes():
    raw = pd.Series(
        {
            "513100.SH": "国泰纳斯达克100ETF(QDII)",
            "501225.SH": "景顺长城全球半导体芯片产业股票(QDII-LOF)-A-CNY",
            "162703.SZ": "广发小盘成长混合(LOF)-A",
            "161129.SZ": "易方达原油(QDII-LOF-FOF)-A-CNY",
            "518880.SH": "华安易富黄金ETF",
        }
    )
    out = abbreviate(raw)
    assert out["513100.SH"] == "国泰纳斯达克100ETF"
    assert out["501225.SH"] == "景顺长城全球半导体芯片产业股票-A"
    assert out["162703.SZ"] == "广发小盘成长混合-A"
    assert out["161129.SZ"] == "易方达原油-A"
    assert out["518880.SH"] == "华安易富黄金ETF"


def test_never_returns_empty_and_keeps_index():
    raw = pd.Series({"A.SH": "(QDII)", "B.SZ": "(LOF)-CNY", "C.SH": "正常名称"})
    out = abbreviate(raw)
    assert list(out.index) == ["A.SH", "B.SZ", "C.SH"]
    assert (out.str.len() > 0).all()
    assert out["A.SH"] == "(QDII)"
    assert out["B.SZ"] == "(LOF)-CNY"
    assert out["C.SH"] == "正常名称"


def test_abbreviations_unique_within_dashboard_universe():
    """简称只需在看板用到的代码里唯一，全量 fund_basic 允许重名。

    实测全量 2971 个代码里有 34 个落在 17 组重名（如 159073.SZ 与 159319.SZ
    都叫「汇添富国证粮食产业ETF」）。看板载荷只含 971 个代码，其中 0 组重名。
    """
    path = ROOT / "data" / "bronze" / "tushare" / "etf_rotation" / "fund_basic.parquet"
    payload = ROOT / "reports" / "dashboard.html"
    if not path.exists():
        pytest.skip(f"缺 fund_basic：{path}")
    if not payload.exists():
        pytest.skip(f"缺看板产物：{payload}")

    import json

    fb = pd.read_parquet(path)[["ts_code", "name"]]
    names = fb.set_index("ts_code")["name"]
    html = payload.read_text(encoding="utf-8")
    start = html.find("window.__REPORT_DATA__ = ") + len("window.__REPORT_DATA__ = ")
    data = json.loads(html[start:html.find("</script>", start)].rstrip().rstrip(";"))
    codes = sorted(data["signals"])
    assert codes, "载荷里没有证券代码，测试前提不成立"

    missing = [c for c in codes if c not in names.index]
    assert not missing, f"有代码查不到名称：{missing[:5]}"
    abbr = abbreviate(names.reindex(codes))
    dup = abbr[abbr.duplicated(keep=False)]
    assert dup.empty, f"看板内简称重复：{sorted(dup.items())[:5]}"
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe -m pytest tests\test_dashboard_names.py -q
```

Expected: FAIL，`ImportError: cannot import name 'abbreviate'`。

- [ ] **Step 3: 实现 `abbreviate`**

在 `src/etf_rotation/data/universe.py` 末尾追加。模块顶部已 `import pandas as pd` 与 `from __future__ import annotations`，需要补 `import re`。

```python
# 名称里可丢弃的份额/渠道后缀。顺序有意义：(QDII-LOF-FOF) 必须先于 (QDII)。
_ABBR_SUFFIXES = ("(QDII-LOF-FOF)", "(QDII-LOF)", "(QDII)", "(LOF)")


def abbreviate(names: pd.Series) -> pd.Series:
    """把 fund_basic 的正式名称裁成简称。

    只剥后缀与结尾的 `-CNY`，不截断、不改主体。剥完为空则退回原名。
    实测 971 个标的按此规则无重名，截断到 12 字则会撞出 14 组，故不做截断。
    """
    def _one(raw) -> str:
        text = str(raw)
        for suffix in _ABBR_SUFFIXES:
            text = text.replace(suffix, "")
        text = re.sub(r"-CNY$", "", text)
        return text.strip() or str(raw)

    return names.map(_one).rename("abbr")
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_dashboard_names.py -q
```

Expected: 3 passed。

- [ ] **Step 5: 提交**

```powershell
git add src/etf_rotation/data/universe.py tests/test_dashboard_names.py
git commit -m "feat(universe): 证券名称裁剪为简称"
```

---

### Task 2: 载荷新增第 49 键 `names`

**Files:**
- Modify: `src/etf_rotation/report/dashboard.py:914`（`tickers` 方法之后插入 `names`）、`:1790`（`BUILD_ORDER`）、`:1801`（`BUILDER_METHODS`）
- Modify: `tests/test_dashboard_data.py:69-81`（键数断言）
- Test: `tests/test_dashboard_names.py`（追加）

**Interfaces:**
- Consumes: `universe.abbreviate`（任务 1）
- Produces: `BUILD_ORDER` 变 49 项，`"names"` 追加在末尾。`DashboardBuilder.names() -> dict[str, str]`，键是 payload 里出现过的全部证券代码，值是简称。

- [ ] **Step 1: 把 `builder` fixture 移到 `tests/conftest.py`，修正 fund_basic 打桩**

`tests/test_dashboard_names.py` 也需要 `builder`，但两个测试文件不能互相 import（`tests/` 无 `__init__.py`，`pythonpath` 只含 `src`）。把 fixture 搬到 `tests/conftest.py`，两个文件按参数名取用。

`tests/conftest.py` 现在只有 4 行 `sys.path` 补丁，改完后变成：

```python
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]


def _real_run_dir() -> Path | None:
    """返回 reports/latest.json 指向的 run 目录；run 不存在返回 None。"""
    latest_path = ROOT / "reports" / "latest.json"
    if not latest_path.exists():
        return None
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    run_id = latest.get("run_id")
    if not run_id:
        return None
    run_dir = ROOT / "reports" / "runs" / run_id
    if not (run_dir / "meta.parquet").exists():
        return None
    return run_dir


@pytest.fixture
def builder(monkeypatch):
    """真实 run 的 DashboardBuilder；价格面板与分类打桩（200 万行，太慢）。

    fund_basic 打桩必须带 `name` 列：`DashboardBuilder.names()` 会读它，
    只给 `ts_code` 会抛 KeyError，让全量载荷用例连带变红。
    """
    import pandas as pd

    run_dir = _real_run_dir()
    if run_dir is None:
        pytest.skip("真实 run 缺失（reports/latest.json 无有效 run_id）")
    from etf_rotation import pipeline
    from etf_rotation.data import universe
    from etf_rotation.report.context import ReportContext
    from etf_rotation.report.dashboard import DashboardBuilder

    idx = pd.to_datetime(["2024-01-02", "2024-01-03"])
    prices = pd.DataFrame({"A": [10.0, 10.1]}, index=idx)
    fund_basic = pd.DataFrame({"ts_code": ["A"], "name": ["测试A"]})
    monkeypatch.setattr(pipeline, "load_prices", lambda: (prices, prices, prices))
    monkeypatch.setattr(pipeline, "load_fund_basic", lambda: fund_basic)
    monkeypatch.setattr(universe, "classify", lambda _: {})
    ctx = ReportContext.load(run_dir)
    return DashboardBuilder(ctx, run_dir, run_dir.parent.parent)
```

然后从 `tests/test_dashboard_data.py` 删掉 `_real_run_dir`、`builder` fixture（第 34 至 63 行）以及不再需要的 `ReportContext` / `DashboardBuilder` / `ROOT` / `json` / `Path` 导入，只保留 `BUILDER_METHODS`、`BUILD_ORDER`、`dumps` 三个导入。

- [ ] **Step 2: 写失败的测试**

在 `tests/test_dashboard_names.py` 追加：

```python
def test_names_cover_every_code_in_payload(builder):
    payload = builder.build(only=["names", "signals", "tickers"])
    names = payload["names"]
    codes = set(payload["signals"]) | {r["t"] for r in payload["tickers"]}
    assert codes, "payload 里没有证券代码，测试前提不成立"
    assert codes <= set(names), f"缺简称：{sorted(codes - set(names))[:5]}"
    assert all(isinstance(v, str) and v for v in names.values())


def test_names_is_last_key_in_build_order():
    from etf_rotation.report.dashboard import BUILDER_METHODS, BUILD_ORDER

    assert len(BUILD_ORDER) == 49
    assert len(set(BUILD_ORDER)) == 49
    assert BUILD_ORDER[-1] == "names"
    assert BUILDER_METHODS["names"] == "names"
```

`builder` fixture 来自 `tests/conftest.py`，测试函数直接声明参数 `builder` 即可，**不要**写跨文件 import。实测 `from tests.test_dashboard_data import builder` 会抛 `ModuleNotFoundError: No module named 'tests'`。

同时把 `tests/test_dashboard_data.py` 的键数断言改掉：

```python
def test_build_order_49_unique_stable():
    assert len(BUILD_ORDER) == 49
    assert len(set(BUILD_ORDER)) == 49
    assert BUILD_ORDER == [
        "meta", "kpi", "kpiTable", "params", "paramSnapshot", "series", "monthly",
        "months", "annual", "drawdowns", "longest", "stats", "events", "candidates",
        "signals", "tickers", "topPnl", "trades", "diary", "holdingsTop",
        "top10Changes", "regimeIntervals", "budgetSegments", "stages", "stageOrder",
        "contribution", "turnoverDecomp", "costByYear", "sweeps", "grid2d",
        "costLadder", "dsr", "ablation", "assumption", "oos", "oosOverride",
        "regime", "attribution", "exposureSummary", "exDef", "dataQuality", "gap",
        "issues", "lagScan", "roundtrips", "slippage", "capacity", "dist", "names",
    ]
```

同步改该文件第 1 行与第 4 行的「48 键」字样为「49 键」。

- [ ] **Step 3: 跑测试确认失败**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe -m pytest tests\test_dashboard_names.py tests\test_dashboard_data.py -q
```

Expected: FAIL，`assert 48 == 49`，以及 `KeyError: 'names'`。`tests/conftest.py` 的 fixture 改动不应让既有用例变红，如果它们红了说明打桩改错了。

- [ ] **Step 4: 加 `names` 构建方法**

在 `src/etf_rotation/report/dashboard.py` 的 `tickers` 方法（L914）之后插入，与 `# 16 ── tickers` 同风格：

```python
    # 17 ── names
    def names(self) -> dict:
        return self._c("names", self._build_names)

    def _build_names(self):
        from etf_rotation import pipeline
        from etf_rotation.data import universe

        codes = set(self.cls_map())
        if self.tsig is not None:
            codes.update(str(t) for t in self.tsig.index.get_level_values(1).unique())
        fb = pipeline.load_fund_basic()
        raw = fb.set_index("ts_code")["name"]
        abbr = universe.abbreviate(raw)
        # 查不到或简称为空串时回落成代码本身，前端无需再做空值判断
        return {c: abbr.get(c) or c for c in sorted(codes)}
```

注意兜底写 `abbr.get(c) or c`，不能写 `abbr.get(c, c)`。任务 1 的 `abbreviate` 对缺名/非字符串输入返回**空串**（不是缺失值），`abbr.get(c, c)` 只在不存在的键上兜底，空串会照原样传出去，看板单元格会显示空白而不是代码。

把 `"names"` 加到 `BUILD_ORDER` 末尾（`"dist"` 之后），`BUILDER_METHODS` 里加 `"names": "names",`。

同时把模块 docstring（L2、L5）、类注释（L155）、段落注释（L274）、`build_dashboard` docstring（L1913）里的「48 键」改成「49 键」。

- [ ] **Step 5: 跑测试确认通过**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_dashboard_names.py tests\test_dashboard_data.py -q
```

Expected: 全部 passed。`test_full_payload_dumps_parses_cleanly` 会真实构建 49 键，耗时约 30 秒。

- [ ] **Step 6: 提交**

```powershell
git add src/etf_rotation/report/dashboard.py tests/conftest.py tests/test_dashboard_data.py tests/test_dashboard_names.py
git commit -m "feat(report): 载荷新增 names 键（49 键）"
```

---

### Task 3: 前端查表函数与悬浮格式统一

**Files:**
- Modify: `reports/front-design/index.html:547`（`esc` 之后加 `nm` / `nmHtml`）、`:1048`（`window.OD` 导出）

**Interfaces:**
- Consumes: `D.names`（任务 2）
- Produces:
  - `nm(code) -> str`：返回简称。查不到回落代码本身。
  - `nmHtml(code) -> str`：返回带 `title` 的 span，`title` 里是代码，正文是简称。已过 `esc`。
  - 两者挂到 `window.OD`，供 `OD.nm` / `OD.nmHtml` 使用。
  - 同时把已有的 `TBL` 表实例表挂到 `OD.TBL`。渲染测试要靠它读列配置和行数据，现在它只是闭包内的 `var TBL = {}`（L762），外部拿不到。

**作用域注意（必读）：** 模板有三个 IIFE。第一个（L533 到 L1064）定义 `nm` / `nmHtml` / `Tbl` / `csv` / `detail` 渲染，可直接用裸名 `nm(...)`。第二个（L1065 起）是全部 `T.*` 表格函数，第三个（L1578 起）是全部 `B.*` 绘图函数。这两个 IIFE 顶部只解构了 `var O = window.OD`，**没有**裸 `nm` 可用。这两段里一律写 `O.nm(...)`。

具体到行号：
- 用裸 `nm(...)`：L786（`filtered`）、L809-811（`Tbl` 单元格）、L880 / L884 / L885 / L886 / L887（`detail` 面板）、L867 / L972（`sigTicker`）、L968（下拉填充）、`csv()`（L833）内。
- 用 `O.nm(...)`：L1107 与 L1191（第二个 IIFE）、L2008 / L2011 / L2175（第三个 IIFE）。

行号以 Task 3 落地后为准（Task 3 在 L548 插入两行，使 L547 之后的所有行号比原计划 +2）。

- [ ] **Step 1: 写失败的测试（浏览器断言）**

新建 `tests/test_dashboard_render.py`。注意 harness 的属性引号必须用双引号：实测 Chrome `--dump-dom` 会把属性统一序列化成双引号，用单引号写正则匹配不到输出。

```python
"""看板渲染断言：用无头 Chrome 读真实产物，确认证券简称与代码都出现在该出现的地方。

前提：`reports/dashboard.html` 已由 `scripts/build_dashboard.py` 生成。
缺失时 skip，不静默通过。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def _dump(harness_html: Path, budget_ms: int = 40000) -> str:
    if shutil.which("chrome") is None and not CHROME.exists():
        pytest.skip("缺 Chrome，跳过渲染断言")
    exe = str(CHROME) if CHROME.exists() else "chrome"
    proc = subprocess.run(
        [exe, "--headless=new", "--disable-gpu", "--allow-file-access-from-files",
         f"--virtual-time-budget={budget_ms}", "--dump-dom", harness_html.as_uri()],
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    return proc.stdout


def _probe(script: str) -> dict:
    dash = ROOT / "reports" / "dashboard.html"
    if not dash.exists():
        pytest.skip(f"缺产物：{dash}")
    tmp = Path(tempfile.mkdtemp(prefix="dash_probe_"))
    harness = tmp / "h.html"
    harness.write_text(
        '<!doctype html><html><head><meta charset="utf-8"></head><body>'
        f'<iframe id="f" src="{dash.as_uri()}" style="width:1500px;height:950px"></iframe>'
        f'<pre id="out">pending</pre><script>const f=document.getElementById("f");'
        'f.addEventListener("load",()=>setTimeout(()=>{'
        f"{script}"
        'document.getElementById("out").textContent=JSON.stringify(RESULT);'
        "},12000));</script></body></html>",
        encoding="utf-8",
    )
    dom = _dump(harness)
    match = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
    assert match, "harness 没有输出"
    return json.loads(match.group(1))


@pytest.fixture(scope="module")
def probe():
    return _probe


def test_nm_returns_abbreviation_and_falls_back_to_code(probe):
    """nm 查表返回简称，查不到时回落成代码本身；nmHtml 把代码放进 title。"""
    result = probe(
        "const w=f.contentWindow; const RESULT={};"
        "RESULT.typeNm=typeof w.OD.nm; RESULT.typeHtml=typeof w.OD.nmHtml;"
        "RESULT.hasNames=!!(w.OD.D&&w.OD.D.names);"
        "RESULT.sample=w.OD.nm('513100.SH');"
        "RESULT.missing=w.OD.nm('999999.SH');"
        "RESULT.html=w.OD.nmHtml('513100.SH');"
    )
    assert result["typeNm"] == "function", "OD.nm 没有导出"
    assert result["typeHtml"] == "function", "OD.nmHtml 没有导出"
    assert result["hasNames"], "载荷里没有 names 键"
    assert re.search(r"[\u4e00-\u9fa5]", result["sample"]), f"nm 未返回简称：{result['sample']}"
    assert result["missing"] == "999999.SH", f"nm 未回落成代码：{result['missing']}"
    assert 'title="513100.SH"' in result["html"], f"nmHtml 的 title 不含代码：{result['html']}"
    assert result["sample"] in result["html"], f"nmHtml 的正文不含简称：{result['html']}"
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\build_dashboard.py
.venv\Scripts\python.exe -m pytest tests\test_dashboard_render.py -q
```

Expected: FAIL，`OD.nm 没有导出`。此时 `reports/dashboard.html` 已含 `names` 键（Task 2 的产物），所以 `hasNames` 已经是 true，只有 `nm`/`nmHtml` 缺失。

- [ ] **Step 3: 加查表函数并导出**

在 `reports/front-design/index.html` 的 `esc`（L547）之后插入两行：

```javascript
function nm(c) { var n = D && D.names ? D.names[c] : null; return n || String(c == null ? "" : c); }
function nmHtml(c) { return '<span title="' + esc(c) + '">' + esc(nm(c)) + "</span>"; }
```

在 `window.OD = {` 的字面量里加两项。L1052 的 `TABLES: {},` 改成 `TABLES: {}, TBL: TBL,`，L1053 的 `esc: esc,` 改成 `esc: esc, nm: nm, nmHtml: nmHtml,`。

- [ ] **Step 4: 跑测试确认通过**

```powershell
.venv\Scripts\python.exe scripts\build_dashboard.py
.venv\Scripts\python.exe -m pytest tests\test_dashboard_render.py -q
```

Expected: 1 passed。同时确认 `OD.TBL` 也导出了（Task 4 要用）。下面的探针顺手验一下：

```powershell
.venv\Scripts\python.exe -c @"
import json,pathlib,re,subprocess,tempfile
dash=pathlib.Path('reports/dashboard.html').resolve()
h=pathlib.Path(tempfile.mkdtemp())/'h.html'
h.write_text('<iframe id="f" src="'+dash.as_uri()+'"></iframe><pre id="out">pending</pre><script>const f=document.getElementById("f");f.addEventListener("load",()=>setTimeout(()=>{const w=f.contentWindow;document.getElementById("out").textContent=JSON.stringify({hasNm:typeof w.OD.nm,hasTBL:typeof w.OD.TBL,sample:w.OD.nm("513100.SH"),html:w.OD.nmHtml("513100.SH")});},12000));</script>',encoding='utf-8')
dom=subprocess.run([r'C:\Program Files\Google\Chrome\Application\chrome.exe','--headless=new','--disable-gpu','--allow-file-access-from-files','--virtual-time-budget=40000','--dump-dom',h.as_uri()],capture_output=True,text=True,encoding='utf-8').stdout
print(re.search(r'<pre id="out">(.*?)</pre>',dom,re.S).group(1))
"@
```

Expected: `{"hasNm":"function","hasTBL":"object","sample":"国泰纳斯达克100ETF","html":"<span title=\"513100.SH\">国泰纳斯达克100ETF</span>"}`。`hasTBL` 必须是 `object`，Task 4 的测试靠它。

- [ ] **Step 5: 提交**

```powershell
git add reports/front-design/index.html tests/test_dashboard_render.py
git commit -m "feat(dashboard): 前端新增简称查表与悬浮渲染"
```

---

### Task 4: 表格渲染点改造（9 张表）

**Files:**
- Modify: `reports/front-design/index.html:811`（`Tbl` 单元格统一加 `title`）、`:807`（`fmt` 支持简称）
- Test: `tests/test_dashboard_render.py`（追加）

**Interfaces:**
- Consumes: `nm` / `nmHtml`（任务 3）
- Produces: `Tbl` 列配置新增两个可选项。`c.code` 为真时该列是证券代码列，单元格正文换成简称、`title` 放代码。`c.code` 为 `"both"` 时正文是「简称 代码」、`title` 放简称。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_dashboard_render.py` 追加：

```python
def test_narrow_ticker_columns_show_name_only(probe):
    """窄列（panoramaTable 标的 108px、topPnlTable 标的 165px）正文只放简称。"""
    result = probe(
        "const d=f.contentDocument; const RESULT={};"
        "['panoramaTable','topPnlTable','rtTable','tradeTable','candTable'].forEach(id=>{"
        "const el=d.getElementById(id); if(!el)return;"
        "const td=el.querySelector('tbody tr td:nth-child('+(id==='tradeTable'||id==='candTable'?2:1)+')');"
        "if(td)RESULT[id]={text:td.textContent.trim(),title:td.getAttribute('title')};});"
    )
    for mount, cell in result.items():
        assert not re.search(r"\d{6}\.(SH|SZ|CSI)", cell["text"]), f"{mount} 正文仍有代码：{cell}"
        assert re.search(r"\d{6}\.(SH|SZ|CSI)", cell["title"] or ""), f"{mount} 缺代码悬浮：{cell}"


def test_wide_ticker_columns_show_both(probe):
    """宽列（holdTable 标的 456px、extremeTable top3 550px、eventTable 前三大变动 380px）保留代码。"""
    result = probe(
        "const d=f.contentDocument; const RESULT={};"
        "const hd=d.querySelector('#holdTable tbody tr td:nth-child(2)');"
        "if(hd)RESULT.holdTable=hd.textContent.trim();"
        "const ex=d.querySelector('#extremeTable tbody tr td:nth-child(5)');"
        "if(ex)RESULT.extremeTable=ex.textContent.trim().slice(0,90);"
        "const ev=d.querySelector('#eventTable tbody tr td:nth-child(5)');"
        "if(ev)RESULT.eventTable=ev.textContent.trim().slice(0,90);"
    )
    for mount, text in result.items():
        assert re.search(r"[\u4e00-\u9fa5]", text), f"{mount} 没有简称：{text}"
        assert re.search(r"\d{6}\.(SH|SZ|CSI)", text), f"{mount} 没有代码：{text}"


def test_csv_export_has_both_name_and_code(probe):
    """CSV 里标的列必须同时有简称和代码，否则导出后无法与其他表关联。

    直接调用产品代码 `OD.csv`，不复刻取值逻辑：复刻测的是测试自己，不是产品。
    断言落在「标的列那一格」上，不是整行：整行里还有类别、状态等中文字段，
    只查整行会让缺简称的回归漏过。
    Blob 与 click 都要替换在 iframe 的 realm 上：`csv()` 在 iframe 内运行，
    解析到的是 iframe 的全局对象。替换父页面的 `window.Blob` 抓不到文本，
    真实 `a.click()` 又会触发下载让无头 Chrome 卡死。
    """
    result = probe(
        "const w=f.contentWindow;"
        "const RESULT={hasCsv:typeof w.OD.csv, tables:[]};"
        "const OB=w.Blob, OC=w.HTMLAnchorElement.prototype.click;"
        "w.HTMLAnchorElement.prototype.click=function(){};"
        "function capture(cfg){let cap=null;"
        "w.Blob=function(parts,opts){cap=parts.join('');return new OB(parts,opts);};"
        "try{ w.OD.csv(cfg); }finally{ w.Blob=OB; }"
        "return cap||'';}"
        "try{"
        "Object.keys(w.OD.TBL).forEach(function(id){"
        "const inst=w.OD.TBL[id]; if(!inst||!inst.cfg)return;"
        "const cols=inst.cfg.cols||[];"
        "let j=-1; cols.forEach(function(c,k){ if(c.code && j<0) j=k; });"
        "if(j<0)return;"
        "const rows=(inst.cfg.rows||[]).slice(0,3); if(!rows.length)return;"
        "RESULT.tables.push({id:id, j:j, label:String(cols[j].label), mode:cols[j].code,"
        "text:capture({cols:cols, rows:rows, csv:'probe'})});"
        "});"
        "} finally { w.Blob=OB; w.HTMLAnchorElement.prototype.click=OC; }"
    )
    assert result["hasCsv"] == "function", "OD.csv 没有导出"
    got = {t["id"] for t in result["tables"]}
    for want in CODE_CELL_TABLES:
        assert want in got, f"{want} 的标的列没有 code 标记（命中：{sorted(got)}）"
    for t in result["tables"]:
        lines = [ln for ln in t["text"].split("\r\n") if ln]
        assert lines, f"{t['id']} 的 CSV 没有内容"
        header = next(csv.reader([lines[0].lstrip("\ufeff")]))
        assert header[t["j"]] == t["label"], f"{t['id']} 表头错位：{header}"
        for line in lines[1:]:
            cell = next(csv.reader([line]))[t["j"]]
            assert re.search(r"[\u4e00-\u9fa5]", cell), f"{t['id']} 标的列缺简称：{cell}"
            assert re.search(r"\d{6}\.(SH|SZ|CSI)", cell), f"{t['id']} 标的列缺代码：{cell}"


def test_panorama_search_matches_name_and_code(probe):
    """panoramaTable 搜索框既能按代码也能按简称命中。"""
    result = probe(
        "const d=f.contentDocument, w=f.contentWindow;"
        "const el=d.getElementById('panoramaTable'); const inst=w.OD.TBL[el.id];"
        "const se=el.querySelector('.search');"
        "function run(q){inst.q=q;inst.page=0;se.value=q;"
        "se.dispatchEvent(new Event('input',{bubbles:true}));"
        "return el.querySelector('.meta').textContent;}"
        "const row=inst.cfg.rows[0];"
        "const RESULT={code:run(row.t), name:run(w.OD.nm(row.t)), all:run('')};"
    )
    total = int(result["all"].split()[0].replace(",", ""))
    for key in ("code", "name"):
        filtered = int(result[key].split()[0].replace(",", ""))
        assert filtered < total, f"按 {key} 搜索没有收窄结果（{filtered} / {total}）"
    assert result["code"] == result["name"], "按代码与按简称命中的行数不一致"
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_dashboard_render.py -q
```

Expected: 4 条新用例全 FAIL。

- [ ] **Step 3: 改造 `Tbl` 的单元格渲染与搜索匹配**

把 `reports/front-design/index.html:809-811` 三段换成：

```javascript
        var txt = c.fmt ? (typeof c.fmt === "function" ? c.fmt(v, r) : fmtBy(c.fmt, v)) : (v == null ? "—" : esc(v));
        var ttl = "";
        if (c.code) {
          if (c.code === "both") { txt = esc(nm(v)) + " " + esc(v); ttl = nm(v); }
          else { txt = esc(nm(v)); ttl = String(v); }
        }
        var klass = (c.num ? "num " : "") + (typeof c.cls === "function" ? c.cls(v, r) : (c.cls || "")) + (c.wrap ? " wrap" : "");
        return "<td class='" + klass.trim() + "'" + (ttl ? ' title="' + esc(ttl) + '"' : "") + ">" + txt + "</td>";
```

注意这里用 `esc(nm(v))` 自己拼，**不要用 `nmHtml(v)`**。`nmHtml` 返回的是已经转义过的 HTML 字符串，把它塞进 `innerHTML` 会原样显示 `&lt;span…`。`nmHtml` 只在需要「一段完整可信 HTML」的地方用，`Tbl` 的单元格不是。

搜索框原本只匹配列的原始值，改成简称后按代码就搜不到了。把 L786 的 `filtered()` 匹配条件换成同时看原始值和简称：

```javascript
    if (q) rows = rows.filter(function (r) { return (cfg.cols || []).some(function (c) { var v = typeof c.k === "function" ? c.k(r) : r[c.k]; var hay = String(v == null ? "" : v); if (c.code) hay += " " + nm(v); return hay.toLowerCase().indexOf(q) >= 0; }); });
```

同时改 `csv()`（L827）让导出的标的列带代码。`csv()` 目前没有挂在 `OD` 上，Step 4 会把它导出去，测试才能调到真函数：

```javascript
      if (c.code) { v = c.code === "both" ? nm(v) + " " + v : nm(v) + " (" + v + ")"; }
      else if (c.csv) v = c.csv(v, r);
      else if (c.fmt) v = typeof c.fmt === "function" ? String(c.fmt(v, r)).replace(/<[^>]+>/g, "") : fmtBy(c.fmt, v);
```

- [ ] **Step 3b: 把 `csv` 挂到 `OD`**

L1057 的 `Tbl: Tbl, tableMounts: tableMounts,` 改成 `Tbl: Tbl, csv: csv, tableMounts: tableMounts,`。

理由：`csv()` 能导出时带不带代码是本次改动的对外行为，必须测产品代码本身。不导出的话测试只能自己复刻一遍取值逻辑，那测的是复刻，不是产品。

- [ ] **Step 4: 给 9 张表的标的列加 `code` 标记**

按实测宽度分两组。

窄列（正文只放简称）：L918（candTable）、L1309（topPnlTable）、L1324（tradeTable，`T.allTradeTable` 复用同一函数所以一起生效）、L1338（rtTable）、L1508（panoramaTable）。

把这几行的 `{ k: ..., label: "标的", cls: "mono" }` 改成 `{ k: ..., label: "标的", cls: "mono", code: true }`。candTable 那行是 `{ k: 0, label: "标的", cls: "mono" }`。

宽列（正文放「简称 代码」）：L936（holdTable）。

把该行的 `{ k: "t", label: "标的", cls: "mono" }` 改成 `{ k: "t", label: "标的", cls: "mono", code: "both" }`。

宽列（单元格内多条）：L1191（eventTable 前三大变动）、L1107（extremeRows 的 top3 持仓）。这两处不是标准列，改映射表达式：

L1191（在第二个 IIFE 内，用 `O.nm`）改为：

```javascript
      chg: e.changes.slice(0, 3).map(function (c) { return O.nm(c.t) + " " + c.t + " " + sgnPct(c.d); }).join(" · ") || "—",
```

L1107（在第二个 IIFE 内，用 `O.nm`）改为：

```javascript
    var i = p[0], hold = (D.holdingsTop[i] || []).slice(0, 3).map(function (h) { return O.nm(h[0]) + " " + h[0] + " " + pct(h[1], 1); }).join(" · ");
```

`detail` 面板的四处（L880 `addList` 的 `<span class="t">`、L884 `preRows`、L885 `postRows`、L886 `trRows` 的标的格、L887 `postDev`）正文用简称、`title` 放代码：

L880 的 `<span class="t">' + esc(x.t) + '</span>` 改为 `<span class="t" title="' + esc(x.t) + '">' + esc(nm(x.t)) + '</span>`。

L884 与 L885 的 `'<td class="mono">' + esc(x.t) + "</td>"` 改为 `'<td class="mono" title="' + esc(x.t) + '">' + esc(nm(x.t)) + "</td>"`。

L886 的 `'<tr><td class="mono">' + esc(x.t) + '</td>` 改为 `'<tr><td class="mono" title="' + esc(x.t) + '">' + esc(nm(x.t)) + '</td>`。

L887 的 `<span class="t">' + esc(x.t) + '</span>` 改为 `<span class="t" title="' + esc(x.t) + '">' + esc(nm(x.t)) + '</span>`。

- [ ] **Step 5: 重建并跑测试确认通过**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\build_dashboard.py
.venv\Scripts\python.exe -m pytest tests\test_dashboard_render.py -q
```

Expected: 5 passed。

- [ ] **Step 6: 实测列宽没有溢出**

`dashboard.py` 里 `TARGET_GAP` 与既有审计立场都是「1280/980/720 三档无横向溢出」。跑一遍确认宽列没撑破：

```powershell
.venv\Scripts\python.exe -c @"
import pathlib,re,subprocess,tempfile,json
dash=pathlib.Path('reports/dashboard.html').resolve()
h=pathlib.Path(tempfile.mkdtemp())/'w.html'
h.write_text('<iframe id=f src=\''+dash.as_uri()+'\' style=\"width:1500px;height:950px\"></iframe><pre id=out>pending</pre><script>const f=document.getElementById(\"f\");f.addEventListener(\"load\",()=>setTimeout(()=>{const d=f.contentDocument;const o={};d.querySelectorAll(\".twrap\").forEach(tw=>{const m=tw.closest(\".tbl\").parentElement.id;o[m]={c:tw.clientWidth,s:tw.scrollWidth};});document.getElementById(\"out\").textContent=JSON.stringify(o);},12000));</script>',encoding='utf-8')
dom=subprocess.run([r'C:\Program Files\Google\Chrome\Application\chrome.exe','--headless=new','--disable-gpu','--allow-file-access-from-files','--window-size=1600,1100','--virtual-time-budget=40000','--dump-dom',h.as_uri()],capture_output=True,text=True,encoding='utf-8').stdout
o=json.loads(re.search(r'<pre id=\"out\">(.*?)</pre>',dom,re.S).group(1))
bad={k:v for k,v in o.items() if v['s']>v['c']+1}
print('溢出表:', bad)
print('改造前只有 diaryTable/allDiaryTable 溢出 1272>1197，改造后新增溢出即回归')
"@
```

Expected: `溢出表` 只含 `diaryTable`、`allDiaryTable`（改造前已如此，属既有状态）。出现其它表就回退该表的 `code` 标记。

- [ ] **Step 7: 提交**

```powershell
git add reports/front-design/index.html tests/test_dashboard_render.py
git commit -m "feat(dashboard): 表格标的列显示简称，代码入悬浮"
```

---

### Task 5: 图表与选择器改造

**Files:**
- Modify: `reports/front-design/index.html:2000`（`topPnlChart` y 轴）、`:2003`（hover）、`:2167`（d04 hover）、`:960`（`tickerSel` 下拉）、`:859` 与 `:964`（`#sigTicker` 标题）
- Test: `tests/test_dashboard_render.py`（追加）

**Interfaces:**
- Consumes: `nm`（任务 3）
- Produces: 无新接口。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_dashboard_render.py` 追加：

```python
def test_top_pnl_chart_axis_uses_abbreviation(probe):
    result = probe(
        "const d=f.contentDocument; const gd=d.getElementById('topPnlChart'); const RESULT={};"
        "RESULT.y=gd.data[0].y; RESULT.hover=gd.data[0].hovertemplate;"
        "const t=gd.querySelectorAll('.ytick text');"
        "RESULT.tickW=Math.max.apply(null,Array.from(t).map(x=>Math.round(x.getBoundingClientRect().width)));"
        "RESULT.plotW=Math.round(gd.getBoundingClientRect().width);"
    )
    assert result["y"], "topPnlChart 没有数据"
    assert not any(re.search(r"\d{6}\.(SH|SZ|CSI)", str(v)) for v in result["y"]), "y 轴仍是代码"
    assert re.search(r"\d{6}\.(SH|SZ|CSI)", result["hover"]), "hover 里没有代码"
    assert result["tickW"] < result["plotW"] * 0.35, f"y 轴标签过宽：{result['tickW']} / {result['plotW']}"


def test_d04_hover_has_name_and_code(probe):
    result = probe(
        "const d=f.contentDocument; const gd=d.getElementById('d04Chart');"
        "const tr=gd.data.filter(t=>t.stackgroup==='h')[0];"
        "const RESULT={hover:tr.hovertemplate, name:tr.name};"
    )
    assert re.search(r"[\u4e00-\u9fa5]", result["hover"]), f"d04 hover 没有简称：{result['hover']}"
    assert re.search(r"\d{6}\.(SH|SZ|CSI)", result["hover"]), f"d04 hover 没有代码：{result['hover']}"


def test_ticker_select_and_signal_title_show_name(probe):
    result = probe(
        "const d=f.contentDocument, w=f.contentWindow; const RESULT={};"
        "const sel=d.getElementById('tickerSel');"
        "RESULT.optCount=sel.options.length;"
        "RESULT.optText=sel.options[0].textContent;"
        "RESULT.optValue=sel.options[0].value;"
        "RESULT.sigTicker=d.getElementById('sigTicker').textContent;"
        "RESULT.sigTitle=d.getElementById('sigTicker').getAttribute('title');"
    )
    assert result["optCount"] > 100, "下拉没有填充"
    assert re.search(r"[\u4e00-\u9fa5]", result["optText"]), f"下拉选项没有简称：{result['optText']}"
    assert re.search(r"\d{6}\.(SH|SZ|CSI)", result["optValue"]), "下拉 option.value 被改坏了"
    assert re.search(r"[\u4e00-\u9fa5]", result["sigTicker"]), f"D06 标题没有简称：{result['sigTicker']}"
    assert re.search(r"\d{6}\.(SH|SZ|CSI)", result["sigTitle"] or ""), f"D06 标题缺代码悬浮：{result['sigTitle']}"
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_dashboard_render.py -q
```

Expected: 3 条新用例 FAIL。

- [ ] **Step 3: 改 `topPnlChart`**

L2008 的 `y: rows.map(function (r) { return r.t; })` 改为 `y: rows.map(function (r) { return O.nm(r.t); })`。

L2011 的 `hovertemplate: "%{y}<br>%{x:.2%}<extra></extra>"` 改为 `hovertemplate: "%{y}<br>%{x:.2%}<br>%{customdata}<extra></extra>", customdata: rows.map(function (r) { return r.t; })`。

y 轴不再需要手工留宽。`axis()`（L613）与 `LAY` 的 `yaxis`（L606）都已带 `automargin: true`，Plotly 会按最长简称自己撑开。把该图 `margin.l` 从 74 改成 8，把多出来的宽度还给绘图区。Step 1 的用例已断言 `tickW < plotW * 0.35`，实测不达标再回退成 `l: 74` 并接受绘图区变窄。

- [ ] **Step 4: 改 d04 hover**
L2175（第三个 IIFE，用 `O.nm`）的 `hovertemplate: "%{y:.1%}<extra>" + t + "</extra>"` 改为 `hovertemplate: "%{y:.1%}<extra>" + O.nm(t) + " " + t + "</extra>"`。

- [ ] **Step 5: 改下拉与 D06 标题**

L968 改为：

```javascript
  sel.innerHTML = tickers.map(function (t) { return '<option value="' + t + '">' + esc(nm(t)) + " · " + t + "</option>"; }).join("");
```

L867 与 L972 两处 `$("#sigTicker").textContent = state.ticker;` 改为：

```javascript
  $("#sigTicker").textContent = nm(state.ticker);
  $("#sigTicker").setAttribute("title", state.ticker);
```

`nm` 返回的是纯文本，`textContent` 赋值不做 HTML 转义，安全。

- [ ] **Step 6: 重建并跑测试确认通过**

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\build_dashboard.py
.venv\Scripts\python.exe -m pytest tests\test_dashboard_render.py -q
```

Expected: 7 passed。

- [ ] **Step 7: 提交**

```powershell
git add reports/front-design/index.html tests/test_dashboard_render.py
git commit -m "feat(dashboard): 图表与选择器显示简称，代码入悬浮"
```

---

### Task 6: 逐键比对豁免、全量验证与文档

**Files:**
- Modify: `.superpowers/sdd/dashboard/cmp_dashboard.py:22-43`（`KNOWN_RULES`）与 `compare()` 的 `hit()` 路径处理
- Modify: `reports/回测报告.md:100`（口径说明）
- Modify: `scripts/build_dashboard.py:10`（48 → 49）
- Test: 全量 `pytest tests -q`

**Interfaces:**
- Consumes: 任务 1 到任务 5 的全部产物
- Produces: 无。

- [ ] **Step 1: 给逐键比对加豁免**

先修 `compare()` 的匹配路径。`hit()` 原本拿外层 `path`，顶层调用时 `path` 是 `""`，`known_for("")` 返回 `None`，任何前缀都匹配不上，报错文本里的 `.names` 只是拼出来的展示串。把 `hit` 改成可接收路径：

```python
    def hit(msg, at=None):
        # `at` 让调用方指定用于匹配豁免规则的路径。顶层键必须传裸键名，
        # 否则 path 是 ""，任何 KNOWN_RULES 前缀都匹配不上。
        p = path if at is None else at
        why = None if strict else known_for(p)
        if why:
            stats["known"] += 1
            stats["known_paths"].add((why, p.split("[")[0]))
        else:
            out.append(msg)
            stats["bad"] += 1
```

再把字典分支的三处调用改成传带键名的路径：

```python
        for k in list(design):
            if k not in ours:
                hit(f"{path}.{k} 缺失", f"{path}.{k}" if path else k)
                continue
            compare(ours[k], design[k], f"{path}.{k}" if path else k, out, stats, strict)
        for k in ours:
            if k not in design:
                hit(f"{path}.{k} 多余", f"{path}.{k}" if path else k)
        return out, stats
```

然后在 `cmp_dashboard.py` 的 `KNOWN_RULES` 末尾（`("trades", ...)` 之后）加一行：

```python
    ("names", "设计稿无此键（49 键契约新增，简称由当前 fund_basic 裁剪）"),
```

- [ ] **Step 1b: 验证豁免真的生效，并且没有放太宽**

```powershell
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.superpowers/sdd/dashboard'); import cmp_dashboard as C; ours={'meta':{'run_id':'R'},'names':{'513100.SH':'x'}}; des={'meta':{'run_id':'R'}}; o,s=C.compare(ours,des,'',strict=False); print('bad=',s['bad'],'known=',s['known'],o)"
```

Expected: `bad= 0 known= 1 []`

反向对照（临时过滤掉 `names` 规则，确认仍会报错）：

```powershell
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.superpowers/sdd/dashboard'); import cmp_dashboard as C; C.KNOWN_RULES=[(p,w) for p,w in C.KNOWN_RULES if p!='names']; ours={'meta':{'run_id':'R'},'names':{'513100.SH':'x'}}; des={'meta':{'run_id':'R'}}; o,s=C.compare(ours,des,'',strict=False); print('bad=',s['bad'],o)"
```

Expected: `bad= 1 ['.names 多余']`

两条都要跑。只跑正向无法区分「豁免按预期生效」和「豁免写得太宽把所有多余键都放过了」。

- [ ] **Step 2: 更新文档里的键数**

`scripts/build_dashboard.py:10` 的「48 键载荷」改「49 键载荷」。

`reports/回测报告.md:100` 的「重建 48 键载荷」改「重建 49 键载荷」，并在同段末补一句：

```
49 键中的 `names` 是本次新增：`{证券代码: 简称}`，简称由 `fund_basic.name` 剥掉 QDII/LOF/-CNY 后缀得到，供看板表格与图表显示。
```

- [ ] **Step 3: 跑逐键比对**

先跑默认模式（带豁免，这才是「通过」的判定口径）：

```powershell
$env:PYTHONIOENCODING="utf-8"
$env:PYTHONPATH="D:\project\quant_1\src"
.venv\Scripts\python.exe .superpowers\sdd\dashboard\cmp_dashboard.py 2>&1 | Select-Object -Last 25
```

Expected: `意外差异 0 条，已记录差异 1014 条`，退出码 0。`names` 行显示 `OK ok=0 bad=0 known=1`，即整块被豁免记为 1 条已记录差异。

再跑 `--strict` 作为对照：

```powershell
.venv\Scripts\python.exe .superpowers\sdd\dashboard\cmp_dashboard.py --strict 2>&1 | Select-Object -Last 3
```

Expected: `意外差异 1014 条，已记录差异 0 条`，退出码 1。这是 `--strict` 的定义使然：它关掉全部豁免，于是 1013 条历史已知差异连同 `names` 这条一起变成「意外」。

两条都要跑，因为它们的语义相反，只跑一条会得出错误结论。判定通过用默认模式；`--strict` 只用来确认豁免确实由规则驱动、而不是比对逻辑本身宽松。

- [ ] **Step 4: 跑全量单测**

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

Expected: 295 passed，0 failed。

- [ ] **Step 5: 验离线与体积**

```powershell
.venv\Scripts\python.exe scripts\build_dashboard.py
```

Expected 输出里：
- `顶层键 : 49 / 49`
- `外部引用: 0 处`
- `体积` 落在 15.68 到 15.72 MB 之间（`names` 约 28 KB）。超出 15.8 MB 说明简称没裁剪，回任务 1 查规则。

连续跑两次 `build_dashboard.py`，两次 `sha256` 必须相同。

- [ ] **Step 6: 提交**

```powershell
git add .superpowers/sdd/dashboard/cmp_dashboard.py reports/回测报告.md scripts/build_dashboard.py
git commit -m "chore(dashboard): 49 键口径同步到比对脚本与文档"
```

---

## 自检

**规格覆盖**

| 需求 | 落点 |
| --- | --- |
| 排查所有显示证券代码的地方 | 任务 4（9 张表 + detail 面板 4 处）+ 任务 5（2 张图 + 下拉 + D06 标题） |
| 有位置则增加简称 | 任务 4 的 `code: "both"`（holdTable、eventTable、extremeTable 的 top3、detail 面板） |
| 没位置则代码换简称 | 任务 4 的 `code: true`（candTable、topPnlTable、tradeTable、rtTable、panoramaTable）+ 任务 5 的 y 轴 |
| 有条件则代码入悬浮 | 任务 4 的 `title` 属性 + 任务 5 的 `hovertemplate` |
| 简称口径 | 任务 1 的 `abbreviate` |
| 载荷 49 键 | 任务 2 |

**实测数据支撑**

- 简称长度：min 4、中位 13、max 22。971 个标的无重名。截断到 12 字会撞 14 组重名，故不截断。
- 列宽实测（1600px 窗口）：eventTable 前三大变动 380px、extremeTable top3 550px、holdTable 标的 456px、candTable 标的 228px、tradeTable 标的 200px、rtTable 标的 184px、topPnlTable 标的 165px、panoramaTable 标的 108px。
- 改造前只有 `diaryTable` / `allDiaryTable` 横向溢出（1272 > 1197），这是既有状态。
- `topPnlChart` 图宽 589px，当前 y 刻度最宽 42px，`margin.l=74`。
- `names` 全量映射 JSON 约 28 KB，对 9.85 MB 载荷是 0.29% 增量。

**类型一致性**

- `abbreviate` 在任务 1 定义 `(pd.Series) -> pd.Series`，任务 2 按 Series 使用，一致。
- `nm(code) -> str` 在任务 3 定义，任务 4、5 按字符串拼接使用，一致。
- `c.code` 取 `true` / `"both"`，任务 4 的 `Tbl` 与 `csv()` 两处都判这两个值，一致。
- `BUILD_ORDER` 与 `BUILDER_METHODS` 的 `"names"` 在任务 2 同时加，键名与方法名相同，一致。

**一处已知未覆盖**

`tests/test_dashboard_render.py` 依赖 `reports/dashboard.html` 存在。缺产物时 `pytest.skip`，这一点与既有 `test_dashboard_data.py` 的 fixture 行为一致，不新增静默通过风险，但也不算 hermetic。已在任务 3 的测试文件 docstring 里写明前提。
