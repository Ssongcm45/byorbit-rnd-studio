"""Crossref — DOI 등록 기관의 서지 메타데이터(키 없이 사용 가능).

공식 문서
- REST API: https://www.crossref.org/documentation/retrieve-metadata/rest-api/
- 사용 요령·한도: https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/
- Swagger: https://api.crossref.org/swagger-ui/index.html  (works?query=&rows=&filter=from-pub-date:YYYY&select=)
- 이메일(mailto)을 보내지 않으므로 공용 풀(public pool)을 쓴다: 2026-11 응답 헤더 기준 초당 1회·동시 1건.

PDF는 보수적으로만 넘긴다: Creative Commons 라이선스이고, 링크의 content-type이 application/pdf이며,
출판사 전용 API(토큰 필요) 주소가 아닐 때만. 나머지는 서지·초록만.
"""
from __future__ import annotations

import re

from .. import http
from ..base import Item, Source, SourceError, clean_text

API = "https://api.crossref.org/works"
SELECT = "DOI,title,author,container-title,issued,published,abstract,license,link,type,URL,publisher"
TYPE_MAP = {"journal-article": "article", "proceedings-article": "article", "posted-content": "article",
            "report": "report", "report-component": "report", "dissertation": "thesis", "dataset": "dataset",
            "standard": "report", "book-chapter": "other", "book": "other", "monograph": "other"}
TOKEN_HOSTS = ("api.elsevier.com", "api.wiley.com", "onlinelibrary.wiley.com/doi/full-xml")

http.set_interval("api.crossref.org", 1.0)


def _year(w: dict) -> int | None:
    for k in ("issued", "published", "published-print", "published-online"):
        dp = ((w.get(k) or {}).get("date-parts") or [[None]])[0]
        if dp and dp[0]:
            return int(dp[0])
    return None


def _license(w: dict) -> str | None:
    lic = w.get("license") or []
    vor = [x for x in lic if x.get("content-version") == "vor"]
    pick = (vor or lic or [{}])[0]
    return pick.get("URL")


def _is_open_license(url: str | None) -> bool:
    return bool(url) and "creativecommons.org" in url


def _pdf(w: dict, lic: str | None) -> str | None:
    if not _is_open_license(lic):
        return None
    for ln in w.get("link") or []:
        u = ln.get("URL") or ""
        if (ln.get("content-type") == "application/pdf" and u.startswith("https://")
                and not any(h in u for h in TOKEN_HOSTS)):
            return u
    return None


def clean_abstract(s: str | None) -> str | None:
    if not s:
        return None
    s = re.sub(r"<jats:title>.*?</jats:title>", " ", s, flags=re.S | re.I)
    s = clean_text(s)
    s = re.sub(r"^(abstract|summary)[\s:.]+", "", s, flags=re.I)
    return s or None


def parse(data: dict) -> list[Item]:
    out = []
    for w in ((data.get("message") or {}).get("items") or []):
        doi = w.get("DOI")
        if not doi:
            continue
        lic = _license(w)
        authors = []
        for a in w.get("author") or []:
            n = " ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name")
            if n:
                authors.append(n)
        out.append(Item(
            source="crossref", source_id=doi.lower(), title=" ".join(w.get("title") or []),
            doi=doi, authors=authors, year=_year(w),
            venue=(w.get("container-title") or [None])[0] or w.get("publisher"),
            abstract=clean_abstract(w.get("abstract")), url=w.get("URL") or f"https://doi.org/{doi}",
            pdf_url=_pdf(w, lic), oa=True if _is_open_license(lic) else None, language=w.get("language"),
            doc_type=TYPE_MAP.get(w.get("type") or "", "other"), license=lic,
            extra={"crossref_type": w.get("type"), "publisher": w.get("publisher")},
        ).normalized())
    return out


class Crossref(Source):
    key = "crossref"
    name = "Crossref"
    group = "해외 학술"
    homepage = "https://www.crossref.org"
    terms_url = "https://www.crossref.org/documentation/retrieve-metadata/rest-api/"
    description = "DOI가 붙은 논문·보고서·학위논문의 공식 서지 정보. 초록은 출판사가 제공한 경우에만 있습니다(초당 1회)."
    doc_types = ("article", "report", "thesis", "dataset")

    def search(self, query: str, *, limit: int = 25, since_year: int | None = None) -> list[Item]:
        params = {"query": query, "rows": max(1, min(int(limit), 100)), "select": SELECT}
        if since_year:
            params["filter"] = f"from-pub-date:{int(since_year)}"
        try:
            data = http.get_json(API, params, timeout=30)
        except http.HttpError as e:
            if e.status == 429:
                raise SourceError("Crossref가 요청이 많다고 잠시 막았습니다. 1~2분 뒤 다시 시도하세요.") from e
            raise SourceError(f"Crossref 검색 실패: {e}. 잠시 뒤 다시 시도하세요.") from e
        return parse(data)

    def info(self) -> dict:
        return {**super().info(), "description": self.description}


SOURCE = Crossref()
