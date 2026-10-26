# 多资产 ETF 轮动 · 回测报告（单文件）— 设计说明

## 1. 交付物

- `index.html`：单文件报告，双击即可打开；数据、样式、脚本全部内嵌，仅 Plotly 2.35.2 走 CDN。
- 规模：约 10.55 MB（9.96 M 字符），含 1,838 个交易日、519 个事件日、22,433 笔成交、971 个标的、41 张 Plotly 图、34 张表。
- 语言：简体中文；深色研究终端风格；1280 / 980 / 720 三档响应式；含打印样式（打印 C0–C1 读数 + C6 的 V02 KPI 对照，共一页）。
- 章节编号沿用 C0、C1、C3–C11，C2 已整章移除，编号不重排；阅读顺序调整为 C0 → C4 → C3 → C5 → C6 → C7 → C8 → C9 → C10 → C11。

## 2. 数据与口径

唯一数据源：`D:/project/quant_1/reports/`（只读，不回写引擎）。run `5d5a64c88b30`，git `76ad294`，snapshot `cbcc8bf8953b`，版本 1.1.1，execution `T+1 开盘（OpenRebalance）`，单边成本 8bp。

| 指标 | 来源 / 口径 |
|---|---|
| 年化收益 | `metrics.json` · 日历日 CAGR（`nav_end^(365.25/days)−1`）= 9.6051% |
| 波动 / Sharpe / Sortino | 日收益 × √252；rf = 0；11.6459% / 0.877 / 1.2235 |
| 最大回撤 / Calmar | `equity.csv` nav 逐日重算；−15.7884% / 0.6084 |
| 基准 | `benchmark.csv` hs300，已与策略同日对齐；**不再二次 shift** |
| 相对指标 | 几何超额 3.6688%、算术 2.4099%、TE 16.5521%、IR 0.1456、beta 0.3114、corr 0.512 |
| 捕获率 | 上行 0.3626 / 下行 0.2917；月胜率 51.65%（91 个月） |
| 成本 | `metrics.total_fees = 0.20973`，与 `trades.cost` 求和一致；换手 4.9868% |
| 归因 | 风险 41.73% / 纳指 34.98% / 黄金 15.46% / 防守 8.29% |
| 逐日类别贡献 | duckdb `warehouse.duckdb` 的 `close_adj` × 前一日持仓估算，按类别对齐 `attribution.json` |
| 权重 | `weights.parquet` 目标权重；`holdings.csv` 实际持仓；偏差单独成图（X01） |

基准对齐自检：lag 0 相关 **0.512**、lag −1 相关 0.021，B06 扫描峰值落 0；基准止于 2026-07-31。

ES 补充口径：`derived/relative.json` 的 `ex_defensive` 直接内嵌为 `exDef`（对风险腿 corr 0.524、beta 0.587、风险腿平均权重 0.5515）。

## 3. 章节地图

| 章 | 内容 | 关键图 / 表 |
|---|---|---|
| C0–C1 报告头与核心读数 | 单一头块（headblock）：标题行 + 只读声明 + 元信息条 → 高亮读数带（4 个主读数 + 4 个辅读数，净值/回撤优先）；侧栏合并为一项 | c0Range / metaCards / navddStats |
| C4 绩效 | 净值+事件、水下、回撤表、年度、年×月热力+数字表、滚动 60/120/252 可切换（默认 252，63 为参照）、收益分布、QQ | navEventsChart / underwaterChart / ddTable / annualTable / monthHeat / monthTable / rollChart / dailyHist / qqChart |
| C3 决策审计 | 联合时间轴（共用一条时间轴、6 轨自上而下：净值/基准（关键事件菱形标注在曲线上：换手 ≥30% 或过热/波动触发）→ 回撤 → TOP10 持仓 → 状态分 → 风险预算 → 仓位/现金）→ D01 事件表 → 四步详情 → D10 市场状态区间（整行）→ D11 风险预算分段（整行）→ D05 候选池与 D06 单标的信号（同屏组合，合计一屏高）→ 24 列日记 | d04Chart / eventTable / detail / regimeTable / budgetTable / candTable / signalChart / diaryTable |
| C5 风险 | 滚动波动（34/26/18% 线）、beta/相关、捕获率、回撤期暴露、集中度（HHI/top5/有效 N）、仓位、极端日 | `volChart` / `betaChart` / `captureCards` / `ddAttrChart` / `concChart` / `posChart` / `extremeTable` |
| C6 相对基准 | 累计超额+超额回撤、滚动 IR、分年超额、月度超额、相对指标、对齐自检 → 末尾 V02 KPI 对照双栏表（不折叠，随区间联动） | `excessChart` / `exRollChart` / `yearExChart` / `monthExChart` / `relTable` / `alignChart` / `alignBanner` / `kpiTableA` `kpiTableB` |
| C7 归因与暴露 | 类别贡献、分年贡献、类别暴露、成本拖累、状态分层、剔除防守相关、top 贡献标的 | `classContribChart` / `classYearChart` / `classExpoChart` / `costDragChart` / `statePerf` / `exDefChart` / `topPnlChart` |
| C8 执行与交易 | 目标 vs 实际、换手分解、交易明细、按日持仓、持有期/盈亏分布、成本表、滑点、容量 | `x01Chart` / `turnDecompChart` / `tradeTable` / `holdTable` / `rtHoldChart` / `rtPnlChart` / `rtTable` / `costTable` / `slipChart` / `capTable` |
| C9 稳健性与可信度 | 数据质量、消融、成本阶梯、子区间、假设敏感性、8 组参数扫描、corr×cost 网格、DSR、问题清单、研报差距 | `dqTable` / `ablChart` / `costLadderChart` / `subTable` / `assumeTable` / `sweeps` / `grid2d` / `dsrCard` / `issuesList` / `gapTable` |
| C10 明细附录 | 全量交易、全量日记、标的全景、CSV 导出 | `allTradeTable` / `allDiaryTable` / `panoramaTable` |
| C11 参数备查 | 51 项参数、run 元信息、复现命令、环境、参数快照、版本页脚 | `paramTable` / `metaTableC11` / `cmdBlock` / `envTable` / `paramSnapshot` |

C1 不再有独立 `<section>`：`id="c1"` 挂在合并头块的读数带上，只作锚点与打印标记；侧栏合并为「C0–C1 头与核心读数」。

## 4. 交互

- **全局区间**：全部 / 近 3 年 / 近 1 年 / 自定义（`#dFrom` / `#dTo`）。KPI 表、区间指标卡、表格与所有时序图同步重算；越界日期自动选区间内最近事件日。
- **D04 联动**：在时间轴上框选/缩放，自动换算为全局区间并重绘全页；顶部区间按钮反向重置时间轴。
- **事件下钻**：事件表行 → 四步详情（事前持仓 → 目标变动 → 实际成交 → 事后持仓）；`#evPrev` / `#evNext` / `#evJump` 前后跳与换日，详情与时间轴游标同步。
- **候选 → 信号**：候选表行点击切换 `#sigTicker` 与 D06 单标的信号图；交易/持仓表点击切详情日期。
- **对数轴**：联合时间轴净值轨（`#navLog`，位于 C3 面板头）与水下图（`#p01Log`）各自切换，双向写入全局轴偏好。
- **P07 窗口**：滚动收益/Sharpe 支持 60 / 120 / 252 三档切换（`#p07W`），默认 252 并以 63 日为淡色参照；切换即时重算，不触发全页重绘。
- **净值 ↔ 回撤悬停联动**：C4 的 P01 与 P02 共享日期位置；悬停任一图，另一图同步显示同一交易日的回撤/净值标签（`Plotly.Fx`），两图标签均带完整日期、净值与回撤。
- **深链接**：`?date=&ticker=&from=&to=`；刷新保持状态，`idxLoose` 容错非交易日（映射到最近有效日）。
- **导航**：IntersectionObserver 滚动高亮侧栏；C0 与 C1 合并为「C0–C1 头与核心读数」；锚点滚动预留 70px 顶距。
- **导出**：每张表 CSV（UTF-8 BOM，Excel 直开）；图表悬停出现 Plotly 工具条，可导出 PNG。
- **打印**：顶栏「打印」或合并头块内的「打印本页」输出高亮读数 + C6 的 V02 KPI 双栏表（`body.print-c1` 只显示 `#c0` 与 `#c6` 末面板），一页 A4（图表不打印）；隐藏侧栏、控件与非必要表头，白底黑字。

## 5. 视觉 Token（`:root`）

| Token | 值 | 用途 |
|---|---|---|
| `--bg` / `--bg2` | `#0e1117` / `#0b1016` | 页面 / 侧栏 |
| `--panel` / `--panel2` / `--panel3` | `#10151d` / `#141a24` / `#171e2a` | 卡片层级 |
| `--line` / `--line2` | `#1d2532` / `#2a3546` | 1px 细边框 |
| `--text` / `--text2` / `--muted` / `--dim` | `#dde4f0` / `#aab6c8` / `#79869b` / `#5a6577` | 文字四级 |
| `--blue` / `--blue2` | `#4c8dff` / `#82b1ff` | 策略、主交互 |
| `--green` / `--red` | `#22c58b` / `#ff5f6d` | 盈利 / 亏损、回撤 |
| `--amber` | `#f2a93b` | 警示、事件点、当前日 |
| `--purple` / `--cyan` / `--pink` | `#a98bff` / `#35c7d8` / `#ef7fb0` | 纳指 / 防守 / 辅助 |
| 圆角 | 4px（表格/卡片）/ 3px（控件） | 不做大圆角、阴影、渐变；面板头/头块均为纯色平铺 |

字体：系统栈 + PingFang SC / Microsoft YaHei；数字统一 `ui-monospace, SFMono-Regular, Cascadia Mono, Consolas`。
栅格：`.g5` / `.g7` 支持 5/7 列并排；`.pager` 允许换行，表格容器横向滚动且首列冻结。
首屏：C0–C1 合并为一个 `headblock`（标题 + 元信息 + 高亮读数，约 240px），其下为 C4 绩效。C3 的 D05 与 D06 组成 `.duo` 同屏组合（高 `calc(100vh - 118px)`，D05 上限 44% 内滚，D06 占剩余高度）。C3 的 D04 高度取 `calc(100vh - 150px)`（640–1200px，900px 屏约 750px），比上一版进一步放大，底部日期轴保持可见，说明文字可滚动查看。

## 6. 降级规则（界面内显式说明，不画空白图）

| 缺失 | 处理 |
|---|---|
| 逐标的收益 / w×r 面板（A02/A06/A07） | 提供分年类别贡献、剔除防守相关、top 贡献标的等替代读法 |
| pipeline 五相位路径（X06） | 以 519 个事件日的四步详情替代；阶段归因瀑布已移除 |
| 成交时点 / 顺延日志 / 成交额（X03） | 以目标 vs 实际偏差与滑点分布替代，注明顺延/停牌未逐笔记录 |
| 全量持仓宽表 | 内嵌每日 top10 持仓与事件四步详情，完整矩阵不内嵌（C9 已知问题注明） |
| 参数扫描批次 | 旧 close 口径（2026-10-17，默认点 1.039）；只读 ΔSharpe 形状，标注批次日期 |
| DSR 双口径 | 主口径 `assumption_sensitivity` = 0.9934；扫描口径 `sweep` = 0.5352，分开呈现不混用 |

## 7. 数据构建与再生成

1. `build_data_v3.py`：只读 `reports/`，重建净值/回撤/事件/滚动/敏感性/归因/阶段/持有期等派生量，并读 `warehouse.duckdb` 估算逐日类别贡献与暴露，输出 `data_v3.json`（约 10.4 MB）。
2. `shell_v3.html`：11 章骨架 + 全部 CSS + 图表/表格挂载点（C2 移除，编号保留）。
3. `app_core_v3.js` / `app_tables_v3.js` / `app_charts_v3.js`：状态机、区间与下钻、表格组件、Plotly builders（`O.B` / `O.TABLES`）。
4. `build_inject_v3.py`：拼接 JS、转义 `</`、注入数据与骨架，生成 `index.html`（同时导出 `app_all_v3.js`）。

校验：`build_inject_v3.py` 输出 0 占位符；Edge headless 加载 41 张图、34 张表、Console 0 error；CDP 探针验证区间切换、D04 框选同步、P07 窗口切换、P01↔P02 悬停联动、事件下钻、标的切换、深链接与重置；关键数字抽查（9.6051% / −15.7884% / 0.877 / 3.6688pp / lag0 0.512 / 596 日）与 `metrics.json`、`performance.json` 一致。

## 8. 已知限制

- 参数扫描为 2026-10-17 close 口径旧批次（默认点 Sharpe 1.039），与当前 open 口径（0.877）不可直接比绝对值。
- `oos_check.json` 含 `multi_asset.nasdaq_exit_threshold = −0.05` 的事后 override，表中单列标注，不混入主结论。
- 组合 34% 波动目标全样本仅 3 天触发；回撤期只能看暴露，不能看逐标的贡献。
- 换手分解按目标权重变动归集，低于按成交额计算的真实换手（费用口径以 `trades.cost` 为准）。
- 逐日类别贡献为复权收盘 × 持仓估算，期末合计对齐归因，不等同于逐笔会计贡献。
- 阶段归因瀑布（D09）已移除；阶段口径只在事件四步详情中体现。
- `holdings` 经过归一化；研报差距为定性判断，未逐项重跑，定位是「同量级复现」。
