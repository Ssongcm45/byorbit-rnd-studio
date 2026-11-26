"""지식그래프 API (/api/kg) — 개념(점)과 관계(선)에 자료·측정값을 이어 붙인 지도.

- 점(node): 개념(concept, 체계별 색) · 자료(document, 라벨이 그 개념을 가리킨 문서)
- 선(edge): 개념 관계(concept_relation: broader·derivedFrom·generatedBy·contains·사용자 관계)
           + 언급(mentions: 자료 → 개념, 라벨 수) + 측정(measured: 부산물 → 측정 항목, n·평균·범위)
- 동의어(alt)·숨은 표기(hidden)는 따로 점을 만들지 않고 표준명 점 하나로 모인다.

이 화면은 내 PC 전용이지만 시료의 로트·공급처·시료번호는 어디에도 싣지 않는다.
내보내기(export.json)는 PC 밖으로 옮겨질 수 있으므로 기밀 자료 이름을 가리고 기밀 측정값은 빼고 만든다.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from . import db
from .seed import seed_data as S

router = APIRouter(prefix="/api/kg")

# 선 종류 — 화면 범례 순서이기도 하다
REL_LABEL = {
    "broader": "상위 분류",
    "derivedFrom": "원료",
    "generatedBy": "발생 공정",
    "contains": "함유 성분",
    "measured": "측정",
    "mentions": "언급",
}
REL_ORDER = {k: i for i, k in enumerate(REL_LABEL)}
OTHER = "other"  # 위 종류가 아닌 사용자 관계
NODE_CAP = 150
DOCS_PER_CONCEPT = 6
SCHEME_KEY = {name: cls for name, (cls, _, _) in S.SCHEME_CLASS.items()}  # 체계 → 색 키(영문 클래스)
DEFAULT_CENTER = "사과박"


def _full_iri(iri: str | None) -> str | None:
    if not iri:
        return None
    if iri.startswith("mine:"):
        return "https://byorbit.kr/onto/mine/" + iri[5:]
    if iri.startswith("byo:"):
        return "https://byorbit.kr/onto/" + iri[4:]
    return iri


def _rel_label(t: str) -> str:
    return REL_LABEL.get(t, t)


def _parse_types(types: str | None) -> set[str]:
    if not types:
        return set(REL_LABEL) | {OTHER}
    return {t.strip() for t in types.split(",") if t.strip()}


def _allowed(rel_type: str, types: set[str]) -> bool:
    return rel_type in types if rel_type in REL_LABEL else OTHER in types


# ---------------------------------------------------------------- 데이터 읽기

def _concepts() -> dict[str, dict]:
    return {r["concept_id"]: r for r in db.rows(
        "SELECT c.concept_id, c.pref_label_ko, c.pref_label_en, c.origin, c.status, c.iri, s.name AS scheme "
        "FROM concept c LEFT JOIN concept_scheme s ON s.scheme_id=c.scheme_id")}


def _measured(public_only: bool = False) -> list[dict]:
    """부산물 개념 × 측정 항목 개념의 집계. 단위가 다르면 단위별로 나눠 두고, 가장 많은 단위를 대표로 쓴다."""
    where = "m.target_concept_id IS NOT NULL"
    if public_only:  # 내보내기: 기밀 자료·기밀 시료의 값은 뺀다
        where += (" AND COALESCE(src.confidentiality,'일반')!='기밀' AND COALESCE(sm.confidentiality,'일반')!='기밀'")
    groups = db.rows(
        "SELECT b.concept_id AS bp, m.target_concept_id AS tg, COALESCE(m.unit_text,'') AS unit, COUNT(*) AS n, "
        "COUNT(m.value) AS n_num, AVG(m.value) AS mean, MIN(m.value) AS mn, MAX(m.value) AS mx, "
        "COUNT(DISTINCT m.doc_id) AS docs "
        "FROM measurement m JOIN byproduct b ON b.byproduct_id=m.byproduct_id "
        "LEFT JOIN sample sm ON sm.sample_id=m.sample_id LEFT JOIN document d ON d.doc_id=m.doc_id "
        "LEFT JOIN source src ON src.source_id=d.source_id "
        f"WHERE {where} GROUP BY b.concept_id, m.target_concept_id, COALESCE(m.unit_text,'')")
    by_pair: dict[tuple, list] = defaultdict(list)
    for g in groups:
        by_pair[(g["bp"], g["tg"])].append(g)
    out = []
    for (bp, tg), gs in by_pair.items():
        gs.sort(key=lambda g: (-g["n"], g["unit"]))
        units = [{"unit": g["unit"], "n": g["n"], "n_numeric": g["n_num"],
                  "mean": _r(g["mean"]), "min": _r(g["mn"]), "max": _r(g["mx"])} for g in gs]
        top = units[0]
        out.append({"source": bp, "target": tg, "n": sum(g["n"] for g in gs), "unit": top["unit"],
                    "mean": top["mean"], "min": top["min"], "max": top["max"], "n_numeric": top["n_numeric"],
                    "units": units})
    return out


def _r(v):
    return None if v is None else round(float(v), 4)


def _mentions() -> dict[str, list[dict]]:
    """개념 → 그 개념을 라벨로 가리킨 자료 목록(라벨 수 많은 순). 거절한 라벨은 세지 않는다."""
    rows = db.rows(
        "SELECT a.concept_id AS cid, c.doc_id, COUNT(*) AS n FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id "
        "WHERE a.concept_id IS NOT NULL AND a.status!='rejected' GROUP BY a.concept_id, c.doc_id")
    out: dict[str, list] = defaultdict(list)
    for r in rows:
        out[r["cid"]].append({"doc_id": r["doc_id"], "n": r["n"]})
    for lst in out.values():
        lst.sort(key=lambda x: -x["n"])
    return out


def _docs(ids) -> dict[str, dict]:
    ids = list(ids)
    if not ids:
        return {}
    return {r["doc_id"]: r for r in db.rows(
        "SELECT d.doc_id, d.file_name, s.title, s.source_type, s.year, s.confidentiality FROM document d "
        "JOIN source s ON s.source_id=d.source_id WHERE d.doc_id IN (%s)" % ",".join("?" * len(ids)), ids)}


def _concept_node(c: dict) -> dict:
    return {"id": c["concept_id"], "kind": "concept", "label": c["pref_label_ko"], "en": c["pref_label_en"],
            "scheme": c["scheme"], "key": SCHEME_KEY.get(c["scheme"], "Other"), "origin": c["origin"],
            "status": c["status"]}


def _doc_node(d: dict, mask: bool = False) -> dict:
    secret = d["confidentiality"] == "기밀"
    label = d["title"] or d["file_name"]
    if mask and secret:
        return {"id": "doc:" + d["doc_id"], "kind": "document", "label": "기밀자료-" + d["doc_id"][:6],
                "key": "Document", "confidentiality": "기밀"}
    return {"id": "doc:" + d["doc_id"], "kind": "document", "label": label, "file_name": d["file_name"],
            "doc_id": d["doc_id"], "source_type": d["source_type"], "year": d["year"], "key": "Document",
            "confidentiality": d["confidentiality"]}


def find_center(center: str | None, C: dict) -> str | None:
    if center and center in C:
        return center
    term = center or DEFAULT_CENTER
    hits = search_concepts(term, limit=1)
    if hits:
        return hits[0]["concept_id"]
    if center:
        return None
    r = db.one("SELECT concept_id FROM byproduct LIMIT 1")
    return r["concept_id"] if r else None


# ---------------------------------------------------------------- 그래프

def build_graph(center: str | None = None, depth: int = 1, types: str | None = None, cap: int = NODE_CAP) -> dict:
    depth = 2 if depth >= 2 else 1
    cap = max(5, min(int(cap), 400))
    T = _parse_types(types)
    C = _concepts()
    cid = find_center(center, C)
    if not cid:
        raise KeyError(center)

    # 이웃 목록: (다른 점, 선). 자료 점은 펼치지 않는다(자료 → 개념 방향은 넣지 않음)
    adj: dict[str, list] = defaultdict(list)
    edges: dict[str, dict] = {}

    def link(a, b, e):
        edges[e["id"]] = e
        adj[a].append((b, e))
        if not b.startswith("doc:"):
            adj[b].append((a, e))

    for r in db.rows("SELECT concept_id, target_concept_id, rel_type FROM concept_relation"):
        t = r["rel_type"]
        if not _allowed(t, T) or r["concept_id"] not in C or r["target_concept_id"] not in C:
            continue
        link(r["concept_id"], r["target_concept_id"],
             {"id": f"{t}:{r['concept_id']}>{r['target_concept_id']}", "source": r["concept_id"],
              "target": r["target_concept_id"], "type": t if t in REL_LABEL else OTHER, "rel_type": t,
              "label": _rel_label(t)})
    if "measured" in T:
        for m in _measured():
            if m["source"] in C and m["target"] in C:
                link(m["source"], m["target"], {"id": f"measured:{m['source']}>{m['target']}", "type": "measured",
                                                "rel_type": "measured", "label": REL_LABEL["measured"], **m})
    more_docs: dict[str, int] = {}
    if "mentions" in T:
        for k, lst in _mentions().items():
            if k not in C:
                continue
            for x in lst[:DOCS_PER_CONCEPT]:
                did = "doc:" + x["doc_id"]
                link(k, did, {"id": f"mentions:{did}>{k}", "source": did, "target": k, "type": "mentions",
                              "rel_type": "mentions", "label": REL_LABEL["mentions"], "count": x["n"]})
            if len(lst) > DOCS_PER_CONCEPT:
                more_docs[k] = len(lst) - DOCS_PER_CONCEPT

    rank = lambda pair: (REL_ORDER.get(pair[1]["type"], 99), C.get(pair[0], {}).get("pref_label_ko") or pair[0])  # noqa: E731
    seen = {cid: 0}
    frontier = [cid]
    truncated = False
    for d in range(1, depth + 1):
        nxt = []
        for n in frontier:
            for other, _e in sorted(adj[n], key=rank):
                if other in seen:
                    continue
                if len(seen) >= cap:
                    truncated = True
                    continue
                seen[other] = d
                if not other.startswith("doc:"):
                    nxt.append(other)
        frontier = nxt

    docs = _docs(k[4:] for k in seen if k.startswith("doc:"))
    nodes = []
    for k, d in seen.items():
        if k.startswith("doc:"):
            if k[4:] not in docs:
                continue
            node = _doc_node(docs[k[4:]])
        else:
            node = _concept_node(C[k])
            node["hidden"] = sum(1 for o, _ in adj[k] if o not in seen)  # 이 점에서 더 펼칠 수 있는 이웃 수
            if k in more_docs:
                node["more_docs"] = more_docs[k]
        node["depth"] = d
        nodes.append(node)
    keep = {n["id"] for n in nodes}
    out_edges = [e for e in edges.values() if e["source"] in keep and e["target"] in keep]
    out_edges.sort(key=lambda e: (REL_ORDER.get(e["type"], 99), e["id"]))
    counts = defaultdict(int)
    for e in out_edges:
        counts[e["type"]] += 1
    return {"center": cid, "center_label": C[cid]["pref_label_ko"], "depth": depth, "types": sorted(T),
            "nodes": nodes, "edges": out_edges, "truncated": truncated, "cap": cap,
            "edge_counts": dict(counts), "legend": {**REL_LABEL, OTHER: "기타 관계"}}


# ---------------------------------------------------------------- 찾기·자세히

def search_concepts(q: str, limit: int = 15) -> list[dict]:
    """표준명·동의어·숨은 표기 어디에 맞아도 개념 하나로 돌려준다. 띄어쓰기·대소문자는 무시한다."""
    q = (q or "").strip()
    if not q:
        return []
    key = q.lower().replace(" ", "")
    like = "%" + key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = db.rows(
        "SELECT l.label, l.label_type, c.concept_id, c.pref_label_ko, c.pref_label_en, c.status, s.name AS scheme "
        "FROM concept_label l JOIN concept c ON c.concept_id=l.concept_id "
        "LEFT JOIN concept_scheme s ON s.scheme_id=c.scheme_id "
        "WHERE replace(lower(l.label),' ','') LIKE ? ESCAPE '\\' LIMIT 2000", (like,))
    best: dict[str, tuple] = {}
    for r in rows:
        lab = r["label"].lower().replace(" ", "")
        score = (0 if lab == key else 1 if lab.startswith(key) else 2,
                 {"pref": 0, "alt": 1, "hidden": 2}.get(r["label_type"], 3), 0 if r["status"] == "active" else 1,
                 len(r["label"]))
        if r["concept_id"] not in best or score < best[r["concept_id"]][0]:
            best[r["concept_id"]] = (score, r)
    out = []
    for score, r in sorted(best.values(), key=lambda x: (x[0], x[1]["pref_label_ko"]))[:max(1, min(limit, 50))]:
        via = r["label"] if r["label"] != r["pref_label_ko"] else None
        out.append({"concept_id": r["concept_id"], "pref_label": r["pref_label_ko"], "pref_label_en": r["pref_label_en"],
                    "scheme": r["scheme"], "key": SCHEME_KEY.get(r["scheme"], "Other"), "status": r["status"],
                    "matched": r["label"], "match_type": r["label_type"], "via": via, "exact": score[0] == 0})
    return out


def concept_detail(cid: str) -> dict:
    c = db.one("SELECT c.*, s.name AS scheme, k.label_ko AS class_ko, k.label_en AS class_en, k.iri AS class_iri "
               "FROM concept c LEFT JOIN concept_scheme s ON s.scheme_id=c.scheme_id "
               "LEFT JOIN onto_class k ON k.class_id=c.class_id WHERE c.concept_id=?", (cid,))
    if not c:
        raise KeyError(cid)
    labels = {"pref": [], "alt": [], "hidden": []}
    for l in db.rows("SELECT label, lang, label_type FROM concept_label WHERE concept_id=? ORDER BY label_type, label",
                     (cid,)):
        labels.setdefault(l["label_type"], []).append({"label": l["label"], "lang": l["lang"]})
    rel_q = ("SELECT r.rel_type, k.concept_id, k.pref_label_ko AS label, s.name AS scheme FROM concept_relation r "
             "JOIN concept k ON k.concept_id=r.{other} LEFT JOIN concept_scheme s ON s.scheme_id=k.scheme_id "
             "WHERE r.{me}=? ORDER BY r.rel_type, k.pref_label_ko")
    out_rel = db.rows(rel_q.format(other="target_concept_id", me="concept_id"), (cid,))
    in_rel = db.rows(rel_q.format(other="concept_id", me="target_concept_id"), (cid,))
    for r in out_rel + in_rel:
        r["rel_label"] = _rel_label(r["rel_type"])
        r["key"] = SCHEME_KEY.get(r["scheme"], "Other")
    docs = db.rows(
        "SELECT c.doc_id, COUNT(*) AS mentions, MIN(c.ord) AS first_ord FROM annotation a "
        "JOIN chunk c ON c.chunk_id=a.chunk_id WHERE a.concept_id=? AND a.status!='rejected' "
        "GROUP BY c.doc_id ORDER BY mentions DESC LIMIT 50", (cid,))
    info = _docs(d["doc_id"] for d in docs)
    documents = []
    for d in docs:
        i = info.get(d["doc_id"])
        if not i:
            continue
        first = db.one("SELECT c.chunk_id FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id "
                       "WHERE a.concept_id=? AND c.doc_id=? AND a.status!='rejected' ORDER BY c.ord LIMIT 1",
                       (cid, d["doc_id"]))
        documents.append({"doc_id": d["doc_id"], "file_name": i["file_name"], "title": i["title"],
                          "source_type": i["source_type"], "year": i["year"], "confidentiality": i["confidentiality"],
                          "mentions": d["mentions"], "first_chunk_id": first["chunk_id"] if first else None})
    bp = db.one("SELECT byproduct_id, sector FROM byproduct WHERE concept_id=?", (cid,))
    meas = []
    role = None
    sel = ("COUNT(*) AS n, COUNT(m.value) AS n_numeric, AVG(m.value) AS mean, MIN(m.value) AS min, MAX(m.value) AS max, "
           "COALESCE(m.unit_text,'') AS unit, COUNT(DISTINCT m.doc_id) AS docs, group_concat(DISTINCT m.entry) AS entries")
    if bp:  # 이 부산물에서 잰 항목들
        role = "byproduct"
        meas = db.rows(
            f"SELECT COALESCE(k.pref_label_ko, m.target_text) AS item, m.target_concept_id AS concept_id, {sel} "
            "FROM measurement m LEFT JOIN concept k ON k.concept_id=m.target_concept_id WHERE m.byproduct_id=? "
            "GROUP BY COALESCE(m.target_concept_id, m.target_text), COALESCE(m.unit_text,'') ORDER BY n DESC, item",
            (bp["byproduct_id"],))
    else:  # 이 항목을 잰 부산물들
        meas = db.rows(
            f"SELECT COALESCE(k.pref_label_ko, '(부산물 미상)') AS item, b.concept_id AS concept_id, {sel} "
            "FROM measurement m LEFT JOIN byproduct b ON b.byproduct_id=m.byproduct_id "
            "LEFT JOIN concept k ON k.concept_id=b.concept_id WHERE m.target_concept_id=? "
            "GROUP BY b.concept_id, COALESCE(m.unit_text,'') ORDER BY n DESC, item", (cid,))
        role = "target" if meas else None
    for m in meas:
        for k in ("mean", "min", "max"):
            m[k] = _r(m[k])
    return {"concept_id": cid, "pref_label": c["pref_label_ko"], "pref_label_en": c["pref_label_en"],
            "scheme": c["scheme"], "key": SCHEME_KEY.get(c["scheme"], "Other"),
            "class": {"label_ko": c["class_ko"], "label_en": c["class_en"], "iri": _full_iri(c["class_iri"])},
            "iri": _full_iri(c["iri"]), "curie": c["iri"], "origin": c["origin"], "status": c["status"],
            "definition": c["definition"], "labels": labels, "relations_out": out_rel, "relations_in": in_rel,
            "documents": documents, "byproduct": {"sector": bp["sector"]} if bp else None,
            "measurements": {"role": role, "rows": meas}}


def document_detail(doc_id: str) -> dict:
    d = _docs([doc_id]).get(doc_id)
    if not d:
        raise KeyError(doc_id)
    concepts = db.rows(
        "SELECT k.concept_id, k.pref_label_ko AS label, s.name AS scheme, COUNT(*) AS mentions FROM annotation a "
        "JOIN chunk c ON c.chunk_id=a.chunk_id JOIN concept k ON k.concept_id=a.concept_id "
        "LEFT JOIN concept_scheme s ON s.scheme_id=k.scheme_id WHERE c.doc_id=? AND a.status!='rejected' "
        "GROUP BY k.concept_id ORDER BY mentions DESC, label LIMIT 60", (doc_id,))
    for k in concepts:
        k["key"] = SCHEME_KEY.get(k["scheme"], "Other")
    first = db.one("SELECT chunk_id FROM chunk WHERE doc_id=? ORDER BY ord LIMIT 1", (doc_id,))
    return {**d, "concepts": concepts, "first_chunk_id": first["chunk_id"] if first else None,
            "measurements": db.one("SELECT COUNT(*) AS n FROM measurement WHERE doc_id=?", (doc_id,))["n"]}


def stats() -> dict:
    schemes = db.rows(
        "SELECT s.name AS scheme, COUNT(c.concept_id) AS concepts, "
        "SUM(CASE WHEN c.origin='mine' THEN 1 ELSE 0 END) AS mine FROM concept_scheme s "
        "LEFT JOIN concept c ON c.scheme_id=s.scheme_id GROUP BY s.name ORDER BY concepts DESC")
    for s in schemes:
        s["key"] = SCHEME_KEY.get(s["scheme"], "Other")
    rels = db.rows("SELECT rel_type, COUNT(*) AS n FROM concept_relation GROUP BY rel_type ORDER BY n DESC")
    for r in rels:
        r["label"] = _rel_label(r["rel_type"])
    labels = {r["label_type"]: r["n"] for r in db.rows(
        "SELECT label_type, COUNT(*) AS n FROM concept_label GROUP BY label_type")}
    m = db.one("SELECT COUNT(*) AS pairs, COALESCE(SUM(n),0) AS annotations, COUNT(DISTINCT doc_id) AS documents FROM ("
               "SELECT a.concept_id, c.doc_id, COUNT(*) AS n FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id "
               "WHERE a.concept_id IS NOT NULL AND a.status!='rejected' GROUP BY a.concept_id, c.doc_id)")
    meas = _measured()
    return {"concepts": sum(s["concepts"] for s in schemes), "schemes": schemes, "relations": rels,
            "labels": labels, "mentions": m, "measured": {"pairs": len(meas), "values": sum(x["n"] for x in meas)},
            "legend": {**REL_LABEL, OTHER: "기타 관계"}}


# ---------------------------------------------------------------- 내보내기

def export_ttl() -> str:
    """표준 시드(seed.ttl)와 내 확장(mine.ttl)을 합친 SKOS Turtle. 파일을 이어 붙이지 않고 지금 DB에서 만들므로
    작업대에서 배운 동의어까지 들어가고, 승인 전(제안) 개념은 빠진다."""
    parts = [db.TTL_PREFIX,
             f"# R&D Studio V0.5 — 온톨로지·시소러스 내보내기 ({datetime.now():%Y-%m-%d %H:%M})",
             "# 표준 시드(seed.ttl) + 내 확장(mine.ttl). SKOS 형식이라 Protégé·Skosmos 등에서 열 수 있습니다.", "",
             "# ---- 표준 시드", ""]
    for r in db.rows("SELECT concept_id FROM concept WHERE origin='seed' ORDER BY pref_label_ko"):
        parts.append(db.concept_ttl(r["concept_id"]))
    parts += ["# ---- 내 확장", ""]
    for r in db.rows("SELECT concept_id FROM concept WHERE origin='mine' AND status='active' ORDER BY pref_label_ko"):
        parts.append(db.concept_ttl(r["concept_id"]))
    return "\n".join(parts)


def export_json() -> dict:
    """전체 그래프(개념·관계·언급·측정). 기밀 자료 이름은 가리고, 기밀 자료·시료의 측정값은 뺀다."""
    C = {k: v for k, v in _concepts().items() if v["status"] == "active"}
    nodes = [{**_concept_node(c), "iri": _full_iri(c["iri"])} for c in C.values()]
    edges = []
    for r in db.rows("SELECT concept_id, target_concept_id, rel_type FROM concept_relation"):
        if r["concept_id"] in C and r["target_concept_id"] in C:
            t = r["rel_type"]
            edges.append({"source": r["concept_id"], "target": r["target_concept_id"],
                          "type": t if t in REL_LABEL else OTHER, "rel_type": t, "label": _rel_label(t)})
    for m in _measured(public_only=True):
        if m["source"] in C and m["target"] in C:
            edges.append({"type": "measured", "rel_type": "measured", "label": REL_LABEL["measured"], **m})
    men = _mentions()
    docs = _docs({x["doc_id"] for lst in men.values() for x in lst})
    for d in docs.values():
        nodes.append(_doc_node(d, mask=True))
    for k, lst in men.items():
        if k not in C:
            continue
        for x in lst:
            if x["doc_id"] in docs:
                edges.append({"source": "doc:" + x["doc_id"], "target": k, "type": "mentions", "rel_type": "mentions",
                              "label": REL_LABEL["mentions"], "count": x["n"]})
    return {"@context": {"skos": "http://www.w3.org/2004/02/skos/core#", "byo": "https://byorbit.kr/onto/"},
            "generator": "R&D Studio V0.5", "exported_at": datetime.now().isoformat(timespec="seconds"),
            "note": "기밀 자료 이름은 '기밀자료-xxxxxx'로 가렸고, 기밀 자료·시료의 측정값은 넣지 않았습니다. "
                    "로트·공급처·시료번호는 넣지 않습니다.",
            "legend": {**REL_LABEL, OTHER: "기타 관계"}, "nodes": nodes, "edges": edges}


# ---------------------------------------------------------------- 경로

@router.get("/search")
def api_search(q: str = "", limit: int = 15):
    return {"q": q, "results": search_concepts(q, limit)}


@router.get("/graph")
def api_graph(center: str = "", depth: int = 1, types: str = "", cap: int = NODE_CAP):
    try:
        return build_graph(center or None, depth, types or None, cap)
    except KeyError:
        raise HTTPException(404, f"'{center}' 개념을 찾지 못했습니다. 위 검색창에서 표준명이나 동의어로 찾아 보세요.")


@router.get("/concept/{cid}")
def api_concept(cid: str):
    try:
        return concept_detail(cid)
    except KeyError:
        raise HTTPException(404, "개념이 없습니다. 지운 개념일 수 있으니 그래프를 새로 불러오세요.")


@router.get("/document/{doc_id}")
def api_document(doc_id: str):
    try:
        return document_detail(doc_id)
    except KeyError:
        raise HTTPException(404, "자료가 없습니다. 자료함에서 지웠다면 그래프를 새로 불러오세요.")


@router.get("/stats")
def api_stats():
    return stats()


@router.get("/export.ttl")
def api_export_ttl():
    return Response(export_ttl(), media_type="text/turtle; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="rd-studio-ontology.ttl"'})


@router.get("/export.json")
def api_export_json():
    import json
    return Response(json.dumps(export_json(), ensure_ascii=False, indent=1), media_type="application/json; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="rd-studio-knowledge-graph.json"'})
