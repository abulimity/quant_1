"""数据快照哈希：对 bronze 输入文件做内容寻址，供 run 登记复现。

目的：回测结果必须能回答「这组数字是用哪份数据算出来的」。
做法：对实际被读取的输入文件逐个算 sha256，再把「文件名:摘要」拼起来做一次
sha256，取前 12 位作为 snapshot id，写入 run 登记（registry）。
数据内容变了 → id 变 → 历史 run 不会被误认为可复现。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from etf_rotation.data import paths


def hash_file(path: Path) -> str:
    """单个文件的 sha256 十六进制摘要（分块读取，避免大文件一次性进内存）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_files(paths: list[Path]) -> str:
    """对一组文件做稳定内容哈希：按路径名排序，拼接「文件名:摘要」再 sha256，取前 12 位。

    公式：id = sha256( join("\\n", [f"{name_i}:{sha256_i}"]) )[:12]
    排序保证同一批文件无论传入顺序如何都得到同一个 id（内容寻址必须稳定）。
    """
    parts = [f"{p.name}:{hash_file(p)}" for p in sorted(paths)]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def data_snapshot_id() -> str:
    """回测输入数据的内容快照 id。

    覆盖 pipeline 实际读取的 bronze 输入：ETF 行情/复权/标的、指数日线、
    以及补充拉取目录（中证2000/中证红利/fund_basic）。warehouse.duckdb 为
    派生产物（可由 bronze 重建），不入快照。
    """
    files = [paths.BARS, paths.ADJ, paths.SYMBOLS, paths.IDX]
    if paths.FETCHED.exists():
        files.extend(sorted(paths.FETCHED.glob("*.parquet")))
    return hash_files(files)
