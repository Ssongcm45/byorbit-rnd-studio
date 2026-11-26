"""파서 선택 API — /api/parse. 메인 앱이 app.include_router(routes_parse.router)로 붙인다.

문서마다 파서 도구를 골라 다시 파싱하고, 결과를 나란히 비교하고, 고른 결과로 다시 청킹한다.
클라우드 도구(Upstage)만 문서 파일을 밖으로 보낸다: '기밀' → 403, '내부'는 confirm_cloud=true가 있어야 한다(409).

작업 상태(/jobs)는 메모리 + `<데이터 폴더>/config/parse_jobs.json`(최근 200개)에 남긴다. 앱을 다시 켠 뒤 첫 요청 때
끝나지 못한 'running' 작업(이전 실행에서 시작한 것)을 'interrupted'(중단됨)로 바꾼다 — server.py를 고치지 않아도 된다.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import config
from .ingest import parser_tools as PT
from .ingest.parser_tools import results as R

router = APIRouter(prefix="/api/parse", tags=["파서 선택"])

NOTICE = ("로컬 도구는 문서를 이 PC 안에서만 읽습니다. 클라우드 도구(Upstage)는 문서 파일을 Upstage 서버로 보내며, "
          "'기밀' 문서는 보낼 수 없습니다.")

JOBS: dict[str, dict] = {}
JOB_TTL_SEC = 3600
JOBS_KEEP = 200
BOOT = uuid.uuid4().hex[:12]       # 이 앱 실행의 표시 — 다른 실행에서 'running'으로 남은 작업은 중단된 것
_jobs_lock = threading.RLock()
_loaded: set[str] = set()
INTERRUPTED_MSG = "앱이 꺼지거나 다시 켜져 작업이 중단되었습니다. 같은 도구로 다시 실행하세요(이미 저장된 결과는 결과 목록에 있습니다)."


def _jobs_file():
    return config.path("config", "parse_jobs.json")


def _public(j: dict) -> dict:
    return {k: v for k, v in j.items() if not k.startswith("_")}


def _ensure_loaded() -> None:
    """데이터 폴더마다 한 번: 파일의 작업을 읽고, 이전 실행에서 끝나지 못한 작업을 '중단됨'으로 바꾼다."""
    f = _jobs_file()
    key = str(f)
    with _jobs_lock:
        if key in _loaded:
            return
        _loaded.add(key)
        try:
            saved = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        except (OSError, ValueError):
            saved = []
        changed = False
        for j in saved if isinstance(saved, list) else []:
            if not isinstance(j, dict) or not j.get("job_id"):
                continue
            if j.get("status") == "running" and j.get("boot") != BOOT:
                j.update(status="interrupted", error=INTERRUPTED_MSG, finished=j.get("finished") or time.time())
                changed = True
            j["_home"] = key
            JOBS.setdefault(j["job_id"], j)
        if changed:
            _save_locked(key)


def _save_locked(key: str | None = None) -> None:
    f = _jobs_file()
    key = key or str(f)
    mine = sorted((j for j in JOBS.values() if j.get("_home") == key), key=lambda j: j.get("started") or 0)[-JOBS_KEEP:]
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps([_public(j) for j in mine], ensure_ascii=False, default=str), encoding="utf-8")
        for i in range(20):  # Windows: 누가 파일을 읽는 순간에는 바꾸기가 거절된다 → 잠깐 뒤 다시
            try:
                os.replace(tmp, f)
                break
            except PermissionError:
                if i == 19:
                    raise
                time.sleep(0.025)
    except OSError:
        pass  # 기록을 못 해도 작업 자체는 계속한다(메모리 상태는 그대로)


def _persist(job: dict) -> None:
    with _jobs_lock:
        _save_locked(job.get("_home"))


def _err(e: Exception) -> HTTPException:
    if isinstance(e, PT.CloudBlocked):
        return HTTPException(403, str(e))
    if isinstance(e, PT.NeedsConfirm):
        return HTTPException(409, str(e))
    if isinstance(e, R.NotFound):
        return HTTPException(404, str(e))
    if isinstance(e, KeyError):
        return HTTPException(404, "자료를 찾지 못했습니다. 자료함에서 다시 고르세요.")
    return HTTPException(400, str(e))


def _prune() -> None:
    """메모리에서만 오래된 끝난 작업을 뺀다(파일에는 최근 200개가 남아 다시 켠 뒤에도 문서별 목록에 보인다)."""
    now = time.time()
    with _jobs_lock:
        for jid in [j for j, v in JOBS.items() if v["status"] != "running" and now - (v.get("finished") or now) > JOB_TTL_SEC
                    and v.get("boot") == BOOT]:
            JOBS.pop(jid, None)


def _start(kind: str, fn, *args, doc_id: str | None = None, tool: str | None = None, **kw) -> dict:
    _ensure_loaded()
    _prune()
    jid = uuid.uuid4().hex[:12]
    job = {"job_id": jid, "kind": kind, "status": "running", "started": time.time(), "doc_id": doc_id, "tool": tool,
           "boot": BOOT, "_home": str(_jobs_file())}
    with _jobs_lock:
        JOBS[jid] = job
    _persist(job)

    def go():
        upd: dict = {}
        try:
            res = fn(*args, **kw)
            upd["result"] = res
            upd["status"] = "done" if res.get("status") != "error" else "error"
            if upd["status"] == "error":
                upd["error"] = res.get("error")
        except Exception as e:  # noqa: BLE001
            upd.update(status="error", error=str(e))
        upd["finished"] = time.time()
        with _jobs_lock:   # 상태·끝난 시각을 한 번에 바꾼다(폴링하는 쪽이 반쯤 바뀐 작업을 보지 않게)
            job.update(upd)
        _persist(job)

    threading.Thread(target=go, daemon=True).start()
    return job


# ---------------------------------------------------------------- 도구·기본값

@router.get("/tools")
def tool_list(doc_id: str = "", reload: bool = False):
    ext = None
    if doc_id:
        try:
            ext = R.doc_info(doc_id)["ext"]
        except Exception as e:  # noqa: BLE001
            raise _err(e) from e
    defaults = PT.load_defaults()
    out = []
    for t in PT.tools(reload=reload).values():
        info = t.info()
        info["supports_doc"] = (ext in t.formats) if ext else None
        info["default_for"] = sorted(x for x, k in defaults.items() if k == t.key)
        out.append(info)
    order = {k: i for i, k in enumerate(["pymupdf", "pdfplumber", "rapidocr", "docling", "kordoc", "hwpx", "xlsx",
                                         "text", "upstage"])}
    out.sort(key=lambda x: order.get(x["key"], 99))
    return {"tools": out, "notice": NOTICE, "load_errors": PT._load_errors}


@router.get("/defaults")
def get_defaults():
    defaults = PT.load_defaults()
    choices = {ext: [t.key for t in PT.for_ext(ext) if t.kind == "local"] for ext in PT.BUILTIN_DEFAULTS}
    return {"defaults": defaults, "builtin": PT.BUILTIN_DEFAULTS, "choices": choices}


class DefaultsIn(BaseModel):
    defaults: dict[str, str]


@router.post("/defaults")
def set_defaults(body: DefaultsIn):
    try:
        PT.save_defaults(body.defaults)
    except PT.ToolError as e:
        raise _err(e) from e
    return get_defaults()


# ---------------------------------------------------------------- 문서별 실행·결과

@router.get("/docs/{doc_id}")
def doc(doc_id: str):
    try:
        return R.doc_info(doc_id)
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


class RunIn(BaseModel):
    tool: str
    options: dict = Field(default_factory=dict)
    confirm_cloud: bool = False


@router.post("/docs/{doc_id}/run")
def run(doc_id: str, body: RunIn):
    try:
        R.precheck(doc_id, body.tool, body.confirm_cloud)   # 문서·형식·기밀 차단은 바로 답한다
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e
    job = _start("parse", R.parse_with, doc_id, body.tool, body.options, body.confirm_cloud, doc_id=doc_id, tool=body.tool)
    return _public(job)


@router.get("/jobs/{job_id}")
def job(job_id: str):
    """status: running · done · error · interrupted(앱을 다시 켜서 중단됨 — error에 안내 문구)."""
    _ensure_loaded()
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(404, "작업을 찾지 못했습니다(앱을 다시 켰다면 결과 목록을 새로 고치세요).")
    return _public(j)


@router.get("/docs/{doc_id}/jobs")
def doc_jobs(doc_id: str, limit: int = 20):
    """이 문서의 최근 파싱 작업(새것부터). 앱을 다시 켠 뒤에도 '중단됨'·'실패'를 보일 수 있게 파일에서 읽는다."""
    _ensure_loaded()
    with _jobs_lock:
        js = [_public(j) for j in JOBS.values() if j.get("doc_id") == doc_id and j.get("_home") == str(_jobs_file())]
    js.sort(key=lambda j: j.get("started") or 0, reverse=True)
    return {"jobs": js[:max(1, min(limit, 200))]}


@router.get("/docs/{doc_id}/estimate")
def estimate(doc_id: str, tool: str = "upstage", mode: str = "standard"):
    try:
        return R.estimate(doc_id, tool, {"mode": mode})
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.get("/docs/{doc_id}/results")
def results(doc_id: str):
    try:
        R.doc_info(doc_id)
        return {"results": R.list_results(doc_id)}
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


@router.get("/docs/{doc_id}/compare")
def compare(doc_id: str, a: str = "", b: str = "", page: int | None = None, max_blocks: int = 80):
    try:
        return R.compare(doc_id, a or None, b or None, page, max(1, min(max_blocks, 400)))
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e


class ChooseIn(BaseModel):
    result_id: str


@router.post("/docs/{doc_id}/choose")
def choose(doc_id: str, body: ChooseIn):
    try:
        return R.choose(doc_id, body.result_id)
    except Exception as e:  # noqa: BLE001
        raise _err(e) from e
