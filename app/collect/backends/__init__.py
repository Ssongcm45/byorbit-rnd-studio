"""크롤러 가져오기 방식(backend) — 크롤링 규칙은 app/collect/crawler.py의 한 루프가 모두 지키고,
여기 방식들은 "페이지를 어떻게 받아 오느냐"만 맡는다.

| key | 방식 | 어디서 | 필요한 것 |
|---|---|---|---|
| `direct`  | 표준 라이브러리 HTTP(app/collect/http.py) — 기본 | 이 PC | 없음 |
| `browser` | Playwright 파이썬 라이브러리 + 헤드리스 Chrome — 자바스크립트로 그리는 목록 | 이 PC | install-browser.bat |
| `apify`   | Apify 클라우드(Website Content Crawler) — 유료, 선택 | Apify 서버 | 환경 변수 BYORBIT_APIFY_TOKEN |

계약
- 쪽 단위 방식(direct·browser): `open(site) -> Session`(with 문). `Session.fetch(url) -> Page`. 크롤 루프가 주소마다
  robots.txt·허용 경로·간격을 먼저 확인한 뒤 부른다. 실패는 FetchError(사용자에게 보여 줄 한국어).
- 일괄 방식(apify): `bulk = True`, `crawl(site, seeds, max_pages, max_depth) -> (list[Page], 참고 메시지[])`. 받은 페이지는 크롤 루프가
  다시 robots·허용 경로·쪽수 제한으로 거른 뒤에만 쓴다(Apify가 더 가져와도 버린다).
- `status() -> {"ready": bool, "message": str, ...}` — 화면의 준비 표시(미설치·키 없음).

왜 Playwright MCP가 아닌가: MCP는 AI가 브라우저를 직접 조종하는 통로다. 앱 안의 Claude에 브라우저 MCP를 붙이면
file:// 주소로 이 PC의 파일을 열 수 있어 기밀 자료 가림(masking)을 우회할 수 있다. 그래서 브라우저는 크롤러 코드만
정해진 규칙(http/https만, 사이트 허용 경로만)으로 쓰고, AI에게는 도구로 주지 않는다.
"""
from __future__ import annotations

import importlib
import urllib.parse
from dataclasses import dataclass, field

BACKENDS = ("direct", "browser", "apify")
LABELS = {"direct": "기본(이 PC, HTTP)", "browser": "브라우저(이 PC, 헤드리스 Chrome)",
          "apify": "Apify 클라우드(유료)"}


class FetchError(Exception):
    """페이지 하나를 받지 못함. 메시지는 사용자에게 그대로 보여 줄 한국어."""

    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


class BackendUnavailable(Exception):
    """방식을 쓸 준비가 안 됨(미설치·키 없음). 메시지에 할 일을 적는다."""


@dataclass
class Page:
    url: str                        # 요청한 주소(또는 Apify가 보고한 주소)
    final_url: str                  # 리디렉션 뒤 실제 주소
    status: int | None = 200
    html: str = ""                  # 받은(그려진) HTML. 없으면 text만
    text: str | None = None
    depth: int | None = None        # 일괄 방식이 알려 주는 깊이(시작 주소 = 0)
    note: str | None = None         # 대기 시간 초과 같은 참고 메시지
    links: list[str] = field(default_factory=list)


def is_web_url(url: str) -> bool:
    """http(s) 주소인가 — 브라우저·Apify 모두 이것만 연다(file:, data:, javascript:, chrome: 등은 거절)."""
    try:
        p = urllib.parse.urlsplit((url or "").strip())
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.hostname)


def get(key: str | None):
    """방식 모듈. 모르는 key는 ValueError."""
    key = key or "direct"
    if key not in BACKENDS:
        raise ValueError(f"가져오기 방식은 {', '.join(BACKENDS)} 중 하나입니다: {key!r}")
    return importlib.import_module(f"{__name__}.{key}")


def backend_status() -> dict:
    """{direct:{ready,...}, browser:{ready, how, message}, apify:{ready, message}} — 화면의 준비 표시."""
    out = {}
    for k in BACKENDS:
        try:
            st = dict(get(k).status())
        except Exception as e:  # noqa: BLE001 — 상태 확인이 깨져도 목록은 보여 준다
            st = {"ready": False, "message": f"상태를 확인하지 못했습니다: {e}"}
        st["label"] = LABELS[k]
        out[k] = st
    return out
