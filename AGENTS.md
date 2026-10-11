# AGENTS.md

## 项目
复现券商研报中的多资产 ETF 轮动策略，本地回测、调参、稳健性评估。

## 工作流
使用 Superpowers 作为主框架。当前阶段：细节优化与调参。
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

## 技术约束
- 本地 Python 开源环境，依赖与版本见 requirements.txt
- 回测引擎使用 bt，不满足的功能可在 bt 框架下自行开发
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
- 已知尚未接入主流水线：整组迟滞、T+1 开盘+跳空顺延、组合 34% 目标波动、
  单 ETF 过热退出；执行价用 T+1 收盘近似

## 纪律与验收
- 滚动统计量一律 `.shift(1)`；T 日信号、T+1 成交；禁止未来信息
- 与研报对标 20.74% / -10.13% / 2.05，目标是「同量级」而非精确复现，
  数值差异写入 `reports/回测报告.md`
- `.env` 的 tushare token 不得打印/提交/写日志
- 当前分支 master，改动按语义化 commit

## 阶段目标
1. 单参数敏感性分析
2. 参数组合调试
3. 样本外稳健性验证（规则驱动无训练集，用时间子区间近似：2019–2023 vs 2024–2026）
4. 成本敏感性测试
5. 回测结果可视化展示

## 交付物
可复现的回测代码库、回测报告（净值/风险指标/参数敏感性）、调参记录与最终参数建议、与研报描述的差异说明。
