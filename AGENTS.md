# AGENTS.md

## 项目
复现券商研报中的多资产 ETF 轮动策略，本地回测、调参、稳健性评估。

## 工作流
使用 Superpowers 作为主框架。当前阶段：工程化基础设施 + 差距归因 + 信号可观测化（见 docs/superpowers/specs 与 plans 下 2026-10-19 文档）。
- 先澄清、再设计、后实现，禁止跳过规划直接写代码
- 调参用 ml4t-sensitivity-analysis（网格、稳健性分数、悬崖检测）+ ml4t-backtest-overfitting（多重检验校正）
- 遇到回测异常/bug 才用 superpowers:systematic-debugging：根因调查 → 假设 → 实验 → 修复
- 每次调整后用 superpowers:verification-before-completion 验证，没跑命令不下结论
- 优化时一次只动一个维度，避免多参数同时调整导致归因困难

## 方法论参考
参考 ml4t/skills 的回测纪律，但注意差异：
- 借鉴：前视偏差防护、数据泄漏检查、样本外验证、交易成本建模、过拟合检测
- 不适用：ML 模型训练、特征工程、交叉验证策略、模型集成
使用每个 Skill 前先判断是否适用于规则驱动策略，不适用就跳过，不强行套用。

常用技能：ml4t-lookahead-bias、ml4t-data-leakage、ml4t-sensitivity-analysis、
ml4t-backtest-overfitting、ml4t-deflated-sharpe、ml4t-cost-model、ml4t-tearsheet、
ml4t-risk-metrics；Superpowers：verification-before-completion、systematic-debugging、
brainstorming、writing-plans。

## ml4t Skill 适用性清单（已判定，后续直接查表，勿重复读取）
判定基准：本项目为规则驱动 ETF 轮动（非 ML），bt 引擎 + tushare 日/周线数据 + 本地回测，无实盘、无特征工程、无模型训练。2026-10-19 初判；同日按「重量基础设施 + 差距归因」新目标修订：ml4t-registry-system、ml4t-canonical-schema 转 ✅，ml4t-case-study-pipeline、ml4t-data-export 转 🔶（实验跟踪、schema、分阶段 artifact 已成为目标所需）。

### ✅ 适用（直接用，19 个）
ml4t-lookahead-bias、ml4t-data-leakage、ml4t-sensitivity-analysis、ml4t-backtest-overfitting、
ml4t-deflated-sharpe、ml4t-cost-model、ml4t-tearsheet、ml4t-risk-metrics、
ml4t-calendar-ops、ml4t-validate-data、ml4t-fetch-data、ml4t-define-universe、
ml4t-survivorship-bias、ml4t-stress-test、ml4t-exposure-analysis、ml4t-position-sizing、
ml4t-transaction-costs、ml4t-registry-system、ml4t-canonical-schema

### 🔶 参考借鉴（按需读取，7 个）
- ml4t-run-backtest：回测引擎已用 bt，仅借订单/持仓/成本的概念
- ml4t-strategy-workflow：端到端生命周期，本项目用 Superpowers 主框架
- ml4t-non-stationarity：子区间 OOS（2019–2023 vs 2024–2026）已覆盖，仅作参考
- ml4t-point-in-time：仅价格数据无修订；接入基本面/宏观数据时再用
- ml4t-regime-awareness：若后续加 regime 条件风险缩放时再用
- ml4t-case-study-pipeline：分阶段 artifact 边界与 rerun 规则（基础设施/归因阶段用）
- ml4t-data-export：列式持久化 + schema 强制（parquet/duckdb 落盘用）

### ❌ 不适用（跳过，勿读取，35 个）
- ML 模型/特征/CV/监督标签/因子/解释（规则驱动无这些）：ml4t-compute-features、
  ml4t-feature-families、ml4t-feature-selection、ml4t-feature-store、ml4t-feature-validation、
  ml4t-triple-barrier、ml4t-meta-labels、ml4t-latent-factors、ml4t-shap-analysis、
  ml4t-stationarity-tests、ml4t-model-validation、ml4t-drift-detection、ml4t-walk-forward-cv、
  ml4t-purging-embargo、ml4t-cpcv、ml4t-information-coefficient、ml4t-evaluate-factor、
  ml4t-factor-research、ml4t-horizon-design、ml4t-causal-identification
- 期货/高频数据类型（本项目 ETF 日/周线，无 tick、无期货）：ml4t-build-bars、
  ml4t-continuous-futures
- 实盘/生产部署（本地回测，无实盘）：ml4t-live-trading、ml4t-kill-switch、
  ml4t-monitoring-alerting、ml4t-production-readiness、ml4t-rl-execution
- Agent/治理（本项目非自主 agent 系统）：ml4t-agent-governance、ml4t-agent-state-memory、
  ml4t-agent-tool-contracts、ml4t-research-operator、ml4t-multi-agent-forecasting
- 流程/工程（已有 Superpowers 或自有结构）：ml4t-case-study-development、
  ml4t-polars-patterns、ml4t-regime-features

## 技术约束
- 本地 Python 开源环境，依赖与版本见 requirements.txt
- 回测引擎使用 bt，不满足的功能可在 bt 框架下自行开发（不换 vectorbt/其它引擎）
- 实验基础设施复用成熟开源件：Hydra（配置 + multirun 网格）、DVC/轻量 manifest（数据快照哈希）、
  现有 registry.py 修到 ml4t-registry-system 标准；不引入 MLflow/wandb 等重或商业 SDK
- 数据源使用 tushare，token 已写入 `.env`
- 产出物必须可独立运行、可复现，不依赖任何商业产品/SDK

## 环境与运行
- Python 3.10，虚拟环境 `.venv`（uv 创建、无 pip）；统一用 `.venv\Scripts\python.exe`
- 装依赖走官方 PyPI 或代理 http://127.0.0.1:7897；不要用阿里云镜像（新 wheel 会 404）
- 运行任何 Python 前先 `$env:PYTHONIOENCODING="utf-8"`（Windows GBK 报错）
- 命令：
  - `.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31`  基准回测
  - `.venv\Scripts\python.exe scripts\run_sensitivity.py`  成本敏感性
  - `.venv\Scripts\python.exe scripts\fetch_data.py`  补充 tushare 数据
  - `.venv\Scripts\python.exe -m pytest tests -q`  全量单测

## 数据与已知差异
- `data/` 为 git 忽略的原始数据（bronze parquet + duckdb）
- `src/etf_rotation/data/calendar.py` 与 `pipeline.py` 硬编码了 tushare 快照路径
  tushare-f4f7c81a15b5779c，换数据目录时需同步修改
- 复现假设 H1–H10 与「已知简化」见 `reports/回测报告.md` 与
  `docs/superpowers/specs/2026-10-10-etf-rotation-design.md`
- 机制（整组迟滞 / T+1 开盘+跳空+停牌 / 组合 34% 目标波动 / 单 ETF 过热退出）已接入主线；
  默认执行口径为 open（`OpenRebalance`），`--execution close` 可回退
- 回测产物按 `reports/runs/{run_id}/` 保存：`--save-profile` 默认 standard，
  出报告需要 full；`reports/latest.json` 指向最新 run，`reports/derived/` 是其派生数据
- `data/cache/signals/{signal_id}/` 是跨 worktree 复用的信号缓存（默认读写，
  `ETF_SIGNAL_CACHE=off` 只关读取）；不要手工清理，写盘是原子的
- 产物完整性用 `scripts/verify_artifacts.py` 校验；`scripts/activate_data.ps1`
  供 worktree 复用主仓库的 data/ 与 .venv

## 纪律与验收
- 滚动统计量一律 `.shift(1)`；T 日信号、T+1 成交；禁止未来信息
- 与研报对标 20.74% / -10.13% / 2.05，目标是「同量级」而非精确复现，
  数值差异写入 `reports/回测报告.md`
- `.env` 的 tushare token 不得打印/提交/写日志
- 当前分支 main，改动按语义化 commit

## 阶段目标
1. 单参数敏感性分析
2. 参数组合调试
3. 样本外稳健性验证（规则驱动无训练集，用时间子区间近似：2019–2023 vs 2024–2026）
4. 成本敏感性测试
5. 回测结果可视化展示

## 交付物
可复现的回测代码库、回测报告（净值/风险指标/参数敏感性）、调参记录与最终参数建议、与研报描述的差异说明。
