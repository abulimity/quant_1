# pre-remediation 归档（2026-10-25 审计整改，Task 10）

这些是审计整改**之前**的 52 个 run 与 14 个 family，已整体归档（未删除）：

- 归档原因：旧 run 来自 3 个 commit（`b3af110` / `d5ce1bc` / `991c5f0`）+ 5 个脏工作区 run，
  且 28 个 run 的 `equity.parquet` 首行带 NaN bootstrap 行（早期代码版本）。
- 新 campaign（`tuning-2026-10`）在单一干净 commit `5016f25` 上重建，run/family 全部换新。
- 旧 run 清单见 `old-run-ids.txt`（52 个），旧 family 清单见 `old-family-ids.txt`（14 个）。
- 数值对照：新基线 `4b303fe538c2` 与旧基线 `e925fa0ee0d5` 的 ann_return/sharpe/max_drawdown/
  calmar/total_fees **逐项相等**；净值与 `../v1.1.1/equity.csv` 零差异（N1 只改基准，不改净值）。
- 如需回看旧结果，用 `--runs-root reports/legacy/pre-remediation/runs` 指向本目录。
