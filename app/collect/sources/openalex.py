"""OpenAlex — 전 세계 학술 문헌 색인(키 없이 사용 가능).

공식 문서
- 검색: https://docs.openalex.org/api-entities/works/search-works
- 필터: https://docs.openalex.org/api-entities/works/filter-works  (from_publication_date:YYYY-MM-DD)
- 필드 선택: https://docs.openalex.org/how-to-use-the-api/get-single-entities/select-fields
- 요금·한도: https://help.openalex.org/  — 2026-11 기준 키 없이 호출하면 같은 IP가 하루 0.1 USD 공용 예산
  (검색 1회 0.001 USD ≈ 하루 100회)을 나눠 쓴다. 환경 변수 OPENALEX_API_KEY가 있으면 api_key로 붙인다(선택).
- 개인정보 원칙에 따라 mailto(이메일)는 보내지 않는다. 그래서 '정중한 풀(polite pool)' 혜택은 없다.
"""
from __future__ import annotations

import os

from .. import http
from ..base import Item, Source, SourceError

API = "https://api.openalex.org/works"
SELECT = ("id,doi,display_name,publication_year,authorships,primary_location,best_oa_location,"
          "open_access,abstract_inverted_index,type,language")
TYPE_MAP = {"article": "article", "review": "article", "preprint": "article", "letter": "article",
            "editorial": "article", "dissertation": "thesis", "dataset": "dataset", "report": "report",
            "standard": "report", "book": "other", "book-chapter": "other"}

http.set_interval("api.openalex.org", 0.2)


def abstract_from_index(inv: dict | None) -> str | None:
    """OpenAlex는 저작권 때문에 초록을 {단어: [위치…]} 역색인으로 준다 → 위치 순서로 다시 잇는다."""
    if not inv:
        return None
    pos: dict[int, str] = {}
    for word, idx in inv.items():
        for i in idx or ():
            pos[int(i)] = word
    return " ".join(pos[i] for i in sorted(pos)) or None


def parse(data: dict) -> list[Item]:
    out = []
    for w in data.get("results") or []:
        oa = w.get("open_access") or {}
        best = w.get("best_oa_location") or {}
        prim = w.get("primary_location") or {}
        venue = ((prim.get("source") or {}).get("display_name")) or ((best.get("source") or {}).get("display_name"))
        is_oa = bool(oa.get("is_oa")) if "is_oa" in oa else None
        pdf = best.get("pdf_url") if is_oa else None
        wid = str(w.get("id") or "").rsplit("/", 1)[-1]
        if not wid:
            continue
        out.append(Item(
            source="openalex", source_id=wid, title=w.get("display_name") or w.get("title") or "",
            doi=w.get("doi"), year=w.get("publication_year"),
            authors=[(a.get("author") or {}).get("display_name") for a in (w.get("authorships") or [])
                     if (a.get("author") or {}).get("display_name")],
            venue=venue, abstract=abstract_from_index(w.get("abstract_inverted_index")),
            url=prim.get("landing_page_url") or w.get("doi") or w.get("id"),
            pdf_url=pdf or None, oa=is_oa, language=w.get("language"),
            doc_type=TYPE_MAP.get(w.get("type") or "", "other"),
            license=best.get("license") or prim.get("license"),
            extra={"openalex_id": w.get("id"), "oa_status": oa.get("oa_status")},
        ).normalized())
    return out


class OpenAlex(Source):
    key = "openalex"
    name = "OpenAlex"
    group = "해외 학술"
    homepage = "https://openalex.org"
    terms_url = "https://openalex.org/terms"   # 데이터는 CC0
    description = "전 세계 논문·보고서 2억 건 이상의 공개 색인. 초록과 오픈 액세스 원문 위치를 함께 줍니다(키 없이 하루 약 100회)."
    doc_types = ("article", "report", "thesis", "dataset")

    def search(self, query: str, *, limit: int = 25, since_year: int | None = None) -> list[Item]:
        params = {"search": query, "per_page": max(1, min(int(limit), 100)), "select": SELECT}
        if since_year:
            params["filter"] = f"from_publication_date:{int(since_year)}-01-01"
        key = os.environ.get("OPENALEX_API_KEY")
        if key:
            params["api_key"] = key
        try:
            data = http.get_json(API, params)
        except http.HttpError as e:
            if e.status == 429:
                raise SourceError("OpenAlex 하루 무료 한도를 다 썼습니다. 내일 다시 하거나, 무료 키를 받아 "
                                  "환경 변수 OPENALEX_API_KEY에 넣으세요(https://openalex.org/settings/api).") from e
            raise SourceError(f"OpenAlex 검색 실패: {e}. 잠시 뒤 다시 시도하세요.") from e
        return parse(data)

    def info(self) -> dict:
        return {**super().info(), "description": self.description}


SOURCE = OpenAlex()
