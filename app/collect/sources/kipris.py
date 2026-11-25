"""KIPRIS Plus — 특허·실용신안 검색(한국특허정보원 Open API, 키 필요).

공식 문서(2026-11-25 확인)
- 서비스 안내: https://plus.kipris.or.kr/portal/data/service/DBII_000000000000001/view.do?menuNo=200100
  (특허·실용 공개·등록공보, 오퍼레이션 명세 getAdvancedSearch). getWordSearch는 '폐기예정'이라 쓰지 않는다.
- 요청: https://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/getAdvancedSearch
  매개변수: word(자유 검색어), patent=true, utility=true, numOfRows(기본 20, 최대 500), pageNo(1부터),
  applicationDate(YYYYMMDD~YYYYMMDD), sortSpec(AD=출원일 …), descSort, ServiceKey(발급 키).
  ('Sevice'는 공식 주소의 철자 그대로)
- 응답(XML): response > header(successYN, resultCode, resultMsg) > body > items > item*, count는 body와 형제
  item: indexNo, registerStatus, inventionTitle, ipcNumber('|' 구분), registerNumber, registerDate,
  applicationNumber, applicationDate(YYYYMMDD), openNumber, openDate, publicationNumber, publicationDate,
  astrtCont(요약), drawing, bigDrawing, applicantName
  count > numOfRows, pageNo, totalCount. 날짜는 YYYYMMDD(옛 형식 "1985/12/30 00:00:00"도 처리), IPC·출원인은 '|' 구분
- 오류: HTTP 200 + successYN=N, resultCode=30 SERVICE_KEY_IS_NOT_REGISTERED_ERROR(2026-11-25 키 없이 호출해 확인)
- 원문: 공보 PDF는 KIPRIS 화면에서 열람(API에 원문·랜딩 주소 없음) → pdf_url 없음. 랜딩은 출원번호로 만든
  특허 DOI(10.8080/출원번호, 특허청 DOI 체계 — 추정, 실제 키로 미검증) 주소.
- 이용 조건·요금: https://plus.kipris.or.kr/portal/use/paymentMmg.do?menuNo=210112 — 월 1,000건 무료(매월 1일 초기화),
  초과는 유료. 이 앱은 호출 간격을 1초 이상으로 두고 한 번에 최대 100건만 받는다.
- 키는 환경 변수 BYORBIT_KIPRIS_KEY로만 받는다.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .. import http
from ..base import Item, Source, SourceError
from .kci import _find, _findall, _local, _t, mask  # noqa: F401 — 같은 묶음(B)의 XML·가리기 도우미

API = "https://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/getAdvancedSearch"
ENV_KEY = "BYORBIT_KIPRIS_KEY"
http.set_interval("plus.kipris.or.kr", 1.0)


def _date(s: str | None) -> str | None:
    d = re.sub(r"\D", "", (s or "").strip()[:10])
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) >= 8 else None


def parse(xml_text: str) -> tuple[list[Item], int | None]:
    try:
        root = ET.fromstring(xml_text.strip().encode("utf-8"))
    except ET.ParseError as e:
        raise SourceError(f"KIPRIS 응답을 읽지 못했습니다(XML 오류: {e}). 잠시 뒤 다시 시도하세요.") from None
    code = _t(_find(root, "resultCode"))
    if code not in (None, "00", "0", "000"):
        msg = _t(_find(root, "resultMsg")) or ""
        raise SourceError(f"KIPRIS 오류({code} {msg}). 키(BYORBIT_KIPRIS_KEY)·월 호출 한도를 확인하세요.")
    if (_t(_find(root, "successYN")) or "Y").upper() == "N":
        raise SourceError(f"KIPRIS 오류: {_t(_find(root, 'resultMsg')) or '실패'}. 키와 호출 한도를 확인하세요.")
    tc = _t(_find(root, "totalCount"))
    total = int(tc) if tc and tc.isdigit() else None
    out: list[Item] = []
    for it in _findall(root, "item"):
        g = lambda n: _t(_find(it, n))  # noqa: E731
        app_no = g("applicationNumber")
        title = g("inventionTitle")
        if not (app_no or title):
            continue
        ipc = [x.strip() for x in (g("ipcNumber") or "").split("|") if x.strip()]
        applicants = [x.strip() for x in (g("applicantName") or "").split("|") if x.strip()]
        app_date = _date(g("applicationDate"))
        url = (f"https://doi.org/10.8080/{app_no}" if app_no and len(app_no) == 13 else None)
        out.append(Item(
            source="kipris", source_id=app_no or title[:80], title=title or "",
            authors=applicants, year=app_date[:4] if app_date else None,
            venue="특허청(KIPO)", abstract=g("astrtCont"),
            url=url or "https://www.kipris.or.kr/khome/main.do", pdf_url=None, oa=None, language="ko",
            doc_type="patent",
            extra={k: v for k, v in {
                "출원번호": app_no, "출원일": app_date, "출원인": applicants or None, "IPC": ipc or None,
                "등록상태": g("registerStatus"), "등록번호": g("registerNumber"), "등록일": _date(g("registerDate")),
                "공개번호": g("openNumber"), "공개일": _date(g("openDate")),
                "공고번호": g("publicationNumber"), "공고일": _date(g("publicationDate")),
                "대표도면": g("bigDrawing") or g("drawing"),
            }.items() if v},
        ).normalized())
    return out, total


class KIPRIS(Source):
    key = "kipris"
    name = "KIPRIS Plus 특허"
    group = "국가 R&D·특허"
    homepage = "https://plus.kipris.or.kr"
    terms_url = "https://plus.kipris.or.kr/portal/use/paymentMmg.do?menuNo=210112"
    needs_env = (ENV_KEY,)
    key_help = ("KIPRIS Plus(https://plus.kipris.or.kr) 회원 가입 → '데이터 신청' > '특허·실용 공개·등록공보' "
                "Open API 신청(https://plus.kipris.or.kr/portal/data/request/apiFsmtmList.do?menuNo=290005) → 승인 후 마이페이지에서 "
                "키 확인(월 1,000건 무료). "
                "키를 환경 변수 BYORBIT_KIPRIS_KEY에 넣고 앱을 다시 켜세요.")
    doc_types = ("patent",)

    def search(self, query: str, *, limit: int = 25, since_year: int | None = None) -> list[Item]:
        key = self.env(ENV_KEY)
        params = {"word": query, "patent": "true", "utility": "true",
                  "numOfRows": max(1, min(int(limit), 100)), "pageNo": 1, "ServiceKey": key}
        if since_year:
            params["applicationDate"] = f"{int(since_year)}0101~{int(since_year) + 100}1231"
        try:
            txt = http.get_text(API, params, {"Accept": "application/xml"})
        except http.HttpError as e:
            raise SourceError(mask(f"KIPRIS 검색 실패: {e}. 키와 네트워크를 확인한 뒤 다시 시도하세요.", key)) from None
        try:
            items, _ = parse(txt)
        except SourceError as e:
            raise SourceError(mask(str(e), key)) from None
        if since_year:
            items = [i for i in items if not i.year or i.year >= since_year]
        return items[:limit]


SOURCE = KIPRIS()
