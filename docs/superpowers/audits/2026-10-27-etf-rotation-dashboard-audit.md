# 单文件回测看板计划 · 第三方审计报告

审计对象：`docs/superpowers/plans/2026-10-26-etf-rotation-dashboard.md`（392 行）
审计日期：2026-10-27
审计基准：工作区 `main` 分支 `e2c21ae`，工作树干净
审计方式：逐条复跑计划里的验证命令，不采信计划正文与旧会话结论

## 一、结论

计划标称「7 个 Task 全部完成」成立。构建链路、前端资产、契约测试、离线可用性、48 键载荷、逐键比对都能独立复现。

交付质量有缺陷。发现 3 条 P1、2 条 P2、4 条 P3。其中两条 P1 是读者可见的错误数字，一条 P1 是构建器的跨 run 串台。修掉 P1 之前不要把这个计划标记为收口。

下面每一个数字都来自本次实际执行的命令，命令列在第七节。

## 二、计划标称项核实

| 计划标称 | 实测 | 结论 |
|---|---|---|
| 7 个 Task 全部完成 | 两个主提交 `5019d01`、`37787fe` 都在，配套提交 `18adc2c`、`615f9b9`、`e2c21ae` 也在 | 成立 |
| `dashboard.py` 1916 行 | 1916 行，71653 字符 | 成立 |
| `dashboard_tables.py` 170 行 | 170 行 | 成立 |
| `build_dashboard.py` 121 行 | 121 行 | 成立 |
| `test_dashboard_data.py` 134 行 | 134 行 | 成立 |
| vendor plotly 4558696 B，sha256 `6d21266c…` | 4558696 B，sha256 `6d21266ce1bd7d9e5ab4e115989c70c20de0382fd973a8f26ab58619eba4d603` | 成立 |
| 全量单测 281 passed | 281 passed in 54.21s | 成立 |
| 看板 48/48 键 | 48/48 | 成立 |
| 外部引用 0 处 | 0 处 | 成立 |
| 产物 15,663,630 B | 15,663,630 B，sha256 `933b118ce798b4bb5cc1571cd8c80375dff74afcba647fa11783a350c4bce775` | 成立 |
| 重建可复现 | 重跑 `scripts/build_dashboard.py` 得到一个字节不差的同一 sha256 | 成立 |
| 逐键比对「意外差异 0 条」 | `意外差异 0 条，已记录差异 1013 条`，`KNOWN_RULES` 20 条 | 成立 |
| 真实页 `plots=43 sweeps=8 chartdivs=35 tables=34 plotly=object` | 完全一致 | 成立 |
| 对照页 0 图 | `plots=0`，`Plotly` 为 `undefined` | 成立 |
| 三档宽度无横向溢出 | 1280 / 980 / 720 三档 `scrollWidth` 等于 `clientWidth`，表格都在滚动容器内 | 成立 |
| 区间联动 `?from=2025-07-30&to=2026-07-31` | 实测 `?date=2026-07-31&from=2025-07-30&to=2026-07-31`，时序图重绘 | 成立 |
| 骨架只改 3 处（2 容器 + 1 角标） | `git show 37787fe` 只有 4 行增删，其中 1 行是把 `旧批次 · Sharpe` 原文重新排布 | 成立 |
| `class="chart"` 35 个 | 模板与产物都是 35 | 成立 |
| 热力图 family 12 个成员全脏，sha 全为 `d752bbc` | 12 个成员，12 个 `git_dirty=True`，sha 集合 `{d752bbc}`，页面角标在 | 成立 |
| Task 6 三条口径差异 | 与载荷逐值对齐，见下 | 成立 |
| 载荷无 NaN / Infinity | 数据块搜不到 `NaN`、`Infinity`、`-Infinity`，也搜不到 `</script>`、`<!--`、`<script` | 成立 |

Task 6 三条口径差异的实测值：

| 项 | 计划写的当前值 | 载荷实测 |
|---|---|---|
| `defensive.max_vol_60d` 三行 Sharpe | `[0.8698, 0.8770, 0.8709]` | `[0.8698, 0.877, 0.8709]`，x 为 `['0.02','0.03','0.04']` |
| `grid2d` 峰值 | 1.0793（corr 0.80 / 0bp） | 1.079269（corr 0.80 / 0bp） |
| 热力图 12 个脏成员 | 全 `git_dirty=True` | 12/12，sha 全 `d752bbc` |

## 三、缺陷清单

### P1-1 页面三处写死的「旧批次」文案与页面自己的数据矛盾

现象。产物 `reports/dashboard.html` 同时写着三段互斥的话。

第一段在 T05 单参数敏感性面板下方：

> 参数扫描为 2026-10-17 close 口径旧批次（默认点 Sharpe 1.039），与当前 open 口径 0.877 不可直接比绝对值

第二段在 T07 热力图标题栏：`旧批次 · Sharpe`。

第三段在 DSR 卡片右下角：`sweep 口径 0.9899（旧批次）`。

而同一个页面的「已知问题」列表写着：

> `sensitivity/*.json` 的 8 组网格为 2026-10-25 open 口径，默认点 Sharpe 0.877 与本期一致

证据。`reports/sensitivity/*.json` 的 `generated_at` 分布在 `2026-10-25T16:08:07` 到 `2026-10-25T17:51:05`，全部是 open 口径的新批次。载荷里 8 个 `sweeps[].batch` 全是 `2026-10-25 · open 口径`。`grid2d` 所属 family `00d0a6f0e9f8` 的 `generated` 是 `2026-10-25T20:50:47Z`。DSR 卡片里的 `sweep` 是 8 个 `sensitivity/*.json` 的 `dsr` 最小值 0.9899，也就是 2026-10-25 的那批。

无头浏览器读 `body.innerText` 确认这三段都能被读者看到，`stale_close_note: true`，`older_batch_suffix: true`。

根因。这三段是设计骨架 `reports/front-design/index.html` 里随设计批次一起写进去的静态文案。计划 Task 4 的约束是「设计骨架的 CSS、绘图函数、表格函数一律不改，只补两个缺失的图表容器和一处角标」，所以这三段没人动。约束与「页面文案必须描述当前数据」这条要求冲突，计划没有识别出这个冲突。

顺带一处死数据。`dashboard.py:1388` 给 `grid2d` 生成了 `note`（`2026-10-25 open 口径；峰值 Sharpe …`），但渲染函数 `B.grid2d` 从不读 `note`。浏览器实测该文案不可见。

影响。读者看到「旧批次」会认为参数扫描不可用于本期结论，而实际数据与本期同口径可用。同一页两个相反说法，哪个都可被引用。

### P1-2 T10 脚注把 Calmar 2.05 写成 Sharpe 2.05

现象。T10「与研报差距」面板脚注写：

> 研报：20.74% / −10.13% / Sharpe 2.05

同面板表格的研报列是四行：年化收益 20.74%，最大回撤 −10.13%，Sharpe 1.94，Calmar 2.05。

证据。载荷 `gap` 为 `[["年化收益","20.74%","9.61%","-11.13pp"],["最大回撤","−10.13%","-15.79%","-5.66pp"],["Sharpe","1.94","0.88","-1.06"],["Calmar","2.05","0.61","-1.44"]]`。`dashboard_tables.py:165-170` 的 `TARGET_GAP` 也是四项。`reports/回测报告.md:14` 的四列顺序同样把 2.05 放在 Calmar。

影响。脚注与表格互相打脸，且把 Calmar 冠上 Sharpe 名字，是硬性数字错误。

同一问题的弱化版本在两份报告里也有。`reports/回测报告.md:16` 与 `reports/差距归因.md:4` 都用 `（20.74% / -10.13% / 2.05）` 这个三元组，跳过了 Sharpe 取了 Calmar，读者按惯例会读成 Sharpe。

### P1-3 构建器静默回退 `reports/derived`，跨 run 串台

现象。`DashboardBuilder.__init__` 在 run 目录没有 `derived/` 时，静默改用 `reports/derived`。

```python
# src/etf_rotation/report/dashboard.py:161-164
self.derived = self.run_dir / "derived"
if not self.derived.exists():
    alt = self.reports / "derived"
    self.derived = alt if alt.exists() else self.derived
```

证据。取一个非 latest 的 run `57ad104114db` 构造 builder。该 run 没有自己的 `derived/`。`builder.derived` 解析到 `reports\derived`，而这个目录的 `index.json` 写的 `run_id` 是 `4b303fe538c2`，是另一个 run。随后 `lagScan`、`exDef`、`attribution`、`dataQuality` 四个键都能构建成功，内容来自 `4b303fe538c2`。整份 build 走到 `dashboard.py:495 _build_series` 才抛 `TypeError: 'NoneType' object is not subscriptable`，报错跟真正的病因（派生数据串台）无关。

统计面。`reports/runs/` 下 58 个 run，只有 `4b303fe538c2` 有自带 `derived/`。其余 57 个只要指定 `--run-id` 就会先读到别的 run 的派生数据。

代码里没有任何护栏。全文件搜不到 `derived_version`，搜不到 `index.json`，只搜到 `run_id` 出现但不用来校验派生目录归属。

影响。这正好违反项目自己的纪律（AGENTS.md「持久化与证据链」）：`build_report_data.py --run-id <非 latest>` 的镜像必须是 latest 的函数，否则前端读到别的 run 的派生数据。也违反计划 Review Focus 第 1 条「载荷里任何一键如果按设计稿写死的旧值，页面就会显示另一条 run 的数字」。当前 single-run 场景没被触发，所以 `reports/dashboard.html` 本身是干净的。但构建器把「拿到别的 run 的数」当成正常路径，下次谁用 `--run-id` 出图就会中招。

修法。回退分支必须校验 `derived/index.json` 的 `run_id` 是否等于 `run_dir.name`，不等就报错退出。同时校验 `derived_version == 2`。

### P2-1 顶层 JSON 产物没有 run 绑定

现象。`reports/attribution.json`、`reports/exposure.json`、`reports/data_quality.json` 的结构里没有 `run_id`、没有 `generated_at`、没有 `git_sha`。

证据。三个文件的顶层键分别是 `['class_contribution','annual_returns']`、`['hhi_mean','effective_n_mean','hhi_max','effective_n_min','asset_class_exposure_mean']`、`['classification_counts','n_etfs','n_delisted','survivorship','source_gap']`。mtime 分别是 2026-10-25T09:41、2026-10-21T11:16、2026-10-20T22:29，而当前 run 是 2026-10-25T16:08。

数值本身对得上。`attribution.json` 的 8 个年度收益与 `4b303fe538c2` 的 `equity.parquet` 逐年复利完全一致（容差 1e-4）。`exposure.json` 的 `hhi_mean=0.226239`、`hhi_max=0.5`、`effective_n_mean=6.991287`、`effective_n_min=2.0` 用该 run 的 `weights.parquet` 按正权重 HHI 复算一致。

影响。文件值正确但来源不绑定。一旦有人把旧文件覆盖过来，页面数字无声变旧，没有任何机制能发现。对照组：`oos` 键在两个 run 之间确实不同，说明有些报告 JSON 是 per-run 的，混着两种产物容易误判。

### P2-2 契约测试不是 hermetic，缺 run 就静默跳过

现象。`tests/test_dashboard_data.py:52-53` 在 `reports/latest.json` 无效或缺 run 时 `pytest.skip`。5 条用例里有 2 条依赖这个 fixture（`test_sampled_keys_match_direct_read`、`test_full_payload_dumps_parses_cleanly`）。

证据。单独跑 `pytest tests/test_dashboard_data.py -q` 得 5 passed in 27.19s。fixture 里把 `load_prices` 换成了 2 行的假价格面板，所以「全量载荷」用例并没有在真实 1838 天数据上跑。`test_sampled_keys_match_direct_read` 只覆盖 48 键里的 `meta`、`kpi`、`stats` 三个。

影响。在干净 clone（无 `reports/`）里，剩下 3 条静态用例照过，但「全量载荷能 dumps 并解析」「抽样键与 run 直读一致」两条变 skipped，CI 报不出错。计划 Task 5 Step 3 明确写了「真实 run 缺失时 `pytest.skip`」，所以这是计划自己接受的取舍，不是实现偏离。它让 Review Focus 第 2 条（NaN 漏进 JSON 有单测钉住）在干净环境下只剩 `dumps()` 单元级保障。

### P3-1 构建脚本的体积自证在算术上不成立

现象。计划 Task 3 Step 4 写：

> `数据 9.85 MB` 加 `plotly 4.56 MB` 约等于 15.66 MB 的产物体积，两个数能对上就说明没有别的资源被内联或遗漏

实测。`9.85 + 4.56 = 14.41`，与 15.66 差 1.25 MB，对不上。

原因。`build_dashboard.py` 打印的是 `len(data_json)/1e6` 和 `len(plotly)/1e6`，单位是字符。文件按 UTF-8 落盘，中文与 `−`（U+2212）占多字节。实测字符 14,561,426，字节 15,663,630，多出 1,102,204 字节。

按字节重新算账就对得上：数据 10.94 MB + plotly 4.56 MB + 外壳 0.16 MB = 15.66 MB。

影响。这条自证是计划给 Task 3 定的通过标准之一。它现在恒为「对不上」，等于把一条有效检查用成了噪声。修法是把打印改成字节数，或直接打印 `len(data_json.encode())`。

### P3-2 计划遗留项一条已过期、三条未做

| 遗留项 | 实际状态 |
|---|---|
| `.openchamber/` 未加 `.gitignore` | 已修。`.gitignore:66` 有 `.openchamber/`，`615f9b9` 提交。计划文本未回填 |
| 热力图 family 需干净重跑 | 未做。12/12 仍脏，计划已承认 |
| `build_dashboard_data.py` 可再拆出 | 未做，文件确实不存在，计划已承认 |
| 本机 `http.server` 8765/8766/8777 未清理 | 未做。三个端口仍在 LISTEN，PID 27360 / 14820 / 22540，命令行都是 `-m http.server` |

另有一项计划没列的残留。Task 7 Step 6 写「删对照页与临时测量脚本，停掉本地 `http.server`（PID 12716）」。PID 12716 已经退出，但在跑的是 8765/8766/8777 三个，且对照页 `reports/.offline-control.html`（11,104,974 B，2026-10-27 15:44）与脚本 `.superpowers/sdd/dashboard/offline_ctrl.py` 都还留着。`.superpowers/sdd/dashboard/` 下有 226 个文件共 11.7 MB 的过程脚本。该目录被 git 忽略，仓库本身是干净的，所以只是磁盘残留，不影响交付物。

### P3-3 SDD ledger 只记了一条

`.superpowers/sdd/dashboard/progress.md` 只有 16 行，`Ledger` 段只有 `Task 1: complete`。计划第 17 行说这份计划原本只存在于对话与这个 ledger 里。ledger 与「7 个 Task 全部完成」不匹配，无法用它复核 Task 2 到 Task 7 的执行过程。

### P3-4 死代码与写死的口径字面量

`dashboard.py:1345` 把批次标签硬拼成 `f"{batch_date} · open 口径"`，不读数据里的执行口径。`dashboard.py:1357` 有 `if False else None` 的死表达式。如果 `family_id` 缺失或 summary 不在，`batch_date` 退回 `self.dates[-1]`，仍然标「open 口径」。当前不影响数字，只影响未来换口径时的正确性。

## 四、验证过但不算缺陷的项

`dist` 直方图 41 个桶合计 1837，`meta.n_days` 是 1838。差 1 是因为 `ret = self.ret.iloc[1:]` 去掉了首日，属于既定口径。

用 `np.histogram` 拿载荷 `edges` 复算得 1835，比载荷少 2。原因是样本最小值与最大值恰好等于首尾边界，重算时的左闭右开约定把它们排除了。载荷与自身 `np.histogram` 调用自洽，不是缺陷。

`ISSUES` 静态表里可核的数字都对得上：`vol_cap_scale<1` 的天数是 3，实现波动 11.65%，`defensive.top_n` 网格是 `[1,2,3,5]` 且后三点 Sharpe 全为 0.877，`stages` 事件数是 519。

## 五、计划文本自身的问题

1. 第 19 行的执行状态写「48/48 键，外部引用 0，逐键比对「意外差异 0 条」」，这三项都能复现，措辞没有夸大。
2. 第 178 行的体积自证算错了单位，见 P3-1。
3. 第 389 行的 `.openchamber/` 遗留项已过期。
4. 第 371 行「`grid2d` 的脏池未重跑，只加角标」写清了取舍，可接受。
5. 第 7 行「设计骨架的 CSS、绘图函数、表格函数一律不改」，正是 P1-1 与 P1-2 两条读者可见错误文案没被发现的直接原因。计划把「不改骨架」当成了硬约束，没给它设例外。

## 六、处置顺序

修 P1 三条再收口。

1. 把 T05 注释、T07 hint、DSR 卡片后缀改成由载荷驱动的文案，或在 `build_dashboard.py` 里做一次静态文案替换并加断言。`dashboard.py` 已经生成了正确的 `grid2d.note`，让 `B.grid2d` 读它即可。
2. 把 T10 脚注改成四项或删掉 Sharpe 一词。同时统一 `回测报告.md` 与 `差距归因.md` 里的三元组写法。
3. 给 `DashboardBuilder` 的派生目录回退加 `run_id` 与 `derived_version` 校验，不等就 `sys.exit(1)`。

P2 两条排进下一个计划。P3 里只有 P3-1 要马上改，其余是记账与磁盘残留。

## 七、复现命令

```powershell
$env:PYTHONIOENCODING="utf-8"
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$env:PYTHONPATH="D:\project\quant_1\src"

# 产物与键数
.venv\Scripts\python.exe scripts\build_dashboard.py
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m pytest tests\test_dashboard_data.py -q
.venv\Scripts\python.exe .superpowers\sdd\dashboard\cmp_dashboard.py

# 离线与渲染（需 iframe 外壳页）
chrome --headless=new --allow-file-access-from-files `
  --host-resolver-rules="MAP * ~NOTFOUND" `
  --virtual-time-budget=25000 --dump-dom <harness.html>

# 跨 run 串台复现
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'src'); from etf_rotation.report.context import ReportContext; from etf_rotation.report.dashboard import DashboardBuilder; r=__import__('pathlib').Path('reports/runs/57ad104114db'); b=DashboardBuilder(ReportContext.load(r), r, __import__('pathlib').Path('reports')); print(b.derived)"
```

`cmp_dashboard.py` 的汇总行是 `意外差异 0 条，已记录差异 1013 条`，退出码 0。用 `Select-Object -First` 截断输出会让管道提前关闭并报退出码 1，这不是脚本失败。
