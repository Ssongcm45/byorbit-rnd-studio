"""식품안전나라(식약처) — 건강기능식품 기능성 원료 인정현황(I-0040, 키 필요).

공공데이터 개방 서비스이지만 공공데이터포털이 아니라 식품안전나라 Open API로 제공된다(키도 따로 발급).
공식 문서(2026-11-25 확인)
- 서비스: https://www.foodsafetykorea.go.kr/api/openApiInfo.do?menu_grp=MENU_GRP31&menu_no=661&show_cnt=10&start_idx=1&svc_no=I-0040&svc_type_cd=API_TYPE06
- 요청: GET http://openapi.foodsafetykorea.go.kr/api/{인증키}/I-0040/json/{시작}/{끝}/APLC_RAWMTRL_NM={원료명}
  (키가 **주소 경로**에 들어간다 → 오류 메시지의 주소를 반드시 가린다). 추가 조건: PRMS_DT(인정일자),
  HF_FNCLTY_MTRAL_RCOGN_NO(인정번호), CHNG_DT(변경일자)
- 응답(JSON): {"I-0040": {"total_count", "row": [...], "RESULT": {"CODE": "INFO-000", "MSG"}}}
  row: HF_FNCLTY_MTRAL_RCOGN_NO(인정번호), PRMS_DT(인정일자 YYYYMMDD), BSSH_NM(업체), INDUTY_NM(업종), ADDR,
       APLC_RAWMTRL_NM(신청 원료명), FNCLTY_CN(기능성 내용), DAY_INTK_CN(일일 섭취량), IFTKN_ATNT_MATR_CN(섭취 주의)
- 결과 코드: INFO-000 정상, INFO-100 키 오류, INFO-110 이 서비스 미신청, INFO-200 자료 없음, INFO-300 한도 초과,
  INFO-320 증분 조건 없이 시간당 100회 제한. 키 없이 호출한 실제 응답(INFO-100)으로 형식 확인(2026-11-25).
- 쓰임: 부산물 유래 원료(예: 사과 폴리페놀, 감귤 추출물)가 이미 개별인정형 기능성 원료로 인정됐는지 확인.
- 키는 환경 변수 BYORBIT_FOODSAFETY_KEY로만 받는다. 시간당 100회 제한을 고려해 호출 간격을 3초로 둔다.
※ 정상 응답은 공개 sample 키 호출 결과의 필드 이름으로 구성 — 실제 키로 미검증.
"""
from __future__ import annotations

import urllib.parse

from .. import http
from ..base import Item, Source, SourceError
from .kci import mask

BASE = "http://openapi.foodsafetykorea.go.kr/api"
SERVICE = "I-0040"
ENV_KEY = "BYORBIT_FOODSAFETY_KEY"
http.set_interval("openapi.foodsafetykorea.go.kr", 3.0)

CODES = {"INFO-100": "인증키가 유효하지 않습니다", "INFO-110": "이 서비스(I-0040) 이용 신청이 없습니다",
         "INFO-300": "호출 한도를 넘었습니다", "INFO-320": "시간당 호출 한도(100회)를 넘었습니다"}


def _date(s) -> str | None:
    s = "".join(ch for ch in str(s or "") if ch.isdigit())
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) >= 8 else None


def parse(data) -> tuple[list[Item], int | None]:
    block = (data or {}).get(SERVICE) if isinstance(data, dict) else None
    if not isinstance(block, dict):
        raise SourceError("기능성 원료 인정현황 응답 형식이 예상과 다릅니다. 잠시 뒤 다시 시도하세요.")
    res = block.get("RESULT") or {}
    code = res.get("CODE") or "INFO-000"
    if code == "INFO-200":
        return [], 0
    if code != "INFO-000":
        raise SourceError(f"식품안전나라 오류({code}): {CODES.get(code, res.get('MSG') or '')}. "
                          "식품안전나라 인증키(BYORBIT_FOODSAFETY_KEY)와 I-0040 이용 신청을 확인하세요.")
    try:
        total = int(block.get("total_count") or 0)
    except (TypeError, ValueError):
        total = None
    out = []
    for r in block.get("row") or []:
        no = r.get("HF_FNCLTY_MTRAL_RCOGN_NO")
        name = r.get("APLC_RAWMTRL_NM")
        if not (no or name):
            continue
        d = _date(r.get("PRMS_DT"))
        parts = [f"[기능성] {r['FNCLTY_CN']}" if r.get("FNCLTY_CN") else "",
                 f"[일일 섭취량] {r['DAY_INTK_CN']}" if r.get("DAY_INTK_CN") else "",
                 f"[섭취 시 주의] {r['IFTKN_ATNT_MATR_CN']}" if r.get("IFTKN_ATNT_MATR_CN") else ""]
        out.append(Item(
            source="datagokr_hffunc", source_id=no or name, title=f"[기능성 원료 인정] {name}",
            authors=[r["BSSH_NM"]] if r.get("BSSH_NM") else [], year=d[:4] if d else None,
            venue="식품의약품안전처 건강기능식품 기능성 원료 인정현황", abstract="\n".join(p for p in parts if p) or None,
            url="https://www.foodsafetykorea.go.kr/api/openApiInfo.do?menu_grp=MENU_GRP31&menu_no=661&svc_no=I-0040"
                "&svc_type_cd=API_TYPE06",
            pdf_url=None, oa=True, language="ko", doc_type="dataset", license="식품안전나라 공공데이터(출처 표시)",
            extra={k: v for k, v in {"인정번호": no, "인정일자": d, "업체": r.get("BSSH_NM"),
                                     "업종": r.get("INDUTY_NM"), "원료명": name}.items() if v},
        ).normalized())
    return out, total


class HealthFuncMaterial(Source):
    key = "datagokr_hffunc"
    name = "식약처 기능성 원료 인정현황 (식품안전나라 I-0040)"
    group = "공공데이터"
    homepage = "https://www.foodsafetykorea.go.kr/api/main.do"
    terms_url = "https://www.foodsafetykorea.go.kr/api/openApiInfo.do?menu_grp=MENU_GRP31&menu_no=661&svc_no=I-0040&svc_type_cd=API_TYPE06"
    needs_env = (ENV_KEY,)
    key_help = ("식품안전나라(https://www.foodsafetykorea.go.kr) 회원 가입 → '데이터활용서비스' > 'OpenAPI' > '이용신청'에서 "
                "인증키 발급 → I-0040(건강기능식품 기능성 원료인정현황) 이용 신청. 인증키 관리 화면의 키를 "
                "환경 변수 BYORBIT_FOODSAFETY_KEY에 넣고 앱을 다시 켜세요(공공데이터포털 키와 다릅니다).")
    doc_types = ("dataset",)

    def search(self, query: str, *, limit: int = 25, since_year: int | None = None) -> list[Item]:
        key = self.env(ENV_KEY)
        n = max(1, min(int(limit), 100))
        name = urllib.parse.quote(query.strip(), safe="")
        url = f"{BASE}/{urllib.parse.quote(key, safe='')}/{SERVICE}/json/1/{n}/APLC_RAWMTRL_NM={name}"
        try:
            data = http.get_json(url)
        except http.HttpError as e:
            raise SourceError(mask(f"식품안전나라 호출 실패: {e}. 키와 네트워크를 확인하세요.", key)) from None
        try:
            items, _ = parse(data)
        except SourceError as e:
            raise SourceError(mask(str(e), key)) from None
        if since_year:
            items = [i for i in items if not i.year or i.year >= since_year]
        return items[:limit]


SOURCE = HealthFuncMaterial()
