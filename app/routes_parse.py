"""파서 선택 API — /api/parse. 메인 앱이 app.include_router(routes_parse.router)로 붙인다.

문서마다 파서 도구를 골라 다시 파싱하고, 결과를 나란히 비교하고, 고른 결과로 다시 청킹한다.
클라우드 도구(Upstage)만 문서 파일을 밖으로 보낸다: '기밀' → 403, '내부'는 confirm_cloud=true가 있어야 한다(409).
"""
from __future__ import annotations

import threading
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .ingest import parser_tools as PT
from .ingest.parser_tools import results as R

router = APIRouter(prefix="/api/parse", tags=["파서 선택"])

NOTICE = ("로컬 도구는 문서를 이 PC 안에서만 읽습니다. 클라우드 도구(Upstage)는 문서 파일을 Upstage 서버로 보내며, "
          "'기밀' 문서는 보낼 수 없습니다.")

JOBS: dict[str, dict] = {}
JOB_TTL_SEC = 3600
_jobs_lock = threading.Lock()


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
    now = time.time()
    with _jobs_lock:
        for jid in [j for j, v in JOBS.items() if v["status"] != "running" and now - v.get("finished", now) > JOB_TTL_SEC]:
            JOBS.pop(jid, None)


def _start(kind: str, fn, *args, **kw) -> dict:
    _prune()
    jid = uuid.uuid4().hex[:12]
    job = {"job_id": jid, "kind": kind, "status": "running", "started": time.time()}
    JOBS[jid] = job

    def go():
        try:
            job["result"] = fn(*args, **kw)
            job["status"] = "done" if job["result"].get("status") != "error" else "error"
            if job["status"] == "error":
                job["error"] = job["result"].get("error")
        except Exception as e:  # noqa: BLE001
            job["status"], job["error"] = "error", str(e)
        job["finished"] = time.time()

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
    job = _start("parse", R.parse_with, doc_id, body.tool, body.options, body.confirm_cloud)
    return dict(job)


@router.get("/jobs/{job_id}")
def job(job_id: str):
    j = JOBS.get(job_id)
    if not j:
        raise HTTPException(404, "작업을 찾지 못했습니다(앱을 다시 켰다면 결과 목록을 새로 고치세요).")
    return j


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
