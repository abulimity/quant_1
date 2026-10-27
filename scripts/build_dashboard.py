"""把看板数据与离线 plotly 注入设计稿，产出单文件 `reports/dashboard.html`。

用法：
    python scripts/build_dashboard.py                       # 取 reports/latest.json 指向的 run
    python scripts/build_dashboard.py --run-id 4b303fe538c2
    python scripts/build_dashboard.py --out reports/other.html
    python scripts/build_dashboard.py --template other.html # 换外壳（须含同一个数据块）

做的事只有三件：
1. 用 `etf_rotation.report.dashboard` 从 run 重算 49 键载荷；
2. 把模板里的 `window.__REPORT_DATA__ = {...};` 整块替换成新载荷（紧凑 JSON）；
3. 把 CDN 的 `<script src=...plotly...>` 换成本仓库 vendor 的内联脚本（校验 sha256）。

模板与 vendor 都不改。产物 UTF-8 无 BOM、双击可开、断网可用。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "reports" / "front-design" / "index.html"
VENDOR = ROOT / "reports" / "front-design" / "vendor" / "plotly-2.35.2.min.js"
PLOTLY_SHA256 = "6d21266ce1bd7d9e5ab4e115989c70c20de0382fd973a8f26ab58619eba4d603"
DEFAULT_OUT = ROOT / "reports" / "dashboard.html"

DATA_OPEN = "window.__REPORT_DATA__ = "
CDN_RE = re.compile(r'<script\s+src="https://cdn\.plot\.ly/plotly-[0-9.]+\.min\.js"[^>]*>\s*</script>')


def main() -> None:
    parser = argparse.ArgumentParser(description="构建单文件看板")
    parser.add_argument("--run-id", default=None, help="指定 run_id（默认 reports/latest.json）")
    parser.add_argument("--template", default=str(TEMPLATE), help="外壳 HTML")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="输出路径")
    parser.add_argument("--only", nargs="+", default=None, help="只构建指定键（体积调试用）")
    args = parser.parse_args()

    from etf_rotation.evaluation import artifacts
    from etf_rotation.report.context import ReportContext
    from etf_rotation.report.dashboard import BUILD_ORDER, build_dashboard, dumps

    try:
        run_dir = artifacts.resolve_run(ROOT / "reports" / "runs", args.run_id)
    except FileNotFoundError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        sys.exit(1)

    if not VENDOR.exists():
        print(f"错误：缺少离线 plotly：{VENDOR}", file=sys.stderr)
        sys.exit(1)
    plotly_bytes = VENDOR.read_bytes()
    digest = hashlib.sha256(plotly_bytes).hexdigest()
    if digest != PLOTLY_SHA256:
        print(f"错误：plotly 校验失败\n  期望 {PLOTLY_SHA256}\n  实际 {digest}", file=sys.stderr)
        sys.exit(1)
    plotly = plotly_bytes.decode("utf-8")

    ctx = ReportContext.load(run_dir, strict_snapshot=False)
    only = None
    if args.only:
        only = [name for value in args.only for name in value.split(",") if name]
        unknown = [k for k in only if k not in BUILD_ORDER]
        if unknown:
            print(f"错误：未知键 {unknown}", file=sys.stderr)
            sys.exit(1)
    payload = build_dashboard(ctx, run_dir, ROOT / "reports", only=only)
    data_json = dumps(payload)

    template = Path(args.template)
    html = template.read_text(encoding="utf-8")

    start = html.find(DATA_OPEN)
    if start < 0:
        print(f"错误：模板缺少 {DATA_OPEN.strip()} 数据块：{template}", file=sys.stderr)
        sys.exit(1)
    open_brace = start + len(DATA_OPEN)
    close_tag = html.find("</script>", open_brace)
    if close_tag < 0:
        print("错误：模板数据块未闭合", file=sys.stderr)
        sys.exit(1)
    body = html[open_brace:close_tag].rstrip()
    if not body.endswith(";"):
        print("错误：模板数据块不是以 `};` 结束", file=sys.stderr)
        sys.exit(1)

    html = html[:open_brace] + data_json + html[open_brace + len(body.rstrip(";")) + 1:]

    n_cdn = len(CDN_RE.findall(html))
    if n_cdn != 1:
        print(f"错误：模板里 CDN plotly script 出现 {n_cdn} 次，预期 1 次", file=sys.stderr)
        sys.exit(1)
    html = CDN_RE.sub(lambda _m: "<script>" + plotly + "</script>", html, count=1)

    for cid in ("navddChart", "eventChart"):
        if f'id="{cid}"' not in html:
            print(f"错误：外壳缺少图表容器 #{cid}", file=sys.stderr)
            sys.exit(1)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8", newline="\n")

    written = out.read_bytes()
    print(f"run_id : {run_dir.name}")
    print(f"模板   : {template.name}")
    print(f"产物   : {out}")
    print(f"顶层键 : {len(payload)} / {len(BUILD_ORDER)}")
    print(f"数据   : {len(data_json) / 1e6:.2f} MB")
    print(f"plotly : 内联 {len(plotly) / 1e6:.2f} MB  sha256 {digest[:12]}")
    print(f"体积   : {len(written) / 1e6:.2f} MB")
    print(f"sha256 : {hashlib.sha256(written).hexdigest()}")
    print(f"外部引用: {len(re.findall(r'<(?:script|link)[^>]*(?:src|href)=.https?://', html))} 处")


if __name__ == "__main__":
    main()
