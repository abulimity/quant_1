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

    公式：run_id = sha256(json({params, git_sha, data_snapshot_id, execution,
                                signal_version}, sort_keys=True))[:12]
    —— sort_keys=True 保证键序固定，参数顺序不同也得到同一个 id（内容寻址）。
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
                 git_sha: str = "", execution: str = "open",
                 report_root: Path = Path("reports")) -> str:
    """把一次回测的 params/metrics/产物路径写入 duckdb 并落 manifest.json。

    append-only：run_id 已存在时不覆写 metrics，仅标记 superseded=True，保持首次登记的
    审计轨迹。execution 记入 runs 表，便于 close/open 口径可查回。
    """
    con = duckdb.connect(str(db_path))
    # runs 表：一次回测的身份与元信息（主键 run_id）
    con.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id VARCHAR PRIMARY KEY, spec_id VARCHAR NOT NULL, engine VARCHAR NOT NULL,
            origin VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL,
            data_snapshot_id VARCHAR NOT NULL, env_lock_hash VARCHAR NOT NULL,
            git_sha VARCHAR NOT NULL, params_json VARCHAR NOT NULL, status VARCHAR NOT NULL,
            execution VARCHAR NOT NULL, superseded BOOLEAN NOT NULL DEFAULT FALSE,
            CHECK (status IN ('ok', 'failed', 'partial')))
    """)
    # 迁移旧库：补 execution 列与 superseded 标记列（旧 runs 表无这两列）
    con.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS execution VARCHAR DEFAULT 'close'")
    con.execute("ALTER TABLE runs ADD COLUMN IF NOT EXISTS superseded BOOLEAN DEFAULT FALSE")
    con.execute("""
        CREATE TABLE IF NOT EXISTS run_metrics (
            run_id VARCHAR NOT NULL, metric VARCHAR NOT NULL, value DOUBLE NOT NULL,
            PRIMARY KEY (run_id, metric))
    """)
    exists = con.execute("SELECT 1 FROM runs WHERE run_id = ?", [run_id]).fetchone()
    if exists:
        # 同一身份重跑：只标记 superseded，不覆写历史 metrics（append-only）
        con.execute("UPDATE runs SET superseded = TRUE WHERE run_id = ?", [run_id])
        con.close()
        return run_id  # append-only：相同身份重跑不覆写 metrics
    con.execute(
        "INSERT INTO runs VALUES (?, 'etf-rotation', 'bt', 'run_backtest', ?, ?, ?, ?, ?, 'ok', ?, FALSE)",
        [run_id, datetime.now(timezone.utc).isoformat(), data_snapshot_id, env_lock_hash,
         git_sha, json.dumps(params, sort_keys=True), execution],
    )
    # run_metrics 表：长表存指标（每个指标一行），便于跨 run 做分布比较
    for k, v in metrics.items():
        con.execute(
            "INSERT INTO run_metrics (run_id, metric, value) VALUES (?, ?, ?)",
            [run_id, k, float(v)],
        )
    con.close()

    # manifest.json：与 duckdb 登记对等的可读快照（便于人工审阅与 diff）
    out = report_root / "runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "params": params, "metrics": metrics,
                    "artifacts": artifacts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return run_id
