# 单文件回测看板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 OpenDesign 交付的看板骨架（`reports/front-design/index.html`）与当前 run 的真实回测产物接上，产出一个双击可开、断网可用的单文件 HTML 看板。

**Architecture:** 新增一个数据构建模块，从 `reports/runs/{run_id}/` 与 `reports/families/`、`reports/sensitivity/` 重算 48 个顶层键。新增一个注入脚本，把 48 键紧凑 JSON 写回设计骨架的数据块，并把 CDN 的 plotly 换成本仓库 vendor 的内联脚本。设计骨架的 CSS、绘图函数、表格函数一律不改，只补两个缺失的图表容器和一处角标。

**Tech Stack:** Python 3.10、pandas、pandas parquet（pyarrow）、Plotly 2.35.2（离线 vendor）、pytest。不新增第三方依赖。

**Spec:**
- `reports/front-design/DESIGN.md`（视觉与交互事实源）
- `reports/front-design/DESIGN-HANDOFF.md`（交接说明）
- `docs/superpowers/specs/2026-10-24-etf-rotation-report-content-spec.md`（报告内容规范）
- `docs/superpowers/specs/2026-10-25-etf-rotation-report-content-spec-frontend-v2.md`（前端版规范 v2）

**来源说明:** 本计划由 OpenChamber 会话 `ses_e891b6a89ffeBAIuvzCyEXkOkD` 与 `ses_e875852f5ffe0y6R7sYlKkxX2Q` 的对话内计划整理成文档。前一会话在上下文压缩时失败中断，计划只存在于对话与 `.superpowers/sdd/dashboard/progress.md`。本文档是该计划的落盘版本，已按实际执行结果校正。

**执行状态:** 7 个 Task 全部完成，两个提交 `5019d01`、`37787fe`。全量单测 281 passed。产物 `reports/dashboard.html` 15,663,630 B，48/48 键，外部引用 0，逐键比对「意外差异 0 条」。

## Global Constraints

- Python 一律用 `.venv\Scripts\python.exe`；运行任何 Python 前先 `$env:PYTHONIOENCODING="utf-8"`；PowerShell 读中文文件加 `-Encoding UTF8`。
- 不新增第三方依赖。plotly 只用仓库内 vendor 的那一份，构建前校验 sha256。
- 设计骨架不放宽：不新增 CSS 变量、不新增颜色/字体/间距 token、不改 `B.*` 绘图函数与 `T.*` 表格函数。
- 数据只读 `reports/`，不回写回测引擎，不重跑回测。
- `DERIVED_VERSION` 必须是 2。版本不符直接报错，不做降级。
- 载荷 JSON 必须能通过 `json.dumps(..., allow_nan=False)`。NaN 与 Infinity 一律抛错。
- `reports/*.html` 已被 `.gitignore` 忽略，产物不入库。vendor 的 4.56 MB plotly 必须入库。
- **不要整份读取 `.superpowers/sdd/dashboard/design-data.json`（10.9 MB）。** 它撑爆了上一个会话的上下文。要字段就用脚本取。
- **不要 dump 全量逐键差异。** 只看 `cmp_dashboard.py` 的汇总行。
- 提交按语义分组。实际执行时 7 个 Task 合成两个 commit：`5019d01` 装构建链路（Task 2、3、5、6），`37787fe` 装前端资产与容器（Task 1、4）。同一个文件不跨两次 commit。

## Review Focus

1. **看板数字与 run 脱节**：载荷里任何一键如果按设计稿写死的旧值，页面就会显示另一条 run 的数字。所有键必须从当前 run 现算，`kpiTable`/`gap`/`issues` 的证据性文案除外，且这三处要写明取数来源。
2. **NaN 漏进 JSON**：`json.dumps` 默认允许 NaN，浏览器 `JSON.parse` 会直接抛错，整页白屏。`dumps()` 必须传 `allow_nan=False`，并且有单测钉住。
3. **断网白屏**：模板原本用 CDN 加载 plotly。断网时页面一张图都不画且控制台报错。注入脚本必须把 CDN 那一个 `<script src=...>` 换成内联脚本，并用对照页证明「没有内联就不画」。
4. **图表容器缺失导致静默不画**：`B.navdd` 与 `B.event` 找不到容器时 `plot()` 直接 return，页面不报错也不画图。构建脚本必须校验 `#navddChart` 与 `#eventChart` 存在，缺一个就报错退出。
5. **脏工作区数据当证据**：热力图 family `00d0a6f0e9f8` 的 12 个成员 run 全部 `git_dirty=True`。这类 run 只存 sha 不存 diff，不可复现。页面必须显示「脏工作区 仅参考」角标，且报告里写明不进证据链。

---

## Task 1: plotly 2.35.2 vendor 落地

**Files:**
- Create: `reports/front-design/vendor/plotly-2.35.2.min.js`

**Interfaces:**
- Produces: 常量路径 `reports/front-design/vendor/plotly-2.35.2.min.js` 与 sha256 `6d21266ce1bd7d9e5ab4e115989c70c20de0382fd973a8f26ab58619eba4d603`，Task 3 的注入脚本按此校验。

- [x] **Step 1: 建立 vendor 目录并落盘**

从设计交付物或 CDN 取 plotly 2.35.2 的 `plotly.min.js`，存为 `reports/front-design/vendor/plotly-2.35.2.min.js`。

- [x] **Step 2: 校验文件完整性**

Run:
```
.venv\Scripts\python.exe -c "import hashlib,pathlib; b=pathlib.Path('reports/front-design/vendor/plotly-2.35.2.min.js').read_bytes(); print(len(b), hashlib.sha256(b).hexdigest())"
```
Expected: `4558696 6d21266ce1bd7d9e5ab4e115989c70c20de0382fd973a8f26ab58619eba4d603`

- [x] **Step 3: 入库**

vendor 文件与 `index.html` 同批入库，落在 `37787fe`。`18adc2c` 只跟踪了设计交付物本体（`index.html`、`DESIGN.md`、`DESIGN-HANDOFF.md`、`DESIGN-MANIFEST.json`），当时 vendor 目录还没建。

---

## Task 2: 48 键数据构建模块

**Files:**
- Create: `src/etf_rotation/report/dashboard.py`（1916 行）
- Create: `src/etf_rotation/report/dashboard_tables.py`（170 行）

**Interfaces:**
- Consumes: `etf_rotation.report.artifacts.resolve_run(root: Path, run_id: str | None = None) -> Path`、`etf_rotation.report.context.ReportContext.load(run_dir: Path, *, strict_snapshot: bool = False) -> ReportContext`
- Produces: `BUILD_ORDER: list[str]`（48 项，顺序即前端渲染顺序）
- Produces: `BUILDER_METHODS: dict[str, str]`（键 → `DashboardBuilder` 方法名，必须与 `BUILD_ORDER` 一一对应）
- Produces: `DashboardBuilder(ctx: ReportContext, run_dir: Path, reports_dir: Path)`，方法 `build(only: list[str] | None = None) -> dict`
- Produces: `build_dashboard(ctx: ReportContext, run_dir: Path, reports_dir: Path | None = None, only=None) -> dict`
- Produces: `dumps(payload) -> str`，紧凑分隔符、`ensure_ascii=False`、`allow_nan=False`

- [x] **Step 1: 固定 48 键顺序**

```python
BUILD_ORDER = [
    "meta", "kpi", "kpiTable", "params", "paramSnapshot", "series", "monthly",
    "months", "annual", "drawdowns", "longest", "stats", "events", "candidates",
    "signals", "tickers", "topPnl", "trades", "diary", "holdingsTop",
    "top10Changes", "regimeIntervals", "budgetSegments", "stages", "stageOrder",
    "contribution", "turnoverDecomp", "costByYear", "sweeps", "grid2d",
    "costLadder", "dsr", "ablation", "assumption", "oos", "oosOverride",
    "regime", "attribution", "exposureSummary", "exDef", "dataQuality", "gap",
    "issues", "lagScan", "roundtrips", "slippage", "capacity", "dist",
]
```

- [x] **Step 2: 按来源分批实现构建方法**

四批，每批写完跑一次逐键比对：

| 批次 | 键 | 口径要点 |
|---|---|---|
| 一：run 直读 | `meta` `kpi` `params` `tickers` `stats` | 主指标取 `metrics.parquet`，`kpi.s` 现算 |
| 二：run 派生 | `series` `monthly` `months` `annual` `drawdowns` `longest` `events` `stages` `stageOrder` `trades` `candidates` `signals` `diary` | `series` 39 条序列；滚动统计 `window=252, min_periods=120`；`mad` 用索引 `shift(1)` |
| 三：现算 | `contribution` `turnoverDecomp` `costByYear` `holdingsTop` `top10Changes` `regimeIntervals` `budgetSegments` `regime` | `class_contribution` 用 weights × `close.pct_change().shift(1)` |
| 四：外部产物 | `sweeps` `grid2d` `costLadder` `dsr` 加顶层 JSON 21 键 | `sweeps` 按参数值对齐，不按位置 |

- [x] **Step 3: 写 `dumps()`**

```python
def dumps(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                      default=_json_default, allow_nan=False)
```

- [x] **Step 4: 逐键比对设计原值**

Run: `.venv\Scripts\python.exe .superpowers\sdd\dashboard\cmp_dashboard.py 2>&1 | Select-Object -Last 1`

Expected: `意外差异 0 条，已记录差异 N 条`。已记录差异逐条对得上 `KNOWN_RULES` 的 20 条口径说明。

- [x] **Step 5: 提交**（与 Task 3、5、6 合并到 `5019d01`）

---

## Task 3: 注入脚本

**Files:**
- Create: `scripts/build_dashboard.py`（121 行）
- Consumes: Task 1 的 vendor、Task 2 的 `build_dashboard` / `dumps` / `BUILD_ORDER`

**Interfaces:**
- Produces: CLI `scripts/build_dashboard.py [--run-id ID] [--template PATH] [--out PATH] [--only KEY ...]`，默认读 `reports/latest.json`，默认输出 `reports/dashboard.html`
- Produces: 常量 `PLOTLY_SHA256`、`DATA_OPEN = "window.__REPORT_DATA__ = "`、`CDN_RE`

- [x] **Step 1: 校验三处前置条件**

vendor 存在且 sha256 匹配。模板含 `window.__REPORT_DATA__ = ` 且数据块以 `};` 结束。CDN 的 plotly `<script>` 恰好出现 1 次。任一不满足就 `sys.exit(1)` 并打印原因。

- [x] **Step 2: 替换数据块并内联 plotly**

```python
open_brace = start + len(DATA_OPEN)
close_tag = html.find("</script>", open_brace)
body = html[open_brace:close_tag].rstrip()
html = html[:open_brace] + data_json + html[open_brace + len(body.rstrip(";")) + 1:]
html = CDN_RE.sub(lambda _m: "<script>" + plotly + "</script>", html, count=1)
```

- [x] **Step 3: 校验两个图表容器**

```python
for cid in ("navddChart", "eventChart"):
    if f'id="{cid}"' not in html:
        print(f"错误：外壳缺少图表容器 #{cid}", file=sys.stderr)
        sys.exit(1)
```

- [x] **Step 4: 构建并检查输出摘要**

Run: `.venv\Scripts\python.exe scripts\build_dashboard.py`

Expected:
```
run_id : 4b303fe538c2
模板   : index.html
产物   : D:\project\quant_1\reports\dashboard.html
顶层键 : 48 / 48
数据   : 9.85 MB
plotly : 内联 4.56 MB  sha256 6d21266ce1bd
体积   : 15.66 MB
sha256 : 933b118ce798b4bb5cc1571cd8c80375dff74afcba647fa11783a350c4bce775
外部引用: 0 处
```

`外部引用: 0 处` 是这个 Task 的通过标准。`数据 9.85 MB` 加 `plotly 4.56 MB` 约等于 15.66 MB 的产物体积，两个数能对上就说明没有别的资源被内联或遗漏。

- [x] **Step 5: 提交**（与 Task 2、5、6 合并到 `5019d01`）

---

## Task 4: 骨架补两个图表容器与一处角标

**Files:**
- Modify: `reports/front-design/index.html`（三处）

**Interfaces:**
- Produces: DOM 容器 `#navddChart`（C1 读数带下，`height:240px`）、`#eventChart`（C3 事件表下，`height:220px`）
- Consumes: Task 2 的 `sweeps`/`grid2d` 数据、`B.navdd` / `B.event` 绘图函数

- [x] **Step 1: C1 补 `navddChart`**

```html
<div class="panel-b tight"><div class="chart" id="navddChart" style="height:240px"></div></div>
```
插在 `<div class="coregrid" id="navddStats"></div>` 之后。沿用 `.chart` 与 `.panel-b`，不加新样式。

- [x] **Step 2: C3 补 `eventChart`**

```html
<div class="panel-b tight"><div class="chart" id="eventChart" style="height:220px"></div></div>
```
插在 `<div id="eventTable"></div>` 的包壳之后。

- [x] **Step 3: T07 加脏工作区角标**

在 `<h3>corr × cost 热力图</h3>` 之后插 `<span class="tag warn">脏工作区 仅参考</span>`。复用现成 `.tag.warn`，不加新 CSS。

- [x] **Step 4: 核实容器都被画出来**

Run: `.venv\Scripts\python.exe -c "import pathlib; h=pathlib.Path('reports/front-design/index.html').read_text(encoding='utf-8'); print(h.count('class=\"chart\"'), 'id=\"navddChart\"' in h, 'id=\"eventChart\"' in h)"`

Expected: `35 True True`（设计稿原为 33 张图，补两个容器后 35）

- [x] **Step 5: 提交** `git commit -m "chore(front-design): 内联 plotly 2.35.2 与两个图表容器"`

---

## Task 5: 契约单测

**Files:**
- Create: `tests/test_dashboard_data.py`（134 行）

**Interfaces:**
- Consumes: `BUILD_ORDER`、`BUILDER_METHODS`、`DashboardBuilder`、`dumps`
- Produces: 5 条用例

- [x] **Step 1: 写静态契约测试**

```python
def test_build_order_48_unique_stable():
    assert len(BUILD_ORDER) == 48
    assert len(set(BUILD_ORDER)) == 48
    assert BUILD_ORDER == [ ... ]   # 48 项字面量，钉死顺序


def test_every_key_has_builder_method():
    assert set(BUILDER_METHODS) == set(BUILD_ORDER)
    for key in BUILD_ORDER:
        assert getattr(DashboardBuilder, BUILDER_METHODS[key], None) is not None
```

- [x] **Step 2: 写 `dumps()` 契约测试**

```python
def test_dumps_raw_decode_roundtrip_and_rejects_nan():
    payload = {"a": np.float64(1.5), "b": [np.int64(2), {"c": np.bool_(True)}],
               "d": None, "e": "中文"}
    text = dumps(payload)
    obj, end = json.JSONDecoder().raw_decode(text)
    assert end == len(text)
    with pytest.raises(ValueError):
        dumps({"nan": float("nan")})
    with pytest.raises(ValueError):
        dumps({"inf": float("inf")})
```

- [x] **Step 3: 写抽样键直读测试**

`meta.run_id` / `meta.git_sha` 直读 `meta.parquet`；`kpi.s.sharpe` 与 `stats.cost.fees` 直读 `metrics.parquet`，容差 1e-4 / 1e-8。真实 run 缺失时 `pytest.skip`。价格面板与分类重，沿用 `test_report_context.py` 的做法 monkeypatch 掉。

- [x] **Step 4: 写全量载荷测试**

```python
def test_full_payload_dumps_parses_cleanly(builder):
    text = dumps(builder.build())
    obj, end = json.JSONDecoder().raw_decode(text)
    assert end == len(text)
    assert "NaN" not in text
    assert "Infinity" not in text
```

- [x] **Step 5: 跑测试**

Run: `.venv\Scripts\python.exe -m pytest tests/test_dashboard_data.py -q`

Expected: `5 passed`

- [x] **Step 6: 提交**（与 Task 2、3、6 合并到 `5019d01`）

---

## Task 6: 报告补「看板数据口径」

**Files:**
- Modify: `reports/回测报告.md`（新增一节，插在「复现假设与差异说明」之前）

**Interfaces:**
- Consumes: Task 2 的 `cmp_dashboard.py` 里 `KNOWN_RULES` 的口径说明、`reports/families/00d0a6f0e9f8/summary.json`

- [x] **Step 1: 写三条口径差异**

必须写清这三条，并说明原因而不是只给数字：

| 项 | 设计稿 | 当前看板 | 原因 |
|---|---|---|---|
| `defensive.max_vol_60d` 三行 Sharpe（按 0.02 / 0.03 / 0.04 升序） | `[1.0313, 1.0394, 1.0339]` | `[0.8698, 0.8770, 0.8709]` | 设计稿 close 口径，当前 open 口径 |
| `grid2d` 峰值 | 1.2466（corr 0.85 / 0bp） | 1.0793（corr 0.80 / 0bp） | open 口径整体下移，成本维度由 3 档扩到 4 档 |
| heatmap family 12 个成员 run | 无标注 | 全部 `git_dirty=True`，sha 全为 `d752bbc` | 脏工作区只存 hash 不存 diff，只作参考，不进证据链 |

三行 Sharpe 必须按 `x` 升序写，不能写成执行时口述的 `[0.877, 0.8709, 0.8698]`。后者把 0.03 排到了首位，读者会对不上 `sweeps` 的横轴。

- [x] **Step 2: 写明比对方式**

写清比对脚本是 `.superpowers/sdd/dashboard/cmp_dashboard.py`，通过标准是汇总行「意外差异 0 条」。

- [x] **Step 3: 提交**（与 Task 2、3、5 合并到 `5019d01`）

---

## Task 7: 端到端验证

**Files:**
- 无新增源码。临时脚本放 `.superpowers/sdd/dashboard/`，用完清理。

**Interfaces:**
- Consumes: 全部前置任务的产物

- [x] **Step 1: 重建产物并核对键数与外部引用**

Run: `.venv\Scripts\python.exe scripts\build_dashboard.py`

Expected: `顶层键 : 48 / 48`、`外部引用: 0 处`、体积约 15.66 MB。

- [x] **Step 2: 断网对照实验**

把产物里的内联 plotly 整段替换成空串，另存为对照页。用 headless 浏览器加载对照页与真实页。

Expected: 对照页 3 条图表报错（`TypeError: ... is not a function`），真实页 0 报错。

实测真实页渲染结果（headless Chrome，`--virtual-time-budget=20000`，在 iframe 里读 `contentDocument`）：

```
plots=43 sweeps=8 chartdivs=35 tables=34 plotly=object
```

43 = 35 个 `.chart` 容器 + 8 个 `#sweeps` 子图。设计稿原本 41 张图，补两个容器后 43，与计划预期的「41 → 43」一致。

- [x] **Step 3: 三档宽度溢出检测**

用 headless Chrome 在 1280 / 980 / 720 三档宽度加载，检查 `documentElement.scrollWidth > clientWidth`，并逐个检查表格是否落在横向滚动容器内。

Run: `chrome --headless=new --window-size=<W>,900 --virtual-time-budget=15000 --dump-dom <url>`

Expected: 三档全部 `overflowX: false`、`problems: []`。

- [x] **Step 4: 区间联动**

点 `#rangeSeg button[data-r="1y"]`。

Expected: URL 变为 `?from=2025-07-30&to=2026-07-31`，时序图重绘。

- [x] **Step 5: 全量单测**

Run: `.venv\Scripts\python.exe -m pytest tests -q`

Expected: `281 passed`

- [x] **Step 6: 清理临时文件与服务**

删对照页与临时测量脚本，停掉本地 `http.server`（PID 12716）。

---

## 偏离与降级记录

1. **计划原本有两只脚本，实际合并成一只。** 对话里的定稿方案写了 `scripts/build_dashboard_data.py`（出 `reports/derived/dashboard/data.json`）与 `scripts/build_dashboard.py`（注入）两只。实现时合并为 `scripts/build_dashboard.py` 一只，数据直接进内存后注入，不再落中间 JSON。理由：中间文件 8 MB 且只被同一进程消费一次。代价是单独检查载荷形状需要写脚本调 `build_dashboard()`，不能再 `cat` 一个 JSON。
2. **三档宽度截图降级为脚本化溢出检测。** OpenChamber 的浏览器面板只有 1440 与 768 两档预设视口，无法精确到 1280 / 980 / 720。改用本机 headless Chrome 精确截图，同时写带 `overflowX` 与滚动容器感知的测量脚本做程序化断言。程序化断言比看图更硬，但截图存到了 `Temp\opencode\` 而非仓库。
3. **`grid2d` 的脏池未重跑，只加角标。** 该 family 的 12 个成员 run 全部脏工作区。重跑成本约 30 分钟且会换 `run_id`，本次选择先标注后重跑。重跑列为遗留项。
4. **`reports/回测报告.md` 的口径差异只写了 3 条。** `KNOWN_RULES` 里另有 17 条已记录差异（ticker 类归属、价格 tie、`dist` 桶边界、`oos` 微差等），本次只写了对外影响最大的 3 条，其余留在比对脚本里作为豁免清单。

## 本计划使用的验证命令

```powershell
$env:PYTHONIOENCODING="utf-8"
[Console]::OutputEncoding=[Text.Encoding]::UTF8

.venv\Scripts\python.exe scripts\build_dashboard.py
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe .superpowers\sdd\dashboard\cmp_dashboard.py
```

三条命令的结果都写进了本文档。`build_dashboard.py` 约 32 秒，全量单测约 62 秒。

## 遗留项

- `.openchamber/`（3 张前序会话的浏览器截图）未跟踪，未加 `.gitignore`，未处理。
- 热力图 family 需要干净工作区重跑，才能从「仅参考」升级为证据。
- `scripts/build_dashboard_data.py` 若后续需要单独校验载荷形状，可再拆出来。
- 本机常驻的 `http.server`（端口 8765 / 8766 / 8777，含重复进程）不属于本计划，未清理。
