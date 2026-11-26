"""1단계(M1) 시험: DB·시드·파이프라인·검색·MCP 도구·MCP stdio 연결·Claude Code 실행기·웹 API."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def home(tmp_path_factory):
    h = tmp_path_factory.mktemp("byorbit_home")
    os.environ["BYORBIT_HOME"] = str(h)
    from app import db, thesaurus
    thesaurus.invalidate()
    db.init(seed=True)
    return h


@pytest.fixture(scope="session")
def samples(home, tmp_path_factory):
    from app.sample_files import make_all
    return make_all(tmp_path_factory.mktemp("samples"))


@pytest.fixture(scope="session")
def loaded(samples):
    from app.ingest import pipeline
    out = {}
    for k, p in samples.items():
        out[k] = pipeline.ingest_file(p, project="사과박 식이섬유")
    return out


# ---------------------------------------------------------------- DB·시드

def test_thirty_tables(home):
    from app import db
    names = db.table_names()
    assert len(names) == 39  # M1 30 + 수집 3 + 실험 3 + 작업대 3
    for t in ("concept", "chunk", "annotation", "measurement", "project", "project_item", "change_log", "usage_log"):
        assert t in names


def test_init_is_idempotent(home):
    from app import db
    before = db.one("SELECT COUNT(*) AS n FROM concept")["n"]
    r = db.init(seed=True)
    assert r["seeded_concepts"] == 0
    assert db.one("SELECT COUNT(*) AS n FROM concept")["n"] == before
    assert (home / "ontology" / "seed.ttl").stat().st_size > 1000
    assert (home / "agents" / "labeler.md").exists()


def test_seed_taxonomy(home):
    from app import db
    n = db.one("SELECT COUNT(*) AS n FROM byproduct")["n"]
    assert n >= 30
    sectors = {r["sector"] for r in db.rows("SELECT DISTINCT sector FROM byproduct")}
    assert {"농업", "임업", "수산"} <= sectors


def test_thesaurus(home):
    from app import thesaurus
    hit = thesaurus.lookup("사과 포마스")[0]
    assert hit["pref_label"] == "사과박" and hit["exact"]
    assert "총식이섬유" in thesaurus.expand("TDF")
    found = [m["surface"] for m in thesaurus.find_mentions("동결건조(FD)한 사과박의 TPC를 측정. FDA 아님")]
    assert found == ["동결건조", "FD", "사과박", "TPC"]


# ---------------------------------------------------------------- 파이프라인

def test_ingest_all_formats(loaded):
    for k, r in loaded.items():
        assert not r.get("error"), (k, r)
        assert r["status"]["load"] == "done"
        assert r["chunks"] >= 1
    assert loaded["pdf"]["source_type"] == "paper"
    assert loaded["hwpx"]["source_type"] == "report"
    assert loaded["coa"]["source_type"] == "coa"
    assert loaded["pdf"]["annotations"] > 10


def test_pdf_table_extracted(loaded):
    from app import db
    t = db.rows("SELECT cells_json FROM doc_table WHERE doc_id=?", (loaded["pdf"]["doc_id"],))
    assert t, "PDF 표를 찾지 못함"
    rows = json.loads(t[0]["cells_json"])
    assert rows[1][0] == "동결건조" and rows[1][1] == "54.2"


def test_hwpx_table_and_text(loaded):
    from app import db
    texts = " ".join(r["text"] for r in db.rows("SELECT text FROM chunk WHERE doc_id=?", (loaded["hwpx"]["doc_id"],)))
    assert "사과 포마스" in texts and "비건가죽" in texts


def test_coa_measurements(loaded):
    from app import db
    assert loaded["coa"]["measurements"] == 5
    m = {r["target_text"]: r for r in db.rows("SELECT * FROM measurement WHERE doc_id=?", (loaded["coa"]["doc_id"],))}
    assert m["총식이섬유"]["value"] == 52.6 and m["총식이섬유"]["unit_text"] == "g/100 g"
    assert m["납"]["value"] is None and m["납"]["value_text"] == "불검출"
    assert m["총식이섬유"]["byproduct_id"] is not None  # 시료명 '사과박' → 부산물 연결
    s = db.one("SELECT * FROM sample WHERE coa_doc_id=?", (loaded["coa"]["doc_id"],))
    assert s["lot_no"] == "AP-2610-03" and s["supplier"] == "○○농산" and s["confidentiality"] == "기밀"


def test_duplicate_rejected(samples, loaded):
    from app.ingest import pipeline
    with pytest.raises(pipeline.Duplicate):
        pipeline.ingest_file(samples["pdf"], project="다른 프로젝트")


def test_unsupported_hwp(home, tmp_path):
    from app.ingest import parsers, pipeline
    f = tmp_path / "옛문서.hwp"
    f.write_bytes(b"\xd0\xcf\x11\xe0dummy")
    r = pipeline.ingest_file(f)
    assert r["status"]["parse"] == "error" and "HWPX" in r["error"]


# ---------------------------------------------------------------- 검색

def test_search_synonym_expansion(loaded):
    from app import search
    r = search.search("사과 포마스 TDF", project="사과박 식이섬유")
    assert r["results"], r
    assert any("총식이섬유" in g for g in r["expanded"])
    files = {h["file_name"] for h in r["results"]}
    assert any("논문" in f for f in files)


def test_search_short_korean(loaded):
    from app import search
    r = search.search("수분")  # 2글자 — LIKE 경로
    assert r["results"]


def test_search_project_filter(loaded):
    from app import search
    assert not search.search("사과박", project="없는 프로젝트")["results"]


# ---------------------------------------------------------------- MCP 도구

def test_tool_mask_confidential(loaded):
    from app import config, tools
    config.save_settings({"coa_rule": "mask"})
    coa_chunk = tools.search_chunks("의뢰처 사과박")["results"]
    coa = [h for h in coa_chunk if h["confidentiality"] == "기밀"]
    assert coa
    full = tools.get_chunk(coa[0]["chunk_id"])["text"]
    assert "AP-2610-03" not in full and "○○농산" not in full and "R-2026-0417" not in full
    assert "[가림]" in full and "52.6" in full


def test_tool_mask_confidential_file_name(loaded, tmp_path):
    """기밀 자료는 파일명·제목도 AI에 넘기지 않는다(공급처가 파일명에 들어간 경우)."""
    from app import config, tools
    from app.ingest import pipeline
    config.save_settings({"coa_rule": "mask"})
    p = tmp_path / "○○농산_AP-2610-03_메모.txt"
    p.write_text("○○농산 납품분 동결건조 메모. 로트 AP-2610-03 수분 함량 재측정 필요.", encoding="utf-8")
    r = pipeline.ingest_file(p, project="사과박 식이섬유", confidentiality="기밀")
    try:
        hits = [h for h in tools.search_chunks("재측정")["results"] if h["doc_id"] == r["doc_id"]]
        assert hits
        h = hits[0]
        assert "○○농산" not in json.dumps(h, ensure_ascii=False)
        assert h["file_name"].startswith("기밀자료-") and h["file_name"].endswith(".txt")
        c = tools.get_chunk(h["chunk_id"])
        dumped = json.dumps(c, ensure_ascii=False)
        # 이 문서는 CoA가 아니지만 다른 CoA에 등록된 공급처·로트번호를 언급하므로 가린다
        assert "○○농산" not in dumped and "AP-2610-03" not in dumped and "[가림]" in c["text"]
    finally:
        pipeline.delete_document(r["doc_id"], remove_file=True)


def test_tool_block_confidential(loaded):
    from app import config, tools
    config.save_settings({"coa_rule": "block"})
    try:
        r = tools.search_chunks("의뢰처 사과박")
        assert all(h["confidentiality"] != "기밀" for h in r["results"])
        m = tools.query_measurements("사과박")
        assert m["withheld"] == 5 and m["count"] == 0
    finally:
        config.save_settings({"coa_rule": "mask"})


def test_tool_measurements_hide_ids(loaded):
    from app import tools
    m = tools.query_measurements("사과 포마스", "식이섬유")
    assert m["count"] == 1
    row = m["rows"][0]
    assert row["value"] == 52.6 and row["sample"] == "시료 1"
    assert "lot_no" not in row and "supplier" not in row and "_sample_id" not in row


def test_tool_save_annotations(loaded):
    from app import db, tools
    ch = db.one("SELECT chunk_id, text FROM chunk WHERE doc_id=? AND text LIKE '%54.2 g/100 g%' AND chunk_type='text'",
                (loaded["pdf"]["doc_id"],))
    r = tools.save_annotations(ch["chunk_id"], [
        {"surface": "54.2 g/100 g", "label_type": "VALUE", "value": 54.2, "unit": "g/100 g", "target": "식이섬유",
         "basis": "건량", "confidence": 0.97},
        {"surface": "열풍건조", "label_type": "PROCESS", "concept": "열풍건조", "confidence": 0.95},
        {"surface": "없는 문구", "label_type": "VALUE", "confidence": 0.9},
        {"surface": "사과박", "label_type": "BYPRODUCT", "confidence": 0.3},
    ])
    st = {s["index"]: s["status"] for s in r["saved"]}
    assert st[0] == "pending"           # 수치는 신뢰도와 관계없이 검토 대기
    assert st[1] == "auto"
    assert {x["index"] for x in r["rejected"]} == {2, 3}
    ann = db.one("SELECT normalized_value FROM annotation WHERE ann_id=?", (r["saved"][0]["ann_id"],))
    assert json.loads(ann["normalized_value"])["value"] == 54.2


def test_tool_report_requires_citations(loaded):
    from app import db, tools
    ch = db.one("SELECT chunk_id FROM chunk WHERE doc_id=? AND text LIKE '%54.2%' LIMIT 1", (loaded["pdf"]["doc_id"],))
    bad = tools.save_report_draft("검증 시험", "동결건조 사과박의 식이섬유는 54.2 g/100 g이다.", [])
    assert not bad["ok"] and bad["uncited_numeric_sentences"]
    good = tools.save_report_draft("검증 시험 2", "동결건조 사과박의 식이섬유는 54.2 g/100 g이다 [1].",
                                   [{"claim": "TDF 54.2", "chunk_id": ch["chunk_id"]}])
    assert good["ok"], good
    assert Path(good["file"]).exists()


def test_tool_propose_concept(home):
    from app import thesaurus, tools
    r = tools.propose_concept("사과 씨", "부산물", ["apple seed"])
    assert r["status"] == "proposed"
    assert not [h for h in thesaurus.lookup("apple seed") if h["exact"]]  # 승인 전에는 쓰이지 않음
    assert "exists" in tools.propose_concept("사과 포마스", "부산물")


# ---------------------------------------------------------------- MCP stdio (실제 서버 프로세스)

def test_mcp_stdio_roundtrip(loaded, home):
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_server"],
                                   env={**os.environ, "PYTHONPATH": str(ROOT), "BYORBIT_HOME": str(home)},
                                   cwd=str(ROOT))

    async def go():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                res = await s.call_tool("lookup_concept", {"term": "사과 포마스"})
                text = "".join(getattr(c, "text", "") for c in res.content)
                res2 = await s.call_tool("search_chunks", {"query": "동결건조 식이섬유", "limit": 3})
                text2 = "".join(getattr(c, "text", "") for c in res2.content)
                return names, text, text2

    names, text, text2 = anyio.run(go)
    assert names == {"search_chunks", "get_chunk", "lookup_concept", "query_measurements", "save_annotations",
                     "save_report_draft", "propose_concept"}
    assert "사과박" in text
    assert "chunk_id" in text2


# ---------------------------------------------------------------- Claude Code 실행기 (가짜 CLI)

class FakeProc:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def test_claude_command_and_parse(home, monkeypatch):
    from app.engines import claude_code
    monkeypatch.setattr(claude_code, "executable", lambda: "claude")
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"], seen["input"], seen["cwd"] = cmd, kw["input"], kw["cwd"]
        return FakeProc(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "사과박",
                                    "session_id": "s-1", "duration_ms": 1234, "num_turns": 2}))

    r = claude_code.run("질문입니다", role="librarian", runner=runner)
    assert r["ok"] and r["result"] == "사과박" and r["session_id"] == "s-1"
    cmd = seen["cmd"]
    assert cmd[:4] == ["claude", "-p", "--output-format", "json"]
    assert "--strict-mcp-config" in cmd and "--append-system-prompt-file" in cmd
    allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
    assert "mcp__byorbit-rd__save_annotations" in allowed and all(a.startswith("mcp__byorbit-rd__") for a in allowed)
    assert cmd[cmd.index("--tools") + 1] == ""   # 내장 도구 전부 제거 — 파일 직접 읽기 불가
    blocked = cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert {"Bash", "Read", "Glob", "Grep", "Agent", "Task", "WebFetch"} <= set(blocked)
    assert seen["input"] == "질문입니다"           # 프롬프트는 표준입력으로
    cfg = json.loads(Path(cmd[cmd.index("--mcp-config") + 1]).read_text(encoding="utf-8"))
    srv = cfg["mcpServers"]["byorbit-rd"]
    assert srv["args"] == ["-m", "app.mcp_server"] and srv["env"]["BYORBIT_HOME"] == str(home)


def test_claude_fallback_old_cli(home, monkeypatch):
    from app.engines import claude_code
    monkeypatch.setattr(claude_code, "executable", lambda: "claude")
    calls = []

    def runner(cmd, **kw):
        calls.append((cmd, kw["input"]))
        if "--append-system-prompt-file" in cmd:
            return FakeProc("", 1, "error: unknown option '--append-system-prompt-file'")
        return FakeProc(json.dumps({"type": "result", "is_error": False, "result": "ok", "session_id": "s"}))

    r = claude_code.run("Q", role="labeler", runner=runner)
    assert r["ok"] and len(calls) == 2
    assert "라벨러" in calls[1][1] and calls[1][1].endswith("Q")


def test_claude_fallback_no_tools_flag(home, monkeypatch):
    """--tools를 모르는 CLI면 그 옵션만 빼고 다시 부른다. 그래도 Read 등은 차단 목록으로 막힌다."""
    from app.engines import claude_code
    monkeypatch.setattr(claude_code, "executable", lambda: "claude")
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        if "--tools" in cmd:
            return FakeProc("", 1, "error: unknown option '--tools'")
        if "--append-system-prompt-file" in cmd:
            return FakeProc("", 1, "error: unknown option '--append-system-prompt-file'")
        return FakeProc(json.dumps({"type": "result", "is_error": False, "result": "ok", "session_id": "s"}))

    r = claude_code.run("Q", role="labeler", runner=runner)
    assert r["ok"] and len(calls) == 3
    last = calls[-1]
    assert "--tools" not in last and "Read" in last[last.index("--disallowedTools") + 1].split(",")


def test_claude_check_smoke(home, monkeypatch):
    from app.engines import claude_code
    monkeypatch.setattr(claude_code, "executable", lambda: "claude")
    monkeypatch.setattr(claude_code, "version", lambda: {"installed": True, "path": "claude", "version": "2.x"})
    ok = claude_code.check(runner=lambda cmd, **kw: FakeProc(json.dumps({"type": "result", "result": "사과박"})))
    assert ok["ok"] and ok["smoke"]["passed"]
    bad = claude_code.check(runner=lambda cmd, **kw: FakeProc("", 1, "Invalid API key · Please run /login"))
    assert not bad["ok"] and "로그인" in bad["hint"]


def test_parse_output_variants():
    from app.engines.claude_code import parse_output
    assert parse_output('[{"type":"system"},{"type":"result","result":"x"}]')["result"] == "x"
    assert parse_output('warning: foo\n{"type":"result","result":"y"}')["result"] == "y"
    assert parse_output("") is None


# ---------------------------------------------------------------- 웹 API

@pytest.fixture(scope="module")
def client(loaded):
    from fastapi.testclient import TestClient

    from app.server import app
    app.state.no_watch = True
    with TestClient(app) as c:
        yield c


def test_api_basics(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["counts"]["document"] >= 4
    assert client.get("/").status_code == 200
    docs = client.get("/api/documents", params={"project": "사과박 식이섬유"}).json()
    assert len(docs) >= 4 and all("parse_status" in d for d in docs)
    s = client.get("/api/search", params={"q": "굴 패각 소성"}).json()
    assert s["results"]
    tree = client.get("/api/concepts/tree").json()
    assert [n["label"] for n in tree][:3] == ["농업", "임업", "수산"]
    assert len(client.get("/api/schema").json()) == 39


def test_api_upload_and_delete(client, tmp_path):
    f = tmp_path / "메모.txt"
    f.write_text("미강(쌀겨)은 단백질과 식이섬유가 많다.", encoding="utf-8")
    with open(f, "rb") as fh:
        r = client.post("/api/upload", files=[("files", ("메모.txt", fh, "text/plain"))],
                        data={"project": "감귤·커피박 탐색", "confidentiality": "일반"}).json()
    res = r["results"][0]
    assert res["chunks"] == 1, res
    assert any(p["name"] == "감귤·커피박 탐색" for p in client.get("/api/projects").json())
    assert client.delete(f"/api/documents/{res['doc_id']}").json()["ok"]


def test_api_review_promotes_measurement(client):
    pend = client.get("/api/annotations", params={"status": "pending"}).json()
    val = [a for a in pend if a["label_type"] == "VALUE"]
    assert val
    r = client.post(f"/api/annotations/{val[0]['ann_id']}", json={"status": "accepted"}).json()
    assert r["measurement_id"]
    rows = client.get("/api/measurements", params={"byproduct": "", "target": "식이섬유"}).json()
    entries = {x["entry"] for x in rows}
    assert {"coa", "extracted"} <= entries
    coa = [x for x in rows if x["entry"] == "coa"][0]
    assert coa["lot_no"] == "AP-2610-03"  # 내 PC 화면에서는 보인다


def test_api_concept_add_and_settings(client):
    r = client.post("/api/concepts", json={"label": "배 과피", "scheme": "부산물", "alt_labels": ["pear peel"]}).json()
    assert r["status"] == "active"
    assert client.get("/api/lookup", params={"term": "pear peel"}).json()["matches"][0]["pref_label"] == "배 과피"
    assert client.post("/api/settings", json={"coa_rule": "nope"}).status_code == 400
    assert client.post("/api/settings", json={"coa_rule": "block"}).json()["coa_rule"] == "block"
    client.post("/api/settings", json={"coa_rule": "mask"})


def test_cli_init_and_search(home):
    env = {**os.environ, "PYTHONPATH": str(ROOT), "BYORBIT_HOME": str(home), "PYTHONUTF8": "1"}
    p = subprocess.run([sys.executable, "-m", "app.cli", "search", "사과 착즙박"], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 0 and "검색어 확장" in p.stdout


# ---------------------------------------------------------------- 식품 영양 DB (ByOrbit Food MCP)

FOOD_TOOL_PREFIX = "mcp__byorbit-food__"


@pytest.fixture
def food_dir(home, tmp_path, monkeypatch):
    """가짜 Food MCP 폴더. 끝나면 설정을 늘 되돌린다(데이터 폴더를 세션 내내 같이 쓴다)."""
    from app import config
    from app.engines import food_mcp
    d = tmp_path / "food-agent"
    (d / "mcp").mkdir(parents=True)
    (d / "mcp" / "food-db-server.mjs").write_text("// dummy\n", encoding="utf-8")
    monkeypatch.setattr(food_mcp, "node_executable", lambda: "node")
    try:
        yield d
    finally:
        config.save_settings({"food_mcp": False, "food_mcp_dir": ""})


def _capture_runner(seen):
    def runner(cmd, **kw):
        seen["cmd"] = cmd
        if "--append-system-prompt-file" in cmd:
            seen["role"] = Path(cmd[cmd.index("--append-system-prompt-file") + 1]).read_text(encoding="utf-8")
        return FakeProc(json.dumps({"type": "result", "is_error": False, "result": "ok", "session_id": "s"}))
    return runner


def _mcp_cfg(cmd):
    return json.loads(Path(cmd[cmd.index("--mcp-config") + 1]).read_text(encoding="utf-8"))


def test_food_off_by_default(home, monkeypatch):
    from app import config
    from app.engines import claude_code, food_mcp
    monkeypatch.setattr(claude_code, "executable", lambda: "claude")
    config.save_settings({"food_mcp": False, "food_mcp_dir": ""})
    seen = {}
    assert claude_code.run("Q", role="librarian", runner=_capture_runner(seen))["ok"]
    cmd = seen["cmd"]
    assert list(_mcp_cfg(cmd)["mcpServers"]) == ["byorbit-rd"]
    assert not any(a.startswith(FOOD_TOOL_PREFIX) for a in cmd[cmd.index("--allowedTools") + 1].split(","))
    # 꺼져 있어도 파일·URL을 읽는 도구는 차단 목록에 있다
    assert FOOD_TOOL_PREFIX + "extract_label_table" in cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert food_mcp.GUIDE not in seen["role"]


def test_food_active_command(food_dir, monkeypatch):
    from app import config
    from app.engines import claude_code, food_mcp
    monkeypatch.setattr(claude_code, "executable", lambda: "claude")
    config.save_settings({"food_mcp": True, "food_mcp_dir": str(food_dir)})
    st = food_mcp.status()
    assert st["active"] and st["script_exists"] and not st["env_local_exists"]
    seen = {}
    assert claude_code.run("Q", role="librarian", runner=_capture_runner(seen))["ok"]
    cmd = seen["cmd"]
    food = _mcp_cfg(cmd)["mcpServers"]["byorbit-food"]
    assert food["command"] == "node"
    assert food["args"] == [str((food_dir / "mcp" / "food-db-server.mjs").resolve())]
    assert food["env"] == {}  # 시크릿은 넣지 않는다
    allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
    assert {FOOD_TOOL_PREFIX + n for n in food_mcp.TOOLS} <= set(allowed)
    assert len([a for a in allowed if a.startswith(FOOD_TOOL_PREFIX)]) == 12
    assert FOOD_TOOL_PREFIX + "extract_label_table" not in allowed
    blocked = cmd[cmd.index("--disallowedTools") + 1].split(",")
    assert FOOD_TOOL_PREFIX + "extract_label_table" in blocked
    assert {"Bash", "Read", "Glob", "Grep", "Agent", "Task", "WebFetch"} <= set(blocked)
    assert cmd[cmd.index("--tools") + 1] == ""
    assert food_mcp.GUIDE in seen["role"]

    # 스모크 점검(role 없음)에는 지침 파일이 붙지 않는다
    seen2 = {}
    claude_code.run("Q", role=None, runner=_capture_runner(seen2))
    assert "--append-system-prompt-file" not in seen2["cmd"]

    # 끄면 다음 실행부터 바로 빠진다(mcp.json을 매번 새로 쓴다)
    config.save_settings({"food_mcp": False})
    seen3 = {}
    claude_code.run("Q", role="librarian", runner=_capture_runner(seen3))
    assert "byorbit-food" not in _mcp_cfg(seen3["cmd"])["mcpServers"]
    assert food_mcp.GUIDE not in seen3["role"]


def test_food_guide_in_old_cli_fallback(food_dir, monkeypatch):
    from app import config
    from app.engines import claude_code, food_mcp
    monkeypatch.setattr(claude_code, "executable", lambda: "claude")
    config.save_settings({"food_mcp": True, "food_mcp_dir": str(food_dir)})
    inputs = []

    def runner(cmd, **kw):
        inputs.append(kw["input"])
        if "--append-system-prompt-file" in cmd:
            return FakeProc("", 1, "error: unknown option '--append-system-prompt-file'")
        return FakeProc(json.dumps({"type": "result", "is_error": False, "result": "ok", "session_id": "s"}))

    assert claude_code.run("Q", role="librarian", runner=runner)["ok"]
    assert food_mcp.GUIDE in inputs[-1] and inputs[-1].endswith("Q")


FAKE_FOOD_SERVER = r"""
import { createInterface } from 'node:readline'
const send = m => process.stdout.write(JSON.stringify(m) + '\n')
createInterface({ input: process.stdin }).on('line', line => {
  const { id, method } = JSON.parse(line)
  if (method === 'initialize') send({ jsonrpc: '2.0', id, result: { protocolVersion: '2025-06-18', capabilities: { tools: {} }, serverInfo: { name: 'fake', version: '0' } } })
  else if (method === 'tools/list') send({ jsonrpc: '2.0', id, result: { tools: ['search_food', 'get_food', 'verify_nutrition', 'extract_label_table'].map(name => ({ name })) } })
})
"""

FAKE_FOOD_SERVER_NO_DB = (
    "process.stderr.write('[food-db] DATABASE_URL 미설정 — 서버를 시작할 수 없습니다.\\n')\n"
    "process.exit(1)\n")


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_food_check_fake_server(food_dir, monkeypatch):
    from app import config
    from app.engines import food_mcp
    monkeypatch.setattr(food_mcp, "node_executable", lambda: shutil.which("node"))
    (food_dir / "mcp" / "food-db-server.mjs").write_text(FAKE_FOOD_SERVER, encoding="utf-8")
    config.save_settings({"food_mcp_dir": str(food_dir)})
    r = food_mcp.check(timeout=20)
    assert r["ok"], r
    assert {"search_food", "get_food", "verify_nutrition"} <= set(r["tools"])
    assert "compare_foods" in r["missing"] and "search_food" not in r["missing"]
    assert r["blocked"] == ["extract_label_table"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_food_check_server_exits(food_dir, monkeypatch):
    from app import config
    from app.engines import food_mcp
    monkeypatch.setattr(food_mcp, "node_executable", lambda: shutil.which("node"))
    (food_dir / "mcp" / "food-db-server.mjs").write_text(FAKE_FOOD_SERVER_NO_DB, encoding="utf-8")
    config.save_settings({"food_mcp_dir": str(food_dir)})
    r = food_mcp.check(timeout=20)
    assert not r["ok"] and "DATABASE_URL" in r["error"], r


def test_food_check_not_ready(home, monkeypatch):
    from app.engines import food_mcp
    monkeypatch.setattr(food_mcp, "resolve_dir", lambda: None)

    def boom(*a, **k):
        raise AssertionError("준비되지 않았으면 띄우지 않는다")

    r = food_mcp.check(popen=boom)
    assert not r["ok"] and "BYORBIT_FOOD_MCP_DIR" in r["error"]


def test_api_food_settings(client, tmp_path):
    r = client.post("/api/settings", json={"food_mcp_dir": str(tmp_path / "없는폴더")})
    assert r.status_code == 400 and "food-db-server.mjs" in r.json()["detail"]
    e = client.get("/api/engines/check").json()
    assert {"enabled", "ready", "active", "message"} <= set(e["food"])
    assert "food" in e["claude"]
