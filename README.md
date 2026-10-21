# 多资产 ETF 轮动策略复现

复现浙商证券研报《多资产 ETF 轮动策略：固收+视角下动态组合管理的构建与实践》(2026-08-07) 的规则驱动 ETF 轮动策略。纯本地、开源可复现，不依赖商业平台/SDK。

## 当前状态

- 版本：v1.1.1（见 CHANGELOG.md）
- 基准结果（默认 open 口径 + 候选参数）：2019-01 ~ 2026-07 年化 9.61% / 最大回撤 -15.79% / Calmar 0.61；close 口径候选 12.31% / -12.21% / Calmar 1.01（研报对标 20.74% / -10.13% / 2.05）
- 测试：97 passed
- 待办与已知限制见 TODO.md；复现差异见 reports/回测报告.md；调参记录见 reports/调参记录.md

## 环境

- Python 3.10，项目虚拟环境 `.venv`（用 `uv` 创建）。
- 安装：`$env:UV_INDEX_URL="https://pypi.org/simple"`（本机阿里云镜像对新 wheel 有 404），必要时设 `HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:7897`。
- `uv pip install --python ".venv\Scripts\python.exe" -e ".[dev]"`，冻结版本见 `requirements.txt`。

## 数据

- 原始数据在 `data/`（git 忽略）：tushare 的 ETF 日线/复权因子/指数日线，parquet + duckdb。
- tushare token 存 `.env`（git 忽略），格式 `TUSHARE_TOKEN=...`。
- 数据引导（全新机器从零拉取）：
  - `python scripts/fetch_etf_bars.py` —— ETF 日线/复权因子/标的表（全量约数十分钟，一次性）
  - `python scripts/fetch_data.py` —— 指数（中证2000/中证红利/上证/创业板/沪深300）与 ETF fund_basic
- 已有 bronze 快照时无需重新拉取；数据路径可用环境变量覆盖：
  `ETF_BARS_PARQUET` / `ETF_ADJ_PARQUET` / `ETF_SYMBOLS_PARQUET` / `ETF_INDEX_PARQUET` / `ETF_FETCHED_DIR`（写入 `.env` 即可生效）。

## 运行

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
.venv\Scripts\python.exe scripts\run_sensitivity.py
.venv\Scripts\python.exe scripts\run_report.py
.venv\Scripts\python.exe -m pytest tests -q
```

顺序：先 `run_backtest.py` 产出净值/权重/基准，再 `run_sensitivity.py` 做成本敏感性，最后 `run_report.py` 生成交互式报告与交易明细。

## 架构

```
data/       bronze parquet + duckdb（原始）
src/etf_rotation/
  config.py           参数加载（config/params.yaml + .env）
  data/               calendar / curate(复权/校验) / ingest(tushare) / universe(point-in-time)
  signals/            trend(时间加权回归) / reversal(ZBias) / market_state(LLT)
  portfolio/          dedupe / hrp(PyPortfolioOpt) / multi_asset / risk_layers / defensive
  execution/          shift_weights(T+1生效)；五相位/迟滞在 pipeline.py，跳空顺延在 backtest/open_rebalance.py
  backtest/run.py     bt 引擎封装（现金/持仓/净值记账、成本、现金计息）+ OpenRebalance(T+1开盘)
  evaluation/         metrics / sensitivity / overfitting(DSR) / registry / attribution / exposure / observability / plots / trades
  pipeline.py         端到端组装
scripts/              入口脚本
reports/              净值、指标、敏感性、可视化报告、交易明细（生成物）
tests/                pytest 单测
```

## 技术栈

pandas / numpy / pyarrow / duckdb / tushare / TA-Lib / PyPortfolioOpt(HRP) / bt(引擎) / plotly(可视化) / scipy。

## 复现假设与已知差异

见 `reports/回测报告.md` 的「复现假设与差异说明」章节；设计文档 `docs/superpowers/specs/2026-10-10-etf-rotation-design.md` 为权威来源。

