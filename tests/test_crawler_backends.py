"""크롤러 가져오기 방식(direct·browser·apify) 시험 — 네트워크·실제 브라우저 없이.

- 크롤 루프는 방식과 상관없이 같은 규칙(robots·허용 경로·같은 호스트·쪽수·깊이·검색어)을 지킨다.
- 브라우저: http/https가 아닌 이동·요청을 거절한다(file:/// 포함). Playwright가 설치돼 있으면 로컬 http.server로 실제 시험.
- Apify: 요청 모양(주소·액터·입력·비용 상한·robots 존중), 토큰은 환경 변수·헤더로만, 오류에서 가림, 결과 해석, 시간 초과 중단.
"""
from __future__ import annotations

import importlib.util
import io
import json
import threading
import urllib.error
import urllib.parse

import pytest

from app.collect import backends, crawler, http
from app.collect.backends import FetchError, Page
from app.collect.backends import apify as apify_be
from app.collect.backends import browser as browser_be
from tests.test_collect_kr import DETAIL_HTML, LIST_HTML, FakeResp, _site, web  # noqa: F401 — web는 fixture

TOKEN = "apify_api_SECRETtoken1234567890"


# ================================================================ 가짜 방식

class FakePaged:
    """쪽 단위 가짜 방식: 주소 → HTML. 받은 주소를 기록한다."""
    key = "fakepaged"
    bulk = False

    def __init__(self, pages: dict, redirects: dict | None = None):
        self.pages, self.redirects, self.calls = pages, redirects or {}, []
        self.opened = 0

    def status(self):
        return {"ready": True, "message": "가짜"}

    def open(self, site):
        fake = self
        self.opened += 1

        class S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def fetch(self, url):
                fake.calls.append(url)
                if url not in fake.pages:
                    raise FetchError(f"HTTP 404: {url}", 404)
                return Page(url=url, final_url=fake.redirects.get(url, url), html=fake.pages[url])
        return S()


class FakeBulk:
    key = "fakebulk"
    bulk = True

    def __init__(self, pages: list[Page]):
        self.pages, self.args = pages, None

    def status(self):
        return {"ready": True, "message": "가짜"}

    def crawl(self, site, seeds, max_pages, max_depth):
        self.args = (list(seeds), max_pages, max_depth)
        return list(self.pages), ["가짜 일괄 실행"]


def _use(monkeypatch, name: str, mod) -> None:
    real = backends.get
    monkeypatch.setattr(backends, "get", lambda k: mod if k == name else real(k))
    monkeypatch.setattr(backends, "BACKENDS", backends.BACKENDS + (name,))


# ================================================================ 크롤 루프는 방식과 무관

def test_paged_backend_same_rules_as_direct(web, monkeypatch):
    web.pages["https://ok.kr/robots.txt"] = "User-agent: *\nDisallow: /files/secret.pdf\nDisallow: /view/3\n"
    pages = {"https://ok.kr/list": LIST_HTML, "https://ok.kr/view/1": DETAIL_HTML,
             "https://ok.kr/view/3": "<html></html>", "https://ok.kr/view/77": "<html><body>상세</body></html>"}
    web.pages.update(pages)
    site = _site("ok.kr", title_hint=".tit", link_template="https://ok.kr/view/{1}")
    d_items, d_rep = crawler.crawl_site(site, "사과박")

    fake = FakePaged(dict(pages))
    _use(monkeypatch, "fakepaged", fake)
    f_items, f_rep = crawler.crawl_site({**site, "backend": "fakepaged"}, "사과박")

    assert {i.title for i in f_items} == {i.title for i in d_items}
    assert {i.url for i in f_items} == {i.url for i in d_items}
    assert f_rep.pages == d_rep.pages and fake.opened == 1
    assert "https://ok.kr/view/3" not in fake.calls                  # robots가 막은 상세는 받지 않음
    assert not any("other/4" in c or "elsewhere" in c for c in fake.calls)   # 허용 경로 밖·다른 호스트는 따라가지 않음
    it = next(i for i in f_items if i.title == "사과박 건조 공정 연구")
    assert it.abstract == "사과박을 열풍 건조한 결과 요약." and it.license == "공공누리 제1유형"
    assert "https://ok.kr/files/secret.pdf" not in {a["url"] for a in it.extra["attachments"]}
    assert http.MIN_INTERVAL["ok.kr"] >= 3.0                          # 간격도 방식과 무관하게 정한다
    assert f_rep.to_dict()["backend"] == "fakepaged"


def test_paged_backend_robots_block_and_redirect_offsite(web, monkeypatch):
    web.pages["https://deny.kr/robots.txt"] = "User-agent: *\nDisallow: /\n"
    fake = FakePaged({"https://deny.kr/list": LIST_HTML})
    _use(monkeypatch, "fakepaged", fake)
    items, rep = crawler.crawl_site({**_site("deny.kr"), "backend": "fakepaged"}, "사과박")
    assert items == [] and rep.pages == 0 and rep.robots_ok is False and fake.calls == []

    web.pages["https://rd.kr/robots.txt"] = "User-agent: *\nAllow: /\n"
    fake2 = FakePaged({"https://rd.kr/list": LIST_HTML}, redirects={"https://rd.kr/list": "https://evil.example/list"})
    _use(monkeypatch, "fakepaged", fake2)
    items, rep = crawler.crawl_site({**_site("rd.kr"), "backend": "fakepaged"}, "사과박")
    assert items == [] and rep.pages == 0 and any("다른 사이트" in m for m in rep.messages)


def test_paged_backend_max_pages(web, monkeypatch):
    rows = "".join(f'<li><a href="/view/{i}">사과박 시험 {i}</a></li>' for i in range(40))
    web.pages["https://big.kr/robots.txt"] = "User-agent: *\nAllow: /\n"
    pages = {"https://big.kr/list": f"<ul>{rows}</ul>"}
    pages.update({f"https://big.kr/view/{i}": "<html><body>상세</body></html>" for i in range(40)})
    fake = FakePaged(pages)
    _use(monkeypatch, "fakepaged", fake)
    items, rep = crawler.crawl_site({**_site("big.kr", max_pages=4), "backend": "fakepaged"}, "사과박", limit=100)
    assert rep.pages == 4 and len(fake.calls) == 4 and len(items) == 40


def test_bulk_backend_filtered_like_direct(web, monkeypatch):
    web.pages["https://bk.kr/robots.txt"] = "User-agent: *\nDisallow: /view/3\n"
    pages = [
        Page(url="https://bk.kr/view/1", final_url="https://bk.kr/view/1", html=DETAIL_HTML, depth=1),   # 목록보다 먼저 와도 됨
        Page(url="https://bk.kr/list", final_url="https://bk.kr/list", html=LIST_HTML, depth=0),
        Page(url="https://bk.kr/view/3", final_url="https://bk.kr/view/3", html="<html></html>", depth=1),  # robots 막힘
        Page(url="https://bk.kr/other/4", final_url="https://bk.kr/other/4", html="<html></html>", depth=1),  # 허용 경로 밖
        Page(url="https://elsewhere.example/view/5", final_url="https://elsewhere.example/view/5", html="", depth=1),
        Page(url="https://bk.kr/view/2", final_url="https://bk.kr/view/2", html="<html></html>", depth=2),  # 너무 깊음
        Page(url="file:///C:/secret.txt", final_url="file:///C:/secret.txt", html="기밀", depth=1),
        Page(url="https://bk.kr/view/9", final_url="https://bk.kr/view/9", html="<html></html>", status=404, depth=1),
    ]
    fake = FakeBulk(pages)
    _use(monkeypatch, "fakebulk", fake)
    site = {**_site("bk.kr", title_hint=".tit", search_urls=["https://bk.kr/s?q={q}"]), "backend": "fakebulk"}
    items, rep = crawler.crawl_site(site, "사과박")
    titles = {i.title for i in items}
    assert "사과박 건조 공정 연구" in titles and "커피박 추출 효율" not in titles      # 검색어는 이 PC에서 거름
    it = next(i for i in items if i.title == "사과박 건조 공정 연구")
    assert it.abstract == "사과박을 열풍 건조한 결과 요약." and it.extra["detail_fetched"] is True
    assert rep.pages == 2                                                       # 목록 + 상세 1
    for bad in ("https://bk.kr/other/4", "https://elsewhere.example/view/5", "https://bk.kr/view/2",
                "file:///C:/secret.txt", "https://bk.kr/view/3"):
        assert bad in rep.skipped, bad
    assert fake.args[0] == ["https://bk.kr/list"]                               # 일괄 방식에는 검색어(search_urls)를 보내지 않는다
    assert any("가짜 일괄 실행" in m for m in rep.messages)


def test_bulk_backend_page_budget(web, monkeypatch):
    web.pages["https://bb.kr/robots.txt"] = "User-agent: *\nAllow: /\n"
    rows = "".join(f'<li><a href="/view/{i}">사과박 {i}</a></li>' for i in range(10))
    pages = [Page(url="https://bb.kr/list", final_url="https://bb.kr/list", html=f"<ul>{rows}</ul>", depth=0)]
    pages += [Page(url=f"https://bb.kr/view/{i}", final_url=f"https://bb.kr/view/{i}", html="<p>x</p>", depth=1)
              for i in range(10)]
    fake = FakeBulk(pages)
    _use(monkeypatch, "fakebulk", fake)
    items, rep = crawler.crawl_site({**_site("bb.kr", max_pages=3), "backend": "fakebulk"}, "사과박", limit=50)
    assert rep.pages == 3 and fake.args[1] == 3 and fake.args[2] == 1
    assert any("쪽수 제한" in m and "8쪽" in m for m in rep.messages)
    assert len(items) == 10


# ================================================================ 사이트 필드·예전 파일 호환

def test_backend_field_validation_and_backward_compat(web):
    from app import config
    f = config.path("config", "crawl_sites.json")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"version": 1, "overrides": {}, "sites": [
        {"id": "old-site", "name": "예전 사이트", "start_urls": ["https://old.kr/list"], "link_pattern": "v",
         "interval_s": 3, "enabled": True}]}, ensure_ascii=False), encoding="utf-8")
    sites = {s["id"]: s for s in crawler.list_sites()}
    assert sites["old-site"]["backend"] == "direct"
    assert all(s["backend"] == "direct" for s in sites.values() if s["default"])

    base = {"name": "x", "start_urls": ["https://x.kr/"], "link_pattern": "a"}
    assert crawler.validate_site(base)["backend"] == "direct"
    with pytest.raises(ValueError):
        crawler.validate_site({**base, "backend": "selenium"})
    with pytest.raises(ValueError):
        crawler.validate_site({**base, "backend": "browser", "wait_for": "xpath=//a"})   # CSS만
    with pytest.raises(ValueError):
        crawler.validate_site({**base, "backend": "browser", "wait_for": "a\nb"})
    b = crawler.validate_site({**base, "backend": "browser", "wait_for": " table tbody tr ", "wait_ms": 99999})
    assert b["wait_for"] == "table tbody tr" and b["wait_ms"] == 15000
    a = crawler.validate_site({**base, "backend": "apify", "actor": "apify/website-content-crawler"})
    assert a["actor"] == "apify~website-content-crawler" and a["max_charge_usd"] == 0.5
    assert crawler.validate_site({**base, "backend": "apify", "max_charge_usd": 50})["max_charge_usd"] == 5.0
    assert crawler.validate_site({**base, "backend": "apify", "max_charge_usd": 0})["max_charge_usd"] == 0.05
    with pytest.raises(ValueError):
        crawler.validate_site({**base, "backend": "apify", "actor": "../../etc"})
    saved = crawler.save_site({**base, "backend": "browser", "wait_for": "#list li"})
    assert crawler.get_site(saved["id"])["backend"] == "browser"
    # 기본 사이트에 방식을 바꿔 저장하면 덮어쓰기로 남는다
    d0 = crawler.load_defaults()[0]["id"]
    crawler.save_site({**crawler.get_site(d0), "backend": "browser"})
    assert crawler.get_site(d0)["backend"] == "browser"
    assert json.loads(f.read_text(encoding="utf-8"))["overrides"][d0]["backend"] == "browser"


def test_backend_status_and_unavailable_backend(web, monkeypatch):
    monkeypatch.delenv(apify_be.TOKEN_ENV, raising=False)
    monkeypatch.setattr(browser_be.importlib.util, "find_spec", lambda name: None)
    st = crawler.backend_status()
    assert st["direct"]["ready"] is True
    assert st["browser"]["ready"] is False and "install-browser.bat" in st["browser"]["message"]
    assert "브라우저 엔진 미설치" in st["browser"]["message"]
    assert st["apify"]["ready"] is False and apify_be.TOKEN_ENV in st["apify"]["message"]
    assert "console.apify.com" in st["apify"]["message"]
    web.pages["https://nb.kr/robots.txt"] = "User-agent: *\nAllow: /\n"
    for b in ("browser", "apify"):
        items, rep = crawler.crawl_site({**_site("nb.kr"), "backend": b}, "사과박")
        assert items == [] and rep.backend_ready is False and rep.pages == 0
        assert "https://nb.kr/list" not in web.calls
    s = crawler.save_site({"name": "점검", "start_urls": ["https://nb.kr/list"], "link_pattern": "v",
                           "backend": "browser"})
    r = crawler.check_site(s["id"])
    assert r["backend"] == "browser" and r["backend_ready"] is False and "install-browser.bat" in r["message"]


def test_test_crawl_small(web, monkeypatch):
    rows = "".join(f'<li><a href="/view/{i}">사과박 시험 {i}</a> 2025-01-0{i % 9 + 1}</li>' for i in range(8))
    web.pages["https://tc.kr/robots.txt"] = "User-agent: *\nAllow: /\n"
    web.pages["https://tc.kr/list"] = f"<ul>{rows}</ul>"
    web.fallback = lambda url: "<p>상세</p>" if "tc.kr/view/" in url else None
    s = crawler.save_site({"name": "시험 수집", "start_urls": ["https://tc.kr/list"], "allow_prefixes": ["/view/"],
                           "link_pattern": r"/view/\d+$", "max_pages": 20})
    r = crawler.test_crawl(s["id"], "", max_pages=99)
    assert r["max_pages"] == 3 and r["pages"] <= 3 and len(r["items"]) == 8
    assert r["items"][0]["title"].startswith("사과박 시험") and r["items"][0]["date"]
    assert not any("collect_item" in k for k in r)          # 저장하지 않는다(결과만 돌려줌)


# ================================================================ 브라우저 안전장치(브라우저 없이)

@pytest.mark.parametrize("url", ["file:///C:/Users/me/secret.pdf", "file://localhost/etc/passwd", "data:text/html,<b>x</b>",
                                 "javascript:alert(1)", "chrome://settings", "about:blank", "blob:https://a.kr/1",
                                 "C:\\Users\\me\\a.html", "ftp://a.kr/x", "", "http:///nohost"])
def test_browser_refuses_non_web_navigation(url):
    with pytest.raises(FetchError):
        browser_be.check_navigation(url)
    assert browser_be.should_block(url, "document") is not None
    assert browser_be.should_block(url, "script") is not None
    s = browser_be.Session({"id": "x"})          # 띄우기 전이라도 fetch는 먼저 주소를 거절한다
    with pytest.raises(FetchError):
        s.fetch(url)


def test_browser_request_guard():
    assert browser_be.check_navigation("https://www.rda.go.kr/board/board.do?mode=list")
    assert browser_be.should_block("https://a.kr/app.js", "script") is None
    assert browser_be.should_block("https://a.kr/list.do", "document") is None
    assert browser_be.should_block("https://a.kr/api/list", "xhr") is None
    for t in ("image", "font", "media"):
        assert browser_be.should_block("https://a.kr/x", t)

    class Req:
        def __init__(self, url, rt):
            self.url, self.resource_type = url, rt

    class Route:
        def __init__(self, url, rt):
            self.request, self.done = Req(url, rt), None

        def abort(self):
            self.done = "abort"

        def continue_(self):
            self.done = "continue"
    cases = [("file:///C:/x.txt", "fetch", "abort"), ("https://a.kr/a.png", "image", "abort"),
             ("https://a.kr/app.js", "script", "continue"), ("data:image/png;base64,AA", "image", "abort"),
             ("chrome-extension://abc/x.js", "script", "abort")]
    for url, rt, want in cases:
        r = Route(url, rt)
        browser_be._route_handler(r)
        assert r.done == want, url


def test_browser_status_how(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_be.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(browser_be, "find_chrome", lambda: r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    assert browser_be.status() == {**browser_be.status(), "ready": True, "how": "chrome"}
    monkeypatch.setattr(browser_be, "find_chrome", lambda: None)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "none"))
    assert browser_be.status()["ready"] is False and "150MB" in browser_be.status()["message"]
    (tmp_path / "chromium-1234").mkdir()
    assert browser_be.status()["how"] == "chromium"


HAS_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None


@pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="Playwright 미설치(install-browser.bat) — 실제 브라우저 시험은 건너뜀")
def test_browser_real_local_server(web, monkeypatch, tmp_path):
    """로컬 http.server: 자바스크립트로 그린 목록을 읽고, file:// 요청·이동은 막는다(다른 스레드에서 실행)."""
    if not browser_be.status()["ready"]:
        pytest.skip("Chrome/chromium 없음")
    import http.server as hs
    secret = tmp_path / "secret.txt"
    secret.write_text("기밀", encoding="utf-8")
    file_url = secret.as_uri()
    hits: list[str] = []
    page = f"""<html><body><ul id="list"></ul>
<img src="/logo.png"><img src="{file_url}">
<script>
fetch("{file_url}").then(r => r.text()).then(t => {{ document.title = 'LEAK ' + t }}).catch(() => {{}});
setTimeout(() => {{
  const ul = document.getElementById('list');
  for (const i of [1, 2]) {{ const li = document.createElement('li');
    li.innerHTML = '<a href="/view/' + i + '">사과박 자바스크립트 목록 ' + i + '</a>'; ul.appendChild(li); }}
}}, 300);
</script></body></html>"""

    class H(hs.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            body = page.encode() if self.path == "/list" else (b"<html><body>detail</body></html>"
                                                                if self.path.startswith("/view/") else b"")
            self.send_response(200 if body else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = hs.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host = f"127.0.0.1:{srv.server_address[1]}"
    http.set_opener(None)                                  # robots.txt는 진짜 로컬 서버에서(404 → 허용)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    try:
        site = crawler.validate_site({"name": "로컬", "start_urls": [f"http://{host}/list"], "allow_prefixes": ["/view/"],
                                      "link_pattern": r"/view/\d+$", "backend": "browser", "wait_for": "#list li",
                                      "max_pages": 3}) | {"id": "local", "default": False}
        out = {}
        th = threading.Thread(target=lambda: out.update(r=crawler.crawl_site(site, "사과박", max_pages=3)))
        th.start()
        th.join(120)
        items, rep = out["r"]
        assert sorted(i.title for i in items) == ["사과박 자바스크립트 목록 1", "사과박 자바스크립트 목록 2"]
        assert "/logo.png" not in hits                     # 이미지 요청은 끊는다
        with browser_be.open(site) as s:
            pg = s.fetch(f"http://{host}/list")
            assert "LEAK 기밀" not in pg.html and "<title>LEAK" not in pg.html   # file:// fetch는 끊겼다
            with pytest.raises(FetchError):
                s.fetch(file_url)
    finally:
        srv.shutdown()


# ================================================================ Apify (가짜 응답)

class FakeApify:
    """api.apify.com 흉내: 실행 시작 → 상태 → 데이터셋. 요청(주소·헤더·본문)을 기록한다."""

    def __init__(self, items=None, final_status="SUCCEEDED", stay_running=False, start_code=201, status_message=""):
        self.items = items if items is not None else []
        self.final_status, self.stay_running, self.start_code = final_status, stay_running, start_code
        self.status_message = status_message
        self.reqs: list[dict] = []

    def __call__(self, req, timeout):
        url = req.full_url
        body = req.data.decode("utf-8") if req.data else None
        self.reqs.append({"url": url, "method": req.get_method(), "headers": dict(req.header_items()), "body": body,
                          "timeout": timeout})
        p = urllib.parse.urlsplit(url)
        if p.hostname != "api.apify.com":
            return FakeResp(b"User-agent: *\nAllow: /\n")       # robots.txt 등
        if p.path.endswith("/runs") and req.get_method() == "POST":
            if self.start_code >= 400:
                raise urllib.error.HTTPError(url, self.start_code, "err", None, io.BytesIO(b"{}"))
            return FakeResp(json.dumps({"data": {"id": "RUN1", "status": "READY", "defaultDatasetId": "DS1"}}).encode())
        if p.path == "/v2/actor-runs/RUN1/abort":
            return FakeResp(json.dumps({"data": {"id": "RUN1", "status": "ABORTING"}}).encode())
        if p.path == "/v2/actor-runs/RUN1":
            st = "RUNNING" if self.stay_running else self.final_status
            return FakeResp(json.dumps({"data": {"id": "RUN1", "status": st, "defaultDatasetId": "DS1",
                                                 "usageTotalUsd": 0.0123,
                                                 "statusMessage": self.status_message}}).encode())
        if p.path == "/v2/datasets/DS1/items":
            return FakeResp(json.dumps(self.items).encode())
        raise urllib.error.HTTPError(url, 404, "nf", None, io.BytesIO(b"{}"))


def _apify_site(**kw):
    s = {"id": "ap", "name": "Apify 시험", "start_urls": ["https://ap.kr/list"], "allow_prefixes": ["/view/", "/list"],
         "search_urls": ["https://ap.kr/search?q={q}"], "link_pattern": r"/view/\d+$", "backend": "apify",
         "max_pages": 7, "max_depth": 1}
    s.update(kw)
    return crawler.validate_site(s) | {"id": "ap", "default": False}


@pytest.fixture()
def apify_env(web, monkeypatch):
    monkeypatch.setenv(apify_be.TOKEN_ENV, TOKEN)
    return web


def test_apify_request_construction(apify_env, monkeypatch):
    fa = FakeApify(items=[
        {"url": "https://ap.kr/list", "crawl": {"loadedUrl": "https://ap.kr/list", "depth": 0, "httpStatusCode": 200},
         "html": LIST_HTML.replace("ok.kr", "ap.kr"), "metadata": {"title": "목록"}},
        {"url": "https://ap.kr/view/1", "crawl": {"loadedUrl": "https://ap.kr/view/1", "depth": 1}, "html": DETAIL_HTML},
        {"url": "https://ap.kr/view/3", "crawl": {"depth": 1}, "text": "글만 있는 페이지", "metadata": {"title": "t"}},
        {"url": "file:///C:/x", "html": "기밀"},
        "이상한 항목",
    ])
    http.set_opener(fa)
    site = _apify_site(title_hint=".tit", max_charge_usd=0.3, wait_for="#list li")
    items, rep = crawler.crawl_site(site, "사과박 건조")
    start = next(r for r in fa.reqs if r["url"].startswith("https://api.apify.com/v2/actors/"))
    p = urllib.parse.urlsplit(start["url"])
    q = dict(urllib.parse.parse_qsl(p.query))
    assert start["method"] == "POST" and p.path == "/v2/actors/apify~website-content-crawler/runs"
    assert q["maxTotalChargeUsd"] == "0.3" and q["timeout"] == str(apify_be.RUN_TIMEOUT_S) and q["memory"] == "4096"
    hdr = {k.lower(): v for k, v in start["headers"].items()}
    assert hdr["authorization"] == f"Bearer {TOKEN}"
    assert all(TOKEN not in r["url"] for r in fa.reqs)                   # 토큰은 주소에 넣지 않는다
    inp = json.loads(start["body"])
    assert inp["respectRobotsTxtFile"] is True
    assert inp["startUrls"] == [{"url": "https://ap.kr/list"}]           # search_urls(검색어)는 보내지 않는다
    assert "사과박" not in start["body"] and "건조" not in start["body"]
    assert inp["maxCrawlPages"] == 7 and inp["maxResults"] == 7 and inp["maxCrawlDepth"] == 1
    assert {"glob": "https://ap.kr/view/**"} in inp["includeUrlGlobs"]
    assert {"glob": "https://ap.kr/list**"} in inp["includeUrlGlobs"]
    assert inp["crawlerType"] == "playwright:adaptive" and inp["saveHtml"] is True and inp["htmlTransformer"] == "none"
    assert inp["maxConcurrency"] == 1 and inp["softWaitForSelector"] == "#list li"
    assert items and items[0].title == "사과박 건조 공정 연구" and items[0].abstract.startswith("사과박을 열풍")
    assert any("비용" in m and "0.012" in m for m in rep.messages)
    assert rep.backend == "apify" and rep.pages == 3                    # 목록 + 상세 2(글만 있는 페이지 포함)
    runs_get = [r for r in fa.reqs if "/actor-runs/RUN1" in r["url"]]
    assert runs_get and "waitForFinish=60" in runs_get[0]["url"]
    ds = next(r for r in fa.reqs if "/datasets/DS1/items" in r["url"])
    assert "clean=true" in ds["url"] and "format=json" in ds["url"]


def test_apify_globs_escape_and_actor_override():
    site = {"start_urls": ["https://a.kr/board/board.do?mode=list"], "allow_prefixes": ["/board/board.do", "/x[1]/"]}
    g = [x["glob"] for x in apify_be.include_globs(site)]
    assert g == ["https://a.kr/board/board.do**", "https://a.kr/x\\[1\\]/**"]
    assert apify_be.include_globs({"start_urls": ["https://a.kr/l"], "allow_prefixes": []}) == [{"glob": "https://a.kr/**"}]
    assert apify_be.norm_actor("someone/cheerio-scraper") == "someone~cheerio-scraper"
    assert apify_be.norm_actor(None) == apify_be.DEFAULT_ACTOR
    assert apify_be.run_params({})["maxTotalChargeUsd"] == apify_be.DEFAULT_MAX_CHARGE_USD


def test_apify_token_only_from_env_and_redacted(apify_env, monkeypatch):
    # 토큰은 사이트 설정에 넣어도 쓰지 않는다(저장 필드가 아님)
    s = crawler.validate_site({"name": "x", "start_urls": ["https://ap.kr/list"], "link_pattern": "v", "backend": "apify",
                               "token": "from-file-should-be-dropped", "apify_token": "nope"})
    assert "token" not in s and "apify_token" not in s
    monkeypatch.delenv(apify_be.TOKEN_ENV)
    with pytest.raises(backends.BackendUnavailable):
        apify_be.token()
    monkeypatch.setenv(apify_be.TOKEN_ENV, TOKEN)
    # 실패 메시지에 토큰이 섞여 와도 가린다
    fa = FakeApify(final_status="FAILED", status_message=f"Invalid input; token {TOKEN} rejected")
    http.set_opener(fa)
    items, rep = crawler.crawl_site(_apify_site(), "사과박")
    assert items == [] and any("실패" in m for m in rep.messages)
    assert all(TOKEN not in m for m in rep.messages) and any("***" in m for m in rep.messages)
    # 401·402 → 할 일을 적은 한국어, 토큰 없음
    for code, word in ((401, "토큰"), (402, "크레딧")):
        http.set_opener(FakeApify(start_code=code))
        with pytest.raises(FetchError) as ei:
            apify_be.crawl(_apify_site(), ["https://ap.kr/list"], 3, 1)
        assert word in str(ei.value) and TOKEN not in str(ei.value) and ei.value.status == code


def test_apify_timeout_aborts_run(apify_env):
    fa = FakeApify(stay_running=True)
    http.set_opener(fa)
    with pytest.raises(FetchError) as ei:
        apify_be.crawl(_apify_site(), ["https://ap.kr/list"], 3, 1, deadline_s=0)
    assert "중단" in str(ei.value)
    assert any(r["url"].endswith("/actor-runs/RUN1/abort") and r["method"] == "POST" for r in fa.reqs)
    # 크롤 루프에서는 메시지로 남고 예외가 새지 않는다
    fa2 = FakeApify(final_status="TIMED-OUT", items=[
        {"url": "https://ap.kr/list", "crawl": {"depth": 0}, "html": '<a href="/view/1">사과박 하나</a>'}])
    http.set_opener(fa2)
    items, rep = crawler.crawl_site(_apify_site(), "사과박")
    assert [i.title for i in items] == ["사과박 하나"] and any("TIMED-OUT" in m for m in rep.messages)


def test_apify_items_parsing():
    pg = apify_be._page_from_item({"url": "https://a.kr/x", "crawl": {"loadedUrl": "https://a.kr/y", "depth": "2",
                                                                       "httpStatusCode": 200}, "html": "<p>h</p>"}, TOKEN)
    assert (pg.url, pg.final_url, pg.depth, pg.status, pg.html) == ("https://a.kr/x", "https://a.kr/y", 2, 200, "<p>h</p>")
    pg = apify_be._page_from_item({"url": "https://a.kr/x", "markdown": "# 제목 <b>", "metadata": {"title": "T<"}}, TOKEN)
    assert "&lt;b&gt;" in pg.html and "<title>T&lt;</title>" in pg.html
    assert apify_be._page_from_item({"url": "javascript:x()"}, TOKEN) is None
    assert apify_be._page_from_item({"url": "https://a.kr/x", "crawl": {"loadedUrl": "file:///etc"}}, TOKEN) is None


# ================================================================ API

@pytest.fixture()
def api(web):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import routes_collect
    a = FastAPI()
    a.include_router(routes_collect.router)
    return TestClient(a)


def test_api_backends_and_test_endpoint(api, web, monkeypatch):
    monkeypatch.delenv(apify_be.TOKEN_ENV, raising=False)
    r = api.get("/api/collect/sites/backends")
    assert r.status_code == 200
    b = r.json()["backends"]
    assert set(b) == {"direct", "browser", "apify"} and b["direct"]["ready"] is True and b["apify"]["ready"] is False
    web.pages["https://ep.kr/robots.txt"] = "User-agent: *\nAllow: /\n"
    web.pages["https://ep.kr/list"] = '<ul><li><a href="/view/1">부산물 소재 1</a></li></ul>'
    web.fallback = lambda url: "<p>d</p>" if "ep.kr/view/" in url else None
    s = api.post("/api/collect/sites", json={"name": "엔드포인트", "start_urls": ["https://ep.kr/list"],
                                             "allow_prefixes": ["/view/"], "link_pattern": r"/view/\d+$"}).json()
    assert s["backend"] == "direct"
    t = api.post(f"/api/collect/sites/{s['id']}/test", json={"query": "부산물"})
    assert t.status_code == 200 and t.json()["items"][0]["title"] == "부산물 소재 1" and t.json()["pages"] <= 3
    assert api.post(f"/api/collect/sites/{s['id']}/test", json={"max_pages": 9}).status_code == 422
    assert api.post("/api/collect/sites/없는/test").status_code == 404
    bad = api.post("/api/collect/sites", json={"name": "x", "start_urls": ["https://ep.kr/"], "link_pattern": "a",
                                               "backend": "selenium"})
    assert bad.status_code == 400
    c = api.post(f"/api/collect/sites/{s['id']}/check").json()
    assert c["backend"] == "direct" and c["backend_ready"] is True
