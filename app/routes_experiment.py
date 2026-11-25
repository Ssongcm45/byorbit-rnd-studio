"""내 실험 API — /api/exp. 메인 앱이 app.include_router(routes_experiment.router)로 붙인다.

공정 흐름(단계 목록·틀·고치기) · 실험 · 런·실측값 · 가져오기(CSV·XLSX)·내보내기 · 모의 · 예측 대 실측 비교 ·
민감도 · 보정(미리보기·적용) · 다음 조건 제안. 모든 계산은 이 컴퓨터 안에서만 한다(밖으로 보내는 길 없음).
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .experiment import calib, importer, plan, sim, steps as S, store

router = APIRouter(prefix="/api/exp", tags=["내 실험"])


def _err(ex: Exception):
    if isinstance(ex, store.NotFound):
        raise HTTPException(404, str(ex)) from ex
    raise HTTPException(400, str(ex)) from ex


ERRS = (store.StoreError, store.NotFound, S.StepError, importer.ImportError_)


class FlowIn(BaseModel):
    name: str = ""
    template_id: str | None = None
    steps: list[dict] | None = None
    byproduct: str | None = None
    description: str | None = None
    force: bool = False


class OpIn(BaseModel):
    op: str
    key: str | None = None
    type: str | None = None
    index: int | None = None
    delta: int | None = None
    enabled: bool | None = None
    params: dict | None = None
    replace: bool = False
    label: str | None = None
    force: bool = False


class ExpIn(BaseModel):
    name: str = ""
    template_id: str | None = None
    flow_id: str | None = None
    byproduct: str | None = None
    confidentiality: str = "내부"
    note: str | None = None


class ExpPatch(BaseModel):
    name: str | None = None
    confidentiality: str | None = None
    note: str | None = None
    byproduct: str | None = None


class RunIn(BaseModel):
    label: str | None = None
    conditions: dict | None = None
    run_date: str | None = None
    note: str | None = None
    values: list[dict] | None = None


class SimIn(BaseModel):
    wf_id: str | None = None
    steps: list[dict] | None = None
    conditions: dict | None = None
    byproduct: str | None = None


class CompareIn(BaseModel):
    calib: dict | None = None
    save_predicted: bool = False


class SensIn(BaseModel):
    step_key: str
    param: str
    target: str = "moisture"
    target_step: str | None = None
    base_run: str | None = None
    n: int = 21
    lo: float | None = None
    hi: float | None = None
    calib: dict | None = None


class CalIn(BaseModel):
    use_ea_fit: bool = False
    include: bool = True


class CommitIn(BaseModel):
    token: str
    columns: list[dict] | None = None


class PlanIn(BaseModel):
    design: dict
    add_runs: bool = False


# ---------------------------------------------------------------- 단계·틀·흐름

@router.get("/steps")
def steps_catalog():
    return S.catalog()


@router.get("/templates")
def templates():
    return {"templates": store.list_templates()}


@router.get("/flows")
def flows(templates: bool = False):
    return {"flows": store.list_flows(include_templates=templates)}


@router.post("/flows")
def flow_create(body: FlowIn):
    try:
        return store.create_flow(body.name, body.template_id, body.steps, body.byproduct, body.description)
    except ERRS as ex:
        _err(ex)


@router.get("/flows/{wf_id}")
def flow_get(wf_id: str):
    try:
        return store.get_flow(wf_id)
    except ERRS as ex:
        _err(ex)


@router.put("/flows/{wf_id}")
def flow_put(wf_id: str, body: FlowIn):
    try:
        return store.update_flow(wf_id, body.name or None, body.steps, body.force, body.byproduct, body.description)
    except ERRS as ex:
        _err(ex)


@router.post("/flows/{wf_id}/ops")
def flow_ops(wf_id: str, body: OpIn):
    try:
        kw = {k: v for k, v in body.model_dump().items() if k != "op" and v is not None}
        return store.flow_op(wf_id, body.op, **kw)
    except ERRS as ex:
        _err(ex)


@router.delete("/flows/{wf_id}")
def flow_delete(wf_id: str):
    try:
        store.delete_flow(wf_id)
        return {"ok": True}
    except ERRS as ex:
        _err(ex)


@router.post("/simulate")
def simulate(body: SimIn):
    try:
        return sim.simulate_flow(body.wf_id, body.steps, body.conditions, body.byproduct)
    except ERRS as ex:
        _err(ex)


# ---------------------------------------------------------------- 실험

@router.get("/experiments")
def experiments():
    return {"experiments": store.list_experiments()}


@router.post("/experiments")
def experiment_create(body: ExpIn):
    try:
        return store.create_experiment(body.name, body.template_id, body.flow_id, body.byproduct, body.confidentiality, body.note)
    except ERRS as ex:
        _err(ex)


@router.get("/experiments/{exp_id}")
def experiment_get(exp_id: str):
    try:
        return store.get_experiment(exp_id)
    except ERRS as ex:
        _err(ex)


@router.put("/experiments/{exp_id}")
def experiment_put(exp_id: str, body: ExpPatch):
    try:
        return store.update_experiment(exp_id, body.name, body.confidentiality, body.note, body.byproduct)
    except ERRS as ex:
        _err(ex)


@router.delete("/experiments/{exp_id}")
def experiment_delete(exp_id: str):
    try:
        store.delete_experiment(exp_id)
        return {"ok": True}
    except ERRS as ex:
        _err(ex)


# ---------------------------------------------------------------- 런·값

@router.post("/experiments/{exp_id}/runs")
def run_add(exp_id: str, body: RunIn):
    try:
        store.get_experiment(exp_id, with_runs=False)
        return store.add_run(exp_id, body.label, body.conditions, body.run_date, body.note, body.values)
    except ERRS as ex:
        _err(ex)


@router.put("/runs/{xrun_id}")
def run_put(xrun_id: str, body: RunIn):
    try:
        return store.update_run(xrun_id, body.label, body.conditions, body.run_date, body.note, body.values)
    except ERRS as ex:
        _err(ex)


@router.put("/runs/{xrun_id}/values")
def run_values(xrun_id: str, body: RunIn):
    try:
        return store.update_run(xrun_id, values=body.values or [])
    except ERRS as ex:
        _err(ex)


@router.delete("/runs/{xrun_id}")
def run_delete(xrun_id: str):
    try:
        store.delete_run(xrun_id)
        return {"ok": True}
    except ERRS as ex:
        _err(ex)


# ---------------------------------------------------------------- 가져오기·내보내기

@router.post("/experiments/{exp_id}/import/preview")
async def import_preview(exp_id: str, file: UploadFile = File(...)):
    try:
        content = await file.read(importer.MAX_BYTES + 1)
        return importer.preview(exp_id, file.filename or "upload.csv", content)
    except ERRS as ex:
        _err(ex)


@router.post("/experiments/{exp_id}/import/commit")
def import_commit(exp_id: str, body: CommitIn):
    try:
        return importer.commit(exp_id, body.token, body.columns)
    except ERRS as ex:
        _err(ex)


@router.get("/experiments/{exp_id}/export.csv")
def export_csv(exp_id: str):
    try:
        exp = store.get_experiment(exp_id, with_runs=False)
        text = importer.export_csv(exp_id)
    except ERRS as ex:
        _err(ex)
    fname = f"실험-{exp['name']}.csv"
    return Response(text.encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=\"experiment.csv\"; filename*=UTF-8''{quote(fname)}"})


# ---------------------------------------------------------------- 비교·민감도·보정·제안

@router.post("/experiments/{exp_id}/compare")
def compare(exp_id: str, body: CompareIn | None = None):
    body = body or CompareIn()
    try:
        r = sim.compare(exp_id, body.calib)
        if body.save_predicted:
            for run in r["runs"]:
                store.save_predicted(run["xrun_id"], [
                    {"step_key": p["step_key"], "target_text": p["label"], "value": p["predicted"], "unit_text": p["unit"],
                     "value_text": None, "basis": None} for p in run["pairs"] if p.get("predicted") is not None])
            r["saved_predicted"] = True
        return r
    except ERRS as ex:
        _err(ex)


@router.get("/experiments/{exp_id}/params")
def numeric_params(exp_id: str):
    try:
        return {"params": sim.numeric_params(exp_id)}
    except ERRS as ex:
        _err(ex)


@router.post("/experiments/{exp_id}/sensitivity")
def sensitivity(exp_id: str, body: SensIn):
    try:
        return sim.sensitivity(exp_id, body.step_key, body.param, body.target, body.target_step, body.base_run, body.n,
                               body.calib, None, body.lo, body.hi)
    except ERRS as ex:
        _err(ex)


@router.post("/experiments/{exp_id}/calibrate/preview")
def calibrate_preview(exp_id: str, body: CalIn | None = None):
    try:
        return calib.preview(exp_id, (body or CalIn()).use_ea_fit)
    except ERRS as ex:
        _err(ex)


@router.post("/experiments/{exp_id}/calibrate/apply")
def calibrate_apply(exp_id: str, body: CalIn):
    try:
        return calib.apply(exp_id, body.include, body.use_ea_fit)
    except ERRS as ex:
        _err(ex)


@router.get("/experiments/{exp_id}/suggest")
def suggest(exp_id: str):
    try:
        return plan.suggest(exp_id)
    except ERRS as ex:
        _err(ex)


@router.post("/experiments/{exp_id}/plan")
def save_plan(exp_id: str, body: PlanIn):
    try:
        r = plan.save_plan(exp_id, body.design)
        if body.add_runs:
            r["runs"] = [x["xrun_id"] for x in plan.add_planned_runs(exp_id, body.design)]
        return r
    except ERRS as ex:
        _err(ex)
