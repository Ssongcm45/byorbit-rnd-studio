"""Semantic Scholar — AI2의 학술 그래프(키 없이 사용 가능, 대신 자주 막힘).

공식 문서
- Graph API: https://api.semanticscholar.org/api-docs/graph  (/graph/v1/paper/search?query=&limit=&fields=&year=YYYY-)
- 한도·키: https://www.semanticscholar.org/product/api  — 키 없는 호출은 전 세계 사용자가 한도를 나눠 써서
  429(Too Many Requests)가 잦다. 호스트 간격을 1.1초로 두고, http 모듈이 Retry-After만큼 한 번 기다려 다시 시도한다.
  환경 변수 SEMANTIC_SCHOLAR_API_KEY가 있으면 x-api-key 헤더로 붙인다(선택).
"""
from __future__ import annotations

import os

from .. import http
from ..base import Item, Source, SourceError

API = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,year,authors,venue,abstract,externalIds,openAccessPdf,isOpenAccess,url,publicationTypes,journal"

http.set_interval("api.semanticscholar.org", 1.1)


def _doc_type(types) -> str:
    t = {x.lower() for x in (types or [])}
    if "dataset" in t:
        return "dataset"
    if t & {"journalarticle", "review", "conference", "letterseditorial", "casereport", "clinicaltrial", "study"} or not t:
        return "article"
    if "book" in t or "booksection" in t:
        return "other"
    return "article"


def parse(data: dict) -> list[Item]:
    out = []
    for p in data.get("data") or []:
        pid = p.get("paperId")
        if not pid:
            continue
        ext = p.get("externalIds") or {}
        oap = p.get("openAccessPdf") or {}
        pdf = oap.get("url") or None
        out.append(Item(
            source="semanticscholar", source_id=pid, title=p.get("title") or "",
            doi=ext.get("DOI"), authors=[a.get("name") for a in (p.get("authors") or []) if a.get("name")],
            year=p.get("year"), venue=p.get("venue") or (p.get("journal") or {}).get("name"),
            abstract=p.get("abstract"), url=p.get("url"),
            pdf_url=pdf if (p.get("isOpenAccess") or pdf) else None,
            oa=p.get("isOpenAccess") if p.get("isOpenAccess") is not None else (True if pdf else None),
            doc_type=_doc_type(p.get("publicationTypes")), license=oap.get("license"),
            extra={"s2_id": pid, "arxiv": ext.get("ArXiv"), "pubmed": ext.get("PubMed")},
        ).normalized())
    return out


class SemanticScholar(Source):
    key = "semanticscholar"
    name = "Semantic Scholar"
    group = "해외 학술"
    homepage = "https://www.semanticscholar.org"
    terms_url = "https://www.semanticscholar.org/product/api/license"
    description = "AI2의 학술 그래프. 오픈 액세스 PDF 위치를 잘 찾지만, 키 없이 쓰면 혼잡할 때 잠시 막힙니다."
    doc_types = ("article", "dataset")
    optional_env = ("SEMANTIC_SCHOLAR_API_KEY",)
    optional_key_help = ("키 없이도 쓸 수 있지만 혼잡할 때 자주 막힙니다. Semantic Scholar API 신청 양식"
                         "(https://www.semanticscholar.org/product/api#api-key-form)으로 무료 키를 신청해 받은 값을 넣으세요.")

    def search(self, query: str, *, limit: int = 25, since_year: int | None = None) -> list[Item]:
        params = {"query": query, "limit": max(1, min(int(limit), 100)), "fields": FIELDS}
        if since_year:
            params["year"] = f"{int(since_year)}-"
        key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
        headers = {"x-api-key": key} if key else None
        try:
            data = http.get_json(API, params, headers, timeout=30)
        except http.HttpError as e:
            if e.status == 429:
                raise SourceError("Semantic Scholar가 혼잡해 잠시 막혔습니다(키 없는 공용 한도). 1분쯤 뒤 다시 하거나, "
                                  "무료 키를 받아 설정 → API 키 관리의 SEMANTIC_SCHOLAR_API_KEY에 넣으세요"
                                  "(https://www.semanticscholar.org/product/api#api-key-form).") from e
            raise SourceError(f"Semantic Scholar 검색 실패: {e}. 잠시 뒤 다시 시도하세요.") from e
        return parse(data)

    def info(self) -> dict:
        return {**super().info(), "description": self.description}


SOURCE = SemanticScholar()
