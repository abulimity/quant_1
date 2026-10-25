# Changelog

## Unreleased · fix: 审计整改（证据链 / 派生镜像 / 计划尾巴）

- 证据链：campaign trial 按 `run_id` 去重（49 成员位 → 40 唯一搜索 trial）；`family.json` 记录 `git_dirty/dirty_hash`，脏工作区 run 与脏 family 移出 DSR 分母；`verify_families` 校验成员 git_sha/data_snapshot_id/execution 一致性并告警 equity 首行 NaN。
- 派生镜像只跟随 latest：`build_report_data.py --mirror auto|always|never`，镜像原子替换、不残留旧 step；`verify_reports` 校验 latest ↔ derived ↔ analysis 身份。
- `performance.json` 增加 `summary.max_drawdown` 并与 metrics 对账；`DERIVED_VERSION=2` 参与 `--only` 增量判断。
- 同一 `run_id` 的写入加排它锁（`os.open(O_CREAT|O_EXCL)`），Hydra 重复候选值不再并发写坏目录。
- `collect_runs.py` 生成 `reports/index.md`；`run_report.py` 成本敏感性改读 cost family（不再混用顶层 campaign 文件）。
- 网格脚本默认 `--save-profile standard` 并落 `benchmark.parquet`。
- 全量重跑：在干净 commit `5016f25` 上重建 campaign `tuning-2026-10`（基线 `4b303fe538c2`，45 run / 12 family），旧 52 run / 14 family 归档到 `reports/legacy/pre-remediation/`；净值与 v1.1.1 零差异。
- 测试：273 passed。

## Unreleased · feat: 回测/网格持久化 v2 + 报告派生数据

- 回测产物按 run 落盘：`reports/runs/{run_id}/`（`meta/metrics/artifacts` + parquet 产物），新增 `--save-profile minimal|standard|full`（默认 standard）；`reports/latest.json` 指向最新 run，顶层保留兼容镜像。
- 三级内容寻址：`data_snapshot_id`（bronze + warehouse 表指纹）、`signal_id`（信号代码 + 参数 + 数据）、`run_id`（参数 + 代码 + 数据 + 执行口径 + signal_id）。`dirty_hash` 排除 `reports/`、`data/`，同一份代码重跑得到同一 `run_id`。
- 登记层从共享 duckdb 改为 parquet + DuckDB 只读查询，并行回测不再撞写锁；新增 family/trial 与 campaign 级 DSR（分母只计 grid/ablation/assumption）。
- 信号面板缓存 `data/cache/signals/{signal_id}/`：冷 10m00s → 热 4m36s；dtype 原样保存、原子写入、`price_hash` 防串。
- 7 个网格/消融/假设/OOS/成本脚本统一走 `store_run`，`collect_runs.py` 生成 family summary；`--keys` 支持假设敏感性分块执行。
- 报告派生层：`etf_rotation.report`（context/serialize/runner + 10 个 step）与 `scripts/build_report_data.py`，输出绑定 `run_id` 与输入 sha256；下游 `run_attribution/exposure/report` 支持 `--run-id`。
- 修 `compute_benchmark` 双重 `shift(1)`（lag 峰值回到 0、首日置零）；修 `build_equity_frame` 把 bt bootstrap 日并入索引导致 equity 首行 `nav=NaN`。
- 校验与清理：`verify_artifacts.py`（哈希 + 费用对账 + derived 溯源）、`prune_runs.py`（默认 dry-run）。
- 测试：249 passed。

## Unreleased · docs

- 全仓代码补充中文注释：`src/etf_rotation/**`（39 个文件）+ `scripts/**`（15 个文件），tests 不动。
- 注释深度：解释「为什么」+ 决策链路导航 + **代码块级粒度** + 每个计算块列出**显式计算公式**（60 条公式逐条落到注释里）。
- 补齐 21 处缺失的函数/类 docstring；`scripts/` 全部 `main()` 均有说明（用法、输出产物、口径注意事项）。
- 关键防错说明已固化到注释里：`run_oos_check.py`「全窗口建权再切片」（禁止子区间独立 `build_weights`）、`run_attribution.py` / `run_exposure.py` 的四分类映射、`shift_weights` 的 T 日信号 T+1 生效纪律。
- 顺带修正 `docs/代码审阅手册.md` 的过期描述：基线 commit 与单测数（32 → 97 passed）、`calendar.py` 日历主路径已改读 `warehouse.trading_calendar`、point-in-time 过滤已移入 `pipeline._daily_target`、`momentum_panel` 已迁至 `signals/trend.py`、默认参数（bull 0.30 / bear −0.35 / corr 0.85）、回测引擎已改 `WeighTarget` + `OpenRebalance`、`open_price` 不再是死参数、`metrics.from_stats` 不含 VaR/CVaR、`trades.csv` 已改为以引擎成交为依据、§8.1–§8.5 标注当前修复状态。
- **仅注释与 docstring 改动**：零逻辑、零数值变化。验收用剥 docstring 后的 AST dump 与改动前逐文件比对完全一致，基准回测指标与改动前 IDENTICAL。

## v1.1.1 (2026-10-21)

- 修复 `deflated_sharpe` 标准误用「候选数 N」当「观测数 T」的 bug（旧 DSR ~0.54 为公式伪影；修正后成本变体 DSR 0.985、18 变体 DSR 0.9934）。
- 假设敏感性补充多重检验（DSR / Sharpe haircut）与 H1/H7 样本外子区间复核（2019–2023 / 2024–2026）：H1 exp 与 H7 纳指 -0.05 两个子区间收益均相对默认改善，通过 DSR + OOS 两道关。
- 机制 ablation 变体登记 registry；暴露分析报告（`scripts/run_exposure.py`，HHI 0.226 / 有效持仓 6.99 / 资产类暴露）；registry 增加 `execution` 列与 `superseded` 标记。
- Hydra 网格默认执行口径 close → open（与全局默认一致）。
- 回测报告成本/OOS/执行精度表刷新为 open 口径；TODO.md 勾选、代码审阅手册更新。
- 测试：97 passed。

## v1.1.0 (2026-10-20)

- 工程化基础设施：run 身份哈希含「参数+代码+数据+执行+信号版本」（ml4t-registry-system）、append-only 登记、参数 schema 校验、H1–H10 参数化 + 假设账本（docs/assumptions.md）、Hydra multirun 网格、bronze 数据快照哈希。
- 默认执行口径切到 T+1 开盘成交（OpenRebalance）；候选参数（bull 0.30 / corr 0.85）写回默认。
- 修复 open 执行下前导纯现金日导致净值全 NaN 的 bug。
- 测试：90 passed。默认基线 open 口径 9.61% / -15.79% / 0.88 / 0.61。

## v1.0.1 (2026-10-16)

- bt 官方用法收敛：单次 `bt.run`、`WeighTarget` 按名传数（`additional_data`）、净值/收益改用 `Result.prices`。
- `BacktestResult` 暴露引擎 `cash` / `positions` / `fees`；交易成本以引擎 `strategy.fees` 对账，`metrics.json` 新增 `total_fees`。
- 基准/沪深300 保持向量化 `compute_benchmark`（bt 引擎化实测出现严重性能回退与 `PerformanceWarning` 洪水，已否决并回退）。
- 验证：全量单测 46 通过；基准回测指标与基线一致（年化 12.48%、total_fees 0.2414）。

## v1.0.0 (2026-10-12)

- 完成规则驱动多资产 ETF 轮动策略复现：数据引导、信号、组合、风控、执行、回测、评估全链路。
- 回测引擎使用 bt；可视化使用 plotly（自包含交互式 HTML，8 张图 + 指标卡）。
- 基准（计入单边 8bp 成本，2019-01 ~ 2026-07）：年化 13.64%、最大回撤 -12.98%、Sharpe 1.10、Calmar 1.05。
- 修复两处代码缺陷：市场状态/纳指黄金动量前视错位、震荡市 95% 重复扣减（见 docs/代码审阅手册.md §8）。
- 测试：33 个单测通过。
- 已知限制见 TODO.md；复现差异见 reports/回测报告.md。

