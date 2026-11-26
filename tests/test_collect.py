"""M3 묶음 A 시험: 해외 공식 API 4종 파싱(가짜 응답·네트워크 없음), DOI 정규화, 출처 간 중복 병합,
출처 하나가 실패하는 검색, 자료함 투입(PDF·초록 .md·중복), 저장 검색 자동 실행(가짜 시각), API 경로, 개인정보."""
from __future__ import annotations

import email.message
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
from datetime import datetime, timedelta

import pytest

QUERY = "apple pomace drying"
DOI_A = "10.3390/app12031434"
DOI_B = "10.1016/j.biortech.2021.125207"


# ---------------------------------------------------------------- 가짜 응답(실제 응답 모양을 줄인 것)

def openalex_json():
    return {"meta": {"count": 2}, "results": [
        {"id": "https://openalex.org/W4210766440", "doi": "https://doi.org/10.3390/APP12031434",
         "display_name": "Modeling of the Drying Process of Apple Pomace", "publication_year": 2022,
         "type": "article", "language": "en",
         "authorships": [{"author": {"display_name": "Weronika Tulej"}}, {"author": {"display_name": "Szymon Głowacki"}}],
         "primary_location": {"landing_page_url": "https://doi.org/10.3390/app12031434", "license": "cc-by",
                              "source": {"display_name": "Applied Sciences"}},
         "best_oa_location": {"pdf_url": "https://www.mdpi.com/2076-3417/12/3/1434/pdf", "license": "cc-by",
                              "source": {"display_name": "Applied Sciences"}},
         "open_access": {"is_oa": True, "oa_status": "gold"},
         "abstract_inverted_index": {"Apple": [0], "pomace": [1, 5], "was": [2], "dried.": [3], "The": [4],
                                     "model": [6], "fits.": [7]}},
        {"id": "https://openalex.org/W1", "doi": None, "display_name": "Apple Pomace Drying",
         "publication_year": 2010, "type": "book", "authorships": [], "primary_location": {"source": None},
         "best_oa_location": None, "open_access": {"is_oa": False}, "abstract_inverted_index": None},
    ]}


def crossref_json():
    return {"status": "ok", "message": {"items": [
        {"DOI": "10.3390/app12031434", "title": ["Modeling of the Drying Process of Apple Pomace"],
         "author": [{"given": "Weronika", "family": "Tulej"}], "container-title": ["Applied Sciences"],
         "issued": {"date-parts": [[2022, 1, 28]]}, "type": "journal-article", "URL": "https://doi.org/10.3390/app12031434",
         "abstract": "<jats:title>Abstract</jats:title><jats:p>Understanding <jats:italic>biological</jats:italic> materials "
                     "is quite complicated. A much longer abstract text from Crossref than the OpenAlex one, so it should win.</jats:p>",
         "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/", "content-version": "vor"}],
         "link": [{"URL": "https://www.mdpi.com/2076-3417/12/3/1434/pdf", "content-type": "application/pdf"}]},
        {"DOI": "10.1016/J.FOODCHEM.2019.05.131", "title": ["Impact of air-drying on polyphenol extractability"],
         "author": [{"given": "A", "family": "B"}], "container-title": ["Food Chemistry"],
         "issued": {"date-parts": [[2019]]}, "type": "journal-article",
         "license": [{"URL": "https://www.elsevier.com/tdm/userlicense/1.0/", "content-version": "tdm"}],
         "link": [{"URL": "https://api.elsevier.com/content/article/PII:S0308814619309367", "content-type": "application/pdf"}]},
    ]}}


def europepmc_json():
    return {"hitCount": 2, "resultList": {"result": [
        {"id": "33932812", "source": "MED", "pmid": "33932812", "doi": "10.1016/j.biortech.2021.125207",
         "title": "Microwave hydrodiffusion and gravity as a sustainable alternative approach for an efficient apple pomace drying.",
         "authorString": "Fernandes PAR, Bastos R.", "authorList": {"author": [{"fullName": "Fernandes PAR"}, {"fullName": "Bastos R"}]},
         "journalInfo": {"journal": {"title": "Bioresource technology"}}, "pubYear": "2021",
         "abstractText": "Apple pomace <i>(AP)</i> drying was studied.", "isOpenAccess": "N", "language": "eng",
         "pubTypeList": {"pubType": ["Journal Article"]}},
        {"id": "PMC13605857", "source": "PMC", "pmcid": "PMC13605857", "doi": "10.3390/foods15183244",
         "title": "Phytochemical Profiling of Apple Pomaces", "authorString": "Chiș MS.",
         "journalInfo": {"journal": {"title": "Foods"}}, "pubYear": "2026", "abstractText": "Apple pomace phenolics.",
         "isOpenAccess": "Y", "license": "cc by", "language": "eng",
         "fullTextUrlList": {"fullTextUrl": [
             {"availabilityCode": "S", "documentStyle": "doi", "url": "https://doi.org/10.3390/foods15183244"},
             {"availabilityCode": "OA", "documentStyle": "pdf", "url": "https://europepmc.org/articles/PMC13605857?pdf=render"}]}},
    ]}}


def s2_json():
    return {"total": 1, "data": [
        {"paperId": "abc123", "title": "Microwave hydrodiffusion and gravity as a sustainable alternative approach "
                                       "for an efficient apple pomace drying",
         "year": 2021, "venue": "Bioresource Technology", "abstract": None,
         "externalIds": {"DOI": "10.1016/J.BIORTECH.2021.125207"}, "isOpenAccess": True,
         "openAccessPdf": {"url": "https://repo.example.org/ap.pdf", "status": "GREEN", "license": "CCBY"},
         "authors": [{"name": "P. Fernandes"}], "url": "https://www.semanticscholar.org/paper/abc123",
         "publicationTypes": ["JournalArticle"]},
    ]}


def make_pdf(text="Apple pomace drying PDF body. 사과박 건조 원문.") -> bytes:
    import pymupdf
    d = pymupdf.open()
    p = d.new_page()
    p.insert_text((72, 72), text)
    out = d.tobytes()
    d.close()
    return out


class FakeResp(io.BytesIO):
    def __init__(self, body: bytes, ctype="application/json"):
        super().__init__(body)
        self.headers = email.message.Message()
        self.headers["Content-Type"] = ctype + ("; charset=utf-8" if "json" in ctype or "html" in ctype else "")


class Fake:
    """http.set_opener용. 주소별 응답을 돌려주고 모든 요청을 기록한다."""

    def __init__(self):
        self.requests: list[tuple[str, dict]] = []
        self.fail: dict[str, int] = {}       # host → HTTP 상태(항상 실패)
        self.files: dict[str, bytes] = {}    # 전체 URL → 바이트
        self.sleep = 0.0

    def __call__(self, req, timeout):
        url = req.full_url
        self.requests.append((url, dict(req.header_items())))
        if self.sleep:
            time.sleep(self.sleep)
        host = urllib.parse.urlsplit(url).hostname
        if host in self.fail:
            hdrs = email.message.Message()
            hdrs["Retry-After"] = "0"
            raise urllib.error.HTTPError(url, self.fail[host], "fail", hdrs, io.BytesIO(b"{}"))
        if url in self.files:
            body = self.files[url]
            return FakeResp(body, "application/pdf" if body.startswith(b"%PDF") else "text/html")
        body = {"api.openalex.org": openalex_json, "api.crossref.org": crossref_json,
                "www.ebi.ac.uk": europepmc_json, "api.semanticscholar.org": s2_json}.get(host)
        if body is None:
            hdrs = email.message.Message()
            raise urllib.error.HTTPError(url, 404, "not found", hdrs, io.BytesIO(b""))
        return FakeResp(json.dumps(body()).encode())


# ---------------------------------------------------------------- 준비

@pytest.fixture(scope="module")
def home(tmp_path_factory):
    from app import db, thesaurus
    prev = os.environ.get("BYORBIT_HOME")
    h = tmp_path_factory.mktemp("byorbit_home_collect")
    os.environ["BYORBIT_HOME"] = str(h)
    thesaurus.invalidate()
    db.init(seed=True)
    yield h
    if prev is None:
        os.environ.pop("BYORBIT_HOME", None)
    else:
        os.environ["BYORBIT_HOME"] = prev
    thesaurus.invalidate()


@pytest.fixture
def fake(home, monkeypatch):
    from app.collect import http
    f = Fake()
    monkeypatch.setattr(http, "MIN_INTERVAL", {"default": 0.0})
    monkeypatch.setattr(http.time, "sleep", lambda s: None)   # 429 재시도 대기 없이
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    http.set_opener(f)
    yield f
    http.set_opener(None)


@pytest.fixture
def clean(home):
    from app import db
    with db.tx() as c:
        c.execute("DELETE FROM collect_item")
        c.execute("DELETE FROM collect_job")
        c.execute("DELETE FROM collect_query")
    yield


# ---------------------------------------------------------------- 출처 파싱

def test_registry_has_foreign_sources(home):
    from app.collect import registry
    s = registry.sources(reload=True)
    for k in ("openalex", "crossref", "europepmc", "semanticscholar"):
        assert k in s and s[k].group == "해외 학술" and s[k].status()["ready"], k
        assert s[k].homepage.startswith("https://") and s[k].terms_url.startswith("https://")
        assert s[k].info()["description"]


def test_openalex_parse(fake):
    from app.collect.sources import openalex
    items = openalex.SOURCE.search(QUERY, limit=5, since_year=2015)
    a, b = items
    assert a.source_id == "W4210766440" and a.doi == DOI_A and a.year == 2022
    assert a.abstract == "Apple pomace was dried. The pomace model fits."
    assert a.oa is True and a.pdf_url.endswith("/pdf") and a.license == "cc-by" and a.venue == "Applied Sciences"
    assert a.authors == ["Weronika Tulej", "Szymon Głowacki"]
    assert b.doi is None and b.pdf_url is None and b.oa is False and b.doc_type == "other"
    url = fake.requests[0][0]
    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert qs["search"] == [QUERY] and qs["filter"] == ["from_publication_date:2015-01-01"] and qs["per_page"] == ["5"]


def test_crossref_parse_conservative_pdf(fake):
    from app.collect.sources import crossref
    a, b = crossref.SOURCE.search(QUERY, limit=2, since_year=2019)
    assert a.doi == DOI_A and a.year == 2022 and a.venue == "Applied Sciences"
    assert a.abstract.startswith("Understanding biological materials") and "<" not in a.abstract
    assert a.license.startswith("https://creativecommons.org") and a.oa is True
    assert a.pdf_url == "https://www.mdpi.com/2076-3417/12/3/1434/pdf"
    # 비공개 라이선스 + 출판사 전용 API 링크 → PDF 넘기지 않음
    assert b.doi == "10.1016/j.foodchem.2019.05.131" and b.pdf_url is None and b.oa is None
    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(fake.requests[0][0]).query)
    assert qs["query"] == [QUERY] and qs["filter"] == ["from-pub-date:2019"]


def test_europepmc_parse(fake):
    from app.collect.sources import europepmc
    a, b = europepmc.SOURCE.search(QUERY, limit=2, since_year=2020)
    assert a.source_id == "MED:33932812" and a.doi == DOI_B and a.oa is False and a.pdf_url is None
    assert a.abstract == "Apple pomace (AP) drying was studied." and a.language == "en"
    assert a.authors == ["Fernandes PAR", "Bastos R"] and a.venue == "Bioresource technology"
    assert b.oa is True and b.pdf_url is None and b.license == "cc by" and b.authors == ["Chiș MS"]
    assert b.extra["fulltext_xml"] == "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC13605857/fullTextXML"
    assert a.extra["fulltext_xml"] is None   # 유료 → 전문 없음
    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(fake.requests[0][0]).query)
    assert qs["query"] == [f"({QUERY}) AND FIRST_PDATE:[2020-01-01 TO 3000-12-31]"] and qs["resultType"] == ["core"]


def test_semanticscholar_parse_and_429(fake):
    from app.collect.base import SourceError
    from app.collect.sources import semanticscholar
    (a,) = semanticscholar.SOURCE.search(QUERY, limit=3, since_year=2018)
    assert a.doi == DOI_B and a.oa is True and a.pdf_url == "https://repo.example.org/ap.pdf" and a.year == 2021
    qs = urllib.parse.parse_qs(urllib.parse.urlsplit(fake.requests[0][0]).query)
    assert qs["query"] == [QUERY] and qs["year"] == ["2018-"]
    fake.fail["api.semanticscholar.org"] = 429
    with pytest.raises(SourceError, match="SEMANTIC_SCHOLAR_API_KEY"):
        semanticscholar.SOURCE.search(QUERY)
    assert sum("semanticscholar" in u for u, _ in fake.requests) == 3   # 성공 1 + 429 뒤 한 번 더 시도


def test_semanticscholar_interval_polite():
    from app.collect import http
    import app.collect.sources.semanticscholar  # noqa: F401
    assert http.MIN_INTERVAL["api.semanticscholar.org"] >= 1.1


def test_norm_doi_and_title_key():
    from app.collect.base import norm_doi, title_key
    assert norm_doi("https://doi.org/10.3390/APP12031434") == DOI_A
    assert norm_doi("doi:10.1016/J.Biortech.2021.125207.") == DOI_B
    assert norm_doi("no doi here") is None and norm_doi(None) is None
    assert title_key("Apple Pomace — Drying!") == title_key("apple pomace drying")


# ---------------------------------------------------------------- 중복·병합

def test_dedupe_merge_across_sources(fake, clean):
    from app import db
    from app.collect import store
    from app.collect.base import Item
    r1 = store.save_items([Item("openalex", "W1", "Microwave drying of apple pomace", doi="10.1/X", year=2021,
                                abstract="short", oa=False)])
    r2 = store.save_items([Item("europepmc", "MED:1", "Microwave Drying of Apple Pomace.", doi="https://doi.org/10.1/x",
                                year=2021, pdf_url="https://e.org/x.pdf", oa=True, license="cc by",
                                abstract="a much longer abstract from Europe PMC that should replace the short one")])
    assert r1["new"] == 1 and r2 == {"found": 1, "new": 0, "dup": 1, "item_ids": r1["item_ids"]}
    it = store.get_item(r1["item_ids"][0])
    assert it["found_in"] == ["openalex", "europepmc"] and it["pdf_url"] == "https://e.org/x.pdf"
    assert it["oa"] is True and it["license"] == "cc by" and it["abstract"].startswith("a much longer")
    assert it["ids"] == {"openalex": "W1", "europepmc": "MED:1"}
    assert db.one("SELECT oa FROM collect_item WHERE item_id=?", (it["item_id"],))["oa"] == 1
    # DOI 없이 같은 제목·같은 연도 → 병합, 연도가 다르면 다른 자료
    r3 = store.save_items([Item("semanticscholar", "s1", "microwave drying of APPLE pomace", year=2021)])
    r4 = store.save_items([Item("semanticscholar", "s2", "Microwave drying of apple pomace", year=2015)])
    assert r3["dup"] == 1 and r4["new"] == 1
    # 같은 출처·같은 ID를 다시 받으면 중복
    assert store.save_items([Item("semanticscholar", "s2", "Changed title", year=2015)])["dup"] == 1
    assert db.one("SELECT COUNT(*) AS n FROM collect_item")["n"] == 2


def test_rejected_stays_rejected_on_rediscovery(fake, clean):
    from app.collect import store
    from app.collect.base import Item
    (iid,) = store.save_items([Item("openalex", "W9", "Rejected paper", doi="10.9/r")])["item_ids"]
    store.set_status(iid, "rejected")
    store.save_items([Item("crossref", "10.9/r", "Rejected paper", doi="10.9/r")])
    assert store.get_item(iid)["status"] == "rejected"
    with pytest.raises(store.CollectError):
        store.set_status(iid, "ingested")


def test_run_search_one_source_fails(fake, clean):
    from app.collect import store
    fake.fail["api.semanticscholar.org"] = 429
    job = store.run_search(QUERY, ["openalex", "crossref", "europepmc", "semanticscholar"], 5, 2015)
    st = job["stats"]["sources"]
    assert job["status"] == "done" and job["finished_at"]
    assert st["semanticscholar"]["status"] == "error" and "SEMANTIC_SCHOLAR_API_KEY" in st["semanticscholar"]["error"]
    assert all(st[k]["status"] == "done" for k in ("openalex", "crossref", "europepmc"))
    assert st["openalex"]["found"] == 2 and st["crossref"]["found"] == 2 and st["europepmc"]["found"] == 2
    tot = job["stats"]["total"]
    assert tot["found"] == 6 and tot["new"] + tot["dup"] == 6 and tot["errors"] == 1
    # DOI_A는 openalex·crossref 두 곳, 나머지는 한 곳씩 → 수집함 5건(제목만 같은 책 포함)
    lst = store.list_items("new", page_size=50)
    assert lst["total"] == 5 and tot["new"] == 5
    a = next(i for i in lst["items"] if i["doi"] == DOI_A)
    assert sorted(a["found_in"]) == ["crossref", "openalex"] and a["abstract"].startswith("Understanding")
    assert "Semantic Scholar" in job["error"]
    # 필터
    assert store.list_items("new", source="crossref")["total"] == 2
    assert store.list_items("new", oa=True)["total"] == 2
    assert store.list_items("new", doc_type="other")["total"] == 1
    assert store.list_items("new", q="Phytochemical")["total"] == 1
    assert store.list_jobs()[0]["job_id"] == job["job_id"]


def test_run_search_all_fail_and_validation(fake, clean):
    from app.collect import store
    fake.fail["api.openalex.org"] = 500
    job = store.run_search(QUERY, ["openalex"], 3)
    assert job["status"] == "error" and "OpenAlex" in job["error"]
    with pytest.raises(store.CollectError, match="알 수 없는 출처"):
        store.run_search(QUERY, ["nope"])
    with pytest.raises(store.CollectError, match="검색어"):
        store.run_search("  ", ["openalex"])


def test_not_ready_source_reports_key_hint(fake, clean, monkeypatch):
    from app.collect import registry, store
    from app.collect.base import Source

    class Keyed(Source):
        key, name, group, needs_env, key_help = "keyed_test", "키 시험", "국내 학술", ("BYO_TEST_KEY_X",), "시험용 키 안내"
    srcs = dict(registry.sources())
    srcs["keyed_test"] = Keyed()
    monkeypatch.setattr(registry, "_cache", srcs)
    monkeypatch.delenv("BYO_TEST_KEY_X", raising=False)
    job = store.run_search(QUERY, ["keyed_test", "openalex"], 3)
    assert job["stats"]["sources"]["keyed_test"]["status"] == "error"
    assert "BYO_TEST_KEY_X" in job["stats"]["sources"]["keyed_test"]["error"]
    assert job["stats"]["sources"]["openalex"]["status"] == "done"


# ---------------------------------------------------------------- 개인정보: 밖으로 나가는 것은 검색어뿐

def test_privacy_only_query_leaves(fake, clean, monkeypatch):
    from app.collect import http, store
    monkeypatch.setenv("BYORBIT_TEST_SECRET_EMAIL", "someone@example.com")
    secret_query = "사과박 동결건조 TDF"
    store.run_search(secret_query, ["openalex", "crossref", "europepmc", "semanticscholar"], 4, 2020)
    assert len(fake.requests) == 4
    allowed_headers = {"user-agent", "accept"}
    for url, headers in fake.requests:
        low = urllib.parse.unquote(url).lower()
        assert "@" not in low and "mailto" not in low and "email" not in low, url
        assert {k.lower() for k in headers} <= allowed_headers, headers
        assert headers.get("User-agent") == http.USER_AGENT and "@" not in http.USER_AGENT
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        free_text = [v for k, vs in qs.items() for v in vs if k in ("search", "query")]
        assert free_text and all(secret_query in v for v in free_text), url
        others = {k: vs for k, vs in qs.items() if k not in ("search", "query")}
        for vs in others.values():   # 나머지 매개변수는 숫자·필드 이름·연도 필터뿐
            assert all(secret_query not in v and "@" not in v for v in vs)


# ---------------------------------------------------------------- 자료함에 넣기

def _seed_items(fake):
    from app.collect import store
    store.run_search(QUERY, ["openalex", "europepmc"], 5)
    return {i["doi"] or i["title"]: i for i in store.list_items("new", page_size=50)["items"]}


def test_ingest_with_pdf(fake, clean):
    from app import db
    from app.collect import store
    items = _seed_items(fake)
    a = items[DOI_A]
    fake.files[a["pdf_url"]] = make_pdf("Modeling apple pomace drying. 사과박 열풍건조 모델.")
    r = store.ingest(a["item_id"], project="수집 시험")
    assert r["pdf"] is True and r["duplicate"] is False and r["doc_id"] and r["chunks"] >= 1
    it = store.get_item(a["item_id"])
    assert it["status"] == "ingested" and it["doc_id"] == r["doc_id"]
    src = db.one("SELECT s.* FROM source s JOIN document d ON d.source_id=s.source_id WHERE d.doc_id=?", (r["doc_id"],))
    assert src["doi"] == DOI_A and src["license"] == "cc-by" and src["year"] == 2022
    assert src["title"].startswith("Modeling") and src["confidentiality"] == "일반" and "Tulej" in src["authors"]
    doc = db.one("SELECT * FROM document WHERE doc_id=?", (r["doc_id"],))
    assert doc["file_name"].endswith(".pdf") and "OpenAlex" in doc["note"] and "오픈 액세스" in doc["note"]
    assert db.one("SELECT 1 AS x FROM project_item pi JOIN project p ON p.project_id=pi.project_id "
                  "WHERE p.name='수집 시험' AND pi.entity_id=?", (r["doc_id"],))
    # 다시 넣으면 그대로 기존 자료
    again = store.ingest(a["item_id"])
    assert again["doc_id"] == r["doc_id"] and again["duplicate"] is True


def test_ingest_without_pdf_writes_markdown(fake, clean):
    from app import db
    from app.collect import store
    items = _seed_items(fake)
    b = items[DOI_B]   # Europe PMC + OpenAlex 아님(가짜 OpenAlex에는 없음) → 유료, PDF 없음
    assert not b["pdf_url"]
    r = store.ingest(b["item_id"], project="수집 시험")
    assert r["pdf"] is False and r["doc_id"]
    doc = db.one("SELECT * FROM document WHERE doc_id=?", (r["doc_id"],))
    assert doc["file_name"].endswith(".md") and "서지·초록만" in doc["note"]
    text = " ".join(x["text"] for x in db.rows("SELECT text FROM chunk WHERE doc_id=?", (r["doc_id"],)))
    assert "Apple pomace (AP) drying was studied." in text and DOI_B in text and "Europe PMC" in text
    src = db.one("SELECT s.doi FROM source s JOIN document d ON d.source_id=s.source_id WHERE d.doc_id=?", (r["doc_id"],))
    assert src["doi"] == DOI_B


JATS = """<?xml version="1.0"?><article><front><article-meta><title-group><article-title>T</article-title></title-group></article-meta></front>
<body><sec><title>1. Introduction</title><p>Apple pomace is a <italic>juice</italic> by-product.</p>
<sec><title>1.1 Drying</title><p>Hot-air drying at 60 °C for 12 h.</p></sec></sec>
<sec><title>2. Results</title><table-wrap><caption><p>Table 1. TDF of dried pomace.</p></caption></table-wrap>
<p>TDF was 45 g/100 g.</p></sec></body><back><ref-list><ref>Should not appear</ref></ref-list></back></article>"""


def test_fulltext_from_xml():
    from app.collect import store
    t = store.fulltext_from_xml(JATS)
    assert "### 1. Introduction" in t and "#### 1.1 Drying" in t and "Apple pomace is a juice by-product." in t
    assert "Table 1. TDF of dried pomace." in t and "Should not appear" not in t
    assert store.fulltext_from_xml("<not xml") is None and store.fulltext_from_xml("<article/>") is None


def test_ingest_open_access_fulltext(fake, clean):
    from app import db
    from app.collect import store
    items = _seed_items(fake)
    oa = items["10.3390/foods15183244"]
    assert not oa["pdf_url"] and oa["extra"]["fulltext_xml"]
    fake.files[oa["extra"]["fulltext_xml"]] = JATS.encode()
    r = store.ingest(oa["item_id"])
    assert r["fulltext"] is True and r["pdf"] is False and "전문" in r["message"]
    text = " ".join(x["text"] for x in db.rows("SELECT text FROM chunk WHERE doc_id=?", (r["doc_id"],)))
    assert "TDF was 45 g/100 g." in text and "Apple pomace phenolics." in text
    assert "오픈 액세스 전문" in db.one("SELECT note FROM document WHERE doc_id=?", (r["doc_id"],))["note"]


def test_fulltext_only_from_official_host(fake, clean):
    from app.collect import store
    from app.collect.base import Item
    (iid,) = store.save_items([Item("openalex", "Wx", "Odd", extra={"fulltext_xml": "https://evil.example/x.xml"})])["item_ids"]
    fake.files["https://evil.example/x.xml"] = JATS.encode()
    r = store.ingest(iid)
    assert r["fulltext"] is False and not any("evil.example" in u for u, _ in fake.requests)


def test_ingest_pdf_not_pdf_falls_back(fake, clean):
    from app import db
    from app.collect import store
    items = _seed_items(fake)
    a = items[DOI_A]
    fake.files[a["pdf_url"]] = b"<html>login</html>"
    r = store.ingest(a["item_id"])
    assert r["pdf"] is False and "PDF는 받지 못함" in r["message"]
    doc = db.one("SELECT note FROM document WHERE doc_id=?", (r["doc_id"],))
    assert "원문 PDF를 받지 못해" in doc["note"]


def test_ingest_duplicate_links_existing(fake, clean):
    from app.collect import store
    from app.collect.base import Item
    pdf = make_pdf("Same bytes for two catalogue records.")
    ids = store.save_items([Item("openalex", "Wd1", "Record one", doi="10.5/one", pdf_url="https://x.org/1.pdf", oa=True),
                            Item("crossref", "10.5/two", "Record two", doi="10.5/two", pdf_url="https://x.org/2.pdf", oa=True)])["item_ids"]
    fake.files["https://x.org/1.pdf"] = pdf
    fake.files["https://x.org/2.pdf"] = pdf
    r1 = store.ingest(ids[0])
    r2 = store.ingest(ids[1])
    assert r2["duplicate"] is True and r2["doc_id"] == r1["doc_id"]
    assert store.get_item(ids[1])["status"] == "ingested"


def test_bulk_actions(fake, clean):
    from app.collect import store
    ids = [i["item_id"] for i in _seed_items(fake).values()]
    r = store.bulk(ids[:2], "reject")
    assert r["done"] == 2 and store.get_item(ids[0])["status"] == "rejected"
    r = store.bulk(ids[2:3] + ["missing"], "later")
    assert r["done"] == 1 and r["failed"] == 1 and store.get_item(ids[2])["status"] == "accepted"
    with pytest.raises(store.CollectError):
        store.bulk(ids, "explode")


# ---------------------------------------------------------------- 저장 검색·자동 실행

def test_saved_query_crud(fake, clean):
    from app.collect import store
    q = store.save_query({"name": "사과박", "query": QUERY, "sources": ["openalex", "crossref"], "auto": True,
                          "interval_h": 24, "since_year": 2018, "limit_per_source": 7})
    assert q["auto"] is True and q["sources"] == ["openalex", "crossref"] and q["since_year"] == 2018
    assert q["limit_per_source"] == 7 and q["next_run_at"]
    q2 = store.save_query({"query_id": q["query_id"], "auto": False, "interval_h": 48})
    assert q2["auto"] is False and q2["interval_h"] == 48 and q2["query"] == QUERY and q2["since_year"] == 2018
    assert [x["query_id"] for x in store.list_queries()] == [q["query_id"]]
    with pytest.raises(store.CollectError):
        store.save_query({"query": "", "sources": ["openalex"]})
    with pytest.raises(store.CollectError):
        store.save_query({"query": "x", "sources": []})
    store.delete_query(q["query_id"])
    assert store.list_queries() == []


def test_scheduler_fake_clock(fake, clean):
    from app.collect import scheduler, store
    t0 = store.utcnow().replace(second=0, microsecond=0) + timedelta(minutes=1)  # 실제 시각 기준(날짜 고정 금지)
    q = store.save_query({"name": "자동", "query": QUERY, "sources": ["openalex"], "auto": True, "interval_h": 24})
    manual = store.save_query({"name": "수동", "query": "x", "sources": ["openalex"], "auto": False})
    ran = scheduler.tick(now=t0 + timedelta(minutes=1))
    assert [r["query_id"] for r in ran] == [q["query_id"]] and ran[0]["status"] == "done"
    got = store.get_query(q["query_id"])
    assert got["last_run_at"] == store._ts(t0 + timedelta(minutes=1))
    assert got["next_run_at"] == store._ts(t0 + timedelta(minutes=1, hours=24))
    assert store.list_items("new", query_id=q["query_id"])["total"] == 2
    qs = {x["query_id"]: x for x in store.list_queries()}
    assert qs[q["query_id"]]["last_job"]["status"] == "done" and "last_job" not in qs[manual["query_id"]]
    assert scheduler.tick(now=t0 + timedelta(hours=10)) == []           # 아직 간격 전
    assert len(scheduler.tick(now=t0 + timedelta(hours=24, minutes=2))) == 1
    # 일시 정지
    scheduler.set_paused(True)
    try:
        assert scheduler.tick(now=t0 + timedelta(days=5)) == []
        assert scheduler.status()["paused"] is True
    finally:
        scheduler.set_paused(False)
    # 같은 저장 검색이 이미 실행 중이면 건너뛴다(동시 실행 금지), 수동 실행도 막힌다
    store.begin_query(q["query_id"])
    try:
        r = scheduler.tick(now=t0 + timedelta(days=9))
        assert r == []                                                  # due_queries가 실행 중인 것을 뺀다
        with pytest.raises(store.Busy):
            store.begin_query(q["query_id"])
    finally:
        store.finish_query(q["query_id"])
    assert manual["query_id"] not in [r["query_id"] for r in scheduler.tick(now=t0 + timedelta(days=30))]


def test_scheduler_failure_does_not_block_others(fake, clean):
    from app.collect import scheduler, store
    t0 = store.utcnow().replace(second=0, microsecond=0) + timedelta(minutes=1)  # 실제 시각 기준(날짜 고정 금지)
    a = store.save_query({"name": "a", "query": "a", "sources": ["openalex"], "auto": True})
    b = store.save_query({"name": "b", "query": "b", "sources": ["openalex"], "auto": True})
    calls = []

    def run(qid, begun):
        calls.append(qid)
        if qid == a["query_id"]:
            raise RuntimeError("boom")
        return {"status": "done"}
    out = scheduler.tick(now=t0, run=run)
    assert sorted(calls) == sorted([a["query_id"], b["query_id"]])
    assert {r["status"] for r in out} == {"error", "done"}
    assert not store._running_queries


def test_scheduler_thread_start_stop(home, monkeypatch):
    from app.collect import scheduler
    monkeypatch.setattr(scheduler, "FIRST_DELAY_SEC", 3600)
    monkeypatch.setenv("BYORBIT_COLLECT_SCHEDULER", "1")
    assert scheduler.start() is True and scheduler.status()["running"] is True
    scheduler.stop()
    assert scheduler.status()["running"] is False
    monkeypatch.setenv("BYORBIT_COLLECT_SCHEDULER", "0")
    assert scheduler.start() is False


# ---------------------------------------------------------------- API 경로

@pytest.fixture
def client(fake, clean):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app import routes_collect
    app = FastAPI()
    app.include_router(routes_collect.router)
    return TestClient(app)


def _wait_job(client, jid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        j = client.get(f"/api/collect/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("작업이 끝나지 않음")


def test_api_flow(client, fake):
    s = client.get("/api/collect/sources").json()
    keys = [x["key"] for x in s["sources"]]
    assert {"openalex", "crossref", "europepmc", "semanticscholar"} <= set(keys)
    assert s["groups"][0] == "해외 학술" and "검색어" in s["notice"]
    assert all("ready" in x and "missing_env" in x and "key_help" in x for x in s["sources"])

    assert client.post("/api/collect/search", json={"query": " ", "sources": ["openalex"]}).status_code == 400
    assert "알 수 없는 출처" in client.post("/api/collect/search", json={"query": "x", "sources": ["zz"]}).json()["detail"]
    j = client.post("/api/collect/search", json={"query": QUERY, "sources": ["openalex", "europepmc"],
                                                 "limit_per_source": 5, "since_year": 2015}).json()
    assert j["status"] == "running" and set(j["stats"]) <= {"sources", "total", "params"}
    j = _wait_job(client, j["job_id"])
    assert j["status"] == "done" and j["stats"]["total"]["found"] == 4
    assert client.get("/api/collect/jobs").json()["jobs"][0]["job_id"] == j["job_id"]
    assert client.get("/api/collect/jobs/nope").status_code == 404

    lst = client.get("/api/collect/items", params={"status": "new"}).json()
    assert lst["total"] == 4 and lst["counts"]["new"] == 4
    ids = [i["item_id"] for i in lst["items"]]
    assert client.get("/api/collect/items", params={"status": "bogus"}).status_code == 400
    assert client.post(f"/api/collect/items/{ids[0]}/status", json={"status": "rejected"}).json()["status"] == "rejected"
    assert client.post(f"/api/collect/items/{ids[0]}/status", json={"status": "ingested"}).status_code == 400
    assert client.post("/api/collect/items/nope/status", json={"status": "new"}).status_code == 404
    r = client.post("/api/collect/items/bulk", json={"ids": ids[1:3], "action": "later"}).json()
    assert r["done"] == 2
    r = client.post(f"/api/collect/items/{ids[3]}/ingest", json={"project": "API 시험"}).json()
    assert r["doc_id"] and r["pdf"] is False
    assert client.get(f"/api/collect/items/{ids[3]}").json()["status"] == "ingested"
    b = client.post("/api/collect/items/bulk", json={"ids": ids[1:3], "action": "ingest", "project": "API 시험"}).json()
    assert b["background"] is True
    jb = _wait_job(client, b["job_id"])
    assert jb["kind"] == "ingest" and jb["stats"]["done"] == 2 and jb["status"] == "done"
    assert client.get("/api/collect/items", params={"status": "ingested"}).json()["total"] == 3
    assert client.post("/api/collect/items/bulk", json={"ids": [], "action": "reject"}).status_code == 400


def test_api_queries(client, fake):
    q = client.post("/api/collect/queries", json={"name": "저장", "query": QUERY, "sources": ["openalex"],
                                                  "auto": True, "interval_h": 12}).json()
    assert q["query_id"] and q["auto"] is True and q["interval_h"] == 12
    lst = client.get("/api/collect/queries").json()
    assert lst["queries"][0]["query_id"] == q["query_id"] and "paused" in lst["scheduler"]
    u = client.post("/api/collect/queries", json={"query_id": q["query_id"], "auto": False}).json()
    assert u["auto"] is False and u["interval_h"] == 12
    assert client.post("/api/collect/queries", json={"query": "x", "sources": ["zz"]}).status_code == 400
    j = client.post(f"/api/collect/queries/{q['query_id']}/run").json()
    j = _wait_job(client, j["job_id"])
    assert j["status"] == "done" and j["query_id"] == q["query_id"]
    assert client.get("/api/collect/queries").json()["queries"][0]["last_run_at"]
    assert client.post("/api/collect/queries/nope/run").status_code == 404
    assert client.post("/api/collect/scheduler", json={"paused": True}).json()["paused"] is True
    assert client.post("/api/collect/scheduler", json={"paused": False}).json()["paused"] is False
    assert client.delete(f"/api/collect/queries/{q['query_id']}").json()["ok"] is True
    assert client.delete(f"/api/collect/queries/{q['query_id']}").status_code == 404


def test_api_query_run_busy(client, fake):
    from app.collect import store
    q = client.post("/api/collect/queries", json={"query": QUERY, "sources": ["openalex"]}).json()
    store.begin_query(q["query_id"])
    try:
        r = client.post(f"/api/collect/queries/{q['query_id']}/run")
        assert r.status_code == 409 and "이미 실행 중" in r.json()["detail"]
    finally:
        store.finish_query(q["query_id"])


def test_api_sites_crawler_missing(client, monkeypatch):
    monkeypatch.setitem(sys.modules, "app.collect.crawler", None)   # import 시 ImportError
    r = client.get("/api/collect/sites")
    assert r.status_code == 503 and "크롤러 준비 중" in r.json()["detail"]
    assert client.post("/api/collect/sites/x/check").status_code == 503


def test_api_sites_delegate(client, monkeypatch):
    import types
    calls = []
    fake_mod = types.ModuleType("app.collect.crawler")
    sites = [{"id": "s1", "name": "시험 사이트", "enabled": True, "default": True}]
    fake_mod.list_sites = lambda: sites
    fake_mod.save_site = lambda s: (calls.append(("save", s)), {**s, "id": s.get("id") or "new1"})[1]

    def delete_site(sid):
        if sid != "s1":
            raise KeyError(sid)
        calls.append(("del", sid))
    fake_mod.delete_site = delete_site
    fake_mod.check_site = lambda sid: {"robots_ok": True, "terms_url": None, "message": "허용"}
    monkeypatch.setitem(sys.modules, "app.collect.crawler", fake_mod)
    assert client.get("/api/collect/sites").json()["sites"] == sites
    assert client.post("/api/collect/sites", json={"name": "새 사이트", "start_urls": ["https://e.org"]}).json()["id"] == "new1"
    assert client.delete("/api/collect/sites/s1").json()["ok"] is True
    assert client.delete("/api/collect/sites/zz").status_code == 404
    assert client.post("/api/collect/sites/s1/check").json()["robots_ok"] is True
    assert ("del", "s1") in calls
