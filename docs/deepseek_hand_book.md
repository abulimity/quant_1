# 用 bt 框架复现多资产 ETF 轮动策略：分步实现路线

以下基于策略报告的逻辑，结合 bt 框架的算法链架构，给出从零开始的实现路线。bt 的核心理念是“算法链”——一个 `bt.Strategy` 接收一个算法列表，按顺序执行：**调度 → 选券 → 权重 → 再平衡**。你的策略需要围绕这条链路逐层搭建。


## 第一阶段：环境与数据基础

### 步骤 1：搭建数据层

bt 的 `Backtest` 接受一个 **DatetimeIndex 为行、每列一个标的收盘价**的 DataFrame。但你的策略需要更多维度的数据：

**需要准备的数据矩阵：**

| 数据 | 用途 | 格式要求 |
|---|---|---|
| ETF 复权价格矩阵 | 趋势回归、动量、反转、HRP 协方差估计 | 宽表，DatetimeIndex × ETF代码 |
| 指数价格矩阵 | 市场状态识别（上证/中证2000/中证红利）、A股趋势约束（创业板指） | 同上 |
| 创业板指 LLT 序列 | A股趋势约束 | Series 或附加列 |
| ETF 成交额矩阵 | 流动性筛选（20日均成交额≥500万） | 用于生成布尔筛选矩阵 |

bt 本身不提供数据下载，需要用 `akshare`、`tushare` 或 Wind 接口获取。数据质量直接决定回测可信度。

### 步骤 2：预计算所有信号（在 bt 之外完成）

**这是最关键的架构决策**。bt 的算法链更适合“选券 → 权重 → 再平衡”的调度执行，而不是逐日逐标的做复杂的时间加权回归。建议在 pandas 中预先计算好所有信号，再以 DataFrame 形式传入 bt。

需要预计算的信号：

**① 趋势得分矩阵**（每个交易日 × 每只 ETF）：

- 对每只 ETF 的复权价格对数序列做**时间加权线性回归**（近期观测权重更高）
- 提取斜率 Slope 和拟合优度 R²
- 计算 `Momentum = [exp(250 × Slope) - 1] × R²`
- 分别计算 21 日和 60 日两个窗口
- 21 日动量为负的标的标记为不可选

**② 反转信号矩阵**（每个交易日 × 每只 ETF）：

- 14 日指数移动平均线作为短期中枢
- 计算对数偏离度，用 170 日滚动均值和标准差做 Z-score → ZBias
- 标记满足条件：`ZBias ≤ -0.5 且 ZBias > ZBias.shift(3)`

**③ 市场状态序列**（每个交易日）：

- 对三个指数分别计算 LLT（α=0.10）和 8 日 LLT 斜率
- 斜率 > 1.005 → +1，< 0.995 → -1，其余 → 0
- 三指数等权平均 → 复合分数
- 映射为状态：≥0.35 强势 / ≤-0.35 危险 / 其余震荡

**④ 防守资产信号**（每 120 个交易日更新）：

- 从债券和货币 ETF 中筛选 60 日年化波动率 < 3%
- 按 60 日风险调整后动量排序，取前 5，同一细分类别仅留 1 只

这一步产出的核心是：**一个每日更新的“目标权重矩阵”**（DatetimeIndex × 所有 ETF），以及辅助的“可交易标记矩阵”。


## 第二阶段：用 bt 搭建基础回测骨架

### 步骤 3：跑通最小可运行版本

先忽略所有风控和 HRP，用最简算法链验证数据管道是否通畅：

```python
strategy = bt.Strategy('base', [
    bt.algos.RunDaily(),
    bt.algos.SelectAll(),
    bt.algos.WeighTarget(target_weights_df),
    bt.algos.Rebalance(),
])
result = bt.run(bt.Backtest(strategy, prices))
```

`WeighTarget` 接受一个目标权重 DataFrame，维度与 universe 一致时会在每个周期按该权重再平衡。**这一步的目标是确认：数据对齐、日期索引、缺失值处理都正确，且回测结果能正常输出。**

### 步骤 4：加入选券与市场状态过滤

bt 提供 `SelectWhere` 用于基于布尔矩阵过滤标的。将步骤 2 中生成的可交易标记矩阵传入：

```python
strategy = bt.Strategy('filtered', [
    bt.algos.RunDaily(),
    bt.algos.SelectWhere(selectable_df),
    bt.algos.WeighTarget(target_weights_df),
    bt.algos.Rebalance(),
])
```

此时 `target_weights_df` 应该在不可选标的的位置填 0，或者权重逻辑在选券之后动态生成。


## 第三阶段：实现核心选券与权重逻辑

### 步骤 5：实现动量 + 反转的横截面排序

bt 的 `SelectMomentum` 只做简单的收益率排序，无法满足你的“趋势得分 = 斜率 × R²”的需求。有两种方案：

**方案 A（推荐）** ：在 bt 外部完成排序，将最终选中的 ETF 列表通过自定义 `SelectThese` 类算法传入。bt 的 `SelectThese` 接受一个标的列表，适合“我已经算好了选谁”的场景。

**方案 B**：自定义一个 `SelectByScore` 算法，继承 `bt.Algo`，在 `__call__` 中读取 `target.temp` 中的得分数据，按市场状态选择排序规则，写入 `target.temp['selected']`。

无论哪种方案，核心逻辑是：

- **强势状态**：按 `0.7 × Rank(21日动量) + 0.3 × Rank(60日动量)` 排序，取前 N
- **震荡状态**：将动量得分和反转得分分别横截面标准化后相加排序
- **危险状态**：`selected` 为空列表，全部转防守

### 步骤 6：实现相关性去重

bt 没有内置的相关性去重算法。需要自定义一个 `DeduplicateByCorr` 算法：

- 在 `__call__` 中读取 `target.temp['selected']` 对应的历史收益率
- 计算相关系数矩阵
- 若两个标的相关系数 > 0.80，保留趋势得分更高者
- 再叠加主题约束（半导体、芯片等同类只留一只）
- 更新 `target.temp['selected']`

### 步骤 7：实现 HRP 权重配置

bt 内置的 `WeighERC` 是 Equal Risk Contribution，不是 HRP。需要自定义一个 `WeighHRP` 算法：

```python
class WeighHRP(bt.Algo):
    def __init__(self, lookback=250):
        self.lookback = lookback

    def __call__(self, target):
        selected = target.temp.get('selected', [])
        if not selected:
            target.temp['weights'] = {}
            return True
        # 1. 取过去250日收益率
        # 2. 计算协方差矩阵 → 相关系数矩阵 → 距离矩阵
        # 3. Single Linkage 层次聚类
        # 4. 递归二分之一分配组间权重
        # 5. 组内逆方差配置
        # 6. 归一化
        target.temp['weights'] = {sec: w for sec, w in zip(selected, weights)}
        return True
```

权重算法需要从 `target.temp['selected']` 读取选券结果，将权重写入 `target.temp['weights']`，返回 `True`。


## 第四阶段：多资产配置与分层风控

### 步骤 8：实现多资产基础配置

报告的基础配置是：风险资产 ETF 50% + 纳指 ETF 37.5% + 黄金 ETF 12.5%。bt 的 **策略树（Portfolio Tree）** 天然适合这种嵌套结构——父策略分配资金给子策略。

一种实现方式：

```python
# 子策略1：风险资产ETF轮动（50%）
risk_strategy = bt.Strategy('risk_rotation', [...], children=None)

# 子策略2：纳指ETF（37.5%）
nasdaq_strategy = bt.Strategy('nasdaq', [
    bt.algos.RunDaily(),
    bt.algos.SelectThese(['513100.SH']),
    bt.algos.WeighEqually(),
    bt.algos.Rebalance(),
])

# 子策略3：黄金ETF（12.5%）
gold_strategy = bt.Strategy('gold', [...])

# 父策略分配资金
parent = bt.Strategy('multi_asset', [
    bt.algos.RunDaily(),
    bt.algos.WeighSpecified(risk_rotation=0.50, nasdaq=0.375, gold=0.125),
], children=[risk_strategy, nasdaq_strategy, gold_strategy])
```

`WeighSpecified` 用于固定权重分配。

### 步骤 9：实现分层风控算法

需要在权重之后、再平衡之前插入自定义风控算法。bt 支持在算法链中任意位置插入 `Algo`，但**风控需要在每个交易日动态计算**，因此不能用 `RunMonthly` 之类的调度器，而是让风控算法在每次 `RunDaily` 时都执行。

需要自定义的算法：

**① `MarketRiskControl`**：读取市场状态，危险状态时将风险资产 ETF 权重置 0，释放权重转防守。

**② `AStockTrendControl`**：读取创业板指与 80 日 LLT 的关系，触发条件时风险资产 ETF 配置比例降至 5%。

**③ `OverheatExit`**：检查每只 ETF 价格是否高于自身 80 日 LLT 达 20%，触发则该 ETF 权重归零。

**④ `VolatilityTarget`**：bt 有内置的 `TargetVol`，可用于资产类别层面的波动率控制，但组合整体层面的二次调整（20 日 EWMA 波动率 + 34% 目标）需要自定义。

这些算法按顺序插入算法链，在每个交易日依次执行，修改 `target.temp['weights']`。

### 步骤 10：实现防守仓机制

防守仓的逻辑是“风险资产减仓后资金转入防守”。有两种实现路径：

**路径 A（推荐）** ：将防守仓作为**独立的子策略**纳入策略树，父策略的权重分配根据风控信号动态调整。但 bt 的 `WeighSpecified` 是静态的，需要自定义一个 `DynamicAllocate` 算法来动态调整父策略对各子策略的分配比例。

**路径 B**：将所有 ETF（含防守 ETF）放在同一个 universe 中，在权重算法中统一处理。当选券输出为空时（危险状态），自动将权重分配给预选的防守 ETF。


## 第五阶段：交易执行机制

### 步骤 11：实现五相位调仓与整组迟滞

**五相位调仓**是 bt 的调度器难以直接表达的机制。bt 的 `RunDaily` / `RunMonthly` 等调度器是全局的，不支持“1/5 仓位每 5 天调一次、5 组错开”。

**可行方案**：创建 5 个独立的子策略，每个使用不同的起始偏移，在父策略层等权汇总。例如：

```python
phases = []
for i in range(5):
    phase = bt.Strategy(f'phase_{i}', [
        bt.algos.RunEveryN(5, offset=i),  # 需自定义调度器
        # ... 选券、权重、风控
    ])
    phases.append(phase)

parent = bt.Strategy('phased', [
    bt.algos.WeighEqually(),
], children=phases)
```

bt 内置调度器可能没有 `RunEveryN(offset=)`，需要自定义一个调度器类。

**整组迟滞**：在权重算法中增加逻辑——比较新组合总得分与当前持仓组合总得分，若未超越则维持当前权重。

### 步骤 12：实现 T+1 执行与跳空延迟

bt 的 `Rebalance` 默认在算法执行的**下一个 bar** 执行交易（bt 的机制是 T 日收盘后生成权重，T+1 日开盘执行）。这与你策略的 T+1 开盘执行一致。

**跳空延迟**需要自定义。bt 的 `Rebalance` 不接受条件执行。一种方式是自定义一个 `ConditionalRebalance` 算法，在 `Rebalance` 之前检查 T+1 开盘价相对 T 日收盘价的跳空幅度，若超过 1% 则将该标的的新增买入标记为“延迟”，下一日再执行。


## 第六阶段：成本模型与绩效分析

### 步骤 13：配置交易成本

bt 的 `Backtest` 接受 `commissions` 参数，可以传入一个函数。你的策略要求单边 8bp：

```python
bt.Backtest(
    strategy, prices,
    commissions=lambda q, p: abs(q) * p * 0.0008,
)
```

现金部分的年化 1.8% 收益，bt 没有内置的现金收益机制。一种变通方式是在 universe 中加入一个现金类 ETF，其价格序列按 1.8% 年化增长，当防守仓不足时权重分配给该“现金 ETF”。

### 步骤 14：绩效分析与对照

bt 的结果对象 `Result` 继承自 ffn 的 `GroupStats`，提供 `get_weights()`、`get_transactions()`、`plot_weights()` 等方法。你可以：

- 用 `result.display()` 查看年化、最大回撤、夏普
- 用 `result.get_weights()` 导出权重矩阵，自行计算 Calmar 比率
- 用 `Backtest.turnover()` 和 `Backtest.herfindahl_index()` 检查换手和集中度

ffn 的 `PerformanceStats` 提供大量统计函数，可以扩展计算 Calmar 等自定义指标。


## 总体实现顺序总结

| 优先级 | 步骤 | 核心任务 | bt 组件 |
|---|---|---|---|
| **P0** | 1-3 | 数据准备 + 最小回测跑通 | `bt.run` + `WeighTarget` |
| **P1** | 4 | 选券过滤 + 市场状态 | `SelectWhere` + 自定义选券 |
| **P2** | 5-6 | 动量/反转排序 + 相关性去重 | 自定义 `Algo` |
| **P3** | 7 | HRP 权重 | 自定义 `WeighHRP` |
| **P4** | 8 | 多资产策略树 | `children` + `WeighSpecified` |
| **P5** | 9-10 | 分层风控 + 防守仓 | 自定义风控 `Algo` |
| **P6** | 11-12 | 五相位调仓 + 跳空延迟 | 自定义调度器 + 自定义 `Rebalance` |
| **P7** | 13-14 | 成本模型 + 绩效分析 | `commissions` + ffn |

**最关键的原则**：bt 擅长的是“算法链调度 + 选券/权重/再平衡”的框架，但你的策略中**大量复杂信号（时间加权回归、HRP、LLT、反转 ZBias）应该在 bt 外部用 pandas 预计算好**，以 DataFrame 形式传入。bt 只负责“按日期执行这些预计算的信号，并追踪组合权重和交易”。把信号生成和回测执行分离，是复现这类复杂策略最务实的架构。

以上仅为基于报告内容和 bt 框架文档的技术路线梳理，不构成投资建议。
