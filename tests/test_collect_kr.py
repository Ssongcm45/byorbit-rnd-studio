"""M3 묶음 B 시험: 국내·키 필요 API(KCI·ScienceON·NTIS·KIPRIS·공공데이터포털) 응답 해석과 키 보호,
예의 바른 크롤러(robots.txt·간격·링크 거르기·검색어·쪽수 제한·사이트 목록). 네트워크는 쓰지 않는다."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse

import pytest

from app.collect import base, crawler, http


# ================================================================ 가짜 네트워크

class FakeResp(io.BytesIO):
    def __init__(self, body: bytes, charset: str = "utf-8"):
        super().__init__(body)
        self._charset = charset

        class H:
            def __init__(s, cs):
                s.cs = cs

            def get_content_charset(s):
                return s.cs

            def get(s, k, d=None):
                return d
        self.headers = H(charset)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeWeb:
    """URL → 본문(str|bytes) 또는 (상태코드, 본문). 요청 기록을 남긴다."""

    def __init__(self, pages: dict | None = None, fallback=None):
        self.pages = dict(pages or {})
        self.fallback = fallback
        self.calls: list[str] = []

    def __call__(self, req, timeout):
        url = req.full_url
        self.calls.append(url)
        val = self.pages.get(url)
        if val is None:
            # 쿼리 순서와 무관하게 찾기(path만 같은 항목)
            for k, v in self.pages.items():
                if callable(k) and k(url):
                    val = v
                    break
        if val is None and self.fallback:
            val = self.fallback(url)
        if val is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        if isinstance(val, tuple):
            code, body = val
            if code >= 400:
                raise urllib.error.HTTPError(url, code, "err", None, None)
            val = body
        if isinstance(val, str):
            val = val.encode("utf-8")
        return FakeResp(val)


@pytest.fixture()
def web(monkeypatch, tmp_path):
    monkeypatch.setenv("BYORBIT_HOME", str(tmp_path / "home"))
    sleeps: list[float] = []
    monkeypatch.setattr(http.time, "sleep", lambda s: sleeps.append(s))
    crawler.clear_robots_cache()
    saved_interval = dict(http.MIN_INTERVAL)
    http._last.clear()
    fw = FakeWeb()
    fw.sleeps = sleeps
    http.set_opener(fw)
    yield fw
    http.set_opener(None)
    http.MIN_INTERVAL.clear()
    http.MIN_INTERVAL.update(saved_interval)
    http._last.clear()
    crawler.clear_robots_cache()


def _site(host: str, **kw) -> dict:
    s = {"id": f"t-{host.split('.')[0]}", "name": f"시험 {host}", "group": "시험",
         "start_urls": [f"https://{host}/list"], "allow_prefixes": ["/view/"],
         "link_pattern": r"/view/\d+$", "interval_s": 3, "enabled": True, "default": False,
         "max_pages": 10, "max_depth": 1}
    s.update(kw)
    return crawler.validate_site(s) | {"id": s["id"], "default": s["default"]}


LIST_HTML = """<html><head><title>목록</title><meta name="description" content="사이트 공통 설명"></head><body>
<ul class="list">
  <li><a href="/view/1"><span class="tit">사과박 건조 공정 연구</span></a> <span class="date">2025.03.04</span>
      <a href="/files/a1.pdf">보고서.pdf</a> <a href="/files/a1.hwp">보고서.hwp</a></li>
  <li><a href="/view/2"><span class="tit">커피박 추출 효율</span></a> <span class="date">2024-11-02</span></li>
  <li><a href="/view/3"><span class="tit">감귤 부산물 <mark>사과</mark> 박 비교</span></a> <span>2023-01-09</span></li>
  <li><a href="/other/4">허용 경로 밖 사과박</a></li>
  <li><a href="https://elsewhere.example/view/5">다른 호스트 사과박</a></li>
  <li><a href="javascript:goView('77');">자바스크립트 사과박 보고서</a></li>
  <li><a href="#top">맨 위로</a></li>
</ul></body></html>"""

DETAIL_HTML = """<html><head><meta property="og:description" content="사과박을 열풍 건조한 결과 요약.">
<title>사과박 건조 공정 연구 | 시험</title></head><body>
<a href="http://www.kogl.or.kr/info/licenseType1.do"><img alt="공공누리 제1유형"></a>
<a href="/files/d1.pdf">원문 PDF</a> <a href="/files/secret.pdf">막힌 PDF</a></body></html>"""


# ================================================================ robots.txt

def test_robots_longest_match_and_agent_groups():
    rb = crawler.Robots("User-agent: *\nAllow: /\nDisallow: /js/\nDisallow: /search\n")
    assert rb.can_fetch("https://a.kr/board/list")
    assert not rb.can_fetch("https://a.kr/js/app.js")          # Allow: / 가 먼저 있어도 더 긴 Disallow가 이김
    assert not rb.can_fetch("https://a.kr/search?q=1")
    rb2 = crawler.Robots("User-agent : *\nDisallow : /fileDownLoad.do\nAllow : /\n")   # 콜론 앞 공백(농진청 형식)
    assert rb2.can_fetch("https://a.kr/board/board.do?mode=list")
    assert not rb2.can_fetch("https://a.kr/fileDownLoad.do?x=1")
    only_google = crawler.Robots("User-agent: Googlebot\nAllow: /\n\nUser-agent: *\nDisallow: /\n")
    assert not only_google.can_fetch("https://a.kr/anything")
    ours = crawler.Robots("User-agent: *\nDisallow: /\n\nUser-agent: ByOrbit-RD-Studio\nAllow: /reports/\n"
                          "Disallow: /\n")
    assert ours.can_fetch("https://a.kr/reports/1") and not ours.can_fetch("https://a.kr/x")
    wild = crawler.Robots("User-agent: *\nDisallow: /*.hwp$\nDisallow: /tmp*\n")
    assert not wild.can_fetch("https://a.kr/f/a.hwp") and wild.can_fetch("https://a.kr/f/a.hwpx")
    assert not wild.can_fetch("https://a.kr/tmpdir/x")
    assert crawler.Robots("User-agent: *\nDisallow:\n").can_fetch("https://a.kr/x")   # 빈 Disallow = 전부 허용
    assert crawler.Robots("User-agent: *\nCrawl-delay: 7\n").crawl_delay() == 7


def test_robots_fetch_status_rules(web):
    web.pages["https://none.kr/robots.txt"] = (404, "")
    web.pages["https://down.kr/robots.txt"] = (500, "")
    web.pages["https://html.kr/robots.txt"] = "<!DOCTYPE html><html><title>오류</title></html>"
    assert crawler.robots_for("https://none.kr/x").can_fetch("https://none.kr/x")        # 404 → 허용
    assert not crawler.robots_for("https://down.kr/x").can_fetch("https://down.kr/x")    # 5xx → 보수적으로 막음
    assert crawler.robots_for("https://html.kr/x").can_fetch("https://html.kr/x")        # HTML 오류 페이지 → 없음
    n = len(web.calls)
    crawler.robots_for("https://none.kr/y")                                               # 하루 캐시
    assert len(web.calls) == n


def test_crawl_skips_when_robots_disallows(web):
    web.pages["https://deny.kr/robots.txt"] = "User-agent: *\nDisallow: /\n"
    web.pages["https://deny.kr/list"] = LIST_HTML
    items, rep = crawler.crawl_site(_site("deny.kr"), "사과박")
    assert items == [] and rep.pages == 0 and rep.robots_ok is False
    assert "https://deny.kr/list" not in web.calls
    assert any("robots" in m for m in rep.messages)


def test_crawl_delay_and_minimum_interval(web):
    web.pages["https://slow.kr/robots.txt"] = "User-agent: *\nCrawl-delay: 7\nAllow: /\n"
    web.pages["https://slow.kr/list"] = LIST_HTML
    web.pages["https://slow.kr/view/1"] = DETAIL_HTML
    web.pages["https://slow.kr/view/3"] = DETAIL_HTML
    crawler.crawl_site(_site("slow.kr", interval_s=1), "사과박")
    assert http.MIN_INTERVAL["slow.kr"] == 7
    assert web.sleeps and max(web.sleeps) > 6.5          # 실제로 7초 가까이 기다렸다(가짜 sleep)
    # 사이트 간격이 1초로 들어와도 3초 아래로는 내려가지 않는다
    assert crawler.validate_site({"name": "x", "start_urls": ["https://q.kr/"], "link_pattern": "x",
                                  "interval_s": 0.2})["interval_s"] == 3.0
    web.pages["https://fast.kr/robots.txt"] = "User-agent: *\nAllow: /\n"
    web.pages["https://fast.kr/list"] = LIST_HTML
    crawler.crawl_site(_site("fast.kr", interval_s=1), "없는말")
    assert http.MIN_INTERVAL["fast.kr"] == 3.0


# ================================================================ 링크·항목

def test_link_filtering_and_query_matching(web):
    web.pages["https://ok.kr/robots.txt"] = "User-agent: *\nDisallow: /files/secret.pdf\n"
    web.pages["https://ok.kr/list"] = LIST_HTML
    web.pages["https://ok.kr/view/1"] = DETAIL_HTML
    web.pages["https://ok.kr/view/3"] = "<html><body>내용 없음</body></html>"
    web.pages["https://ok.kr/view/77"] = "<html><body>자바스크립트 상세</body></html>"
    site = _site("ok.kr", title_hint=".tit", link_template="https://ok.kr/view/{1}")
    items, rep = crawler.crawl_site(site, "사과 박")      # 띄어쓰기가 달라도 맞는다
    titles = {i.title for i in items}
    assert "사과박 건조 공정 연구" in titles
    assert "감귤 부산물 사과 박 비교" in titles            # <mark> 안 글자도 이어 붙여 본다
    assert "자바스크립트 사과박 보고서" in titles          # javascript:goView('77') → link_template
    assert not any("허용 경로 밖" in t or "다른 호스트" in t for t in titles)
    assert "커피박 추출 효율" not in titles                # 검색어 불일치
    assert "https://ok.kr/other/4" not in web.calls and not any("elsewhere" in c for c in web.calls)
    it = next(i for i in items if i.title == "사과박 건조 공정 연구")
    assert it.source == "crawler" and it.source_id.startswith("t-ok:")
    assert it.year == 2025 and it.extra["date"] == "2025-03-04"
    assert it.abstract == "사과박을 열풍 건조한 결과 요약."   # 상세 페이지 og:description
    assert it.license == "공공누리 제1유형"
    assert it.pdf_url == "https://ok.kr/files/a1.pdf"       # PDF만 pdf_url
    assert it.doc_type == "report"
    att = {a["url"] for a in it.extra["attachments"]}
    assert "https://ok.kr/files/a1.hwp" in att and "https://ok.kr/files/d1.pdf" in att
    assert "https://ok.kr/files/secret.pdf" not in att      # robots가 막은 첨부는 기록하지 않음
    # 모든 검색어가 있어야 한다
    items2, _ = crawler.crawl_site(site, "사과박 커피박")
    assert items2 == []


def test_onclick_rows_and_attachment_items(web):
    html = """<table><tbody>
      <tr onclick="location.href='/web/board/9/101'"><td class="num">2</td><td class="tit_td">사과박 식이섬유</td>
          <td class="date">2026-11-16</td></tr>
      <tr onclick="location.href='/web/board/9/102'"><td class="tit_td">기타 소식</td></tr>
    </tbody></table>
    <ul><li><a href="/upload/attach/2026/10/20/x.pdf" download="사과박 가이드라인"><img alt="표지"></a></li></ul>"""
    web.pages["https://kf.kr/robots.txt"] = "User-agent: *\nAllow: /\n"
    web.pages["https://kf.kr/list"] = html
    web.pages["https://kf.kr/web/board/9/101"] = "<html><body>본문</body></html>"
    s = _site("kf.kr", allow_prefixes=["/web/board/9/"], link_pattern=r"/web/board/9/\d+$", title_hint=".tit_td")
    items, _ = crawler.crawl_site(s, "사과박")
    assert [i.title for i in items] == ["사과박 식이섬유"] and items[0].extra["date"] == "2026-11-16"
    s2 = _site("kf.kr", id="t-kf2", allow_prefixes=["/upload/attach/"], link_pattern=r"/upload/attach/.+\.pdf$",
               pdf_pattern=r"\.pdf$", date_pattern=r"/upload/attach/((?:19|20)\d{2})/(\d{2})/(\d{2})/")
    items, rep = crawler.crawl_site(s2, "가이드라인")
    assert len(items) == 1 and items[0].pdf_url == "https://kf.kr/upload/attach/2026/10/20/x.pdf"
    assert items[0].title == "사과박 가이드라인" and items[0].year == 2026 and rep.pages == 1


def test_max_pages_limit(web):
    rows = "".join(f'<li><a href="/view/{i}">사과박 시험 {i}</a></li>' for i in range(60))
    web.pages["https://big.kr/robots.txt"] = "User-agent: *\nAllow: /\n"
    web.pages["https://big.kr/list"] = f"<ul>{rows}</ul>"
    web.fallback = lambda url: "<html><body>상세</body></html>" if "big.kr/view/" in url else None
    items, rep = crawler.crawl_site(_site("big.kr", max_pages=5), "사과박", limit=100)
    assert rep.pages == 5
    assert sum(1 for c in web.calls if "big.kr/view/" in c) == 4
    assert len(items) == 60                    # 목록에서 찾은 항목은 모두 돌려주되 상세는 4장만 봤다
    capped = crawler.validate_site({"name": "x", "start_urls": ["https://q.kr/"], "link_pattern": "x",
                                    "max_pages": 999, "max_depth": 9})
    assert capped["max_pages"] == crawler.HARD_MAX_PAGES and capped["max_depth"] == crawler.HARD_MAX_DEPTH


def test_search_urls_template_used(web):
    web.pages["https://s.kr/robots.txt"] = "User-agent: *\nAllow: /\n"
    q = urllib.parse.quote("사과박")
    web.pages[f"https://s.kr/list?q={q}"] = '<a href="/view/9">사과박 검색 결과</a>'
    s = _site("s.kr", search_urls=["https://s.kr/list?q={q}"], max_depth=1)
    s["max_pages"] = 1
    items, rep = crawler.crawl_site(s, "사과박")
    assert web.calls[-1] == f"https://s.kr/list?q={q}" and items[0].title == "사과박 검색 결과"
    assert "https://s.kr/list" not in web.calls          # 사이트 검색이 있으면 첫 목록은 생략


def test_query_terms_korean_friendly():
    t = crawler.query_terms('"사과박" AND 건조')
    assert t == ["사과박", "건조"]
    assert crawler.matches(t, "사과 박 열풍 건조 연구")
    assert crawler.matches(crawler.query_terms("Apple Pomace"), "apple pomace drying")
    assert not crawler.matches(t, "사과박 추출")


# ================================================================ 사이트 목록

def test_site_crud_merges_defaults_and_user_file(web):
    from app import config
    defaults = crawler.load_defaults()
    assert defaults and all(d["default"] for d in defaults)
    for d in defaults:                                      # 기본 사이트는 정해진 필드를 모두 갖춘다
        for f in crawler.SITE_FIELDS:
            assert f in d, (d["id"], f)
        assert d["interval_s"] >= 3 and d.get("terms_checked") and d.get("robots_checked")
        assert d["enabled"] is False or d.get("terms_url")  # 이용 조건을 못 찾은 곳은 꺼져 있다
    ids = [s["id"] for s in crawler.list_sites()]
    assert ids == [d["id"] for d in defaults]

    new = crawler.save_site({"name": "내 사이트", "start_urls": ["https://my.kr/list"],
                             "link_pattern": r"/view/\d+", "interval_s": 1})
    assert new["default"] is False and new["interval_s"] == 3 and new["id"]
    f = config.path("config", "crawl_sites.json")
    assert f.exists() and new["id"] in f.read_text(encoding="utf-8")
    assert any(s["id"] == new["id"] for s in crawler.list_sites())

    d0 = defaults[0]["id"]
    crawler.save_site({**crawler.get_site(d0), "enabled": False, "interval_s": 1})
    got = crawler.get_site(d0)
    assert got["enabled"] is False and got["default"] is True
    assert got["interval_s"] >= defaults[0]["interval_s"]   # 기본 간격보다 짧게 못 줄인다
    crawler.save_site({**got, "enabled": True})
    crawler.delete_site(d0)                                  # 기본 사이트는 삭제 대신 꺼짐
    assert crawler.get_site(d0)["enabled"] is False
    crawler.delete_site(new["id"])
    assert all(s["id"] != new["id"] for s in crawler.list_sites())
    with pytest.raises(KeyError):
        crawler.delete_site("없는-사이트")
    with pytest.raises(ValueError):
        crawler.save_site({"name": "x", "start_urls": ["https://x.kr/"], "link_pattern": "(["})
    with pytest.raises(ValueError):
        crawler.save_site({"name": "x", "start_urls": ["ftp://x.kr/"], "link_pattern": "a"})
    with pytest.raises(ValueError):
        crawler.save_site({"name": "x", "start_urls": ["https://x.kr/"]})          # 패턴 없음
    with pytest.raises(ValueError):
        crawler.save_site({"name": "x", "start_urls": ["https://x.kr/"], "link_pattern": "a",
                           "search_urls": ["https://x.kr/s"]})                     # {q} 없음


def test_check_site(web, monkeypatch):
    web.pages["https://chk.kr/robots.txt"] = "User-agent: *\nCrawl-delay: 5\nDisallow: /private\n"
    s_ok = crawler.save_site({"name": "점검", "start_urls": ["https://chk.kr/list"], "link_pattern": "v",
                              "terms_url": "https://chk.kr/terms"})
    r = crawler.check_site(s_ok["id"])
    assert r["robots_ok"] is True and r["terms_url"] == "https://chk.kr/terms" and "5" in r["message"]
    s_bad = crawler.save_site({"name": "막힘", "start_urls": ["https://chk.kr/private/list"], "link_pattern": "v"})
    r = crawler.check_site(s_bad["id"])
    assert r["robots_ok"] is False and r["terms_url"] is None and "막힘" in r["message"]


def test_crawler_source(web, monkeypatch):
    from app.collect.sources import crawler as src_mod
    src = src_mod.SOURCE
    assert src.key == "crawler" and src.kind == "crawler" and src.group == "크롤러"
    monkeypatch.setattr(crawler, "load_defaults", lambda: [])
    assert src.status()["ready"] is False
    with pytest.raises(base.SourceError):
        src.search("사과박")
    web.pages["https://src.kr/robots.txt"] = "User-agent: *\nAllow: /\n"
    web.pages["https://src.kr/list"] = LIST_HTML
    web.fallback = lambda url: "<html></html>" if "src.kr/view/" in url else None
    crawler.save_site({"id": "src-test", "name": "출처 시험", "start_urls": ["https://src.kr/list"],
                       "allow_prefixes": ["/view/"], "link_pattern": r"/view/\d+$"})
    assert src.status()["ready"] is True
    items = src.search("커피박")
    assert [i.title for i in items] == ["커피박 추출 효율"]
    assert src.last_reports()[0]["site_id"] == "src-test"
    from app.collect import registry
    assert "crawler" in registry.sources(reload=True)


# ================================================================ 키 필요 API — 공통

def _api_web(monkeypatch, body, status=200):
    """한 응답만 돌려주는 가짜 opener. 요청 주소를 기록한다."""
    calls = []

    def opener(req, timeout):
        calls.append(req)
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "err", None, io.BytesIO(body.encode()))
        b = body(req) if callable(body) else body
        return FakeResp(b.encode("utf-8") if isinstance(b, str) else b)
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    http.set_opener(opener)
    return calls


@pytest.fixture()
def no_net():
    yield
    http.set_opener(None)


SECRET = "SeCrEt-KEY-1234567890=="


# ---------------------------------------------------------------- KCI
# 문서 스키마를 따른 재구성 예시(MetaData > outputData > result/total + record). 실제 키로는 미검증.
KCI_OK = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData>
  <inputData><key>SeCrEt-KEY-1234567890==</key><apiCode>articleSearch</apiCode><title><![CDATA[사과박]]></title></inputData>
  <outputData>
    <result><total>2</total></result>
    <record>
      <journalInfo>
        <journal-name>한국식품저장유통학회지</journal-name><publisher-name>한국식품저장유통학회</publisher-name>
        <pub-year>2021</pub-year><pub-mon>04</pub-mon><volume>28</volume><issue>2</issue>
      </journalInfo>
      <articleInfo article-id="ART002712345">
        <article-categories>식품과학</article-categories>
        <title-group>
          <article-title lang="original"><![CDATA[열풍 건조 조건에 따른 사과박 분말의 이화학적 특성]]></article-title>
          <article-title lang="english"><![CDATA[Physicochemical properties of apple pomace powder by hot-air drying]]></article-title>
        </title-group>
        <author-group><author>김사과(한국대학교)</author><author>이건조(식품연구원)</author></author-group>
        <abstract-group><abstract lang="original"><![CDATA[사과박을 50–70 ℃에서 건조하였다.]]></abstract></abstract-group>
        <fpage>201</fpage><lpage>210</lpage>
        <doi>https://doi.org/10.11002/KJFP.2021.28.2.201</doi>
        <url>https://www.kci.go.kr/kciportal/landing/article.kci?arti_id=ART002712345</url>
        <citation-count>3</citation-count>
      </articleInfo>
    </record>
    <record>
      <journalInfo><journal-name>농업생명과학연구</journal-name><pub-year>2019</pub-year></journalInfo>
      <articleInfo article-id="ART002400001">
        <title-group><article-title lang="original">사과 부산물 이용</article-title></title-group>
      </articleInfo>
    </record>
  </outputData>
</MetaData>"""

KCI_ERR = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData><inputData><key>SeCrEt-KEY-1234567890==</key><apiCode>articleSearch</apiCode></inputData>
<outputData><result><resultMsg>등록되지 않은 key 입니다.</resultMsg></result></outputData></MetaData>"""


def test_kci_parse_and_request(monkeypatch, no_net):
    from app.collect.sources import kci
    monkeypatch.setenv("BYORBIT_KCI_KEY", SECRET)
    calls = _api_web(monkeypatch, KCI_OK)
    items = kci.SOURCE.search("사과박", limit=5, since_year=2020)
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[0].full_url).query)
    assert q["apiCode"] == ["articleSearch"] and q["title"] == ["사과박"] and q["key"] == [SECRET]
    assert q["displayCount"] == ["5"] and q["dateFrom"] == ["202001"]
    assert len(items) == 1                                  # 2019년 논문은 since_year로 빠짐
    it = items[0]
    assert it.source == "kci" and it.source_id == "ART002712345"
    assert it.title == "열풍 건조 조건에 따른 사과박 분말의 이화학적 특성"
    assert it.extra["title_en"].startswith("Physicochemical")
    assert it.authors == ["김사과", "이건조"] and it.year == 2021
    assert it.venue == "한국식품저장유통학회지" and it.doi == "10.11002/kjfp.2021.28.2.201"
    assert it.abstract.startswith("사과박을") and it.url.endswith("ART002712345")
    assert it.pdf_url is None and it.doc_type == "article" and it.extra["pages"] == "201-210"


def test_kci_error_never_shows_key(monkeypatch, no_net):
    from app.collect.sources import kci
    monkeypatch.setenv("BYORBIT_KCI_KEY", SECRET)
    _api_web(monkeypatch, KCI_ERR)
    with pytest.raises(base.SourceError) as ei:
        kci.SOURCE.search("사과박")
    assert "등록되지 않은 key" in str(ei.value) and SECRET not in str(ei.value)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__


# ---------------------------------------------------------------- KIPRIS
# 오류 응답은 2026-11-25 키 없이 실제 호출한 결과 그대로, 정상 응답은 문서 스키마를 따른 재구성(실제 키로 미검증).
KIPRIS_OK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<response><header><successYN>Y</successYN><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
<body><items>
<item><indexNo>1</indexNo><registerStatus>등록</registerStatus>
<inventionTitle>사과박을 이용한 식이섬유 소재의 제조방법</inventionTitle>
<ipcNumber>A23L 33/21|A23L 19/00</ipcNumber><registerNumber>1023456780000</registerNumber><registerDate>20210315</registerDate>
<applicationNumber>1020190012345</applicationNumber><applicationDate>20190130</applicationDate>
<openNumber>1020200098765</openNumber><openDate>20200807</openDate><publicationNumber/><publicationDate/>
<astrtCont>본 발명은 사과박을 열풍 건조·분쇄하여 식이섬유 소재를 얻는 방법에 관한 것이다.</astrtCont>
<drawing>http://plus.kipris.or.kr/kiprisplusws/fileToss.jsp?arg=abc</drawing><bigDrawing>http://plus.kipris.or.kr/kiprisplusws/fileToss.jsp?arg=big</bigDrawing>
<applicantName>한국식품연구원|주식회사 사과</applicantName></item>
</items><count><numOfRows>10</numOfRows><pageNo>1</pageNo><totalCount>1</totalCount></count></body></response>"""

KIPRIS_ERR = """<response>
<header>
<requestMsgID/>
<responseTime>2026-11-25 09:27:58</responseTime>
<responseMsgID/>
<successYN>N</successYN>
<resultCode>30</resultCode>
<resultMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</resultMsg>
</header>
</response>"""


def test_kipris_parse_and_request(monkeypatch, no_net):
    from app.collect.sources import kipris
    monkeypatch.setenv("BYORBIT_KIPRIS_KEY", SECRET)
    calls = _api_web(monkeypatch, KIPRIS_OK)
    items = kipris.SOURCE.search("사과박", limit=10)
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[0].full_url).query)
    assert calls[0].full_url.startswith(kipris.API) and q["word"] == ["사과박"] and q["ServiceKey"] == [SECRET]
    it = items[0]
    assert it.doc_type == "patent" and it.source_id == "1020190012345" and it.year == 2019
    assert it.title.startswith("사과박을 이용한") and it.authors == ["한국식품연구원", "주식회사 사과"]
    assert it.extra["출원번호"] == "1020190012345" and it.extra["출원인"] == ["한국식품연구원", "주식회사 사과"]
    assert it.extra["IPC"] == ["A23L 33/21", "A23L 19/00"] and it.extra["등록상태"] == "등록"
    assert it.extra["출원일"] == "2019-01-30" and it.extra["공개일"] == "2020-08-07"
    assert it.pdf_url is None and it.abstract.startswith("본 발명은")


def test_kipris_error(monkeypatch, no_net):
    from app.collect.sources import kipris
    monkeypatch.setenv("BYORBIT_KIPRIS_KEY", SECRET)
    _api_web(monkeypatch, KIPRIS_ERR)
    with pytest.raises(base.SourceError) as ei:
        kipris.SOURCE.search("사과박")
    assert "30" in str(ei.value) and SECRET not in str(ei.value)


# ---------------------------------------------------------------- NTIS
NTIS_OK = """<?xml version='1.0' encoding='UTF-8' ?>
<RESULT><TOTALHITS>1</TOTALHITS><RESULTSET>
<HIT>
  <ProjectNumber>1395071234</ProjectNumber>
  <ProjectTitle><Korean>사과박 고부가 식품소재화 기술 개발</Korean><English>Upcycling of apple pomace</English></ProjectTitle>
  <Manager><Name>박연구</Name></Manager>
  <Researchers>박연구, 최보조</Researchers>
  <Goal><Full>사과박 건조·분말화 공정 확립</Full></Goal>
  <Abstract><Full>열풍·동결 건조 비교</Full></Abstract>
  <Effect><Teaser>부산물 자원화</Teaser></Effect>
  <Keyword><Korean>사과박, 건조</Korean><English>apple pomace</English></Keyword>
  <OrderAgency><Name>농림식품기술기획평가원</Name></OrderAgency>
  <ResearchAgency><Name>한국식품연구원</Name></ResearchAgency>
  <BudgetProject><Name>고부가가치식품기술개발</Name></BudgetProject>
  <Ministry><Name>농림축산식품부</Name></Ministry>
  <ProjectYear>2023</ProjectYear>
  <ProjectPeriod><Start>20230401</Start><End>20231231</End><TotalStart>20230401</TotalStart><TotalEnd>20251231</TotalEnd></ProjectPeriod>
  <GovernmentFunds>150000000</GovernmentFunds>
</HIT></RESULTSET></RESULT>"""


def test_ntis_parse(monkeypatch, no_net):
    from app.collect.sources import ntis
    monkeypatch.setenv("BYORBIT_NTIS_KEY", SECRET)
    calls = _api_web(monkeypatch, NTIS_OK)
    items = ntis.SOURCE.search("사과박")
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[0].full_url).query)
    assert q["apprvKey"] == [SECRET] and q["collection"] == ["project"] and q["query"] == ["사과박"]
    it = items[0]
    assert it.doc_type == "project" and it.source_id == "1395071234" and it.year == 2023
    assert it.title == "사과박 고부가 식품소재화 기술 개발" and it.authors == ["박연구", "최보조"]
    assert it.venue == "한국식품연구원" and "[연구목표] 사과박 건조" in it.abstract
    assert it.extra["과제번호"] == "1395071234" and it.extra["부처"] == "농림축산식품부"


def test_ntis_error_echoes_key_masked(monkeypatch, no_net):
    from app.collect.sources import ntis
    monkeypatch.setenv("BYORBIT_NTIS_KEY", SECRET)
    # 2026-11-25 실제 응답 형식: 보낸 키를 그대로 되돌려 준다
    _api_web(monkeypatch, f"<?xml version='1.0' encoding='UTF-8' ?>\n<error>유효한 인증키가 아닙니다. 인증키 : {SECRET}</error>")
    with pytest.raises(base.SourceError) as ei:
        ntis.SOURCE.search("사과박")
    assert "유효한 인증키가 아닙니다" in str(ei.value) and SECRET not in str(ei.value)


NTIS_REPORT = """<RESULT><TOTALHITS>1</TOTALHITS><RESULTSET><HIT NO="1">
 <TermSn>REP-2023-0001</TermSn><PublicationYm>202312</PublicationYm><ResearchPublicNo>TRKO202400001234</ResearchPublicNo>
 <PublicationAgency>농촌진흥청</PublicationAgency>
 <ResultTitle><Korean>&lt;span class="search_word"&gt;사과박&lt;/span&gt; 사료화 연구</Korean><English>Apple pomace feed</English></ResultTitle>
 <Abstract><Korean>사과박을 발효 사료로 이용</Korean></Abstract><Keyword><Korean>사과박;사료</Korean></Keyword>
 <DocUrl>https://nrms.kisti.re.kr/sc/fullDvsSrch/pop_srchList.do?rpt_ctrl_no=RTTRKO1</DocUrl>
 <ProjectNumber>1395000001</ProjectNumber><ProjectTitle>사과박 과제</ProjectTitle><Manager>정책임</Manager>
</HIT></RESULTSET></RESULT>"""


def test_ntis_reports_mixed_in(monkeypatch, no_net):
    from app.collect.sources import ntis
    monkeypatch.setenv("BYORBIT_NTIS_KEY", SECRET)
    calls = _api_web(monkeypatch, lambda req: NTIS_REPORT if "rresearchpdf" in req.full_url else NTIS_OK)
    items = ntis.SOURCE.search("사과박")
    assert [i.doc_type for i in items] == ["project", "report"]
    rep = items[1]
    assert rep.title == "사과박 사료화 연구"                   # 검색어 강조 태그 제거
    assert rep.source_id == "TRKO202400001234" and rep.year == 2023 and rep.venue == "농촌진흥청"
    assert rep.pdf_url is None and rep.url.startswith("https://nrms.kisti.re.kr/")
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[1].full_url).query)
    assert q["collection"] == ["rresearchpdf"]


def test_ntis_report_api_not_approved_keeps_projects(monkeypatch, no_net):
    from app.collect.sources import ntis
    monkeypatch.setenv("BYORBIT_NTIS_KEY", SECRET)
    _api_web(monkeypatch, lambda req: (f"<error>유효한 인증키가 아닙니다. 인증키 : {SECRET}</error>"
                                        if "rresearchpdf" in req.full_url else NTIS_OK))
    items = ntis.SOURCE.search("사과박")
    assert len(items) == 1 and items[0].doc_type == "project"
    assert ntis.SOURCE.last_warning and SECRET not in ntis.SOURCE.last_warning


# ---------------------------------------------------------------- ScienceON

def test_aes_matches_fips197_and_token_accounts():
    import base64
    from datetime import datetime

    from app.collect.sources import scienceon as so
    pt = bytes.fromhex("00112233445566778899aabbccddeeff")
    assert so._encrypt_block(pt, so._expand_key(bytes(range(32)))).hex() == "8ea2b7ca516745bfeafc49904b496089"
    assert so._encrypt_block(pt, so._expand_key(bytes(range(16)))).hex() == "69c4e0d86a7b0430d8cdb78070b4c55a"
    acc = so.make_accounts("A" * 32, "b4:2e:99:ad:48:7d", now=datetime(2021, 4, 30, 1, 15, 40))
    raw = base64.urlsafe_b64decode(acc)
    assert len(raw) % 16 == 0 and "+" not in acc and "/" not in acc
    try:                                                     # 있으면 표준 구현과 바이트 단위로 비교
        from cryptography.hazmat.primitives import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        return
    plain = b'{"datetime":"20210430011540","mac_address":"B4-2E-99-AD-48-7D"}'
    p = padding.PKCS7(128).padder()
    e = Cipher(algorithms.AES(b"A" * 32), modes.CBC(so.IV)).encryptor()
    assert raw == e.update(p.update(plain) + p.finalize()) + e.finalize()


SO_ARTI = """<?xml version="1.0" encoding="UTF-8"?>
<MetaData><resultSummary><TotalCount>1</TotalCount><statusCode>200</statusCode></resultSummary>
<recordList><record rownum="1">
 <item metaCode="CN" metaName="CN"><![CDATA[JAKO202112345678901]]></item>
 <item metaCode="DBCode" metaName="DB코드"><![CDATA[JAKO]]></item>
 <item metaCode="Title" metaName="제목"><![CDATA[사과박 분말의 항산화 활성]]></item>
 <item metaCode="Author" metaName="저자"><![CDATA[김사과;이분말]]></item>
 <item metaCode="Pubyear" metaName="발행년"><![CDATA[2021]]></item>
 <item metaCode="JournalName" metaName="저널명"><![CDATA[한국식품영양과학회지]]></item>
 <item metaCode="Abstract" metaName="초록"><![CDATA[사과박의 페놀 함량]]></item>
 <item metaCode="DOI" metaName="DOI"><![CDATA[10.3746/jkfn.2021.50.1.1]]></item>
 <item metaCode="FulltextURL" metaName="원문"><![CDATA[https://example.kisti.re.kr/full/JAKO.pdf]]></item>
 <item metaCode="ContentURL" metaName="상세"><![CDATA[https://scienceon.kisti.re.kr/srch/selectPORSrchArticle.do?cn=JAKO202112345678901]]></item>
</record></recordList></MetaData>"""
SO_REPORT = SO_ARTI.replace("JAKO202112345678901", "TRKO202400001234").replace(
    'metaCode="JournalName" metaName="저널명"><![CDATA[한국식품영양과학회지]]>',
    'metaCode="Publisher" metaName="발행기관"><![CDATA[농촌진흥청]]>').replace(".pdf", "")


def _so_env(monkeypatch):
    from app.collect.sources import scienceon as so
    monkeypatch.setenv("BYORBIT_SCIENCEON_CLIENT_ID", "c" * 64)
    monkeypatch.setenv("BYORBIT_SCIENCEON_KEY", "K" * 32)
    monkeypatch.setenv("BYORBIT_SCIENCEON_MAC", "B4-2E-99-AD-48-7D")
    so.SOURCE._token = None
    return so


def test_scienceon_token_and_search(monkeypatch, no_net):
    so = _so_env(monkeypatch)

    def body(req):
        u = req.full_url
        if "tokenrequest.do" in u:
            return json.dumps({"access_token": "TOKEN-abc", "access_token_expire": "2099-01-01 00:00:00.000",
                               "refresh_token": "r", "client_id": "c" * 64})
        return SO_REPORT if "target=REPORT" in u else SO_ARTI
    calls = _api_web(monkeypatch, body)
    items = so.SOURCE.search("사과박", limit=10)
    assert sum("tokenrequest.do" in c.full_url for c in calls) == 1     # 토큰은 한 번만 발급(메모리 보관)
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[1].full_url).query)
    assert json.loads(q["searchQuery"][0]) == {"BI": "사과박"} and q["token"] == ["TOKEN-abc"]
    art = next(i for i in items if i.doc_type == "article")
    rep = next(i for i in items if i.doc_type == "report")
    assert art.authors == ["김사과", "이분말"] and art.venue == "한국식품영양과학회지" and art.year == 2021
    assert art.pdf_url.endswith(".pdf") and art.doi == "10.3746/jkfn.2021.50.1.1"
    assert rep.source_id == "TRKO202400001234" and rep.venue == "농촌진흥청" and rep.pdf_url is None


def test_scienceon_error_masks_secrets(monkeypatch, no_net):
    so = _so_env(monkeypatch)
    _api_web(monkeypatch, json.dumps({"errorMessage": "클라이언트ID 값 오류 " + "c" * 64, "errorCode": "E4102",
                                      "statusCode": "401"}))
    with pytest.raises(base.SourceError) as ei:
        so.SOURCE.search("사과박")
    assert "E4102" in str(ei.value) and "c" * 64 not in str(ei.value) and "K" * 32 not in str(ei.value)
    err_xml = """<MetaData><resultSummary><statusCode>401</statusCode></resultSummary><errorDetail>
    <statusMessage>Unauthorized</statusMessage><errorCode>E4102</errorCode><errorMessage>클라이언트ID 값 오류</errorMessage>
    </errorDetail></MetaData>"""
    with pytest.raises(base.SourceError, match="E4102"):
        so.parse(err_xml, "ARTI")


# ---------------------------------------------------------------- 공공데이터

FOODNUTRI_OK = {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {"pageNo": 1, "totalCount": 1, "numOfRows": 10, "items": [
                    {"NUM": "1", "FOOD_CD": "R102-001", "FOOD_NM_KR": "사과_부사_생것", "DB_CLASS_NM": "품목대표",
                     "FOOD_CAT1_NM": "과일류", "SERVING_SIZE": "100g", "AMT_NUM1": "53", "AMT_NUM2": "85.2",
                     "AMT_NUM3": "0.2", "AMT_NUM4": "0.1", "AMT_NUM6": "14.2", "AMT_NUM8": "1.4", "AMT_NUM157": "",
                     "SUB_REF_NAME": "식품의약품안전처", "RESEARCH_YMD": "2020-12-31"}]}}


def test_foodnutri_parse(monkeypatch, no_net):
    from app.collect.sources import datagokr_foodnutri as fn
    monkeypatch.setenv("BYORBIT_DATAGOKR_KEY", "abc%2Bdef%3D%3D")      # Encoding 키를 넣어도 풀어서 보낸다
    calls = _api_web(monkeypatch, json.dumps(FOODNUTRI_OK))
    items = fn.SOURCE.search("사과")
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[0].full_url).query)
    assert q["serviceKey"] == ["abc+def=="] and q["FOOD_NM_KR"] == ["사과"] and q["type"] == ["json"]
    it = items[0]
    assert it.doc_type == "dataset" and it.source_id == "R102-001" and it.year == 2020
    assert it.extra["영양성분"]["식이섬유(g)"] == 1.4 and "폐기율(%)" not in it.extra["영양성분"]
    assert "100g 기준" in it.abstract and "식이섬유 1.4g" in it.abstract
    alt = {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": FOODNUTRI_OK["body"]["items"][0]}}}}
    assert len(fn.parse(alt)[0]) == 1                        # items.item 모양도 받는다


def test_foodnutri_gateway_403_masks_key(monkeypatch, no_net):
    from app.collect.sources import datagokr_foodnutri as fn
    monkeypatch.setenv("BYORBIT_DATAGOKR_KEY", SECRET)
    _api_web(monkeypatch, '{"OpenAPI_ServiceResponse":{"cmmMsgHeader":{"returnReasonCode":"30"}}}', status=403)
    with pytest.raises(base.SourceError) as ei:
        fn.SOURCE.search("사과")
    assert "활용신청" in str(ei.value) and SECRET not in str(ei.value)
    with pytest.raises(base.SourceError, match="30"):
        fn.parse({"OpenAPI_ServiceResponse": {"cmmMsgHeader": {"errMsg": "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
                                                               "returnReasonCode": "30"}}})


# 2026-11-25 공개 sample 키로 실제 호출한 응답(일부)
HFFUNC_OK = {"I-0040": {"total_count": "1", "row": [{
    "PRMS_DT": "20150320", "DAY_INTK_CN": "풋사과추출물 애플페논(Applephenon)으로서 600 mg",
    "IFTKN_ATNT_MATR_CN": "사과에 알레르기가 있으신 분은 섭취 시 주의", "HF_FNCLTY_MTRAL_RCOGN_NO": "2015-9",
    "BSSH_NM": "(주)서흥", "FNCLTY_CN": "체지방 감소에 도움을 줄 수 있음(생리활성기능 2등급)",
    "APLC_RAWMTRL_NM": "풋사과추출물 애플페논(Applephenon)", "INDUTY_NM": "", "ADDR": "충청북도 청주시"}],
    "RESULT": {"MSG": "정상처리되었습니다.", "CODE": "INFO-000"}}}


def test_hffunc_parse_and_key_in_path_masked(monkeypatch, no_net):
    from app.collect.sources import datagokr_hffunc as hf
    monkeypatch.setenv("BYORBIT_FOODSAFETY_KEY", "pathkey12345")
    calls = _api_web(monkeypatch, json.dumps(HFFUNC_OK))
    items = hf.SOURCE.search("사과")
    assert "/api/pathkey12345/I-0040/json/1/" in calls[0].full_url
    assert urllib.parse.unquote(calls[0].full_url).endswith("APLC_RAWMTRL_NM=사과")
    it = items[0]
    assert it.source_id == "2015-9" and it.year == 2015 and it.extra["인정일자"] == "2015-03-20"
    assert it.authors == ["(주)서흥"] and "[기능성] 체지방 감소" in it.abstract
    _api_web(monkeypatch, "", status=500)                    # 키가 주소 경로에 있어도 오류 메시지에서 가린다
    with pytest.raises(base.SourceError) as ei:
        hf.SOURCE.search("사과")
    assert "pathkey12345" not in str(ei.value) and "***" in str(ei.value)
    _api_web(monkeypatch, '{"I-0040":{"total_count":"","RESULT":{"MSG":"인증키가 유효하지 않습니다.","CODE":"INFO-100"}}}')
    with pytest.raises(base.SourceError, match="INFO-100"):
        hf.SOURCE.search("사과")
    _api_web(monkeypatch, '{"I-0040":{"total_count":"0","RESULT":{"MSG":"해당하는 데이터가 없습니다.","CODE":"INFO-200"}}}')
    assert hf.SOURCE.search("없는원료") == []


BYPROD_LIST = """<?xml version="1.0" encoding="UTF-8"?><response><header><resultCode>00</resultCode><resultMsg/></header>
<body><items><item><cntntsNo>101</cntntsNo><cntntsSj>사과박</cntntsSj><lvstckSeNm>한우</lvstckSeNm>
<chartrCn>당분이 많고 수분이 높아 변패 쉬움</chartrCn><useLevelAtpnCn>건물 기준 10% 이내</useLevelAtpnCn></item>
<item><cntntsNo>102</cntntsNo><cntntsSj>사과박 사일리지</cntntsSj></item></items>
<numOfRows>10</numOfRows><pageNo>1</pageNo><totalCount>2</totalCount></body></response>"""
BYPROD_DTL = """<response><header><resultCode>00</resultCode></header><body><items><item><cntntsNo>101</cntntsNo>
<mitrValue>78.5</mitrValue><takprotValue>5.6</takprotValue><crfbValue>18.2</crfbValue><tdngValue>70.1</tdngValue>
</item></items></body></response>"""


def test_byprod_list_and_detail(monkeypatch, no_net):
    from app.collect.sources import datagokr_byprod as bp
    monkeypatch.setenv("BYORBIT_NONGSARO_KEY", SECRET)
    calls = _api_web(monkeypatch, lambda req: BYPROD_DTL if "Dtl" in req.full_url else BYPROD_LIST)
    items = bp.SOURCE.search("사과박")
    assert [i.title for i in items] == ["[농식품부산물 영양정보] 사과박", "[농식품부산물 영양정보] 사과박 사일리지"]
    assert items[0].extra["성분"]["조섬유(%)"] == "18.2" and "[이용 수준·주의] 건물 기준 10% 이내" in items[0].abstract
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(calls[0].full_url).query)
    assert q["sText"] == ["사과박"] and q["apiKey"] == [SECRET]
    _api_web(monkeypatch, "<response><header><resultCode>15</resultCode><resultMsg>도메인</resultMsg></header></response>")
    with pytest.raises(base.SourceError, match="도메인"):
        bp.SOURCE.search("사과박")


# ---------------------------------------------------------------- 키 없음·가리기 공통

KEYED = ["kci", "scienceon", "ntis", "kipris", "datagokr_foodnutri", "datagokr_hffunc", "datagokr_byprod"]


@pytest.mark.parametrize("key", KEYED)
def test_missing_key_status_and_search(key, monkeypatch, no_net):
    from app.collect import registry
    src = registry.sources(reload=True)[key]
    for e in src.needs_env:
        monkeypatch.delenv(e, raising=False)
    calls = _api_web(monkeypatch, "<x/>")
    st = src.status()
    assert st["ready"] is False and st["missing_env"] == list(src.needs_env)
    assert all(e.startswith("BYORBIT_") for e in src.needs_env)
    assert "https://" in src.key_help and src.needs_env[0] in src.key_help    # 어디서·어떤 변수
    assert src.group in ("국내 학술", "국가 R&D·특허", "공공데이터") and src.homepage and src.terms_url
    with pytest.raises(base.MissingKey):
        src.search("사과박")
    assert calls == []                                       # 키가 없으면 밖으로 아무것도 나가지 않는다


def test_mask_helper():
    from app.collect.sources.kci import mask
    s = mask(f"https://x.kr/a?key={SECRET}&q=1 {urllib.parse.quote(SECRET, safe='')} ServiceKey=zzz", SECRET)
    assert SECRET not in s and urllib.parse.quote(SECRET, safe="") not in s and "zzz" not in s
