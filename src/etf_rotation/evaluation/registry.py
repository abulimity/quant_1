"""回测登记：内容寻址 run_identity(params+code+data+execution+signal) → runs/run_metrics（ml4t-registry-system）。"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import duckdb


def run_identity(params: dict, *, git_sha: str = "", data_snapshot_id: str = "",
                 execution: str = "close", signal_version: str = "") -> str:
    """确定性 run 身份哈希：参数 + 代码 + 数据 + 执行口径 + 信号版本。

    任一维度不同即映射到不同 run_id，避免 close/open、不同代码/数据共用同一
    run_id 互相覆盖（TODO 3.7）。
    """
    blob = json.dumps(
        {"params": params, "git_sha": git_sha, "data_snapshot_id": data_snapshot_id,
         "execution": execution, "signal_version": signal_version},
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


def git_sha() -> str:
    """当前提交短哈希，用于登记回测对应的代码版本；git 不可用时返回 'unknown'。"""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def register_run(db_path: Path, run_id: str, params: dict, metrics: dict,
                 artifacts: dict, *, data_snapshot_id: str = "", env_lock_hash: str = "",
                 git_sha: str = "", report_root: Path = Path("reports")) -> str:
    """把一次回测的 params/metrics/产物路径写入 duckdb 并落 manifest.json。

    append-only：run_id 已存在时不覆写（幂等），保持首次登记的 metrics 与审计轨迹。
    """
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
    exists = con.execute("SELECT 1 FROM runs WHERE run_id = ?", [run_id]).fetchone()
    if exists:
        con.close()
        return run_id  # 幂等：相同身份重跑不覆写
    con.execute(
        "INSERT INTO runs VALUES (?, 'etf-rotation', 'bt', 'run_backtest', ?, ?, ?, ?, ?, 'ok')",
        [run_id, datetime.now(timezone.utc).isoformat(), data_snapshot_id, env_lock_hash,
         git_sha, json.dumps(params, sort_keys=True)],
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
    return run_id
