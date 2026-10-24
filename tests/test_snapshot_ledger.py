"""数据快照账本测试：warehouse 指纹、manifest 比对、signal_id 的敏感性。

覆盖三条纪律：
1. 指纹必须对行内容敏感（数据变了 id 必须变），对同一内容稳定；
2. verify_warehouse 在 strict 模式下，指纹与 manifest 不一致必须报错；
3. signal_id 只随「信号相关参数 + 数据快照 + 信号代码」变化，
   组合/去重参数变化不得让信号缓存失效。
"""
from __future__ import annotations

import duckdb
import pytest

from etf_rotation.data import snapshot


def test_fingerprint_changes_when_row_changes(tmp_path):
    """新增一行 → 行数与哈希都变（内容寻址必须对行级改动敏感）。"""
    db = tmp_path / "w.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE close_adj (symbol_id INT, ts DATE, close_adj DOUBLE)")
    con.execute("INSERT INTO close_adj VALUES (1, DATE '2024-01-02', 10.0)")
    a = snapshot.warehouse_fingerprint(con)
    con.execute("INSERT INTO close_adj VALUES (1, DATE '2024-01-03', 11.0)")
    b = snapshot.warehouse_fingerprint(con)
    assert a["close_adj"]["hash"] != b["close_adj"]["hash"]
    assert b["close_adj"]["rows"] == 2


def test_fingerprint_is_stable(tmp_path):
    """同一连接连续两次调用必须完全相等（指纹本身无随机性/时间戳）。"""
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    con.execute("CREATE TABLE bars_daily (symbol_id INT, ts DATE, open DOUBLE, high DOUBLE,"
                " low DOUBLE, close DOUBLE, volume BIGINT, amount DOUBLE)")
    con.execute("INSERT INTO bars_daily VALUES (1, DATE '2024-01-02', 1, 1, 1, 1, 100, 1000)")
    assert snapshot.warehouse_fingerprint(con) == snapshot.warehouse_fingerprint(con)


def test_verify_raises_on_mismatch(tmp_path, monkeypatch):
    """manifest 与当前库不一致时，strict 模式必须抛 RuntimeError。"""
    monkeypatch.setattr(snapshot, "load_manifest", lambda: {"close_adj": {"rows": 1, "hash": 0}})
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    con.execute("CREATE TABLE close_adj (symbol_id INT, ts DATE, close_adj DOUBLE)")
    con.execute("INSERT INTO close_adj VALUES (1, DATE '2024-01-02', 10.0)")
    with pytest.raises(RuntimeError):
        snapshot.verify_warehouse(con=con, strict=True)


def test_manifest_roundtrip(tmp_path, monkeypatch):
    """写 manifest 后再读回，指纹逐字段一致（落盘格式不丢信息）。"""
    monkeypatch.setattr(snapshot, "MANIFEST", tmp_path / "warehouse.manifest.json")
    con = duckdb.connect(str(tmp_path / "w.duckdb"))
    con.execute("CREATE TABLE close_adj (symbol_id INT, ts DATE, close_adj DOUBLE)")
    con.execute("INSERT INTO close_adj VALUES (1, DATE '2024-01-02', 10.0)")
    snapshot.write_warehouse_manifest(con)
    assert snapshot.load_manifest() == snapshot.warehouse_fingerprint(con)


def test_signal_id_ignores_non_signal_params():
    """去重参数（组合层）不参与信号身份；趋势窗口（信号层）必须参与。"""
    from etf_rotation.signals import cache
    p = {"trend": {"windows": [21, 60], "weighting": "linear"},
         "risk": {"vol_window": 60}, "dedupe": {"corr_threshold": 0.8}}
    a = cache.signal_id(p, "d1")
    p["dedupe"]["corr_threshold"] = 0.75
    assert cache.signal_id(p, "d1") == a
    p["trend"]["windows"] = [20, 60]
    assert cache.signal_id(p, "d1") != a
    assert cache.signal_id(p, "d2") != cache.signal_id(p, "d1")
