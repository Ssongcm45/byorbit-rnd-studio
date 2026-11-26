"""문서 작업대(L): 청크 검사 표시, 청크 고치기(전문검색 동기화·라벨 위치 옮기기·사람 라벨 보호·되돌리기),
규칙 배우기(제목·잡음·짧은 조각)와 비슷한 자료에 적용·미리보기, 사람 라벨(수치→측정값)·고치기·지우기,
동의어 배우기, 부정 사례(사전 라벨이 건너뜀), AI 프롬프트의 사례(기밀 가림·막기), API."""
from __future__ import annotations

import json
import re

import pytest

ID = re.compile(r"^[0-9a-f]{32}$")
SECRET_LOT, SECRET_SUP = "LOT-WB-7781", "비밀농산"


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    from app import db, thesaurus
    h = tmp_path_factory.mktemp("wb_home")
    mp = pytest.MonkeyPatch()
    mp.setenv("BYORBIT_HOME", str(h))
    thesaurus.invalidate()
    db.init(seed=True)
    with db.tx() as c:  # 기밀 식별자(가림 대상)
        c.execute("INSERT INTO sample(sample_id, supplier, lot_no, sample_code) VALUES (?,?,?,?)",
                  (db.new_id(), SECRET_SUP, SECRET_LOT, "SC-WB-1"))
    yield h
    mp.undo()
    thesaurus.invalidate()


def make_doc(file_name: str, sections: list[tuple[str, list]], title: str | None = None, conf: str = "내부",
             dict_label: bool = True) -> dict:
    """청크를 직접 넣는다(파서와 무관하게 정확한 본문). sections: [(제목, [본문 | ("table", 본문, 표키) | (본문, bbox)])]."""
    from app import db
    from app.ingest import pipeline
    sid, did = db.new_id(), db.new_id()
    rows = []
    with db.tx() as c:
        c.execute("INSERT INTO source(source_id, source_type, title, confidentiality) VALUES (?,?,?,?)",
                  (sid, "report", title or file_name.rsplit(".", 1)[0], conf))
        c.execute("INSERT INTO document(doc_id, source_id, file_uri, file_name, sha256) VALUES (?,?,?,?,?)",
                  (did, sid, f"C:/nowhere/{file_name}", file_name, db.new_id()))
        ordn, tables = 0, {}
        for si, (heading, items) in enumerate(sections):
            sec = db.new_id()
            c.execute("INSERT INTO doc_section(section_id, doc_id, heading, ord, page_from, page_to) VALUES (?,?,?,?,?,?)",
                      (sec, did, heading, si, si + 1, si + 1))
            for it in items:
                ctype, table_id, bbox = "text", None, None
                if isinstance(it, tuple) and it[0] == "table":
                    ctype, body, tkey = it
                    if tkey not in tables:
                        tables[tkey] = db.new_id()
                        c.execute("INSERT INTO doc_table(table_id, doc_id, section_id, caption) VALUES (?,?,?,?)",
                                  (tables[tkey], did, sec, heading))
                    table_id = tables[tkey]
                elif isinstance(it, tuple):
                    body, bbox = it
                else:
                    body = it
                text = body if heading == "(머리말)" else f"{heading}\n{body}"
                cid = db.new_id()
                c.execute("INSERT INTO chunk(chunk_id, doc_id, section_id, table_id, chunk_type, ord, text, page, bbox) "
                          "VALUES (?,?,?,?,?,?,?,?,?)", (cid, did, sec, table_id, ctype, ordn, text, si + 1, bbox))
                rows.append((cid, text))
                ordn += 1
    if dict_label:
        pipeline.dict_label(rows)
    return {"doc_id": did, "chunks": [r[0] for r in rows]}


def chunks_of(doc_id):
    from app import db
    return db.rows("SELECT c.*, s.heading FROM chunk c LEFT JOIN doc_section s ON s.section_id=c.section_id "
                   "WHERE c.doc_id=? ORDER BY c.ord", (doc_id,))


def anns_of(chunk_id):
    from app import db
    return db.rows("SELECT * FROM annotation WHERE chunk_id=? ORDER BY span_start", (chunk_id,))


def fts(term: str) -> set[str]:
    from app import db
    return {r["chunk_id"] for r in db.rows(
        "SELECT c.chunk_id FROM chunk c WHERE c.rowid IN (SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ?)",
        ('"' + term + '"',))}


def spans_ok(chunk_id):
    from app import db
    text = db.one("SELECT text FROM chunk WHERE chunk_id=?", (chunk_id,))["text"]
    for a in anns_of(chunk_id):
        if a["span_start"] is not None:
            assert text[a["span_start"]:a["span_end"]] == a["surface_text"], (a, text)


def concept(label):
    from app import thesaurus
    return next(h for h in thesaurus.lookup(label) if h["exact"])["concept_id"]


LONG = "사과박 분말을 동결건조하여 성분을 분석하였다. " * 90
BODY1 = "사과박은 사과 착즙 후 남는 부산물이다. 총식이섬유는 건량 기준 54.2 g/100 g이었다."


# ---------------------------------------------------------------- 검사 표시

def test_quality_flags(home):
    from app import chunk_edit as E
    d = make_doc("검사용.md", [
        ("1. 서론", [BODY1 + "\nByOrbit 연구소 내부 보고서\n- 3 -", "짧은 조각.",
                   "문장이 끝나지 않고 이어지는\nByOrbit 연구소 내부 보고서", "다음 청크에서 문장이 끝난다. 그리고 계속 설명한다."
                   "\nByOrbit 연구소 내부 보고서"]),
        ("2. 결과", [LONG, BODY1 + "\nByOrbit 연구소 내부 보고서\n- 3 -",
                   ("table", "[표] 시료 | TDF\n시료: 동결건조; TDF: 54.2", "t1"),
                   ("table", "[표] 시료 | TDF\n시료: 열풍건조; TDF: 48.7", "t1"),
                   ("스캔으로 읽은 글자 사과박 시료 분석 결과를 정리하였다.", json.dumps({"ocr_conf": 0.55}))]),
    ])
    r = E.inspect(d["doc_id"])
    by = {c["ord"]: {f["code"] for f in c["flags"]} for c in r["chunks"]}
    assert "short" in by[1]
    assert "broken" in by[2] and "broken" not in by[3]
    assert "noise" in by[0]
    noise_lines = {x["line"] for x in next(f for f in r["chunks"][0]["flags"] if f["code"] == "noise")["lines"]}
    assert {"- 3 -", "ByOrbit 연구소 내부 보고서"} <= noise_lines
    assert "long" in by[4]
    assert "dup" in by[5]            # 0번 청크와 본문이 같음(섹션 제목만 다름)
    assert "table_split" in by[6] and "table_split" in by[7]
    assert "ocr_low" in by[8]
    assert r["summary"]["noise"] >= 2 and r["flagged_chunks"] >= 6
    # 섹션 제목 줄은 되풀이되어도 잡음으로 보지 않는다
    assert all("1. 서론" not in {x["line"] for f in c["flags"] if f["code"] == "noise" for x in f["lines"]}
               for c in r["chunks"])


# ---------------------------------------------------------------- 청크 고치기

def test_edit_shifts_labels_keeps_fts_and_protects_manual(home):
    from app import chunk_edit as E, db, labeling as L
    d = make_doc("고치기.md", [("1. 서론", [BODY1])])
    cid = d["chunks"][0]
    text = chunks_of(d["doc_id"])[0]["text"]
    m = L.create_manual(cid, "VALUE", surface="54.2 g/100 g", concept_id=concept("식이섬유"), target="식이섬유",
                        basis="건량")
    dict_before = [a for a in anns_of(cid) if a["method"] == "dict"]
    assert dict_before and any(a["surface_text"] == "사과박" for a in dict_before)
    # 앞에 글을 넣으면 모든 라벨 위치가 밀리고 표기는 그대로
    new = text.replace("사과박은", "시험 결과로 본 사과박은")
    r = E.edit_text(cid, new)
    assert r["ok"] and r["report"]["shifted"] >= 2 and not r["report"]["dropped"]
    spans_ok(cid)
    assert cid in fts("시험 결과로") and cid in fts("사과 착즙")
    # 사람 수치 라벨의 표기를 지우면: 라벨은 남고 위치만 비운다(확인 필요). 사과박을 지우면 사전 라벨은 지운다(보고)
    new2 = new.replace("54.2 g/100 g", "약 54 g").replace("시험 결과로 본 사과박은", "시료는")
    r2 = E.edit_text(cid, new2)
    assert any(x["ann_id"] == m["ann_id"] for x in r2["report"]["flagged"])
    assert any(x["surface"] == "사과박" and x["method"] == "dict" for x in r2["report"]["dropped"])
    a = db.one("SELECT * FROM annotation WHERE ann_id=?", (m["ann_id"],))
    assert a and a["span_start"] is None and a["status"] == "accepted"
    assert db.one("SELECT meas_id FROM measurement WHERE ann_id=?", (m["ann_id"],))  # 측정값도 그대로
    assert cid not in fts("시험 결과로")
    flags = {f["code"] for f in E.inspect(d["doc_id"])["chunks"][0]["flags"]}
    assert "attention" in flags
    # 되돌리면 글·라벨 위치·지워진 사전 라벨이 돌아온다
    E.undo(d["doc_id"])
    assert db.one("SELECT text FROM chunk WHERE chunk_id=?", (cid,))["text"] == new
    a = db.one("SELECT * FROM annotation WHERE ann_id=?", (m["ann_id"],))
    assert a["span_start"] is not None
    assert any(x["surface_text"] == "사과박" and x["method"] == "dict" for x in anns_of(cid))
    spans_ok(cid)
    assert cid in fts("시험 결과로")


def test_split_merge_move_labels_and_undo(home):
    from app import chunk_edit as E, db, labeling as L
    body = BODY1 + "\n\n" + "열풍건조 사과박의 총폴리페놀은 6.1 mg GAE/g이었다."
    d = make_doc("나누기.md", [("2. 결과", [body, "마지막 청크 내용이다."])])
    a_id, last = d["chunks"]
    text = chunks_of(d["doc_id"])[0]["text"]
    m = L.create_manual(a_id, "VALUE", surface="6.1 mg GAE/g", concept_id=concept("총폴리페놀"))
    pos = text.index("열풍건조")
    r = E.split_chunk(a_id, pos)
    b_id = r["chunk_ids"][1]
    cs = chunks_of(d["doc_id"])
    assert [c["ord"] for c in cs] == [0, 1, 2] and [c["chunk_id"] for c in cs] == [a_id, b_id, last]
    assert cs[1]["text"].startswith("2. 결과\n열풍건조")        # 뒤 조각에도 섹션 제목 줄
    assert db.one("SELECT chunk_id FROM annotation WHERE ann_id=?", (m["ann_id"],))["chunk_id"] == b_id
    spans_ok(a_id), spans_ok(b_id)
    assert b_id in fts("총폴리페놀") and a_id not in fts("총폴리페놀")
    # 합치기: 겹친 제목 줄은 한 번만, 라벨은 앞 청크로
    r = E.merge_chunk(a_id, "next")
    assert r["removed"] == b_id
    merged = db.one("SELECT text FROM chunk WHERE chunk_id=?", (a_id,))["text"]
    assert merged.count("2. 결과") == 1 and "열풍건조" in merged
    assert db.one("SELECT chunk_id FROM annotation WHERE ann_id=?", (m["ann_id"],))["chunk_id"] == a_id
    spans_ok(a_id)
    assert not db.one("SELECT 1 AS x FROM chunk WHERE chunk_id=?", (b_id,))
    assert fts("총폴리페놀") & {a_id, b_id} == {a_id}
    # 되돌리기 두 번 → 처음 그대로
    E.undo(d["doc_id"])
    assert db.one("SELECT chunk_id FROM annotation WHERE ann_id=?", (m["ann_id"],))["chunk_id"] == b_id
    E.undo(d["doc_id"])
    cs = chunks_of(d["doc_id"])
    assert [c["chunk_id"] for c in cs] == [a_id, last] and cs[0]["text"] == text
    assert db.one("SELECT chunk_id FROM annotation WHERE ann_id=?", (m["ann_id"],))["chunk_id"] == a_id
    spans_ok(a_id)
    assert fts("총폴리페놀") & {a_id, b_id} == {a_id}
    with pytest.raises(E.WbError):
        E.split_chunk(a_id, 2)  # 섹션 제목 줄만 남는 자리는 거절


def test_drop_never_loses_manual_labels(home):
    from app import chunk_edit as E, db, labeling as L
    d = make_doc("지우기.md", [("(머리말)", ["첫 청크: 사과박 분말 시료를 준비하였다.", "머리글 ByOrbit 사과박 보고서", "셋째 청크."])])
    c0, c1, c2 = d["chunks"]
    m = L.create_manual(c1, "BYPRODUCT", surface="사과박", concept_id=concept("사과박"))
    with pytest.raises(E.WbError) as ei:
        E.drop_chunk(c1)
    assert "그래도 지우기" in str(ei.value)
    r = E.drop_chunk(c1, force=True)
    a = db.one("SELECT * FROM annotation WHERE ann_id=?", (m["ann_id"],))
    assert a["chunk_id"] == c0 and a["span_start"] is not None  # 앞 청크에 '사과박'이 있어 자리를 찾음
    spans_ok(c0)
    assert [c["chunk_id"] for c in chunks_of(d["doc_id"])] == [c0, c2]
    assert c1 not in fts("ByOrbit")
    E.undo(d["doc_id"])
    assert [c["chunk_id"] for c in chunks_of(d["doc_id"])] == [c0, c1, c2]
    assert db.one("SELECT chunk_id FROM annotation WHERE ann_id=?", (m["ann_id"],))["chunk_id"] == c1
    assert c1 in fts("ByOrbit")
    spans_ok(c1)
    assert r["report"]["moved"] >= 1


def test_undo_refuses_after_rechunk(home):
    """다시 파싱(다시 청킹)으로 청크가 통째로 바뀐 뒤에는 옛 작업을 되돌리지 않는다(한국어 안내)."""
    from app import chunk_edit as E, db
    d = make_doc("재청킹.md", [("(머리말)", ["첫 문장이다. 둘째 문장이다. 셋째 문장이다."])])
    cid = d["chunks"][0]
    E.split_chunk(cid, chunks_of(d["doc_id"])[0]["text"].index("둘째"))
    with db.tx() as c:  # pipeline.reprocess_from_blocks처럼: 청크를 지우고 새 id로 다시 넣는다
        c.execute("DELETE FROM chunk WHERE doc_id=?", (d["doc_id"],))
        c.execute("INSERT INTO chunk(chunk_id, doc_id, chunk_type, ord, text) VALUES (?,?,?,?,?)",
                  (db.new_id(), d["doc_id"], "text", 0, "첫 문장이다. 둘째 문장이다. 셋째 문장이다."))
    with pytest.raises(E.WbError) as ei:
        E.undo(d["doc_id"])
    assert "다시 파싱" in str(ei.value)
    assert len(chunks_of(d["doc_id"])) == 1 and cid not in {c["chunk_id"] for c in chunks_of(d["doc_id"])}


def test_rules_apply_on_pipeline_rechunk(home):
    """P의 pipeline.reprocess_from_blocks가 다시 청킹할 때 배운 규칙(chunker_params·apply)이 쓰이고 사람 라벨은 남는다."""
    from app import chunk_edit as E, chunk_rules as R, db, labeling as L
    from app.ingest import pipeline
    if not hasattr(pipeline, "reprocess_from_blocks"):
        pytest.skip("파서 묶음(P)의 reprocess_from_blocks가 아직 없음")
    d = make_doc("재파싱_2026_01.md", [("(머리말)", ["사과박 분말의 총식이섬유는 54.2 g/100 g이었다.\n- 1 -"])])
    m = L.create_manual(d["chunks"][0], "VALUE", surface="54.2 g/100 g", target="식이섬유")
    R.create_rule("noise", r"^-\s*\d+\s*-$", scope={"type": "doc", "value": d["doc_id"]})
    blocks = [{"type": "text", "text": "사과박 분말의 총식이섬유는 54.2 g/100 g이었다.", "page": 1},
              {"type": "text", "text": "- 1 -", "page": 1}]
    pipeline.reprocess_from_blocks(d["doc_id"], blocks, "builtin")
    text = "\n".join(c["text"] for c in chunks_of(d["doc_id"]))
    assert "- 1 -" not in text and "54.2 g/100 g" in text
    a = db.one("SELECT * FROM annotation WHERE ann_id=?", (m["ann_id"],))
    assert a and a["method"] == "human"
    spans_ok(a["chunk_id"])
    E.undo(d["doc_id"])  # 다시 청킹 뒤 규칙 적용(맨 마지막 작업)은 되돌릴 수 있다
    assert "- 1 -" in "\n".join(c["text"] for c in chunks_of(d["doc_id"]))
    with pytest.raises(E.WbError):  # 그 전(다시 청킹 이전)의 작업은 없거나 되돌릴 수 없다
        E.undo(d["doc_id"])


def test_type_section_and_promote_heading(home):
    from app import chunk_edit as E, db
    d = make_doc("제목.md", [("1. 서론", ["서론 내용이다.\n2. 재료 및 방법\n시료는 사과박이다.", "방법 설명이 이어진다."]),
                            ("3. 결과", ["결과 내용이다."])])
    c0, c1, c2 = d["chunks"]
    r = E.promote_line(c0, "2. 재료 및 방법")
    cs = chunks_of(d["doc_id"])
    assert [c["heading"] for c in cs] == ["1. 서론", "2. 재료 및 방법", "2. 재료 및 방법", "3. 결과"]
    assert cs[1]["text"] == "2. 재료 및 방법\n시료는 사과박이다."
    assert cs[2]["chunk_id"] == c1 and cs[2]["text"].startswith("2. 재료 및 방법\n")
    secs = [s["heading"] for s in db.rows("SELECT heading FROM doc_section WHERE doc_id=? ORDER BY ord", (d["doc_id"],))]
    assert secs == ["1. 서론", "2. 재료 및 방법", "3. 결과"]
    for c in cs:
        spans_ok(c["chunk_id"])
    E.set_chunk_type(c2, "table")
    assert db.one("SELECT chunk_type FROM chunk WHERE chunk_id=?", (c2,))["chunk_type"] == "table"
    with pytest.raises(E.WbError):
        E.set_chunk_type(c2, "heading")
    E.set_chunk_section(c2, section_id=cs[0]["section_id"])
    assert db.one("SELECT text FROM chunk WHERE chunk_id=?", (c2,))["text"] == "1. 서론\n결과 내용이다."
    for _ in range(3):
        E.undo(d["doc_id"])
    cs = chunks_of(d["doc_id"])
    assert [c["chunk_id"] for c in cs] == [c0, c1, c2] and cs[0]["text"].count("2. 재료 및 방법") == 1
    assert len(db.rows("SELECT 1 FROM doc_section WHERE doc_id=?", (d["doc_id"],))) == 2
    with pytest.raises(E.WbError):
        E.undo(d["doc_id"])


# ---------------------------------------------------------------- 규칙 배우기·적용

def test_learn_noise_heading_merge_rules_and_apply_to_similar_doc(home):
    from app import chunk_edit as E, chunk_rules as R, db
    page = lambda n: f"- {n} -"  # noqa: E731
    a = make_doc("작물보고서_2024_01.md", [("1. 서론", [f"서론 내용이다.\n{page(1)}", "짧은 꼬리.",
                                                      f"본문 설명이다.\n2. 재료 및 방법\n시료를 준비하였다.\n{page(2)}"])],
                 title="농업부산물 연구보고서 1호")
    b = make_doc("작물보고서_2024_02.md", [("1. 개요", [f"개요 내용이다.\n{page(7)}", "또 짧은 꼬리.",
                                                      f"설명이다.\n3. 결과 및 고찰\n결과를 정리하였다.\n{page(8)}"])],
                 title="농업부산물 연구보고서 2호")
    a0, a1, a2 = a["chunks"]
    E.drop_line(a0, page(1))
    E.merge_chunk(a1, "prev")
    E.promote_line(a2, "2. 재료 및 방법")
    props = {p["kind"]: p for p in R.propose(a["doc_id"])}
    assert {"noise", "heading", "merge_short"} <= set(props)
    assert re.fullmatch(props["noise"]["pattern"], "- 12 -") and props["noise"]["matches"] >= 1  # 아직 남은 '- 2 -'
    assert re.fullmatch(props["heading"]["pattern"], "3. 결과 및 고찰")
    assert props["merge_short"]["params"]["min_len"] > len("짧은 꼬리.")
    scopes = {s["type"]: s for s in R.scope_options(a["doc_id"])}
    assert scopes["file_pattern"]["value"] == "작물보고서_*_*.md"
    assert scopes["title_prefix"]["value"] == "농업부산물 연구보고서"
    rules = [R.accept(props["noise"], scopes["file_pattern"]), R.accept(props["heading"], scopes["title_prefix"]),
             R.accept(props["merge_short"], scopes["title_prefix"])]
    assert all(r["origin"] == "learned" and r["enabled"] for r in rules)
    assert not {p["kind"] for p in R.propose(a["doc_id"])} & {"noise", "heading"}   # 이미 규칙이 된 것은 다시 제안하지 않음
    # 범위: 다른 이름·제목의 자료에는 맞지 않는다
    other = make_doc("다른자료.md", [("(머리말)", ["- 4 -\n내용."])], title="전혀 다른 제목")
    assert R.rules_for(other["doc_id"]) == []
    # 미리보기는 아무것도 바꾸지 않는다
    before = [(c["chunk_id"], c["text"]) for c in chunks_of(b["doc_id"])]
    pv = R.preview(b["doc_id"])
    acts = {c["action"] for c in pv["changes"]}
    assert {"잡음 줄 지움", "제목으로 올림", "짧은 조각 합침"} <= acts and pv["total"] >= 3
    assert pv["before"] == 3 and pv["after"] != pv["before"]
    assert [(c["chunk_id"], c["text"]) for c in chunks_of(b["doc_id"])] == before
    assert not db.one("SELECT 1 AS x FROM change_log WHERE table_name='wb_op' AND row_id=?", (b["doc_id"],))
    # 적용
    rep = R.apply(b["doc_id"])
    assert rep["total"] >= 3
    texts = "\n".join(c["text"] for c in chunks_of(b["doc_id"]))
    assert "- 7 -" not in texts and "- 8 -" not in texts and "또 짧은 꼬리." in texts
    assert "3. 결과 및 고찰" in [c["heading"] for c in chunks_of(b["doc_id"])]
    for c in chunks_of(b["doc_id"]):
        spans_ok(c["chunk_id"])
    lst = {r["rule_id"]: r for r in R.list_rules()}
    assert all(lst[r["rule_id"]]["hits"] >= 1 for r in rules)
    assert any(x["doc_id"] == b["doc_id"] for x in lst[rules[0]["rule_id"]]["docs"])
    # 적용은 되돌리기 한 번에 모두 되돌아간다
    E.undo(b["doc_id"])
    assert [(c["chunk_id"], c["text"]) for c in chunks_of(b["doc_id"])] == before
    # 끄면 적용되지 않는다, 지우면 목록에서 빠진다
    for r in rules:
        R.update_rule(r["rule_id"], enabled=False)
    assert R.apply(b["doc_id"])["total"] == 0
    R.delete_rule(rules[0]["rule_id"])
    assert rules[0]["rule_id"] not in {r["rule_id"] for r in R.list_rules()}
    with pytest.raises(R.RuleError):
        R.create_rule("noise", "([", scope={"type": "global"})


def test_chunker_params_and_table_rule(home):
    from app import chunk_rules as R
    from app.ingest import chunker
    rows = [["시료", "TDF"]] + [[f"시료{i}", str(i)] for i in range(60)]
    blocks = [{"type": "heading", "text": "표", "page": 1}, {"type": "table", "rows": rows, "page": 1}]
    assert len([c for c in chunker.build(blocks)["chunks"] if c["type"] == "table"]) == 3
    assert len([c for c in chunker.build(blocks, keep_tables=True)["chunks"] if c["type"] == "table"]) == 1
    long = [{"type": "text", "text": "가나다라마바사. " * 300, "page": 1}]
    assert len(chunker.build(long, target=400)["chunks"]) > len(chunker.build(long)["chunks"])
    d = make_doc("표자료.xlsx", [("(머리말)", [("table", "[표] a | b\na: 1", "t"), ("table", "[표] a | b\na: 2", "t")])])
    R.create_rule("table", params={"keep_together": True}, scope={"type": "doc", "value": d["doc_id"]})
    R.create_rule("length", params={"target": 700, "overlap": 80}, scope={"type": "format", "value": "xlsx"})
    assert R.chunker_params(d["doc_id"]) == {"keep_tables": True, "target": 700, "overlap": 80}
    lo, hi = R.limits(d["doc_id"])
    assert hi == int(700 * 1.6)
    rep = R.apply(d["doc_id"])
    cs = chunks_of(d["doc_id"])
    assert len(cs) == 1 and cs[0]["text"].count("[표] a | b") == 1 and "a: 1" in cs[0]["text"] and "a: 2" in cs[0]["text"]
    assert rep["total"] == 1
    blocks2 = R.prepare_blocks(d["doc_id"], [{"type": "text", "text": "x"}])
    assert blocks2 == [{"type": "text", "text": "x"}]


# ---------------------------------------------------------------- 사람 라벨

def test_manual_value_label_creates_measurement_edit_delete(home):
    from app import db, labeling as L
    d = make_doc("수치.md", [("2. 결과", [BODY1])])
    cid = d["chunks"][0]
    text = chunks_of(d["doc_id"])[0]["text"]
    s = text.index("54.2")
    e = s + len("54.2 g/100 g")
    sug = L.suggest(cid, s, e)
    assert sug["label_type"] == "VALUE" and sug["value"]["value"] == "54.2" and sug["value"]["unit"] == "g/100 g"
    assert sug["value"]["basis"] == "건량" and sug["target"] == "식이섬유"
    r = L.create_manual(cid, "VALUE", start=s, end=e, concept_id=concept("식이섬유"), unit="g/100 g", target="식이섬유",
                        basis="건량")
    a = db.one("SELECT * FROM annotation WHERE ann_id=?", (r["ann_id"],))
    assert a["method"] == "human" and a["status"] == "accepted" and a["surface_text"] == "54.2 g/100 g"
    m = db.one("SELECT * FROM measurement WHERE meas_id=?", (r["measurement_id"],))
    assert m["value"] == 54.2 and m["entry"] == "extracted" and m["basis"] == "건량" and m["doc_id"] == d["doc_id"]
    assert m["byproduct_id"]  # 자료의 부산물(사전 라벨 '사과박')에 연결
    ex = db.one("SELECT * FROM label_example WHERE ex_id=?", (r["example_id"],))
    assert ex["kind"] == "positive" and "54.2" in ex["context"]
    # 고치기: 값 바꾸면 측정값이 한 건만(새 값)
    u = L.update_label(r["ann_id"], value="54.3")
    ms = db.rows("SELECT value FROM measurement WHERE ann_id=?", (r["ann_id"],))
    assert [x["value"] for x in ms] == [54.3] and u["measurement_id"]
    # 표기로 붙이기(키보드), 없는 표기는 거절
    r2 = L.create_manual(cid, "CONSTITUENT", surface="총식이섬유", concept_id=concept("식이섬유"))
    assert db.one("SELECT span_start FROM annotation WHERE ann_id=?", (r2["ann_id"],))["span_start"] == text.index("총식이섬유")
    with pytest.raises(L.ManualError):
        L.create_manual(cid, "VALUE", surface="99.9 kg")
    with pytest.raises(L.ManualError):
        L.create_manual(cid, "NOPE", surface="사과")
    # 지우기: 측정값도 함께
    L.delete_label(r["ann_id"])
    assert not db.one("SELECT 1 AS x FROM measurement WHERE ann_id=?", (r["ann_id"],))
    assert not db.one("SELECT 1 AS x FROM annotation WHERE ann_id=?", (r["ann_id"],))
    # 사전 라벨을 고치면 '고친 라벨'(승인) + 사례
    dl = next(x for x in anns_of(cid) if x["method"] == "dict")
    u2 = L.update_label(dl["ann_id"], label_type="COMMODITY")
    assert db.one("SELECT status FROM annotation WHERE ann_id=?", (dl["ann_id"],))["status"] == "accepted"
    assert db.one("SELECT note FROM label_example WHERE ex_id=?", (u2["example_id"],))["note"] == "고친 라벨"


def test_review_accept_reject_same_as_server(home):
    from app import db, labeling as L, tools
    d = make_doc("검토.md", [("2. 결과", [BODY1])])
    cid = d["chunks"][0]
    s = tools.save_annotations(cid, [{"surface": "54.2 g/100 g", "label_type": "VALUE", "value": 54.2, "unit": "g/100 g",
                                      "target": "식이섬유", "confidence": 0.8}])
    aid = s["saved"][0]["ann_id"]
    r = L.review_annotation(aid, "accepted")
    assert r["measurement_id"]
    r = L.review_annotation(aid, "accepted")
    assert len(db.rows("SELECT 1 FROM measurement WHERE ann_id=?", (aid,))) == 1 and r["removed_measurements"] == 1
    r = L.review_annotation(aid, "pending")
    assert not db.rows("SELECT 1 FROM measurement WHERE ann_id=?", (aid,))


# ---------------------------------------------------------------- 배우기: 동의어·부정 사례

def test_learn_synonym_and_remove(home):
    from app import db, labeling as L, thesaurus
    d = make_doc("동의어.md", [("(머리말)", ["애플 포미스 분말을 시료로 썼다."])])
    cid = d["chunks"][0]
    assert not any(h["exact"] for h in thesaurus.lookup("애플 포미스"))
    r = L.create_manual(cid, "BYPRODUCT", surface="애플 포미스", concept_id=concept("사과박"))
    assert r["offer_synonym"] and r["offer_synonym"]["surface"] == "애플 포미스"
    syn = L.learn_synonym(r["offer_synonym"]["concept_id"], "애플 포미스", ann_id=r["ann_id"])
    assert syn["label_id"] and syn["concept"] == "사과박"
    hit = [h for h in thesaurus.lookup("애플 포미스") if h["exact"]]
    assert hit and hit[0]["concept_id"] == concept("사과박")
    assert any(m["surface"] == "애플 포미스" for m in thesaurus.find_mentions("새 자료의 애플 포미스 시료"))
    assert "애플 포미스" in thesaurus.expand("사과박")
    assert L.learn_synonym(concept("사과박"), "애플 포미스")["already"]
    lst = L.learned()
    assert any(s["label"] == "애플 포미스" for s in lst["synonyms"])
    assert any(e["surface"] == "애플 포미스" for e in lst["examples"])
    L.remove_synonym(syn["label_id"])
    assert not any(h["exact"] for h in thesaurus.lookup("애플 포미스"))
    seed_label = db.one("SELECT label_id FROM concept_label WHERE label='사과박'")["label_id"]
    with pytest.raises(L.ManualError):
        L.remove_synonym(seed_label)  # 시드 표기는 지우지 않는다


def test_negative_example_makes_dict_skip(home):
    from app import db, labeling as L, thesaurus
    d = make_doc("부정.md", [("(머리말)", ["회사 이름 사과박 상사의 주소는 생략한다.", "사과박 분말의 식이섬유를 분석하였다."])])
    c0, c1 = d["chunks"]
    wrong = next(a for a in anns_of(c0) if a["surface_text"] == "사과박")
    r = L.review_annotation(wrong["ann_id"], "rejected", learn=True)
    ex_id = r["negative_example"]
    ex = db.one("SELECT * FROM label_example WHERE ex_id=?", (ex_id,))
    assert ex["kind"] == "negative" and json.loads(ex["value_json"])["right"] == "상사의"
    # 사전 라벨 다시: 같은 문맥(c0)에서는 건너뛰고, 다른 문맥(c1)에서는 그대로 붙는다
    out = L.dict_relabel(d["doc_id"])
    assert out["ok"]
    c0_dict = [a for a in anns_of(c0) if a["surface_text"] == "사과박" and a["method"] == "dict"]
    assert [a["status"] for a in c0_dict] == ["rejected"]     # 거절 기록만 남고 새로 붙지 않음
    assert any(a["surface_text"] == "사과박" and a["status"] == "auto" for a in anns_of(c1))
    assert not any(m["surface"] == "사과박" for m in thesaurus.find_mentions("문의: 사과박 상사의 담당자"))
    # 어디서나 → 다른 문맥도 건너뜀, 끄면 다시 붙음
    L.set_negative_scope(ex_id, "everywhere")
    assert not any(m["surface"] == "사과박" for m in thesaurus.find_mentions("사과박 분말"))
    L.set_example(ex_id, False)
    assert any(m["surface"] == "사과박" for m in thesaurus.find_mentions("사과박 분말"))
    L.set_example(ex_id, True)
    L.set_negative_scope(ex_id, "context")
    # 거절을 되돌리면 그 부정 사례는 꺼진다
    L.review_annotation(wrong["ann_id"], "auto", learn=True)
    assert not db.one("SELECT enabled FROM label_example WHERE ex_id=?", (ex_id,))["enabled"]
    assert any(m["surface"] == "사과박" for m in thesaurus.find_mentions("회사 이름 사과박 상사의 주소"))


# ---------------------------------------------------------------- AI 라벨러 사례(가림·막기)

class CaptureEngine:
    __name__ = "fake_claude"

    def __init__(self):
        self.prompts, self.kw = [], []

    def run(self, prompt, **kw):
        from app import db, tools
        self.prompts.append(prompt)
        self.kw.append(kw)
        for cid in [ln.strip() for ln in prompt.splitlines() if ID.match(ln.strip())]:
            text = db.one("SELECT text FROM chunk WHERE chunk_id=?", (cid,))["text"]
            tools.save_annotations(cid, [{"surface": text[:4], "label_type": "OTHER", "confidence": 0.7}])
        return {"ok": True, "result": "ok", "session_id": "s"}


def test_examples_in_labeler_prompt_masked_or_blocked(home, monkeypatch):
    from app import config, engines, labeling as L
    secret = make_doc("기밀메모.md", [("(머리말)", [f"로트 {SECRET_LOT} ({SECRET_SUP}) 사과박의 총식이섬유는 건량 51.0 g/100 g이었다."])],
                      conf="기밀")
    L.create_manual(secret["chunks"][0], "VALUE", surface="51.0 g/100 g", concept_id=concept("식이섬유"),
                    target="식이섬유", basis="건량")
    target = make_doc("새논문.md", [("2. 결과", ["사과박 분말의 총식이섬유 함량은 47.0 g/100 g이었다."])])
    eng = CaptureEngine()
    monkeypatch.setattr(engines, "get", lambda name=None: eng)
    config.save_settings({"coa_rule": "mask"})
    L.start(target["doc_id"], background=False)
    p = eng.prompts[-1]
    assert eng.kw[-1]["role"] == "labeler"
    assert "## 참고 사례" in p and "51.0 g/100 g" in p
    assert SECRET_LOT not in p and SECRET_SUP not in p and "[가림]" in p
    assert len([ln for ln in p.splitlines() if re.match(r"^\d+\. ", ln)]) <= L.EX_LIMIT
    sec = L.examples_section(target["chunks"], "codex")   # Codex는 늘 막기
    assert "51.0 g/100 g" not in sec
    config.save_settings({"coa_rule": "block"})
    try:
        L.start(target["doc_id"], background=False, force=True)
        p2 = eng.prompts[-1]
        assert "51.0 g/100 g" not in p2 and SECRET_LOT not in p2
        assert L.examples_for(target["chunks"])["excluded_confidential"] >= 1
    finally:
        config.save_settings({"coa_rule": "mask"})
    # 사례를 끄면 프롬프트에서 빠진다
    lst = L.learned()
    for e in lst["examples"]:
        L.set_example(e["ex_id"], False)
    assert "51.0 g/100 g" not in L.examples_section(target["chunks"], "claude")
    for e in lst["examples"]:
        L.set_example(e["ex_id"], True)


def test_ai_label_selected_chunks_only(home, monkeypatch):
    from app import engines, labeling as L
    d = make_doc("선택.md", [("(머리말)", ["첫째 청크 사과박.", "둘째 청크 사과박.", "셋째 청크 사과박."])])
    eng = CaptureEngine()
    monkeypatch.setattr(engines, "get", lambda name=None: eng)
    rid = L.start(d["doc_id"], background=False, chunk_ids=[d["chunks"][1]])
    st = L.status(rid)
    assert st["total"] == 1 and st["steps"][0]["chunk_id"] == d["chunks"][1] and st["status"] == "done"


# ---------------------------------------------------------------- API

@pytest.fixture(scope="module")
def client(home):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import routes_workbench
    app = FastAPI()
    app.include_router(routes_workbench.router)
    return TestClient(app)


def test_api_flow(client, home):
    d = make_doc("API_2024_01.md", [("1. 서론", [BODY1 + "\n- 5 -", "다음 청크이다."])], title="API 시험 보고서")
    doc_id, (c0, c1) = d["doc_id"], d["chunks"]
    r = client.get(f"/api/wb/docs/{doc_id}")
    assert r.status_code == 200 and r.json()["scopes"][0]["type"] == "doc"
    lst = client.get(f"/api/wb/docs/{doc_id}/chunks").json()
    assert len(lst["chunks"]) == 2 and any(f["code"] == "noise" for f in lst["chunks"][0]["flags"])
    r = client.post(f"/api/wb/chunks/{c0}/drop-line", json={"line": "- 5 -"})
    assert r.status_code == 200 and r.json()["removed_lines"] == 1
    pr = client.get(f"/api/wb/docs/{doc_id}/rules/proposals").json()
    noise = next(p for p in pr["proposals"] if p["kind"] == "noise")
    pv = client.post(f"/api/wb/docs/{doc_id}/rules/preview", json={"rules": [noise]}).json()
    assert pv["total"] == 0  # 이 자료에는 이미 지웠음
    acc = client.post("/api/wb/rules/accept", json={"proposal": noise, "scope": pr["scopes"][1]}).json()
    assert acc["origin"] == "learned"
    assert client.patch(f"/api/wb/rules/{acc['rule_id']}", json={"enabled": False}).json()["enabled"] is False
    assert client.get("/api/wb/rules").status_code == 200
    ch = client.get(f"/api/wb/chunks/{c0}").json()
    s = ch["text"].index("54.2")
    sug = client.get("/api/wb/suggest", params={"chunk_id": c0, "start": s, "end": s + 12}).json()
    assert sug["label_type"] == "VALUE"
    cr = client.post("/api/wb/labels", json={"chunk_id": c0, "label_type": "VALUE", "start": s, "end": s + 12,
                                              "value": "54.2", "unit": "g/100 g", "target": "식이섬유"}).json()
    assert cr["measurement_id"]
    assert client.patch(f"/api/wb/labels/{cr['ann_id']}", json={"basis": "건량"}).json()["ok"]
    dict_ann = next(a for a in client.get(f"/api/wb/chunks/{c0}").json()["annotations"] if a["method"] == "dict")
    rv = client.post(f"/api/wb/labels/{dict_ann['ann_id']}/review", json={"status": "rejected"}).json()
    assert rv["negative_example"]
    learned = client.get("/api/wb/learned").json()
    assert learned["negatives"] and learned["examples"] and learned["rules"]
    assert client.patch(f"/api/wb/examples/{rv['negative_example']}", json={"enabled": False}).json()["ok"]
    sp = client.post(f"/api/wb/chunks/{c0}/split", json={"pos": ch["text"].index("총식이섬유")})
    assert sp.status_code == 200 and len(sp.json()["chunk_ids"]) == 2
    assert client.post(f"/api/wb/docs/{doc_id}/undo").json()["undone"] == "split"
    bad = client.post(f"/api/wb/chunks/{c0}/split", json={"pos": 0})
    assert bad.status_code == 400 and "커서" in bad.json()["detail"]
    nf = client.get("/api/wb/chunks/" + "0" * 32)
    assert nf.status_code == 404 and "새로고침" in nf.json()["detail"]
    dl = client.post(f"/api/wb/docs/{doc_id}/dict-label", json={}).json()
    assert dl["ok"] and dl["chunks"] == 2
    ex = client.get(f"/api/wb/docs/{doc_id}/examples-preview").json()
    assert "examples" in ex and "section" in ex
    assert client.get("/api/wb/concepts", params={"q": "포마스"}).json()["matches"]
    nc = client.post("/api/wb/concepts", json={"label": "사과 씨앗 박", "scheme": "부산물"}).json()
    assert nc["concept_id"] and not nc["exists"]
    assert client.get("/api/wb/meta").json()["label_types"]
    assert client.delete(f"/api/wb/labels/{cr['ann_id']}").json()["removed_measurements"] == 1


def test_agent_instructions_upgrade(tmp_path, monkeypatch):
    """손대지 않은 옛 지침 사본은 새 버전으로 바뀌고, 사용자가 고친 사본은 그대로 남는다."""
    import subprocess
    from app import config, db
    monkeypatch.setenv("BYORBIT_HOME", str(tmp_path / "h"))
    config.ensure_dirs()
    root = config.APP_ROOT
    old = subprocess.run(["git", "show", "4db41c5:agents/labeler.md"], cwd=root, capture_output=True).stdout
    if not old:
        import pytest
        pytest.skip("git 기록 없음")
    dst = config.path("agents")
    (dst / "labeler.md").write_bytes(old.replace(b"\n", b"\r\n"))          # 옛 사본(CRLF)
    (dst / "librarian.md").write_text("내가 고친 지침", encoding="utf-8")  # 사용자가 고친 사본
    db._copy_agents()
    assert (dst / "labeler.md").read_bytes().replace(b"\r\n", b"\n") == (root / "agents" / "labeler.md").read_bytes().replace(b"\r\n", b"\n")
    assert (dst / "librarian.md").read_text(encoding="utf-8") == "내가 고친 지침"
