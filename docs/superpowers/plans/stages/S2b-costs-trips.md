# S2b 成本 / 往返 / 流动性（Task 11、13、16）

**worktree / branch**：`persist-s2b` / `feat/persist-s2b-costs-trips`
**执行位置**：worktree
**前置**：S1 已合并、S0a 已合并

## 任务

主计划 Task 11 → 13 → 16。

## 独占文件

```
src/etf_rotation/report/steps/costs.py
src/etf_rotation/report/steps/roundtrips.py
src/etf_rotation/report/steps/liquidity.py
tests/test_report_costs.py
tests/test_report_roundtrips.py
tests/test_report_liquidity.py
```

## 消费契约

- `ReportContext.equity`（含 `turnover`/`fees`）、`.trades`、`.transactions`、`.ticker_signals`、`.close`、`.opn`、`.amount`
- `trades.parquet` 列：`date, ticker, side, price, quantity, notional, cost`
- `transactions.parquet` 列：`Date, Security, price, quantity`

## 产出契约

- `costs.annual_cost_drag(equity, trades)`、`costs.breakeven_bps(ann_return, ann_one_side_turnover, annual_drag)`
- `roundtrips.match_round_trips(trades, signals)`
- `liquidity.slippage(transactions, trades, close, opn)`、`liquidity.capacity(weights, amount, capital=1e8, adv_window=20)`

## 验收

```powershell
. D:\project\quant_1\scripts\activate_data.ps1
& $env:PY -m pytest tests/test_report_costs.py tests/test_report_roundtrips.py tests/test_report_liquidity.py -q

& $env:PY scripts\run_backtest.py 2019-01-01 2026-07-31 --save-profile full
& $env:PY scripts\build_report_data.py --only costs,roundtrips,liquidity
```

预期：测试全绿；三个 step `ok`；`costs.reconciliation.relative_error < 0.005`；往返 5,000–12,000、胜率 40–60%；`vs_open_bps` 中位数 ≈ 0。

## 注意

- **先对账再写公式**：`equity["turnover"]` 的年度和要与 `trades.notional / (2 × nav)` 对得上（差异 > 5% 就停下，把口径写进提交说明）。`breakeven_bps` 的 `ann_one_side_turnover` 必须与这个口径一致。
- `ctx.metrics` 是 `{指标名: float}`，但 **NaN 指标可能整键缺失**（`all_stats` 会丢掉），一律用 `.get(k)`，缺键时输出 `None` 不要抛异常。
- FIFO 必须支持分数份额与跨批次卖出；费用按份额比例摊到批次。
- `capacity` 的 `capital` 单位是元，`amount` 也是元。
