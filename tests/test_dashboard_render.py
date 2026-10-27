"""看板渲染断言：用无头 Chrome 读真实产物，确认证券简称与代码都出现在该出现的地方。

前提：`reports/dashboard.html` 已由 `scripts/build_dashboard.py` 生成。
缺失时 skip，不静默通过。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def _dump(harness_html: Path, budget_ms: int = 40000) -> str:
    if shutil.which("chrome") is None and not CHROME.exists():
        pytest.skip("缺 Chrome，跳过渲染断言")
    exe = str(CHROME) if CHROME.exists() else "chrome"
    proc = subprocess.run(
        [exe, "--headless=new", "--disable-gpu", "--allow-file-access-from-files",
         f"--virtual-time-budget={budget_ms}", "--dump-dom", harness_html.as_uri()],
        capture_output=True, text=True, encoding="utf-8", timeout=180,
    )
    return proc.stdout


def _probe(script: str) -> dict:
    dash = ROOT / "reports" / "dashboard.html"
    if not dash.exists():
        pytest.skip(f"缺产物：{dash}")
    tmp = Path(tempfile.mkdtemp(prefix="dash_probe_"))
    harness = tmp / "h.html"
    harness.write_text(
        '<!doctype html><html><head><meta charset="utf-8"></head><body>'
        f'<iframe id="f" src="{dash.as_uri()}" style="width:1500px;height:950px"></iframe>'
        f'<pre id="out">pending</pre><script>const f=document.getElementById("f");'
        'f.addEventListener("load",()=>setTimeout(()=>{'
        "let out;try{"
        f"{script}"
        "out=RESULT;}catch(e){out={__error:String(e&&e.message||e)};}"
        'document.getElementById("out").textContent=JSON.stringify(out);'
        "},12000));</script></body></html>",
        encoding="utf-8",
    )
    dom = _dump(harness)
    match = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
    assert match, "harness 没有输出"
    data = json.loads(match.group(1))
    if isinstance(data, dict) and "__error" in data:
        raise AssertionError(f"harness 脚本抛异常：{data['__error']}")
    return data


@pytest.fixture(scope="module")
def probe():
    return _probe


def test_nm_returns_abbreviation_and_falls_back_to_code(probe):
    """nm 查表返回简称，查不到时回落成代码本身；nmHtml 把代码放进 title。"""
    result = probe(
        "const w=f.contentWindow; const RESULT={};"
        "RESULT.typeNm=typeof w.OD.nm; RESULT.typeHtml=typeof w.OD.nmHtml;"
        "RESULT.hasNames=!!(w.OD.D&&w.OD.D.names);"
        "RESULT.sample=typeof w.OD.nm==='function'?w.OD.nm('513100.SH'):null;"
        "RESULT.missing=typeof w.OD.nm==='function'?w.OD.nm('999999.SH'):null;"
        "RESULT.html=typeof w.OD.nmHtml==='function'?w.OD.nmHtml('513100.SH'):null;"
    )
    assert result["typeNm"] == "function", "OD.nm 没有导出"
    assert result["typeHtml"] == "function", "OD.nmHtml 没有导出"
    assert result["hasNames"], "载荷里没有 names 键"
    assert re.search(r"[\u4e00-\u9fa5]", result["sample"]), f"nm 未返回简称：{result['sample']}"
    assert result["missing"] == "999999.SH", f"nm 未回落成代码：{result['missing']}"
    assert 'title="513100.SH"' in result["html"], f"nmHtml 的 title 不含代码：{result['html']}"
    assert result["sample"] in result["html"], f"nmHtml 的正文不含简称：{result['html']}"
