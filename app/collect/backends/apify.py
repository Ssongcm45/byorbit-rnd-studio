"""Apify 방식(선택·유료) — Apify 클라우드의 Website Content Crawler로 페이지를 받아 온다.

이 방식을 쓰면 **사이트 주소와 크롤 설정(허용 경로·쪽수·깊이)이 Apify(클라우드)로 나가고, Apify 크레딧이 든다.**
검색어는 보내지 않는다 — 시작 주소만 보내고, 검색어는 받은 페이지에서 이 PC가 거른다. 자료함·CoA·시료·실험 데이터는
어떤 경우에도 보내지 않는다.

공식 문서(2026-11-25 확인)
- API 개요·인증: https://docs.apify.com/api/v2 — 기본 주소 https://api.apify.com/v2,
  토큰은 `Authorization: Bearer <token>` 헤더(권장, 주소에 넣는 ?token= 은 "less secure").
- 실행 시작: POST /v2/actors/{actorId}/runs — https://docs.apify.com/api/v2/act-runs-post
  쿼리 timeout(초)·memory(MB, 2의 거듭제곱)·maxTotalChargeUsd(실행 전체 비용 상한, USD)·waitForFinish(≤60초).
  actorId는 `사용자명~액터명`(예 apify~website-content-crawler) 또는 ID.
- 실행 상태: GET /v2/actor-runs/{runId}?waitForFinish=60 — https://docs.apify.com/api/v2/actor-run-get
  status: READY, RUNNING, SUCCEEDED, FAILED, TIMING-OUT, TIMED-OUT, ABORTING, ABORTED / usageTotalUsd(비용).
- 실행 중단: POST /v2/actor-runs/{runId}/abort (토큰 없이 부르면 401 — 2026-11-25 확인).
- 결과: GET /v2/datasets/{datasetId}/items?format=json&clean=true
- run-sync-get-dataset-items(POST /v2/actors/{id}/run-sync-get-dataset-items)는 300초를 넘으면 408을 주고 연결이
  끊기면 실행 상태를 알 수 없다고 문서가 경고한다 → 이 모듈은 "시작 + 상태 확인(polling) + 마감 시각에 abort"를 쓴다.
- Website Content Crawler 입력(빌드 version-0 0.3.108의 input schema, 2026-11-25 확인):
  https://apify.com/apify/website-content-crawler/input-schema
  startUrls[{url}], crawlerType(playwright:adaptive|playwright:firefox|cheerio|…), includeUrlGlobs/excludeUrlGlobs[{glob}],
  maxCrawlPages, maxCrawlDepth(시작 주소 = 0), maxResults, respectRobotsTxtFile(**기본 false → 반드시 true로 보냄**,
  Crawl-delay는 지원 안 함), maxConcurrency, requestTimeoutSecs, dynamicContentWaitSecs, waitForSelector/softWaitForSelector,
  blockMedia, htmlTransformer(none = 기본 정리만), removeElementsCssSelector, saveHtml(데이터셋 html 칸), saveMarkdown,
  clickElementsCssSelector, proxyConfiguration.
  출력: url, crawl.loadedUrl, crawl.depth, crawl.httpStatusCode, metadata.title, text, markdown, html(saveHtml일 때).

토큰: 환경 변수 BYORBIT_APIFY_TOKEN에서만 읽는다(설정 파일·DB·로그에 쓰지 않음). 헤더로만 보내고, 오류 문구는
http.redact()로 가린다. 발급: https://console.apify.com/settings/integrations (Apify 가입 → Settings → API & Integrations).
**실제 토큰으로는 아직 확인하지 못했다(가짜 응답으로만 시험).**
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse

from .. import http
from . import BackendUnavailable, FetchError, Page, is_web_url

log = logging.getLogger(__name__)

key = "apify"
bulk = True
API = "https://api.apify.com/v2"
TOKEN_ENV = "BYORBIT_APIFY_TOKEN"
TOKEN_URL = "https://console.apify.com/settings/integrations"
DEFAULT_ACTOR = "apify~website-content-crawler"
DEFAULT_MAX_CHARGE_USD = 0.5
MIN_CHARGE_USD = 0.05
MAX_CHARGE_USD = 5.0
RUN_TIMEOUT_S = 300            # Apify 쪽 실행 시간 상한(넘으면 TIMED-OUT)
DEADLINE_S = 360               # 이 PC가 기다리는 상한(넘으면 abort)
MEMORY_MB = 4096
POLL_WAIT_S = 60               # waitForFinish 최대값
TERMINAL = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}
ACTOR_RX = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9_.\-]{0,62}[~/][A-Za-z0-9][A-Za-z0-9_.\-]{0,62}|[A-Za-z0-9]{17})$")
SKIP_FILES_GLOB = "**/*.{pdf,PDF,hwp,hwpx,zip,doc,docx,xls,xlsx,ppt,pptx}"

NO_TOKEN = (f"키 없음 — Apify API 토큰을 환경 변수 {TOKEN_ENV}에 넣으세요. 발급: Apify 가입 → Settings → "
            f"API & Integrations({TOKEN_URL}). 유료(크레딧 차감)이며 사이트 주소·설정이 Apify 클라우드로 나갑니다.")

_ERRORS = {
    401: "Apify 토큰이 맞지 않습니다. 환경 변수 BYORBIT_APIFY_TOKEN의 값을 Apify 콘솔에서 다시 확인하세요.",
    402: "Apify 크레딧(또는 결제 수단)이 부족합니다. Apify 콘솔의 Billing에서 확인하세요.",
    403: "이 토큰으로는 이 액터를 실행할 권한이 없습니다. 토큰 권한(Actor 실행)을 확인하세요.",
    404: "Apify 액터를 찾지 못했습니다. 사이트 설정의 액터 이름(예 apify~website-content-crawler)을 확인하세요.",
    408: "Apify 응답 시간이 초과했습니다. 잠시 뒤 다시 시도하세요.",
    429: "Apify 호출 한도에 걸렸습니다. 잠시 뒤 다시 시도하세요.",
}


def token() -> str:
    v = os.environ.get(TOKEN_ENV, "").strip()
    if not v:
        raise BackendUnavailable(NO_TOKEN)
    return v


def status() -> dict:
    if not os.environ.get(TOKEN_ENV, "").strip():
        return {"ready": False, "message": NO_TOKEN, "env": TOKEN_ENV, "token_url": TOKEN_URL}
    return {"ready": True, "env": TOKEN_ENV, "token_url": TOKEN_URL,
            "message": ("사용 가능(유료) — 사이트 주소·설정이 Apify 클라우드로 나가고 크레딧이 듭니다. "
                        f"실행마다 비용 상한(기본 {DEFAULT_MAX_CHARGE_USD} USD)을 겁니다.")}


def norm_actor(actor: str | None) -> str:
    a = (actor or "").strip() or DEFAULT_ACTOR
    if not ACTOR_RX.match(a):
        raise ValueError("Apify 액터는 '사용자명~액터명'(예 apify~website-content-crawler) 또는 17자 ID입니다.")
    return a.replace("/", "~")


def charge_cap(v) -> float:
    try:
        x = float(v) if v not in (None, "") else DEFAULT_MAX_CHARGE_USD
    except (TypeError, ValueError):
        raise ValueError("Apify 비용 상한(max_charge_usd)은 USD 숫자여야 합니다(예 0.5).") from None
    return round(min(MAX_CHARGE_USD, max(MIN_CHARGE_USD, x)), 2)


# ---------------------------------------------------------------- 입력 만들기

_GLOB_SPECIAL = re.compile(r"([*?\[\]{}()!+@\\])")


def _glob_escape(s: str) -> str:
    return _GLOB_SPECIAL.sub(r"\\\1", s)


def include_globs(site: dict) -> list[dict]:
    """allow_prefixes → includeUrlGlobs. 경로 접두어는 시작 주소의 호스트마다 하나씩."""
    hosts = []
    for u in site.get("start_urls", []):
        p = urllib.parse.urlsplit(u)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in hosts:
            hosts.append(origin)
    out: list[str] = []
    for pre in site.get("allow_prefixes") or []:
        if "://" in pre:
            out.append(_glob_escape(pre) + "**")
        else:
            out.extend(_glob_escape(o + pre) + "**" for o in hosts)
    if not out:                                   # 허용 경로가 없으면 같은 호스트 전체(크롤 루프가 다시 거른다)
        out = [_glob_escape(o) + "/**" for o in hosts]
    return [{"glob": g} for g in dict.fromkeys(out)]


def build_input(site: dict, seeds: list[str], max_pages: int, max_depth: int) -> dict:
    """Website Content Crawler 입력. 검색어는 넣지 않는다(시작 주소만)."""
    seeds = [u for u in seeds if is_web_url(u)]
    wait_s = 10
    try:
        if site.get("wait_ms"):
            wait_s = max(1, min(15, int(site["wait_ms"]) // 1000 or 1))
    except (TypeError, ValueError):
        pass
    inp = {
        "startUrls": [{"url": u} for u in seeds],
        "crawlerType": "playwright:adaptive",        # 자바스크립트가 있으면 브라우저, 없으면 HTTP(문서 권장값)
        "includeUrlGlobs": include_globs(site),
        "excludeUrlGlobs": [{"glob": SKIP_FILES_GLOB}],
        "maxCrawlPages": int(max_pages),
        "maxResults": int(max_pages),
        "maxCrawlDepth": int(max_depth),
        "respectRobotsTxtFile": True,
        "useSitemaps": False,
        "maxConcurrency": 1,                         # Crawl-delay를 지원하지 않으므로 한 번에 한 쪽씩
        "maxRequestRetries": 1,
        "requestTimeoutSecs": 60,
        "dynamicContentWaitSecs": wait_s,
        "blockMedia": True,
        "saveFiles": False,
        "saveScreenshots": False,
        "saveMarkdown": False,
        "saveHtml": True,                            # 링크·표를 이 PC에서 다시 읽기 위해 HTML이 필요
        "htmlTransformer": "none",
        "removeElementsCssSelector": "script, style, noscript, svg",
        "clickElementsCssSelector": "",
        "removeCookieWarnings": True,
        "proxyConfiguration": {"useApifyProxy": True},
    }
    if site.get("wait_for"):
        inp["softWaitForSelector"] = site["wait_for"]   # 없어도 실패시키지 않는다
    return inp


def run_params(site: dict) -> dict:
    return {"timeout": RUN_TIMEOUT_S, "memory": MEMORY_MB, "maxTotalChargeUsd": charge_cap(site.get("max_charge_usd"))}


# ---------------------------------------------------------------- HTTP

def _call(method: str, path: str, tok: str, params: dict | None = None, body: dict | None = None,
          timeout: float = 30):
    url = API + path
    headers = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    try:
        with http.request(url, params, headers, timeout, data=data, method=method) as r:
            raw = r.read(20_000_000)
    except http.HttpError as e:
        msg = _ERRORS.get(e.status or 0) or f"Apify 호출 실패: {e}"
        raise FetchError(http.redact(msg), e.status) from None
    except OSError as e:          # 소켓 시간 초과 등
        raise FetchError(http.redact(f"Apify 연결 실패: {e}")) from None
    try:
        return json.loads(raw.decode("utf-8", errors="replace") or "null")
    except json.JSONDecodeError:
        raise FetchError("Apify가 JSON이 아닌 응답을 돌려주었습니다. 잠시 뒤 다시 시도하세요.") from None


def _abort(run_id: str, tok: str) -> None:
    try:
        _call("POST", f"/actor-runs/{urllib.parse.quote(run_id)}/abort", tok, timeout=20)
    except FetchError as e:
        log.warning("Apify 실행 중단 실패: %s", e)


def _page_from_item(it: dict, tok: str) -> Page | None:
    if not isinstance(it, dict):
        return None
    crawl = it.get("crawl") or {}
    url = it.get("url") or crawl.get("loadedUrl")
    final = crawl.get("loadedUrl") or url
    if not (is_web_url(url or "") and is_web_url(final or "")):
        return None
    html = it.get("html") or ""
    hu = it.get("htmlUrl")
    if not html and hu and urllib.parse.urlsplit(hu).hostname == "api.apify.com":
        try:
            html = http.get_text(hu, headers={"Authorization": f"Bearer {tok}"}, max_bytes=4_000_000)
        except http.HttpError:
            html = ""
    text = it.get("text") or it.get("markdown")
    if not html and text:          # HTML이 없으면 글만(링크 없음) — 제목은 metadata.title
        title = ((it.get("metadata") or {}).get("title") or "")
        from html import escape
        html = f"<html><head><title>{escape(title)}</title></head><body><p>{escape(text)}</p></body></html>"
    try:
        depth = int(crawl["depth"]) if crawl.get("depth") is not None else None
    except (TypeError, ValueError):
        depth = None
    code = crawl.get("httpStatusCode")
    return Page(url=url, final_url=final, status=code if isinstance(code, int) else None, html=html,
                text=text, depth=depth)


def crawl(site: dict, seeds: list[str], max_pages: int, max_depth: int, *,
          deadline_s: float = DEADLINE_S) -> tuple[list[Page], list[str]]:
    """액터를 한 번 돌려 페이지를 받는다 → (페이지들, 참고 메시지). 마감 시각을 넘기면 실행을 중단(abort)한다."""
    tok = token()
    actor = norm_actor(site.get("actor"))
    seeds = [u for u in seeds if is_web_url(u)]
    if not seeds:
        raise FetchError("Apify로 보낼 시작 주소(http/https)가 없습니다.")
    params = run_params(site)
    notes = [f"Apify 실행: {actor}, 최대 {max_pages}쪽·깊이 {max_depth}, 비용 상한 {params['maxTotalChargeUsd']} USD"]
    started = _call("POST", f"/actors/{urllib.parse.quote(actor, safe='~')}/runs", tok, params=params,
                    body=build_input(site, seeds, max_pages, max_depth), timeout=60)
    run = (started or {}).get("data") or {}
    run_id = run.get("id")
    if not run_id:
        raise FetchError("Apify가 실행 번호를 돌려주지 않았습니다. 잠시 뒤 다시 시도하세요.")
    t_end = time.monotonic() + max(0.0, float(deadline_s))
    while run.get("status") not in TERMINAL:
        if time.monotonic() >= t_end:
            _abort(run_id, tok)
            raise FetchError(f"Apify 실행이 {int(deadline_s)}초 안에 끝나지 않아 중단했습니다(run {run_id}). "
                             "쪽수를 줄이거나 잠시 뒤 다시 시도하세요.")
        got = _call("GET", f"/actor-runs/{urllib.parse.quote(run_id)}", tok,
                    params={"waitForFinish": POLL_WAIT_S}, timeout=POLL_WAIT_S + 20)
        run = (got or {}).get("data") or run
    st = run.get("status")
    cost = run.get("usageTotalUsd")
    if cost is not None:
        notes.append(f"Apify 비용 약 {float(cost):.3f} USD")
    if st == "FAILED":
        raise FetchError(f"Apify 실행이 실패했습니다: {http.redact(str(run.get('statusMessage') or ''))[:200]}".rstrip(": "))
    if st in ("TIMED-OUT", "ABORTED"):
        notes.append(f"Apify 실행이 {st} 상태로 끝나 받은 만큼만 씁니다(비용 상한·시간 제한).")
    ds = run.get("defaultDatasetId")
    if not ds:
        return [], notes + ["Apify 결과 데이터셋이 없습니다."]
    items = _call("GET", f"/datasets/{urllib.parse.quote(ds)}/items", tok,
                  params={"format": "json", "clean": "true", "limit": int(max_pages) * 2}, timeout=60)
    if isinstance(items, dict):           # 일부 응답은 {data: {items: [...]}} 형태
        items = (items.get("data") or {}).get("items") or []
    pages = [p for p in (_page_from_item(it, tok) for it in (items or [])) if p is not None]
    return pages, notes
