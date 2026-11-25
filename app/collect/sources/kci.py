"""KCI 한국학술지인용색인 — 국내 학술지 논문 검색(Open API, 키 필요).

공식 문서(2026-11-25 확인)
- Open API 안내·신청: https://www.kci.go.kr/kciportal/po/openapi/openApiList.kci  (KCI 포털 > 오픈 API)
- 논문 검색 요청: https://open.kci.go.kr/po/openapi/openApiSearch.kci?apiCode=articleSearch&key=…&title=…
  매개변수: apiCode=articleSearch, key(발급 키), title(논문명) 또는 keyword, displayCount(1–100), page(1부터),
  dateFrom/dateTo(YYYYMM), sortNm(정렬)
- 응답(XML): MetaData > outputData > result > total, record*(journalInfo, articleInfo)
  journalInfo: journal-name, publisher-name, pub-year, pub-mon, volume, issue
  articleInfo@article-id: title-group/article-title(@lang=original|english|foreign), author-group/author,
  abstract-group/abstract(@lang), fpage, lpage, doi, url, citation-count
- 원문: KCI 원문은 대부분 KCI 포털에서 무료 열람이지만 API는 PDF 직접 주소를 주지 않는다 → pdf_url 없음,
  랜딩 url만 넘긴다.
- 이용 조건: KCI 오픈 API 이용약관(신청 화면) — 비영리·출처 표시. 하루 호출 한도는 신청 유형별로 다르다
  (문서상 명시 수치가 없어 이 앱은 호출 간격을 1초 이상으로 둔다).
- 키는 환경 변수 BYORBIT_KCI_KEY로만 받는다. 오류 메시지에 키가 섞이면 가린다.
"""
from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET

from .. import http
from ..base import Item, Source, SourceError

API = "https://open.kci.go.kr/po/openapi/openApiSearch.kci"
ENV_KEY = "BYORBIT_KCI_KEY"
http.set_interval("open.kci.go.kr", 1.0)


def mask(text: str, *secrets: str) -> str:
    """메시지 속 API 키(원문·URL 인코딩 모두)를 ***로 가린다."""
    text = str(text)
    for s in secrets:
        if s and len(s) >= 4:
            for v in {s, urllib.parse.quote(s, safe=""), urllib.parse.quote_plus(s)}:
                text = text.replace(v, "***")
    return re.sub(r"(?i)((?:service)?key|token|client_id|apprvKey|accessKey)=([^&\s\"'<]+)", r"\1=***", text)


def _t(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    s = "".join(el.itertext()).strip()
    return s or None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(el: ET.Element, name: str) -> ET.Element | None:
    for c in el.iter():
        if _local(c.tag) == name:
            return c
    return None


def _findall(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el.iter() if _local(c.tag) == name]


def _pick_lang(els: list[ET.Element], order=("original", "korean", "foreign", "english")) -> str | None:
    by = {(e.get("lang") or "").lower(): _t(e) for e in els if _t(e)}
    for k in order:
        if by.get(k):
            return by[k]
    return next((v for v in by.values() if v), None)


def _author(s: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", s).strip()   # "홍길동(OO대학교)" → "홍길동"


def parse(xml_text: str) -> tuple[list[Item], int | None]:
    try:
        root = ET.fromstring(xml_text.strip().encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError as e:
        raise SourceError(f"KCI 응답을 읽지 못했습니다(XML 오류: {e}). 잠시 뒤 다시 시도하세요.") from None
    # 오류는 outputData > result > resultMsg 로 온다(예: "등록되지 않은 key 입니다." — 2026-11-25 키 없이 호출해 확인).
    # 응답의 inputData에는 보낸 key가 그대로 되돌아오므로 그 부분은 절대 메시지에 쓰지 않는다.
    out_el = _find(root, "outputData")
    scope = out_el if out_el is not None else root
    total = _find(scope, "total")
    msg = _t(_find(scope, "resultMsg"))
    if msg and total is None and not _findall(scope, "record"):
        raise SourceError(f"KCI가 오류를 돌려주었습니다: {msg} 키(BYORBIT_KCI_KEY)와 신청 상태를 확인하세요.")
    try:
        total_n = int(_t(total)) if total is not None else None
    except (TypeError, ValueError):
        total_n = None
    out: list[Item] = []
    for rec in _findall(scope, "record"):
        art = _find(rec, "articleInfo")
        jr = _find(rec, "journalInfo")
        if art is None:
            continue
        aid = art.get("article-id") or _t(_find(art, "article-id")) or ""
        titles = _findall(art, "article-title")
        title = _pick_lang(titles)
        en = _pick_lang(titles, order=("english",))
        abstract = _pick_lang(_findall(art, "abstract"))
        authors = [_author(_t(a)) for a in _findall(art, "author") if _t(a)]
        year = _t(_find(jr, "pub-year")) if jr is not None else None
        url = _t(_find(art, "url")) or (
            f"https://www.kci.go.kr/kciportal/ci/sereArticleSearch/ciSereArtiView.kci?sereArticleSearchBean.artiId={aid}"
            if aid else None)
        extra = {"kci_id": aid, "title_en": en if en != title else None,
                 "publisher": _t(_find(jr, "publisher-name")) if jr is not None else None,
                 "volume": _t(_find(jr, "volume")) if jr is not None else None,
                 "issue": _t(_find(jr, "issue")) if jr is not None else None,
                 "pages": "-".join(x for x in (_t(_find(art, "fpage")), _t(_find(art, "lpage"))) if x) or None,
                 "citations": _t(_find(art, "citation-count"))}
        if not (aid or title):
            continue
        out.append(Item(
            source="kci", source_id=aid or (title or "")[:80], title=title or en or "",
            doi=_t(_find(art, "doi")), authors=authors, year=year,
            venue=_t(_find(jr, "journal-name")) if jr is not None else None,
            abstract=abstract, url=url, pdf_url=None, oa=None, language="ko", doc_type="article",
            extra={k: v for k, v in extra.items() if v},
        ).normalized())
    return out, total_n


class KCI(Source):
    key = "kci"
    name = "KCI 한국학술지인용색인"
    group = "국내 학술"
    homepage = "https://www.kci.go.kr"
    terms_url = "https://www.kci.go.kr/kciportal/po/openapi/openApiList.kci"
    needs_env = (ENV_KEY,)
    key_help = ("KCI 포털(https://www.kci.go.kr) 로그인 → 상단 '오픈 API' → 'Open API 신청'에서 논문 검색(articleSearch) "
                "이용을 신청하면 인증키가 메일·마이페이지로 발급됩니다. 발급 키를 환경 변수 BYORBIT_KCI_KEY에 넣고 앱을 다시 켜세요.")
    doc_types = ("article",)

    def search(self, query: str, *, limit: int = 25, since_year: int | None = None) -> list[Item]:
        key = self.env(ENV_KEY)
        params = {"apiCode": "articleSearch", "key": key, "title": query,
                  "displayCount": max(1, min(int(limit), 100)), "page": 1}
        if since_year:
            params["dateFrom"] = f"{int(since_year)}01"
        try:
            txt = http.get_text(API, params, {"Accept": "application/xml"})
        except http.HttpError as e:
            raise SourceError(mask(f"KCI 검색 실패: {e}. 키와 네트워크를 확인한 뒤 다시 시도하세요.", key)) from None
        try:
            items, _ = parse(txt)
        except SourceError as e:
            raise SourceError(mask(str(e), key)) from None
        if since_year:
            items = [i for i in items if not i.year or i.year >= since_year]
        return items[:limit]


SOURCE = KCI()
