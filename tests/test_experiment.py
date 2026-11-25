"""내 실험: 질량 수지, 건조 단계 = 건조 예측, 흐름 고치기, 틀, 가져오기(ND·'<0.01'·단위), 잔차, 보정(실험 실측·n·전후),
Ea는 온도 3개 이상에서만, 제안, API, 개인정보."""
from __future__ import annotations

import io
import json
import math

import pytest

HA_T, FD_T, EXT_T = "사과박 열풍건조 분말", "사과박 동결건조 분말", "사과박 열풍건조 + 에탄올 추출"
SECRETS = ("LOT-SECRET", "비밀공급처", "S-CODE")


@pytest.fixture(scope="module")
def xhome(tmp_path_factory):
    """이 모듈 전용 데이터 폴더 + CoA 시료 2개(test_predict와 같은 값, 식별 정보 포함)."""
    from app import db, thesaurus
    h = tmp_path_factory.mktemp("exp_home")
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
def client(xhome):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import routes_experiment, routes_predict
    app = FastAPI()
    app.include_router(routes_experiment.router)
    app.include_router(routes_predict.router)
    return TestClient(app)


def tpl(name):
    from app.experiment import store
    return next(t for t in store.list_templates() if t["name"] == name)


CSV = ("런,날짜,원료 수분(%),원료 TPC (mg GAE/g 건량),압착 후 수분(%),건조 온도(℃),건조 시간(min),건조 후 수분(%),"
       "TPC (mg GAE/100 g 건량),총식이섬유(g/100 g),체 통과 수율(%),비고\n"
       "A-50,2026-11-01,78.2,9.1,64.8,50,600,21.5,610,48.1,82.5,\n"
       "A-60,2026-11-02,78.0,9.0,65.1,60,600,12.4,540,47.6,84.0,\n"
       "A-70,2026-11-03,77.8,9.2,64.9,70,600,7.9,505,47.9,83.1,\n"
       "A-80,2026-11-04,78.1,9.0,65.0,80,480,6.8,< 450,ND,85.2,검출한계 시험\n")


@pytest.fixture(scope="module")
def ha_exp(xhome):
    """열풍건조 틀 실험 + CSV 4런(50·60·70·80 ℃)."""
    from app.experiment import importer, store
    e = store.create_experiment("온도 비교", template_id=tpl(HA_T)["wf_id"])
    pv = importer.preview(e["exp_id"], "runs.csv", CSV.encode("utf-8"))
    r = importer.commit(e["exp_id"], pv["token"], pv["columns"])
    assert r["created"] == 4 and not r["errors"]
    return e["exp_id"]


# ---------------------------------------------------------------- 질량 수지

@pytest.mark.parametrize("name", [HA_T, FD_T, EXT_T])
def test_mass_balance_dry_matter_conserved_except_declared(xhome, name):
    from app.experiment import sim
    r = sim.simulate_flow(tpl(name)["wf_id"])
    assert all(not s.get("error") for s in r["steps"]), [s.get("error") for s in r["steps"]]
    for s in r["steps"][1:]:
        b = s["balance"]
        assert b["closure"] == pytest.approx(0, abs=1e-6), (s["key"], b)
        if not s["losses"]:
            assert b["dm_in"] == pytest.approx(b["dm_out"], rel=1e-9), s["key"]
        if s["type"] == "dry":
            assert b["dm_out"] == pytest.approx(b["dm_in"]) and s["stream_out"]["moisture_pct"] < s["stream_in"]["moisture_pct"]
        so = s["stream_out"]
        assert so["wet_kg"] == pytest.approx(so["dm_kg"] + so["water_kg"], abs=1e-3)
        assert so["moisture_pct"] == pytest.approx(100 * so["water_kg"] / so["wet_kg"], abs=0.01)
        for o in s["outputs"].values():  # 모든 예측값에 근거가 붙는다
            assert o["formula"]["text"] or o["formula"]["model"]
            for p in o["params"]:
                assert p["evidence"]["type"] in ("literature", "measured", "equipment", "assumption", "input")


def test_press_algebra_and_mill_keeps_concentration(xhome):
    from app.experiment import steps as S
    s0 = S.make_stream(100, 78, 9.0, 50.0)
    r = S.sim_press(s0, S.clean_params("press", {"target_moisture_pct": 65}), {})
    s = r["stream"]
    assert s["moisture_pct"] == pytest.approx(65, abs=1e-9)
    liquid = r["side"][0]["wet_kg"]
    assert r["side"][0]["dm_kg"] == pytest.approx(0.08 * liquid)  # 가정 용해 고형분 8%
    assert s["wet_kg"] + liquid == pytest.approx(100)
    m = S.sim_mill(s, S.clean_params("mill", {"particle_mm": 2}), {})["stream"]
    assert S.conc(m, "tpc") == pytest.approx(S.conc(s, "tpc")) and m["particle_mm"] == 2
    assert m["dm_kg"] == pytest.approx(s["dm_kg"] * 0.995)


# ---------------------------------------------------------------- 건조 단계 = 건조 예측

@pytest.mark.parametrize("name", [HA_T, FD_T])
def test_drying_step_equals_predict(xhome, name):
    from app.experiment import sim
    from app.viz import predict as P
    r = sim.simulate_flow(tpl(name)["wf_id"])
    d = next(s for s in r["steps"] if s["type"] == "dry")
    inp = dict(d["predict"]["inputs"])
    assert inp["initial_moisture"] == pytest.approx(round(d["stream_in"]["moisture_pct"], 2))
    ref = {o["key"]: o for o in P.predict(d["drying_method"], inp, "사과박")["outputs"]}
    o = d["outputs"]
    for k in ("value", "low", "high"):
        assert o["moisture"][k] == ref["moisture"][k]
        assert o["energy"][k] == ref["energy"][k]
    assert o["tpc_ret"]["step_value"] == ref["tpc"]["value"]
    assert o["time_target"]["value"] == ref["moisture"]["headline"]["value"]
    assert [p["key"] for p in o["moisture"]["params"]] == [p["key"] for p in ref["moisture"]["params"]]
    assert o["moisture"]["formula"] == ref["moisture"]["formula"]
    # 잔존율은 원료 대비로 누적: 들어온 잔존율 × 건조 잔존율
    assert o["tpc_ret"]["value"] == pytest.approx(d["stream_in"]["tpc_ret_pct"] * ref["tpc"]["value"] / 100, abs=0.02)


# ---------------------------------------------------------------- 흐름 고치기·틀

def test_templates_and_instantiation(xhome):
    from app.experiment import store
    names = [t["name"] for t in store.list_templates()]
    assert names[:3] == [FD_T, HA_T, EXT_T]
    store.ensure_templates()
    assert len(store.list_templates()) == 3  # 두 번 불러도 중복 없음
    e = store.create_experiment("틀 복사", template_id=tpl(EXT_T)["wf_id"], confidentiality="기밀")
    assert e["wf_id"] != tpl(EXT_T)["wf_id"] and not e["flow"]["is_template"]
    assert [s["key"] for s in e["flow"]["steps"]] == [s["key"] for s in tpl(EXT_T)["steps"]]
    assert e["confidentiality"] == "기밀"
    with pytest.raises(store.StoreError, match="일반·내부·기밀"):
        store.create_experiment("x", confidentiality="공개")
    with pytest.raises(store.StoreError, match="기본 틀은 고칠 수 없습니다"):
        store.update_flow(tpl(HA_T)["wf_id"], name="x")


def test_flow_ops_reorder_disable_add_remove(xhome):
    from app.experiment import sim, store
    f = store.create_flow("고치기 시험", template_id=tpl(HA_T)["wf_id"])
    wf = f["wf_id"]
    keys = lambda f: [s["key"] for s in f["steps"]]  # noqa: E731
    f = store.flow_op(wf, "move", key="mill1", delta=-1)
    assert keys(f)[2:4] == ["mill1", "press1"] and f["version"] == 2
    f = store.flow_op(wf, "move", key="mill1", index=3)
    assert keys(f)[2:4] == ["press1", "mill1"]
    f = store.flow_op(wf, "enable", key="wash1", enabled=False)
    r = sim.simulate_flow(wf)
    w = next(s for s in r["steps"] if s["key"] == "wash1")
    assert w["skipped"] and next(s for s in r["steps"] if s["key"] == "press1")["stream_in"]["moisture_pct"] == pytest.approx(78.4)  # 원료 수분 기본값 = CoA 생시료 실측
    f = store.flow_op(wf, "add", type="extract", index=len(f["steps"]))
    assert keys(f)[-1] == "extract1"
    f = store.flow_op(wf, "params", key="extract1", params={"ethanol_pct": 40})
    assert f["steps"][-1]["params"]["ethanol_pct"] == 40
    f = store.flow_op(wf, "params", key="dry1", params={"method": "동결건조"})
    assert "air_velocity_ms" not in next(s for s in f["steps"] if s["key"] == "dry1")["params"]  # 방식이 바뀌면 그 방식에 없는 값은 지움
    f = store.flow_op(wf, "rename", key="dry1", label="동결건조(파일럿)")
    assert next(s for s in f["steps"] if s["key"] == "dry1")["label"] == "동결건조(파일럿)"
    f = store.flow_op(wf, "remove", key="extract1")
    assert "extract1" not in keys(f)
    with pytest.raises(store.StoreError, match="원료 투입"):
        store.flow_op(wf, "move", key="feed1", delta=1)
    with pytest.raises(store.StoreError, match="끌 수 없습니다"):
        store.flow_op(wf, "enable", key="feed1", enabled=False)
    with pytest.raises(store.StoreError, match="범위 밖"):
        store.flow_op(wf, "params", key="dry1", params={"temp_c": 999})
    with pytest.raises(store.StoreError, match="없는 공정 단계"):
        store.flow_op(wf, "add", type="teleport")
    store.delete_flow(wf)
    with pytest.raises(store.NotFound):
        store.get_flow(wf)


def test_removing_step_with_data_needs_force_and_logs(xhome, ha_exp):
    from app import db
    from app.experiment import store
    e = store.get_experiment(ha_exp)
    with pytest.raises(store.StoreError, match="실측값이 있습니다"):
        store.flow_op(e["wf_id"], "remove", key="sieve1")
    with pytest.raises(store.StoreError, match="실험을 먼저 지우세요"):
        store.delete_flow(e["wf_id"])
    tmp = store.create_experiment("지울 실험", template_id=tpl(HA_T)["wf_id"])
    store.add_run(tmp["exp_id"], values=[{"step_key": "sieve1", "target": "체 통과 수율", "value": 80}])
    store.flow_op(tmp["wf_id"], "remove", key="sieve1", force=True)
    store.delete_experiment(tmp["exp_id"])
    assert db.one("SELECT COUNT(*) AS n FROM change_log WHERE table_name='experiment' AND row_id=?", (tmp["exp_id"],))["n"] == 1
    assert db.one("SELECT COUNT(*) AS n FROM workflow WHERE wf_id=?", (tmp["wf_id"],))["n"] == 0


# ---------------------------------------------------------------- 가져오기·내보내기

def test_import_mapping_units_nd_and_censored(xhome, ha_exp):
    from app.experiment import store
    runs = store.get_experiment(ha_exp)["runs"]
    r1, r4 = runs[0], runs[3]
    assert r1["label"] == "A-50" and r1["run_date"] == "2026-11-01"
    assert r1["conditions"]["dry1"] == {"temp_c": 50.0, "time_h": 10.0}  # 600 min → 10 h
    assert r1["conditions"]["feed1"]["moisture_pct"] == 78.2 and r1["conditions"]["press1"]["target_moisture_pct"] == 64.8
    v = {(x["step_key"], x["target_key"]): x for x in r1["values"]}
    assert v[("dry1", "tpc")]["value"] == pytest.approx(6.1) and v[("dry1", "tpc")]["unit"] == "mg GAE/g"  # 610 mg/100 g → 6.1 mg/g
    assert v[("dry1", "tpc")]["basis"] == "건량" and v[("dry1", "moisture")]["value"] == 21.5
    assert v[("sieve1", "sieve_yield")]["value"] == 82.5
    v4 = {(x["step_key"], x["target_key"]): x for x in r4["values"]}
    assert v4[("dry1", "tpc")]["value"] == pytest.approx(4.5) and v4[("dry1", "tpc")]["value_text"] == "< 4.5"
    assert v4[("dry1", "tdf")]["value"] is None and v4[("dry1", "tdf")]["value_text"] == "ND"
    assert r4["note"] == "검출한계 시험"


def test_import_xlsx_and_column_detection(xhome):
    import openpyxl
    from app.experiment import importer, store
    e = store.create_experiment("엑셀", template_id=tpl(EXT_T)["wf_id"])
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["시료명", "에탄올 농도(%)", "추출 온도(℃)", "추출 시간(h)", "추출 수율(%)", "[dry1] 수분 (%)", "비소 (ppm)", "무슨 열"])
    ws.append(["E1", 50, 45, 1.5, 61.2, 7.7, "0.01 미만", "x"])
    buf = io.BytesIO()
    wb.save(buf)
    pv = importer.preview(e["exp_id"], "ext.xlsx", buf.getvalue())
    cols = {c["header"]: c for c in pv["columns"]}
    assert cols["시료명"]["role"] == "label"
    assert (cols["에탄올 농도(%)"]["role"], cols["에탄올 농도(%)"]["key"]) == ("condition", "ethanol_pct")
    assert (cols["추출 시간(h)"]["step_key"], cols["추출 시간(h)"]["key"]) == ("extract1", "time_min")
    assert (cols["추출 수율(%)"]["role"], cols["추출 수율(%)"]["key"]) == ("value", "tpc_extract_yield")
    assert (cols["[dry1] 수분 (%)"]["step_key"], cols["[dry1] 수분 (%)"]["key"]) == ("dry1", "moisture")
    assert cols["무슨 열"]["role"] == "ignore" and pv["issues"]
    # 모르는 대상(비소)은 값으로 지정해도 텍스트 대상으로 남는다 — 지정 안 하면 무시
    r = importer.commit(e["exp_id"], pv["token"], pv["columns"])
    assert r["created"] == 1
    run = store.get_experiment(e["exp_id"])["runs"][0]
    assert run["conditions"]["extract1"] == {"ethanol_pct": 50.0, "temp_c": 45.0, "time_min": 90.0}  # 1.5 h → 90 min
    with pytest.raises(importer.ImportError_, match="만료"):
        importer.commit(e["exp_id"], pv["token"])
    with pytest.raises(importer.ImportError_, match=".xls"):
        importer.read_grid("old.xls", b"x")


def test_export_csv_round_trip(xhome, ha_exp):
    from app.experiment import importer, store
    text = importer.export_csv(ha_exp)
    assert text.startswith("﻿런,날짜,비고")
    assert "[dry1] 열풍 온도 (℃)" in text and "< 4.5" in text and "ND" in text
    e2 = store.create_experiment("왕복", template_id=tpl(HA_T)["wf_id"])
    pv = importer.preview(e2["exp_id"], "x.csv", text.encode("utf-8"))
    assert not pv["errors"]
    importer.commit(e2["exp_id"], pv["token"], pv["columns"])
    a, b = store.get_experiment(ha_exp)["runs"], store.get_experiment(e2["exp_id"])["runs"]
    assert [r["conditions"] for r in a] == [r["conditions"] for r in b]
    # 값과 검출 한계·ND 표기가 같으면 된다(원래 단위 메모 '610 mg GAE/100 g'은 첫 가져오기에만 남는다)
    cens = lambda v: v["value_text"] if v["value"] is None or str(v["value_text"] or "")[:1] in "<>" else None  # noqa: E731
    key = lambda r: sorted((v["step_key"], v["target"], v["value"], cens(v)) for v in r["values"])  # noqa: E731
    assert [key(r) for r in a] == [key(r) for r in b]
    store.delete_experiment(e2["exp_id"])


# ---------------------------------------------------------------- 비교

def test_compare_residuals_and_summary(xhome, ha_exp):
    from app.experiment import sim
    c = sim.compare(ha_exp)
    pairs = [p for r in c["runs"] for p in r["pairs"]]
    m = [p for p in pairs if p["target"] == "moisture"]
    assert len(m) == 4 and all(p["residual"] == pytest.approx(p["measured"] - p["predicted"], abs=1e-3) for p in m)
    cens = next(p for p in pairs if p["run"] == "런 4" and p["target"] == "tpc")
    assert cens.get("residual") is None and "검출 한계" in cens["note"]
    nd = next(p for p in pairs if p["run"] == "런 4" and p["target"] == "tdf")
    assert nd.get("residual") is None
    s = c["summary"]
    assert s["moisture"]["n"] == 4 and s["tpc"]["n"] == 3 and s["sieve_yield"]["n"] == 4
    assert s["moisture"]["rmse"] == pytest.approx(math.sqrt(sum(p["residual"] ** 2 for p in m) / 4), abs=1e-3)
    assert s["sieve_yield"]["with_band"] == 0  # 가정 표 값은 폭이 없어 '폭 안' 판정을 하지 않는다
    assert len(c["parity"]["moisture"]) == 4 and all(e["params"] for e in c["evidence"].values())
    assert c["in_sample"] is False


def test_sensitivity_sweep_with_measured_points(xhome, ha_exp):
    from app.experiment import sim, store
    s = sim.sensitivity(ha_exp, "dry1", "temp_c", "moisture")
    ys = [p[1] for p in s["points"]]
    assert len(s["points"]) == 21 and all(a >= b for a, b in zip(ys, ys[1:]))  # 온도가 오를수록 수분이 준다
    assert sorted(m["x"] for m in s["measured"]) == [50, 60, 70, 80]
    s2 = sim.sensitivity(ha_exp, "dry1", "temp_c", "TPC 잔존율", target_step="store1", n=9)
    assert len(s2["points"]) == 9
    with pytest.raises(store.StoreError, match="뒤여야"):
        sim.sensitivity(ha_exp, "dry1", "temp_c", "moisture", target_step="feed1")
    with pytest.raises(store.StoreError, match="숫자 값이 아니라"):
        sim.sensitivity(ha_exp, "dry1", "method", "moisture")


# ---------------------------------------------------------------- 보정

def test_calibration_preview_apply_uses_experiment_data(xhome, ha_exp):
    from app.experiment import calib, sim
    from app.viz import predict as P
    pv = calib.preview(ha_exp)
    assert pv["applied"] is False and pv["n_usable"] == {"dry": 4, "tpc": 3}
    b, a = pv["before"]["dry"], pv["after"]["dry"]
    assert b["n"] == 1 and b["n_exp"] == 0          # CoA만
    assert a["n"] == 5 and a["n_exp"] == 4 and a["n_coa"] == 1 and "내 실험 4" in a["message"]
    assert a["factor"] != b["factor"] and a["ea"]["applied"] is False  # Ea는 고르기 전에는 문헌 유지
    names = [p["sample"] for p in a["points"]]
    assert "시료 2" in names and "실험 온도 비교 · 런 1" in names
    exp_pt = next(p for p in a["points"] if p["sample"] == "실험 온도 비교 · 런 1")
    assert exp_pt["moist_init"] == pytest.approx(64.8)  # 압착 후 수분 조건 → 건조 전 수분
    assert "residual_lit" in exp_pt and "lit_final" in exp_pt  # 문헌만 → 보정 후를 함께 보인다
    assert pv["after"]["summary"]["moisture"]["rmse"] < pv["before"]["summary"]["moisture"]["rmse"]
    assert pv["after"]["tpc"]["n_exp"] == 3 and any(p["basis"] == "런 안 건조 전후" for p in pv["after"]["tpc"]["points"])
    # 미리보기는 저장하지 않는다
    assert P.calibration_settings("사과박")["experiments"] == []
    before = P.predict("열풍건조", {"temp_c": 70, "time_h": 10, "initial_moisture": 65})
    r = calib.apply(ha_exp, include=True)
    assert r["settings"]["experiments"] == [ha_exp] and r["preview"]["applied"]
    after = P.predict("열풍건조", {"temp_c": 70, "time_h": 10, "initial_moisture": 65})
    mo = after["outputs"][0]
    assert mo["calibration"]["n"] == 5 and mo["value"] != before["outputs"][0]["value"]
    mp = next(p for p in mo["params"] if p["key"] == "cal_dry")
    assert mp["evidence"]["locator"] == "내 DB 측정값(CoA·내 실험)" and mp["evidence"]["n"] == 5
    assert sim.compare(ha_exp)["in_sample"] is True
    calib.apply(ha_exp, include=False)
    assert P.calibration_settings("사과박")["experiments"] == []
    assert P.predict("열풍건조", {"temp_c": 70, "time_h": 10, "initial_moisture": 65})["outputs"][0]["value"] == before["outputs"][0]["value"]


def _synthetic_exp(name, temps, ea_true_kj=40.0, c60=1.3):
    """감귤박(CoA 없음)으로 원료 → 열풍건조 흐름. 알려진 배율·Ea로 만든 건조 후 수분을 넣는다."""
    from app.experiment import store
    from app.viz import predict as P
    steps = [{"type": "feed", "params": {"mass_kg": 10}},
             {"type": "dry", "params": {"method": "열풍건조", "time_h": 4, "air_velocity_ms": 0.9, "thickness_mm": 3, "target_moisture": 8}}]
    e = store.create_experiment(name, steps=steps, byproduct="감귤박")
    ea_lit = P.dry_fit()["ea_j"]
    beta = -(ea_true_kj * 1000 - ea_lit) / P.R_GAS
    for t in temps:
        x0 = P.wb_to_db(75.0)
        xe = P.gab_xe(P.heated_air_aw(t))
        c = c60 * math.exp(beta * (1 / (t + 273.15) - 1 / 333.15))
        k = P.k_dry_lit(t) * c
        mf = P.db_to_wb(xe + (x0 - xe) * math.exp(-k * 4))
        store.add_run(e["exp_id"], conditions={"feed1": {"moisture_pct": 75}, "dry1": {"temp_c": t}},
                      values=[{"step_key": "dry1", "target": "수분", "value": round(mf, 4)}])
    return e["exp_id"]


def test_ea_fit_only_with_three_temperatures(xhome):
    from app.experiment import calib
    from app.viz import predict as P
    two = _synthetic_exp("두 온도", [50, 70])
    pv = calib.preview(two, use_ea_fit=True)
    assert pv["ea_possible"] is False and pv["after"]["dry"]["ea"]["available"] is False
    assert pv["after"]["dry"]["ea"]["applied"] is False and "3개 이상" in pv["after"]["dry"]["ea"]["message"]
    three = _synthetic_exp("세 온도", [50, 70, 90])
    pv = calib.preview(three, use_ea_fit=False)
    ea = pv["after"]["dry"]["ea"]
    assert ea["available"] and not ea["applied"] and ea["ea_kj"] == pytest.approx(40.0, abs=0.05)
    pv = calib.preview(three, use_ea_fit=True)
    d = pv["after"]["dry"]
    assert d["ea"]["applied"] and d["factor"] == pytest.approx(1.3, rel=2e-3) and d["ea"]["rmse_ln"] < 1e-3
    assert all(abs(p["residual"]) < 0.01 for p in d["points"])
    calib.apply(three, include=True, use_ea_fit=True)
    assert P.calibration_settings("감귤박") == {**P.calibration_settings("감귤박"), "experiments": [three], "ea_fit": True}
    # 적용한 모델은 실측 조건을 다시 재현한다(두께·풍속 같음)
    r = P.predict("열풍건조", {"temp_c": 90, "time_h": 4, "initial_moisture": 75}, "감귤박")
    pt = next(p for p in d["points"] if p["temp_c"] == 90)
    assert r["outputs"][0]["value"] == pytest.approx(pt["moist_final"], abs=0.02)
    calib.apply(three, include=False)


def test_apply_refuses_experiment_without_usable_runs(xhome):
    from app.experiment import calib, store
    e = store.create_experiment("빈 실험", template_id=tpl(HA_T)["wf_id"])
    store.add_run(e["exp_id"], values=[{"step_key": "sieve1", "target": "체 통과 수율", "value": 80}])
    with pytest.raises(store.StoreError, match="보정에 쓸 수 있는 런이 없습니다"):
        calib.apply(e["exp_id"])
    pv = calib.preview(e["exp_id"])
    assert pv["runs"][0]["reasons"] and not pv["runs"][0]["usable"]["dry"]


# ---------------------------------------------------------------- 제안

def test_suggestions(xhome, ha_exp):
    from app.experiment import plan, store
    s = plan.suggest(ha_exp)
    assert s["label"] == "제안" and "제안입니다" in s["disclaimer"]
    lo, hi = s["validity"]["temp_range"]
    assert (lo, hi) == (40, 120) and s["validity"]["covered_temps"] == [50, 60, 70, 80]
    assert s["gap_fill"] and all(lo <= g["temp_c"] <= hi and min(abs(g["temp_c"] - c) for c in (50, 60, 70, 80)) >= 7.5
                                 for g in s["gap_fill"])
    assert all(g["predicted"]["moisture"]["value"] is not None for g in s["gap_fill"])
    f = s["factorial"][0]
    assert f["design"].startswith("3×2") and len(f["rows"]) == 6
    two = _synthetic_exp("제안용 두 온도", [50, 70])
    assert any("1개 더" in n for n in plan.suggest(two)["notes"])
    ext = store.create_experiment("추출 제안", template_id=tpl(EXT_T)["wf_id"])
    fx = [x for x in plan.suggest(ext["exp_id"])["factorial"] if x["step_key"] == "extract1"][0]
    assert len(fx["rows"]) == 6 and fx["rows"][0]["predicted"]["tpc_extract_yield"]
    saved = plan.save_plan(ext["exp_id"], fx)
    runs = plan.add_planned_runs(ext["exp_id"], fx)
    assert saved["plan_id"] and len(runs) == 6 and store.get_experiment(ext["exp_id"])["plan_id"] == saved["plan_id"]


# ---------------------------------------------------------------- API·개인정보

def test_api_round_trip(client, xhome):
    assert {s["type"] for s in client.get("/api/exp/steps").json()["steps"]} == {"feed", "wash", "press", "mill", "dry", "sieve", "extract", "store"}
    t = client.get("/api/exp/templates").json()["templates"]
    e = client.post("/api/exp/experiments", json={"name": "API 실험", "template_id": t[1]["wf_id"], "confidentiality": "기밀"}).json()
    eid = e["exp_id"]
    assert e["confidentiality"] == "기밀"
    r = client.post(f"/api/exp/flows/{e['wf_id']}/ops", json={"op": "move", "key": "mill1", "delta": -1})
    assert r.status_code == 200 and [s["key"] for s in r.json()["steps"]][2] == "mill1"
    up = client.post(f"/api/exp/experiments/{eid}/import/preview", files={"file": ("r.csv", CSV.encode("utf-8"), "text/csv")})
    assert up.status_code == 200 and up.json()["n_rows"] == 4
    cm = client.post(f"/api/exp/experiments/{eid}/import/commit", json={"token": up.json()["token"], "columns": up.json()["columns"]})
    assert cm.json()["created"] == 4
    run = client.get(f"/api/exp/experiments/{eid}").json()["runs"][0]
    r = client.put(f"/api/exp/runs/{run['xrun_id']}", json={"conditions": {"dry1": {"temp_c": 55}}})
    assert r.status_code == 200 and r.json()["conditions"] == {"dry1": {"temp_c": 55.0}}
    bad = client.put(f"/api/exp/runs/{run['xrun_id']}", json={"conditions": {"dry1": {"temp_c": 500}}})
    assert bad.status_code == 400 and "사이로 넣으세요" in bad.json()["detail"]
    bad = client.post(f"/api/exp/experiments/{eid}/runs", json={"values": [{"step_key": "nope", "target": "수분", "value": 1}]})
    assert bad.status_code == 400 and "흐름에 없습니다" in bad.json()["detail"]
    bad = client.post(f"/api/exp/experiments/{eid}/runs", json={"values": [{"step_key": "dry1", "target": "수분", "value": "많음"}]})
    assert bad.status_code == 400 and "ND" in bad.json()["detail"]
    assert client.get("/api/exp/experiments/0000").status_code == 404
    ex = client.get(f"/api/exp/experiments/{eid}/export.csv")
    assert ex.status_code == 200 and "text/csv" in ex.headers["content-type"]
    sm = client.post("/api/exp/simulate", json={"wf_id": e["wf_id"]})
    assert sm.status_code == 200 and sm.json()["summary"]["text"].startswith("이 모의의 근거")
    c = client.post(f"/api/exp/experiments/{eid}/compare", json={"save_predicted": True})
    assert c.status_code == 200 and c.json()["saved_predicted"]
    kinds = {v["kind"] for v in client.get(f"/api/exp/experiments/{eid}").json()["runs"][1]["values"]}
    assert kinds == {"measured", "predicted"}
    s = client.post(f"/api/exp/experiments/{eid}/sensitivity", json={"step_key": "dry1", "param": "temp_c", "target": "moisture", "n": 7})
    assert s.status_code == 200 and len(s.json()["points"]) == 7
    assert client.post(f"/api/exp/experiments/{eid}/calibrate/preview", json={}).status_code == 200
    assert client.get(f"/api/exp/experiments/{eid}/suggest").json()["label"] == "제안"
    assert client.get(f"/api/exp/experiments/{eid}/params").json()["params"]
    assert client.delete(f"/api/exp/experiments/{eid}").json() == {"ok": True}


def test_privacy_no_identifiers_in_outputs(client, xhome, ha_exp):
    from app.experiment import store
    store.update_run(store.get_experiment(ha_exp)["runs"][0]["xrun_id"], label="A-50")
    dumps = [json.dumps(x, ensure_ascii=False) for x in (
        client.post(f"/api/exp/experiments/{ha_exp}/compare", json={}).json(),
        client.post(f"/api/exp/experiments/{ha_exp}/calibrate/preview", json={"use_ea_fit": True}).json(),
        client.post("/api/exp/simulate", json={"wf_id": store.get_experiment(ha_exp)["wf_id"]}).json(),
        client.get(f"/api/exp/experiments/{ha_exp}/suggest").json(),
        client.post("/api/viz/predict", json={"method": "열풍건조", "inputs": {}}).json(),
    )]
    for d in dumps:
        for s in SECRETS:
            assert s not in d
    # 보정 근거에는 런 이름(사용자 라벨)이 아니라 '실험 <이름> · 런 n'만
    cal = json.loads(dumps[1])
    assert all("A-50" not in p["sample"] for p in cal["after"]["dry"]["points"])
