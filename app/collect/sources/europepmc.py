"""Europe PMC — 생명과학·식품·농학 문헌(PubMed·PMC·Agricola 포함), 키 없이 사용 가능.

공식 문서
- REST 검색: https://europepmc.org/RestfulWebService  (/webservices/rest/search?query=&format=json&resultType=core&pageSize=)
- 검색 문법: https://europepmc.org/searchsyntax  (FIRST_PDATE:[YYYY-MM-DD TO YYYY-MM-DD], OPEN_ACCESS:y)
- 전문 XML: https://europepmc.org/RestfulWebService#!/Europe32PMC32Articles32RESTful32API/fullTextXML
  (/webservices/rest/{PMCID}/fullTextXML — 오픈 액세스 논문만)
- 이용 조건: https://europepmc.org/Copyright
- europepmc.org/articles/…?pdf=render 링크는 2026-11 확인 결과 브라우저가 아닌 호출에 403을 돌려준다.
  그래서 pdf_url은 넘기지 않고, isOpenAccess=Y이고 PMCID가 있으면 공식 전문 XML 주소를 extra["fulltext_xml"]로
  넘긴다(store.ingest가 이를 받아 본문을 .md로 넣는다). 공식 한도 수치는 없지만 정중하게 0.5초 간격을 둔다.
"""
from __future__ import annotations

from .. import http
from ..base import Item, Source, SourceError

API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
LANG = {"eng": "en", "kor": "ko", "chi": "zh", "jpn": "ja", "ger": "de", "fre": "fr", "spa": "es"}

http.set_interval("www.ebi.ac.uk", 0.5)


def _doc_type(r: dict) -> str:
    if r.get("source") == "PAT":
        return "patent"
    if r.get("source") == "ETH":
        return "thesis"
    types = " ".join((r.get("pubTypeList") or {}).get("pubType") or []).lower()
    if "dissertation" in types or "thesis" in types:
        return "thesis"
    if "dataset" in types:
        return "dataset"
    return "article"


FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"


def _fulltext(r: dict) -> str | None:
    pmcid = r.get("pmcid")
    if r.get("isOpenAccess") == "Y" and pmcid and r.get("inEPMC", "Y") == "Y":
        return FULLTEXT.format(pmcid=pmcid)
    return None


def parse(data: dict) -> list[Item]:
    out = []
    for r in ((data.get("resultList") or {}).get("result") or []):
        src, rid = r.get("source"), r.get("id")
        if not (src and rid):
            continue
        authors = [a.get("fullName") for a in ((r.get("authorList") or {}).get("author") or []) if a.get("fullName")]
        if not authors and r.get("authorString"):
            authors = [a.strip() for a in r["authorString"].rstrip(".").split(",") if a.strip()]
        ji = r.get("journalInfo") or {}
        venue = (ji.get("journal") or {}).get("title") or r.get("journalTitle") or \
            (r.get("bookOrReportDetails") or {}).get("publisher")
        oa = {"Y": True, "N": False}.get(r.get("isOpenAccess"))
        out.append(Item(
            source="europepmc", source_id=f"{src}:{rid}", title=r.get("title") or "",
            doi=r.get("doi"), authors=authors, year=r.get("pubYear"), venue=venue,
            abstract=r.get("abstractText"), url=f"https://europepmc.org/article/{src}/{rid}",
            pdf_url=None, oa=oa, language=LANG.get(r.get("language") or "", r.get("language")),
            doc_type=_doc_type(r), license=r.get("license"),
            extra={"pmid": r.get("pmid"), "pmcid": r.get("pmcid"), "epmc_source": src,
                   "fulltext_xml": _fulltext(r)},
        ).normalized())
    return out


class EuropePMC(Source):
    key = "europepmc"
    name = "Europe PMC"
    group = "해외 학술"
    homepage = "https://europepmc.org"
    terms_url = "https://europepmc.org/Copyright"
    description = "생명과학·식품·농학 논문(PubMed·PMC·Agricola). 오픈 액세스 논문은 본문 전체를 넣을 수 있습니다."
    doc_types = ("article", "thesis", "patent")

    def search(self, query: str, *, limit: int = 25, since_year: int | None = None) -> list[Item]:
        q = query if not since_year else f"({query}) AND FIRST_PDATE:[{int(since_year)}-01-01 TO 3000-12-31]"
        params = {"query": q, "format": "json", "resultType": "core", "pageSize": max(1, min(int(limit), 100))}
        try:
            data = http.get_json(API, params, timeout=30)
        except http.HttpError as e:
            raise SourceError(f"Europe PMC 검색 실패: {e}. 잠시 뒤 다시 시도하세요.") from e
        return parse(data)

    def info(self) -> dict:
        return {**super().info(), "description": self.description}


SOURCE = EuropePMC()
