"""回测登记：内容寻址 hash(params) → runs/run_metrics（ml4t-registry-system）。"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def config_hash(params: dict) -> str:
    """确定性参数哈希：同配置永远映射到同一 run_id。"""
    blob = json.dumps(params, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def register_run(db_path: Path, run_id: str, params: dict, metrics: dict,
                 artifacts: dict, report_root: Path = Path("reports")) -> None:
    """把一次回测的 params/metrics/产物路径写入 duckdb 并落 manifest.json。"""
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id VARCHAR PRIMARY KEY, spec_id VARCHAR NOT NULL, engine VARCHAR NOT NULL,
            origin VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL,
            data_snapshot_id VARCHAR NOT NULL, env_lock_hash VARCHAR NOT NULL,
            git_sha VARCHAR NOT NULL, params_json VARCHAR NOT NULL, status VARCHAR NOT NULL,
            CHECK (status IN ('ok', 'failed', 'partial')))
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS run_metrics (
            run_id VARCHAR NOT NULL, metric VARCHAR NOT NULL, value DOUBLE NOT NULL,
            PRIMARY KEY (run_id, metric))
    """)
    con.execute(
        "INSERT OR REPLACE INTO runs VALUES (?, 'etf-rotation', 'bt', 'run_backtest', ?, '', '', ?, ?, 'ok')",
        [run_id, datetime.now(timezone.utc).isoformat(), git_sha(),
         json.dumps(params, sort_keys=True)],
    )
    for k, v in metrics.items():
        con.execute(
            "INSERT OR REPLACE INTO run_metrics (run_id, metric, value) VALUES (?, ?, ?)",
            [run_id, k, float(v)],
        )
    con.close()

    out = report_root / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "params": params, "metrics": metrics,
                    "artifacts": artifacts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
