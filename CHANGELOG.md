# Changelog

## v1.1.0 (2026-10-20)

- 工程化基础设施：run 身份哈希含「参数+代码+数据+执行+信号版本」（ml4t-registry-system）、append-only 登记、参数 schema 校验、H1–H10 参数化 + 假设账本（docs/assumptions.md）、Hydra multirun 网格、bronze 数据快照哈希。
- 默认执行口径切到 T+1 开盘成交（OpenRebalance）；候选参数（bull 0.30 / corr 0.85）写回默认。
- 修复 open 执行下前导纯现金日导致净值全 NaN 的 bug。
- 测试：83 passed。默认基线 open 口径 9.61% / -15.79% / 0.88 / 0.61。

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

