"""API 키 관리 — /api/keys. 메인 앱이 app.include_router(routes_keys.router)로 붙인다.

- 응답에는 키 값이 절대 없다(있는지·어디서 왔는지·끝 4자리 가림·저장 시각만).
- 저장 본문은 직접 읽는다: pydantic 검증 오류(422)는 받은 값을 응답에 되돌려 주므로 쓰지 않는다.
- 이 PC 전용: server.py의 Host/Origin 방어가 그대로 적용된다. 본문을 로그에 쓰는 코드는 없다.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from . import keys

router = APIRouter(prefix="/api/keys", tags=["API 키"])


def _fail(e: Exception) -> HTTPException:
    if isinstance(e, keys.UnknownSlot):
        return HTTPException(404, str(e))
    if isinstance(e, keys.StoreUnavailable):
        return HTTPException(503, str(e) + " " + keys.ENV_HELP)
    return HTTPException(400, str(e))


@router.get("")
def list_keys():
    return keys.listing()


@router.post("/{name}")
async def save_key(name: str, request: Request):
    try:
        keys.slot(name)
    except keys.KeyStoreError as e:
        raise _fail(e) from None
    raw = await request.body()
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(400, '본문은 JSON {"value": "키"} 이어야 합니다.') from None
    if not isinstance(data, dict) or "value" not in data:
        raise HTTPException(400, '본문은 JSON {"value": "키"} 이어야 합니다.')
    try:
        st = keys.save(name, data["value"])
    except keys.KeyStoreError as e:
        raise _fail(e) from None
    finally:
        data = raw = None  # noqa: F841 — 값을 오래 들고 있지 않는다
    msg = "저장했습니다." + (" 다만 같은 이름의 환경 변수가 있어 그 값이 먼저 쓰입니다." if st["env_set"] else
                           " 지금부터 바로 쓰입니다(앱을 다시 켤 필요 없음).")
    return {"ok": True, "message": msg, "slot": st}


@router.delete("/{name}")
def delete_key(name: str):
    try:
        st = keys.delete(name)
    except keys.KeyStoreError as e:
        raise _fail(e) from None
    msg = "보관소에서 지웠습니다." + (" 환경 변수 값은 그대로 쓰입니다(환경 변수는 이 앱이 지우지 않습니다)."
                                 if st["env_set"] else "")
    return {"ok": True, "message": msg, "slot": st}


@router.post("/{name}/test")
def test_key(name: str):
    try:
        keys.slot(name)
    except keys.KeyStoreError as e:
        raise _fail(e) from None
    return keys.test(name)
