"""크롤러 출처 — 켜진 크롤러 사이트(app/collect/crawler.py)를 한 출처로 묶는다.

search(query)는 켜진 사이트를 (서로 다른 호스트는 동시에) 예의 바르게 훑고 검색어와 맞는 항목을 돌려준다.
사이트별 결과(쪽수·robots로 건너뛴 주소·메시지)는 SOURCE.last_reports()로 볼 수 있다.
"""
from __future__ import annotations

from .. import crawler
from ..base import Item, Source, SourceError


class CrawlerSource(Source):
    key = "crawler"
    name = "크롤러(공개 자료 페이지)"
    kind = "crawler"
    group = "크롤러"
    homepage = ""
    terms_url = ""
    needs_env = ()
    key_help = ("API 키가 필요 없습니다. 설정 화면의 크롤러 사이트 목록에서 켜고 끕니다. "
                "robots.txt가 막은 사이트·주소는 자동으로 건너뜁니다.")
    doc_types = ("report", "web")

    def status(self) -> dict:
        sites = crawler.list_sites()
        on = [s for s in sites if s.get("enabled")]
        if not on:
            return {"ready": False, "missing_env": [],
                    "message": "켜진 크롤러 사이트가 없습니다. 설정 화면에서 사이트를 켜거나 추가하세요."}
        return {"ready": True, "missing_env": [],
                "message": f"켜진 사이트 {len(on)}곳 / 전체 {len(sites)}곳"}

    def search(self, query: str, *, limit: int = 25, since_year: int | None = None) -> list[Item]:
        items, reports = crawler.search_all(query, limit=limit, since_year=since_year)
        if not reports:
            raise SourceError("켜진 크롤러 사이트가 없습니다. 설정 화면에서 사이트를 켜거나 추가하세요.")
        if not items and reports and all(r["pages"] == 0 for r in reports):
            msgs = "; ".join(m for r in reports for m in r["messages"][:2])
            raise SourceError(f"크롤러가 한 페이지도 가져오지 못했습니다. {msgs}".strip())
        return items

    def last_reports(self) -> list[dict]:
        return crawler.last_reports()


SOURCE = CrawlerSource()
