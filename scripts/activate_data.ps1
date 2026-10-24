param([string]$DataRoot = "D:\project\quant_1")

# 在 worktree 中复用主仓库的数据与虚拟环境。
# 用法： . D:\project\quant_1\scripts\activate_data.ps1
$env:PYTHONIOENCODING = "utf-8"
$env:ETF_BARS_PARQUET     = "$DataRoot\data\bronze\tushare\tushare-f4f7c81a15b5779c\bars_daily.parquet"
$env:ETF_ADJ_PARQUET      = "$DataRoot\data\bronze\tushare\tushare-f4f7c81a15b5779c\fund_adj.parquet"
$env:ETF_SYMBOLS_PARQUET  = "$DataRoot\data\bronze\tushare\tushare-f4f7c81a15b5779c\symbols.parquet"
$env:ETF_INDEX_PARQUET    = "$DataRoot\data\bronze\tushare\tushare-index-86318b52ea0fbe04\index_daily.parquet"
$env:ETF_FETCHED_DIR      = "$DataRoot\data\bronze\tushare\etf_rotation"
$env:ETF_WAREHOUSE_DUCKDB = "$DataRoot\data\warehouse.duckdb"
$env:PY = "$DataRoot\.venv\Scripts\python.exe"

# worktree 没有 reports/（被 .gitignore 排除）：把基线参照拷进来，供数值对照
$legacyDst = Join-Path (Get-Location) "reports\legacy"
if (-not (Test-Path "$legacyDst\v1.1.1")) {
    New-Item -ItemType Directory -Force $legacyDst | Out-Null
    Copy-Item "$DataRoot\reports\legacy\v1.1.1" $legacyDst -Recurse -Force
}
