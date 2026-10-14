# bt回测推荐配套库
- 推荐配套库：yfinance / akshare（数据），pandas / numpy（数据处理），ta / pandas_ta / TA‑Lib（技术指标），ffn / empyrical / pyfolio（绩效/统计），optuna / scikit‑optimize（参数搜索），joblib 或 dask（并行），arch（bootstrap）、cvxpy / PyPortfolioOpt（组合/优化），mlflow（实验追踪）。这些能最大程度减少你自己实现的统计/搜索/可视化工作量，同时和 bt 无缝配合。

按用途的推荐清单与说明
- 数据获取与处理
  - yfinance：直接拉取 ETF 历史 OHLCV，适合快速原型。
  - akshare：中文/宏观/另类数据来源（中国宏观数据方便）。
  - pandas / numpy：基础数据清洗、对齐、重采样、特征工程。

- 技术指标与特征
  - ta 或 pandas_ta：纯 Python 指标库（移动平均、RSI、MACD 等），无需编写指标实现。
  - TA‑Lib：指标齐全且高效（需编译 C 库，但功能强）。

- 参数搜索与超参优化
  - optuna：易用、支持 TPE、并行、可中断恢复，适合大规模参数搜索。
  - scikit‑optimize：另一个贝叶斯优化选项。
  - 如果只做网格或随机搜索，直接用 itertools + joblib 并行足够。

- 并行化与分布式运行
  - joblib：轻量并行化回测任务（本地多核）。
  - dask：当任务较多或数据较大时进行分布式并行。
  - Celery（若做长期/服务器端批量作业）。

- 回测结果与统计/可视化
  - ffn：与 bt 生态兼容，用于绩效汇总、图表、指标表。
  - empyrical：常用金融统计（年化、夏普、最大回撤）。
  - pyfolio（若仍用）：更深入回撤与持仓分析（注意部分项目不再维护）。
  - matplotlib / seaborn / plotly：绘图。

- 健壮性检验 / 置信度 / bootstrap / PBO
  - arch（arch.bootstrap）：提供 block bootstrap 等方法，方便做蒙特卡洛/区块自助。
  - numpy / scipy：统计检验与自定义方法。
  - PBO / Deflated Sharpe：没有通用 pip 包（实现较专门），但可以用 optuna + bootstrap +多次 walk‑forward 组合实现类似分析；若需可提供实现范例。

- 组合构建与最优化
  - PyPortfolioOpt：方便做均值方差、风险平价、约束优化等；基于 cvxpy 可扩展约束。
  - cvxpy：定制化优化问题。

- 向量化/高性能回测（可与 bt 补充）
  - vectorbt：极快、向量化的回测与统计库，适合做大规模参数扫描（但与 bt API 不同，可作为对照）。
  - numba：自定义向量运算加速。

- 实验追踪与可重复性
  - mlflow / sacred / Weights & Biases：记录参数、度量、artifact（结果文件、图表）。
  - DVC：版本化大数据集。
  - 保证 reproducibility：固定随机种子、记录数据快照、保存回测配置文件。

快速安装建议（常用包）
pip install bt yfinance pandas numpy ta pandas_ta ffn empyrical optuna joblib arch pyportfolioopt scikit-learn matplotlib seaborn mlflow

最小工作流示例（思路代码，演示如何用 bt + yfinance + optuna + joblib 做参数敏感性扫描）
- 思路：用 yfinance 拉数据；写一个接受参数的函数，返回 bt.Backtest；用 joblib/optuna 批量并行运行不同参数组合；用 ffn/empyrical 汇总对比。

示例（伪代码，供复制改写）
```python
import yfinance as yf
import pandas as pd
import bt
from joblib import Parallel, delayed
import itertools
import ffn

# 1. 数据
symbols = ["SPY", "QQQ", "TLT", "IWM"]  # 示例 ETF
prices = yf.download(symbols, start="2010-01-01", end="2024-01-01")["Adj Close"].dropna()

# 2. 参数化策略工厂（示例：动量 + 宏观阈值）
def make_backtest(momentum_lookback=63, top_k=2, rebalance_period='M'):
    class MyAlgo(bt.Algo):
        def __call__(self, target):
            # 简化示例：按动量选 top_k，等权再平衡
            df = target.universe
            # 此处应将指标预先计算并保存在 target.data
            return True
    s = bt.Strategy("mom", [bt.algos.RunMonthly() if rebalance_period=='M' else bt.algos.RunDaily(),
                            bt.algos.SelectAll(),
                            bt.algos.WeighEqually(),
                            bt.algos.Rebalance()])
    return bt.Backtest(s, prices)

# 3. 构建参数网格并并行运行
param_grid = {
    "momentum_lookback": [21, 63, 126],
    "top_k": [1, 2, 3],
}
combos = [dict(zip(param_grid.keys(), v)) for v in itertools.product(*param_grid.values())]

def run_combo(p):
    bt_run = bt.run(make_backtest(**p))
    stats = bt_run.stats  # 或者用 ffn 的 result 进一步分析
    return {"params": p, "stats": stats}

results = Parallel(n_jobs=4)(delayed(run_combo)(p) for p in combos)

# 4. 汇总与导出（示例）
import json
with open("results.json", "w") as f:
    json.dump(results, f, default=str)
```

关于 walk‑forward / block bootstrap / PBO 的建议
- Walk‑forward：把历史分为滚动训练/测试窗口（例如 3 年训练、1 年测试），对每个窗口跑完整参数格并记录在测试集上的表现，统计参数稳定性（多窗口一致性）。
- Block bootstrap：用 arch.bootstrap 或自实现分块重采样生成样本序列，重跑回测以估计绩效分布和置信区间。
- PBO / Deflated Sharpe：需要做大量独立样本搜索并计算超额优化偏差，通常用 optuna 控制搜索策略并配合 bootstrap/多次 walk‑forward。若要，我可以给出 PBO 的实现模板。

实践建议（针对你的 ETF+宏观轮动、只做研究、重视参数敏感性）
1. 初期快速筛选：用 bt + yfinance + pandas 在 notebook 中做少量参数网格与可视化（快速迭代）。
2. 扩展稳健性：当筛到候选参数集合后，用 optuna 做更细粒度搜索（并行 joblib/dask）。
3. 严格检验：基于候选参数，做 walk‑forward（多窗口）和 block bootstrap（arch），计算 Deflated Sharpe / PBO 指标（或近似方法）。
4. 记录与复现：用 mlflow 或把每次实验的参数/数据快照/随机种子存档，确保报告可复现。

要不要我：
- 给你一个完整的 notebook 模板（含数据加载、指标计算、bt 策略实现、optuna 搜索、walk‑forward 示例和 block bootstrap）？（我可以把代码写成可直接运行的 Notebook 片段）
- 或者只要一个更详细的 PBO / Deflated‑Sharpe 实现示例？

你想先要哪一个？
