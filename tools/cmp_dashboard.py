# -*- coding: utf-8 -*-
"""逐键容差比对：src 构建结果 vs 设计稿基线 design-data.json。

数值 |diff| <= TOL 视为一致；字符串/列表/字典逐字段递归。
设计稿数据取自旧 run（git 76ad294），本看板取当前 run，已知口径差异
见 KNOWN_RULES / reports/回测报告.md「看板数据口径」。

用法：
    python tools/cmp_dashboard.py [--keys k1,k2] [--strict]

设计稿基线默认读 `.superpowers/sdd/dashboard/design-data.json`（该目录是
git 忽略的 scrub 区，不属于证据链）。要让比对可复现，把该文件放到
`tools/design-data.json`，本脚本会优先读它。
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TOL = 1e-5

# 设计稿基线：优先用入库的 tools/design-data.json，回落到本地 scratch 区
DESIGN_CANDIDATES = [
    ROOT / "tools" / "design-data.json",
    ROOT / ".superpowers/sdd/dashboard/design-data.json",
]

# 已知且已记录的口径差异（前缀匹配；--strict 时不做豁免）
KNOWN_RULES = [
    ("meta.run_id", "看板取当前 run，设计稿为旧 run"),
    ("names", "设计稿无此键：49 键契约新增的证券简称表，纯展示用，不参与任何数值比对"),
    ("meta.git_sha", "同上"),
    ("meta.generated", "同上"),
    ("meta.dsr", "DSR 取当前家族 f42d16191378，设计稿为旧家族"),
    ("dsr", "DSR 家族值与扫描口径变化（0.9931 vs 0.9934）"),
    ("sweeps", "网格按当前 sensitivity/*.json 重建，x 升序、批次为当前口径"),
    ("grid2d", "成本维度由 3 档扩到 4 档（0/8/16/24bp），note 改为当前批次"),
    ("oos", "子区间微差（旧 run 多一行 NaN bootstrap）"),
    ("oosOverride", "当前 oos_check.json 的 param_overrides 已为空"),
    ("issues", "第 5/7/10 条按当前实况改写（批次日、矩阵尺寸、override 状态）"),
    ("dist.daily", "2 个桶各差 1（旧 run 有 1 天落在桶边界）"),
    ("dist.norm", "正态曲线由旧 run 的 sd 生成，与新 run 相差 ≤1e-6"),
    ("series.hhi", "5 位舍入的 ±1e-5 tie（浮点末位，不影响图形）"),
    ("series.madMaxTicker", "并列最大偏差的取列规则（旧 run 浮点末位不同）"),
    ("series.exposure", "6 个 ticker 的类归属（设计稿 fund_basic 快照标 other）"),
    ("contribution", "6 个 ticker 的类归属导致 risk 与 other 之间互相搬移"),
    ("budgetSegments", "2 条 trigger 文案（确定性规则，其余 494 段一致）"),
    ("tickers", "同上 6 个 ticker 的 cls"),
    ("events", "同上 6 个 ticker 的 cls + 3 处价格 tie"),
    ("trades", "3 处价格 tie（跨 run float 噪声）"),
]


def known_for(path):
    for prefix, why in KNOWN_RULES:
        p = path.lstrip(".")
        if p == prefix or p.startswith(prefix + ".") or p.startswith(prefix + "["):
            return why
    return None


def compare(ours, design, path="", out=None, stats=None, strict=True):
    if out is None:
        out = []
    if stats is None:
        stats = {"ok": 0, "bad": 0, "known": 0, "known_paths": set()}

    def hit(msg, at=None):
        # `at` 让调用方指定用于匹配豁免规则的路径。顶层键必须传裸键名，
        # 否则 path 是 ""，任何 KNOWN_RULES 前缀都匹配不上。
        p = path if at is None else at
        why = None if strict else known_for(p)
        if why:
            stats["known"] += 1
            stats["known_paths"].add((why, p.split("[")[0]))
        else:
            out.append(msg)
            stats["bad"] += 1

    if isinstance(design, dict) and isinstance(ours, dict):
        for k in list(design):
            if k not in ours:
                hit(f"{path}.{k} 缺失", f"{path}.{k}" if path else k)
                continue
            compare(ours[k], design[k], f"{path}.{k}" if path else k, out, stats, strict)
        for k in ours:
            if k not in design:
                hit(f"{path}.{k} 多余", f"{path}.{k}" if path else k)
        return out, stats
    if isinstance(design, list) and isinstance(ours, list):
        if len(design) != len(ours):
            hit(f"{path} 长度 {len(ours)} != {len(design)}")
            n = min(len(design), len(ours))
        else:
            stats["ok"] += 1
            n = len(design)
        for i in range(n):
            compare(ours[i], design[i], f"{path}[{i}]", out, stats, strict)
        return out, stats
    if design is None or ours is None:
        if design is not ours:
            hit(f"{path} {ours!r} != {design!r}")
        else:
            stats["ok"] += 1
        return out, stats
    if isinstance(design, bool) or isinstance(ours, bool):
        if bool(design) != bool(ours):
            hit(f"{path} {ours!r} != {design!r}")
        else:
            stats["ok"] += 1
        return out, stats
    if isinstance(design, (int, float)) and isinstance(ours, (int, float)):
        if abs(float(ours) - float(design)) > TOL:
            hit(f"{path} {ours!r} != {design!r} (diff {float(ours) - float(design):.3e})")
        else:
            stats["ok"] += 1
        return out, stats
    if design != ours:
        hit(f"{path} {ours!r} != {design!r}")
    else:
        stats["ok"] += 1
    return out, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys", default="")
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--strict", action="store_true", help="不豁免已知差异")
    args = ap.parse_args()

    from etf_rotation.report.context import ReportContext
    from etf_rotation.report.dashboard import build_dashboard

    latest = json.loads((ROOT / "reports/latest.json").read_text(encoding="utf-8"))
    run_dir = ROOT / "reports/runs" / latest["run_id"]
    ctx = ReportContext.load(run_dir)
    only = [k for k in args.keys.split(",") if k] or None
    ours = build_dashboard(ctx, run_dir, ROOT / "reports", only=only)

    design_path = next((p for p in DESIGN_CANDIDATES if p.exists()), None)
    if design_path is None:
        sys.exit("找不到设计稿基线，试过：\n  " + "\n  ".join(str(p) for p in DESIGN_CANDIDATES))
    print(f"设计稿 : {design_path}")
    design = json.loads(design_path.read_text(encoding="utf-8"))
    total_bad = 0
    total_known = 0
    for key in ours:
        if key in design:
            out, stats = compare(ours[key], design[key], key, strict=args.strict)
        else:
            # 设计稿没有的顶层键（当前只有 names）：按「多余」判定，
            # 与嵌套键共用同一套 KNOWN_RULES 豁免和报错文本。
            out, stats = compare({key: ours[key]}, {}, "", strict=args.strict)
        status = "OK  " if not out else "DIFF"
        print("%-18s %s ok=%d bad=%d known=%d"
              % (key, status, stats["ok"], stats["bad"], stats["known"]))
        total_bad += len(out)
        total_known += stats["known"]
        for line in out[:args.max]:
            print("     ", line)
        if len(out) > args.max:
            print("      ... 共 %d 条" % len(out))
    print("\n意外差异 %d 条，已记录差异 %d 条" % (total_bad, total_known))
    return 1 if total_bad else 0


if __name__ == "__main__":
    sys.exit(main())
