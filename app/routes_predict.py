"""건조 결과 예측 API — /api/viz/predict. 메인 앱이 app.include_router(routes_predict.router)로 붙인다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .viz import predict as P

router = APIRouter(prefix="/api/viz/predict", tags=["건조 예측"])


class PredictIn(BaseModel):
    method: str = "열풍건조"
    byproduct: str | None = None
    project: str | None = None
    inputs: dict = {}


class EquipmentIn(BaseModel):
    method: str
    values: dict = {}


@router.get("/models")
def predict_models(method: str = "열풍건조", byproduct: str = "", project: str = ""):
    try:
        return P.models(method, byproduct or None, project or None)
    except P.PredictError as ex:
        raise HTTPException(400, str(ex)) from ex


@router.post("")
def predict_run(body: PredictIn):
    try:
        return P.predict(body.method, body.inputs, body.byproduct, body.project or None)
    except P.PredictError as ex:
        raise HTTPException(400, str(ex)) from ex


@router.get("/equipment")
def equipment_get(method: str = ""):
    try:
        m = P.method_or_error(method) if method else None
    except P.PredictError as ex:
        raise HTTPException(400, str(ex)) from ex
    return P.equipment_view(m)


@router.post("/equipment")
def equipment_post(body: EquipmentIn):
    try:
        return P.save_equipment(body.method, body.values)
    except P.PredictError as ex:
        raise HTTPException(400, str(ex)) from ex
