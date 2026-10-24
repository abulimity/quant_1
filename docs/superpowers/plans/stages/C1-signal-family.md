# C1 信号缓存 + family 登记（Task 17–18）

**worktree / branch**：`persist-c1` / `feat/persist-c1-signal-family`
**执行位置**：worktree
**前置**：S0a 已合并

## 任务

主计划 Task 17 → 18。两个任务互不依赖，但同属一个分支。

## 独占文件

```
src/etf_rotation/signals/cache.py            # 追加 PANEL_FIELDS/SCALAR_FIELDS/save/load
src/etf_rotation/pipeline.py::_precompute_signals   # 仅这一个函数
src/etf_rotation/evaluation/registry.py      # 只在文件末尾追加 family 函数
src/etf_rotation/evaluation/overfitting.py
tests/test_signal_cache.py
tests/test_families.py
```

`pipeline.py` 的 `compute_benchmark` 由 S0b 改；`_daily_target`/`build_weights` 由 S3 改。**不要碰这两处**。

## 产出契约

- `cache.signal_id(params, data_snapshot_id)`（S0a 已有，本 stage 不要改语义）
- `cache.save(panels, scalars, sid, root, meta)` / `cache.load(sid, root)`，原子写入 `tmp-{pid}` + rename
- `data/cache/signals/{sid}/manifest.json`：`fields, dtypes, tickers, date_min, date_max, bytes, created_at, code_hash, data_snapshot_id`
- `registry.family_id(kind, spec, base_params, start, end, execution, git_sha, data_snapshot_id, campaign_id="")`
- `registry.write_family_member(root, fid, run_id, variant, campaign_id="")`、`registry.load_family(root, fid)`
- `overfitting.campaign_trials(root, campaign_id)`

## 验收

```powershell
. D:\project\quant_1\scripts\activate_data.ps1
$PY -m pytest tests/test_signal_cache.py tests/test_families.py -q

# 冷→热耗时（同一命令跑两次）
$env:ETF_SIGNAL_CACHE="off"; Measure-Command { $PY scripts\run_backtest.py 2019-01-01 2026-07-31 }
Measure-Command { $PY scripts\run_backtest.py 2019-01-01 2026-07-31 }
Get-ChildItem data\cache\signals
```

预期：测试全绿；第二次快 ≥ 4 分钟；两次 `equity.nav` 完全一致；只生成一个 `signal_id` 目录；目录里没有 `.tmp-*`。

## 注意

- 缓存是**跨 worktree 共享**的：写入必须原子，已存在且 manifest 一致则直接复用，不要覆盖或删除。
- `_precompute_signals` 命中缓存后仍要补 `close/ret/n_days/avg20` 四个派生字段，保持返回 dict 的键不变。
- `registry.py` 只追加，不改 S0a 已定的函数签名。
