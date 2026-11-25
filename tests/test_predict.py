"""건조 결과 예측: 속도식 계산, 단조성, 실측 보정, 외삽 경고, 근거 완전성, 설비 사양, 개인정보, 속도."""
from __future__ import annotations

import json
import math
import statistics
import time

import pytest

HA, FD = "열풍건조", "동결건조"


@pytest.fixture(scope="module")
def phome(tmp_path_factory):
    """이 모듈 전용 데이터 폴더 + 예시 CoA와 같은 값의 시료 2개(동결건조, 열풍건조 60 ℃ 12 h)."""
    from app import db, thesaurus
    h = tmp_path_factory.mktemp("predict_home")
    mp = pytest.MonkeyPatch()
    mp.setenv("BYORBIT_HOME", str(h))
    thesaurus.invalidate()
    db.init(seed=True)
    bp = db.one("SELECT b.byproduct_id FROM byproduct b JOIN concept c ON c.concept_id=b.concept_id "
                "WHERE c.pref_label_ko='사과박'")["byproduct_id"]
    fd = db.one("SELECT concept_id FROM concept WHERE pref_label_ko='동결건조'")["concept_id"]
    with db.tx() as c:
        for i, (pre, cid, rows) in enumerate([
            ("동결건조", fd, [("총식이섬유", 52.6, "g/100 g"), ("총폴리페놀", 8.9, "mg GAE/g"), ("수분", 6.2, "%")]),
            ("열풍건조; 60 ℃; 12 h", None, [("수분(생시료)", 78.4, "%"), ("수분(건조 후)", 7.9, "%"),
                                            ("총식이섬유 TDF", 47.9, "g/100 g"), ("총폴리페놀 TPC", 5.7, "mg GAE/g")]),
        ]):
            sid = db.new_id()
            c.execute("INSERT INTO sample(sample_id, byproduct_id, supplier, pretreatment_concept_id, pretreatment_text, lot_no, sample_code) "
                      "VALUES (?,?,?,?,?,?,?)", (sid, bp, f"비밀공급처{i}", cid, pre, f"LOT-SECRET-{i}", f"S-CODE-{i}"))
            for t, v, u in rows:
                c.execute("INSERT INTO measurement(meas_id, byproduct_id, sample_id, target_text, value, unit_text, entry) "
                          "VALUES (?,?,?,?,?,?, 'coa')", (db.new_id(), bp, sid, t, v, u))
    yield h
    mp.undo()
    thesaurus.invalidate()


@pytest.fixture(scope="module")
def client(phome):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import routes_predict
    app = FastAPI()
    app.include_router(routes_predict.router)
    return TestClient(app)


def out(r, key):
    return next(o for o in r["outputs"] if o["key"] == key)


# ---------------------------------------------------------------- 계산식(손 계산 대조)

def test_arrhenius_hand_computed():
    from app.viz import predict as P
    # k(70 ℃) = 1·exp(−50000/8.314462618·(1/343.15 − 1/333.15)) = exp(0.525995…) = 1.69210
    assert P.arrhenius(1.0, 50000, 70, 60) == pytest.approx(1.69210, rel=1e-4)
    assert P.arrhenius(0.3, 30000, 60, 60) == pytest.approx(0.3)


def test_fit_arrhenius_recovers_known_parameters():
    from app.viz import predict as P
    pts = [(t, P.arrhenius(0.2, 40000, t, 60)) for t in (40, 60, 80, 100)]
    f = P.fit_arrhenius(pts, 60)
    assert f["k_ref"] == pytest.approx(0.2, rel=1e-9) and f["ea_j"] == pytest.approx(40000, rel=1e-9) and f["rmse"] < 1e-9


def test_moisture_basis_and_gab():
    from app.viz import predict as P
    assert P.wb_to_db(78.4) == pytest.approx(0.784 / 0.216)
    assert P.db_to_wb(P.wb_to_db(7.9)) == pytest.approx(7.9)
    # GAB(K=1): m0·C·aw / ((1−aw)(1−aw+C·aw)) = 0.0387·8.2·0.5/(0.5·4.6) = 0.0689870
    assert P.gab_xe(0.5) == pytest.approx(0.0387 * 8.2 * 0.5 / (0.5 * 4.6))


def test_literature_derived_rate_constants_match_hand_calculation():
    from app.viz import predict as P
    pts = {p["temp_c"]: p["k"] for p in P.dry_fit()["residuals"]}
    xe = P.gab_xe(P.heated_air_aw(60))
    assert pts[60.0] == pytest.approx(-math.log((0.15 - xe) / (0.76 - xe)) / (471 / 60))
    tp = {p["temp_c"]: p["k"] for p in P.tpc_fit()["residuals"]}
    assert tp[60.0] == pytest.approx(-math.log(0.55) / (471 / 60))  # 표 2: 55%, 표 1: 471 min
    assert tp[120.0] == pytest.approx(-math.log(0.45) / (129 / 60))
    # 맞춤 Ea는 두 문헌값(23.9, 38.21 kJ/mol) 사이
    assert 23.9 < P.dry_fit()["ea_j"] / 1000 < 38.21


def test_sublimation_enthalpy_from_murphy_koop():
    from app.viz import predict as P
    assert 2.82e6 < P.dh_sub_j_per_kg(253.15) < 2.86e6


# ---------------------------------------------------------------- 단조성

def test_hot_air_monotonic(phome):
    from app.viz import predict as P
    for bp in ("사과박", "굴 패각"):  # 보정 있음 / 실측 없음(보정 없음)
        times, rets, finals = [], [], []
        for t in (40, 50, 60, 70, 80, 100, 120):
            r = P.predict(HA, {"temp_c": t, "time_h": 6}, bp)
            times.append(out(r, "moisture")["headline"]["value"])
            rets.append(out(r, "tpc")["value"])
            finals.append(out(r, "moisture")["value"])
        assert all(a > b for a, b in zip(times, times[1:])), times
        assert all(a > b for a, b in zip(rets, rets[1:])), rets
        assert all(a >= b for a, b in zip(finals, finals[1:])), finals


def test_thicker_layer_dries_slower_and_freeze_shelf_temperature(phome):
    from app.viz import predict as P
    a = out(P.predict(HA, {"thickness_mm": 3}), "moisture")["headline"]["value"]
    b = out(P.predict(HA, {"thickness_mm": 10}), "moisture")["headline"]["value"]
    assert b > a
    cold = P.predict(FD, {"temp_c": -10})["outputs"][0]["headline"]["value"]
    warm = P.predict(FD, {"temp_c": 30})["outputs"][0]["headline"]["value"]
    assert warm < cold
    # 압력이 선반 온도의 얼음 증기압보다 높으면 승화하지 않는다
    r = P.predict(FD, {"temp_c": -30, "pressure_pa": 100})
    assert any("승화가 일어나지 않" in w["text"] for w in out(r, "moisture")["warnings"])


# ---------------------------------------------------------------- 실측 보정

def test_calibration_with_measured_samples(phome):
    from app.viz import predict as P
    ctx = P.context("사과박", None)
    dc, tc = ctx["dry_cal"], ctx["tpc_cal"]
    x0, xf = P.wb_to_db(78.4), P.wb_to_db(7.9)
    xe = P.gab_xe(P.heated_air_aw(60))
    k_meas = -math.log((xf - xe) / (x0 - xe)) / 12
    assert dc["applied"] and dc["n"] == 1 and dc["factor"] == pytest.approx(k_meas / P.k_dry_lit(60), rel=1e-3)
    assert tc["applied"] and tc["n"] == 1 and tc["ref"]["value"] == pytest.approx(8.9)
    assert tc["factor"] == pytest.approx((-math.log(5.7 / 8.9) / 12) / P.k_tpc_lit(60), rel=1e-3)
    assert "신뢰도 낮음" in dc["message"] and "n=1" in tc["message"]
    # 보정된 모델은 그 실측 조건을 다시 재현한다
    r = P.predict(HA, {"temp_c": 60, "time_h": 12, "initial_moisture": 78.4})
    assert out(r, "moisture")["value"] == pytest.approx(7.9, abs=0.05)
    tpc = out(r, "tpc")
    assert tpc["value"] == pytest.approx(64.04, abs=0.1)
    assert tpc["secondary"][0]["value"] == pytest.approx(5.7, abs=0.02)
    assert any(w["kind"] == "calibration" and "n=1" in w["text"] for w in tpc["warnings"])
    assert tpc["calibration"]["points"][0]["residual"] == pytest.approx(0, abs=1e-3)
    # n=1이면 폭을 넓힌다: 보정 없는 부산물보다 상대 폭이 넓다
    cal = out(r, "moisture")["headline"]
    raw = out(P.predict(HA, {"temp_c": 60, "time_h": 12, "initial_moisture": 78.4}, "굴 패각"), "moisture")["headline"]
    assert cal["high"] / cal["low"] > raw["high"] / raw["low"]
    # 초기 수분 기본값은 실측 생시료 수분
    spec = next(s for s in P.models(HA)["inputs"] if s["key"] == "initial_moisture")
    assert spec["default"] == 78.4 and "실측" in spec["default_from"]
    # TDF는 실측에 고정
    assert out(r, "tdf")["value"] == pytest.approx(47.9) and out(P.predict(FD), "tdf")["value"] == pytest.approx(52.6)


def test_no_measured_data_falls_back_honestly(phome):
    from app.viz import predict as P
    r = P.predict(HA, {}, "굴 패각")
    assert out(r, "tpc")["calibration"] is None
    assert out(r, "tdf")["status"] == "unavailable" and out(r, "tdf")["value"] is None
    assert any(w["kind"] == "byproduct" for w in out(r, "moisture")["warnings"])
    assert out(r, "color")["status"] == "qualitative" and out(r, "color")["value"] is None


# ---------------------------------------------------------------- 외삽

def test_extrapolation_flags(phome):
    from app.viz import predict as P
    ok = P.predict(HA, {"temp_c": 60, "air_velocity_ms": 0.9, "thickness_mm": 3})
    assert not [w for w in out(ok, "moisture")["warnings"] if w["kind"] == "extrapolation"]
    assert not [w for w in out(ok, "tpc")["warnings"] if w["kind"] == "extrapolation"]
    hot = P.predict(HA, {"temp_c": 130})
    w = [w for w in out(hot, "moisture")["warnings"] if w["kind"] == "extrapolation"]
    assert w and w[0]["input"] == "temp_c" and "외삽 — 근거 범위 밖" in w[0]["text"]
    assert [w for w in out(hot, "tpc")["warnings"] if w["kind"] == "extrapolation"]
    thick = P.predict(HA, {"thickness_mm": 20, "air_velocity_ms": 2.5})
    keys = {w["input"] for w in out(thick, "moisture")["warnings"] if w["kind"] == "extrapolation"}
    assert keys == {"thickness_mm", "air_velocity_ms"}
    sun = P.predict("자연건조", {"temp_c": 25})
    assert any(w["kind"] == "extrapolation" and w["input"] == "temp_c" for w in out(sun, "moisture")["warnings"])


# ---------------------------------------------------------------- 근거 완전성

def test_registry_literature_entries_are_complete():
    from app.viz import predict as P
    reg = P.registry()
    for sid, s in reg["sources"].items():
        assert s["doi"] and s["verified"] is True and s["verified_at"] and s["read"], sid
    for pid, p in reg["parameters"].items():
        ev = p["evidence"]
        assert ev["type"] in ("literature", "assumption"), pid
        if ev["type"] == "literature":
            assert ev.get("source") in reg["sources"], pid
            assert ev.get("locator"), f"{pid}: 문헌 값인데 읽은 곳(locator)이 없음"
        else:
            assert ev.get("note"), f"{pid}: 가정인데 설명이 없음"
    # 원문을 못 읽은 논문(Kara & Doymaz)의 수치는 쓰지 않는다
    assert not [p for p in reg["parameters"].values() if p["evidence"].get("source") == "kara2014"]


@pytest.mark.parametrize("method", ["동결건조", "열풍건조", "진공건조", "분무건조", "자연건조"])
def test_every_output_parameter_has_evidence(phome, method):
    from app.viz import predict as P
    r = P.predict(method, {})
    assert len(r["outputs"]) == 5
    for o in r["outputs"]:
        assert o["formula"]["text"] and o["formula"]["model"], o["key"]
        assert o["params"], o["key"]
        for p in o["params"]:
            ev = p["evidence"]
            for k in ("type", "citation", "doi", "verified", "verified_at", "locator", "note", "validity"):
                assert k in ev, (o["key"], p["key"], k)
            assert ev["type"] in ("literature", "measured", "equipment", "assumption")
            if ev["type"] == "literature":
                assert ev["doi"] and ev["verified"] is True and ev["verified_at"] and ev["locator"], p["key"]
            if ev["type"] == "measured":
                assert ev["n"] >= 1 and all(s.startswith("시료 ") for s in ev["samples"])
        if o["status"] == "ok" and o["value"] is not None:
            assert o["low"] <= o["value"] <= o["high"], (method, o["key"], o["low"], o["value"], o["high"])
    s = r["summary"]
    assert s["text"].startswith("이 예측의 근거: 문헌") and "DOI 확인" in s["text"] and "가정" in s["text"]
    assert "측정값이 아니" in r["disclaimer"]


# ---------------------------------------------------------------- 설비 사양

def test_equipment_round_trip(phome, client):
    from app.viz import predict as P
    f = phome / "config" / "equipment.json"
    g = client.get("/api/viz/predict/equipment", params={"method": HA}).json()
    assert f.exists()
    heater = next(s for s in g["equipment"][HA] if s["key"] == "heater_kw")
    assert heater["value"] == 9.0 and heater["evidence"]["type"] == "equipment" and "가정" in heater["evidence"]["note"]
    before = out(P.predict(HA, {}), "energy")["value"]
    r = client.post("/api/viz/predict/equipment", json={"method": HA, "values": {"heater_kw": 18}})
    assert r.status_code == 200
    saved = json.loads(f.read_text(encoding="utf-8"))
    assert saved["values"][HA]["heater_kw"] == 18 and saved["edited"][HA]["heater_kw"]
    e = out(P.predict(HA, {}), "energy")
    assert e["value"] > before
    p = next(p for p in e["params"] if p["key"] == "eq_heater_kw")
    assert p["value"] == 18 and "사용자 입력" in p["evidence"]["note"]
    bad = client.post("/api/viz/predict/equipment", json={"method": HA, "values": {"heater_kw": -1}})
    assert bad.status_code == 400 and "사이로 넣으세요" in bad.json()["detail"]
    bad = client.post("/api/viz/predict/equipment", json={"method": HA, "values": {"warp_drive": 1}})
    assert bad.status_code == 400 and "설비 항목이 아닙니다" in bad.json()["detail"]
    client.post("/api/viz/predict/equipment", json={"method": HA, "values": {"heater_kw": 9}})


# ---------------------------------------------------------------- 개인정보·API·속도

def test_privacy_no_identifiers(phome, client):
    dumps = [json.dumps(client.post("/api/viz/predict", json={"method": m, "inputs": {}}).json(), ensure_ascii=False)
             for m in ("동결건조", "열풍건조", "자연건조")]
    dumps.append(json.dumps(client.get("/api/viz/predict/models", params={"method": HA}).json(), ensure_ascii=False))
    for d in dumps:
        assert "LOT-SECRET" not in d and "비밀공급처" not in d and "S-CODE" not in d
    assert "시료 1" in dumps[1]


def test_api_models_and_errors(phome, client):
    m = client.get("/api/viz/predict/models", params={"method": FD}).json()
    assert {s["key"] for s in m["inputs"]} >= {"temp_c", "pressure_pa", "time_h", "thickness_mm", "initial_moisture", "target_moisture"}
    assert m["byproducts"][0] == "사과박" and "llavata2022" in m["sources"]
    assert all("evidence" in p for p in m["parameters"].values())
    r = client.post("/api/viz/predict", json={"method": HA, "inputs": {"temp_c": 500}})
    assert r.status_code == 400 and "30–130" in r.json()["detail"]
    r = client.post("/api/viz/predict", json={"method": "라면건조"})
    assert r.status_code == 400 and "고르세요" in r.json()["detail"]
    r = client.post("/api/viz/predict", json={"method": HA, "inputs": {"target_moisture": 20, "initial_moisture": 15}})
    assert r.status_code == 400
    assert client.get("/api/viz/predict/models", params={"method": "?"}).status_code == 400


def test_api_speed(phome, client):
    client.post("/api/viz/predict", json={"method": HA, "inputs": {}})
    for method in (HA, FD):
        ts = []
        for i in range(15):
            t0 = time.perf_counter()
            r = client.post("/api/viz/predict", json={"method": method, "inputs": {"temp_c": 40 + i if method == HA else i}})
            ts.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200
        assert statistics.median(ts) < 50, (method, ts)
