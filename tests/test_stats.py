"""통계 분석: 회귀(손 계산 최소제곱과 비교) · Welch t(scipy·손 공식) · 가정 점검 값 · 예시 데이터 고정 · 3수준(ANOVA+Holm) ·
결측(목록별 삭제) · 실험 → 정돈 표 · 내보낸 analysis.py 실제 실행 재현 · DOCX·그림 형식 · 해석 세 문장 · API."""
from __future__ import annotations

import io
import json
import math
import re
import subprocess
import sys
import zipfile

import numpy as np
import pytest
from scipy import stats as ss

from app.stats import analysis as A, core, data as D, export as E, fmt as F, report as R


@pytest.fixture(scope="module")
def r2():
    return A.run({"kind": "demo", "levels": 2})


@pytest.fixture(scope="module")
def r3():
    return A.run({"kind": "demo", "levels": 3})


def _sentences(text: str) -> int:
    """문장 끝: 마침표·물음표·느낌표 뒤에 공백이나 끝 (소수점 '.034'는 세지 않음)."""
    return len(re.findall(r"[.!?](?=\s|$)", text.strip()))


# ---------------------------------------------------------------- 예시 데이터

def test_demo_deterministic_and_labelled_fake():
    a, b = D.demo(2), D.demo(2)
    assert a.df.equals(b.df)
    assert len(a.df) == 54 and a.df["yield_pct"].isna().sum() == 1
    assert a.is_demo and any("가짜" in w for w in a.warnings)
    assert set(a.df["acid"]) == {"citric", "HCl"}
    assert set(D.demo(3).df["acid"]) == {"citric", "HCl", "nitric"}
    for v in a.codebook:
        assert D.NAME_RE.match(v["name"]), v["name"]


# ---------------------------------------------------------------- 회귀

def test_regression_matches_hand_least_squares(r2):
    d = r2.ds.df.dropna(subset=["yield_pct"])
    X = np.column_stack([np.ones(len(d)), d.temp_c, d.time_min, (d.acid == "HCl").astype(float)])
    y = d.yield_pct.to_numpy()
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    s2 = resid @ resid / (n - k)
    se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    coef = r2.core["regression"]["coef"]
    assert [c["term"] for c in coef] == ["(Intercept)", "temp_c", "time_min", "acid[HCl]"]
    for c, b, s in zip(coef, beta, se):
        assert c["B"] == pytest.approx(b, abs=1e-10)
        assert c["SE"] == pytest.approx(s, abs=1e-10)
        t = b / s
        assert c["p"] == pytest.approx(2 * ss.t.sf(abs(t), n - k), abs=1e-12)
        tc = ss.t.ppf(0.975, n - k)
        assert c["ci"] == pytest.approx([b - tc * s, b + tc * s], abs=1e-10)
    fit = r2.core["regression"]["fit"]
    r2v = 1 - resid @ resid / ((y - y.mean()) @ (y - y.mean()))
    assert fit["r2"] == pytest.approx(r2v, abs=1e-12) and fit["n"] == 53
    assert fit["rmse"] == pytest.approx(math.sqrt(s2), abs=1e-12)
    # 표준화 β = B · SD(x)/SD(y), 연속 변수만
    assert coef[1]["beta"] == pytest.approx(beta[1] * d.temp_c.std(ddof=1) / d.yield_pct.std(ddof=1), abs=1e-12)
    assert coef[3]["beta"] is None
    # HC3 손 계산
    h = np.einsum("ij,jk,ik->i", X, np.linalg.inv(X.T @ X), X)
    meat = (X * (resid / (1 - h))[:, None]).T @ (X * (resid / (1 - h))[:, None])
    V = np.linalg.inv(X.T @ X) @ meat @ np.linalg.inv(X.T @ X)
    assert [c["robust"]["SE"] for c in coef] == pytest.approx(np.sqrt(np.diag(V)), abs=1e-10)


def test_assumption_values_present_and_sane(r2):
    reg = r2.core["regression"]
    assert 0 < reg["shapiro"]["W"] <= 1 and 0 <= reg["shapiro"]["p"] <= 1
    assert reg["bp"]["df"] == 3 and reg["bp"]["LM"] >= 0 and 0 <= reg["bp"]["p"] <= 1
    for t, v in reg["gvif"].items():
        assert v["gvif"] >= 1 - 1e-9 and v["vif_equiv"] < 1.1   # 균형 설계라 거의 1
    assert len(reg["cooks"]) == 53 and all(c >= 0 for c in reg["cooks"])
    g = r2.core["groups"]
    lev = ss.levene(*[r2.ds.df.dropna(subset=["yield_pct"]).query("acid == @x").yield_pct for x in ("citric", "HCl")], center="median")
    assert g["levene"]["F"] == pytest.approx(lev.statistic) and g["levene"]["p"] == pytest.approx(lev.pvalue)
    keys = {c["key"]: c for c in r2.out["assumptions"]}
    for k in ("normality", "homoscedasticity", "vif", "influence", "linearity", "independence", "sample_size", "group_n",
              "group_normality", "levene"):
        assert k in keys, k
        c = keys[k]
        assert c["status"] in ("pass", "warn", "fail", "info") and c["threshold"] and c["text_ko"] and c["text_en"]
    assert keys["independence"]["status"] in ("info", "warn")    # 자료로 증명할 수 없음
    assert "n = 53" in keys["normality"]["stat"]
    # 영향점은 런 이름으로
    assert keys["influence"]["status"] == "warn" and "HCL-" in keys["influence"]["text_ko"]


def test_low_power_note_on_small_n():
    df = D.demo(2).df.iloc[::6].reset_index(drop=True)   # 9런
    ds = D.Dataset(df=df, codebook=D.demo(2).codebook, source={"kind": "x"}, title_ko="작은", title_en="small")
    spec = A.resolve_spec(ds, None)
    c = core.analyze(ds.df, {**spec, "categorical": [{"name": "acid", "reference": "citric"}]})
    checks = {x["key"]: x for x in A.assumptions(ds, spec, c)}
    if checks["normality"]["status"] == "pass":
        assert "검정력" in checks["normality"]["text_ko"]
    assert checks["sample_size"]["status"] in ("warn", "fail")


# ---------------------------------------------------------------- 집단 비교

def test_welch_t_matches_scipy_and_hand(r2):
    d = r2.ds.df.dropna(subset=["yield_pct"])
    a, b = d[d.acid == "HCl"].yield_pct.to_numpy(), d[d.acid == "citric"].yield_pct.to_numpy()
    w = r2.core["groups"]["welch"]
    ref = ss.ttest_ind(a, b, equal_var=False)
    assert w["t"] == pytest.approx(ref.statistic, abs=1e-12) and w["p"] == pytest.approx(ref.pvalue, abs=1e-12)
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    df_hand = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1))
    assert w["df"] == pytest.approx(df_hand, abs=1e-10)
    assert w["t"] == pytest.approx((a.mean() - b.mean()) / math.sqrt(va + vb), abs=1e-12)
    assert w["diff"] == pytest.approx(a.mean() - b.mean())
    tc = ss.t.ppf(0.975, df_hand)
    assert w["ci"] == pytest.approx([w["diff"] - tc * math.sqrt(va + vb), w["diff"] + tc * math.sqrt(va + vb)])
    sp = math.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
    assert w["cohen_d"] == pytest.approx((a.mean() - b.mean()) / sp)
    assert w["hedges_g"] == pytest.approx(w["cohen_d"] * (1 - 3 / (4 * (len(a) + len(b)) - 9)))
    st = r2.core["groups"]["student"]
    assert st["df"] == len(a) + len(b) - 2 and st["p"] == pytest.approx(ss.ttest_ind(a, b).pvalue)
    assert r2.core["groups"]["primary"] == "welch"
    mw = ss.mannwhitneyu(a, b, alternative="two-sided", method="asymptotic")
    assert r2.core["groups"]["mann_whitney"]["p"] == pytest.approx(mw.pvalue)


def test_three_levels_anova_and_holm(r3):
    g = r3.core["groups"]
    assert g["kind"] == "anova" and len(g["pairwise"]) == 3
    d = r3.ds.df.dropna(subset=["yield_pct"])
    ys = [d[d.acid == x].yield_pct.to_numpy() for x in ("citric", "HCl", "nitric")]
    assert g["anova"]["F"] == pytest.approx(ss.f_oneway(*ys).statistic)
    # Holm 손 계산
    ps = [p["p"] for p in g["pairwise"]]
    order = np.argsort(ps)
    m, run, adj = len(ps), 0.0, [0.0] * len(ps)
    for i, j in enumerate(order):
        run = max(run, min(1.0, (m - i) * ps[j]))
        adj[j] = run
    assert [p["p_holm"] for p in g["pairwise"]] == pytest.approx(adj)
    for p in g["pairwise"]:  # 쌍별 Welch
        assert p["p"] == pytest.approx(ss.ttest_ind(d[d.acid == p["a"]].yield_pct, d[d.acid == p["b"]].yield_pct, equal_var=False).pvalue)
    assert g["welch_anova"]["df2"] < 77    # Welch df는 정수가 아님
    assert r3.out["t_test_note"]["ko"]
    assert any(t["term"] == "acid" and t["df1"] == 2 for t in r3.core["regression"]["term_tests"])


def test_missing_listwise_deletion_reported(r2):
    assert r2.core["n_total"] == 54 and r2.core["n_used"] == 53
    assert r2.out["dataset"]["dropped"] == [{"run": "CIT-90-120-r3", "reasons": {"yield_pct": "시료 유실(예시)"}}]
    assert "1개 제외" in r2.out["methods"]["ko"]


def test_errors_give_direction():
    df = D.demo(2).df
    one = df[df.acid == "citric"].reset_index(drop=True)
    ds = D.Dataset(df=one, codebook=D.demo(2).codebook, source={}, title_ko="x", title_en="x")
    with pytest.raises(A.StatsError, match="1개뿐이라.*t검정을 할 수 없습니다 — 두 가지 이상"):
        A._precheck(ds, A.resolve_spec(ds, {"continuous": ["temp_c", "time_min"]}))
    with pytest.raises(A.StatsError, match="결과 변수"):
        A.run({"kind": "demo"}, {"outcome": "acid"})
    with pytest.raises(A.StatsError, match="기준 수준"):
        A.run({"kind": "demo"}, {"categorical": [{"name": "acid", "reference": "sulfuric"}]})


# ---------------------------------------------------------------- 해석·표·그림

def test_interpretation_exactly_three_sentences_with_numbers(r2, r3):
    for r in (r2, r3):
        for lang in ("ko", "en"):
            s = r.out["interpretation"][lang]
            assert len(s) == 3
            for x in s:
                assert _sentences(x) == 1, x
            assert _sentences(" ".join(s)) == 3
    fit = r2.core["regression"]["fit"]
    ko, en = r2.out["interpretation"]["ko"], r2.out["interpretation"]["en"]
    assert f"F(3, 49) = {fit['F']:.2f}" in ko[0] and "n = 53" in en[0]
    assert "R² = .73" in en[0] and "R² = 0.73" in ko[0]          # 영어 APA 0 생략, 한국어 0
    temp = r2.core["regression"]["coef"][1]
    assert f"B = {temp['B']:.3f}" in ko[1] and "p < .001" in en[1]
    w = r2.core["groups"]["welch"]
    assert f"t({w['df']:.1f}) = {w['t']:.2f}" in en[2] and "Hedges' g" in ko[2]
    assert "citric acid" in en[2]       # 문장 가운데 소문자


def test_format_helpers():
    assert F.p_val(0.0004) == "< .001" and F.p_val(0.0004, True) == "< 0.001"
    assert F.p_val(0.0497) == ".0497" and F.p_val(0.034) == ".034" and F.p_val(0.9996) == "> .999"
    assert F.n(-0.25, 2) == "−0.25" and F.bounded(0.73, 2) == ".73" and F.bounded(-0.05, 2) == "−.05"
    assert F.dec_for(0.012) == 3 and F.dec_for(0.25) == 2 and F.dec_for(1.3) == 2
    assert F.w("산 종류", "을") == "산 종류를" and F.w("펙틴 수율", "을") == "펙틴 수율을" and F.w("온도", "로") == "온도로"


def test_table_formats(r2, r3):
    from docx import Document
    for r in (r2, r3):
        doc = Document(io.BytesIO(R.table1_docx(r, "ko")))
        assert len(doc.tables) == 1
        text = "\n".join(c.text for row in doc.tables[0].rows for c in row.cells)
        assert "추출 온도" in text and "염산" in text and "± " in text
        assert R.table1_model(r, "en")["panels"][0]["header"] == ["Predictor", "B", "SE", "β", "t", "p", "95% CI"]
        tex = R.table1_latex(r, "en")
        assert "\\toprule" in tex and "\\bottomrule" in tex and "\\midrule" in tex
        assert "| Predictor |" in R.table1_markdown(r, "en")
        assert R.table1_csv(r, "ko").startswith("﻿")
        html = R.table1_html(r, "en", standalone=True)
        assert "<table>" in html and "Simulated demo data" in html
    t3 = R.table1_model(r3, "en")
    assert t3["panels"][1]["header"][4] == "p (Holm)" and any("−" in row["cells"][0] for row in t3["panels"][1]["rows"])


def test_figures_png_svg_pdf(r2, r3):
    for r in (r2, r3):
        png = R.figure1(r, "ko", "double", "png")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        w = int.from_bytes(png[16:20], "big")
        assert 175 / 25.4 * 300 * 0.85 < w < 175 / 25.4 * 300 * 1.1    # 약 2067 px (300 dpi, 175 mm)
        assert R.figure1(r, "en", "single", "svg").lstrip()[:5] in (b"<?xml", b"<svg ")
        assert R.figure1(r, "en", "single", "pdf")[:4] == b"%PDF"
        assert R.diagnostics(r, "ko", "png")[:4] == b"\x89PNG"
    single = R.figure1(r2, "en", "single", "png")
    assert int.from_bytes(single[16:20], "big") < 85 / 25.4 * 300 * 1.1
    assert "Simulated demo data" in r2.out["caption"]["en"] and "Welch t(" in r2.out["caption"]["en"]


def test_assumption_report_exports(r2):
    from docx import Document
    doc = Document(io.BytesIO(R.assumptions_docx(r2, "ko")))
    assert len(doc.tables) == 1 and len(doc.inline_shapes) == 1
    assert "Shapiro–Wilk" in R.assumptions_html(r2, "en")


# ---------------------------------------------------------------- 재현 패키지

@pytest.mark.parametrize("levels", [2, 3])
def test_exported_analysis_py_reproduces_app(levels, tmp_path):
    r = A.run({"kind": "demo", "levels": levels})
    zipfile.ZipFile(io.BytesIO(E.reproduce_zip(r))).extractall(tmp_path)
    assert {"data.csv", "codebook.csv", "analysis.py", "analysis.R", "analysis.do", "README.txt", "app_results.json"} <= {p.name for p in tmp_path.iterdir()}
    raw = (tmp_path / "data.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and raw[3:].split(b"\n")[0].isascii()
    p = subprocess.run([sys.executable, "-I", "analysis.py"], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert p.returncode == 0, p.stderr
    res = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    for a, b in zip(res["regression"]["coef"], r.core["regression"]["coef"]):
        assert a["term"] == b["term"]
        assert abs(a["B"] - b["B"]) < 1e-8 and abs(a["p"] - b["p"]) < 1e-8 and abs(a["robust"]["SE"] - b["robust"]["SE"]) < 1e-8
    g1, g2 = res["groups"], r.core["groups"]
    if levels == 2:
        assert abs(g1["welch"]["p"] - g2["welch"]["p"]) < 1e-8 and abs(g1["welch"]["t"] - g2["welch"]["t"]) < 1e-8
    else:
        assert [x["p_holm"] for x in g1["pairwise"]] == pytest.approx([x["p_holm"] for x in g2["pairwise"]], abs=1e-8)
    rs = (tmp_path / "analysis.R").read_text(encoding="utf-8")
    assert "lm(yield_pct ~ temp_c + time_min + acid" in rs and 'levels = c("citric"' in rs and "shapiro.test" in rs
    assert ("t.test(" in rs) if levels == 2 else ('p.adjust.method = "holm"' in rs)
    do = (tmp_path / "analysis.do").read_text(encoding="utf-8")
    assert "regress yield_pct temp_c time_min ib1.acid_f" in do and "estat hettest" in do and "swilk r" in do
    assert ("ttest yield_pct, by(acid_f) unequal" in do) if levels == 2 else ("mata:" in do)
    assert "실행해 보지 않았습니다" in rs and "실행해 보지 않았습니다" in do


def test_bundle_contents(r2):
    names = set(zipfile.ZipFile(io.BytesIO(E.bundle_zip(r2, "ko"))).namelist())
    for n in ("Table1.docx", "Table1.html", "Table1.csv", "Table1.tex", "Figure1.png", "Figure1.svg", "Figure1.pdf", "caption.txt",
              "interpretation_ko.txt", "interpretation_en.txt", "assumptions.docx", "assumptions.html", "diagnostics.png",
              "reproduce/analysis.py", "reproduce/analysis.R", "reproduce/analysis.do", "reproduce/data.csv"):
        assert n in names, n


# ---------------------------------------------------------------- 실험·파일 → 정돈 표

@pytest.fixture(scope="module")
def shome(tmp_path_factory):
    from app import db, thesaurus
    h = tmp_path_factory.mktemp("stats_home")
    mp = pytest.MonkeyPatch()
    mp.setenv("BYORBIT_HOME", str(h))
    thesaurus.invalidate()
    db.init(seed=True)
    yield h
    mp.undo()
    thesaurus.invalidate()


@pytest.fixture(scope="module")
def exp_id(shome):
    from app.experiment import store
    tpl = next(t for t in store.list_templates() if "추출" in t["name"])
    e = store.create_experiment("펙틴 산 추출", template_id=tpl["wf_id"])
    rng = np.random.default_rng(1)
    i = 0
    for acid, eff in (("구연산", 0.0), ("염산", 1.5)):
        for T in (60, 70, 80):
            for t in (60, 120):
                i += 1
                val = round(12 + 0.15 * (T - 70) + 0.01 * (t - 90) + eff + rng.normal(0, 0.7), 2)
                vtxt = "ND" if i == 3 else val
                store.add_run(e["exp_id"], label=f"R{i}", conditions={"extract1": {"temp_c": T, "time_min": t}},
                              note=f"산={acid}; 반복=1", values=[{"step_key": "extract1", "target": "추출 고형분 수율", "value": vtxt, "unit": "%"}])
    store.add_run(e["exp_id"], label="R-flow", conditions={}, note="산=염산",
                  values=[{"step_key": "extract1", "target": "추출 고형분 수율", "value": 14.0, "unit": "%"}])
    return e["exp_id"]


def test_experiment_to_tidy_dataset(exp_id):
    ds = D.from_experiment(exp_id)
    assert len(ds.df) == 13
    assert {"run", "temp_c", "time_min", "extract_solids", "acid", "rep"} <= set(ds.df.columns)
    cb = {v["name"]: v for v in ds.codebook}
    assert cb["temp_c"]["type"] == "continuous" and cb["temp_c"]["unit"] == "℃" and cb["temp_c"]["label_ko"] == "추출 온도"
    assert cb["acid"]["type"] == "categorical" and [l["value"] for l in cb["acid"]["levels"]] == ["citric", "HCl"]
    assert cb["acid"]["levels"][0]["label_ko"] == "구연산"
    assert cb["rep"]["type"] == "id"
    assert ds.missing["extract_solids"] == {2: "ND(불검출)"}
    row = ds.df[ds.df.run == "R-flow"].iloc[0]
    assert row.temp_c == 50 and row.time_min == 60          # 런에 비운 조건 = 흐름 값
    assert any("흐름에 넣은 값" in w for w in ds.warnings)
    r = A.run({"kind": "experiment", "exp_id": exp_id})
    assert r.spec["outcome"] == "extract_solids" and r.spec["group"] == "acid"
    assert r.core["n_used"] == 12 and r.out["dataset"]["dropped"][0]["reasons"] == {"extract_solids": "ND(불검출)"}


def test_upload_mapping(shome):
    csv_text = "런,온도(℃),시간(min),산 종류,수율(%)\nA1,70,60,구연산,12.1\nA2,80,60,염산,14.2\nA3,90,90,구연산,< 0.5\nA4,70,90,염산,13.3\nA5,80,120,구연산,13.0\nA6,90,120,염산,16.1\n"
    up = D.upload("runs.csv", csv_text.encode("utf-8"))
    m = {x["name"]: x for x in up["mapping"]}
    assert set(m) == {"run", "temp_c", "time_min", "acid", "yield_pct"}
    assert m["acid"]["type"] == "categorical" and m["temp_c"]["type"] == "continuous" and m["temp_c"]["unit"] == "℃"
    ds = D.from_upload(up["token"])
    assert ds.missing["yield_pct"] == {2: "검출 한계(< 0.5)"} and math.isnan(ds.df.yield_pct[2])
    assert D.from_upload(up["token"], censored="half").df.yield_pct[2] == 0.25
    bad = [dict(x, name="Bad Name") if x["name"] == "acid" else x for x in up["mapping"]]
    with pytest.raises(D.DataError, match="R·Stata"):
        D.from_upload(up["token"], bad)


# ---------------------------------------------------------------- API

@pytest.fixture(scope="module")
def client(shome):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import routes_stats
    app = FastAPI()
    app.include_router(routes_stats.router)
    return TestClient(app)


def test_api_flow(client, exp_id):
    d = client.get("/api/stats/datasets").json()
    assert any(x["exp_id"] == exp_id for x in d["experiments"]) and len(d["demos"]) == 2
    pv = client.post("/api/stats/dataset/preview", json={"source": {"kind": "demo", "levels": 3}}).json()
    assert pv["n"] == 81 and pv["is_demo"] and pv["suggested"]["group"] == "acid"
    res = client.post("/api/stats/run", json={"source": {"kind": "demo", "levels": 2}, "spec": {"zero": "apa"}})
    assert res.status_code == 200
    out = res.json()
    rid = out["result_id"]
    assert len(out["interpretation"]["ko"]) == 3 and "p < .001" in out["interpretation"]["ko"][0]   # APA 0 생략 강제
    for name, sig in (("figure1.png", b"\x89PNG"), ("table1.docx", b"PK"), ("bundle.zip", b"PK"), ("reproduce.zip", b"PK"), ("figure1.pdf", b"%PDF")):
        f = client.get(f"/api/stats/results/{rid}/files/{name}?lang=en&width=single")
        assert f.status_code == 200 and f.content[:len(sig)] == sig, name
    assert "attachment" in client.get(f"/api/stats/results/{rid}/files/table1.html").headers["content-disposition"]
    assert client.get(f"/api/stats/results/{rid}/files/nope.exe").status_code == 400
    assert client.get("/api/stats/results/expired/files/figure1.png").status_code == 404
    ex = client.post("/api/stats/export/table1.csv", json={"source": {"kind": "demo"}, "lang": "en"})
    assert ex.status_code == 200 and "Predictor" in ex.content.decode("utf-8-sig")
    e = client.post("/api/stats/run", json={"source": {"kind": "experiment", "exp_id": exp_id}}).json()
    assert e["spec"]["outcome"] == "extract_solids"
    bad = client.post("/api/stats/run", json={"source": {"kind": "demo"}, "spec": {"group": "acid", "categorical": [{"name": "acid", "reference": "x"}]}})
    assert bad.status_code == 400 and "기준 수준" in bad.json()["detail"]
    up = client.post("/api/stats/upload", files={"file": ("a.csv", "온도,산,수율\n70,구연산,12\n80,염산,14\n".encode("utf-8"), "text/csv")}).json()
    one = client.post("/api/stats/run", json={"source": {"kind": "upload", "token": up["token"]}})
    assert one.status_code == 400 and "넣으세요" in one.json()["detail"]


def test_run_is_fast(r2):
    import time
    t = time.time()
    A.run({"kind": "demo", "levels": 3})
    assert time.time() - t < 2.0
