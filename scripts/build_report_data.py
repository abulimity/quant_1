"""生成报告派生数据（Stage B）：`reports/runs/{run_id}/derived/` + `reports/derived/`。

用法：
    python scripts/build_report_data.py                 # 取 reports/latest.json 指向的 run
    python scripts/build_report_data.py --latest        # 同上（显式）
    python scripts/build_report_data.py --run-id 1a2b3c4d5e6f
    python scripts/build_report_data.py --only alignment relative

前置：run 必须是 `--save-profile full`（full 才有逐笔/信号快照，报告要用）；
档位不足时报错并给出重跑命令，而不是拿半份数据出图。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "reports" / "runs"
MIRROR_DIR = ROOT / "reports" / "derived"

RERUN_HINT = "python scripts/run_backtest.py 2019-01-01 2026-07-31 --save-profile full"


def main() -> None:
    parser = argparse.ArgumentParser(description="生成报告派生数据")
    parser.add_argument("--run-id", default=None, help="指定 run_id（默认读 reports/latest.json）")
    parser.add_argument("--latest", action="store_true", help="使用 reports/latest.json 指向的 run")
    parser.add_argument("--only", nargs="+", default=None, metavar="STEP",
                        help="只跑指定 step（其余同 run 产物保留）")
    args = parser.parse_args()

    if args.run_id and args.latest:
        parser.error("--run-id 与 --latest 只能选一个")

    # 允许 `--only a,b,c` 与 `--only a b c` 两种写法：文档与验收命令混用过，
    # 不拆分会把 "a,b,c" 当成一个未知 step 名。
    if args.only:
        args.only = [name for value in args.only for name in value.split(",") if name]

    from etf_rotation.evaluation import artifacts
    from etf_rotation.report import runner
    from etf_rotation.report.context import ReportContext

    try:
        run_dir = artifacts.resolve_run(RUNS_DIR, args.run_id)
    except FileNotFoundError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)

    profile = str(pd.read_parquet(run_dir / "meta.parquet").iloc[0]["save_profile"])
    if profile != "full":
        print(f"错误：run {run_dir.name} 的档位是 {profile!r}，报告派生数据需要 full 档。\n"
              f"请重跑：{RERUN_HINT}", file=sys.stderr)
        sys.exit(1)

    ctx = ReportContext.load(run_dir, strict_snapshot=False)
    try:
        results = runner.run(run_dir, ctx, only=args.only, mirror_to=MIRROR_DIR)
    except ValueError as exc:   # 未知 step 名
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)

    print(f"run_id: {ctx.run_id}")
    print(f"derived: {run_dir / 'derived'}  (mirror -> {MIRROR_DIR})")
    for name, status in results.items():
        flag = "ok  " if status["ok"] else "FAIL"
        detail = f" {status['error']}" if status["error"] else ""
        print(f"  {flag} {name:<16} {status['duration_ms']:>8.1f} ms{detail}")

    failed = [name for name, status in results.items() if not status["ok"]]
    if failed:
        print(f"失败 step: {failed}（index.json 已写，其余结果可用）", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
