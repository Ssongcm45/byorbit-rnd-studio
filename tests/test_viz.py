"""시각화(B): 분자 구조·건조 방식·구성도·파이프라인·라우터."""
from __future__ import annotations

import io
import json
import urllib.parse

import pytest

rdkit = pytest.importorskip("rdkit", reason="RDKit 미설치 — pip install rdkit")


@pytest.fixture(scope="module")
def vhome(tmp_path_factory):
    """이 모듈 전용 데이터 폴더. test_m1의 세션 BYORBIT_HOME을 끝나면 되돌린다."""
    from app import db, thesaurus
    h = tmp_path_factory.mktemp("viz_home")
    mp = pytest.MonkeyPatch()
    mp.setenv("BYORBIT_HOME", str(h))
    thesaurus.invalidate()
    db.init(seed=True)
    yield h
    mp.undo()
    thesaurus.invalidate()


@pytest.fixture(scope="module")
def client(vhome):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import routes_viz
    app = FastAPI()
    app.include_router(routes_viz.router)
    return TestClient(app)


# ---------------------------------------------------------------- 구조

FORMULAS = {
    "chlorogenic-acid": "C16H18O9", "quercetin": "C15H10O7", "phloridzin": "C21H24O10", "hesperidin": "C28H34O15",
    "ascorbic-acid": "C6H8O6", "galacturonic-acid": "C6H10O7", "cellobiose": "C12H22O11", "caffeine": "C8H10N4O2",
    "catechin": "C15H14O6", "epicatechin": "C15H14O6", "procyanidin-b2": "C30H26O12", "naringin": "C27H32O14",
    "gallic-acid": "C7H6O5", "caffeic-acid": "C9H8O4", "cyanidin-3-glucoside": "C21H21O11+", "rutin": "C27H30O16",
    "tannic-acid": "C76H52O46", "glucose": "C6H12O6", "fructose": "C6H12O6", "sucrose": "C12H22O11",
    "malic-acid": "C4H6O5", "citric-acid": "C6H8O7", "limonene": "C10H16", "beta-carotene": "C40H56",
}


def test_seed_formulas(vhome):
    from app.viz import structures as S
    assert set(FORMULAS) == set(S.SEED)
    for k, f in FORMULAS.items():
        assert S.properties(S.entry(k))["formula"] == f, k
    p = S.properties(S.entry("chlorogenic-acid"))
    assert abs(p["mw"] - 354.31) < 0.05 and p["hbd"] == 6


def test_seed_korean_names_match_plan(vhome):
    from app.viz import structures as S
    plan = ["클로로겐산", "퀘르세틴", "플로리진", "카테킨", "에피카테킨", "프로시아니딘 B2", "헤스페리딘", "나린진", "갈산", "카페산",
            "시아니딘-3-글루코시드", "루틴", "탄닌산", "갈락투론산", "셀로비오스", "포도당", "과당", "자당", "말산", "시트르산",
            "아스코르브산", "리모넨", "베타카로틴", "카페인"]
    assert sorted(e[0] for e in S.SEED.values()) == sorted(plan)


def test_resolve_synonyms_and_representatives(vhome):
    from app.viz import structures as S
    assert S.resolve("chlorogenic acid")["key"] == "chlorogenic-acid"
    assert S.resolve("Chlorogenic Acid")["ko"] == "클로로겐산"
    assert S.resolve("β-carotene")["key"] == "beta-carotene"
    r = S.resolve("총폴리페놀")
    assert r["key"] == "gallic-acid" and r["representative"] is True and "GAE" in r["representative_note"]
    assert S.resolve("TPC")["key"] == "gallic-acid"
    assert S.resolve("pectin")["key"] == "galacturonic-acid" and S.resolve("pectin")["representative"]
    assert S.resolve("셀룰로오스")["key"] == "cellobiose"
    assert S.resolve("총식이섬유")["key"] == "cellobiose"
    assert S.resolve("안토시아닌")["key"] == "cyanidin-3-glucoside"
    assert S.resolve("탄닌")["key"] == "tannic-acid"
    assert S.resolve("클로로겐산")["representative"] is False
    assert S.resolve("없는성분xyz") is None


def test_svg_and_sdf_are_cached(vhome):
    from rdkit import Chem
    from app.viz import structures as S
    e = S.entry("quercetin")
    svg = S.svg(e)
    assert svg.startswith("<svg") and "currentColor" in svg and "<?xml" not in svg and "<rect" not in svg.split("<path")[0]
    assert (vhome / "structures" / "quercetin.svg").exists()
    r = S.sdf(e)
    assert r["ok"] and (vhome / "structures" / "quercetin.sdf").exists()
    m = Chem.MolFromMolBlock(r["sdf"], removeHs=False)
    conf = m.GetConformer()
    assert conf.Is3D() and any(abs(conf.GetAtomPosition(i).z) > 0.1 for i in range(m.GetNumAtoms()))
    assert S.sdf(e)["cached"] is True
    assert S.three_d_status("quercetin") == "ready"


def test_big_molecules_3d_complete(vhome):
    from app.viz import structures as S
    for k in ("tannic-acid", "beta-carotene"):
        r = S.sdf(S.entry(k), time_budget_s=30)
        assert r["ok"] or "2D" in r["message"]


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_pubchem_fetch_sends_only_name(vhome):
    from app.viz import structures as S
    seen = []

    def fake(req, timeout=None):
        seen.append((req, timeout))
        body = {"PropertyTable": {"Properties": [{"CID": 445858, "SMILES": "COC1=C(C=CC(=C1)/C=C/C(=O)O)O",
                                                  "IUPACName": "(E)-3-(4-hydroxy-3-methoxyphenyl)prop-2-enoic acid",
                                                  "MolecularFormula": "C10H10O4"}]}}
        return _Resp(json.dumps(body).encode())

    r = S.fetch_pubchem(name_en="ferulic acid", urlopen=fake)
    req, timeout = seen[0]
    assert timeout == 10 and req.data is None and req.get_method() == "GET"
    path = urllib.parse.urlparse(req.full_url).path
    assert path == "/rest/pug/compound/name/ferulic%20acid/property/IsomericSMILES,CanonicalSMILES,IUPACName,MolecularFormula/JSON"
    assert urllib.parse.urlparse(req.full_url).query == ""
    assert set(k.lower() for k in req.headers) <= {"user-agent", "accept"}
    assert r["source"] == "PubChem CID 445858" and r["key"] == "ferulic-acid"
    assert (vhome / "structures" / "ferulic-acid.json").exists()
    # 이제 로컬에서 찾히고 다시 묻지 않는다
    assert S.resolve("ferulic acid")["source"] == "PubChem CID 445858"
    again = S.fetch_pubchem(name_en="ferulic acid", urlopen=lambda *a, **k: pytest.fail("네트워크 호출 금지"))
    assert again["already"] is True
    assert S.properties(S.entry("ferulic-acid"))["formula"] == "C10H10O4"
    assert any(i["key"] == "ferulic-acid" for i in S.listing()["items"])


def test_pubchem_korean_without_english_asks_for_name(vhome):
    from app.viz import structures as S
    with pytest.raises(S.FetchError) as ei:
        S.fetch_pubchem(term="모르는성분", urlopen=lambda *a, **k: pytest.fail("네트워크 호출 금지"))
    assert "영문" in str(ei.value)
    # 시드에 있으면 묻지 않는다
    assert S.fetch_pubchem(term="클로로겐산", urlopen=lambda *a, **k: pytest.fail("x"))["already"]


def test_pubchem_404_message(vhome):
    import urllib.error
    from app.viz import structures as S

    def nf(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    with pytest.raises(S.FetchError) as ei:
        S.fetch_pubchem(name_en="notacompound", urlopen=nf)
    assert "찾지 못했습니다" in str(ei.value)


# ---------------------------------------------------------------- 건조

@pytest.mark.parametrize("text,concept,method,temp,time_h", [
    ("동결건조; -50 ℃; 48 h", None, "동결건조", -50, 48),
    ("열풍건조; 60 ℃", None, "열풍건조", 60, None),
    ("60°C에서 12시간 열풍건조", None, "열풍건조", 60, 12),
    ("freeze-dried at -50 °C for 48 h", None, "동결건조", -50, 48),
    ("vacuum dried at 40-60 ℃ for 90 min", None, "진공건조", 50, 1.5),
    ("천일건조 7일", None, "자연건조", None, 168),
    ("spray-dried, inlet 180 °C", None, "분무건조", 180, None),
    ("-40 ℃; 24 h", "동결건조", "동결건조", -40, 24),
    ("FD", None, "동결건조", None, None),
])
def test_parse_pretreatment(text, concept, method, temp, time_h):
    from app.viz import drying
    r = drying.parse_pretreatment(text, concept)
    assert r["method"] == method and r["temp_c"] == temp and r["time_h"] == time_h


def test_parse_pressure():
    from app.viz import drying
    assert drying.parse_pretreatment("동결건조; -50 ℃; 48 h; 10 Pa")["pressure_pa"] == 10
    assert drying.parse_pretreatment("vacuum 0.1 mbar")["pressure_pa"] == 10


def test_phase_diagram_triple_point():
    from app.viz import drying
    assert abs(drying.p_sub(273.16) - 611.657) < 2
    assert abs(drying.p_vap(373.15) - 101325) < 300
    ph = drying.phase_diagram()
    fd = ph["paths"]["동결건조"]
    assert any(q["p"] < 611.657 and q["t"] < 0 for q in fd)  # 삼중점 아래로 간다
    assert all(q["p"] == 101325 for q in ph["paths"]["열풍건조"])
    assert len(drying.methods()["methods"]) == 5


def _ins_measurements():
    from app import db
    bp = db.one("SELECT b.byproduct_id FROM byproduct b JOIN concept c ON c.concept_id=b.concept_id WHERE c.pref_label_ko='사과박'")["byproduct_id"]
    fd = db.one("SELECT concept_id FROM concept WHERE pref_label_ko='동결건조'")["concept_id"]
    with db.tx() as c:
        for i, (pre, cid, tdf, tpc) in enumerate([("동결건조; -50 ℃; 48 h", fd, 55.0, 10.1),
                                                   ("60°C에서 12시간 열풍건조", None, 47.0, 5.8),
                                                   ("열풍건조; 70 ℃", None, 45.0, 5.0)]):
            sid = db.new_id()
            c.execute("INSERT INTO sample(sample_id, byproduct_id, supplier, pretreatment_concept_id, pretreatment_text, lot_no, sample_code) "
                      "VALUES (?,?,?,?,?,?,?)", (sid, bp, f"비밀공급처{i}", cid, pre, f"LOT-SECRET-{i}", f"S-CODE-{i}"))
            for t, v, u in (("총식이섬유", tdf, "g/100 g"), ("총폴리페놀", tpc, "mg GAE/g")):
                c.execute("INSERT INTO measurement(meas_id, byproduct_id, sample_id, target_text, value, unit_text, entry) "
                          "VALUES (?,?,?,?,?,?, 'coa')", (db.new_id(), bp, sid, t, v, u))
        # 논문 추출값: 같은 문단에 두 방식 — 값 앞의 표기로 나눈다
        src, doc, ch = db.new_id(), db.new_id(), db.new_id()
        text = "동결건조 사과박의 총식이섬유는 건량 기준 54.2 g/100 g으로 열풍건조(48.7 g/100 g)보다 높았다."
        c.execute("INSERT INTO source(source_id, source_type, title) VALUES (?, 'paper', '예시')", (src,))
        c.execute("INSERT INTO document(doc_id, source_id, file_uri, file_name) VALUES (?,?,?,?)", (doc, src, "x.pdf", "x.pdf"))
        c.execute("INSERT INTO chunk(chunk_id, doc_id, chunk_type, ord, text) VALUES (?,?, 'text', 0, ?)", (ch, doc, text))
        for val in ("54.2", "48.7"):
            ann = db.new_id()
            i = text.index(val)
            c.execute("INSERT INTO annotation(ann_id, chunk_id, span_start, span_end, surface_text, label_type, method, status) "
                      "VALUES (?,?,?,?,?, 'VALUE', 'llm', 'accepted')", (ann, ch, i, i + len(val), val))
            c.execute("INSERT INTO measurement(meas_id, target_text, value, unit_text, ann_id, doc_id, entry) "
                      "VALUES (?, '총식이섬유', ?, 'g/100 g', ?, ?, 'extracted')", (db.new_id(), float(val), ann, doc))


def test_compare_groups_by_method(vhome):
    from app.viz import drying
    _ins_measurements()
    r = drying.compare(targets=["식이섬유", "폴리페놀"])
    tdf = {g["method"]: g for g in r["targets"][0]["groups"]}
    assert tdf["동결건조"]["n"] == 2 and tdf["동결건조"]["max"] == 55.0 and tdf["동결건조"]["min"] == 54.2
    assert tdf["열풍건조"]["n"] == 3 and tdf["열풍건조"]["min"] == 45.0 and tdf["열풍건조"]["unit"] == "g/100 g"
    assert abs(tdf["열풍건조"]["mean"] - (47 + 45 + 48.7) / 3) < 1e-3
    assert "문헌 1" in tdf["동결건조"]["samples"] and any(s.startswith("시료 ") for s in tdf["동결건조"]["samples"])
    assert tdf["동결건조"]["conditions"][0]["temp_c"] == -50
    tpc = {g["method"]: g for g in r["targets"][1]["groups"]}
    assert tpc["동결건조"]["unit"] == "mg GAE/g" and tpc["열풍건조"]["n"] == 2
    dump = json.dumps(r, ensure_ascii=False)
    assert "LOT-SECRET" not in dump and "비밀공급처" not in dump and "S-CODE" not in dump
    # 부산물 필터: 논문 값은 본문의 '사과박' 표기로 포함
    r2 = drying.compare(byproduct="사과박", targets=["식이섬유"])
    assert r2["targets"][0]["n"] == 5
    assert drying.compare(byproduct="굴 패각", targets=["식이섬유"])["targets"][0]["n"] == 0


# ---------------------------------------------------------------- 구성도·파이프라인

def test_system_map(vhome):
    from app.viz import system
    m = system.system_map()
    ids = {n["id"]: n for n in m["nodes"]}
    food = ids["mcp_food"]
    assert "extract_label_table" in food["blocked"] and "extract_label_table" not in food["tools"]
    assert len(food["tools"]) == 12 and "extract_label_table" in food["detail"]
    assert len(ids["mcp_rd"]["tools"]) == 7
    assert ids["neon"]["kind"] == "cloud" and ids["anthropic"]["kind"] == "external"
    assert all(n["status"] in ("ok", "off", "missing") for n in m["nodes"])
    out = [e for e in m["edges"] if e["boundary"] != "local"]
    assert any(e["to"] == "anthropic" and "가림" in e["crosses"] for e in out)
    assert any(e["to"] == "pubchem" and "성분명" in e["crosses"] for e in out)


def test_pipeline_counts(vhome):
    from app.viz import system
    p = system.pipeline()
    st = {s["id"]: s for s in p["stages"]}
    assert st["docs"]["n"] >= 1 and st["chunks"]["n"] >= 1
    assert st["meas"]["detail"]["CoA"] == 6 and st["meas"]["detail"]["논문 추출"] == 2
    assert st["labels"]["detail"]["승인"] == 2
    assert system.pipeline("기본 프로젝트")["stages"][0]["n"] == 0
    assert "error" in system.pipeline("없는 프로젝트")


# ---------------------------------------------------------------- 라우터

def test_router_endpoints(client):
    r = client.get("/api/viz/structures")
    assert r.status_code == 200 and r.json()["rdkit"] is True and len(r.json()["items"]) >= 24
    r = client.get("/api/viz/structures/resolve", params={"term": "총폴리페놀"})
    assert r.json()["found"] and r.json()["key"] == "gallic-acid" and r.json()["representative"] is True
    r = client.get("/api/viz/structures/resolve", params={"term": "모르는성분"})
    assert r.json()["found"] is False and "PubChem" in r.json()["message"]
    assert client.get("/api/viz/structures/resolve").status_code == 400
    r = client.get("/api/viz/structures/caffeine")
    assert r.json()["props"]["formula"] == "C8H10N4O2"
    r = client.get("/api/viz/structures/caffeine.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml") and r.text.startswith("<svg")
    r = client.get("/api/viz/structures/caffeine.sdf")
    assert r.status_code == 200 and "M  END" in r.text
    r = client.get("/api/viz/structures/nothing-here")
    assert r.status_code == 404 and "검색" in r.json()["detail"]
    assert client.get("/api/viz/structures/nothing-here.svg").status_code == 404
    r = client.post("/api/viz/structures/fetch", json={})
    assert r.status_code == 400
    r = client.post("/api/viz/structures/fetch", json={"term": "모르는성분"})
    assert r.status_code == 400 and "영문" in r.json()["detail"]
    assert len(client.get("/api/viz/drying/methods").json()["methods"]) == 5
    assert client.get("/api/viz/drying/phase").json()["triple_point"]["p"] == 611.657
    r = client.get("/api/viz/drying/compare", params=[("target", "식이섬유"), ("byproduct", "사과박")])
    assert r.status_code == 200 and r.json()["targets"][0]["target"] == "식이섬유"
    assert client.get("/api/viz/drying/parse", params={"text": "열풍건조; 60 ℃"}).json()["temp_c"] == 60
    assert any(n["id"] == "mcp_food" for n in client.get("/api/viz/system").json()["nodes"])
    assert client.get("/api/viz/pipeline").status_code == 200
    assert client.get("/api/viz/pipeline", params={"project": "없는 프로젝트"}).status_code == 404


def test_rdkit_missing_message(client, monkeypatch):
    from app.viz import structures as S
    monkeypatch.setattr(S, "rdkit_available", lambda: False)
    r = client.get("/api/viz/structures/caffeine.svg")
    assert r.status_code == 503 and "RDKit" in r.json()["detail"]
    assert client.get("/api/viz/structures").json()["message"]


# ---------------------------------------------------------------- 건조 설비 모델(3D·P&ID)

def _equip_variants():
    from app.viz import drying
    for name in drying.ORDER:
        vs = [v["id"] for v in drying.EQUIPMENT[name].get("variants", [])] or [None]
        for v in vs:
            yield name, v, drying.equipment(name, v)


def test_equipment_catalog_consistent():
    from app.viz import drying
    assert set(drying.EQUIPMENT) == set(drying.ORDER)
    for name, v, e in _equip_variants():
        assert len(e["stages"]) == len(drying.METHODS[name]["stages"]), name
        ids = [p["id"] for p in e["parts"]]
        assert len(ids) == len(set(ids)) and len(ids) >= 5, (name, v)
        for p in e["parts"]:
            assert all(p[k].strip() for k in ("name", "role", "setting", "note")), p
        keys = {g["key"] for g in e["gauges"]}
        for g in e["gauges"]:
            assert g["part"] in ids, (name, v, g)
        for s in e["stages"]:
            plain = {g["key"] for g in e["gauges"] if not g.get("derive")}
            assert plain <= set(s["gauges"]), (name, v, plain - set(s["gauges"]))
            assert all(0 <= x <= 1.2 for a in s["anim"].values() for x in a)
            for g in e["gauges"]:
                if g["unit"] == "Pa" and g["key"] in s["gauges"]:
                    assert min(s["gauges"][g["key"]]) > 0  # 로그 보간
        cm = e["condition"]
        assert cm["temp"] in keys and 0 <= cm["stage"] < len(e["stages"])
        assert cm.get("pressure") in (None, *keys)


def test_equipment_part_ids_in_3d_and_pid():
    """부품 id는 3D 모델(equipment3d.js)과 흐름도(pid.js)가 같은 값을 써야 누르면 같은 설명이 나온다."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "app" / "static" / "viz"
    js3d = (root / "equipment3d.js").read_text(encoding="utf-8")
    pid = (root / "pid.js").read_text(encoding="utf-8")
    for name, v, e in _equip_variants():
        for p in e["parts"]:
            assert f"part('{p['id']}'" in js3d, (name, p["id"], "3D")
            assert f"'{p['id']}'" in pid, (name, p["id"], "P&ID")


def test_equipment_endpoint(client):
    r = client.get("/api/viz/drying/equipment/동결건조")
    assert r.status_code == 200
    j = r.json()
    assert j["method"] == "동결건조" and any(p["id"] == "condenser" for p in j["parts"])
    assert j["stages"][1]["gauges"]["p_ch"][1] == 15
    r = client.get("/api/viz/drying/equipment/자연건조")
    assert r.json()["variant"] == "open" and any(p["id"] == "racks" for p in r.json()["parts"])
    r = client.get("/api/viz/drying/equipment/자연건조", params={"variant": "solar"})
    ids = {p["id"] for p in r.json()["parts"]}
    assert "collector" in ids and "racks" not in ids and "sun" in ids
    assert client.get("/api/viz/drying/equipment/freeze drying").json()["method"] == "동결건조"
    r = client.get("/api/viz/drying/equipment/없는방식")
    assert r.status_code == 404 and "동결건조" in r.json()["detail"]
