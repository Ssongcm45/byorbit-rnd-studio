"""2단계(M2) 핵심 시험: AI 라벨 일괄 실행(묶음·재시도·취소·이어하기), 검토 되돌리기, 실제 CoA 양식,
승인 측정값의 부산물 연결, 접근 방어(Host·Origin), 작업 목록 정리."""
from __future__ import annotations

import json
import os
import re
import time

import pytest

ID = re.compile(r"^[0-9a-f]{32}$")


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    from app import db, thesaurus
    prev = os.environ.get("BYORBIT_HOME")
    h = tmp_path_factory.mktemp("byorbit_home_m2")
    os.environ["BYORBIT_HOME"] = str(h)
    thesaurus.invalidate()
    db.init(seed=True)
    yield h
    if prev is None:
        os.environ.pop("BYORBIT_HOME", None)
    else:
        os.environ["BYORBIT_HOME"] = prev
    thesaurus.invalidate()


@pytest.fixture(scope="module")
def files(home, tmp_path_factory):
    from app.sample_files import make_samples
    return make_samples(tmp_path_factory.mktemp("samples_m2"))


@pytest.fixture(scope="module")
def loaded(files):
    from app.ingest import pipeline
    return {k: pipeline.ingest_file(p, project="M2 시험") for k, p in files.items()}


@pytest.fixture(scope="module")
def many(home, tmp_path_factory):
    """청크가 여러 개인 메모 자료(라벨 실행 시험용)."""
    from app import db
    from app.ingest import pipeline
    d = tmp_path_factory.mktemp("many")
    parts = []
    for i in range(8):
        parts.append(f"# {i + 1}. 사과박 건조 시험 {i + 1}\n\n" +
                     f"사과박 시료 {i + 1}번을 동결건조하여 총식이섬유를 측정하였다. " * 40)
    f = d / "여러청크_메모.md"
    f.write_text("\n\n".join(parts), encoding="utf-8")
    r = pipeline.ingest_file(f, project="M2 시험")
    ids = [x["chunk_id"] for x in db.rows("SELECT chunk_id FROM chunk WHERE doc_id=? ORDER BY ord", (r["doc_id"],))]
    assert len(ids) >= 7, len(ids)
    return {"doc_id": r["doc_id"], "chunks": ids}


class FakeEngine:
    """프롬프트의 chunk_id마다 tools.save_annotations를 직접 부른다.
    bad는 늘 실패, flaky는 처음 한 번만 실패(둘 다 엔진 오류 ok=False로 끝남).
    empty는 엔진은 정상 종료하지만 라벨할 것이 없는 청크."""
    __name__ = "fake_engine"

    def __init__(self, bad=(), flaky=(), on_call=None, empty=()):
        self.bad, self.flaky, self.on_call, self.empty = set(bad), set(flaky), on_call, set(empty)
        self.calls: list[list[str]] = []
        self.kw: list[dict] = []
        self.seen: set[str] = set()

    def run(self, prompt, **kw):
        from app import db, tools
        ids = [ln.strip() for ln in prompt.splitlines() if ID.match(ln.strip())]
        self.calls.append(ids)
        self.kw.append(kw)
        failed = False
        for cid in ids:
            if cid in self.bad or (cid in self.flaky and cid not in self.seen):
                self.seen.add(cid)
                failed = True
                continue
            if cid in self.empty:
                continue
            text = db.one("SELECT text FROM chunk WHERE chunk_id=?", (cid,))["text"]
            tools.save_annotations(cid, [{"surface": text[:6], "label_type": "OTHER", "confidence": 0.7}])
        if self.on_call:
            self.on_call(self, ids)
        if failed:
            return {"ok": False, "error": "도구 호출 실패", "session_id": f"s-{len(self.calls)}"}
        return {"ok": True, "result": "저장했습니다", "session_id": f"s-{len(self.calls)}", "duration_ms": 5}


def _use(monkeypatch, eng):
    from app import engines
    monkeypatch.setattr(engines, "get", lambda name=None: eng)


# ---------------------------------------------------------------- 라벨 실행

def test_label_batches_retry_and_resume(many, monkeypatch):
    from app import db, labeling
    ch = many["chunks"]
    eng = FakeEngine(bad={ch[1]}, flaky={ch[4]})
    _use(monkeypatch, eng)
    rid = labeling.start(many["doc_id"], batch_size=3, background=False)
    st = labeling.status(rid)
    n = len(ch)
    assert st["total"] == n and st["status"] == "error"
    assert st["ok"] == n - 1 and st["error"] == 1 and st["skipped"] == 0 and st["done"] == n
    assert st["pending_labels"] == n - 1           # 신뢰도 0.7 → 검토 대기
    assert eng.calls[0] == ch[:3]                  # 3개씩 묶음
    assert all(len(c) <= 3 for c in eng.calls)
    assert sum(1 for c in eng.calls if ch[1] in c) == 3   # 첫 시도 + 재시도 2번
    assert sum(1 for c in eng.calls if ch[4] in c) == 2   # 한 번 실패 후 재시도에서 성공
    assert all(k["role"] == "labeler" and k["write"] and k["task"] == "label" and k["run_id"] == rid for k in eng.kw)
    steps = {s["chunk_id"]: s for s in st["steps"]}
    assert steps[ch[1]]["status"] == "error" and steps[ch[1]]["output"]["attempts"] == 3
    assert steps[ch[4]]["output"] == {"saved": 1, "pending": 1, "attempts": 2}
    assert steps[ch[0]]["engine"] == "fake_engine" and steps[ch[0]]["session_id"]
    doc = json.loads(db.one("SELECT parse_status FROM document WHERE doc_id=?", (many["doc_id"],))["parse_status"])
    assert doc["label"] == "dict"                  # 실패가 남아 있으면 'AI 완료'로 표시하지 않는다

    # 이어하기: 오류 청크만 다시
    eng2 = FakeEngine()
    _use(monkeypatch, eng2)
    r = labeling.resume(rid, background=False)
    assert r["ok"] and r["remaining"] == 1
    assert eng2.calls == [[ch[1]]]
    st = labeling.status(rid)
    assert st["status"] == "done" and st["ok"] == n and st["error"] == 0
    doc = json.loads(db.one("SELECT parse_status FROM document WHERE doc_id=?", (many["doc_id"],))["parse_status"])
    assert doc["label"] == "llm"
    assert not labeling.resume(rid, background=False)["ok"]   # 남은 것 없음

    # 이미 AI 라벨이 있으면 건너뛰고, force면 다시 한다
    eng3 = FakeEngine()
    _use(monkeypatch, eng3)
    r2 = labeling.start(many["doc_id"], background=False)
    st2 = labeling.status(r2)
    assert st2["skipped"] == n and st2["status"] == "done" and eng3.calls == []
    r3 = labeling.start(many["doc_id"], max_chunks=4, batch_size=2, force=True, background=False)
    st3 = labeling.status(r3)
    assert st3["total"] == 4 and st3["ok"] == 4 and eng3.calls == [ch[:2], ch[2:4]]
    runs = labeling.list_runs(many["doc_id"])
    assert runs[0]["run_id"] == r3 and {r["run_id"] for r in runs} >= {rid, r2, r3}


def test_label_engine_exception_and_text_not_trusted(many, monkeypatch):
    """모델이 '저장했다'고 말해도 라벨이 실제로 없으면 실패, 예외도 실패로 기록한다."""
    from app import labeling

    class Liar:
        def run(self, prompt, **kw):
            return {"ok": True, "result": "10건 저장했습니다"}

    class Boom:
        def run(self, prompt, **kw):
            raise RuntimeError("연결 끊김")

    liar = Liar()
    liar.n = 0
    orig_run = Liar.run

    def counted(self, prompt, **kw):
        self.n += 1
        return orig_run(self, prompt, **kw)
    Liar.run = counted
    _use(monkeypatch, liar)
    rid = labeling.start(many["doc_id"], max_chunks=2, force=True, background=False)
    st = labeling.status(rid)
    # '저장했다'는 말은 믿지 않는다 → 성공(ok) 0. 엔진은 정상 종료했으므로 2번 확인 후 '건너뜀'(오류 아님)
    assert st["ok"] == 0 and st["skipped"] == 2 and st["error"] == 0 and liar.n == 2
    assert "찾지 못했습니다" in st["steps"][0]["output"]["reason"]
    _use(monkeypatch, Boom())
    rid = labeling.start(many["doc_id"], max_chunks=1, force=True, background=False)
    st = labeling.status(rid)
    assert st["error"] == 1 and "연결 끊김" in st["steps"][0]["output"]["error"]


def test_label_cancel_and_resume(many, monkeypatch):
    from app import labeling
    ch = many["chunks"]
    holder = {}

    def cancel_after_first(eng, ids):
        if len(eng.calls) == 1:
            holder["cancel"] = labeling.cancel(holder["rid"])

    eng = FakeEngine(on_call=cancel_after_first)
    _use(monkeypatch, eng)
    # start를 background=False로 부르면 run_id를 미리 알 수 없으므로 실행 레코드만 만들고 직접 돌린다
    orig = labeling._launch
    monkeypatch.setattr(labeling, "_launch", lambda run_id, background: holder.setdefault("rid", run_id))
    rid = labeling.start(many["doc_id"], batch_size=2, force=True)
    monkeypatch.setattr(labeling, "_launch", orig)
    assert labeling.execute(rid) == "cancelled"
    assert holder["cancel"]["status"] == "cancelling"
    st = labeling.status(rid)
    assert st["status"] == "cancelled" and st["ok"] == 2 and st["waiting"] == len(ch) - 2
    assert len(eng.calls) == 1
    assert not labeling.cancel(rid)["ok"]          # 이미 끝남
    r = labeling.resume(rid, background=False)
    assert r["remaining"] == len(ch) - 2
    st = labeling.status(rid)
    assert st["status"] == "done" and st["ok"] == len(ch)


def test_label_interrupted_on_restart(many, monkeypatch):
    from app import db, labeling
    from fastapi.testclient import TestClient

    from app.server import app
    _use(monkeypatch, FakeEngine())
    monkeypatch.setattr(labeling, "_launch", lambda run_id, background: None)  # 돌기 전에 앱이 꺼진 상황
    rid = labeling.start(many["doc_id"], max_chunks=2, force=True)
    assert db.one("SELECT status FROM run WHERE run_id=?", (rid,))["status"] == "running"
    app.state.no_watch = True
    with TestClient(app):                          # lifespan 시작 → 남은 실행을 '중단됨'으로
        pass
    assert labeling.status(rid)["status"] == "interrupted"


@pytest.fixture(scope="module")
def client(loaded):
    from fastapi.testclient import TestClient

    from app.server import app
    app.state.no_watch = True
    with TestClient(app) as c:
        yield c


def test_api_label_flow(client, many, monkeypatch):
    eng = FakeEngine(bad={many["chunks"][0]})
    _use(monkeypatch, eng)
    r = client.post("/api/label", json={"doc_id": many["doc_id"], "max_chunks": 3, "batch_size": 2, "force": True})
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]
    for _ in range(100):
        st = client.get(f"/api/label/runs/{rid}").json()
        if st["status"] not in ("running", "cancelling"):
            break
        time.sleep(0.05)
    assert st["status"] == "error" and st["total"] == 3 and st["ok"] == 2 and st["error"] == 1
    assert {"done", "skipped", "pending_labels", "steps"} <= set(st)
    runs = client.get("/api/label/runs", params={"doc_id": many["doc_id"]}).json()
    assert runs[0]["run_id"] == rid and runs[0]["error"] == 1
    assert client.post(f"/api/label/runs/{rid}/cancel").json()["ok"] is False
    eng.bad.clear()
    assert client.post(f"/api/label/runs/{rid}/resume").json()["remaining"] == 1
    for _ in range(100):
        st = client.get(f"/api/label/runs/{rid}").json()
        if st["status"] != "running":
            break
        time.sleep(0.05)
    assert st["status"] == "done"
    assert client.get("/api/label/runs/없는실행").status_code == 404
    assert client.post("/api/label/runs/없는실행/resume").status_code == 404
    bad = client.post("/api/label", json={"doc_id": "nope"})
    assert bad.status_code == 404 and "자료" in bad.json()["detail"]


# ---------------------------------------------------------------- 검토 되돌리기·부산물 연결

def _pending_value(doc_id: str, needle: str, value, target: str):
    from app import db, tools
    ch = db.one("SELECT chunk_id, text FROM chunk WHERE doc_id=? AND text LIKE ? ORDER BY ord",
                (doc_id, f"%{needle}%"))
    r = tools.save_annotations(ch["chunk_id"], [{"surface": needle, "label_type": "VALUE", "value": value,
                                                 "unit": "g/100 g", "target": target, "confidence": 0.95}])
    return r["saved"][0]["ann_id"]


def test_review_undo_and_byproduct(client, loaded):
    from app import db
    bp = db.one("SELECT b.byproduct_id FROM byproduct b JOIN concept k ON k.concept_id=b.concept_id "
                "WHERE k.pref_label_ko='사과박'")["byproduct_id"]
    # 논문: CoA 시료가 없으니 자료에 가장 많이 나온 부산물(사과박)로 연결
    ann = _pending_value(loaded["pdf"]["doc_id"], "54.2 g/100 g", 54.2, "식이섬유")
    r = client.post(f"/api/annotations/{ann}", json={"status": "accepted"}).json()
    m = db.one("SELECT * FROM measurement WHERE meas_id=?", (r["measurement_id"],))
    assert m["byproduct_id"] == bp and m["entry"] == "extracted"
    rows = client.get("/api/measurements", params={"byproduct": "사과박", "target": "식이섬유"}).json()
    assert any(x["entry"] == "extracted" for x in rows)
    # 되돌리기 → 검토 대기, 측정값 삭제
    u = client.post(f"/api/annotations/{ann}", json={"status": "pending"}).json()
    assert u["removed_measurements"] == 1 and u["measurement_id"] is None
    a = db.one("SELECT status, reviewed_at FROM annotation WHERE ann_id=?", (ann,))
    assert a["status"] == "pending" and a["reviewed_at"] is None
    assert not db.one("SELECT 1 AS x FROM measurement WHERE ann_id=?", (ann,))
    # 다시 승인해도 측정값은 한 건, 거절로 바꾸면 지워진다
    client.post(f"/api/annotations/{ann}", json={"status": "accepted"})
    client.post(f"/api/annotations/{ann}", json={"status": "accepted"})
    assert db.one("SELECT COUNT(*) AS n FROM measurement WHERE ann_id=?", (ann,))["n"] == 1
    client.post(f"/api/annotations/{ann}", json={"status": "rejected"})
    assert db.one("SELECT COUNT(*) AS n FROM measurement WHERE ann_id=?", (ann,))["n"] == 0
    assert client.post(f"/api/annotations/{ann}", json={"status": "weird"}).status_code == 400
    # CoA 자료의 라벨은 그 CoA 시료의 부산물로
    ann2 = _pending_value(loaded["coa_hot_air"]["doc_id"], "47.9", 47.9, "식이섬유")
    r2 = client.post(f"/api/annotations/{ann2}", json={"status": "accepted"}).json()
    assert db.one("SELECT byproduct_id FROM measurement WHERE meas_id=?", (r2["measurement_id"],))["byproduct_id"] == bp


def test_review_no_byproduct_is_null(client, home, tmp_path):
    from app import db
    from app.ingest import pipeline
    f = tmp_path / "부산물없음.txt"
    f.write_text("시료 X의 측정값은 12.5 g/100 g 이었다.", encoding="utf-8")
    d = pipeline.ingest_file(f, project="M2 시험")
    ann = _pending_value(d["doc_id"], "12.5 g/100 g", 12.5, "식이섬유")
    r = client.post(f"/api/annotations/{ann}", json={"status": "accepted"}).json()
    assert db.one("SELECT byproduct_id FROM measurement WHERE meas_id=?", (r["measurement_id"],))["byproduct_id"] is None


# ---------------------------------------------------------------- 실제 CoA 양식

def test_coa_value_parsing():
    from app.ingest import coa
    assert coa.parse_value("< 0.01") == (0.01, "< 0.01")
    assert coa.parse_value("0.05 미만") == (0.05, "0.05 미만")
    assert coa.parse_value("불검출") == (None, "불검출")
    assert coa.parse_value("N.D.") == (None, "ND")
    assert coa.parse_value("not detected") == (None, "ND")
    assert coa.parse_value("검출") == (None, "검출")
    assert coa.parse_value("Detected") == (None, "검출")
    assert coa.parse_value("1.2×10^3")[0] == 1200
    assert coa.parse_value("3.4E+02")[0] == 340
    assert coa.parse_value(52.6) == (52.6, "52.6")
    for raw, std in [("hot_air", "열풍건조"), ("freeze_dry", "동결건조"), ("자연(천일)", "자연건조"), ("sun_dry", "자연건조"),
                     ("spray_dry", "분무건조"), ("분무", "분무건조"), ("진공건조", "진공건조"), ("none", "없음"),
                     ("동결건조 후 분쇄", "동결건조"), ("모름", None)]:
        assert coa.drying_method(raw) == std, raw
    assert coa.pretreatment_text("동결건조", -50, 48) == "동결건조; -50 ℃; 48 h"
    assert coa.pretreatment_text("열풍건조", 60, None) == "열풍건조; 60 ℃"
    assert coa.pretreatment_text("열풍건조", 62.5, 12) == "열풍건조; 62.5 ℃; 12 h"
    assert coa.match_item("총식이섬유 TDF (g/100g)")[0] == "총식이섬유"
    assert coa.match_item("총식이섬유 TDF (g/100g)")[2] == "g/100g"
    assert coa.match_item("Moisture (fresh)")[0] == "수분(생시료)"
    assert coa.match_item("수분(건조 후)")[0] == "수분(건조 후)"
    assert coa.match_item("비소 (As)")[0] == "비소"
    assert coa.match_item("E. coli")[0] == "대장균"


def test_coa_template_hot_air(loaded):
    from app import db
    r = loaded["coa_hot_air"]
    assert r["source_type"] == "coa" and not r.get("error")
    s = db.one("SELECT s.*, k.pref_label_ko AS pre, bk.pref_label_ko AS bp FROM sample s "
               "LEFT JOIN concept k ON k.concept_id=s.pretreatment_concept_id "
               "LEFT JOIN byproduct b ON b.byproduct_id=s.byproduct_id LEFT JOIN concept bk ON bk.concept_id=b.concept_id "
               "WHERE s.coa_doc_id=?", (r["doc_id"],))
    assert s["pretreatment_text"] == "열풍건조; 60 ℃; 12 h" and s["pre"] == "열풍건조"
    assert s["bp"] == "사과박"                       # 부산물종 'apple_pomace' → 사과박
    assert s["lot_no"] == "AP-2611-07" and s["supplier"] == "△△식품" and s["sample_code"] == "R-2026-0533"
    assert s["collected_at"] == "2026-10"            # 접수일이 없으면 수확시기
    note = db.one("SELECT note FROM document WHERE doc_id=?", (r["doc_id"],))["note"]
    assert "품종 후지" in note and "산지 경북 영주" in note and "분석기관 예시분석연구원" in note
    m = {x["target_text"]: x for x in db.rows(
        "SELECT m.*, k.pref_label_ko AS concept FROM measurement m LEFT JOIN concept k ON k.concept_id=m.target_concept_id "
        "WHERE m.doc_id=? AND m.entry='coa'", (r["doc_id"],))}
    assert len(m) == r["measurements"] == 17
    assert all(x["byproduct_id"] == s["byproduct_id"] for x in m.values())
    assert m["총식이섬유"]["value"] == 47.9 and m["총식이섬유"]["concept"] == "식이섬유"
    assert m["총폴리페놀"]["value"] == 5.7 and m["총폴리페놀"]["unit_text"] == "mg GAE/g"
    assert m["수분(생시료)"]["value"] == 78.4 and m["수분(건조 후)"]["value"] == 7.9
    assert m["수분(생시료)"]["concept"] == m["수분(건조 후)"]["concept"] == "수분"
    assert m["카드뮴"]["value"] == 0.01 and m["카드뮴"]["value_text"] == "< 0.01" and m["카드뮴"]["concept"] == "카드뮴"
    assert m["비소"]["value"] is None and m["비소"]["value_text"] == "ND"
    assert m["대장균"]["value"] is None and m["대장균"]["value_text"] == "ND"
    assert m["살모넬라"]["value_text"] == "불검출"
    assert m["일반세균"]["value"] == 1200 and m["일반세균"]["unit_text"] == "CFU/g"
    assert m["조단백"]["concept"] == "단백질" and m["조지방"]["concept"] == "지방" and m["pH"]["concept"] == "pH"
    units = {x["unit_text"]: x["unit_concept_id"] for x in m.values()}
    assert units["ppm"] and units["CFU/g"] and units["mg/kg"]


def test_two_drying_methods_comparable(loaded):
    """같은 부산물(사과박)의 TDF가 동결건조·열풍건조 두 방법으로 비교된다."""
    from app import tools
    rows = tools.measurements_query("사과박", "식이섬유", apply_rule=False)["rows"]
    coa = {r["pretreatment"]: r["value"] for r in rows if r["entry"] == "coa"}
    assert coa == {"동결건조": 52.6, "열풍건조; 60 ℃; 12 h": 47.9}


def test_seed_new_concepts(home):
    from app import db, thesaurus
    for term, pref, scheme in [("천일건조", "자연건조", "공정"), ("spray drying", "분무건조", "공정"),
                               ("chlorogenic acid", "클로로겐산", "성분"), ("C3G", "시아니딘-3-글루코시드", "성분"),
                               ("구연산", "시트르산", "성분"), ("mg/kg", "ppm", "단위"), ("CFU/g", "CFU/g", "단위")]:
        h = [x for x in thesaurus.lookup(term) if x["exact"]]
        assert h and h[0]["pref_label"] == pref and h[0]["scheme"] == scheme, term
    contains = {r["k"] for r in db.rows(
        "SELECT t.pref_label_ko AS k FROM concept_relation r JOIN concept c ON c.concept_id=r.concept_id "
        "JOIN concept t ON t.concept_id=r.target_concept_id WHERE c.pref_label_ko='사과박' AND r.rel_type='contains'")}
    assert {"클로로겐산", "플로리진", "퀘르세틴"} <= contains
    assert len(db.table_names()) == 39


# ---------------------------------------------------------------- 접근 방어·작업 정리

def test_host_and_origin_guard(client):
    assert client.get("/api/health", headers={"host": "evil.example"}).status_code == 403
    r = client.get("/api/health", headers={"host": "attacker.com:8765"})
    assert r.status_code == 403 and "127.0.0.1" in r.json()["detail"]
    assert client.get("/api/health", headers={"host": "127.0.0.1:8765"}).status_code == 200
    assert client.get("/api/health", headers={"host": "localhost:8765"}).status_code == 200
    body = {"coa_rule": "mask"}
    local = {"host": "127.0.0.1:8765"}
    assert client.post("/api/settings", json=body, headers={**local, "origin": "http://127.0.0.1:8765"}).status_code == 200
    assert client.post("/api/settings", json=body, headers={**local, "origin": "http://localhost:8765"}).status_code == 200
    for bad in ("http://evil.example", "http://127.0.0.1:9999", "null", "https://127.0.0.1:8765"):
        r = client.post("/api/settings", json=body, headers={**local, "origin": bad})
        assert r.status_code == 403, bad
    r = client.post("/api/settings", json=body, headers={**local, "referer": "http://evil.example/page"})
    assert r.status_code == 403 and "다른 사이트" in r.json()["detail"]
    assert client.post("/api/settings", json=body,
                       headers={**local, "referer": "http://127.0.0.1:8765/#review"}).status_code == 200
    assert client.post("/api/settings", json=body, headers=local).status_code == 200   # CLI처럼 Origin 없음
    assert client.post("/api/settings", json=body).status_code == 200                  # TestClient 기본


def test_jobs_pruned():
    from app import server
    server.JOBS.clear()
    now = time.time()
    server.JOBS.update({
        "old": {"status": "done", "started": now - 7300, "finished": now - 7200},
        "olderr": {"status": "error", "started": now - 4000, "finished": now - 3700},
        "fresh": {"status": "done", "started": now - 20, "finished": now - 10},
        "run": {"status": "running", "started": now - 9999},
    })
    server._prune_jobs(now)
    assert set(server.JOBS) == {"fresh", "run"}
    server.JOBS.clear()
    for i in range(250):
        server.JOBS[f"j{i}"] = {"status": "done", "started": now - 100 + i, "finished": now - 100 + i}
    server.JOBS["live"] = {"status": "running", "started": now}
    server._prune_jobs(now)
    assert len(server.JOBS) == 200 and "live" in server.JOBS and "j249" in server.JOBS and "j0" not in server.JOBS
    server.JOBS.clear()
    j = server._job("t", lambda: 1)
    for _ in range(100):
        if server.JOBS[j["job_id"]]["status"] != "running":
            break
        time.sleep(0.01)
    assert server.JOBS[j["job_id"]]["result"] == 1


def test_seed_upgrade_existing_db(tmp_path, monkeypatch):
    """예전 시드로 만든 DB도 시드 버전이 오르면 빠진 개념만 더해진다(중복 없음, 사용자 확장 보존)."""
    from app import db, thesaurus
    monkeypatch.setenv("BYORBIT_HOME", str(tmp_path / "old_home"))
    thesaurus.invalidate()
    db.init(seed=True)
    n0 = db.one("SELECT COUNT(*) AS n FROM concept")["n"]
    # 예전 DB 흉내: 새 개념 하나를 지우고 버전을 낮춘다. 사용자 확장 하나를 둔다.
    cid = db.one("SELECT concept_id FROM concept WHERE pref_label_ko='분무건조'")["concept_id"]
    with db.tx() as c:
        c.execute("DELETE FROM concept_label WHERE concept_id=?", (cid,))
        c.execute("DELETE FROM concept WHERE concept_id=?", (cid,))
        c.execute("UPDATE concept_scheme SET version='seed-1'")
    from app import tools
    mine = tools.propose_concept("내 시험 개념", "성분")["concept_id"]
    r = db.init(seed=True)
    assert r["seeded_concepts"] == 1
    assert db.one("SELECT COUNT(*) AS n FROM concept WHERE pref_label_ko='분무건조'")["n"] == 1
    assert db.one("SELECT COUNT(*) AS n FROM concept")["n"] == n0 + 1  # 분무건조 복구 + 내 개념
    assert db.one("SELECT 1 AS x FROM concept WHERE concept_id=?", (mine,))
    assert db.init(seed=True)["seeded_concepts"] == 0  # 다시 실행해도 그대로
    thesaurus.invalidate()


def test_label_empty_chunk_skipped_after_two_checks(many, monkeypatch):
    """라벨할 것이 없는 청크는 3번이 아니라 2번만 확인하고 건너뛴다(재호출 비용 절약)."""
    from app import labeling
    ch = many["chunks"]
    eng = FakeEngine(empty={ch[0]})
    _use(monkeypatch, eng)
    rid = labeling.start(many["doc_id"], max_chunks=3, batch_size=3, force=True, background=False)
    st = labeling.status(rid)
    assert st["status"] == "done" and st["ok"] == 2 and st["skipped"] == 1 and st["error"] == 0
    assert sum(1 for c in eng.calls if ch[0] in c) == 2
