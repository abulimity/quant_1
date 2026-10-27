"""看板渲染断言：用无头 Chrome 读真实产物，确认证券简称与代码都出现在该出现的地方。

前提：`reports/dashboard.html` 已由 `scripts/build_dashboard.py` 生成。
缺失时 skip，不静默通过。

CSV 相关用例必须把桩打在 iframe 的 realm 上。产物在 iframe 里运行，
`csv()` 里的 `new Blob(...)` 与 `a.click()` 解析到 iframe 的全局对象，
不是外层 harness 页面的 `window`。因此任何调用 `OD.csv`、或点击表格
`.csv` 按钮的渲染用例，都要在 iframe 上替换
`HTMLAnchorElement.prototype.click`（要拿文本时再加 `Blob`），并在
`finally` 里还原。漏掉 click 桩后，真实 `a.click()` 会触发浏览器下载，
`--dump-dom` 会一直等待：用例挂满 180 秒超时，而不是给出一条普通失败。
只替换父页面的 `window.Blob` / `window.HTMLAnchorElement` 同样无效，
因为它们和 iframe 是两个 realm。
"""
from __future__ import annotations

import csv
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


def test_narrow_ticker_columns_show_name_only(probe):
    """窄列（panoramaTable 标的 108px、topPnlTable 标的 165px）正文只放简称。"""
    result = probe(
        "const d=f.contentDocument; const RESULT={};"
        "['panoramaTable','topPnlTable','rtTable','tradeTable','candTable'].forEach(id=>{"
        "const el=d.getElementById(id); if(!el)return;"
        "const td=el.querySelector('tbody tr td:nth-child('+(id==='tradeTable'||id==='candTable'?2:1)+')');"
        "if(td)RESULT[id]={text:td.textContent.trim(),title:td.getAttribute('title')};});"
    )
    for mount, cell in result.items():
        assert not re.search(r"\d{6}\.(SH|SZ|CSI)", cell["text"]), f"{mount} 正文仍有代码：{cell}"
        assert re.search(r"\d{6}\.(SH|SZ|CSI)", cell["title"] or ""), f"{mount} 缺代码悬浮：{cell}"


def test_wide_ticker_columns_show_both(probe):
    """宽列（holdTable 标的 456px、extremeTable top3 550px、eventTable 前三大变动 380px）保留代码。"""
    result = probe(
        "const d=f.contentDocument; const RESULT={};"
        "const hd=d.querySelector('#holdTable tbody tr td:nth-child(2)');"
        "if(hd)RESULT.holdTable=hd.textContent.trim();"
        "const ex=d.querySelector('#extremeTable tbody tr td:nth-child(5)');"
        "if(ex)RESULT.extremeTable=ex.textContent.trim().slice(0,90);"
        "const ev=d.querySelector('#eventTable tbody tr td:nth-child(5)');"
        "if(ev)RESULT.eventTable=ev.textContent.trim().slice(0,90);"
    )
    for mount, text in result.items():
        assert re.search(r"[\u4e00-\u9fa5]", text), f"{mount} 没有简称：{text}"
        assert re.search(r"\d{6}\.(SH|SZ|CSI)", text), f"{mount} 没有代码：{text}"


CODE_CELL_TABLES = (
    "candTable", "holdTable", "topPnlTable", "tradeTable",
    "rtTable", "panoramaTable", "allTradeTable",
)


def test_csv_export_has_both_name_and_code(probe):
    """CSV 里标的列必须同时有简称和代码，否则导出后无法与其他表关联。

    直接调用产品代码 `OD.csv`，不复刻取值逻辑：复刻测的是测试自己，不是产品。
    断言落在「标的列那一格」上，不是整行：整行里还有类别、状态等中文字段，
    只查整行会让缺简称的回归漏过。这条不是空话，第一版正是按整行断言，
    删掉 `csv()` 的 `c.code` 分支后仍然通过，属于假绿。
    Blob 与 click 都要替换在 iframe 的 realm 上：`csv()` 在 iframe 内运行，
    解析到的是 iframe 的全局对象。替换父页面的 `window.Blob` 抓不到文本，
    真实 `a.click()` 又会触发下载让无头 Chrome 卡死。

    负面对照（临时改产品代码 -> 确认本用例变红 -> `git checkout` 还原）：

    1. 删掉 `csv()` 的 `c.code` 分支，即把两行
       `if (c.code) { ... }` / `else if (c.csv) v = c.csv(v, r);`
       改回单行 `if (c.csv) v = c.csv(v, r);`，重建后跑：
       `.venv\\Scripts\\python.exe -m pytest tests\\test_dashboard_render.py -q -k csv`
       预期红：`assert None`，标的格是 `513100.SH`，没有简称。
    2. 摘掉 `tradeTable` 的 `code: true` 标记（`{ k: "t", label: "标的", cls: "mono" }`），
       重建后跑同一条命令。
       预期红：`assert 'tradeTable' in {...}`。
    """
    result = probe(
        "const w=f.contentWindow;"
        "const RESULT={hasCsv:typeof w.OD.csv, tables:[]};"
        "const OB=w.Blob, OC=w.HTMLAnchorElement.prototype.click;"
        "w.HTMLAnchorElement.prototype.click=function(){};"
        "function capture(cfg){let cap=null;"
        "w.Blob=function(parts,opts){cap=parts.join('');return new OB(parts,opts);};"
        "try{ w.OD.csv(cfg); }finally{ w.Blob=OB; }"
        "return cap||'';}"
        "try{"
        "Object.keys(w.OD.TBL).forEach(function(id){"
        "const inst=w.OD.TBL[id]; if(!inst||!inst.cfg)return;"
        "const cols=inst.cfg.cols||[];"
        "let j=-1; cols.forEach(function(c,k){ if(c.code && j<0) j=k; });"
        "if(j<0)return;"
        "const rows=(inst.cfg.rows||[]).slice(0,3); if(!rows.length)return;"
        "RESULT.tables.push({id:id, j:j, label:String(cols[j].label), mode:cols[j].code,"
        "text:capture({cols:cols, rows:rows, csv:'probe'})});"
        "});"
        "} finally { w.Blob=OB; w.HTMLAnchorElement.prototype.click=OC; }"
    )
    assert result["hasCsv"] == "function", "OD.csv 没有导出"
    got = {t["id"] for t in result["tables"]}
    for want in CODE_CELL_TABLES:
        assert want in got, f"{want} 的标的列没有 code 标记（命中：{sorted(got)}）"
    for t in result["tables"]:
        lines = [ln for ln in t["text"].split("\r\n") if ln]
        assert lines, f"{t['id']} 的 CSV 没有内容"
        header = next(csv.reader([lines[0].lstrip("\ufeff")]))
        assert header[t["j"]] == t["label"], f"{t['id']} 表头错位：{header}"
        for line in lines[1:]:
            cell = next(csv.reader([line]))[t["j"]]
            assert re.search(r"[\u4e00-\u9fa5]", cell), f"{t['id']} 标的列缺简称：{cell}"
            assert re.search(r"\d{6}\.(SH|SZ|CSI)", cell), f"{t['id']} 标的列缺代码：{cell}"


def test_top_pnl_chart_axis_uses_abbreviation(probe):
    """y 轴放简称，代码走 hover 的 customdata（hovertemplate 是每条 trace 一份，
    代码只能逐点传入，不能写死在模板字符串里）。"""
    result = probe(
        "const d=f.contentDocument; const gd=d.getElementById('topPnlChart'); const RESULT={};"
        "RESULT.y=gd.data[0].y; RESULT.hover=gd.data[0].hovertemplate;"
        "RESULT.cd=gd.data[0].customdata;"
        "const t=gd.querySelectorAll('.ytick text');"
        "RESULT.tickW=Math.max.apply(null,Array.from(t).map(x=>Math.round(x.getBoundingClientRect().width)));"
        "RESULT.plotW=Math.round(gd.getBoundingClientRect().width);"
    )
    assert result["y"], "topPnlChart 没有数据"
    assert not any(re.search(r"\d{6}\.(SH|SZ|CSI)", str(v)) for v in result["y"]), "y 轴仍是代码"
    assert "%{customdata}" in result["hover"], f"hover 没有消费 customdata：{result['hover']}"
    assert any(re.search(r"\d{6}\.(SH|SZ|CSI)", str(v)) for v in result["cd"] or []), "hover 里没有代码"
    assert result["tickW"] < result["plotW"] * 0.35, f"y 轴标签过宽：{result['tickW']} / {result['plotW']}"


def test_d04_hover_has_name_and_code(probe):
    result = probe(
        "const d=f.contentDocument; const gd=d.getElementById('d04Chart');"
        "const tr=gd.data.filter(t=>t.stackgroup==='h')[0];"
        "const RESULT={hover:tr.hovertemplate, name:tr.name};"
    )
    assert re.search(r"[\u4e00-\u9fa5]", result["hover"]), f"d04 hover 没有简称：{result['hover']}"
    assert re.search(r"\d{6}\.(SH|SZ|CSI)", result["hover"]), f"d04 hover 没有代码：{result['hover']}"


def test_ticker_select_and_signal_title_show_name(probe):
    result = probe(
        "const d=f.contentDocument, w=f.contentWindow; const RESULT={};"
        "const sel=d.getElementById('tickerSel');"
        "RESULT.optCount=sel.options.length;"
        "RESULT.optText=sel.options[0].textContent;"
        "RESULT.optValue=sel.options[0].value;"
        "RESULT.sigTicker=d.getElementById('sigTicker').textContent;"
        "RESULT.sigTitle=d.getElementById('sigTicker').getAttribute('title');"
    )
    assert result["optCount"] > 100, "下拉没有填充"
    assert re.search(r"[\u4e00-\u9fa5]", result["optText"]), f"下拉选项没有简称：{result['optText']}"
    assert re.search(r"\d{6}\.(SH|SZ|CSI)", result["optValue"]), "下拉 option.value 被改坏了"
    assert re.search(r"[\u4e00-\u9fa5]", result["sigTicker"]), f"D06 标题没有简称：{result['sigTicker']}"
    assert re.search(r"\d{6}\.(SH|SZ|CSI)", result["sigTitle"] or ""), f"D06 标题缺代码悬浮：{result['sigTitle']}"


def test_panorama_search_matches_name_and_code(probe):
    """panoramaTable 搜索框既能按代码也能按简称命中。"""
    result = probe(
        "const d=f.contentDocument, w=f.contentWindow;"
        "const el=d.getElementById('panoramaTable'); const inst=w.OD.TBL[el.id];"
        "const se=el.querySelector('.search');"
        "function run(q){inst.q=q;inst.page=0;se.value=q;"
        "se.dispatchEvent(new Event('input',{bubbles:true}));"
        "return el.querySelector('.meta').textContent;}"
        "const row=inst.cfg.rows[0];"
        "const RESULT={code:run(row.t), name:run(w.OD.nm(row.t)), all:run('')};"
    )
    total = int(result["all"].split()[0].replace(",", ""))
    for key in ("code", "name"):
        filtered = int(result[key].split()[0].replace(",", ""))
        assert filtered < total, f"按 {key} 搜索没有收窄结果（{filtered} / {total}）"
    assert result["code"] == result["name"], "按代码与按简称命中的行数不一致"
