# 后续待办

> 项目目标：本地复现研报《多资产 ETF 轮动策略》，验收口径「机制复现 + 指标同量级」（研报 20.74% / -10.13% / 2.05，2019-01 ~ 2026-07）。
> 当前基线（v1.1.1，默认 open + 候选参数）：9.61% / -15.79% / 0.88 / 0.61。
> 阶段一~四的条目已在 v1.0.x ~ v1.1.0 全部收口（见下）。本文件保留为历史轨迹 + 后续遗留清单。

## 后续待办（v1.1.1 整改后遗留）

- [x] 修复基准序列滞后一天：`compute_benchmark` 对 hs300 收益做了两次 `shift`。2026-10-25 已修（同日收益 + 首日置零），`lag_correlation` 峰值在 0（corr 0.512）；策略净值与 v1.1.1 零差异。
- [x] 派生数据管线（N1–N13）：`etf_rotation.report` + `scripts/build_report_data.py`，10 个 step 落到 `reports/runs/{run_id}/derived/` 并绑定 `run_id` 与输入哈希；前端渲染仍待下一阶段。
- [ ] 回测报告 v2 前端：按 `docs/superpowers/specs/2026-10-24-etf-rotation-report-content-spec.md`（C0–C11、74 项图表）重构 `run_report.py` / `plots.py` 的展示层；数据侧已就绪。
- [ ] H1-exp（指数时间权重）与 H7 纳指退出阈值 -0.05 是否采纳入默认：2026-10-25 campaign 重跑后，H1 exp（10.49% / -12.37% / 0.938 / 0.848）与 H7 -0.05（11.30% / -15.54% / 0.987 / 0.727）仍是最强候选，campaign DSR 0.9918、OOS 两段均正。由用户裁决；采纳属「改变数值」，须走 Part 1 流程。
- [x] `env_lock_hash` 已填充（requirements + Python + 关键库版本，sha256[:12]）。
- [x] `data_snapshot_id` 已改为 bronze 哈希 + `warehouse.manifest.json` 表指纹；curate 后生成清单，回测可 `verify_warehouse`。
- [ ] `plots.market_state_timeline` 的 bear 阈值线硬编码 -0.30（实际 -0.35）。
- [ ] `trade_triggers` 的「换仓」标记含 warmup/无持仓日（`held=False` 语义过宽）。
- [ ] H5 `momentum_weight` 使 range 市 score 数值减半（权重不变，仅 `ticker_signals` 的 score 量级）。

## 已完成（阶段一~四，均已收口）

- [x] 1.1 组合 34% 波动上限（只减不加）——接入主线（`pipeline._apply_portfolio_vol_cap`）。
- [x] 1.2 单 ETF 过热退出接入主线（`pipeline._apply_overheat`）。
- [x] 1.3 反转信号接入主线（`pipeline._range_score`，H5/H6）。
- [x] 1.4 整组迟滞接入主线（`pipeline._apply_hysteresis`，H4）。
- [x] 1.5 执行精度：`backtest/open_rebalance.py::OpenRebalance`（T+1 开盘 + 跳空顺延 + 停牌），等价性测试通过。
- [x] 2.1 参数接线：`pipeline` 硬编码参数接入 params.yaml，默认值不变。
- [x] 2.2 回测提速：信号预计算缓存（`pipeline._SIGNAL_CACHE` + `load_context` 缓存）。
- [x] 2.3 单参数敏感性：`run_grid.py`（稳健性分数 + 悬崖 + DSR）。
- [x] 2.4 二维热力图：`run_heatmap.py`（corr×cost）。
- [x] 2.5 参数组合调试：`reports/调参记录.md`（一次只动一个维度）。
- [x] 2.6 样本外 re-验证：2019–2023 vs 2024–2026（`reports/回测报告.md`）。
- [x] 2.7 成本敏感性：`run_sensitivity.py`（0/8/16/24bp）。
- [x] 2.8 可视化：敏感性热力图/稳健性分数接入 `run_report.py`。
- [x] 3.1 五相位两套实现收敛：删除 `execution/phases.py`，保留 `pipeline._combine_phases`。
- [x] 3.2 动量两套实现收敛：`momentum_panel` 迁入 `signals/trend.py`，`momentum_score` 薄封装。
- [x] 3.3 可投资池过滤收敛：`universe.build_pool` 与 `pipeline._daily_target` 内联过滤二选一。
- [x] 3.4 `weights.shift(1).fillna(0)` 抽公共：`execution/shift_weights.py::shift_weights`。
- [x] 3.5 现金计息决策：保留 `_CashInterest`（现金按 `(1+rf/252)` 日复利、不作独立权重资产）。
- [x] 3.6 持仓可视化现金口径：`plots.holdings_distribution` 用引擎 `cash/nav`。
- [x] 3.7 run 登记把执行口径纳入哈希：`registry.run_identity` 含 execution + append-only。
- [x] 3.8 清理陈旧/遗留代码：删除 `execution/hysteresis.py`、`gap_delay.py` 及老测试；`overheat_mask` docstring 更正。
- [x] 3.9 参数接线收尾：`slope_up/slope_down`、`trend.ann_factor`、`multi_asset.*`、`execution.phases/phase_interval`、`run_sensitivity` 的 `cash_rate` 接线或标注为研报固定常量。
- [x] 4.1 README 指标同步。
- [x] 4.2 AGENTS.md 分支名统一为 `main`。
- [x] 4.3 `docs/deepseek_hand_book.md` 与「分步实现路线」二选一：删除 `deepseek_hand_book.md`。
- [x] 4.4 版本号同步：`__version__` → 1.1.0（后 1.1.1），补 `v1.1.0` / `v1.1.1` tag。

## 历史归档

- [x] v1.0.0 全链路复现（数据 → 信号 → 组合 → 执行 → 回测 → 评估）
- [x] 代码审阅 12 条意见全部落实（docs/代码审阅意见.md）
- [x] §8.1 市场状态/纳指黄金动量前视错位修复；§8.2 震荡市 95% 重复扣减修复
- [x] bt 官方用法收敛（单次 bt.run、WeighTarget by name、Result.prices、cash/positions/fees 导出、fees 对账）
- [x] 样本外稳健性验证第一轮（2019–2023 vs 2024–2026，见 reports/回测报告.md）
- [x] 成本敏感性第一轮（0/8/16/24bp，见 reports/sensitivity.json）
- [x] 敏感性基础设施：run_grid.py（网格 + 稳健性分数 + 悬崖 + DSR）
