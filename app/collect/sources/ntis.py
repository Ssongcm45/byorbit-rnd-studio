"""NTIS 국가과학기술지식정보서비스 — 국가R&D 과제 + 연구보고서 검색(Open API, 키 필요).

공식 문서(2026-11-25 확인)
- Open API 목록·신청: https://www.ntis.go.kr/rndopen/api/mng/apiMain.do  (6605 과제검색, 6607 연구보고서 검색)
- 매뉴얼: https://www.ntis.go.kr/rndopen/menual/openapi_menual.pdf, API별 PDF(과제검색 2025-12-16, 연구보고서 2024-01-03 —
  로그인이 필요해 공개 사본으로 확인). 매뉴얼의 표(SRWR·searchFd·displayCnt)와 예제 호출(query·searchField·
  displayCount·sortby)이 서로 달라 **예제 호출의 이름**을 쓴다 — 실제 키로 첫 호출 때 확인 필요.
- 과제 검색: https://www.ntis.go.kr/rndopen/openApi/public_project
  매개변수: apprvKey, collection=project, query, searchField(BI=전체), sortby(RANK/DESC), startPosition(1부터),
  displayCount, addQuery(예: PY=2020/MORE), naviCount
- 연구보고서 검색: https://www.ntis.go.kr/rndopen/openApi/rresearchpdf  (r이 두 개 — 공식 주소 그대로)
  매개변수: apprvKey, collection=rresearchpdf, query, searchField, displayCount, startPosition, sortby, addQuery
  HIT: ResearchPublicNo(TRKO… = ScienceON 보고서 CN), ResultTitle/Korean·English, Abstract/Korean, Keyword/Korean,
  PublicationYm·PublicationYear, PublicationAgency, LeadAgency, Manager·ManagerName, ProjectNumber, ProjectTitle,
  DocUrl(원문 보기 화면 — PDF 직접 주소가 아니므로 pdf_url로 쓰지 않음)
- 각 API는 따로 '활용신청'해야 한다. 보고서 API가 승인되지 않았으면 과제 결과만 돌려준다.
- 응답(XML): RESULT > TOTALHITS, RESULTSET > HIT*
  HIT: ProjectNumber, ProjectTitle/Korean·English, Manager/Name, Researchers, Goal/Full·Teaser,
  Abstract/Full·Teaser, Effect/Full·Teaser, Keyword/Korean·English, OrderAgency/Name, ResearchAgency/Name,
  BudgetProject/Name, Ministry/Name, ProjectYear, ProjectPeriod/Start·End·TotalStart·TotalEnd, GovernmentFunds
- 오류: 루트가 <error>…</error> — 보낸 인증키를 그대로 되돌려 준다("유효한 인증키가 아닙니다. 인증키 : …",
  2026-11-25 키 없이 호출해 확인) → 메시지를 보여 주기 전에 반드시 가린다.
- 검색어 강조 <span class="search_word">…</span>가 글자 안에 섞여 오므로 태그를 지운다. 과제 상세 주소는 응답에
  없어 https://www.ntis.go.kr/project/pjtInfo.do?pjtId={과제번호}로 만든다(로그인 필요 화면).
- 이용 조건: API 상세 화면 — 연구개발 활동 목적, 신청기관 내부 활용, 공공누리 제1유형. 외부 공개 화면에는 정해진
  항목만 보일 수 있다(이 앱은 개인 PC 안에서만 쓴다). 한도 30 tps — 이 앱은 호출 간격을 1초 이상으로 둔다.
- 키는 환경 변수 BYORBIT_NTIS_KEY로만 받는다.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from .. import http
from ..base import Item, Source, SourceError, clean_text
from .kci import _find, _findall, _t, mask

API = "https://www.ntis.go.kr/rndopen/openApi/public_project"
API_REPORT = "https://www.ntis.go.kr/rndopen/openApi/rresearchpdf"
ENV_KEY = "BYORBIT_NTIS_KEY"
VIEW = "https://www.ntis.go.kr/project/pjtInfo.do?pjtId={pid}&pageCode=TH_PJT_PJT_DTL"
http.set_interval("www.ntis.go.kr", 1.0)


def _sub(el, *path: str) -> str | None:
    cur = el
    for p in path:
        if cur is None:
            return None
        cur = next((c for c in list(cur) if c.tag.rsplit("}", 1)[-1] == p), None)
    v = _t(cur)
    return (clean_text(v) or None) if v else None


def parse(xml_text: str) -> tuple[list[Item], int | None]:
    try:
        root = ET.fromstring(xml_text.strip().encode("utf-8"))
    except ET.ParseError as e:
        raise SourceError(f"NTIS 응답을 읽지 못했습니다(XML 오류: {e}). 잠시 뒤 다시 시도하세요.") from None
    if root.tag.lower() == "error" or _find(root, "error") is not None:
        msg = _t(root) if root.tag.lower() == "error" else _t(_find(root, "error"))
        raise SourceError(f"NTIS가 오류를 돌려주었습니다: {msg or '알 수 없음'}. "
                          "키(BYORBIT_NTIS_KEY)의 승인 상태와 이용 서비스(국가R&D 과제)를 확인하세요.")
    th = _t(_find(root, "TOTALHITS"))
    total = int(th) if th and th.isdigit() else None
    out: list[Item] = []
    for hit in _findall(root, "HIT"):
        pid = _sub(hit, "ProjectNumber")
        title = _sub(hit, "ProjectTitle", "Korean") or _sub(hit, "ProjectTitle")
        if not (pid or title):
            continue
        en = _sub(hit, "ProjectTitle", "English")
        parts = []
        for label, tag in (("연구목표", "Goal"), ("연구내용", "Abstract"), ("기대효과", "Effect")):
            v = _sub(hit, tag, "Full") or _sub(hit, tag, "Teaser") or _sub(hit, tag)
            if v:
                parts.append(f"[{label}] {v}")
        manager = _sub(hit, "Manager", "Name") or _sub(hit, "Manager")
        rs = _sub(hit, "Researchers", "Name") or _sub(hit, "Researchers") or ""
        researchers = [x.strip() for x in rs.replace(";", ",").split(",") if x.strip()]
        authors = ([manager] if manager else []) + [r for r in researchers if r != manager]
        year = _sub(hit, "ProjectYear")
        kw = ", ".join(x for x in (_sub(hit, "Keyword", "Korean"), _sub(hit, "Keyword", "English")) if x) or None
        extra = {
            "과제번호": pid, "과제명_영문": en, "연구책임자": manager,
            "주관연구기관": _sub(hit, "ResearchAgency", "Name"), "전문기관": _sub(hit, "OrderAgency", "Name"),
            "부처": _sub(hit, "Ministry", "Name"), "사업명": _sub(hit, "BudgetProject", "Name"),
            "기준연도": year, "연구기간": "~".join(x for x in (_sub(hit, "ProjectPeriod", "Start"),
                                                         _sub(hit, "ProjectPeriod", "End")) if x) or None,
            "총연구기간": "~".join(x for x in (_sub(hit, "ProjectPeriod", "TotalStart"),
                                            _sub(hit, "ProjectPeriod", "TotalEnd")) if x) or None,
            "정부연구비": _sub(hit, "GovernmentFunds"), "키워드": kw,
        }
        out.append(Item(
            source="ntis", source_id=pid or title[:80], title=title or en or "", authors=authors[:20],
            year=year, venue=extra["주관연구기관"] or extra["부처"] or "NTIS 국가R&D",
            abstract="\n".join(parts) or None, url=VIEW.format(pid=pid) if pid else "https://www.ntis.go.kr",
            pdf_url=None, oa=None, language="ko", doc_type="project",
            extra={k: v for k, v in extra.items() if v},
        ).normalized())
    return out, total


def parse_reports(xml_text: str) -> list[Item]:
    try:
        root = ET.fromstring(xml_text.strip().encode("utf-8"))
    except ET.ParseError as e:
        raise SourceError(f"NTIS 보고서 응답을 읽지 못했습니다(XML 오류: {e}).") from None
    if root.tag.lower() == "error":
        raise SourceError(f"NTIS 연구보고서 API 오류: {_t(root)}. 연구보고서 검색 API도 활용신청했는지 확인하세요.")
    if _find(root, "resCd") is not None and _t(_find(root, "resMsg")):
        raise SourceError(f"NTIS 연구보고서 API 오류: {_t(_find(root, 'resMsg'))}")
    out = []
    for hit in _findall(root, "HIT"):
        rid = _sub(hit, "ResearchPublicNo") or _sub(hit, "TermSn")
        title = _sub(hit, "ResultTitle", "Korean") or _sub(hit, "ResultTitle")
        if not (rid or title):
            continue
        ym = _sub(hit, "PublicationYm") or _sub(hit, "PublicationYear") or ""
        mgr = _sub(hit, "ManagerName") or _sub(hit, "Manager")
        agency = _sub(hit, "PublicationAgency") or _sub(hit, "LeadAgency") or _sub(hit, "ManageAgency")
        doc = _sub(hit, "DocUrl") or _sub(hit, "NrmsUrl")
        extra = {"보고서번호": rid, "등록번호": _sub(hit, "TermSn"), "과제번호": _sub(hit, "ProjectNumber"),
                 "과제명": _sub(hit, "ProjectTitle"), "제목_영문": _sub(hit, "ResultTitle", "English"),
                 "발행연월": ym or None, "키워드": _sub(hit, "Keyword", "Korean"), "원문보기": doc}
        out.append(Item(
            source="ntis", source_id=rid or title[:80], title=title or "", authors=[mgr] if mgr else [],
            year=ym[:4] if ym[:4].isdigit() else None, venue=agency or "NTIS 연구보고서",
            abstract=_sub(hit, "Abstract", "Korean") or _sub(hit, "Abstract"),
            url=doc or (f"https://scienceon.kisti.re.kr/srch/selectPORSrchReport.do?cn={rid}" if rid else None),
            pdf_url=None, oa=None, language="ko", doc_type="report",
            extra={k: v for k, v in extra.items() if v},
        ).normalized())
    return out


class NTIS(Source):
    key = "ntis"
    name = "NTIS 국가R&D 과제"
    group = "국가 R&D·특허"
    homepage = "https://www.ntis.go.kr"
    terms_url = "https://www.ntis.go.kr/rndopen/api/mng/apiMain.do"
    needs_env = (ENV_KEY,)
    key_help = ("NTIS(https://www.ntis.go.kr) 회원 가입·로그인 → '국가R&D 개방' > 'Open API'(https://www.ntis.go.kr/rndopen/api/mng/apiMain.do)에서 "
                "'국가R&D 과제검색'과 '연구보고서 검색' 활용 신청(소속기관 등록 필요) → 승인되면 마이페이지에서 승인키(apprvKey) 확인. "
                "키를 설정 → API 키 관리의 BYORBIT_NTIS_KEY에 넣으세요(또는 같은 이름의 환경 변수).")
    doc_types = ("project", "report")
    last_warning: str | None = None

    def _call(self, url: str, collection: str, query: str, n: int, since_year, key: str) -> str:
        params = {"apprvKey": key, "collection": collection, "query": query, "searchField": "BI",
                  "sortby": "RANK/DESC", "startPosition": 1, "displayCount": n, "naviCount": 0}
        if since_year:
            params["addQuery"] = f"PY={int(since_year)}/MORE"
        try:
            return http.get_text(url, params, {"Accept": "application/xml"})
        except http.HttpError as e:
            raise SourceError(mask(f"NTIS 검색 실패: {e}. 키(승인 IP 포함)와 네트워크를 확인한 뒤 다시 시도하세요.",
                                   key)) from None

    def search(self, query: str, *, limit: int = 25, since_year: int | None = None) -> list[Item]:
        key = self.env(ENV_KEY)
        n = max(1, min(int(limit), 100))
        try:
            items, _ = parse(self._call(API, "project", query, n, since_year, key))
        except SourceError as e:
            raise SourceError(mask(str(e), key)) from None
        try:                                   # 연구보고서는 따로 활용신청 — 실패해도 과제 결과는 돌려준다
            reports = parse_reports(self._call(API_REPORT, "rresearchpdf", query, n, since_year, key))
            self.last_warning = None
        except SourceError as e:
            self.last_warning = mask(str(e), key)
            reports = []
        merged = []
        for pair in zip(items, reports):       # 과제·보고서를 번갈아 섞는다
            merged.extend(pair)
        items = merged + items[len(reports):] + reports[len(items):]
        if since_year:
            items = [i for i in items if not i.year or i.year >= since_year]
        return items[:limit]


SOURCE = NTIS()
