# 多资产 ETF 轮动策略复现

复现浙商证券研报《多资产 ETF 轮动策略：固收+视角下动态组合管理的构建与实践》(2026-08-07) 的规则驱动 ETF 轮动策略。纯本地、开源可复现，不依赖商业平台/SDK。

## 环境

- Python 3.10，项目虚拟环境 `.venv`（用 `uv` 创建）。
- 安装：`$env:UV_INDEX_URL="https://pypi.org/simple"`（本机阿里云镜像对新 wheel 有 404），必要时设 `HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:7897`。
- `uv pip install --python ".venv\Scripts\python.exe" -e ".[dev]"`，冻结版本见 `requirements.txt`。

## 数据

- 原始数据在 `data/`（git 忽略）：tushare 的 ETF 日线/复权因子/指数日线，parquet + duckdb。
- tushare token 存 `.env`（git 忽略），格式 `TUSHARE_TOKEN=...`。
- 补充数据：`python scripts/fetch_data.py`（拉取 中证2000/中证红利 至 2026-07、ETF fund_basic）。

## 运行

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31
.venv\Scripts\python.exe scripts\run_sensitivity.py
.venv\Scripts\python.exe -m pytest tests -q
```

## 架构

```
data/       bronze parquet + duckdb（原始）
src/etf_rotation/
  config.py           参数加载（config/params.yaml + .env）
  data/               calendar / curate(复权/校验) / ingest(tushare) / universe(point-in-time)
  signals/            trend(时间加权回归) / reversal(ZBias) / market_state(LLT)
  portfolio/          dedupe / hrp(PyPortfolioOpt) / multi_asset / risk_layers / defensive
  execution/          phases(五相位) / hysteresis / gap_delay(T+1跳空)
  backtest/run.py     净值仿真（成本、现金计息）
  evaluation/         metrics / sensitivity / overfitting(DSR)
  pipeline.py         端到端组装
scripts/              入口脚本
reports/              净值、指标、敏感性（生成物）
tests/                pytest 单测
```

## 技术栈

pandas / numpy / pyarrow / duckdb / tushare / TA-Lib / PyPortfolioOpt(HRP) / bt(引擎封装) / quantstats(备用) / scipy。

## 复现假设与已知差异

见 `reports/回测报告.md` 的「复现假设与差异说明」章节；设计文档 `docs/superpowers/specs/2026-10-10-etf-rotation-design.md` 为权威来源。

