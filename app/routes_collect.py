"""자료 수집 API — /api/collect. 메인 앱이 app.include_router(routes_collect.router)로 붙인다.

밖으로 나가는 것은 검색어(와 출처가 요구하는 API 키)뿐이다. 크롤러 사이트 관리는 app.collect.crawler
(묶음 B)에 맡긴다 — 모듈이 아직 없으면 503과 함께 '크롤러 준비 중'을 돌려준다.
"""
from __future__ import annotations

import importlib
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .collect import registry, scheduler, store

router = APIRouter(prefix="/api/collect", tags=["자료 수집"])

GROUP_ORDER = ["해외 학술", "국내 학술", "국가 R&D·특허", "공공데이터", "크롤러"]
NOTICE = ("외부로 나가는 것: 검색어(와 그 출처가 요구하는 API 키)만. 자료함·CoA·시료·실험 데이터는 보내지 않습니다. "
          "원문 PDF는 오픈 액세스일 때만 받습니다.")


def _bg(fn, *args, **kw) -> None:
    def go():
        try:
            fn(*args, **kw)
        except Exception:  # noqa: BLE001 — 오류는 collect_job에 남는다
            pass
    threading.Thread(target=go, daemon=True).start()


def _bad(e: Exception) -> HTTPException:
    return HTTPException(400, str(e))


# ---------------------------------------------------------------- 출처

@router.get("/sources")
def sources(reload: bool = False):
    out = []
    for s in registry.sources(reload=reload).values():
        try:
            info = s.info()
        except Exception as e:  # noqa: BLE001
            info = {"key": s.key, "name": s.name, "group": s.group, "ready": False, "missing_env": [],
                    "message": f"상태를 확인하지 못했습니다: {e}"}
        info.setdefault("description", getattr(s, "description", ""))
        out.append(info)
    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    out.sort(key=lambda x: (order.get(x.get("group"), 99), x.get("name") or ""))
    groups = GROUP_ORDER + sorted({x.get("group") or "기타" for x in out} - set(GROUP_ORDER))
    return {"sources": out, "groups": groups, "notice": NOTICE}


# ---------------------------------------------------------------- 검색·작업

class SearchIn(BaseModel):
    query: str
    sources: list[str]
    limit_per_source: int = Field(20, ge=1, le=100)
    since_year: int | None = Field(None, ge=1900, le=2100)
    project: str | None = None


@router.post("/search")
def search(body: SearchIn):
    q = body.query.strip()
    if not q:
        raise HTTPException(400, "검색어를 입력하세요.")
    try:
        srcs = store.validate_sources(body.sources)
    except store.CollectError as e:
        raise _bad(e) from e
    jid = store.create_job("search", q, srcs)
    _bg(store.run_search, q, srcs, body.limit_per_source, body.since_year, body.project or None, None, jid)
    return store.get_job(jid)


@router.get("/jobs")
def jobs(limit: int = 20, query_id: str = ""):
    return {"jobs": store.list_jobs(max(1, min(limit, 100)), query_id or None)}


@router.get("/jobs/{job_id}")
def job(job_id: str):
    j = store.get_job(job_id)
    if not j:
        raise HTTPException(404, "작업을 찾지 못했습니다. 목록을 새로 고친 뒤 다시 여세요.")
    return j


# ---------------------------------------------------------------- 수집함

@router.get("/items")
def items(status: str = "new", q: str = "", source: str = "", doc_type: str = "", oa: bool = False,
          page: int = 1, page_size: int = 30, query_id: str = ""):
    try:
        return store.list_items(status or None, q or None, source or None, doc_type or None, oa or None,
                                page, page_size, query_id or None)
    except store.CollectError as e:
        raise _bad(e) from e


@router.get("/items/{item_id}")
def item(item_id: str):
    it = store.get_item(item_id)
    if not it:
        raise HTTPException(404, "수집함 항목을 찾지 못했습니다. 목록을 새로 고치세요.")
    return it


class StatusIn(BaseModel):
    status: str


@router.post("/items/{item_id}/status")
def item_status(item_id: str, body: StatusIn):
    try:
        return store.set_status(item_id, body.status)
    except KeyError as e:
        raise HTTPException(404, "수집함 항목을 찾지 못했습니다. 목록을 새로 고치세요.") from e
    except store.CollectError as e:
        raise _bad(e) from e


class IngestIn(BaseModel):
    project: str | None = None
    confidentiality: str = "일반"


@router.post("/items/{item_id}/ingest")
def item_ingest(item_id: str, body: IngestIn | None = None):
    body = body or IngestIn()
    try:
        return store.ingest(item_id, body.project or None, body.confidentiality)
    except KeyError as e:
        raise HTTPException(404, "수집함 항목을 찾지 못했습니다. 목록을 새로 고치세요.") from e
    except store.CollectError as e:
        raise _bad(e) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"자료함에 넣지 못했습니다: {e}. 원문 링크를 열어 직접 받은 뒤 자료함에 끌어다 놓으세요.") from e


class BulkIn(BaseModel):
    ids: list[str]
    action: str
    project: str | None = None
    confidentiality: str = "일반"


@router.post("/items/bulk")
def items_bulk(body: BulkIn):
    if not body.ids:
        raise HTTPException(400, "항목을 하나 이상 고르세요.")
    if len(body.ids) > 500:
        raise HTTPException(400, "한 번에 500건까지 처리합니다. 나눠서 실행하세요.")
    try:
        if body.action == "ingest":   # PDF 받기가 오래 걸릴 수 있어 백그라운드 작업으로
            jid = store.create_job("ingest", None, [], None, {"action": "ingest", "total": len(body.ids),
                                                              "done": 0, "failed": 0, "errors": []})
            _bg(store.bulk, body.ids, "ingest", body.project or None, body.confidentiality, jid)
            return {"job_id": jid, "background": True, **store.get_job(jid)}
        return store.bulk(body.ids, body.action)
    except store.CollectError as e:
        raise _bad(e) from e


# ---------------------------------------------------------------- 저장 검색

class QueryIn(BaseModel):
    query_id: str | None = None
    name: str | None = None
    query: str | None = None
    sources: list[str] | None = None
    project: str | None = None
    auto: bool | None = None
    interval_h: int | None = Field(None, ge=1, le=2160)
    limit_per_source: int | None = Field(None, ge=1, le=100)
    since_year: int | None = Field(None, ge=1900, le=2100)


@router.get("/queries")
def queries():
    return {"queries": store.list_queries(), "scheduler": scheduler.status()}


@router.post("/queries")
def query_save(body: QueryIn):
    try:
        return store.save_query(body.model_dump(exclude_unset=True))
    except KeyError as e:
        raise HTTPException(404, "저장 검색을 찾지 못했습니다. 목록을 새로 고치세요.") from e
    except store.CollectError as e:
        raise _bad(e) from e


@router.delete("/queries/{query_id}")
def query_delete(query_id: str):
    try:
        store.delete_query(query_id)
    except KeyError as e:
        raise HTTPException(404, "저장 검색을 찾지 못했습니다. 목록을 새로 고치세요.") from e
    return {"ok": True}


@router.post("/queries/{query_id}/run")
def query_run(query_id: str):
    try:
        begun = store.begin_query(query_id)
    except KeyError as e:
        raise HTTPException(404, "저장 검색을 찾지 못했습니다. 목록을 새로 고치세요.") from e
    except store.Busy as e:
        raise HTTPException(409, str(e)) from e
    _bg(store.run_query, query_id, None, begun)
    return store.get_job(begun["job_id"])


class PauseIn(BaseModel):
    paused: bool


@router.get("/scheduler")
def scheduler_get():
    return scheduler.status()


@router.post("/scheduler")
def scheduler_set(body: PauseIn):
    return scheduler.set_paused(body.paused)


# ---------------------------------------------------------------- 크롤러 사이트 (묶음 B의 app.collect.crawler에 위임)

CRAWLER_NOT_READY = ("크롤러 준비 중입니다. 크롤러 모듈(app/collect/crawler.py)이 아직 설치되지 않았습니다. "
                     "공식 API 출처로 먼저 검색하세요.")


def _crawler():
    try:
        mod = importlib.import_module("app.collect.crawler")
    except ImportError as e:
        raise HTTPException(503, CRAWLER_NOT_READY) from e
    for fn in ("list_sites", "save_site", "delete_site", "check_site"):
        if not callable(getattr(mod, fn, None)):
            raise HTTPException(503, CRAWLER_NOT_READY)
    return mod


def _crawler_call(fn, *args):
    try:
        return fn(*args)
    except HTTPException:
        raise
    except KeyError as e:
        raise HTTPException(404, "사이트를 찾지 못했습니다. 목록을 새로 고치세요.") from e
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"사이트 설정을 확인하세요: {e}") from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"크롤러 처리 실패: {e}. 잠시 뒤 다시 시도하세요.") from e


@router.get("/sites")
def sites():
    return {"sites": _crawler_call(_crawler().list_sites)}


@router.post("/sites")
def site_save(site: dict):
    return _crawler_call(_crawler().save_site, site)


@router.delete("/sites/{site_id}")
def site_delete(site_id: str):
    _crawler_call(_crawler().delete_site, site_id)
    return {"ok": True}


@router.post("/sites/{site_id}/check")
def site_check(site_id: str):
    return _crawler_call(_crawler().check_site, site_id)
