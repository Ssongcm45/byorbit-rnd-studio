"""시각화 API — /api/viz. 메인 앱이 app.include_router(routes_viz.router)로 붙인다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from .viz import drying, structures as st, system

router = APIRouter(prefix="/api/viz", tags=["시각화"])


def _entry_or_404(key: str) -> dict:
    e = st.entry(key)
    if not e:
        raise HTTPException(404, f"'{key}' 구조가 없습니다. 분자 구조 화면에서 성분명으로 검색하거나 "
                                 "PubChem에서 가져오기를 누르세요.")
    return e


def _need_rdkit() -> None:
    if not st.rdkit_available():
        raise HTTPException(503, st.RDKIT_MISSING_MSG)


# ---------------------------------------------------------------- 분자 구조

@router.get("/structures")
def structures_list():
    return st.listing()


@router.get("/structures/resolve")
def structures_resolve(term: str = Query("", description="성분명·동의어(한글/영문)")):
    term = term.strip()
    if not term:
        raise HTTPException(400, "찾을 성분명을 넣으세요. 예: 클로로겐산, chlorogenic acid, 총폴리페놀")
    e = st.resolve(term)
    if not e:
        en = st.english_name(term)
        return {"found": False, "term": term, "suggestions": st.suggestions(term), "name_en": en,
                "message": (f"'{term}'의 구조가 로컬에 없습니다. "
                            + (f"'PubChem에서 가져오기'를 누르면 영문명 '{en}'만 보내 구조를 받아옵니다."
                               if en else "영문 성분명을 알면 그 이름으로 PubChem에서 가져올 수 있습니다."))}
    return {"found": True, **e}


@router.get("/structures/{key}.svg")
def structures_svg(key: str):
    e = _entry_or_404(key)
    _need_rdkit()
    try:
        return Response(st.svg(e), media_type="image/svg+xml")
    except ValueError as ex:
        raise HTTPException(422, f"{ex} 구조 자료를 확인하세요.") from ex


@router.get("/structures/{key}.sdf")
def structures_sdf(key: str):
    e = _entry_or_404(key)
    _need_rdkit()
    r = st.sdf(e)
    if not r["ok"]:
        raise HTTPException(422, r["message"])
    return Response(r["sdf"], media_type="chemical/x-mdl-sdfile")


@router.get("/structures/{key}")
def structures_detail(key: str):
    _entry_or_404(key)
    return st.detail(key)


class FetchIn(BaseModel):
    name_en: str | None = None
    term: str | None = None


@router.post("/structures/fetch")
def structures_fetch(body: FetchIn):
    if not (body.name_en or body.term):
        raise HTTPException(400, "가져올 성분의 영문명(name_en)이나 검색어(term)를 넣으세요.")
    try:
        return st.fetch_pubchem(name_en=body.name_en, term=body.term)
    except st.FetchError as ex:
        raise HTTPException(400, str(ex)) from ex


# ---------------------------------------------------------------- 건조 방식

@router.get("/drying/methods")
def drying_methods():
    return drying.methods()


@router.get("/drying/phase")
def drying_phase():
    return drying.phase_diagram()


@router.get("/drying/compare")
def drying_compare(byproduct: str = "", target: list[str] = Query(default=[]), project: str = ""):
    targets = [t for x in target for t in x.split(",") if t.strip()] or None
    return drying.compare(byproduct or None, targets, project or None)


@router.get("/drying/equipment/{method}")
def drying_equipment(method: str, variant: str = ""):
    e = drying.equipment(method, variant or None)
    if not e:
        raise HTTPException(404, f"'{method}' 설비 모델이 없습니다. 동결건조·열풍건조·진공건조·분무건조·자연건조 중에서 고르세요.")
    return e


@router.get("/drying/parse")
def drying_parse(text: str = "", concept: str = ""):
    return drying.parse_pretreatment(text, concept or None)


# ---------------------------------------------------------------- 구성도·파이프라인

@router.get("/system")
def system_map():
    return system.system_map()


@router.get("/pipeline")
def pipeline(project: str = ""):
    r = system.pipeline(project or None)
    if r.get("error"):
        raise HTTPException(404, r["error"])
    return r
