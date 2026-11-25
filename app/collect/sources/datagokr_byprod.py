"""농사로(농촌진흥청) — 농식품부산물 영양정보(foodbyprdNtrinfo, 키 필요).

농사로 Open API 136종 가운데 부산물 R&D에 바로 쓰이는 서비스(사료용 농식품 부산물의 성분·이용 수준).
공식 문서(2026-11-25 확인)
- 서비스 목록: https://www.nongsaro.go.kr/portal/ps/psn/psnj/openApiLst.ps?menuId=PS65428
- 신청 안내: https://www.nongsaro.go.kr/portal/ps/psz/psza/contentMain.ps?menuId=PS00191
- 매뉴얼(HWP): https://www.nongsaro.go.kr/portal/apiManual/foodbyprdNtrinfo.zip
- 요청: http://api.nongsaro.go.kr/service/foodbyprdNtrinfo/{오퍼레이션}?apiKey=…
  foodbyprdNtrinfoLst: sText(제목 검색), sLvstckSeCode(가축 구분), pageNo, numOfRows
     → cntntsNo, cntntsSj(제목), lvstckSeNm, chartrCn(특성), useLevelAtpnCn(이용 수준·주의), imgUrl
  foodbyprdNtrinfoDtl: cntntsNo → mitrValue(수분), takprotValue(조단백), cuftValue(조지방),
     usefulRdshNtrgwaterValue(가용무질소물), crfbValue(조섬유), inqiremntValue(조회분), ctarValue(칼슘), pValue(인),
     tdngValue(TDN), deValue(DE)
- 결과 코드: 00 정상, 11 키 없음·미등록, 12 정지, 13 서비스·오퍼레이션 오류, 15 등록 도메인 불일치, 91 시스템 오류.
  키 없이 호출한 실제 응답(resultCode 11)으로 오류 형식 확인(2026-11-25). 정상 응답 틀(response/header +
  body/items/item)은 매뉴얼에 없어 공공 API 관례로 재구성 — 실제 키로 미검증.
- 주의: 농사로 키는 신청 때 적은 서비스 도메인에 묶인다(매뉴얼은 브라우저 AJAX 호출만 설명). 서버(이 앱)에서
  부르는 방식은 문서에 없으므로, 오류 15가 나면 신청 도메인을 http://localhost 등으로 다시 신청해야 할 수 있다.
- 상세(성분값)는 앞쪽 5건만 추가로 부른다(호출 수 절약). 호출 간격 1초.
- 키는 환경 변수 BYORBIT_NONGSARO_KEY로만 받는다.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from .. import http
from ..base import Item, Source, SourceError
from .kci import _find, _findall, _t, mask

BASE = "http://api.nongsaro.go.kr/service/foodbyprdNtrinfo"
ENV_KEY = "BYORBIT_NONGSARO_KEY"
DETAIL_MAX = 5
http.set_interval("api.nongsaro.go.kr", 1.0)

CODES = {"11": "인증키가 없거나 등록되지 않았습니다", "12": "인증키 사용이 정지되었습니다",
         "13": "서비스·오퍼레이션 이름이 올바르지 않습니다", "15": "신청할 때 등록한 도메인과 호출 위치가 다릅니다",
         "91": "농사로 시스템 오류입니다(잠시 뒤 다시 시도)"}
COMPONENTS = {"mitrValue": "수분(%)", "takprotValue": "조단백질(%)", "cuftValue": "조지방(%)",
              "usefulRdshNtrgwaterValue": "가용무질소물(%)", "crfbValue": "조섬유(%)", "inqiremntValue": "조회분(%)",
              "ctarValue": "칼슘(%)", "pValue": "인(%)", "tdngValue": "TDN(%)", "deValue": "DE(kcal/kg)"}


def _root(xml_text: str) -> ET.Element:
    try:
        root = ET.fromstring(xml_text.strip().encode("utf-8"))
    except ET.ParseError as e:
        raise SourceError(f"농사로 응답을 읽지 못했습니다(XML 오류: {e}). 잠시 뒤 다시 시도하세요.") from None
    code = (_t(_find(root, "resultCode")) or "00").strip()
    if code not in ("00", "0"):
        raise SourceError(f"농사로 오류({code}): {CODES.get(code, _t(_find(root, 'resultMsg')) or '')}. "
                          "농사로 Open API 키(BYORBIT_NONGSARO_KEY)와 신청 상태를 확인하세요.")
    return root


def _fields(item: ET.Element) -> dict[str, str]:
    return {c.tag.rsplit("}", 1)[-1]: v for c in item if (v := _t(c))}


def parse_list(xml_text: str) -> list[dict]:
    root = _root(xml_text)
    return [f for f in (_fields(i) for i in _findall(root, "item")) if f.get("cntntsNo") or f.get("cntntsSj")]


def parse_detail(xml_text: str) -> dict:
    root = _root(xml_text)
    items = _findall(root, "item")
    return _fields(items[0]) if items else {}


def to_item(f: dict, detail: dict | None = None) -> Item:
    d = {**f, **(detail or {})}
    comps = {label: d[k] for k, label in COMPONENTS.items() if d.get(k)}
    parts = []
    if comps:
        parts.append("[성분] " + ", ".join(f"{k} {v}" for k, v in comps.items()))
    if d.get("chartrCn"):
        parts.append(f"[특성] {d['chartrCn']}")
    if d.get("useLevelAtpnCn"):
        parts.append(f"[이용 수준·주의] {d['useLevelAtpnCn']}")
    no = d.get("cntntsNo") or d.get("cntntsSj")
    return Item(
        source="datagokr_byprod", source_id=str(no), title=f"[농식품부산물 영양정보] {d.get('cntntsSj') or no}",
        venue="농촌진흥청 농사로 — 농식품부산물 영양정보", abstract="\n".join(parts) or None,
        url="https://www.nongsaro.go.kr/portal/ps/psn/psnj/openApiLst.ps?menuId=PS65428", pdf_url=None, oa=True,
        language="ko", doc_type="dataset", license="농사로 Open API 이용약관(출처 표시)",
        extra={k: v for k, v in {"콘텐츠번호": d.get("cntntsNo"), "가축구분": d.get("lvstckSeNm"),
                                 "성분": comps or None, "이미지": d.get("imgUrl")}.items() if v},
    ).normalized()


class FoodByproductNutri(Source):
    key = "datagokr_byprod"
    name = "농사로 농식품부산물 영양정보"
    group = "공공데이터"
    homepage = "https://www.nongsaro.go.kr/portal/ps/psn/psnj/openApiLst.ps?menuId=PS65428"
    terms_url = "https://www.nongsaro.go.kr/portal/ps/psz/psza/contentMain.ps?menuId=PS00191"
    needs_env = (ENV_KEY,)
    key_help = ("농사로(https://www.nongsaro.go.kr) 회원 가입·본인 확인 → 'Open API' 신청"
                "(https://www.nongsaro.go.kr/portal/ps/psz/psza/contentMain.ps?menuId=PS00191)에서 '농식품부산물 영양정보' 선택, "
                "서비스 도메인 입력 → 승인되면 신청 내역에서 키 확인. 환경 변수 BYORBIT_NONGSARO_KEY에 넣고 앱을 다시 켜세요.")
    doc_types = ("dataset",)

    def _get(self, op: str, params: dict, key: str) -> str:
        try:
            return http.get_text(f"{BASE}/{op}", {"apiKey": key, **params}, {"Accept": "application/xml"})
        except http.HttpError as e:
            raise SourceError(mask(f"농사로 호출 실패: {e}. 키와 네트워크를 확인하세요.", key)) from None

    def search(self, query: str, *, limit: int = 25, since_year: int | None = None) -> list[Item]:
        key = self.env(ENV_KEY)
        try:
            rows = parse_list(self._get("foodbyprdNtrinfoLst",
                                        {"sText": query.strip(), "pageNo": 1,
                                         "numOfRows": max(1, min(int(limit), 50))}, key))
            out = []
            for i, f in enumerate(rows[:limit]):
                det = None
                if i < DETAIL_MAX and f.get("cntntsNo"):
                    try:
                        det = parse_detail(self._get("foodbyprdNtrinfoDtl", {"cntntsNo": f["cntntsNo"]}, key))
                    except SourceError:
                        det = None                     # 상세 실패는 목록 결과를 막지 않는다
                out.append(to_item(f, det))
            return out
        except SourceError as e:
            raise SourceError(mask(str(e), key)) from None


SOURCE = FoodByproductNutri()
