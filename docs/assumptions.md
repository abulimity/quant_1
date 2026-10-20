# 复现假设账本（H1–H10）

> 每条假设 → 代码位置 → 当前值 → 敏感性候选 → 是否可网格化。与
> `docs/superpowers/specs/2026-10-10-etf-rotation-design.md` §3 假设清单对应。

| # | 假设 | 代码位置 | 当前值 | 敏感性候选 | 网格化 |
|---|---|---|---|---|---|
| H1 | 趋势回归时间加权 | `signals/trend.py::_time_weights` + `params.trend.weighting` | `linear` | `exp`（指数衰减，0.05） | ✅ 标量 |
| H2 | LLT 公式 | `signals/market_state.py::llt` | Ehlers Low-Lag Filter | EMA 等价平滑 | ❌ 结构（公式级，非标量） |
| H3 | 「80 日 LLT」等价平滑 | `params.risk.llm80_alpha` | `0.0247` | 60/100/120 日等价 | ✅ 标量 |
| H4 | 整组迟滞阈值 | `params.execution.hysteresis_improve` | `0.02` | 0 / 0.05 / 0.10 | ✅ 标量 |
| H5 | 反转与动量合成权重 | `pipeline._range_score` + `params.reversal.momentum_weight` | `0.5` | 0.3 / 0.7 | ✅ 标量 |
| H6 | 反转得分构造（仅超跌修复非零） | `pipeline._range_score`（`rev=(-zbias).where(active,0)`） | 激活条件 ZBias≤-0.5 且 3 日收窄 | 全池反转分 | ❌ 结构 |
| H7 | 纳指/黄金退出阈值 | `portfolio/multi_asset.py::base_weights` + `params.multi_asset.*_exit_threshold` | `0.0` | ±0.05 | ✅ 标量 |
| H8 | 主题约束 | `data/universe.py` + `portfolio/dedupe.py`（fund_type + 名称关键词） | 大类 + 关键词聚类 | 更细分类 | ❌ 结构 |
| H9 | 复权口径 | `data/curate.py`（tushare 复权因子） | tushare 后复权 | Wind 口径 | ❌ 结构（无 Wind 无法精确量化，见设计 D7） |
| H10 | 纳指/黄金 ETF 标的 | `params.nasdaq_etf` / `params.gold_etf` | `513100.SH` / `518880.SH` | 同质标的替换 | 🔶 离散替换（手工一次性对照） |
