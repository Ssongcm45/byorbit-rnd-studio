"""문서 작업대 API — /api/wb. 메인 앱이 app.include_router(routes_workbench.router)로 붙인다.

청크: 목록·검사 / 고치기·나누기·합치기·종류·섹션·제목 올리기·잡음 줄·청크 지우기 / 되돌리기·기록
규칙: 제안(고친 것에서) / 수락(범위 선택) / 목록·만들기·고치기·끄기·지우기 / 미리보기 / 적용
라벨: 청크 라벨 / 선택 제안 / 사람 라벨 만들기·고치기·지우기 / 승인·거절 / 개념 찾기·새 개념
배운 것: 동의어·부정 사례·라벨 사례·규칙 목록과 끄기 / AI에 보낼 사례 미리보기
자동: 사전 라벨 다시 / AI 라벨(labeling.start 위임) / 진행
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import chunk_edit as E, chunk_rules as R, db, engines, labeling as L, tools

router = APIRouter(prefix="/api/wb", tags=["문서 작업대"])


def _err(ex: Exception):
    if isinstance(ex, (E.NotFound,)):
        raise HTTPException(404, str(ex)) from ex
    if isinstance(ex, KeyError):
        raise HTTPException(404, "대상을 찾지 못했습니다. 작업대를 새로고침하세요.") from ex
    raise HTTPException(400, str(ex)) from ex


ERRS = (E.WbError, L.LabelError, KeyError)


def _doc(doc_id: str) -> dict:
    d = db.one("SELECT d.doc_id, d.file_name, d.parse_status, d.note, s.title, s.source_type, s.confidentiality "
               "FROM document d JOIN source s ON s.source_id=d.source_id WHERE d.doc_id=?", (doc_id,))
    if not d:
        raise HTTPException(404, "자료를 찾지 못했습니다. 자료함을 새로고침하세요.")
    return d


# ---------------------------------------------------------------- 자료·청크

@router.get("/meta")
def meta():
    return {"label_types": sorted(tools.LABEL_TYPES), "rule_kinds": R.KINDS, "scopes": list(R.SCOPES),
            "schemes": [r["name"] for r in db.rows("SELECT name FROM concept_scheme ORDER BY name")],
            "min_len": E.MIN_LEN, "max_len": E.MAX_LEN, "coa_rule": tools._rule()}


@router.get("/docs/{doc_id}")
def doc(doc_id: str):
    d = _doc(doc_id)
    d["sections"] = db.rows("SELECT section_id, heading, ord, page_from, page_to, "
                            "(SELECT COUNT(*) FROM chunk c WHERE c.section_id=s.section_id) AS chunks "
                            "FROM doc_section s WHERE doc_id=? ORDER BY ord", (doc_id,))
    d["scopes"] = R.scope_options(doc_id)
    d["history"] = E.ops(doc_id, limit=20)
    return d


@router.get("/docs/{doc_id}/chunks")
def chunks(doc_id: str):
    _doc(doc_id)
    return E.inspect(doc_id)


@router.get("/chunks/{chunk_id}")
def chunk(chunk_id: str):
    c = db.one("SELECT c.chunk_id, c.doc_id, c.ord, c.page, c.chunk_type, c.section_id, c.text, s.heading "
               "FROM chunk c LEFT JOIN doc_section s ON s.section_id=c.section_id WHERE c.chunk_id=?", (chunk_id,))
    if not c:
        raise HTTPException(404, "청크를 찾지 못했습니다. 다른 곳에서 바뀌었을 수 있으니 새로고침하세요.")
    c["annotations"] = db.rows(
        "SELECT a.ann_id, a.span_start, a.span_end, a.surface_text, a.label_type, a.concept_id, k.pref_label_ko AS concept, "
        "a.normalized_value, a.confidence, a.method, a.status, a.engine, "
        "(SELECT meas_id FROM measurement m WHERE m.ann_id=a.ann_id LIMIT 1) AS meas_id "
        "FROM annotation a LEFT JOIN concept k ON k.concept_id=a.concept_id WHERE a.chunk_id=? "
        "ORDER BY a.span_start IS NULL DESC, a.span_start", (chunk_id,))
    c["neighbors"] = {
        "prev": (db.one("SELECT chunk_id FROM chunk WHERE doc_id=? AND ord<? ORDER BY ord DESC LIMIT 1",
                        (c["doc_id"], c["ord"])) or {}).get("chunk_id"),
        "next": (db.one("SELECT chunk_id FROM chunk WHERE doc_id=? AND ord>? ORDER BY ord LIMIT 1",
                        (c["doc_id"], c["ord"])) or {}).get("chunk_id")}
    return c


class TextIn(BaseModel):
    text: str


class PosIn(BaseModel):
    pos: int


class DirIn(BaseModel):
    direction: str = "next"


class TypeIn(BaseModel):
    chunk_type: str


class SectionIn(BaseModel):
    section_id: str | None = None
    heading: str | None = None


class LineIn(BaseModel):
    line: str


class DropIn(BaseModel):
    force: bool = False


def _op(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except ERRS as ex:
        _err(ex)


@router.post("/chunks/{chunk_id}/edit")
def edit(chunk_id: str, b: TextIn):
    return _op(E.edit_text, chunk_id, b.text)


@router.post("/chunks/{chunk_id}/split")
def split(chunk_id: str, b: PosIn):
    return _op(E.split_chunk, chunk_id, b.pos)


@router.post("/chunks/{chunk_id}/merge")
def merge(chunk_id: str, b: DirIn):
    return _op(E.merge_chunk, chunk_id, b.direction)


@router.post("/chunks/{chunk_id}/type")
def set_type(chunk_id: str, b: TypeIn):
    return _op(E.set_chunk_type, chunk_id, b.chunk_type)


@router.post("/chunks/{chunk_id}/section")
def set_section(chunk_id: str, b: SectionIn):
    return _op(E.set_chunk_section, chunk_id, b.section_id, b.heading)


@router.post("/chunks/{chunk_id}/heading")
def heading(chunk_id: str, b: LineIn):
    return _op(E.promote_line, chunk_id, b.line)


@router.post("/chunks/{chunk_id}/drop-line")
def drop_line(chunk_id: str, b: LineIn):
    return _op(E.drop_line, chunk_id, b.line)


@router.post("/chunks/{chunk_id}/drop")
def drop(chunk_id: str, b: DropIn):
    return _op(E.drop_chunk, chunk_id, b.force)


@router.post("/docs/{doc_id}/undo")
def undo(doc_id: str):
    _doc(doc_id)
    return _op(E.undo, doc_id)


@router.get("/docs/{doc_id}/history")
def history(doc_id: str, limit: int = 50):
    _doc(doc_id)
    return E.ops(doc_id, limit=min(limit, 500), include_undone=True)


# ---------------------------------------------------------------- 규칙

class RuleIn(BaseModel):
    kind: str
    pattern: str | None = None
    params: dict = {}
    scope: dict | None = None
    note: str | None = None
    enabled: bool = True


class AcceptIn(BaseModel):
    proposal: dict
    scope: dict
    note: str | None = None


class RulePatch(BaseModel):
    pattern: str | None = None
    params: dict | None = None
    scope: dict | None = None
    enabled: bool | None = None
    note: str | None = None


class ApplyIn(BaseModel):
    rule_ids: list[str] | None = None


class PreviewIn(BaseModel):
    rule_ids: list[str] | None = None
    rules: list[dict] | None = None


@router.get("/docs/{doc_id}/rules/proposals")
def proposals(doc_id: str):
    _doc(doc_id)
    return {"proposals": _op(R.propose, doc_id), "scopes": R.scope_options(doc_id)}


@router.post("/rules/accept")
def accept(b: AcceptIn):
    return _op(R.accept, b.proposal, b.scope, b.note)


@router.get("/rules")
def rules(doc_id: str | None = None):
    return _op(R.list_rules, doc_id or None)


@router.post("/rules")
def create_rule(b: RuleIn):
    return _op(R.create_rule, b.kind, b.pattern, b.params, b.scope, "manual", b.note, b.enabled)


@router.patch("/rules/{rule_id}")
def patch_rule(rule_id: str, b: RulePatch):
    return _op(R.update_rule, rule_id, **b.model_dump(exclude_unset=True))


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str):
    return _op(R.delete_rule, rule_id)


@router.post("/docs/{doc_id}/rules/preview")
def preview(doc_id: str, b: PreviewIn):
    _doc(doc_id)
    return _op(R.preview, doc_id, b.rule_ids, b.rules)


@router.post("/docs/{doc_id}/rules/apply")
def apply(doc_id: str, b: ApplyIn):
    _doc(doc_id)
    return _op(R.apply, doc_id, b.rule_ids)


# ---------------------------------------------------------------- 라벨

class LabelIn(BaseModel):
    chunk_id: str
    label_type: str
    start: int | None = None
    end: int | None = None
    surface: str | None = None
    occurrence: int = 0
    concept_id: str | None = None
    value: str | float | None = None
    unit: str | None = None
    target: str | None = None
    basis: str | None = None


class LabelPatch(BaseModel):
    label_type: str | None = None
    concept_id: str | None = None
    clear_concept: bool = False
    value: str | float | None = None
    unit: str | None = None
    target: str | None = None
    basis: str | None = None
    start: int | None = None
    end: int | None = None


class ReviewIn(BaseModel):
    status: str
    learn: bool = True


class ConceptIn(BaseModel):
    label: str
    scheme: str
    alt_labels: list[str] = []


class SynIn(BaseModel):
    concept_id: str
    surface: str
    ann_id: str | None = None


class NegIn(BaseModel):
    ann_id: str | None = None
    chunk_id: str | None = None
    surface: str | None = None
    concept_id: str | None = None
    scope: str = "context"


@router.get("/suggest")
def suggest(chunk_id: str, start: int, end: int):
    return _op(L.suggest, chunk_id, start, end)


@router.get("/concepts")
def concepts(q: str):
    return tools.lookup_concept(q)


@router.post("/concepts")
def new_concept(b: ConceptIn):
    return _op(L.add_concept, b.label, b.scheme, b.alt_labels)


@router.post("/labels")
def create_label(b: LabelIn):
    v = None if b.value in (None, "") else str(b.value)
    return _op(L.create_manual, b.chunk_id, b.label_type, b.start, b.end, b.surface, b.occurrence, b.concept_id,
               v, b.unit, b.target, b.basis)


@router.patch("/labels/{ann_id}")
def patch_label(ann_id: str, b: LabelPatch):
    d = b.model_dump(exclude_unset=True)
    if d.get("value") is not None:
        d["value"] = str(d["value"])
    return _op(L.update_label, ann_id, **d)


@router.delete("/labels/{ann_id}")
def delete_label(ann_id: str, learn_negative: bool = False):
    return _op(L.delete_label, ann_id, learn_negative)


@router.post("/labels/{ann_id}/review")
def review(ann_id: str, b: ReviewIn):
    return _op(L.review_annotation, ann_id, b.status, b.learn)


@router.post("/learn/synonym")
def learn_synonym(b: SynIn):
    return _op(L.learn_synonym, b.concept_id, b.surface, b.ann_id)


@router.post("/learn/negative")
def learn_negative(b: NegIn):
    return {"ex_id": _op(L.learn_negative, ann_id=b.ann_id, chunk_id=b.chunk_id, surface=b.surface,
                         concept_id=b.concept_id, scope=b.scope)}


# ---------------------------------------------------------------- 배운 것

class EnabledIn(BaseModel):
    enabled: bool | None = None
    scope: str | None = None


@router.get("/learned")
def learned():
    return L.learned()


@router.patch("/examples/{ex_id}")
def patch_example(ex_id: str, b: EnabledIn):
    out = {"ok": True}
    if b.scope:
        out = _op(L.set_negative_scope, ex_id, b.scope)
    if b.enabled is not None:
        out = _op(L.set_example, ex_id, b.enabled)
    return out


@router.delete("/examples/{ex_id}")
def delete_example(ex_id: str):
    return _op(L.delete_example, ex_id)


@router.delete("/synonyms/{label_id}")
def delete_synonym(label_id: str):
    return _op(L.remove_synonym, label_id)


@router.get("/docs/{doc_id}/examples-preview")
def examples_preview(doc_id: str, chunk_ids: str = ""):
    """AI 라벨을 돌리면 프롬프트에 붙을 사례를 그대로 보여 준다(무엇이 밖으로 가는지 확인용)."""
    _doc(doc_id)
    ids = [x for x in chunk_ids.split(",") if x] or [r["chunk_id"] for r in db.rows(
        "SELECT chunk_id FROM chunk WHERE doc_id=? ORDER BY ord LIMIT 5", (doc_id,))]
    eng = engines.get()
    name = L._engine_name(eng)
    r = L.examples_for(ids, name)
    return {"engine": name, "rule": r.get("rule"), "excluded_confidential": r.get("excluded_confidential", 0),
            "examples": r["examples"], "section": L.examples_section(ids, name)}


# ---------------------------------------------------------------- 자동 라벨

class AutoIn(BaseModel):
    chunk_ids: list[str] | None = None
    force: bool = False
    batch_size: int = L.DEFAULT_BATCH


@router.post("/docs/{doc_id}/dict-label")
def dict_label(doc_id: str, b: AutoIn):
    _doc(doc_id)
    return _op(L.dict_relabel, doc_id, b.chunk_ids)


@router.post("/docs/{doc_id}/ai-label")
def ai_label(doc_id: str, b: AutoIn):
    _doc(doc_id)
    try:
        return {"run_id": L.start(doc_id, None, b.batch_size, b.force, chunk_ids=b.chunk_ids)}
    except L.LabelError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/docs/{doc_id}/ai-runs")
def ai_runs(doc_id: str, limit: int = 5):
    return L.list_runs(doc_id, limit=min(limit, 50))


@router.get("/ai-runs/{run_id}")
def ai_run(run_id: str):
    try:
        return L.status(run_id)
    except KeyError:
        raise HTTPException(404, "라벨 실행 기록이 없습니다. 'AI 라벨'을 다시 누르세요.")
