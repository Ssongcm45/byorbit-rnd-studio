"""Claude Code·Codex가 MCP로 부르는 도구들. 테스트에서 바로 부를 수 있도록 일반 함수로 둔다.

원칙
- 기밀(CoA) 자료는 설정의 CoA 규칙에 따라 가리거나(mask) 막는다(block).
- 모델이 쓰는 도구는 DB를 직접 고치지 않고 '검토 대기'로만 넣는다(수치는 항상 pending).
"""
from __future__ import annotations

import json
import re

from . import config, db, search as _search, thesaurus

MASK = "[가림]"
LABEL_TYPES = {"BYPRODUCT", "COMMODITY", "PROCESS", "CONSTITUENT", "PROPERTY", "UNIT", "METHOD",
               "APPLICATION", "VALUE", "CONDITION", "OTHER"}


def _rule() -> str:
    return config.load_settings().get("coa_rule", "mask")


def _identifiers() -> list[str]:
    """모든 시료의 로트번호·공급처·시료번호. 긴 것부터(부분 일치로 일부만 가려지는 것을 막는다)."""
    vals = {str(v).strip() for s in db.rows("SELECT lot_no, supplier, sample_code FROM sample")
            for v in (s["lot_no"], s["supplier"], s["sample_code"]) if v and len(str(v).strip()) >= 2}
    return sorted(vals, key=len, reverse=True)


def _mask_text(doc_id: str | None, text: str | None, ids: list[str] | None = None) -> str | None:
    """기밀 자료의 식별 정보를 [가림]으로. 그 CoA의 시료뿐 아니라 등록된 모든 시료 식별자를 가린다
    (기밀로 올린 보고서·메모가 다른 CoA의 공급처를 언급하는 경우)."""
    if not text:
        return text
    for v in (ids if ids is not None else _identifiers()):
        text = text.replace(v, MASK)
    return text


def _mask_source(h: dict, ids: list[str]) -> None:
    """기밀 자료의 파일명·제목도 가린다 — 파일명에 공급처·로트번호가 들어가는 일이 흔하다.
    파일명은 확장자만 남기고 바꾼다. 근거는 chunk_id로 남으므로 화면에서는 원래 파일명이 보인다."""
    name = h.get("file_name") or ""
    ext = name[name.rfind("."):] if "." in name else ""
    h["file_name"] = f"기밀자료-{(h.get('doc_id') or '')[:6]}{ext}"
    if "title" in h:
        h["title"] = _mask_text(None, h["title"], ids)


def _visible(conf: str) -> bool:
    return not (conf == "기밀" and _rule() == "block")


# ---------------------------------------------------------------- 읽기

def search_chunks(query: str, project: str | None = None, limit: int = 10) -> dict:
    """자료 검색. 동의어까지 넓혀 찾는다. 결과의 chunk_id로 get_chunk를 불러 본문을 읽는다."""
    limit = max(1, min(int(limit), 30))
    r = _search.search(query, project=project, limit=limit * 2)
    out, hidden = [], 0
    ids = None
    for h in r["results"]:
        if not _visible(h["confidentiality"]):
            hidden += 1
            continue
        if h["confidentiality"] == "기밀":
            ids = _identifiers() if ids is None else ids
            h["snippet"] = _mask_text(h["doc_id"], h["snippet"], ids)
            _mask_source(h, ids)
        out.append(h)
        if len(out) >= limit:
            break
    return {"query": query, "expanded": r["expanded"], "results": out, "hidden_confidential": hidden}


def get_chunk(chunk_id: str) -> dict:
    """청크 본문과 출처(파일·쪽·섹션), 이미 붙은 라벨."""
    c = db.one("SELECT c.chunk_id, c.doc_id, c.chunk_type, c.page, c.text, d.file_name, s.title, s.year, "
               "s.confidentiality, sec.heading FROM chunk c JOIN document d ON d.doc_id=c.doc_id "
               "JOIN source s ON s.source_id=d.source_id LEFT JOIN doc_section sec ON sec.section_id=c.section_id "
               "WHERE c.chunk_id=?", (chunk_id,))
    if not c:
        return {"error": f"청크 없음: {chunk_id}"}
    if not _visible(c["confidentiality"]):
        return {"error": "기밀 자료입니다. 설정의 CoA 규칙이 '보내지 않기'라 본문을 줄 수 없습니다.", "chunk_id": chunk_id}
    if c["confidentiality"] == "기밀":
        ids = _identifiers()
        c["text"] = _mask_text(c["doc_id"], c["text"], ids)
        c["heading"] = _mask_text(None, c["heading"], ids)
        _mask_source(c, ids)
    c["annotations"] = db.rows(
        "SELECT a.ann_id, a.span_start, a.span_end, a.surface_text, a.label_type, k.pref_label_ko AS concept, "
        "a.normalized_value, a.method, a.status, a.confidence FROM annotation a "
        "LEFT JOIN concept k ON k.concept_id=a.concept_id WHERE a.chunk_id=? AND a.status!='rejected' "
        "ORDER BY a.span_start", (chunk_id,))
    return c


def lookup_concept(term: str) -> dict:
    """용어 → 표준 개념(표준명, 체계, 동의어 전부). 라벨링 전에 표기를 표준명으로 맞출 때 쓴다."""
    hits = thesaurus.lookup(term)
    for h in hits:
        h["broader"] = [r["pref_label_ko"] for r in db.rows(
            "SELECT t.pref_label_ko FROM concept_relation r JOIN concept t ON t.concept_id=r.target_concept_id "
            "WHERE r.concept_id=? AND r.rel_type='broader'", (h["concept_id"],))]
    return {"term": term, "matches": hits}


def query_measurements(byproduct: str | None = None, target: str | None = None,
                       project: str | None = None, limit: int = 100) -> dict:
    """측정값 표. 로트번호·공급처·시료번호는 항상 빼고 '시료 n'으로만 구분한다."""
    return measurements_query(byproduct, target, project, limit, apply_rule=True)


def measurements_query(byproduct=None, target=None, project=None, limit=100, apply_rule=True) -> dict:
    where, params = ["1=1"], []
    if byproduct:
        ids = [h["concept_id"] for h in thesaurus.lookup(byproduct) if h["scheme"] == "부산물"]
        where.append("(m.byproduct_id IN (SELECT byproduct_id FROM byproduct WHERE concept_id IN (%s)) OR 0)"
                     % ",".join("?" * len(ids)) if ids else "0")
        params += ids
    if target:
        syn = thesaurus.expand(target)
        where.append("(" + " OR ".join(["m.target_text LIKE ?"] * len(syn)) +
                     " OR m.target_concept_id IN (SELECT concept_id FROM concept_label WHERE label IN (%s)))"
                     % ",".join("?" * len(syn)))
        params += [f"%{s}%" for s in syn] + syn
    if project:
        where.append("(m.doc_id IN (SELECT entity_id FROM project_item pi JOIN project p ON p.project_id=pi.project_id "
                     "WHERE p.name=? AND pi.entity_type='document') OR m.sample_id IN (SELECT entity_id FROM project_item pi "
                     "JOIN project p ON p.project_id=pi.project_id WHERE p.name=? AND pi.entity_type='sample'))")
        params += [project, project]
    rows = db.rows(
        "SELECT m.meas_id, k.pref_label_ko AS byproduct, m.target_text, tc.pref_label_ko AS target, m.value, "
        "m.value_text, m.unit_text, m.basis, m.method_text, m.entry, m.sample_id, m.doc_id, m.ann_id, "
        "m.verified_at, smp.pretreatment_text AS pretreatment FROM measurement m "
        "LEFT JOIN byproduct b ON b.byproduct_id=m.byproduct_id LEFT JOIN concept k ON k.concept_id=b.concept_id "
        "LEFT JOIN concept tc ON tc.concept_id=m.target_concept_id LEFT JOIN sample smp ON smp.sample_id=m.sample_id "
        "WHERE " + " AND ".join(where) + " ORDER BY m.created_at LIMIT ?", params + [min(int(limit), 500)])
    rule = _rule()
    alias: dict[str, str] = {}
    out, withheld = [], 0
    for r in rows:
        if r["sample_id"]:
            r["sample"] = alias.setdefault(r["sample_id"], f"시료 {len(alias) + 1}")
        r["_sample_id"] = r.pop("sample_id")
        if apply_rule and r["entry"] == "coa" and rule == "block":
            withheld += 1
            continue
        if apply_rule:
            r.pop("_sample_id")
        out.append(r)
    note = f"CoA 규칙이 '보내지 않기'라 기밀 측정값 {withheld}건은 뺐습니다." if withheld else None
    return {"rows": out, "count": len(out), "withheld": withheld, "note": note}


# ---------------------------------------------------------------- 쓰기 (검토 대기로만)

def save_annotations(chunk_id: str, annotations: list[dict], engine: str = "claude") -> dict:
    """라벨 제안 저장. 각 항목: {surface, label_type, concept?(표준명), value?, unit?, confidence}
    - surface는 청크 본문에 그대로 있어야 한다(없으면 거절).
    - 수치(value)가 있으면 신뢰도와 상관없이 '검토 대기'.
    - 신뢰도 0.9 이상 & 수치 없음 → 자동 승인, 0.6~0.9 → 검토 대기, 0.6 미만 → 버림.
    """
    c = db.one("SELECT text FROM chunk WHERE chunk_id=?", (chunk_id,))
    if not c:
        return {"error": f"청크 없음: {chunk_id}"}
    text = c["text"]
    saved, rejected = [], []
    with db.tx() as tx:
        for i, a in enumerate(annotations or []):
            why = _validate_ann(a, text)
            if why:
                rejected.append({"index": i, "reason": why})
                continue
            conf = float(a.get("confidence", 0.7))
            if conf < 0.6:
                rejected.append({"index": i, "reason": "신뢰도 0.6 미만"})
                continue
            start = text.find(a["surface"])
            concept_id = None
            if a.get("concept"):
                m = [h for h in thesaurus.lookup(a["concept"]) if h["exact"]]
                concept_id = m[0]["concept_id"] if m else None
            unit_id = None
            if a.get("unit"):
                m = [h for h in thesaurus.lookup(a["unit"]) if h["exact"] and h["scheme"] == "단위"]
                unit_id = m[0]["concept_id"] if m else None
            has_value = a.get("value") not in (None, "")
            status = "pending" if has_value or conf < 0.9 or concept_id is None else "auto"
            norm = json.dumps({"value": a.get("value"), "unit": a.get("unit"), "target": a.get("target"),
                               "basis": a.get("basis")}, ensure_ascii=False) if has_value else None
            ann_id = db.new_id()
            tx.execute("INSERT INTO annotation(ann_id, chunk_id, span_start, span_end, surface_text, label_type, "
                       "concept_id, normalized_value, unit_concept_id, confidence, method, status, engine) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?, 'llm', ?, ?)",
                       (ann_id, chunk_id, start, start + len(a["surface"]), a["surface"], a["label_type"],
                        concept_id, norm, unit_id, conf, status, engine))
            saved.append({"index": i, "ann_id": ann_id, "status": status})
    return {"saved": saved, "rejected": rejected,
            "pending": sum(1 for s in saved if s["status"] == "pending")}


def _validate_ann(a: dict, text: str) -> str | None:
    if not isinstance(a, dict):
        return "객체가 아님"
    if not a.get("surface"):
        return "surface 없음"
    if a["surface"] not in text:
        return "surface가 청크 본문에 없음(원문 그대로 적어야 함)"
    if a.get("label_type") not in LABEL_TYPES:
        return f"label_type은 {sorted(LABEL_TYPES)} 중 하나"
    try:
        c = float(a.get("confidence", 0.7))
    except (TypeError, ValueError):
        return "confidence는 0~1 숫자"
    if not 0 <= c <= 1:
        return "confidence는 0~1"
    if a.get("value") not in (None, ""):
        try:
            float(str(a["value"]).replace(",", ""))
        except ValueError:
            return "value는 숫자"
    return None


_NUM_SENT = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|g|mg|℃|°C|µm|um|kg|L|mL|배|시간|분|h)")
_MARK = re.compile(r"\[(\d+)\]")


def save_report_draft(title: str, body_md: str, citations: list[dict], run_id: str | None = None) -> dict:
    """리포트 초안 저장. 본문에서 [1], [2]처럼 근거 번호를 달고 citations[i-1]에
    {claim, chunk_id 또는 measurement_id}를 넣는다. 근거 없는 수치 문장은 경고로 돌려준다."""
    problems = []
    for i, cit in enumerate(citations or [], start=1):
        if not (cit.get("chunk_id") or cit.get("measurement_id")):
            problems.append(f"근거 [{i}]에 chunk_id/measurement_id가 없습니다")
        elif cit.get("chunk_id") and not db.one("SELECT 1 AS x FROM chunk WHERE chunk_id=?", (cit["chunk_id"],)):
            problems.append(f"근거 [{i}]의 청크가 없습니다")
        elif cit.get("measurement_id") and not db.one("SELECT 1 AS x FROM measurement WHERE meas_id=?",
                                                      (cit["measurement_id"],)):
            problems.append(f"근거 [{i}]의 측정값이 없습니다")
    n = len(citations or [])
    uncited = []
    for sent in re.split(r"(?<=[.!?。])\s+|\n", body_md):
        if _NUM_SENT.search(sent):
            marks = [int(m) for m in _MARK.findall(sent)]
            if not marks or any(m < 1 or m > n for m in marks):
                uncited.append(sent.strip()[:120])
    rid = db.new_id()
    with db.tx() as c:
        c.execute("INSERT INTO report(report_id, run_id, title, body_md, status) VALUES (?,?,?,?, 'draft')",
                  (rid, run_id, title, body_md))
        for cit in citations or []:
            c.execute("INSERT INTO report_citation(cit_id, report_id, claim_text, chunk_id, measurement_id) "
                      "VALUES (?,?,?,?,?)", (db.new_id(), rid, cit.get("claim", ""), cit.get("chunk_id"),
                                             cit.get("measurement_id")))
    path = config.path("reports", f"{rid[:8]}-{re.sub(r'[^0-9A-Za-z가-힣]+', '_', title)[:40]}.md")
    refs = "\n".join(f"[{i}] {c.get('claim', '')} ({c.get('chunk_id') or c.get('measurement_id')})"
                     for i, c in enumerate(citations or [], start=1))
    path.write_text(f"# {title}\n\n{body_md}\n\n---\n근거\n{refs}\n", encoding="utf-8")
    return {"report_id": rid, "file": str(path), "status": "draft",
            "uncited_numeric_sentences": uncited, "citation_problems": problems,
            "ok": not uncited and not problems}


def propose_concept(label: str, scheme: str, alt_labels: list[str] | None = None,
                    definition: str | None = None, broader: str | None = None) -> dict:
    """새 개념 제안(내 확장). 상태는 'proposed' — 화면에서 승인해야 검색·라벨링에 쓰인다."""
    sch = db.one("SELECT scheme_id FROM concept_scheme WHERE name=?", (scheme,))
    if not sch:
        names = [r["name"] for r in db.rows("SELECT name FROM concept_scheme")]
        return {"error": f"체계는 {names} 중 하나"}
    exist = [h for h in thesaurus.lookup(label) if h["exact"]]
    if exist:
        return {"exists": exist[0], "note": "이미 있는 표기입니다. 동의어 추가가 필요하면 화면에서 하세요."}
    cid = db.new_id()
    cls = db.one("SELECT class_id FROM concept WHERE scheme_id=? AND class_id IS NOT NULL LIMIT 1", (sch["scheme_id"],))
    with db.tx() as c:
        c.execute("INSERT INTO concept(concept_id, scheme_id, class_id, iri, pref_label_ko, definition, origin, status) "
                  "VALUES (?,?,?,?,?,?, 'mine', 'proposed')",
                  (cid, sch["scheme_id"], cls["class_id"] if cls else None, f"mine:{cid[:12]}", label, definition))
        for lab, t in [(label, "pref")] + [(a, "alt") for a in (alt_labels or [])]:
            c.execute("INSERT INTO concept_label(label_id, concept_id, label, label_type) VALUES (?,?,?,?)",
                      (db.new_id(), cid, lab, t))
        if broader:
            b = [h for h in thesaurus.lookup(broader) if h["exact"]]
            if b:
                c.execute("INSERT OR IGNORE INTO concept_relation VALUES (?,?, 'broader')", (cid, b[0]["concept_id"]))
    return {"concept_id": cid, "status": "proposed"}


TOOLS = [search_chunks, get_chunk, lookup_concept, query_measurements, save_annotations,
         save_report_draft, propose_concept]
