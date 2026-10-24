"""报告派生 step 包。

每个 step 是一个独立模块，暴露：
    NAME: str                  —— 派生文件名与 index.json 的键（`derived/{NAME}.json`）
    build(ctx) -> dict | ...   —— 只读 `ReportContext`，返回可 JSON 序列化的 payload

runner 用 `pkgutil.iter_modules` 自动发现，本文件不导入任何 step（避免循环导入）。
"""
from __future__ import annotations
