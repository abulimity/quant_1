"""报告派生数据层（Stage B）：只读 `ReportContext` + step 注册 + 原子落地。

分层：
    context.py    —— run 目录 → 只读上下文（唯一读盘入口）
    serialize.py  —— DataFrame/Series/标量 → JSON 安全的 list/dict（NaN→null）
    runner.py     —— 发现 step、写临时目录、成功后原子改名、镜像 reports/derived
    steps/        —— 每个 step 只依赖 `ReportContext`，不碰文件系统

纪律：派生层只做展示性聚合，不重新推导指标；NaN/Inf 一律 null（`allow_nan=False`）。
"""
from __future__ import annotations

__all__ = ["context", "serialize", "runner"]
