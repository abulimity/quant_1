"""清理过期 run 的大产物（计划 Task 21）。

用法：
    python scripts/prune_runs.py --dry-run                 # 默认；只打印将删哪些文件
    python scripts/prune_runs.py --apply                   # 真正删除，并给 meta 打 pruned=TRUE
    python scripts/prune_runs.py --apply --older-than-days 180 --keep-profiles full minimal

默认 `--dry-run`；`keep-profiles` 默认保留 full 档（出报告要逐笔与信号快照），
只清理 standard/minimal 档里年龄 ≥ `--older-than-days`（默认 90 天）的 run。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from etf_rotation.evaluation import prune

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "reports" / "runs"


def main() -> None:
    """薄 CLI：解析参数 → 调 `prune.prune` → 逐行打印动作与汇总。"""
    parser = argparse.ArgumentParser(description="清理过期 run 的大产物")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true",
                      help="只打印计划动作，不删文件（默认）")
    mode.add_argument("--apply", dest="dry_run", action="store_false",
                      help="真正删除文件并给 meta 打 pruned=TRUE")
    parser.set_defaults(dry_run=True)
    parser.add_argument("--keep-profiles", nargs="+", default=["full"], metavar="PROFILE",
                        help="这些档位一律不清理（默认 full）")
    parser.add_argument("--older-than-days", type=int, default=90,
                        help="只清理年龄 ≥ 该天数的 run（默认 90）")
    parser.add_argument("--root", default=None, help=f"登记根目录（默认 {RUNS_DIR}）")
    args = parser.parse_args()

    root = Path(args.root) if args.root else RUNS_DIR
    actions = prune.prune(root, keep_profiles=tuple(args.keep_profiles),
                          older_than_days=args.older_than_days,
                          dry_run=args.dry_run)
    for line in actions:
        print(line)
    mode_text = "dry-run，未改动磁盘" if args.dry_run else "已执行"
    print(f"{len(actions)} 个 run 符合清理条件（{mode_text}）；"
          f"保留档位 {list(args.keep_profiles)}，年龄 ≥ {args.older_than_days} 天")
    sys.exit(0)


if __name__ == "__main__":
    main()
