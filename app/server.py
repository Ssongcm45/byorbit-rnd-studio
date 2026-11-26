"""로컬 웹앱 (FastAPI). 127.0.0.1에서만 열린다 — 같은 PC의 브라우저 전용."""
from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, engines, labeling, search as _search, thesaurus, tools
from . import routes_collect, routes_experiment, routes_kg, routes_parse, routes_predict, routes_stats, routes_viz, routes_workbench
from .collect import scheduler as collect_scheduler
from .engines import claude_code, food_mcp
from .ingest import parsers, pipeline, watcher

STATIC = Path(__file__).with_name("static")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    db.init(seed=True)
    claude_code.write_mcp_config()
    labeling.mark_interrupted()  # 지난번에 끝나지 못한 AI 라벨 실행 → '중단됨' (이어하기 가능)
    if config.load_settings().get("watch_inbox") and not getattr(app.state, "no_watch", False):
        watcher.start()
    if not getattr(app.state, "no_watch", False):
        collect_scheduler.start()  # 저장 검색 자동 실행(앱이 켜져 있는 동안). BYORBIT_COLLECT_SCHEDULER=0이면 끔
    yield
    collect_scheduler.stop()


app = FastAPI(title="R&D Studio V0.5", version=config.APP_VERSION, lifespan=_lifespan)


# ---------------------------------------------------------------- 접근 방어 (DNS 리바인딩·CSRF)

LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
# FastAPI TestClient가 보내는 Host. 실제 브라우저가 이 이름으로 이 PC에 닿으려면 DNS 조작이 아니라
# hosts 파일 수정이 필요하므로(이미 PC를 장악한 상태) 시험용으로 허용한다.
TEST_HOSTS = {"testserver"}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _split_host(h: str) -> tuple[str, str]:
    h = (h or "").strip().lower()
    if h.startswith("["):
        host, _, rest = h.partition("]")
        return host + "]", rest.lstrip(":")
    host, _, port = h.partition(":")
    return host, port


@app.middleware("http")
async def _guard(request: Request, call_next):
    host, port = _split_host(request.headers.get("host", ""))
    if host not in LOCAL_HOSTS and host not in TEST_HOSTS:
        return JSONResponse(status_code=403, content={
            "detail": "이 PC의 주소(http://127.0.0.1:포트)로만 열 수 있습니다. 주소창에 127.0.0.1을 쓰세요."})
    if request.method in UNSAFE:
        origin = request.headers.get("origin")
        if origin is None and request.headers.get("referer"):
            u = urlsplit(request.headers["referer"])
            origin = f"{u.scheme}://{u.netloc}"
        if origin is not None:
            u = urlsplit(origin)
            o_host, o_port = _split_host(u.netloc)
            same = (u.scheme == "http" and o_host in LOCAL_HOSTS and o_port == port) or \
                   (host in TEST_HOSTS and o_host in TEST_HOSTS)
            if not same:
                return JSONResponse(status_code=403, content={
                    "detail": "다른 사이트에서 온 요청은 막습니다. 이 앱 화면(127.0.0.1)에서 다시 시도하세요."})
    return await call_next(request)


# ---------------------------------------------------------------- 백그라운드 작업

JOBS: dict[str, dict] = {}
JOB_TTL_SEC = 3600
JOB_CAP = 200


def _prune_jobs(now: float | None = None) -> None:
    """끝난 지 1시간 지난 작업을 지우고, 전체를 200건 이하로 유지한다(끝난 것 중 오래된 것부터)."""
    now = now or time.time()
    for jid in [j for j, v in JOBS.items() if v["status"] != "running" and now - v.get("finished", now) > JOB_TTL_SEC]:
        JOBS.pop(jid, None)
    if len(JOBS) > JOB_CAP:
        done = sorted((v.get("finished", 0), j) for j, v in JOBS.items() if v["status"] != "running")
        for _, jid in done[:len(JOBS) - JOB_CAP]:
            JOBS.pop(jid, None)


def _job(kind: str, fn, *args, **kw) -> dict:
    _prune_jobs()
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


class SamplesIn(BaseModel):
    project: str | None = None


@app.post("/api/samples")
def add_samples(s: SamplesIn):
    """예시 자료(가짜 수치의 논문 PDF·CoA·HWPX·메모)를 받은편지함에 만들고 바로 처리한다 — 시작 화면의 '예시 자료 넣기'.
    `python -m app.cli samples`와 같은 파일. 이미 넣었으면 중복으로 건너뛴다."""
    from .sample_files import make_samples
    proj = (s.project or "").strip()
    if any(c in proj for c in r'\/:*?"<>|') or proj in (".", ".."):
        raise HTTPException(400, r'프로젝트 이름에 \ / : * ? " < > | 는 쓸 수 없습니다')
    if proj:
        db.ensure_project(proj)
    tmp = config.path("inbox", ".samples")  # 점(.) 폴더는 받은편지함 감시가 건너뛴다
    shutil.rmtree(tmp, ignore_errors=True)
    files = make_samples(tmp)
    have = {r["file_name"] for r in db.rows("SELECT file_name FROM document")}
    dest = config.path("inbox", proj) if proj else config.path("inbox")
    dest.mkdir(parents=True, exist_ok=True)
    new, skipped = [], []
    for p in files.values():  # 만들 때마다 바이트가 달라 해시 중복으로 안 걸리므로 파일 이름으로 한 번만 넣는다
        if p.name in have:
            skipped.append(p.name)
        else:
            shutil.move(str(p), str(dest / p.name))
            new.append(p.name)
    shutil.rmtree(tmp, ignore_errors=True)
    results = watcher.scan_once() if new else []
    return {"files": new, "skipped": skipped, "results": results}


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
    status: str  # accepted | rejected | pending·auto(되돌리기)
    learn: bool = False  # 거절한 사전 라벨을 부정 사례로 배운다(다음부터 같은 표기 건너뜀). 되돌리기에 주면 배운 것도 끈다


def _doc_byproduct(t, doc_id: str) -> str | None:
    """자료의 부산물: CoA 시료 → 없으면 그 자료에 가장 많이 붙은 부산물 라벨(거절 제외)."""
    r = t.execute("SELECT byproduct_id FROM sample WHERE coa_doc_id=? AND byproduct_id IS NOT NULL LIMIT 1",
                  (doc_id,)).fetchone()
    if r:
        return r[0]
    r = t.execute("SELECT b.byproduct_id, COUNT(*) AS n FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id "
                  "JOIN byproduct b ON b.concept_id=a.concept_id WHERE c.doc_id=? AND a.status!='rejected' "
                  "GROUP BY b.byproduct_id ORDER BY n DESC, MIN(c.ord) LIMIT 1", (doc_id,)).fetchone()
    return r[0] if r else None


@app.post("/api/annotations/{ann_id}")
def review(ann_id: str, r: Review):
    """라벨 검토 — 작업대와 같은 함수(labeling.review_annotation). learn=True면 거절한 사전 라벨을 부정 사례로 배운다(기본 끔)."""
    try:
        return labeling.review_annotation(ann_id, r.status, learn=r.learn)
    except KeyError:
        raise HTTPException(404, "라벨 없음")
    except labeling.ManualError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- 측정값

@app.get("/api/measurements")
def measurements(byproduct: str = "", target: str = "", project: str = ""):
    # 내 PC 화면에서는 시료 식별 정보도 보여준다(AI에 넘길 때만 가린다).
    # doc_id·chunk_id(추출값은 승인한 라벨의 청크)로 화면에서 근거 자료를 바로 연다.
    rows = tools.measurements_query(byproduct or None, target or None, project or None, limit=500, apply_rule=False)["rows"]
    ids = [r["meas_id"] for r in rows]
    if ids:
        extra = {r["meas_id"]: r for r in db.rows(
            "SELECT m.meas_id, s.lot_no, s.supplier, s.sample_code, s.collected_at, d.file_name, a.chunk_id FROM measurement m "
            "LEFT JOIN sample s ON s.sample_id=m.sample_id LEFT JOIN document d ON d.doc_id=m.doc_id "
            "LEFT JOIN annotation a ON a.ann_id=m.ann_id "
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
    max_chunks: int | None = None
    batch_size: int = labeling.DEFAULT_BATCH
    force: bool = False


@app.post("/api/label")
def label(l: LabelIn):
    """AI 라벨 실행 시작: 청크를 batch_size개씩 묶어 라벨러(Claude Code)에 맡긴다. 진행은 /api/label/runs/{run_id}."""
    try:
        return {"run_id": labeling.start(l.doc_id, l.max_chunks, l.batch_size, l.force)}
    except labeling.LabelError as e:
        raise HTTPException(404, str(e))


@app.get("/api/label/runs")
def label_runs(doc_id: str | None = None, limit: int = 50):
    return labeling.list_runs(doc_id or None, limit=min(limit, 200))


@app.get("/api/label/runs/{run_id}")
def label_run(run_id: str):
    try:
        return labeling.status(run_id)
    except KeyError:
        raise HTTPException(404, "라벨 실행 기록이 없습니다. 자료함에서 'AI 라벨'을 다시 누르세요.")


@app.post("/api/label/runs/{run_id}/cancel")
def label_cancel(run_id: str):
    try:
        return labeling.cancel(run_id)
    except KeyError:
        raise HTTPException(404, "라벨 실행 기록이 없습니다. 자료함을 새로고침하세요.")


@app.post("/api/label/runs/{run_id}/resume")
def label_resume(run_id: str):
    try:
        return labeling.resume(run_id)
    except KeyError:
        raise HTTPException(404, "라벨 실행 기록이 없습니다. 자료함을 새로고침하세요.")
    except labeling.LabelError as e:
        raise HTTPException(409, str(e))


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


app.include_router(routes_viz.router)  # /api/viz — 흐름·건조 방식·분자 구조
app.include_router(routes_collect.router)  # /api/collect — 자료 수집·수집함·저장 검색·크롤러 사이트
app.include_router(routes_experiment.router)  # /api/exp — 내 실험(공정 흐름·런·비교·보정)
app.include_router(routes_parse.router)  # /api/parse — 파서 선택·다시 파싱·나란히 비교·다시 청킹
app.include_router(routes_workbench.router)  # /api/wb — 문서 작업대(청크 검사·고치기·규칙·사람 라벨·배운 것)
app.include_router(routes_stats.router)  # /api/stats — 통계 분석(회귀·t검정·논문용 표·그림)
app.include_router(routes_predict.router)  # /api/viz/predict — 건조 조건 → 예상 결과(근거 포함)
app.include_router(routes_kg.router)  # /api/kg — 지식그래프(개념·관계·언급 자료·측정값)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
