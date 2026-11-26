"""화면 개선(UX)에 딸린 API: 시작 화면의 '예시 자료 넣기'(/api/samples), 측정값의 근거 위치(doc_id·chunk_id),
라벨 검토의 '거절을 학습'(POST /api/annotations/{id}의 learn)."""
from __future__ import annotations

import os

import pytest

PROJ = "UX 시험"


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    from app import db, thesaurus
    prev = os.environ.get("BYORBIT_HOME")
    h = tmp_path_factory.mktemp("byorbit_home_ux")
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
def client(home):
    from fastapi.testclient import TestClient

    from app.server import app
    app.state.no_watch = True
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def samples(client):
    r = client.post("/api/samples", json={"project": PROJ})
    assert r.status_code == 200, r.text
    return r.json()


def test_samples_ingest_into_project(client, samples):
    res = samples["results"]
    assert len(samples["files"]) == 5 and len(res) == 5
    assert all(x.get("doc_id") for x in res), res
    docs = client.get("/api/documents", params={"project": PROJ}).json()
    assert len(docs) == 5
    assert {d["source_type"] for d in docs} >= {"paper", "coa"}


def test_samples_twice_is_duplicate(client, samples):
    r = client.post("/api/samples", json={"project": PROJ}).json()
    assert r["files"] == [] and len(r["skipped"]) == 5 and r["results"] == [], r
    assert len(client.get("/api/documents", params={"project": PROJ}).json()) == 5


def test_samples_rejects_bad_project_name(client):
    for bad in ("../밖", "a/b", "c:d"):
        r = client.post("/api/samples", json={"project": bad})
        assert r.status_code == 400, (bad, r.text)


def test_measurements_have_source_location(client, samples):
    from app import db
    rows = client.get("/api/measurements", params={"project": PROJ}).json()
    coa = [m for m in rows if m["entry"] == "coa"]
    assert coa and all(m["doc_id"] and m["file_name"] for m in coa)
    assert all("chunk_id" in m for m in rows)
    # 수치 라벨을 승인하면 측정값이 그 라벨의 청크를 가리킨다
    # (예시 자료의 사전 라벨에는 수치가 없으므로 AI가 제안한 것처럼 한 건 넣는다)
    ch = db.one("SELECT c.chunk_id, c.text FROM chunk c JOIN document d ON d.doc_id=c.doc_id "
                "WHERE d.file_name LIKE '예시논문%' ORDER BY c.ord LIMIT 1")
    a = {"ann_id": db.new_id(), "chunk_id": ch["chunk_id"]}
    with db.tx() as t:
        t.execute("INSERT INTO annotation(ann_id, chunk_id, span_start, span_end, surface_text, label_type, normalized_value, "
                  "confidence, method, status, engine) VALUES (?,?,0,4,?, 'VALUE', ?, 0.7, 'llm', 'pending', 'test')",
                  (a["ann_id"], a["chunk_id"], ch["text"][:4],
                   '{"target": "식이섬유", "value": "54.2", "unit": "g/100 g", "basis": "건물"}'))
    r = client.post(f"/api/annotations/{a['ann_id']}", json={"status": "accepted"}).json()
    assert r["measurement_id"]
    rows = client.get("/api/measurements", params={"project": PROJ}).json()
    m = next(x for x in rows if x["meas_id"] == r["measurement_id"])
    assert m["entry"] == "extracted" and m["chunk_id"] == a["chunk_id"] and m["doc_id"]
    client.post(f"/api/annotations/{a['ann_id']}", json={"status": "pending"})


def _dict_ann(exclude=()):
    from app import db
    q = "SELECT ann_id, surface_text FROM annotation WHERE method='dict' AND status IN ('pending','auto')"
    for row in db.rows(q):
        if row["ann_id"] not in exclude:
            return row
    pytest.skip("사전 라벨이 없음")


def test_reject_without_learn_learns_nothing(client, samples):
    from app import db
    a = _dict_ann()
    before = db.one("SELECT COUNT(*) AS n FROM label_example WHERE kind='negative'")["n"]
    r = client.post(f"/api/annotations/{a['ann_id']}", json={"status": "rejected"}).json()
    assert r["ok"] and "negative_example" not in r
    assert db.one("SELECT COUNT(*) AS n FROM label_example WHERE kind='negative'")["n"] == before
    client.post(f"/api/annotations/{a['ann_id']}", json={"status": "pending"})


def test_reject_with_learn_and_undo(client, samples):
    from app import db
    a = _dict_ann()
    r = client.post(f"/api/annotations/{a['ann_id']}", json={"status": "rejected", "learn": True}).json()
    assert r["ok"] and r.get("negative_example"), r
    ex = db.one("SELECT * FROM label_example WHERE kind='negative' AND ann_id=?", (a["ann_id"],))
    assert ex is not None
    u = client.post(f"/api/annotations/{a['ann_id']}", json={"status": "pending", "learn": True}).json()
    assert u["ok"] and u.get("negatives_disabled"), u
    assert db.one("SELECT status FROM annotation WHERE ann_id=?", (a["ann_id"],))["status"] == "pending"


def test_review_status_still_validated(client, samples):
    a = _dict_ann()
    assert client.post(f"/api/annotations/{a['ann_id']}", json={"status": "weird", "learn": True}).status_code == 400
