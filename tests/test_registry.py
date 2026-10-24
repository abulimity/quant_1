"""旧 registry 测试的留存部分：文件哈希与数据快照 id。

原本的 duckdb `runs`/`run_metrics` 断言随登记层改为 parquet 而删除，
run_identity 的维度断言移到 `tests/test_registry_parquet.py`；
这里只留 snapshot 相关的纯函数/真实数据冒烟。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from etf_rotation.data import paths, snapshot


def test_hash_files_stable_and_order_independent():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        a = d / "a.parquet"
        a.write_bytes(b"hello")
        b = d / "b.parquet"
        b.write_bytes(b"world")
        id1 = snapshot.hash_files([a, b])
        id2 = snapshot.hash_files([b, a])
        assert id1 == id2
        a.write_bytes(b"changed")
        id3 = snapshot.hash_files([a, b])
        assert id1 != id3


@pytest.mark.skipif(not (paths.BARS.exists() and paths.IDX.exists()),
                    reason="真实 bronze 数据未就绪（需先 fetch/curate）")
def test_data_snapshot_id_nonempty_stable():
    sid = snapshot.data_snapshot_id()
    assert isinstance(sid, str) and len(sid) == 12
    assert sid == snapshot.data_snapshot_id()
