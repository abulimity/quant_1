param([string]$DataRoot = "D:\project\quant_1")

# Reuse the main checkout's data and virtualenv from a git worktree.
# Usage: . D:\project\quant_1\scripts\activate_data.ps1
# NOTE: keep this file ASCII-only. PowerShell 5.1 reads BOM-less .ps1 as ANSI,
# and a multi-byte CJK comment can swallow the following newline.
$env:PYTHONIOENCODING = "utf-8"
$env:ETF_BARS_PARQUET     = "$DataRoot\data\bronze\tushare\tushare-f4f7c81a15b5779c\bars_daily.parquet"
$env:ETF_ADJ_PARQUET      = "$DataRoot\data\bronze\tushare\tushare-f4f7c81a15b5779c\fund_adj.parquet"
$env:ETF_SYMBOLS_PARQUET  = "$DataRoot\data\bronze\tushare\tushare-f4f7c81a15b5779c\symbols.parquet"
$env:ETF_INDEX_PARQUET    = "$DataRoot\data\bronze\tushare\tushare_index-86318b52ea0fbe04\index_daily.parquet"
$env:ETF_FETCHED_DIR      = "$DataRoot\data\bronze\tushare\etf_rotation"
$env:ETF_WAREHOUSE_DUCKDB = "$DataRoot\data\warehouse.duckdb"
$env:PY = "$DataRoot\.venv\Scripts\python.exe"

# Worktrees do not get the gitignored reports/ tree: copy the baseline reference in.
$legacyDst = Join-Path (Get-Location) "reports\legacy"
if (-not (Test-Path "$legacyDst\v1.1.1")) {
    New-Item -ItemType Directory -Force $legacyDst | Out-Null
    Copy-Item "$DataRoot\reports\legacy\v1.1.1" $legacyDst -Recurse -Force
}
