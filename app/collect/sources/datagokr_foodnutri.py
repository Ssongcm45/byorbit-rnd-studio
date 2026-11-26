"""공공데이터포털 — 식품의약품안전처 식품영양성분DB정보(원재료·가공식품 영양성분, 키 필요).

공식 문서(2026-11-25 확인)
- 서비스: https://www.data.go.kr/data/15127578/openapi.do  (페이지에 붙은 명세(swagger) 기준)
- 요청: GET https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo03/getFoodNtrCpntDbInq03
  매개변수: serviceKey, pageNo, numOfRows, type=json, FOOD_NM_KR(식품명, 부분 일치), FOOD_CAT1_NM, DB_CLASS_NM
  (품목대표/상용제품), MAKER_NM, FOOD_OR_NM, ITEM_REPORT_NO, RESEARCH_YMD, UPDATE_DATE
- 응답(JSON): header.resultCode·resultMsg, body.totalCount·pageNo·numOfRows, body.items(배열 또는 items.item)
  항목: FOOD_CD, FOOD_NM_KR, DB_CLASS_NM, FOOD_OR_NM, FOOD_CAT1_NM…, SERVING_SIZE("100g"), SUB_REF_NAME(출처),
  MAKER_NM, RESEARCH_YMD, UPDATE_DATE, AMT_NUM1…157(영양성분 — 아래 NUTRIENTS에 자주 쓰는 것만 이름을 붙인다)
- 게이트웨이 오류: 미등록 키는 HTTP 403 + OpenAPI_ServiceResponse/cmmMsgHeader(returnReasonCode 30) —
  2026-11-25 키 없이 호출해 확인(02 판도 여전히 응답하지만 03 판을 쓴다).
- 트래픽: 개발계정 하루 10,000건. 이용허락: 공공데이터포털 이용약관(https://www.data.go.kr/ugs/selectPortalPolicyView.do).
- 쓰임: 부산물의 원물(사과·감귤·커피 등) 기준 영양성분 비교 근거. 결과는 dataset 항목으로 수집함에 들어간다.
- 키는 환경 변수 BYORBIT_DATAGOKR_KEY(공공데이터포털 일반 인증키, Decoding 키 권장)로만 받는다.
※ 정상 응답은 명세로 재구성 — 실제 키로 미검증.
"""
from __future__ import annotations

import urllib.parse

from .. import http
from ..base import Item, Source, SourceError
from .kci import mask

API = "https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo03/getFoodNtrCpntDbInq03"
ENV_KEY = "BYORBIT_DATAGOKR_KEY"
http.set_interval("apis.data.go.kr", 1.0)

NUTRIENTS = {  # 명세(swagger)의 AMT_NUM 이름 — 부산물 R&D에서 자주 보는 것
    "AMT_NUM1": "에너지(kcal)", "AMT_NUM2": "수분(g)", "AMT_NUM3": "단백질(g)", "AMT_NUM4": "지방(g)",
    "AMT_NUM5": "회분(g)", "AMT_NUM6": "탄수화물(g)", "AMT_NUM7": "당류(g)", "AMT_NUM8": "식이섬유(g)",
    "AMT_NUM9": "칼슘(mg)", "AMT_NUM10": "철(mg)", "AMT_NUM11": "인(mg)", "AMT_NUM12": "칼륨(mg)",
    "AMT_NUM13": "나트륨(mg)", "AMT_NUM17": "베타카로틴(μg)", "AMT_NUM21": "비타민 C(mg)",
    "AMT_NUM52": "과당(g)", "AMT_NUM58": "자당(g)", "AMT_NUM60": "포도당(g)",
    "AMT_NUM146": "수용성 식이섬유(g)", "AMT_NUM147": "불용성 식이섬유(g)", "AMT_NUM157": "폐기율(%)",
}
SUMMARY_KEYS = ("AMT_NUM1", "AMT_NUM2", "AMT_NUM3", "AMT_NUM4", "AMT_NUM6", "AMT_NUM8", "AMT_NUM146", "AMT_NUM147")


def gateway_error(e: http.HttpError, key: str, service: str) -> SourceError:
    """공공데이터포털 게이트웨이 오류를 할 일이 담긴 한국어로(키는 가린다)."""
    hint = {401: "인증키가 올바르지 않습니다", 403: "등록되지 않은 서비스키이거나 이 서비스의 활용신청이 승인되지 않았습니다",
            429: "호출 한도를 넘었습니다(내일 다시 시도)"}.get(e.status or 0, "호출에 실패했습니다")
    return SourceError(mask(f"{service}: {hint}. 공공데이터포털 마이페이지에서 활용신청 상태와 "
                            f"설정 → API 키 관리의 BYORBIT_DATAGOKR_KEY를 확인하세요. ({e})", key, service_key(key)))


def service_key(raw: str) -> str:
    # 'Encoding' 키(이미 %인코딩)를 넣어도 두 번 인코딩되지 않게 풀어서 쓴다
    return urllib.parse.unquote(raw) if "%" in raw else raw


def _num(v) -> float | None:
    try:
        s = str(v).strip()
        return float(s) if s not in ("", "-", "None") else None
    except (TypeError, ValueError):
        return None


def parse(data) -> tuple[list[Item], int | None]:
    if not isinstance(data, dict):
        raise SourceError("식품영양성분DB 응답 형식이 예상과 다릅니다. 잠시 뒤 다시 시도하세요.")
    if "OpenAPI_ServiceResponse" in data:
        h = (data["OpenAPI_ServiceResponse"] or {}).get("cmmMsgHeader") or {}
        raise SourceError(f"공공데이터포털 오류({h.get('returnReasonCode')} {h.get('returnAuthMsg') or h.get('errMsg')}). "
                          "활용신청 승인과 BYORBIT_DATAGOKR_KEY를 확인하세요.")
    root = data.get("response") or data
    header = root.get("header") or {}
    code = str(header.get("resultCode", "00"))
    if code not in ("00", "0", "INFO-000"):
        raise SourceError(f"식품영양성분DB 오류({code} {header.get('resultMsg', '')}).")
    body = root.get("body") or {}
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    try:
        total = int(body.get("totalCount")) if body.get("totalCount") is not None else None
    except (TypeError, ValueError):
        total = None
    out = []
    for r in items:
        if not isinstance(r, dict):
            continue
        name = r.get("FOOD_NM_KR")
        code_ = r.get("FOOD_CD")
        if not (name or code_):
            continue
        basis = r.get("SERVING_SIZE") or "100g"
        nutr = {label: _num(r.get(k)) for k, label in NUTRIENTS.items() if _num(r.get(k)) is not None}
        summ = ", ".join(f"{NUTRIENTS[k].split('(')[0]} {r.get(k)}{NUTRIENTS[k][NUTRIENTS[k].find('(') + 1:-1]}"
                         for k in SUMMARY_KEYS if _num(r.get(k)) is not None)
        ymd = str(r.get("RESEARCH_YMD") or r.get("UPDATE_DATE") or "")
        out.append(Item(
            source="datagokr_foodnutri", source_id=code_ or name, title=f"[영양성분] {name}",
            year=ymd[:4] if ymd[:4].isdigit() else None,
            venue=r.get("SUB_REF_NAME") or "식품의약품안전처 식품영양성분DB",
            abstract=(f"{basis} 기준 — {summ}. 출처: {r.get('SUB_REF_NAME') or '식약처 식품영양성분DB'}"
                      if summ else None),
            url="https://www.data.go.kr/data/15127578/openapi.do", pdf_url=None, oa=True, language="ko",
            doc_type="dataset", license="공공데이터포털 이용허락(출처 표시)",
            extra={k: v for k, v in {
                "식품코드": code_, "식품명": name, "분류": r.get("FOOD_CAT1_NM"), "DB구분": r.get("DB_CLASS_NM"),
                "원재료": r.get("FOOD_OR_NM"), "제조사": r.get("MAKER_NM"), "기준량": basis,
                "영양성분": nutr or None, "조사일": r.get("RESEARCH_YMD"), "갱신일": r.get("UPDATE_DATE"),
            }.items() if v},
        ).normalized())
    return out, total


class FoodNutri(Source):
    key = "datagokr_foodnutri"
    name = "식약처 식품영양성분DB (공공데이터포털)"
    group = "공공데이터"
    homepage = "https://www.data.go.kr/data/15127578/openapi.do"
    terms_url = "https://www.data.go.kr/ugs/selectPortalPolicyView.do"
    needs_env = (ENV_KEY,)
    key_help = ("공공데이터포털(https://www.data.go.kr) 로그인 → '식품의약품안전처_식품영양성분DB정보'"
                "(https://www.data.go.kr/data/15127578/openapi.do) '활용신청'(개발계정은 대개 자동 승인) → "
                "마이페이지 > 개발계정에서 일반 인증키(Decoding)를 복사해 설정 → API 키 관리의 BYORBIT_DATAGOKR_KEY에 넣으세요(또는 같은 이름의 환경 변수).")
    doc_types = ("dataset",)

    def search(self, query: str, *, limit: int = 25, since_year: int | None = None) -> list[Item]:
        raw = self.env(ENV_KEY)
        key = service_key(raw)
        params = {"serviceKey": key, "pageNo": 1, "numOfRows": max(1, min(int(limit), 100)), "type": "json",
                  "FOOD_NM_KR": query.strip()}
        try:
            data = http.get_json(API, params)
        except http.HttpError as e:
            raise gateway_error(e, raw, "식품영양성분DB") from None
        try:
            items, _ = parse(data)
        except SourceError as e:
            raise SourceError(mask(str(e), raw, key)) from None
        return items[:limit]


SOURCE = FoodNutri()
