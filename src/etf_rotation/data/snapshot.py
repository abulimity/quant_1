"""数据快照哈希：对 bronze 输入文件与 warehouse 表指纹做内容寻址，供 run 登记复现。

目的：回测结果必须能回答「这组数字是用哪份数据算出来的」。
做法分两层：

1. `warehouse_fingerprint(con)` —— 对 warehouse 里实际参与计算的表逐表取
   行数 / 日期范围 / 行内容哈希，得到结构化指纹；`write_warehouse_manifest`
   把它写进 `data/warehouse.manifest.json`，供 `verify_warehouse` 事后比对
   （「库被悄悄重建过」必须能被发现）。
2. `data_snapshot_id()` —— 对实际被读取的 bronze 输入文件逐个算 sha256，再把
   「文件名:摘要」拼起来做一次 sha256，取前 12 位；若 manifest 存在，也把它
   的哈希并入。数据内容变了 → id 变 → 历史 run 不会被误认为可复现。

设计约束：
- 指纹只取固定列清单（`_TABLES`），不取 `downloaded_at`/`snapshot_id` 这类
  每次 curate 都会变的写入元信息，否则同一份数据每次都会得到新 id。
- manifest 内不含时间戳与绝对路径，保证跨机器/跨次 curate 的确定性。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import duckdb

from etf_rotation.data import paths

# warehouse 指纹覆盖的表与列（与 curate_data.py 写入的表一致）。
# 列清单固定：新增列不影响 id，除非显式加入这里（避免 curate 的元信息列污染身份）。
_TABLES = {
    "close_adj": ("symbol_id", "ts", "close_adj"),
    "bars_daily": ("symbol_id", "ts", "open", "high", "low", "close", "volume", "amount"),
    "symbols": ("symbol_id", "ticker"),
}

# 指纹清单与 warehouse 同目录落盘；data_snapshot_id 会并入其内容哈希。
MANIFEST = paths.WAREHOUSE.parent / "warehouse.manifest.json"


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


def _iso(value) -> str | None:
    """把 duckdb 返回的日期/时间值转成稳定字符串（None 原样返回，供 JSON 落盘）。"""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def warehouse_fingerprint(con) -> dict[str, dict]:
    """计算 warehouse 表的指纹：{表名: {rows, ts_min, ts_max, hash}}。

    哈希公式（逐表）：
        hash = Σ hash(col_1, …, col_n)        —— duckdb 多列 hash，再对全部行求和
    求和用 HUGEINT（duckdb `sum(UBIGINT)` 的返回类型），避免无符号 64 位溢出。
    表不存在时记为 `{"missing": True}`：curate 尚未跑过是可以识别的事实，
    不能与「内容变了」混为一谈。
    """
    out: dict[str, dict] = {}
    for table, cols in _TABLES.items():
        # symbols 表没有 ts 列：日期范围用 NULL 占位，保持返回结构一致
        ts_expr = "ts" if "ts" in cols else "NULL::DATE"
        # hash(...) 接受多列参数；按固定列顺序取值，保证同一行内容得到同一哈希
        sql = (
            f"SELECT count(*) AS rows, min({ts_expr}) AS ts_min, max({ts_expr}) AS ts_max, "
            f"sum(hash({', '.join(cols)})) AS hash FROM {table}"
        )
        try:
            rows, ts_min, ts_max, h = con.execute(sql).fetchone()
        except duckdb.CatalogException:
            # 表不存在（curate 未跑 / 老库）：记录缺失，不中断指纹计算
            out[table] = {"missing": True}
            continue
        out[table] = {
            "rows": int(rows),
            # 空表的 sum() 为 NULL，归零以便 JSON 可比对
            "hash": int(h) if h is not None else 0,
            "ts_min": _iso(ts_min),
            "ts_max": _iso(ts_max),
        }
    return out


def write_warehouse_manifest(con=None) -> dict[str, dict]:
    """把当前 warehouse 指纹写入 `warehouse.manifest.json`（临时文件 + 原子替换）。

    curate_data.py 在写库结束后调用一次；之后 `verify_warehouse` 用同一份清单
    校验库有没有被换过。返回写入的指纹，便于调用方打印/测试。
    """
    own = con is None
    if own:
        con = duckdb.connect(str(paths.WAREHOUSE))
    try:
        fingerprint = warehouse_fingerprint(con)
    finally:
        if own:
            con.close()
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(MANIFEST) + ".tmp")
    tmp.write_text(json.dumps(fingerprint, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, MANIFEST)
    return fingerprint


def load_manifest() -> dict[str, dict]:
    """读取 manifest；文件不存在时返回空 dict（首次 curate 之前属正常状态）。"""
    if not MANIFEST.exists():
        return {}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def verify_warehouse(con=None, strict: bool = False) -> None:
    """比对当前 warehouse 指纹与 manifest。

    strict=True：发现任何不一致（缺清单、缺表、行数/哈希/日期范围不同）抛
    RuntimeError；strict=False 只打印告警，供报告层使用。
    """
    own = con is None
    if own:
        con = duckdb.connect(str(paths.WAREHOUSE), read_only=True)
    try:
        current = warehouse_fingerprint(con)
    finally:
        if own:
            con.close()

    expected = load_manifest()
    problems: list[str] = []
    if not expected:
        problems.append("manifest 缺失（先跑 scripts/curate_data.py）")
    else:
        for table, cur in current.items():
            exp = expected.get(table)
            if exp is None:
                problems.append(f"{table}: manifest 未登记")
                continue
            if cur.get("missing") or exp.get("missing"):
                if bool(cur.get("missing")) != bool(exp.get("missing")):
                    problems.append(f"{table}: 表存在性与 manifest 不符")
                continue
            # 逐字段比较；只比较 manifest 里确实记录过的字段（向前兼容旧清单）
            for field in ("rows", "hash", "ts_min", "ts_max"):
                if field in exp and cur.get(field) != exp.get(field):
                    problems.append(f"{table}.{field}: {cur.get(field)!r} != {exp.get(field)!r}")

    if problems:
        msg = "warehouse 指纹与 manifest 不一致：" + "；".join(problems)
        if strict:
            raise RuntimeError(msg)
        print("WARNING " + msg)


def data_snapshot_id() -> str:
    """回测输入数据的内容快照 id。

    覆盖 pipeline 实际读取的 bronze 输入：ETF 行情/复权/标的、指数日线、
    以及补充拉取目录（中证2000/中证红利/fund_basic）；若 warehouse 指纹清单
    已存在，也并入其哈希，这样「同一批 bronze 但 warehouse 被重建/篡改」
    同样会得到新的 snapshot id。warehouse.duckdb 本身不入快照（体积大且
    可由 bronze 重建，清单已覆盖其内容）。
    """
    files = [paths.BARS, paths.ADJ, paths.SYMBOLS, paths.IDX]
    if paths.FETCHED.exists():
        files.extend(sorted(paths.FETCHED.glob("*.parquet")))
    if MANIFEST.exists():
        files.append(MANIFEST)
    return hash_files(files)
