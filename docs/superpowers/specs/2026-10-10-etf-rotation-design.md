# 多资产 ETF 轮动策略复现 — 设计文档

- 日期：2026-10-10
- 报告：《多资产 ETF 轮动策略：固收+视角下动态组合管理的构建与实践》，浙商证券，2026-08-07
- 工作流：Superpowers（brainstorming → 本设计 → writing-plans → 实现）
- 状态：待用户审阅

## 1. 目标与范围

在本地复现研报中的规则驱动多资产 ETF 轮动策略，搭建可复现、可独立运行的回测代码库，完成基准回测、参数调试与稳健性评估，并输出回测报告、参数调优记录、以及与原研报的差异说明。

验收口径：机制复现 + 指标同量级。目标是年化收益、最大回撤、Calmar 大致接近报告值（20.74% / 10.13% / 2.05，2019-01 ~ 2026-07）。因数据源（Wind vs tushare）、复权口径、ETF 名称/主题分类等差异，不要求数值完全对齐；所有差异写入报告。

## 2. 策略定义（研报机制）

主线：全市场 ETF 趋势筛选 → 市场状态分型 → 相关性去重 + HRP 配权 → 多资产底仓（风险 50% / 纳指 37.5% / 黄金 12.5%）→ 分层风控 → 防守仓承接资金。

### 2.1 资产池

- 全市场 ETF；风险池剔除债券/货币/现金/存单/短融。
- 上市 ≥126 个交易日；过去 20 日日均成交额 ≥500 万元。
- 全部筛选基于当时可获得数据滚动判断（point-in-time），不用期末名单回溯。

### 2.2 趋势得分（动量信号）

对复权价对数序列做时间加权线性回归：

```
Momentum(w) = [exp(250 * Slope(w)) - 1] * R2(w)
```

- Slope(w) 为回归斜率（时间加权），250 日年化；R2(w) 为拟合优度（趋势质量折扣）。
- 双窗口 w ∈ {21, 60}，横截面排名按 70% / 30% 合成。
- 21 日动量为负（Momentum(21) < 0）的 ETF 剔除出候选。

### 2.3 反转信号（仅震荡市）

- 14 日 EMA 作为短期价格中枢，计算价格相对均线的对数偏离 LogBias。
- 170 日滚动均值和标准差做 z-score：`ZBias = (LogBias - Mean170(LogBias)) / Std170(LogBias)`。
- 激活条件：`ZBias <= -0.5` 且 `ZBias[t] > ZBias[t-3]`（超跌 + 负偏离收窄）。
- 震荡市：动量分与反转分分别横截面标准化后相加，综合排名。

### 2.4 市场状态识别

- 三指数：上证指数（000001.SH）、中证2000（932000.CSI）、中证红利（000922.CSI）。
- 各指数 LLT（平滑参数 α=0.10）在 8 个交易日窗口估算斜率：斜率 >1.005 记 +1，<0.995 记 -1，其余记 0。
- 三值等权平均得复合分（[-1, 1]）。
- ≥0.35 强势（纯动量）；≤-0.35 危险（风险资产退出，转防守）；中间震荡（动量+反转，风险仓降至 95%）。

### 2.5 相关性去重与 HRP

- 相关性阈值 0.80 去重；主题约束限制相近方向（如半导体/芯片）重复入选；持仓数量上限 10 只。
- HRP：250 日收益窗口 → 协方差/相关系数 → 距离矩阵 → Single-Linkage 层次聚类 → 递归二分、组内逆方差、权重归一化。

### 2.6 多资产底仓与四层风控

| 风险层级 | 判定参数 | 处理 |
|---|---|---|
| 市场状态 | 复合分阈值 ±0.35 | 震荡配 95%，危险退出风险资产 |
| A 股趋势 | 创业板指（399006.SZ）低于 80 日 LLT 且 LLT 20 日跌幅 >3% | 风险仓降至 5% |
| 单只过热 | ETF 价格高于自身 80 日 LLT 达 20% | 该 ETF 权重归零 |
| 波动率 | 风险资产目标 26%、纳指/黄金各 18%、组合 20 日 EWMA 目标 34% | 超目标同比缩减，只减不加 |

多资产固定权重（趋势行情）：风险资产 50% / 纳指 37.5% / 黄金 12.5%。纳指/黄金各有独立动量信号，转负即退、信号恢复再进。

### 2.7 防守仓

- 债券 + 货币 ETF，剔除可转债；60 日年化波动 <3%。
- 按 60 日风险调整动量排序，取前 5 等权，每 120 个交易日更新；同一细分类别（国债/政金债/地方债/信用债/短融存单/货币）最多 1 只。
- 承接危险状态退出、震荡预留 5%、过热退出、趋势约束与波动率控制释放的资金；不足部分以现金持有。

### 2.8 交易执行

- 五相位：完整组合拆 5 份，每相位每 5 个交易日独立调仓、时间错开，最终持仓 = 5 相位等权汇总。
- 整组迟滞：新组合总得分未明显改善且原持仓仍有效时，维持原组合。
- T 日收盘信号 → T+1 开盘执行；买入标的 T+1 高开 ≥1% 时买入顺延一日，已有仓位不受影响。
- 成本：单边 8bp，买卖双边 16bp。
- 现金：闲置资金年化 1.8%。

### 2.9 报告绩效基准

2019-01 ~ 2026-07：累计净值 3.95、年化 20.74%、最大回撤 10.13%、夏普 1.94、Calmar 2.05。分年度值见报告表 5，作为对标。

## 3. 复现假设清单（研报未写死，由本项目补齐）

| # | 假设 | 取值 | 敏感性检验 |
|---|---|---|---|
| H1 | 趋势回归的时间加权衰减 | 线性权重（越近权重越大） | 对比指数衰减 |
| H2 | LLT 公式 | Ehlers Low-Lag Filter（α=0.10） | 扰动 α |
| H3 | 「80 日 LLT」参数 | 80 日等价平滑参数 | 60/100/120 日 |
| H4 | 整组迟滞阈值 | 新组合得分改善 ≥2% 才换仓 | 0% / 5% / 10% |
| H5 | 反转与动量合成权重 | 50/50 | 30/70、70/30 |
| H6 | 反转得分构造 | 仅超跌修复标的给反转分，其余为 0 | — |
| H7 | 纳指/黄金退出与恢复 | 各自动量转负即退，转正恢复 | 阈值 0 / ±5% |
| H8 | 主题约束实现 | 基于 fund_basic 类别 + 名称关键词聚类 | — |
| H9 | 复权口径 | tushare 复权因子重建后复权价（报告用 Wind） | — |
| H10 | 纳指/黄金 ETF 具体标的 | 纳指 ETF 513100.SH、黄金 ETF 518880.SH（实现时实测流动性后可在候选同质标的中替换） | 同质标的替换 |

## 4. 技术栈与依赖

- 语言/运行时：Python 3.10（项目 venv `.venv`）。
- 数据处理：pandas、numpy、pyarrow、duckdb。
- 数据源：tushare（token 存 `.env`，不提交）。
- 技术指标：TA-Lib（EMA/STD/ROC 等）；LLT 与时间加权回归自建（业界无成熟实现）。
- 组合优化：PyPortfolioOpt（HRP）。
- 回测引擎：bt（pmorissette）。
- 绩效/风险：quantstats（与 ml4t 公式手算交叉核对）。
- 安装注意：本机 pip/uv 默认走阿里云镜像，镜像对新 wheel 有滞后；安装时切官方 PyPI 或经代理 `http://127.0.0.1:7897`。依赖版本写死进 `requirements.txt`。

排除项及原因：pandas-ta（需 Python≥3.12）、Riskfolio-Lib（过重）、empyrical/pyfolio/alphalens（quantopian 已归档）、vectorbt/backtrader（框架已选 bt）。

## 5. 目录结构

```
quant_1/
  paper/               # 研报 PDF
  data/                # 现有 bronze parquet + warehouse.duckdb（git 忽略）
  docs/superpowers/specs/   # 本设计文档
  docs/superpowers/plans/   # 实现计划（下一步生成）
  src/etf_rotation/
    data/              # ingest(tushare) / curate(复权/校验) / universe(point-in-time) / calendar
    signals/           # trend / reversal / market_state(LLT)
    portfolio/         # dedup / hrp / multi_asset / risk_layers / defensive
    execution/         # 五相位 / 迟滞 / T+1+跳空 / 成本 / 现金计息
    backtest/          # bt 引擎封装 + NAV/持仓/换手
    evaluation/        # tearsheet / risk / sensitivity / overfitting
  config/              # 参数 yaml（研报默认值 + 假设清单）
  scripts/             # fetch_data.py、run_backtest.py、run_sensitivity.py 等入口
  notebooks/           # 探索与报告
  reports/             # 回测报告、敏感性图、差异说明（图片/csv git 忽略）
  tests/               # 单元测试
  requirements.txt
  .env / .env.example
```

## 6. 数据层设计

- 复权：bronze 复权因子重建后复权价，日收益/趋势/波动全部基于复权价；口径差异记录。
- 日历：A 股交易日历（tushare trade_cal 或现有 trading_calendar），窗口按交易日、调仓日对齐日历。
- 标的池：point-in-time 滚动过滤；处理退市/清盘（不再进入新持仓，持仓中则按最后交易日强制平仓并记录）。
- 数据补充脚本（`scripts/fetch_data.py`）：补 中证2000(932000.CSI)、中证红利(000922.CSI) 到 2026-07；补 ETF 名称/类型（fund_basic）。
- 校验：沿用 ml4t-validate-data（OHLC 一致性、缺口、重复、极端收益、复权异常），并写报告。

## 7. 信号层设计

- `trend.py`：时间加权线性回归（线性权重）→ Slope、R2 → Momentum(21/60) → 排名合成 → 21 日负值剔除。
- `reversal.py`：14 日 EMA 偏离 → 170 日 z-score → ZBias 激活条件。
- `market_state.py`：LLT(α=0.10) → 8 日斜率 → 三指数复合分 → 三态。
- 所有滚动统计量 `.shift(1)`，禁止使用未来信息（ml4t-lookahead-bias）。

## 8. 组合层设计

- `dedup.py`：相关性阈值 0.80 + 主题约束 + 10 只上限。
- `hrp.py`：PyPortfolioOpt HRP，固定输入口径（250 日复权收益）；薄封装。
- `multi_asset.py`：50/37.5/12.5 底仓 + 市场状态/纳指黄金动量缩放。
- `risk_layers.py`：四层风控落地。
- `defensive.py`：防守池筛选与 120 日更新。

## 9. 执行层与回测设计

- 目标权重矩阵（时间 × 资产）在 pandas 内计算，已含五相位、迟滞、风控、防守仓。
- `bt` 只做仓位记账与净值仿真：现金跟踪、换手、成本。
- 自建薄封装：T+1 开盘成交、高开顺延、单边 8bp、现金年化 1.8%（现金合成资产计息）。

## 10. 评估与验证

- 主区间 2019-01 ~ 2026-07 全样本；输出净值/回撤/滚动夏普、Sharpe/Sortino/Calmar/最大回撤/VaR/CVaR、毛净对比、分年度表，对标报告表 5。
- 参数敏感性：动量窗口、相关性阈值、过热阈值、波动率目标、成本 1x/2x/3x、LLT 参数等网格 + 稳健性分数 + 悬崖检测。
- 多重检验：记录试验总数，报 DSR/PSR（ml4t-deflated-sharpe）。
- 样本外：时间子区间（2019–2023 vs 2024–2026 准样本外；研报发布日 2026-08-07 后区间若可取数）。

## 11. ml4t 方法论映射

借鉴：lookahead-bias、data-leakage、define-universe、survivorship-bias、calendar-ops、fetch-data、validate-data、transaction-costs、cost-model、run-backtest、tearsheet、risk-metrics、sensitivity-analysis、backtest-overfitting/DSR（部分）。

跳过（ML 专属）：walk-forward-cv、purging-embargo、cpcv、triple-barrier、meta-labels、horizon-design、stationarity-tests、drift-detection、non-stationarity、shap-analysis、latent-factors、feature-*、rl-execution、multi-agent-forecasting 等。

## 12. 测试策略

- 信号层数值单测（LLT、时间加权回归、ZBias 激活条件）。
- HRP 与手算/已知案例对比。
- 成本与换手计算单测；无前视检查（信号只用 ≤T 数据）。
- 端到端冒烟测试：小样本跑通全流程并输出净值。

## 13. 交付物

1. 可复现回测代码库（含 requirements 锁版本、README、入口脚本）。
2. 回测报告：净值曲线、风险指标、分年度、毛净对比。
3. 参数敏感性报告 + 调优记录 + 最终参数建议。
4. 与研报的差异说明（含复现假设清单 H1–H9）。

## 14. 开放问题（实现中可能升级）

- tushare fund_basic 分类粒度与研报「债券/货币/可转债/主题」口径的映射需实测后校准。
- 中证2000 指数历史（2015–2023）为 tushare 回补数据，可能与研报 Wind 口径有差异。

