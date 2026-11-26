"""빈틈 메우기: 실험 범주 조건(산·용매) · 측정 수율 → 통계 · 교호작용·2차항 모형(재현 포함) · 영어 가정 점검 ·
파싱 작업 상태 저장(다시 켜면 '중단됨') · 배운 동의어 → mine.ttl · kordoc 한글 PDF(cMap)."""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import time
import zipfile

import numpy as np
import pytest

from app.experiment import importer, sim, steps as S, store, units as U
from app.stats import analysis as A, data as D, export as E, report as R

HANGUL = re.compile(r"[가-힣]")


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    from app import db, thesaurus
    h = tmp_path_factory.mktemp("gaps_home")
    mp = pytest.MonkeyPatch()
    mp.setenv("BYORBIT_HOME", str(h))
    thesaurus.invalidate()
    db.init(seed=True)
    yield h
    mp.undo()
    thesaurus.invalidate()


def _extract_flow():
    return next(t for t in store.list_templates() if "추출" in t["name"])


# ---------------------------------------------------------------- 1. 범주 조건(산·용매)

def test_extract_has_free_choice_specs():
    specs = {s["key"]: s for s in S.specs_for("extract")}
    for k in ("acid", "solvent"):
        assert specs[k]["type"] == "select" and specs[k]["free"] and specs[k]["optional"] and specs[k]["default"] is None
    assert "구연산" in specs["acid"]["options"] and "염산" in specs["acid"]["options"] and "질산" in specs["acid"]["options"]
    assert "물" in specs["solvent"]["options"] and "에탄올" in specs["solvent"]["options"]
    p = S.clean_params("extract", {"acid": "HCl", "solvent": " water "})
    assert p["acid"] == "염산" and p["solvent"] == "물"
    assert S.clean_params("extract", {"acid": "포도산(직접)"})["acid"] == "포도산(직접)"   # 직접 입력
    assert S.clean_params("extract", {})["acid"] is None


def test_categorical_is_recorded_not_modelled():
    steps = [dict(s, params=dict(s["params"])) for s in _extract_flow_steps()]
    base = sim.run_flow(steps)
    ext = next(x for x in steps if x["type"] == "extract")
    ext["params"].update(acid="염산", solvent="메탄올")
    withc = sim.run_flow(steps)
    k = ext["key"]
    y0 = next(r for r in base["steps"] if r["key"] == k)["outputs"]["tpc_extract_yield"]["value"]
    r1 = next(r for r in withc["steps"] if r["key"] == k)
    assert r1["outputs"]["tpc_extract_yield"]["value"] == y0        # 근거 없는 효과를 만들지 않는다
    txt = " ".join(w["text"] for w in r1["warnings"])
    assert "산 종류 '염산'" in txt and "기록" in txt and "메탄올" in txt


def _extract_flow_steps():
    return [dict(s) for s in S_TEMPLATE()]


def S_TEMPLATE():  # noqa: N802
    return next(t for t in store.TEMPLATES if "추출" in t["name"])["steps"]


def test_flow_and_run_conditions_and_stats(home):
    e = store.create_experiment("산 비교", template_id=_extract_flow()["wf_id"])
    store.flow_op(e["wf_id"], "params", key="extract1", params={"acid": "citric acid"})
    f = store.get_flow(e["wf_id"])
    assert next(s for s in f["steps"] if s["key"] == "extract1")["params"]["acid"] == "구연산"
    rng = np.random.default_rng(3)
    for i, (acid, eff) in enumerate([("구연산", 0), ("HCl", 1.6)] * 6):
        T = (60, 70, 80)[i % 3]
        cond = {"extract1": {"temp_c": T, "time_min": 60 + 30 * ((i // 2) % 2)}}
        note = None
        if i < 10:
            cond["extract1"]["acid"] = acid
        else:
            note = f"산={acid}"   # 예전 방식(비고 꼬리표) — 조건 칸이 비면 이것을 쓴다
        store.add_run(e["exp_id"], label=f"R{i}", conditions=cond, note=note,
                      values=[{"step_key": "extract1", "target": "펙틴 수율", "value": round(10 + 0.1 * T + eff + rng.normal(0, .3), 2), "unit": "%"}])
    runs = store.list_runs(e["exp_id"])
    assert runs[1]["conditions"]["extract1"]["acid"] == "염산"
    assert runs[0]["values"][0]["target_key"] == "product_yield"
    ds = D.from_experiment(e["exp_id"])
    cb = {v["name"]: v for v in ds.codebook}
    assert cb["acid"]["type"] == "categorical" and [l["value"] for l in cb["acid"]["levels"]] == ["citric", "HCl"]
    assert cb["acid"]["levels"][1]["label_ko"] == "염산" and cb["acid"]["label_en"] == "Acid type"
    assert "product_yield" in ds.df.columns and ds.df["acid"].notna().all()
    assert list(ds.df["acid"][10:]) == ["citric", "HCl"]                 # 꼬리표로 채움
    assert any("꼬리표" in w for w in ds.warnings)
    assert not any(c.startswith("acid_") for c in ds.df.columns)         # 꼬리표가 따로 열을 만들지 않음
    sp = D.suggest_spec(ds)
    assert sp["outcome"] == "product_yield" and sp["group"] == "acid"
    r = A.run({"kind": "experiment", "exp_id": e["exp_id"]})
    assert r.core["groups"]["levels"] == ["citric", "HCl"]
    # 내보내기 CSV → 같은 열 이름으로 다시 가져오면 조건 칸으로 읽힌다
    out = importer.export_csv(e["exp_id"])
    assert "[extract1] 산 종류" in out.splitlines()[0]
    steps = store.get_flow(e["wf_id"])["steps"]
    col = importer.detect_column("[extract1] 산 종류", steps)
    assert col["role"] == "condition" and col["key"] == "acid"


def test_import_recognizes_acid_solvent_and_yield(home):
    e = store.create_experiment("가져오기", template_id=_extract_flow()["wf_id"])
    csv_text = "런,산,용매 종류,추출 온도(℃),수율(%)\nA1,구연산,물,70,12.1\nA2,HCl,water,80,14.2\nA3,옥살산,에탄올 수용액,90,13.0\n"
    pv = importer.preview(e["exp_id"], "a.csv", csv_text.encode("utf-8"))
    by = {c["header"]: c for c in pv["columns"]}
    assert (by["산"]["role"], by["산"]["key"]) == ("condition", "acid")
    assert (by["용매 종류"]["role"], by["용매 종류"]["key"]) == ("condition", "solvent")
    assert (by["수율(%)"]["role"], by["수율(%)"]["key"]) == ("value", "product_yield")
    res = importer.commit(e["exp_id"], pv["token"], pv["columns"])
    assert res["created"] == 3 and not res["errors"]
    runs = store.list_runs(e["exp_id"])
    assert [r["conditions"]["extract1"]["acid"] for r in runs] == ["구연산", "염산", "옥살산"]
    assert [r["conditions"]["extract1"]["solvent"] for r in runs] == ["물", "물", "에탄올 수용액"]


def test_canon_target_yield():
    assert U.canon_target("수율") == "product_yield" and U.canon_target("펙틴 수율") == "product_yield"
    assert U.canon_target("체 통과 수율") == "sieve_yield" and U.canon_target("추출 수율") == "tpc_extract_yield"


# ---------------------------------------------------------------- 3. 모형 선택 항

@pytest.fixture(scope="module")
def rix():
    return A.run({"kind": "demo", "levels": 3}, {"interactions": [["acid", "temp_c"]], "quadratic": ["time_min"], "xvar": "time_min"})


def test_interaction_and_quadratic_design(rix):
    reg = rix.core["regression"]
    assert reg["columns"][-3:] == ["time_min^2", "temp_c:acid[HCl]", "temp_c:acid[nitric]"]
    assert rix.spec["interactions"] == [["temp_c", "acid"]] and rix.spec["xvar"] == "time_min"
    # 손 계산: 중심화한 곱항으로 최소제곱
    d = rix.ds.df.loc[rix.core["used_index"]]
    t, m = d.temp_c.to_numpy(float), d.time_min.to_numpy(float)
    X = np.column_stack([np.ones(len(d)), t, m, d.acid == "HCl", d.acid == "nitric", (m - m.mean()) ** 2,
                         (t - t.mean()) * (d.acid == "HCl"), (t - t.mean()) * (d.acid == "nitric")]).astype(float)
    b = np.linalg.lstsq(X, d.yield_pct.to_numpy(float), rcond=None)[0]
    assert np.allclose(b, [c["B"] for c in reg["coef"]], atol=1e-9)
    assert any(x["term"] == "temp_c:acid" and x["df1"] == 2 for x in reg["term_tests"])
    lin = {x["var"]: x for x in reg["linearity"]}
    assert lin["time_min"].get("in_model") and lin["temp_c"]["testable"]
    s = R.interpretation(rix, "ko")
    assert len(s) == 3 and "교호작용" in s[1] and "2차항" in s[1]
    assert "×" in R.table1_html(rix, "ko") and "중심화" in R.table1_html(rix, "ko")
    assert R.figure1(rix, "en", "single", "png")[:4] == b"\x89PNG"


def test_default_model_unchanged():
    r = A.run({"kind": "demo", "levels": 2})
    assert r.core["regression"]["columns"] == ["(Intercept)", "temp_c", "time_min", "acid[HCl]"]
    assert r.spec["interactions"] == [] and r.spec["quadratic"] == []


def test_model_term_errors():
    with pytest.raises(A.StatsError, match="설명 변수에 없습니다"):
        A.run({"kind": "demo"}, {"interactions": [["temp_c", "nope"]]})
    with pytest.raises(A.StatsError, match="연속 설명 변수"):
        A.run({"kind": "demo"}, {"quadratic": ["acid"]})
    with pytest.raises(A.StatsError, match="가로축"):
        A.run({"kind": "demo"}, {"xvar": "acid"})


def test_exported_analysis_py_reproduces_interaction_model(rix, tmp_path):
    zipfile.ZipFile(io.BytesIO(E.reproduce_zip(rix))).extractall(tmp_path)
    p = subprocess.run([sys.executable, "-I", "analysis.py"], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert p.returncode == 0, p.stderr
    res = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    for a, b in zip(res["regression"]["coef"], rix.core["regression"]["coef"], strict=True):
        assert a["term"] == b["term"] and abs(a["B"] - b["B"]) < 1e-8 and abs(a["p"] - b["p"]) < 1e-8
    rs = (tmp_path / "analysis.R").read_text(encoding="utf-8")
    assert "m_temp_c <- mean(d$temp_c)" in rs and "add_terms(d)" in rs and "sq_time_min" in rs
    assert '(z$temp_c - m_temp_c) * (z$acid == "HCl")' in rs and "nd <- add_terms(nd)" in rs
    assert re.search(r"lm\(yield_pct ~ temp_c \+ time_min \+ acid \+ sq_time_min \+ ix1_temp_c_acid \+ ix2_temp_c_acid", rs)
    do = (tmp_path / "analysis.do").read_text(encoding="utf-8")
    assert "generate double ix1_temp_c_acid = (temp_c - c_temp_c) * (acid_f == 2)" in do
    assert "regress yield_pct temp_c time_min ib1.acid_f sq_time_min ix1_temp_c_acid ix2_temp_c_acid" in do
    assert "ix1_temp_c_acid" in (tmp_path / "README.txt").read_text(encoding="utf-8")


def test_assumption_cards_english(rix):
    for c in rix.out["assumptions"]:
        for k in ("test_en", "stat_en", "threshold_en", "text_en", "name_en"):
            assert not HANGUL.search(c[k] or ""), (c["key"], k, c[k])
    html = R.assumptions_html(rix, "en", standalone=False)
    assert "Criterion" in html and "n per coefficient" in html


# ---------------------------------------------------------------- 4. 파싱 작업 상태

def test_parse_jobs_persist_and_interrupted(home):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import config, routes_parse as RP
    f = config.path("config", "parse_jobs.json")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps([{"job_id": "old1", "kind": "parse", "status": "running", "started": time.time() - 60,
                              "doc_id": "D1", "tool": "pymupdf", "boot": "previous-run"},
                             {"job_id": "old2", "kind": "parse", "status": "done", "started": time.time() - 90,
                              "finished": time.time() - 80, "doc_id": "D1", "tool": "pdfplumber", "boot": "previous-run"}]),
                 encoding="utf-8")
    RP._loaded.discard(str(f))
    app = FastAPI()
    app.include_router(RP.router)
    c = TestClient(app)
    j = c.get("/api/parse/jobs/old1").json()
    assert j["status"] == "interrupted" and "다시 실행" in j["error"] and "_home" not in j
    lst = c.get("/api/parse/docs/D1/jobs").json()["jobs"]
    assert [x["job_id"] for x in lst] == ["old1", "old2"]
    saved = json.loads(f.read_text(encoding="utf-8"))
    assert next(x for x in saved if x["job_id"] == "old1")["status"] == "interrupted"
    # 새 작업도 파일에 남는다
    job = RP._start("parse", lambda: {"status": "ok"}, doc_id="D2", tool="text")
    def written():
        try:
            return any(x["job_id"] == job["job_id"] and x["status"] == "done" and x["boot"] == RP.BOOT
                       for x in json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            return False
    for _ in range(100):
        if written():
            break
        time.sleep(0.02)
    assert written()


# ---------------------------------------------------------------- 5. 배운 동의어 → mine.ttl

def test_learned_synonym_in_mine_ttl(home):
    from app import config, db, labeling
    cid = db.one("SELECT concept_id FROM concept WHERE origin='seed' AND pref_label_ko='사과박'")["concept_id"]
    r = labeling.learn_synonym(cid, "애플 포미스 찌꺼기")
    ttl = config.path("ontology", "mine.ttl").read_text(encoding="utf-8")
    assert 'skos:altLabel "애플 포미스 찌꺼기"' in ttl and ttl.startswith("@prefix byo:")
    new = labeling.add_concept("시험용 새 부산물", "부산물")
    ttl = config.path("ontology", "mine.ttl").read_text(encoding="utf-8")
    assert '"시험용 새 부산물"' in ttl and ttl.count('"애플 포미스 찌꺼기"') == 1
    labeling.remove_synonym(r["label_id"])
    ttl = config.path("ontology", "mine.ttl").read_text(encoding="utf-8")
    assert "애플 포미스 찌꺼기" not in ttl and '"시험용 새 부산물"' in ttl
    assert config.path("ontology", "mine.ttl.bak").exists() and new["ok"]
    try:   # Turtle로 읽히는지(rdflib가 있으면)
        import rdflib
        rdflib.Graph().parse(data=ttl, format="turtle")
    except ImportError:
        pass


# ---------------------------------------------------------------- 6. kordoc 한글 PDF

def test_kordoc_korean_pdf(tmp_path):
    from app.ingest.parser_tools import kordoc_tool as K
    from app.sample_files import make_pdf
    entry, _ = K.find_kordoc()
    if not (K.node_exe() and entry and K.has_pdfjs(entry)):
        pytest.skip("kordoc + pdfjs-dist가 없음(BYORBIT_KORDOC_DIR로 지정하면 시험)")
    out = K.TOOL.parse(make_pdf(tmp_path / "s.pdf"), {})
    text = " ".join(b.get("text") or "" for b in out["blocks"])
    assert "사과박" in text and "건조" in text
