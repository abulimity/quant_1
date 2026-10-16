# 后续待办

> 项目目标：本地复现研报《多资产 ETF 轮动策略》，验收口径「机制复现 + 指标同量级」（研报 20.74% / -10.13% / 2.05，2019-01 ~ 2026-07）。当前基准 12.48% / -12.98% / 0.96（v1.0.1，46 单测通过），差距主因：日均换手约 5.6% 对成本高度敏感 + 若干机制/执行层未接入主线。
>
> 阶段顺序（已定）：先补机制、再调参。当前主攻「阶段一 机制补全」。

## 阶段一：机制补全（当前主攻，改变数值，逐个接入 + 单独验证）

> 详见 `docs/superpowers/plans/2026-10-16-etf-rotation-mechanisms.md`

- [ ] 1.1 组合 34% 波动上限（只减不加：组合 20 日 EWMA 波动超 34% 时整体等比缩减，资金转现金）。不用 `bt.algos.TargetVol`（其是双向目标，与设计 §2.6「超目标同比缩减，只减不加」冲突），复用 `risk_layers.vol_scale` 语义。
- [ ] 1.2 单 ETF 过热退出接入主线（80 日 LLT×1.2 归零；`risk_layers.overheat_mask` 已实现待接线）。
- [ ] 1.3 反转信号接入主线（震荡市「动量+反转」，动量分/反转分各自横截面标准化后 50/50 相加；H5/H6）。
- [ ] 1.4 整组迟滞接入主线（H4：新组合总得分改善 ≥2% 才换仓；按「风险轮动组」口径，原持仓仍有效才维持）。
- [ ] 1.5 执行精度（bt 框架内自定义 `OpenRebalance` Algo，不另起炉灶重写记账引擎）：T+1 开盘成交 + 跳空顺延 + 停牌；`open_price` 死参数接入。先通过与标准 Rebalance 的等价性测试（open==close 时 nav/fees 一致）再上线。

## 阶段二：调参与稳健性（机制补全后执行）

> 详见 `docs/superpowers/plans/2026-10-16-etf-rotation-tuning.md`

- [ ] 2.1 参数接线：pipeline 里硬编码但 params.yaml 已声明、未生效的参数接上（trend.windows/rank_weights、market_state.slope_window、risk.vol_window、defensive.top_n/max_vol_60d、hrp.window 等），默认值下数值不变。
- [ ] 2.2 回测提速：信号预计算缓存，把单次 2–3 分钟降到可支撑全参数网格。
- [ ] 2.3 单参数敏感性：动量窗口、相关性阈值、市场状态阈值、波动率目标、LLT α、成本等；输出稳健性分数 + 悬崖检测 + DSR/Sharpe haircut。
- [ ] 2.4 二维热力图：相关性阈值×成本、动量窗口×波动率目标等，检测过拟合「孤岛/高原」。
- [ ] 2.5 参数组合调试：在非悬崖、稳健区间局部组合，一次只动一个维度，记录调参轨迹。
- [ ] 2.6 样本外 re-验证：2019–2023 vs 2024–2026 子区间交叉检查（机制补全后需重跑）。
- [ ] 2.7 成本敏感性：`run_sensitivity.py`（0/8/16/24bp）机制补全后重跑。
- [ ] 2.8 可视化：敏感性热力图/稳健性分数接入 `run_report.py`。

## 阶段三：代码卫生与 bt 收敛搁置项（不改变数值）

- [ ] 3.1 五相位两套实现二选一：`pipeline._combine_phases` 与 `execution/phases.combine`（后者未接入）。
- [ ] 3.2 动量两套实现收敛为一套并加等价性测试：`signals/trend.momentum_score`（循环）与 `pipeline.momentum_panel`（向量化）。
- [ ] 3.3 `universe.build_pool` 与 `pipeline._daily_target` 内联可投资池过滤重复，二选一。
- [ ] 3.4 `weights.shift(1).fillna(0)` 在 `run_backtest.py`/`run_sensitivity.py`/`run_grid.py` 三处重复，抽到 `execution` 公共函数。
- [ ] 3.5 现金计息是否改「现金资产」（`cash` 列按 `(1+rf/252)` 日复利、权重补 `1-Σw`）——先决策再评估，当前保留 `_CashInterest`。
- [ ] 3.6 持仓可视化现金口径改引擎 `backtest.strategy.cash / nav`，替换 `plots.holdings_distribution` 的 `1 - w.sum(axis=1)`。
- [ ] 3.7 run 登记把执行口径纳入哈希：`registry.config_hash` 当前只哈希 params，close/open 两种 `--execution` 共用同一 run_id 互相覆盖（`INSERT OR REPLACE`），需把执行口径（含 `gap_delay_pct`）纳入 run_id，避免登记记录被覆盖。
- [ ] 3.8 清理陈旧/遗留代码：`risk_layers.overheat_mask` 的 docstring 仍写「尚未接入主流水线」（实际已由 `pipeline._apply_overheat` 接入）；`execution/hysteresis.py` 与 `execution/gap_delay.py` 及其老测试 `test_hysteresis.py`/`test_gap_delay.py` 为遗留重复实现，二选一或删除。

## 阶段四：文档与仓库维护

- [ ] 4.1 README 过期指标同步：基准 13.64%/33 测试 → 12.48%/46 测试（CHANGELOG v1.0.1 已更新，README 未同步）。
- [ ] 4.2 AGENTS.md 分支名 `master` 与实际 `main` 不一致，统一。
- [ ] 4.3 `docs/deepseek_hand_book.md` 与 `docs/用 bt 框架复现多资产 ETF 轮动策略：分步实现路线.md` 内容完全重复（MD5 相同），二选一或归档其一。

## 已完成（归档）

- [x] v1.0.0 全链路复现（数据 → 信号 → 组合 → 执行 → 回测 → 评估）
- [x] 代码审阅 12 条意见全部落实（docs/代码审阅意见.md）
- [x] §8.1 市场状态/纳指黄金动量前视错位修复；§8.2 震荡市 95% 重复扣减修复
- [x] bt 官方用法收敛（单次 bt.run、WeighTarget by name、Result.prices、cash/positions/fees 导出、fees 对账）
- [x] 样本外稳健性验证第一轮（2019–2023 vs 2024–2026，见 reports/回测报告.md）
- [x] 成本敏感性第一轮（0/8/16/24bp，见 reports/sensitivity.json）
- [x] 敏感性基础设施：run_grid.py（网格 + 稳健性分数 + 悬崖 + DSR）
