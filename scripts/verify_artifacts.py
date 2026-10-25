"""校验 run 产物：哈希、跨文件对账、派生数据溯源（计划 Task 21）。

用法：
    python scripts/verify_artifacts.py                    # 校验 reports/runs 下全部 run
    python scripts/verify_artifacts.py --run-id 1a2b3c4d5e6f

退出码：0 = 全部通过（**无输出**，可直接串进脚本）；1 = 有问题（逐行打印问题）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from etf_rotation.evaluation import verify

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "reports" / "runs"


def main() -> None:
    """薄 CLI：解析参数 → 校验 run + 顶层镜像 + family，逐行打印，有真错误才非零退出。

    `WARN ` 前缀（证据纯度告警）打印但不阻塞；`--run-id` 给定时跳过顶层镜像校验
    （镜像只属于 latest，指定单个 run 时不适用）。
    """
    parser = argparse.ArgumentParser(description="校验 run 产物的哈希与跨文件一致性")
    parser.add_argument("--run-id", default=None,
                        help="只校验指定 run（默认校验 reports/runs 下全部 run）")
    parser.add_argument("--root", default=None,
                        help=f"登记根目录（默认 {RUNS_DIR}）")
    parser.add_argument("--reports-dir", default=None,
                        help=f"reports 根目录（默认 {ROOT / 'reports'}），校验 latest↔derived 镜像")
    parser.add_argument("--families-root", default=None,
                        help=f"family 根目录（默认 {ROOT / 'reports' / 'families'}）")
    parser.add_argument("--campaign", default=None,
                        help="只校验该 campaign 的 family（默认全部）")
    args = parser.parse_args()

    root = Path(args.root) if args.root else RUNS_DIR
    reports_dir = Path(args.reports_dir) if args.reports_dir else ROOT / "reports"
    families_root = (Path(args.families_root) if args.families_root
                     else ROOT / "reports" / "families")

    problems: list[str] = []
    problems.extend(verify.verify(root, args.run_id))
    if args.run_id is None:
        problems.extend(verify.verify_reports(reports_dir))
    problems.extend(verify.verify_families(families_root, root, args.campaign))

    for message in problems:
        print(message)
    if verify.has_errors(problems):
        sys.exit(1)


if __name__ == "__main__":
    main()
