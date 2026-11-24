"""로컬 웹앱 (FastAPI). 127.0.0.1에서만 열린다 — 같은 PC의 브라우저 전용."""
from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, engines, search as _search, thesaurus, tools
from .engines import claude_code, food_mcp
from .ingest import parsers, pipeline, watcher

STATIC = Path(__file__).with_name("static")
app = FastAPI(title="ByOrbit R&D Studio (개인용)", version=config.APP_VERSION)


@app.on_event("startup")
def _startup():
    db.init(seed=True)
    claude_code.write_mcp_config()
    if config.load_settings().get("watch_inbox") and not getattr(app.state, "no_watch", False):
        watcher.start()


# ---------------------------------------------------------------- 백그라운드 작업

JOBS: dict[str, dict] = {}


def _job(kind: str, fn, *args, **kw) -> dict:
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"job_id": jid, "kind": kind, "status": "running", "started": time.time()}

    def go():
        try:
            JOBS[jid]["result"] = fn(*args, **kw)
            JOBS[jid]["status"] = "done"
        except Exception as e:  # noqa: BLE001
            JOBS[jid]["status"] = "error"
            JOBS[jid]["error"] = str(e)
        JOBS[jid]["finished"] = time.time()

    threading.Thread(target=go, daemon=True).start()
    return JOBS[jid]


@app.get("/api/jobs/{jid}")
def job(jid: str):
    if jid not in JOBS:
        raise HTTPException(404, "작업 없음")
    return JOBS[jid]


# ---------------------------------------------------------------- 상태·설정

@app.get("/api/health")
def health():
    counts = {t: db.one(f"SELECT COUNT(*) AS n FROM {t}")["n"]
              for t in ("document", "chunk", "annotation", "measurement", "concept", "report")}
    counts["pending"] = db.one("SELECT COUNT(*) AS n FROM annotation WHERE status='pending'")["n"]
    return {"ok": True, "version": config.APP_VERSION, "data_home": str(config.data_home()),
            "counts": counts, "settings": config.load_settings(),
            "claude": {"path": claude_code.executable()}}


class SettingsIn(BaseModel):
    default_project: str | None = None
    engine: str | None = None
    coa_rule: str | None = None
    watch_inbox: bool | None = None
    claude_timeout_sec: int | None = None
    food_mcp: bool | None = None
    food_mcp_dir: str | None = None


@app.get("/api/settings")
def get_settings():
    return config.load_settings()


@app.post("/api/settings")
def set_settings(s: SettingsIn):
    upd = {k: v for k, v in s.model_dump().items() if v is not None}
    if "coa_rule" in upd and upd["coa_rule"] not in ("mask", "block"):
        raise HTTPException(400, "coa_rule은 mask 또는 block")
    if "engine" in upd and upd["engine"] not in ("claude", "codex"):
        raise HTTPException(400, "engine은 claude 또는 codex")
    if "default_project" in upd:
        db.ensure_project(upd["default_project"])
    if "food_mcp_dir" in upd:
        d = upd["food_mcp_dir"] = upd["food_mcp_dir"].strip().strip('"')
        if d and not Path(d).expanduser().joinpath("mcp", "food-db-server.mjs").is_file():
            raise HTTPException(400, f"'{d}'에 mcp\\food-db-server.mjs가 없습니다. "
                                     "04_byorbit-agent 폴더(그 안에 mcp 폴더가 있는 곳)의 경로를 넣거나, 비워 두면 자동으로 찾습니다.")
    saved = config.save_settings(upd)
    claude_code.write_mcp_config()  # 식품 DB 켜기·끄기를 MCP 설정에 바로 반영
    return saved


@app.get("/api/engines/check")
def engines_check(smoke: bool = False):
    if smoke:
        return _job("check", claude_code.check, smoke=True)
    return {"claude": claude_code.check(smoke=False), "codex": engines.codex.check(), "food": food_mcp.status()}


@app.post("/api/engines/food/check")
def food_check():
    """식품 DB 서버를 띄워 도구 목록까지 받아 본다(백그라운드 작업). DB 조회는 하지 않는다."""
    return _job("food-check", food_mcp.check)


# ---------------------------------------------------------------- 프로젝트

class ProjectIn(BaseModel):
    name: str
    description: str = ""


@app.get("/api/projects")
def projects():
    return db.rows(
        "SELECT p.project_id, p.name, p.description, p.created_at, "
        "(SELECT COUNT(*) FROM project_item i WHERE i.project_id=p.project_id AND i.entity_type='document') AS documents "
        "FROM project p ORDER BY p.created_at")


@app.post("/api/projects")
def add_project(p: ProjectIn):
    name = p.name.strip()
    if not name:
        raise HTTPException(400, "이름을 입력하세요")
    return {"project_id": db.ensure_project(name, p.description)}


# ---------------------------------------------------------------- 자료

@app.get("/api/documents")
def documents(project: str | None = None):
    sql = ("SELECT d.doc_id, d.file_name, d.parse_status, d.note, d.created_at, s.source_type, s.title, s.year, "
           "s.confidentiality, (SELECT COUNT(*) FROM chunk c WHERE c.doc_id=d.doc_id) AS chunks, "
           "(SELECT COUNT(*) FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id WHERE c.doc_id=d.doc_id) AS annotations, "
           "(SELECT COUNT(*) FROM measurement m WHERE m.doc_id=d.doc_id) AS measurements, "
           "(SELECT group_concat(p.name, ', ') FROM project_item i JOIN project p ON p.project_id=i.project_id "
           " WHERE i.entity_type='document' AND i.entity_id=d.doc_id) AS projects "
           "FROM document d JOIN source s ON s.source_id=d.source_id")
    params = []
    if project:
        sql += (" WHERE d.doc_id IN (SELECT entity_id FROM project_item i JOIN project p ON p.project_id=i.project_id "
                "WHERE p.name=? AND i.entity_type='document')")
        params.append(project)
    out = db.rows(sql + " ORDER BY d.created_at DESC", params)
    for r in out:
        r["parse_status"] = json.loads(r["parse_status"] or "{}")
    return out


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), project: str = Form(""), confidentiality: str = Form("내부")):
    if confidentiality not in ("일반", "내부", "기밀"):
        raise HTTPException(400, "보안 등급은 일반·내부·기밀 중 하나")
    tmp_dir = config.path("inbox", ".uploads")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for f in files:
        name = Path(f.filename or "upload").name
        tmp = tmp_dir / f"{uuid.uuid4().hex[:6]}-{name}"
        with open(tmp, "wb") as out:
            shutil.copyfileobj(f.file, out)
        final = tmp.with_name(name)
        if final.exists():
            final = tmp
        else:
            tmp.rename(final)
        try:
            results.append(pipeline.ingest_file(final, project or None, confidentiality, move=True))
        except pipeline.Duplicate as d:
            results.append({"file_name": name, "duplicate_of": d.doc_id})
        except parsers.UnsupportedFile as e:
            results.append({"file_name": name, "error": str(e)})
        finally:
            if final.exists():
                final.unlink()
    return {"results": results}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str, remove_file: bool = True):
    pipeline.delete_document(doc_id, remove_file=remove_file)
    return {"ok": True}


@app.post("/api/documents/{doc_id}/reprocess")
def reprocess(doc_id: str):
    try:
        return pipeline.reprocess(doc_id)
    except KeyError:
        raise HTTPException(404, "자료 없음")


@app.get("/api/documents/{doc_id}/chunks")
def doc_chunks(doc_id: str):
    return db.rows("SELECT c.chunk_id, c.chunk_type, c.ord, c.page, c.text, s.heading, "
                   "(SELECT COUNT(*) FROM annotation a WHERE a.chunk_id=c.chunk_id) AS annotations "
                   "FROM chunk c LEFT JOIN doc_section s ON s.section_id=c.section_id WHERE c.doc_id=? ORDER BY c.ord",
                   (doc_id,))


@app.get("/api/documents/{doc_id}/file")
def doc_file(doc_id: str):
    d = db.one("SELECT file_uri, file_name FROM document WHERE doc_id=?", (doc_id,))
    if not d or not Path(d["file_uri"]).exists():
        raise HTTPException(404, "파일 없음")
    return FileResponse(d["file_uri"], filename=d["file_name"])


@app.get("/api/inbox/recent")
def inbox_recent():
    return {"inbox": str(config.path("inbox")), "recent": watcher.recent}


@app.post("/api/inbox/scan")
def inbox_scan():
    return {"results": watcher.scan_once()}


# ---------------------------------------------------------------- 검색·개념

@app.get("/api/search")
def search(q: str, project: str | None = None, limit: int = 20):
    return _search.search(q, project=project or None, limit=min(limit, 100))


@app.get("/api/chunks/{chunk_id}")
def chunk(chunk_id: str):
    c = db.one("SELECT c.*, d.file_name, s.heading FROM chunk c JOIN document d ON d.doc_id=c.doc_id "
               "LEFT JOIN doc_section s ON s.section_id=c.section_id WHERE c.chunk_id=?", (chunk_id,))
    if not c:
        raise HTTPException(404, "청크 없음")
    c["annotations"] = db.rows("SELECT a.*, k.pref_label_ko AS concept FROM annotation a "
                               "LEFT JOIN concept k ON k.concept_id=a.concept_id WHERE chunk_id=? ORDER BY span_start",
                               (chunk_id,))
    return c


@app.get("/api/concepts")
def concepts(q: str = "", scheme: str = "", origin: str = "", limit: int = 300):
    where, params = ["1=1"], []
    if q:
        where.append("c.concept_id IN (SELECT concept_id FROM concept_label WHERE label LIKE ?)")
        params.append(f"%{q}%")
    if scheme:
        where.append("s.name=?")
        params.append(scheme)
    if origin:
        where.append("c.origin=?")
        params.append(origin)
    rows = db.rows(
        "SELECT c.concept_id, c.pref_label_ko, c.pref_label_en, c.origin, c.status, s.name AS scheme, "
        "(SELECT group_concat(label, ' · ') FROM concept_label l WHERE l.concept_id=c.concept_id AND l.label_type!='pref') AS alts, "
        "(SELECT COUNT(*) FROM annotation a WHERE a.concept_id=c.concept_id) AS uses "
        "FROM concept c LEFT JOIN concept_scheme s ON s.scheme_id=c.scheme_id WHERE " + " AND ".join(where) +
        " ORDER BY s.name, c.pref_label_ko LIMIT ?", params + [min(limit, 2000)])
    return rows


@app.get("/api/concepts/tree")
def concept_tree():
    cats = db.rows("SELECT c.concept_id, c.pref_label_ko, c.iri FROM concept c JOIN concept_scheme s "
                   "ON s.scheme_id=c.scheme_id WHERE s.name='분류'")
    rel = db.rows("SELECT r.concept_id, r.target_concept_id FROM concept_relation r WHERE r.rel_type='broader'")
    names = {c["concept_id"]: c["pref_label_ko"] for c in db.rows("SELECT concept_id, pref_label_ko FROM concept")}
    children: dict[str, list] = {}
    for r in rel:
        children.setdefault(r["target_concept_id"], []).append(r["concept_id"])
    top = [c for c in cats if not any(r["concept_id"] == c["concept_id"] for r in rel)]

    def node(cid):
        return {"id": cid, "label": names.get(cid), "children": [node(k) for k in sorted(children.get(cid, []),
                                                                                        key=lambda x: names.get(x, ""))]}
    order = ["농업", "임업", "수산", "축산"]
    return sorted([node(c["concept_id"]) for c in top], key=lambda n: order.index(n["label"]) if n["label"] in order else 9)


class ConceptIn(BaseModel):
    label: str
    scheme: str
    alt_labels: list[str] = []
    definition: str | None = None
    broader: str | None = None


@app.post("/api/concepts")
def add_concept(c: ConceptIn):
    r = tools.propose_concept(c.label, c.scheme, c.alt_labels, c.definition, c.broader)
    if r.get("concept_id"):
        approve_concept(r["concept_id"])
        r["status"] = "active"
    return r


@app.post("/api/concepts/{cid}/approve")
def approve_concept(cid: str):
    c = db.one("SELECT * FROM concept WHERE concept_id=?", (cid,))
    if not c:
        raise HTTPException(404, "개념 없음")
    with db.tx() as t:
        t.execute("UPDATE concept SET status='active' WHERE concept_id=?", (cid,))
        db.log_change(t, "concept", cid, {"status": c["status"]}, {"status": "active"})
    with open(config.path("ontology", "mine.ttl"), "a", encoding="utf-8") as f:
        f.write("\n" + db.concept_ttl(cid))
    thesaurus.invalidate()
    return {"ok": True}


@app.get("/api/lookup")
def lookup(term: str):
    return tools.lookup_concept(term)


# ---------------------------------------------------------------- 라벨 검토

@app.get("/api/annotations")
def annotations(status: str = "pending", project: str | None = None, limit: int = 200):
    sql = ("SELECT a.ann_id, a.surface_text, a.label_type, a.normalized_value, a.confidence, a.method, a.status, "
           "a.engine, k.pref_label_ko AS concept, c.chunk_id, c.text AS chunk_text, a.span_start, a.span_end, "
           "d.file_name, d.doc_id FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id "
           "JOIN document d ON d.doc_id=c.doc_id LEFT JOIN concept k ON k.concept_id=a.concept_id WHERE a.status=?")
    params: list = [status]
    if project:
        sql += (" AND d.doc_id IN (SELECT entity_id FROM project_item i JOIN project p ON p.project_id=i.project_id "
                "WHERE p.name=? AND i.entity_type='document')")
        params.append(project)
    rows = db.rows(sql + " ORDER BY a.created_at DESC LIMIT ?", params + [min(limit, 1000)])
    for r in rows:
        t, a, b = r.pop("chunk_text"), r["span_start"] or 0, r["span_end"] or 0
        r["context"] = {"before": t[max(0, a - 70):a], "hit": t[a:b], "after": t[b:b + 70]}
    return rows


class Review(BaseModel):
    status: str  # accepted | rejected


@app.post("/api/annotations/{ann_id}")
def review(ann_id: str, r: Review):
    if r.status not in ("accepted", "rejected"):
        raise HTTPException(400, "accepted 또는 rejected")
    a = db.one("SELECT * FROM annotation WHERE ann_id=?", (ann_id,))
    if not a:
        raise HTTPException(404, "라벨 없음")
    meas = None
    with db.tx() as t:
        t.execute("UPDATE annotation SET status=?, reviewed_at=datetime('now') WHERE ann_id=?", (r.status, ann_id))
        db.log_change(t, "annotation", ann_id, {"status": a["status"]}, {"status": r.status})
        # 승인된 수치 라벨 → 측정값(entry=extracted)으로 올린다
        if r.status == "accepted" and a["normalized_value"]:
            v = json.loads(a["normalized_value"])
            doc = t.execute("SELECT doc_id FROM chunk WHERE chunk_id=?", (a["chunk_id"],)).fetchone()[0]
            try:
                value = float(str(v.get("value")).replace(",", ""))
            except (TypeError, ValueError):
                value = None
            target = v.get("target") or a["surface_text"]
            meas = db.new_id()
            t.execute("INSERT INTO measurement(meas_id, target_concept_id, target_text, value, value_text, unit_concept_id, "
                      "unit_text, basis, ann_id, doc_id, entry, verified_at) VALUES (?,?,?,?,?,?,?,?,?,?, 'extracted', datetime('now'))",
                      (meas, a["concept_id"], target, value, str(v.get("value")), a["unit_concept_id"], v.get("unit"),
                       v.get("basis"), ann_id, doc))
    return {"ok": True, "measurement_id": meas}


# ---------------------------------------------------------------- 측정값

@app.get("/api/measurements")
def measurements(byproduct: str = "", target: str = "", project: str = ""):
    # 내 PC 화면에서는 시료 식별 정보도 보여준다(AI에 넘길 때만 가린다)
    rows = tools.measurements_query(byproduct or None, target or None, project or None, limit=500, apply_rule=False)["rows"]
    ids = [r["meas_id"] for r in rows]
    if ids:
        extra = {r["meas_id"]: r for r in db.rows(
            "SELECT m.meas_id, s.lot_no, s.supplier, s.sample_code, s.collected_at, d.file_name FROM measurement m "
            "LEFT JOIN sample s ON s.sample_id=m.sample_id LEFT JOIN document d ON d.doc_id=m.doc_id "
            "WHERE m.meas_id IN (%s)" % ",".join("?" * len(ids)), ids)}
        for r in rows:
            r.update({k: v for k, v in extra.get(r["meas_id"], {}).items() if k != "meas_id"})
    return rows


@app.get("/api/byproducts")
def byproducts():
    return db.rows("SELECT b.byproduct_id, k.pref_label_ko AS name, b.sector, "
                   "(SELECT COUNT(*) FROM measurement m WHERE m.byproduct_id=b.byproduct_id) AS measurements "
                   "FROM byproduct b JOIN concept k ON k.concept_id=b.concept_id ORDER BY b.sector, k.pref_label_ko")


# ---------------------------------------------------------------- AI (Claude Code)

class AskIn(BaseModel):
    prompt: str
    project: str | None = None
    role: str | None = "librarian"
    write: bool = False


@app.post("/api/ask")
def ask(a: AskIn):
    """자료에 질문 — Claude Code가 MCP 도구로 이 PC의 자료를 찾아 답한다(백그라운드 작업)."""
    eng = engines.get()
    proj = f"\n\n(프로젝트 '{a.project}' 자료를 우선 검색하세요: search_chunks에 project='{a.project}')" if a.project else ""
    return _job("ask", eng.run, a.prompt + proj, role=a.role, write=a.write, task="ask")


class LabelIn(BaseModel):
    doc_id: str
    max_chunks: int = 20


@app.post("/api/label")
def label(l: LabelIn):
    """(베타) 라벨러 지침으로 Claude Code가 청크를 읽고 save_annotations로 라벨을 제안한다."""
    ids = [r["chunk_id"] for r in db.rows("SELECT chunk_id FROM chunk WHERE doc_id=? ORDER BY ord LIMIT ?",
                                          (l.doc_id, min(l.max_chunks, 100)))]
    if not ids:
        raise HTTPException(404, "청크 없음")
    prompt = ("다음 청크들을 차례로 get_chunk로 읽고, 지침에 따라 save_annotations로 라벨을 저장하세요. "
              "다 끝나면 저장 건수만 한 줄로 보고하세요.\n" + "\n".join(ids))

    def go():
        r = engines.get().run(prompt, role="labeler", write=True, max_turns=12 + 3 * len(ids), task="label")
        if r.get("ok"):
            d = db.one("SELECT parse_status FROM document WHERE doc_id=?", (l.doc_id,))
            st = json.loads(d["parse_status"])
            st["label"] = "llm"
            with db.tx() as t:
                t.execute("UPDATE document SET parse_status=? WHERE doc_id=?", (json.dumps(st), l.doc_id))
        return r
    return _job("label", go)


@app.get("/api/reports")
def reports():
    return db.rows("SELECT report_id, title, status, created_at, (SELECT COUNT(*) FROM report_citation c "
                   "WHERE c.report_id=r.report_id) AS citations FROM report r ORDER BY created_at DESC")


@app.get("/api/reports/{rid}")
def report(rid: str):
    r = db.one("SELECT * FROM report WHERE report_id=?", (rid,))
    if not r:
        raise HTTPException(404, "리포트 없음")
    r["citations"] = db.rows("SELECT * FROM report_citation WHERE report_id=?", (rid,))
    return r


@app.get("/api/schema")
def schema():
    return {t: [c["name"] for c in db.rows(f"PRAGMA table_info({t})")] for t in db.table_names()}


# ---------------------------------------------------------------- 화면

@app.exception_handler(Exception)
async def _err(request, exc):
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
