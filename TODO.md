# 后续待办

- [ ] 参数敏感性热力图（阶段 B）：已有 `scripts/run_grid.py`（网格 + 稳健性分数 + 悬崖检测 + DSR）；剩余是「信号预计算缓存」提速与二维热力图，用于过拟合「孤岛/高原」检测。
- [ ] 接入主流水线：整组迟滞、T+1 开盘+跳空顺延、组合 34% 目标波动、单 ETF 过热退出。
- [ ] 反转信号接入主线（震荡市「动量+反转」的反转部分，当前为纯动量）。
- [x] 样本外稳健性验证（时间子区间：2019–2023 vs 2024–2026）——结果见 `reports/回测报告.md`。
- [ ] 交易明细推导向量化提速（当前约 2–3 分钟）。

## 代码审阅优化（docs/代码审阅意见.md）

- [x] 拆分 `build_weights`（预计算/单日目标/五相位平滑）
- [x] 回测引擎改用 `WeighTarget`（修复 `_DailyWeights` 归一化+预留现金导致的持仓放大 bug）
- [x] 评估指标唯一取自 bt 内置统计（ffn），移除自算指标与 VaR/CVaR
- [x] 交易明细/换手以 bt 引擎 `get_transactions()`/`turnover` 为准，开放 `holdings.csv`
- [x] 参数覆盖（`--param a.b=值`）与扁平化
- [x] 内容寻址回测登记（warehouse `runs`/`run_metrics` + `reports/runs/{run_id}/manifest.json`）
- [x] 复权价/交易日历 curation 进 warehouse duckdb（`scripts/curate_data.py`），`load_prices`/`calendar` 优先读 warehouse、为空回退 bronze
- [ ] pandas-ta-classic 不引入（决策：自定义动量分/LLT/EWMA 保持手写并单测）

## 代码审阅发现（docs/代码审阅手册.md §8）

- [x] 8.1 市场状态/纳指黄金动量前视错位（`.iloc[i]` → `.loc[d]`）——已修复
- [x] 8.2 震荡市 95% 重复扣减——已修复
- [ ] 8.3 执行价 T+1 收盘、`open_price` 死参数——归入上方「接入 T+1 开盘」待办
- [ ] 8.4 反转/迟滞/跳空/过热退出/34% 未接入主线——归入上方对应待办
- [x] 8.5 参数敏感性仅成本一维——已有 `scripts/run_grid.py` 通用网格，剩余热力图与提速
