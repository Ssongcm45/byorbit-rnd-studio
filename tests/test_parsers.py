"""M3-2 묶음 P 시험: 파서 도구 목록·상태(미설치 → 준비 안 됨 + 설치 안내), PyMuPDF·pdfplumber 실제 파싱(표 포함),
RapidOCR 전 쪽 OCR(가짜 OCR), Docling·kordoc 변환 함수(가짜·기록한 결과), Upstage 요청 구성(가짜 opener)·기밀 차단·키 가림,
비교·선택(다시 청킹 + 사용자 라벨 옮기기·측정값 연결 보고), 형식별 기본 도구 저장·투입 반영, API."""
from __future__ import annotations

import io
import json
import time
import urllib.error

import pytest

KEY = "up_test_secret_key_1234567890"


# ---------------------------------------------------------------- 준비

@pytest.fixture(scope="module")
def home(tmp_path_factory):
    from app import db, thesaurus
    h = tmp_path_factory.mktemp("parsers_home")
    mp = pytest.MonkeyPatch()
    mp.setenv("BYORBIT_HOME", str(h))
    thesaurus.invalidate()
    db.init(seed=True)
    yield h
    mp.undo()
    thesaurus.invalidate()


@pytest.fixture(scope="module")
def samples(home, tmp_path_factory):
    from app import sample_files
    return sample_files.make_all(tmp_path_factory.mktemp("parser_samples"))


@pytest.fixture(scope="module")
def pdf_doc(home, samples):
    from app.ingest import pipeline
    r = pipeline.ingest_file(samples["pdf"], project="파서 시험", confidentiality="일반")
    assert r["status"]["parse"] == "done", r
    return r["doc_id"]


def _copy(samples, key, tmp_path, name):
    import shutil
    dst = tmp_path / name
    shutil.copy2(samples[key], dst)
    if dst.suffix in (".pdf", ".txt"):   # 같은 파일(sha256)은 중복으로 거절되므로 끝에 이름을 덧붙인다(읽기에는 영향 없음)
        dst.write_bytes(dst.read_bytes() + ("\n" + name).encode("utf-8"))
    return dst


def _has_pdfplumber():
    try:
        import pdfplumber  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------- 목록·상태

def test_registry_lists_all_tools(home):
    from app.ingest import parser_tools as PT
    tools = PT.tools(reload=True)
    assert {"pymupdf", "pdfplumber", "rapidocr", "hwpx", "xlsx", "text", "docling", "kordoc", "upstage"} <= set(tools)
    assert not PT._load_errors
    assert tools["upstage"].kind == "cloud" and all(t.kind == "local" for k, t in tools.items() if k != "upstage")
    info = tools["pymupdf"].info()
    assert info["ready"] and info["formats"] == [".pdf"] and not info["sends_file"]
    assert tools["upstage"].info()["sends_file"]
    assert {t.key for t in PT.for_ext(".hwp")} >= {"kordoc", "upstage"}


def test_missing_deps_not_ready_with_hint(home, monkeypatch):
    import importlib.util

    from app.ingest import parser_tools as PT
    from app.ingest import parsers
    from app.ingest.parser_tools import docling_tool, kordoc_tool
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda n, *a: None if n == "docling" else real(n, *a))
    st = docling_tool.TOOL.status()
    assert not st["ready"] and "install-docling.bat" in st["hint"]

    monkeypatch.setattr(parsers, "ocr_available", lambda: False)
    st = PT.get("rapidocr").status()
    assert not st["ready"] and "install-ocr.bat" in st["hint"]

    monkeypatch.delenv("BYORBIT_UPSTAGE_KEY", raising=False)
    st = PT.get("upstage").status()
    assert not st["ready"] and "BYORBIT_UPSTAGE_KEY" in st["hint"]

    monkeypatch.setattr(kordoc_tool, "node_exe", lambda: None)
    st = PT.get("kordoc").status()
    assert not st["ready"] and "Node.js" in st["hint"]
    monkeypatch.setattr(kordoc_tool, "node_exe", lambda: "node")
    monkeypatch.setattr(kordoc_tool, "find_kordoc", lambda: (None, None))
    st = PT.get("kordoc").status()
    assert not st["ready"] and "install-kordoc.bat" in st["hint"]


def test_run_rejects_not_ready_and_wrong_format(home, samples, monkeypatch):
    from app.ingest import parser_tools as PT
    from app.ingest import parsers
    monkeypatch.setattr(parsers, "ocr_available", lambda: False)
    with pytest.raises(PT.NotReady) as e:
        PT.run("rapidocr", samples["pdf"])
    assert "install-ocr.bat" in str(e.value)
    with pytest.raises(PT.ToolError) as e:
        PT.run("pdfplumber", samples["hwpx"])
    assert "읽지 못합니다" in str(e.value)
    with pytest.raises(PT.ToolError):
        PT.get("없는도구")


# ---------------------------------------------------------------- 로컬 도구 실제 실행

def _table_with(blocks, value):
    return [b for b in blocks if b["type"] == "table" and any(value in c for r in b["rows"] for c in r)]


def test_pymupdf_tool_on_sample_pdf(home, samples):
    from app.ingest import parser_tools as PT
    out = PT.run("pymupdf", samples["pdf"])
    m = out["meta"]
    assert m["tool"] == "pymupdf" and m["tool_ver"] and m["duration_ms"] >= 0
    assert _table_with(out["blocks"], "54.2"), "표(54.2)가 있어야 한다"
    assert any(b["type"] == "heading" and "Results" in b["text"] for b in out["blocks"])
    st = PT.stats(out)
    assert st["tables"] == 1 and st["pages"] == 1 and st["chars"] > 300


@pytest.mark.skipif(not _has_pdfplumber(), reason="pdfplumber 미설치")
def test_pdfplumber_tool_on_sample_pdf(home, samples):
    from app.ingest import parser_tools as PT
    out = PT.run("pdfplumber", samples["pdf"])
    blocks = out["blocks"]
    t = _table_with(blocks, "54.2")
    assert t and len(t[0]["rows"]) == 3 and t[0]["rows"][1][0] == "동결건조"
    heads = [b["text"] for b in blocks if b["type"] == "heading"]
    assert "Abstract" in heads and "3. Results" in heads
    # 숫자로 시작하는 본문 줄('991.43, 총폴리페놀은…')을 제목으로 잘못 올리지 않는다
    assert not any(h.startswith("991.43") for h in heads)
    # 표는 위→아래 제자리(결론 뒤)에 온다
    kinds = [b["type"] for b in blocks]
    assert kinds.index("table") > max(i for i, b in enumerate(blocks) if b["type"] == "heading")
    assert out["meta"]["pages"] == 1 and not out["meta"]["needs_ocr"]


def test_hwpx_xlsx_text_tools(home, samples):
    from app.ingest import parser_tools as PT
    assert _table_with(PT.run("hwpx", samples["hwpx"])["blocks"], "비건가죽")
    assert _table_with(PT.run("xlsx", samples["coa"])["blocks"], "총식이섬유")
    assert any(b["type"] == "heading" for b in PT.run("text", samples["txt"])["blocks"])


def test_rapidocr_forces_ocr_on_every_page(home, samples, monkeypatch):
    from app.ingest import parser_tools as PT
    from app.ingest import parsers
    calls = []

    def fake_lines(img):
        calls.append(type(img).__name__)
        box = lambda x, y: [[x, y], [x + 80, y], [x + 80, y + 20], [x, y + 20]]  # noqa: E731
        return [{"text": "3. Results", "box": box(10, 10), "score": 0.99},
                {"text": "건조 후 수분은 7.9%였다.", "box": box(10, 60), "score": 0.95}]

    monkeypatch.setattr(parsers, "ocr_available", lambda: True)
    monkeypatch.setattr(parsers, "_ocr_lines", fake_lines)
    out = PT.run("rapidocr", samples["pdf"])
    assert calls == ["bytes"], "글자층이 있는 쪽도 그림으로 찍어 OCR해야 한다"
    assert out["meta"]["ocr_pages"] == [1] and out["meta"]["ocr"] is True
    assert all(b["page"] == 1 for b in out["blocks"])
    assert PT.stats(out)["ocr_pages"] == 1
    assert any("7.9%" in b["text"] for b in out["blocks"])


# ---------------------------------------------------------------- Docling 변환(가짜 DoclingDocument)

class _L:
    def __init__(self, v):
        self.value = v


class _Prov:
    def __init__(self, p):
        self.page_no = p


class _Item:
    def __init__(self, label, text="", page=1, level=None, data=None, caption=""):
        self.label, self.text, self.prov, self.level, self.data, self._cap = _L(label), text, [_Prov(page)], level, data, caption

    def caption_text(self, doc):
        return self._cap


class _Cell:
    def __init__(self, text, rs=1, cs=1):
        self.text, self.row_span, self.col_span = text, rs, cs


class _Data:
    def __init__(self, grid):
        self.grid = grid


class _Doc:
    def __init__(self, items, pages=2):
        self._items, self.pages = items, {i + 1: None for i in range(pages)}

    def iterate_items(self):
        for it in self._items:
            yield it, 1


def test_docling_convert_document():
    from app.ingest.parser_tools import docling_tool
    merged = _Cell("시료", rs=2)
    grid = [[merged, _Cell("TDF")], [merged, _Cell("54.2")]]
    doc = _Doc([
        _Item("title", "사과박 건조 논문"),
        _Item("page_header", "학회지 12권"),
        _Item("section_header", "2.1 시료", level=2),
        _Item("text", "사과박을 동결건조하였다."),
        _Item("list_item", "AOAC 991.43"),
        _Item("table", page=2, data=_Data(grid), caption="Table 1. 성분"),
        _Item("caption", "Table 1. 성분", page=2),
        _Item("picture", "", page=2),
    ])
    out = docling_tool.convert_document(doc)
    b = out["blocks"]
    assert b[0] == {"type": "heading", "text": "사과박 건조 논문", "level": 1, "page": 1}
    assert b[1]["type"] == "heading" and b[1]["level"] == 2
    assert [x["type"] for x in b] == ["heading", "heading", "text", "text", "table"]
    t = b[-1]
    assert t["page"] == 2 and t["caption"] == "Table 1. 성분" and t["rows"] == [["시료", "TDF"], ["", "54.2"]]
    assert out["meta"]["pages"] == 2
    assert "page_header 1개" in out["meta"]["warnings"][0] and "picture 1개" in out["meta"]["warnings"][0]


# ---------------------------------------------------------------- kordoc 변환(기록한 결과)

KORDOC_HWP = {
    "success": True, "version": "2.5.2", "fileType": "hwp", "pageCount": 1, "metadata": {"pageCount": 1},
    "warnings": [{"message": "이미지 1개를 건너뜀", "code": "SKIPPED_IMAGE"}],
    "blocks": [
        {"type": "table", "pageNumber": 1, "table": {"rows": 1, "cols": 1, "cells": [[{"text": "주요 가공식품 주간가격 동향", "colSpan": 1, "rowSpan": 1}]], "hasHeader": False}},
        {"type": "paragraph", "text": "1. 과제 개요", "pageNumber": 1},
        {"type": "paragraph", "text": "2011년 12월 23일", "pageNumber": 1, "footnoteText": "잠정치"},
        {"type": "heading", "text": "가공식품 가격", "level": 2, "pageNumber": 1},
        {"type": "list", "listType": "ordered", "pageNumber": 1,
         "children": [{"type": "paragraph", "text": "라면"}, {"type": "paragraph", "text": "두부"}]},
        {"type": "table", "pageNumber": 1, "table": {"rows": 3, "cols": 3, "hasHeader": True, "cells": [
            [{"text": "품목", "colSpan": 1, "rowSpan": 2}, {"text": "가격", "colSpan": 2, "rowSpan": 1}],
            [{"text": "11월", "colSpan": 1, "rowSpan": 1}, {"text": "12월", "colSpan": 1, "rowSpan": 1}],
            [{"text": "두부", "colSpan": 1, "rowSpan": 1}, {"text": "1,200", "colSpan": 1, "rowSpan": 1}, {"text": "1,250", "colSpan": 1, "rowSpan": 1}]]}},
        {"type": "image", "pageNumber": 1, "image": {"mimeType": "image/png"}},
    ]}


def test_kordoc_convert_recorded_output():
    from app.ingest.parser_tools import kordoc_tool
    out = kordoc_tool.convert(KORDOC_HWP)
    b = out["blocks"]
    assert b[0] == {"type": "text", "text": "주요 가공식품 주간가격 동향", "page": 1}, "한 칸짜리 표는 본문으로"
    assert b[1]["type"] == "heading" and b[1]["text"] == "1. 과제 개요"
    assert "(주: 잠정치)" in b[2]["text"]
    assert b[3] == {"type": "heading", "text": "가공식품 가격", "level": 2, "page": 1}
    assert b[4]["text"] == "1. 라면\n2. 두부"
    assert b[5]["type"] == "table" and b[5]["rows"] == [["품목", "가격", ""], ["", "11월", "12월"], ["두부", "1,200", "1,250"]]
    assert out["meta"]["file_type"] == "hwp" and out["meta"]["page_unit"] == "section"
    assert any("이미지 1개" in w for w in out["meta"]["warnings"]) and any("image 1개" in w for w in out["meta"]["warnings"])


def test_kordoc_failure_codes_become_korean_direction():
    from app.ingest.parser_tools import ToolError, kordoc_tool
    with pytest.raises(ToolError) as e:
        kordoc_tool.convert({"success": False, "error": "x", "code": "MISSING_DEPENDENCY"})
    assert "install-kordoc.bat" in str(e.value)
    with pytest.raises(ToolError) as e:
        kordoc_tool.convert({"success": False, "error": "x", "code": "ENCRYPTED"})
    assert "암호" in str(e.value)


def test_kordoc_bridge_output_ignores_noise(monkeypatch, tmp_path):
    """pdfjs가 stdout에 경고를 찍어도 표시(MARK) 줄만 읽는다."""
    import subprocess

    from app.ingest.parser_tools import kordoc_tool

    class P:
        returncode = 0
        stdout = ("Warning: loadFont failed\n" + kordoc_tool.MARK + json.dumps(KORDOC_HWP, ensure_ascii=False) + "\n").encode("utf-8")
        stderr = b""
    seen = {}

    def fake_run(args, **kw):
        seen["args"] = args
        return P()
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(kordoc_tool, "node_exe", lambda: "node")
    r = kordoc_tool._run_bridge(tmp_path / "index.js", "a.hwp", {})
    assert r["success"] and seen["args"][1].endswith("kordoc_bridge.mjs")


def test_kordoc_real_hwpx_if_installed(home, samples):
    from app.ingest import parser_tools as PT
    if not PT.get("kordoc").status().get("ready"):
        pytest.skip("kordoc/Node 미설치")
    out = PT.run("kordoc", samples["hwpx"])
    assert _table_with(out["blocks"], "바이오플라스틱 필러")
    assert out["meta"]["tool_ver"]


# ---------------------------------------------------------------- Upstage (가짜 응답)

UPSTAGE_RESP = {
    "api": "2.0", "model": "document-parse-260930", "usage": {"pages": 1},
    "content": {"html": "", "markdown": "", "text": ""},
    "elements": [
        {"category": "header", "content": {"html": "<header>학회지</header>", "text": "학회지"}, "page": 1, "id": 0},
        {"category": "heading1", "content": {"html": "<h1>3. Results</h1>", "text": "3. Results"}, "page": 1, "id": 1},
        {"category": "paragraph", "content": {"html": "<p>총식이섬유는 54.2 g/100 g이었다.</p>", "text": ""}, "page": 1, "id": 2},
        {"category": "table", "page": 1, "id": 3, "content": {"text": "", "html":
            "<table><tr><th rowspan='2'>시료</th><th colspan='2'>성분</th></tr><tr><td>TDF</td><td>TPC</td></tr>"
            "<tr><td>동결건조</td><td>54.2</td><td>9.8</td></tr></table>"}},
        {"category": "footer", "content": {"html": "<footer>1</footer>", "text": "1"}, "page": 1, "id": 4},
    ]}


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


@pytest.fixture
def upstage_fake(monkeypatch):
    from app.collect import http
    seen = []

    def opener(req, timeout):
        seen.append(req)
        return FakeResp(json.dumps(UPSTAGE_RESP).encode("utf-8"))
    monkeypatch.setenv("BYORBIT_UPSTAGE_KEY", KEY)
    monkeypatch.setattr(http, "MIN_INTERVAL", {"default": 0.0})
    http.set_opener(opener)
    yield seen
    http.set_opener(None)


def test_upstage_html_table_spans():
    from app.ingest.parser_tools import upstage_tool
    rows = upstage_tool.html_table_rows(UPSTAGE_RESP["elements"][3]["content"]["html"])
    assert rows == [["시료", "성분", ""], ["", "TDF", "TPC"], ["동결건조", "54.2", "9.8"]]


def test_upstage_request_and_conversion(home, samples, tmp_path, upstage_fake):
    from app.ingest import parser_tools as PT
    import shutil
    f = tmp_path / "비밀과제_업체명.pdf"
    shutil.copy2(samples["pdf"], f)
    out = PT.run("upstage", f, {"confidentiality": "일반", "mode": "enhanced"})
    req = upstage_fake[0]
    assert req.full_url == "https://api.upstage.ai/v1/document-digitization" and req.get_method() == "POST"
    assert req.get_header("Authorization") == f"Bearer {KEY}"
    assert req.get_header("Content-type").startswith("multipart/form-data; boundary=")
    body = req.data
    assert b'name="model"\r\n\r\ndocument-parse\r\n' in body and b'name="mode"\r\n\r\nenhanced' in body
    assert b'filename="document.pdf"' in body
    assert "비밀과제".encode("utf-8") not in body, "파일 이름은 보내지 않는다"
    assert body.count(b"%PDF") == 1
    b = out["blocks"]
    assert [x["type"] for x in b] == ["heading", "text", "table"]
    assert b[1]["text"] == "총식이섬유는 54.2 g/100 g이었다."   # text가 비면 HTML에서 글자를 꺼낸다
    assert b[2]["rows"][2] == ["동결건조", "54.2", "9.8"]
    assert out["meta"]["billed_pages"] == 1 and "header 1개" in out["meta"]["warnings"][0]


def test_upstage_guard_blocks_secret_and_unknown(home, samples, upstage_fake):
    from app.ingest import parser_tools as PT
    with pytest.raises(PT.CloudBlocked) as e:
        PT.run("upstage", samples["pdf"], {"confidentiality": "기밀", "confirm_cloud": True})
    assert "기밀" in str(e.value)
    with pytest.raises(PT.CloudBlocked):
        PT.run("upstage", samples["pdf"], {})          # 보안 등급을 모르면 보내지 않는다
    with pytest.raises(PT.NeedsConfirm):
        PT.run("upstage", samples["pdf"], {"confidentiality": "내부"})
    assert upstage_fake == [], "막힌 요청은 한 번도 나가지 않아야 한다"


def test_upstage_secret_document_hard_block_via_results(home, samples, tmp_path, upstage_fake):
    from app import db
    from app.ingest import pipeline
    from app.ingest.parser_tools import CloudBlocked, NeedsConfirm, results
    f = _copy(samples, "pdf", tmp_path, "기밀문서.pdf")
    doc = pipeline.ingest_file(f, project="파서 시험", confidentiality="기밀")["doc_id"]
    with pytest.raises(CloudBlocked):
        results.parse_with(doc, "upstage", {}, confirm_cloud=True)
    assert results.estimate(doc, "upstage")["blocked"]
    with db.tx() as c:
        c.execute("UPDATE source SET confidentiality='내부' WHERE source_id=(SELECT source_id FROM document WHERE doc_id=?)", (doc,))
    with pytest.raises(NeedsConfirm):
        results.parse_with(doc, "upstage", {})
    assert upstage_fake == []
    r = results.parse_with(doc, "upstage", {"mode": "standard"}, confirm_cloud=True)
    assert r["status"] == "ok" and r["kind"] == "cloud" and r["stats"]["billed_pages"] == 1
    assert "confidentiality" not in r["stats"]["options"]
    est = results.estimate(doc, "upstage", {"mode": "standard"})
    assert est["pages"] == 1 and est["usd"] == 0.01 and est["needs_confirm"]


def test_upstage_key_redacted_in_errors(home, samples, monkeypatch):
    from app.collect import http
    from app.ingest import parser_tools as PT
    monkeypatch.setenv("BYORBIT_UPSTAGE_KEY", KEY)
    monkeypatch.setattr(http, "MIN_INTERVAL", {"default": 0.0})

    def bad(req, timeout):
        raise urllib.error.URLError(f"proxy rejected token {KEY}")
    http.set_opener(bad)
    try:
        with pytest.raises(PT.ToolError) as e:
            PT.run("upstage", samples["pdf"], {"confidentiality": "일반"})
    finally:
        http.set_opener(None)
    assert KEY not in str(e.value) and "***" in str(e.value)

    def unauthorized(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
    http.set_opener(unauthorized)
    try:
        with pytest.raises(PT.ToolError) as e:
            PT.run("upstage", samples["pdf"], {"confidentiality": "일반"})
    finally:
        http.set_opener(None)
    assert "BYORBIT_UPSTAGE_KEY" in str(e.value) and KEY not in str(e.value)


# ---------------------------------------------------------------- 결과 저장·비교·선택(다시 청킹)

def test_ingest_records_first_parse_as_chosen(home, pdf_doc):
    from app import db
    from app.ingest.parser_tools import results
    rs = results.list_results(pdf_doc)
    assert len(rs) == 1 and rs[0]["tool"] == "pymupdf" and rs[0]["chosen"]
    d = db.one("SELECT parse_status, parser_ver FROM document WHERE doc_id=?", (pdf_doc,))
    assert json.loads(d["parse_status"])["tool"] == "pymupdf" and d["parser_ver"].startswith("pymupdf/")
    assert (home / "parsed" / pdf_doc).is_dir()


@pytest.mark.skipif(not _has_pdfplumber(), reason="pdfplumber 미설치")
def test_compare_and_choose_moves_manual_annotations(home, pdf_doc):
    from app import db
    from app.ingest.parser_tools import results
    # 사용자 라벨 2개(하나는 새 결과에 없는 표기) + 측정값 연결 + 사전 라벨 1개에 측정값 연결
    ch = db.one("SELECT chunk_id, text FROM chunk WHERE doc_id=? AND text LIKE '%54.2 g/100 g%' ORDER BY ord", (pdf_doc,))
    i = ch["text"].find("54.2 g/100 g")
    auto = db.one("SELECT ann_id FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id WHERE c.doc_id=? AND a.method='dict' LIMIT 1",
                  (pdf_doc,))["ann_id"]
    keep_id, lost_id = "a" * 32, "b" * 32
    with db.tx() as c:
        c.execute("INSERT INTO annotation(ann_id, chunk_id, span_start, span_end, surface_text, label_type, method, status) "
                  "VALUES (?,?,?,?, '54.2 g/100 g', 'VALUE', 'human', 'accepted')", (keep_id, ch["chunk_id"], i, i + 12))
        c.execute("INSERT INTO annotation(ann_id, chunk_id, span_start, span_end, surface_text, label_type, method, status) "
                  "VALUES (?,?,0,5, '없는표기XYZ', 'VALUE', 'human', 'accepted')", (lost_id, ch["chunk_id"]))
        for mid, aid in (("m-keep", keep_id), ("m-lost", lost_id), ("m-auto", auto)):
            c.execute("INSERT INTO measurement(meas_id, target_text, value, ann_id, doc_id, entry) VALUES (?, '총식이섬유', 54.2, ?, ?, 'extracted')",
                      (mid, aid, pdf_doc))
        c.execute("INSERT INTO report(report_id, title, body_md) VALUES ('r1', 't', 'b')")
        c.execute("INSERT INTO report_citation(cit_id, report_id, claim_text, chunk_id) VALUES ('c1', 'r1', '주장', ?)", (ch["chunk_id"],))
    imp = results.impact(pdf_doc)
    assert imp["manual"] == 2 and imp["linked_measurements"] == 3

    r = results.parse_with(pdf_doc, "pdfplumber")
    assert r["status"] == "ok" and not r["chosen"] and r["stats"]["tables"] == 1
    cmp_ = results.compare(pdf_doc)
    assert {x["tool"] for x in cmp_["results"]} == {"pymupdf", "pdfplumber"} and cmp_["pages"] == [1]
    assert cmp_["a"]["result_id"] != cmp_["b"]["result_id"]
    assert any(b["type"] == "table" and b["rows"] for b in cmp_["b"]["blocks"])
    assert cmp_["page_chars"][0][r["result_id"]] > 300

    old_chunks = {x["chunk_id"] for x in db.rows("SELECT chunk_id FROM chunk WHERE doc_id=?", (pdf_doc,))}
    rep = results.choose(pdf_doc, r["result_id"])
    assert rep["parser_tool"] == "pdfplumber" and rep["chunks"] > 0
    assert rep["manual_moved"] == 1 and [x["ann_id"] for x in rep["manual_lost"]] == [lost_id]
    assert rep["measurements_unlinked"] == 2 and rep["citations_unlinked"] == 1
    assert "측정값 2개" in rep["message"]
    new_chunks = {x["chunk_id"] for x in db.rows("SELECT chunk_id FROM chunk WHERE doc_id=?", (pdf_doc,))}
    assert not (old_chunks & new_chunks)
    moved = db.one("SELECT a.*, c.text FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id WHERE a.ann_id=?", (keep_id,))
    assert moved["text"][moved["span_start"]:moved["span_end"]] == "54.2 g/100 g" and moved["method"] == "human"
    meas = {m["meas_id"]: m["ann_id"] for m in db.rows("SELECT meas_id, ann_id FROM measurement WHERE meas_id LIKE 'm-%'")}
    assert meas == {"m-keep": keep_id, "m-lost": None, "m-auto": None}, "측정값은 남고 연결만 끊긴다"
    # 옮긴 라벨과 같은 자리의 사전 라벨은 중복으로 만들지 않는다
    dup = db.one("SELECT COUNT(*) AS n FROM annotation WHERE chunk_id=? AND span_start=? AND span_end=?",
                 (moved["chunk_id"], moved["span_start"], moved["span_end"]))["n"]
    assert dup == 1
    assert db.one("SELECT COUNT(*) AS n FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id WHERE c.doc_id=? AND a.method='dict'",
                  (pdf_doc,))["n"] == rep["annotations_dict"] > 0
    d = db.one("SELECT parse_status, parser_ver FROM document WHERE doc_id=?", (pdf_doc,))
    assert json.loads(d["parse_status"])["tool"] == "pdfplumber" and d["parser_ver"].startswith("pdfplumber/")
    rs = {x["tool"]: x["chosen"] for x in results.list_results(pdf_doc)}
    assert rs == {"pymupdf": False, "pdfplumber": True}
    assert db.one("SELECT chunk_id FROM report_citation WHERE cit_id='c1'")["chunk_id"] is None
    from pathlib import Path
    assert Path(rep["backup"]).exists()


def test_rerun_same_tool_replaces_unchosen_result(home, pdf_doc):
    from app.ingest.parser_tools import results
    before = [x for x in results.list_results(pdf_doc) if x["tool"] == "pymupdf"]
    results.parse_with(pdf_doc, "pymupdf")
    results.parse_with(pdf_doc, "pymupdf")
    after = [x for x in results.list_results(pdf_doc) if x["tool"] == "pymupdf"]
    assert len(after) == 1 and after[0]["result_id"] != before[0]["result_id"]


def test_failed_tool_leaves_error_result(home, pdf_doc, monkeypatch):
    from app.ingest.parser_tools import pymupdf_tool, results

    def boom(path, options):
        raise RuntimeError("깨진 PDF")
    monkeypatch.setattr(pymupdf_tool.TOOL, "parse_fn", boom)
    r = results.parse_with(pdf_doc, "pymupdf")
    assert r["status"] == "error" and "깨진 PDF" in r["error"]
    with pytest.raises(results.ToolError):
        results.choose(pdf_doc, r["result_id"])


def test_chunk_rules_hook_called_if_present(home, samples, tmp_path, monkeypatch):
    import sys
    import types

    from app.ingest import pipeline
    from app.ingest.parser_tools import results
    called = {}
    fake = types.ModuleType("app.chunk_rules")
    fake.apply = lambda doc_id, origin="manual": called.setdefault("apply", (doc_id, origin)) and {"total": 0}
    fake.chunker_params = lambda doc_id: {"target": 400}
    monkeypatch.setitem(sys.modules, "app.chunk_rules", fake)
    import app
    monkeypatch.setattr(app, "chunk_rules", fake, raising=False)
    f = _copy(samples, "txt", tmp_path, "규칙시험.txt")
    doc = pipeline.ingest_file(f, project="파서 시험", confidentiality="일반")["doc_id"]
    r = results.parse_with(doc, "text")
    rep = results.choose(doc, r["result_id"])
    assert called["apply"] == (doc, "reparse") and rep["rules"] is not None


def test_delete_document_removes_parsed_files(home, samples, tmp_path):
    from app.ingest import pipeline
    f = _copy(samples, "txt", tmp_path, "지울자료.txt")
    doc = pipeline.ingest_file(f, project="파서 시험")["doc_id"]
    assert (home / "parsed" / doc).is_dir()
    pipeline.delete_document(doc, remove_file=True)
    assert not (home / "parsed" / doc).exists()


# ---------------------------------------------------------------- 형식별 기본 도구

def test_defaults_persist_and_apply_to_ingest(home, samples, tmp_path, monkeypatch):
    from app.ingest import parser_tools as PT
    from app.ingest import pipeline
    assert PT.load_defaults()[".pdf"] == "pymupdf" and PT.load_defaults()[".hwp"] == "kordoc"
    with pytest.raises(PT.ToolError) as e:
        PT.save_defaults({".pdf": "upstage"})
    assert "클라우드" in str(e.value)
    with pytest.raises(PT.ToolError):
        PT.save_defaults({".pdf": "hwpx"})
    if _has_pdfplumber():
        assert PT.save_defaults({".pdf": "pdfplumber"})[".pdf"] == "pdfplumber"
        saved = json.loads(PT.defaults_file().read_text(encoding="utf-8"))
        assert saved == {"defaults": {".pdf": "pdfplumber"}}
        f = _copy(samples, "pdf", tmp_path, "기본도구시험.pdf")
        # 같은 파일(sha256)은 중복이라 1바이트 덧붙인다(PDF 끝 뒤 바이트는 읽기에 영향 없음)
        f.write_bytes(f.read_bytes() + b"\n")
        r = pipeline.ingest_file(f, project="파서 시험", confidentiality="일반")
        assert r["parser_tool"] == "pdfplumber" and r["status"]["parse"] == "done"

        # 기본 도구가 준비되지 않으면 기존 파서로 대신 읽고 메모를 남긴다
        monkeypatch.setattr(PT.get("pdfplumber"), "status_fn", lambda: {"ready": False, "message": "없음"})
        f2 = _copy(samples, "pdf", tmp_path, "대체시험.pdf")
        f2.write_bytes(f2.read_bytes() + b"\n\n")
        r2 = pipeline.ingest_file(f2, project="파서 시험", confidentiality="일반")
        assert r2["parser_tool"] == "pymupdf" and r2["chunks"] > 0
        from app import db
        assert "pdfplumber" in db.one("SELECT note FROM document WHERE doc_id=?", (r2["doc_id"],))["note"]
    PT.save_defaults({".pdf": "pymupdf"})
    assert json.loads(PT.defaults_file().read_text(encoding="utf-8")) == {"defaults": {}}


# ---------------------------------------------------------------- API

@pytest.fixture(scope="module")
def client(home):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import routes_parse
    a = FastAPI()
    a.include_router(routes_parse.router)
    return TestClient(a)


def _wait(client, job):
    for _ in range(200):
        if job["status"] != "running":
            return job
        time.sleep(0.05)
        job = client.get(f"/api/parse/jobs/{job['job_id']}").json()
    raise AssertionError("작업이 끝나지 않았습니다")


def test_api_flow(client, home, samples, tmp_path):
    from app.ingest import pipeline
    f = _copy(samples, "hwpx", tmp_path, "API시험.hwpx")
    doc = pipeline.ingest_file(f, project="파서 시험", confidentiality="내부")["doc_id"]

    t = client.get(f"/api/parse/tools?doc_id={doc}").json()
    by = {x["key"]: x for x in t["tools"]}
    assert by["hwpx"]["supports_doc"] and not by["pdfplumber"]["supports_doc"] and "notice" in t
    assert ".hwpx" in by["hwpx"]["default_for"]

    d = client.get("/api/parse/defaults").json()
    assert d["defaults"][".hwpx"] == "hwpx" and "upstage" not in d["choices"][".pdf"]
    assert client.post("/api/parse/defaults", json={"defaults": {".pdf": "upstage"}}).status_code == 400

    assert client.get(f"/api/parse/docs/{doc}").json()["tool"] == "hwpx"
    job = client.post(f"/api/parse/docs/{doc}/run", json={"tool": "hwpx", "options": {}}).json()
    job = _wait(client, job)
    assert job["status"] == "done" and job["result"]["tool"] == "hwpx"
    res = client.get(f"/api/parse/docs/{doc}/results").json()["results"]
    assert len(res) == 2 and sum(r["chosen"] for r in res) == 1   # 투입 때 결과(선택됨)는 다시 실행해도 남는다
    cmp_ = client.get(f"/api/parse/docs/{doc}/compare").json()
    assert cmp_["pages"] == [0] and cmp_["a"]["blocks"] and cmp_["b"]["blocks"]   # HWPX 기본은 쪽 정보 없음 → 0
    rid = next(r["result_id"] for r in res if not r["chosen"])
    rep = client.post(f"/api/parse/docs/{doc}/choose", json={"result_id": rid}).json()
    assert rep["chunks"] > 0 and rep["result"]["chosen"]

    # 클라우드: '내부'는 확인 없이 409, 형식 밖 도구는 400, 없는 자료는 404
    assert client.post(f"/api/parse/docs/{doc}/run", json={"tool": "upstage"}).status_code == 409
    assert client.post(f"/api/parse/docs/{doc}/run", json={"tool": "pdfplumber"}).status_code == 400
    assert client.post("/api/parse/docs/없음/run", json={"tool": "pymupdf"}).status_code == 404
    assert client.get("/api/parse/docs/없음/compare").status_code == 404
    assert client.get("/api/parse/jobs/없음").status_code == 404


def test_api_secret_document_403(client, home, samples, tmp_path, upstage_fake):
    from app.ingest import pipeline
    f = _copy(samples, "pdf", tmp_path, "API기밀.pdf")
    f.write_bytes(f.read_bytes() + b"\n\n\n")
    doc = pipeline.ingest_file(f, project="파서 시험", confidentiality="기밀")["doc_id"]
    r = client.post(f"/api/parse/docs/{doc}/run", json={"tool": "upstage", "confirm_cloud": True})
    assert r.status_code == 403 and "기밀" in r.json()["detail"]
    e = client.get(f"/api/parse/docs/{doc}/estimate?tool=upstage").json()
    assert e["blocked"] and "기밀" in e["message"]
    assert upstage_fake == []
