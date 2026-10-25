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
    """薄 CLI：解析参数 → 调 `verify.verify` → 有问题就逐行打印并非零退出。"""
    parser = argparse.ArgumentParser(description="校验 run 产物的哈希与跨文件一致性")
    parser.add_argument("--run-id", default=None,
                        help="只校验指定 run（默认校验 reports/runs 下全部 run）")
    parser.add_argument("--root", default=None,
                        help=f"登记根目录（默认 {RUNS_DIR}）")
    args = parser.parse_args()

    root = Path(args.root) if args.root else RUNS_DIR
    problems = verify.verify(root, args.run_id)
    for message in problems:
        print(message)
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
