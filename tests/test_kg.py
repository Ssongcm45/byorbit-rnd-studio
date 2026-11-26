"""지식그래프(/api/kg): 동의어 찾기, 사과박 주변의 시드 관계, 깊이·점 상한, 자료 언급 선(예시 자료 투입 후),
측정값 집계 선, 개념 자세히(표기 종류·IRI·관계·자료·측정 요약 — 로트·공급처 없음), TTL·JSON 내보내기, API."""
from __future__ import annotations

import json
import re

import pytest

SECRET_LOT = "AP-2610-03"  # 예시 CoA의 로트번호 — 파일 이름에도 들어 있으므로 화면용 그래프에는 보이고, 내보내기에서는 가린다
SECRET_SUP = ("○○농산", "△△식품")  # 예시 CoA의 공급처(시료 식별 정보) — 그래프 어디에도 나오면 안 된다


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    from app import db, thesaurus
    h = tmp_path_factory.mktemp("kg_home")
    mp = pytest.MonkeyPatch()
    mp.setenv("BYORBIT_HOME", str(h))
    thesaurus.invalidate()
    db.init(seed=True)
    yield h
    mp.undo()
    thesaurus.invalidate()


@pytest.fixture(scope="module")
def loaded(home, tmp_path_factory):
    from app.ingest import pipeline
    from app.sample_files import make_samples
    files = make_samples(tmp_path_factory.mktemp("kg_samples"))
    return {k: pipeline.ingest_file(p, project="사과박 식이섬유") for k, p in files.items()}


@pytest.fixture(scope="module")
def client(loaded):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import routes_kg
    app = FastAPI()
    app.include_router(routes_kg.router)
    return TestClient(app)


def _cid(label, scheme=None):
    from app import db
    sql = "SELECT c.concept_id FROM concept c JOIN concept_scheme s ON s.scheme_id=c.scheme_id WHERE c.pref_label_ko=?"
    args = [label]
    if scheme:
        sql += " AND s.name=?"
        args.append(scheme)
    return db.one(sql, args)["concept_id"]


def _edges(g, typ=None):
    lab = {n["id"]: n["label"] for n in g["nodes"]}
    return {(e["type"], lab[e["source"]], lab[e["target"]]) for e in g["edges"] if typ in (None, e["type"])}


# ---------------------------------------------------------------- 찾기

def test_search_by_synonym(home):
    from app import routes_kg as K
    r = K.search_concepts("사과 포마스")
    assert r[0]["pref_label"] == "사과박" and r[0]["via"] == "사과 포마스" and r[0]["match_type"] == "alt"
    assert r[0]["exact"] and r[0]["scheme"] == "부산물"
    # 띄어쓰기·대소문자 무시, 숨은 표기도 같은 점으로
    assert K.search_concepts("사과포마스")[0]["pref_label"] == "사과박"
    assert K.search_concepts("사과퍼미스")[0]["match_type"] == "hidden"
    assert K.search_concepts("tpc")[0]["pref_label"] == "폴리페놀"
    # 표준명으로 찾으면 via 없음, 같은 개념은 한 번만
    r = K.search_concepts("사과")
    ids = [x["concept_id"] for x in r]
    assert len(ids) == len(set(ids))
    assert r[0]["pref_label"] == "사과" and r[0]["via"] is None
    assert K.search_concepts("") == [] and K.search_concepts("없는표기xyz") == []
    assert K.search_concepts("100%")  == [] or all("%" in x["matched"] for x in K.search_concepts("100%"))


# ---------------------------------------------------------------- 그래프

def test_graph_default_center_is_apple_pomace_with_seed_relations(home):
    from app import routes_kg as K
    g = K.build_graph(None, 1)
    assert g["center_label"] == "사과박" and g["depth"] == 1 and not g["truncated"]
    e = _edges(g)
    assert ("broader", "사과박", "과실 착즙박") in e
    assert ("derivedFrom", "사과박", "사과") in e
    assert ("generatedBy", "사과박", "착즙") in e
    for k in ("식이섬유", "펙틴", "폴리페놀", "클로로겐산", "플로리진"):
        assert ("contains", "사과박", k) in e
    center = next(n for n in g["nodes"] if n["id"] == g["center"])
    assert center["kind"] == "concept" and center["key"] == "Byproduct" and center["depth"] == 0
    # 동의어는 따로 점이 되지 않는다
    assert not any(n["label"] in ("사과 포마스", "apple marc") for n in g["nodes"])
    # 깊이 1이면 상위 분류의 상위(농업)·형제(배박)는 아직 없다
    labels = {n["label"] for n in g["nodes"]}
    assert "농업" not in labels and "배박" not in labels
    assert g["legend"]["broader"] == "상위 분류" and g["legend"]["contains"] == "함유 성분"


def test_graph_depth_two_and_cap(home):
    from app import routes_kg as K
    g2 = K.build_graph("사과박", 2)
    labels = {n["label"] for n in g2["nodes"]}
    assert {"농업", "배박", "포도박"} <= labels
    assert max(n["depth"] for n in g2["nodes"]) == 2
    assert len(g2["nodes"]) > len(K.build_graph("사과박", 1)["nodes"])
    small = K.build_graph("사과박", 2, cap=8)
    assert len(small["nodes"]) == 8 and small["truncated"] and small["cap"] == 8
    ids = {n["id"] for n in small["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in small["edges"])
    # 더 펼칠 수 있는 이웃 수
    fruit = next(n for n in g2["nodes"] if n["label"] == "과실 착즙박")
    assert fruit["hidden"] == 0
    g1 = K.build_graph("사과박", 1)
    assert next(n for n in g1["nodes"] if n["label"] == "과실 착즙박")["hidden"] >= 3  # 배박·포도박·감귤박·농업
    # 깊이 값은 1·2로 정리
    assert K.build_graph("사과박", 5)["depth"] == 2 and K.build_graph("사과박", 0)["depth"] == 1


def test_graph_center_by_id_synonym_and_types(home):
    from app import routes_kg as K
    cid = _cid("폴리페놀")
    assert K.build_graph(cid, 1)["center"] == cid
    assert K.build_graph("TPC", 1)["center"] == cid  # 동의어로도 가운데를 고른다
    with pytest.raises(KeyError):
        K.build_graph("없는개념zzz", 1)
    g = K.build_graph("사과박", 1, types="broader,derivedFrom")
    assert {e["type"] for e in g["edges"]} <= {"broader", "derivedFrom"}
    assert {n["label"] for n in g["nodes"]} == {"사과박", "과실 착즙박", "사과"}


def test_document_mention_edges_after_samples(loaded):
    from app import routes_kg as K
    g = K.build_graph("사과박", 1)
    docs = [n for n in g["nodes"] if n["kind"] == "document"]
    assert docs and all(n["id"].startswith("doc:") for n in docs)
    men = [e for e in g["edges"] if e["type"] == "mentions" and e["target"] == g["center"]]
    assert men and all(e["count"] >= 1 and e["source"].startswith("doc:") for e in men)
    paper = next(n for n in docs if "논문" in n["label"] or "건조" in n["label"])
    assert paper["confidentiality"] in ("일반", "내부")
    # 자료 점은 펼치지 않는다: 자료 → 다른 개념 선은 가운데와 이어진 개념에만
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["target"] in ids for e in g["edges"] if e["type"] == "mentions")
    assert "mentions" not in {e["type"] for e in K.build_graph("사과박", 1, types="contains")["edges"]}


def test_measurement_aggregate_edges(loaded):
    from app import db, routes_kg as K
    g = K.build_graph("사과박", 1)
    ms = {next(n["label"] for n in g["nodes"] if n["id"] == e["target"]): e for e in g["edges"] if e["type"] == "measured"}
    assert "식이섬유" in ms and "수분" in ms
    tdf = ms["식이섬유"]
    rows = db.rows("SELECT m.value FROM measurement m JOIN byproduct b ON b.byproduct_id=m.byproduct_id "
                   "WHERE b.concept_id=? AND m.target_concept_id=? AND m.value IS NOT NULL AND m.unit_text=?",
                   (g["center"], _cid("식이섬유"), tdf["unit"]))
    vals = [r["value"] for r in rows]
    assert tdf["n_numeric"] == len(vals) >= 2  # 동결건조 CoA + 열풍건조 CoA
    assert tdf["mean"] == pytest.approx(sum(vals) / len(vals), abs=1e-3)
    assert tdf["min"] == min(vals) and tdf["max"] == max(vals)
    assert tdf["units"][0]["unit"] == tdf["unit"]
    assert "측정" == tdf["label"]
    blob = json.dumps(g, ensure_ascii=False)
    assert not any(x in blob for x in SECRET_SUP) and "supplier" not in blob and "lot_no" not in blob


def test_concept_detail(loaded):
    from app import routes_kg as K
    d = K.concept_detail(_cid("사과박", "부산물"))
    assert d["pref_label"] == "사과박" and d["scheme"] == "부산물" and d["pref_label_en"] == "Apple pomace"
    assert {l["label"] for l in d["labels"]["alt"]} >= {"사과 포마스", "사과 착즙박"}
    assert [l["label"] for l in d["labels"]["hidden"]] == ["사과퍼미스"]
    assert d["iri"] == "https://byorbit.kr/onto/Byproduct/apple-pomace" and d["curie"] == "byo:Byproduct/apple-pomace"
    assert d["class"]["label_en"] == "Byproduct"
    outs = {(r["rel_type"], r["label"]) for r in d["relations_out"]}
    assert ("derivedFrom", "사과") in outs and ("broader", "과실 착즙박") in outs
    assert all(r["rel_label"] for r in d["relations_out"])
    assert d["documents"] and all(x["mentions"] >= 1 and x["first_chunk_id"] for x in d["documents"])
    assert d["measurements"]["role"] == "byproduct"
    items = {r["item"] for r in d["measurements"]["rows"]}
    assert {"식이섬유", "수분"} <= items
    blob = json.dumps(d, ensure_ascii=False)
    assert not any(x in blob for x in SECRET_SUP) and "lot_no" not in blob and "sample_code" not in blob
    # 측정 항목 쪽에서 보면 부산물 목록
    t = K.concept_detail(_cid("식이섬유"))
    assert t["measurements"]["role"] == "target" and t["measurements"]["rows"][0]["item"] == "사과박"
    assert any(r["label"] == "사과박" and r["rel_type"] == "contains" for r in t["relations_in"])
    with pytest.raises(KeyError):
        K.concept_detail("0" * 32)


def test_document_detail_and_stats(loaded):
    from app import routes_kg as K
    g = K.build_graph("사과박", 1)
    doc = next(n for n in g["nodes"] if n["kind"] == "document")
    d = K.document_detail(doc["doc_id"])
    assert d["file_name"] and any(k["label"] == "사과박" for k in d["concepts"]) and d["first_chunk_id"]
    s = K.stats()
    assert s["concepts"] > 100 and any(x["scheme"] == "부산물" and x["concepts"] >= 30 for x in s["schemes"])
    rels = {r["rel_type"]: r for r in s["relations"]}
    assert rels["contains"]["label"] == "함유 성분" and rels["broader"]["n"] >= 30
    assert s["labels"]["hidden"] >= 1 and s["mentions"]["documents"] >= 3 and s["measured"]["pairs"] >= 5


def test_export_ttl(loaded):
    from app import routes_kg as K, tools
    r = tools.propose_concept("사과 씨", "부산물", ["apple seed"], None, "과실 착즙박")
    from app.server import approve_concept
    approve_concept(r["concept_id"])
    t = K.export_ttl()
    for p in ("@prefix byo: <https://byorbit.kr/onto/> .", "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
              "@prefix mine: <https://byorbit.kr/onto/mine/> ."):
        assert p in t
    assert t.count("@prefix skos:") == 1
    assert '<https://byorbit.kr/onto/Byproduct/apple-pomace> a skos:Concept' in t
    assert 'skos:prefLabel "사과박"@ko' in t and 'skos:altLabel "사과 포마스"' in t and 'skos:hiddenLabel "사과퍼미스"' in t
    assert "skos:broader <https://byorbit.kr/onto/Category/agri-fruit>" in t
    assert "byo:contains" in t and "byo:derivedFrom" in t
    assert "# ---- 내 확장" in t and 'skos:prefLabel "사과 씨"' in t.split("# ---- 내 확장")[1]
    # 문장마다 ' .'로 끝나고 따옴표 짝이 맞는다(간이 구문 점검)
    code = "\n".join(line for line in t.splitlines() if not line.startswith("#"))
    body = [b for b in re.split(r"\n(?=<https://)", code) if b.startswith("<https://")]
    assert len(body) > 150 and all(b.rstrip().endswith(" .") for b in body)
    assert all(line.count('"') % 2 == 0 for line in t.splitlines() if not line.startswith("#"))


def test_export_json_masks_confidential(loaded):
    from app import routes_kg as K
    j = K.export_json()
    assert j["nodes"] and j["edges"] and "기밀" in j["note"]
    docs = [n for n in j["nodes"] if n["kind"] == "document"]
    secret = [n for n in docs if n["confidentiality"] == "기밀"]
    assert secret and all(n["label"].startswith("기밀자료-") and "file_name" not in n for n in secret)
    blob = json.dumps(j, ensure_ascii=False)
    assert SECRET_LOT not in blob and not any(x in blob for x in SECRET_SUP)
    # 예시 CoA(기밀) 값만 있는 측정 선은 내보내지 않는다
    assert not [e for e in j["edges"] if e["type"] == "measured"]


# ---------------------------------------------------------------- API

def test_api(client):
    r = client.get("/api/kg/search", params={"q": "사과 포마스"}).json()
    assert r["results"][0]["pref_label"] == "사과박" and r["results"][0]["via"] == "사과 포마스"
    g = client.get("/api/kg/graph").json()
    assert g["center_label"] == "사과박" and g["nodes"] and g["edges"]
    g2 = client.get("/api/kg/graph", params={"center": g["center"], "depth": 2, "cap": 20}).json()
    assert len(g2["nodes"]) == 20 and g2["truncated"]
    assert client.get("/api/kg/graph", params={"center": "없는개념zzz"}).status_code == 404
    c = client.get(f"/api/kg/concept/{g['center']}").json()
    assert c["pref_label"] == "사과박" and c["labels"]["hidden"]
    assert client.get("/api/kg/concept/" + "0" * 32).status_code == 404
    doc = next(n for n in g["nodes"] if n["kind"] == "document")
    assert client.get(f"/api/kg/document/{doc['doc_id']}").json()["concepts"]
    assert client.get("/api/kg/document/" + "0" * 32).status_code == 404
    assert client.get("/api/kg/stats").json()["concepts"] > 100
    t = client.get("/api/kg/export.ttl")
    assert t.status_code == 200 and t.headers["content-type"].startswith("text/turtle")
    assert "attachment" in t.headers["content-disposition"] and 'skos:prefLabel "사과박"@ko' in t.text
    j = client.get("/api/kg/export.json")
    assert j.status_code == 200 and "attachment" in j.headers["content-disposition"] and j.json()["nodes"]


def test_server_includes_kg_router(home):
    from app.server import app
    paths = set(app.openapi()["paths"])
    assert {"/api/kg/graph", "/api/kg/search", "/api/kg/concept/{cid}", "/api/kg/export.ttl"} <= paths
    assert app.title == "R&D Studio V0.5"
