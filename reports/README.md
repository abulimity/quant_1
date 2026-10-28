# 单文件回测看板

`dashboard.html` 是自包含的看板产物，双击即可打开，断网可用。

## 直接看

双击 `dashboard.html`，或用浏览器打开：

```powershell
Start-Process reports\dashboard.html
```

文件内联了 Plotly 2.35.2 与完整载荷，不发起任何网络请求。

## 内容

产物由 `scripts/build_dashboard.py` 从 `reports/latest.json` 指向的 run 重建，载荷 49 键。
第 49 键 `names` 是证券简称表，看板所有显示证券代码的地方都改为显示简称，代码放进鼠标悬浮提示。

## 为什么不入库重建所需的输入

`reports/runs/`、`reports/latest.json` 与 `data/` 都是 git 忽略的生成物与原始数据，
体积大且可重跑。因此 `dashboard.html` 是 clone 之后唯一可直接查看的入口。

要重建，需要先有 run 产物与原始数据：

```powershell
.venv\Scripts\python.exe scripts\fetch_data.py
.venv\Scripts\python.exe scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
.venv\Scripts\python.exe scripts\build_dashboard.py
```

## 数据口径

看板取当前 run（open 口径），设计稿基线为旧 run（close 口径）。
逐键比对见 `tools/cmp_dashboard.py` 与 `reports/回测报告.md` 的「看板数据口径」一节。
