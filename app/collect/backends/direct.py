"""기본 방식 — 표준 라이브러리 HTTP(app/collect/http.py)로 HTML을 받는다. 자바스크립트는 실행하지 않는다."""
from __future__ import annotations

from .. import http
from . import FetchError, Page

key = "direct"
bulk = False
MAX_BYTES = 4_000_000


def status() -> dict:
    return {"ready": True, "message": "사용 가능 — 설치·키 없이 이 PC에서 바로 읽습니다(자바스크립트로 그리는 목록은 못 읽음)."}


class Session:
    def __init__(self, site: dict):
        self.site = site

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch(self, url: str) -> Page:
        try:
            html = http.get_text(url, max_bytes=MAX_BYTES)
        except http.HttpError as e:
            raise FetchError(str(e), e.status) from None
        return Page(url=url, final_url=url, status=200, html=html)


def open(site: dict) -> Session:  # noqa: A001 — 방식 공통 이름
    return Session(site)
