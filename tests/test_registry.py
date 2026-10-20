import json
import tempfile
from pathlib import Path

import duckdb

from etf_rotation.data import snapshot
from etf_rotation.evaluation import registry


def test_config_hash_deterministic():
    assert registry.config_hash({"x": 1, "y": {"z": 2}}) == \
        registry.config_hash({"y": {"z": 2}, "x": 1})


def test_register_run_writes_rows(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = tmp_path / "r.duckdb"
    run_id = "abc123"
    report_root = tmp_path / "reports"
    registry.register_run(db, run_id, {"a": 1}, {"sharpe": 1.2},
                          {"equity": str(tmp_path / "e.csv")}, report_root=report_root)

    con = duckdb.connect(str(db))
    assert con.execute("SELECT count(*) FROM runs WHERE run_id=?", [run_id]).fetchone()[0] == 1
    assert con.execute("SELECT value FROM run_metrics WHERE run_id=? AND metric='sharpe'",
                       [run_id]).fetchone()[0] == 1.2
    con.close()

    manifest = json.loads(
        (report_root / "runs" / run_id / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifacts"]["equity"] == str(tmp_path / "e.csv")


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


def test_data_snapshot_id_nonempty_stable():
    sid = snapshot.data_snapshot_id()
    assert isinstance(sid, str) and sid
    assert sid == snapshot.data_snapshot_id()
