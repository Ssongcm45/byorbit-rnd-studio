"""수집함 저장소 — 검색 실행(출처별 병렬), 중복 판정·병합, 검토 상태, 자료함 투입, 저장 검색.

흐름: run_search → 출처마다 search() → save_items(중복이면 기존 행에 정보 병합) → collect_item(status=new)
      → 사용자가 검토(accepted=보관 / rejected=거절) → ingest()로 자료함(pipeline.ingest_file)에 넣는다.

중복 판정 순서: DOI → (출처, 출처 ID) → 제목 열쇠(base.title_key; 두 쪽 모두 연도가 있으면 연도도 같아야 함).
밖으로 나가는 것은 검색어뿐이다(출처 모듈이 http 모듈로만 호출). 이 모듈은 DB와 로컬 파일만 다룬다.
"""
from __future__ import annotations

import json
import re
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import db
from . import http, registry
from .base import Item, MissingKey, SourceError, norm_doi, title_key

STATUSES = ("new", "accepted", "rejected", "ingested")
REVIEW_STATUSES = ("new", "accepted", "rejected")   # 사용자가 직접 고를 수 있는 상태(ingested는 ingest()만)
MAX_WORKERS = 4
MAX_LIMIT = 100
PAGE_SIZE = 30
SQL_TS = "%Y-%m-%d %H:%M:%S"                       # SQLite datetime('now')와 같은 형식(UTC)

_running_queries: set[str] = set()                  # 같은 저장 검색이 동시에 두 번 돌지 않게
_run_lock = threading.Lock()


class CollectError(Exception):
    """사용자에게 그대로 보여 줄 한국어 메시지(무엇을 하면 되는지 포함)."""


class Busy(CollectError):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _ts(dt: datetime | None = None) -> str:
    return (dt or utcnow()).strftime(SQL_TS)


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s[:19].replace("T", " "), SQL_TS)
    except ValueError:
        return None


# ---------------------------------------------------------------- 작업 기록(collect_job)

def create_job(kind: str, query: str | None = None, sources: list[str] | None = None,
               query_id: str | None = None, stats: dict | None = None) -> str:
    jid = db.new_id()[:16]
    with db.tx() as c:
        c.execute("INSERT INTO collect_job(job_id, kind, query_id, query, sources_json, status, stats_json, started_at) "
                  "VALUES (?,?,?,?,?, 'running', ?, ?)",
                  (jid, kind, query_id, query, json.dumps(sources or [], ensure_ascii=False),
                   json.dumps(stats or {}, ensure_ascii=False), _ts()))
    return jid


def _update_job(jid: str, stats: dict | None = None, status: str | None = None, error: str | None = None) -> None:
    sets, args = [], []
    if stats is not None:
        sets.append("stats_json=?")
        args.append(json.dumps(stats, ensure_ascii=False))
    if status is not None:
        sets.append("status=?")
        args.append(status)
        if status != "running":
            sets.append("finished_at=?")
            args.append(_ts())
    if error is not None:
        sets.append("error=?")
        args.append(error)
    if sets:
        with db.tx() as c:
            c.execute(f"UPDATE collect_job SET {', '.join(sets)} WHERE job_id=?", (*args, jid))


def _job_out(r: dict | None) -> dict | None:
    if not r:
        return None
    r = dict(r)
    r["sources"] = json.loads(r.pop("sources_json") or "[]")
    r["stats"] = json.loads(r.pop("stats_json") or "{}")
    return r


def get_job(jid: str) -> dict | None:
    return _job_out(db.one("SELECT * FROM collect_job WHERE job_id=?", (jid,)))


def list_jobs(limit: int = 20, query_id: str | None = None) -> list[dict]:
    if query_id:
        rs = db.rows("SELECT * FROM collect_job WHERE query_id=? ORDER BY started_at DESC, rowid DESC LIMIT ?",
                     (query_id, limit))
    else:
        rs = db.rows("SELECT * FROM collect_job ORDER BY started_at DESC, rowid DESC LIMIT ?", (limit,))
    return [_job_out(r) for r in rs]


def mark_interrupted() -> int:
    """앱이 꺼지며 끝나지 못한 작업 → error(중단됨). 서버 시작 때 부른다."""
    with db.tx() as c:
        n = c.execute("UPDATE collect_job SET status='error', error=COALESCE(error, '앱이 꺼져 중단되었습니다. 다시 실행하세요.'), "
                      "finished_at=? WHERE status='running'", (_ts(),)).rowcount
    return n


# ---------------------------------------------------------------- 검색

def validate_sources(sources: list[str]) -> list[str]:
    known = registry.sources()
    sources = [s for s in dict.fromkeys(sources or []) if s]
    if not sources:
        raise CollectError("출처를 하나 이상 고르세요.")
    bad = [s for s in sources if s not in known]
    if bad:
        raise CollectError(f"알 수 없는 출처: {', '.join(bad)}. 사용 가능: {', '.join(sorted(known))}")
    return sources


def _search_one(key: str, query: str, limit: int, since_year: int | None) -> list[Item]:
    src = registry.get(key)
    st = src.status()
    if not st.get("ready"):
        raise MissingKey(st.get("message") or f"{src.name}: 사용할 준비가 되지 않았습니다.")
    return list(src.search(query, limit=limit, since_year=since_year) or [])


def _err_text(key: str, e: Exception) -> str:
    if isinstance(e, (SourceError, MissingKey)):
        return str(e)
    if isinstance(e, http.HttpError):
        return f"{e}. 잠시 뒤 다시 시도하세요."
    name = getattr(registry.sources().get(key), "name", key)
    return f"{name} 처리 중 오류: {e}. 같은 검색을 다시 해 보고, 계속되면 이 출처를 빼고 검색하세요."


def run_search(query: str, sources: list[str], limit_per_source: int = 20, since_year: int | None = None,
               project: str | None = None, query_id: str | None = None, job_id: str | None = None) -> dict:
    """출처마다 병렬로 검색하고 수집함에 저장한다. 한 출처의 실패는 그 출처만 error로 남긴다.

    반환: 작업 dict(get_job과 같은 모양). stats = {"sources": {key: {status, found, new, dup, error}},
    "total": {found, new, dup, errors}, "params": {...}}"""
    query = (query or "").strip()
    if not query:
        raise CollectError("검색어를 입력하세요.")
    sources = validate_sources(sources)
    limit = max(1, min(int(limit_per_source or 20), MAX_LIMIT))
    since_year = int(since_year) if since_year else None
    stats = {"sources": {k: {"status": "running", "found": 0, "new": 0, "dup": 0, "error": None} for k in sources},
             "total": {"found": 0, "new": 0, "dup": 0, "errors": 0},
             "params": {"limit_per_source": limit, "since_year": since_year, "project": project}}
    if job_id:
        _update_job(job_id, stats=stats)
    else:
        job_id = create_job("search", query, sources, query_id, stats)

    try:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(sources))) as ex:
            futs = {ex.submit(_search_one, k, query, limit, since_year): k for k in sources}
            for f in as_completed(futs):
                k = futs[f]
                s = stats["sources"][k]
                try:
                    items = f.result()
                    r = save_items(items, query_id)
                    s.update(status="done", found=r["found"], new=r["new"], dup=r["dup"])
                except Exception as e:  # noqa: BLE001 — 출처 하나가 실패해도 나머지는 계속
                    s.update(status="error", error=_err_text(k, e))
                tot = stats["total"]
                tot.update(found=sum(x["found"] for x in stats["sources"].values()),
                           new=sum(x["new"] for x in stats["sources"].values()),
                           dup=sum(x["dup"] for x in stats["sources"].values()),
                           errors=sum(1 for x in stats["sources"].values() if x["status"] == "error"))
                _update_job(job_id, stats=stats)
    except Exception as e:  # noqa: BLE001
        _update_job(job_id, stats=stats, status="error", error=f"검색을 마치지 못했습니다: {e}")
        return get_job(job_id)
    errs = [f"{registry.sources()[k].name}: {v['error']}" for k, v in stats["sources"].items() if v["status"] == "error"]
    all_failed = len(errs) == len(sources)
    _update_job(job_id, stats=stats, status="error" if all_failed else "done",
                error=("\n".join(errs) if errs else None))
    return get_job(job_id)


# ---------------------------------------------------------------- 저장·중복 병합

MERGE_FIELDS = ("doi", "abstract", "pdf_url", "url", "venue", "year", "license", "language")


def _find_existing(c, it: Item) -> dict | None:
    if it.doi:
        r = c.execute("SELECT * FROM collect_item WHERE doi=? LIMIT 1", (it.doi,)).fetchone()
        if r:
            return dict(r)
    r = c.execute("SELECT * FROM collect_item WHERE source=? AND source_id=?", (it.source, it.source_id)).fetchone()
    if r:
        return dict(r)
    tk = title_key(it.title)
    for r in c.execute("SELECT * FROM collect_item WHERE title_key=?", (tk,)).fetchall():
        r = dict(r)
        if it.year and r["year"] and int(it.year) != int(r["year"]):
            continue
        if it.doi and r["doi"] and it.doi != r["doi"]:
            continue
        return r
    return None


def _merge(old: dict, it: Item) -> dict:
    new = dict(old)
    d = it.to_dict()
    for k in MERGE_FIELDS:
        if not new.get(k) and d.get(k):
            new[k] = d[k]
    if not new.get("authors") and d.get("authors"):
        new["authors"] = d["authors"]
    if it.oa is True:
        new["oa"] = True
    elif new.get("oa") is None:
        new["oa"] = it.oa
    if (it.abstract or "") and len(it.abstract) > len(new.get("abstract") or "") * 1.5:
        new["abstract"] = it.abstract        # 훨씬 긴 초록(잘린 초록 대체)
    found = list(new.get("found_in") or [old.get("source")])
    if it.source not in found:
        found.append(it.source)
    new["found_in"] = found
    ids = dict(new.get("ids") or {})
    ids.setdefault(it.source, it.source_id)
    new["ids"] = ids
    links = dict(new.get("links") or {})
    if it.url:
        links.setdefault(it.source, it.url)
    new["links"] = links
    if it.pdf_url:
        pdfs = dict(new.get("pdf_urls") or {})
        pdfs.setdefault(it.source, it.pdf_url)
        new["pdf_urls"] = pdfs
    extra = dict(new.get("extra") or {})
    for k, v in (it.extra or {}).items():
        if v is not None:
            extra.setdefault(k, v)
    new["extra"] = extra
    return new


def save_items(items: list[Item], query_id: str | None = None) -> dict:
    """수집 결과를 수집함에 넣는다. 반환: {"found", "new", "dup", "item_ids"}"""
    found = new = dup = 0
    ids: list[str] = []
    with db.tx() as c:
        for it in items:
            if not isinstance(it, Item):
                continue
            it.normalized()
            found += 1
            old = _find_existing(c, it)
            if old:
                data = _merge(json.loads(old["item_json"]), it)
                c.execute("UPDATE collect_item SET item_json=?, doi=COALESCE(doi, ?), year=COALESCE(year, ?), oa=? "
                          "WHERE item_id=?",
                          (json.dumps(data, ensure_ascii=False), data.get("doi"), data.get("year"),
                           None if data.get("oa") is None else int(bool(data["oa"])), old["item_id"]))
                dup += 1
                ids.append(old["item_id"])
                continue
            data = it.to_dict()
            data["found_in"] = [it.source]
            data["ids"] = {it.source: it.source_id}
            data["links"] = {it.source: it.url} if it.url else {}
            data["pdf_urls"] = {it.source: it.pdf_url} if it.pdf_url else {}
            iid = db.new_id()
            c.execute("INSERT INTO collect_item(item_id, source, source_id, doi, title, title_key, year, doc_type, "
                      "item_json, oa, status, query_id, first_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?, 'new', ?, ?)",
                      (iid, it.source, it.source_id, it.doi, it.title, title_key(it.title), it.year, it.doc_type,
                       json.dumps(data, ensure_ascii=False), None if it.oa is None else int(bool(it.oa)),
                       query_id, _ts()))
            new += 1
            ids.append(iid)
    return {"found": found, "new": new, "dup": dup, "item_ids": ids}


# ---------------------------------------------------------------- 수집함 조회·검토

def _item_out(r: dict) -> dict:
    d = json.loads(r["item_json"])
    d.update(item_id=r["item_id"], status=r["status"], doc_id=r["doc_id"], query_id=r["query_id"],
             first_seen_at=r["first_seen_at"], source=r["source"], source_id=r["source_id"])
    d.setdefault("found_in", [r["source"]])
    return d


def get_item(item_id: str) -> dict | None:
    r = db.one("SELECT * FROM collect_item WHERE item_id=?", (item_id,))
    return _item_out(r) if r else None


def list_items(status: str | None = "new", q: str | None = None, source: str | None = None,
               doc_type: str | None = None, oa: bool | None = None, page: int = 1,
               page_size: int = PAGE_SIZE, query_id: str | None = None) -> dict:
    where, args = [], []
    if status and status != "all":
        if status not in STATUSES:
            raise CollectError(f"상태는 {', '.join(STATUSES)} 중 하나입니다.")
        where.append("status=?")
        args.append(status)
    if q:
        where.append("(title LIKE ? OR item_json LIKE ?)")
        args += [f"%{q}%", f"%{q}%"]
    if source:
        where.append("(source=? OR EXISTS (SELECT 1 FROM json_each(item_json, '$.found_in') WHERE value=?))")
        args += [source, source]
    if doc_type:
        where.append("doc_type=?")
        args.append(doc_type)
    if oa:
        where.append("(oa=1 OR json_extract(item_json, '$.pdf_url') IS NOT NULL)")
    if query_id:
        where.append("query_id=?")
        args.append(query_id)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    page_size = max(1, min(int(page_size), 200))
    page = max(1, int(page))
    total = db.one(f"SELECT COUNT(*) AS n FROM collect_item {w}", args)["n"]
    rs = db.rows(f"SELECT * FROM collect_item {w} ORDER BY first_seen_at DESC, (year IS NULL), year DESC, rowid DESC "
                 f"LIMIT ? OFFSET ?", (*args, page_size, (page - 1) * page_size))
    counts = {s: 0 for s in STATUSES}
    for r in db.rows("SELECT status, COUNT(*) AS n FROM collect_item GROUP BY status"):
        counts[r["status"]] = r["n"]
    return {"items": [_item_out(r) for r in rs], "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size)), "counts": counts}


def set_status(item_id: str, status: str) -> dict:
    if status not in REVIEW_STATUSES:
        raise CollectError("상태는 new(새 항목)·accepted(보관)·rejected(거절) 중 하나입니다. "
                           "자료함에 넣으려면 '자료함에 넣기'를 쓰세요.")
    r = db.one("SELECT status FROM collect_item WHERE item_id=?", (item_id,))
    if not r:
        raise KeyError(item_id)
    if r["status"] == "ingested":
        raise CollectError("이미 자료함에 넣은 항목입니다. 자료함에서 지운 뒤 상태를 바꾸세요.")
    with db.tx() as c:
        c.execute("UPDATE collect_item SET status=? WHERE item_id=?", (status, item_id))
    return get_item(item_id)


# ---------------------------------------------------------------- 자료함에 넣기

def _file_stem(title: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", title or "").strip()
    s = re.sub(r"\s+", " ", s)[:80].rstrip(" .")
    return s or "수집 자료"


def _source_name(key: str) -> str:
    s = registry.sources().get(key)
    return s.name if s else key


FULLTEXT_PREFIX = "https://www.ebi.ac.uk/europepmc/webservices/rest/"   # 공식 전문 XML(오픈 액세스)만
FULLTEXT_MAX_CHARS = 400_000


def fulltext_from_xml(xml: str) -> str | None:
    """JATS 전문 XML → 제목(###)과 문단만 남긴 글. 표·그림 설명은 문단으로, 참고문헌은 뺀다."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None
    body = root.find(".//body")
    if body is None:
        return None
    out: list[str] = []

    def walk(el, depth=0):
        for ch in el:
            tag = ch.tag.split("}")[-1]
            if tag == "sec":
                t = ch.find("title")
                if t is not None and "".join(t.itertext()).strip():
                    out.append(f"{'#' * min(3 + depth, 6)} {clean(''.join(t.itertext()))}")
                walk(ch, depth + 1)
            elif tag in ("p", "caption"):
                txt = clean("".join(ch.itertext()))
                if txt:
                    out.append(txt)
            elif tag in ("fig", "table-wrap", "list", "boxed-text", "disp-quote"):
                walk(ch, depth)
            elif tag == "list-item":
                txt = clean("".join(ch.itertext()))
                if txt:
                    out.append("- " + txt)

    def clean(t):
        return re.sub(r"\s+", " ", t).strip()
    walk(body)
    text = "\n\n".join(out).strip()
    return text[:FULLTEXT_MAX_CHARS] or None


def _fetch_fulltext(d: dict) -> tuple[str | None, str | None]:
    url = (d.get("extra") or {}).get("fulltext_xml")
    if not url or not str(url).startswith(FULLTEXT_PREFIX):
        return None, None
    try:
        text = fulltext_from_xml(http.get_text(url, timeout=60))
    except Exception as e:  # noqa: BLE001
        return None, f"오픈 액세스 전문을 받지 못했습니다({e})"
    return text, (None if text else "오픈 액세스 전문 XML에서 본문을 찾지 못했습니다")


def to_markdown(d: dict, note: str | None = None, fulltext: str | None = None) -> str:
    """서지·초록 .md — 유료 원문이거나 PDF를 받지 못했을 때 자료함에 넣는 내용."""
    lines = [f"# {d.get('title') or '(제목 없음)'}", ""]
    if d.get("authors"):
        a = d["authors"]
        lines.append(f"- 저자: {', '.join(a[:20])}{' 외' if len(a) > 20 else ''}")
    if d.get("venue") or d.get("year"):
        lines.append(f"- 발행: {' · '.join(str(x) for x in (d.get('venue'), d.get('year')) if x)}")
    if d.get("doi"):
        lines.append(f"- DOI: [{d['doi']}](https://doi.org/{d['doi']})")
    if d.get("url"):
        lines.append(f"- 원문 페이지: {d['url']}")
    lines.append(f"- 수집 출처: {', '.join(_source_name(s) for s in d.get('found_in') or [d.get('source')])}")
    if d.get("license"):
        lines.append(f"- 라이선스: {d['license']}")
    lines.append(f"- 오픈 액세스: {'예' if d.get('oa') else ('아니오' if d.get('oa') is False else '모름')}")
    lines.append(f"- 수집일: {utcnow().strftime('%Y-%m-%d')}")
    if note:
        lines.append(f"- 메모: {note}")
    lines += ["", "## 초록", "", d.get("abstract") or "(출처가 초록을 제공하지 않았습니다. 원문 페이지에서 확인하세요.)", ""]
    if fulltext:
        lines += ["## 본문 (오픈 액세스 전문)", "", fulltext, ""]
    return "\n".join(lines)


def _pdf_candidates(d: dict) -> list[str]:
    out = []
    for u in [d.get("pdf_url"), *(d.get("pdf_urls") or {}).values()]:
        if u and u not in out:
            out.append(u)
    return out


def _record_meta(doc_id: str, d: dict, note: str) -> None:
    lic = d.get("license")
    authors = ", ".join((d.get("authors") or [])[:30]) or None
    with db.tx() as c:
        c.execute("UPDATE source SET doi=COALESCE(doi, ?), license=COALESCE(license, ?), "
                  "title=COALESCE(?, title), year=COALESCE(year, ?), authors=COALESCE(authors, ?) "
                  "WHERE source_id=(SELECT source_id FROM document WHERE doc_id=?)",
                  (d.get("doi"), lic, d.get("title"), d.get("year"), authors, doc_id))
        c.execute("UPDATE document SET note = COALESCE(note || char(10), '') || ? WHERE doc_id=?", (note, doc_id))


def ingest(item_id: str, project: str | None = None, confidentiality: str = "일반") -> dict:
    """수집함 항목 → 자료함. 오픈 액세스 PDF가 있으면 받아서, 없거나 못 받으면 서지·초록 .md로 넣는다.

    반환: {"item_id", "doc_id", "pdf": bool, "duplicate": bool, "message", "chunks"}"""
    from ..ingest import pipeline   # 늦게 불러온다(가벼운 import 유지)
    r = db.one("SELECT * FROM collect_item WHERE item_id=?", (item_id,))
    if not r:
        raise KeyError(item_id)
    if confidentiality not in ("일반", "내부", "기밀"):
        raise CollectError("보안 등급은 일반·내부·기밀 중 하나입니다.")
    if r["status"] == "ingested" and r["doc_id"] and db.one("SELECT 1 AS x FROM document WHERE doc_id=?", (r["doc_id"],)):
        return {"item_id": item_id, "doc_id": r["doc_id"], "pdf": None, "duplicate": True,
                "message": "이미 자료함에 있습니다."}
    d = _item_out(r)
    src_names = ", ".join(_source_name(s) for s in d.get("found_in") or [d["source"]])
    pdf_note = None
    with tempfile.TemporaryDirectory(prefix="byorbit-collect-") as tmp:
        stem = _file_stem(d.get("title"))
        path, got_pdf = None, False
        for u in _pdf_candidates(d):
            try:
                path = http.download(u, Path(tmp) / f"{stem}.pdf")
                got_pdf = True
                break
            except Exception as e:  # noqa: BLE001 — PDF를 못 받으면 서지·초록으로 넣는다
                pdf_note = f"원문 PDF를 받지 못해 서지·초록만 넣었습니다({e})"
        fulltext = None
        if not got_pdf:
            fulltext, ft_note = _fetch_fulltext(d)
            if fulltext:
                pdf_note = None
            elif ft_note and not pdf_note:
                pdf_note = ft_note
            path = Path(tmp) / f"{stem}.md"
            path.write_text(to_markdown(d, pdf_note, fulltext), encoding="utf-8")
        authors = ", ".join((d.get("authors") or [])[:30]) or None
        dup = False
        try:
            res = pipeline.ingest_file(path, project=project, confidentiality=confidentiality,
                                       title=d.get("title"), year=d.get("year"), authors=authors)
            doc_id = res["doc_id"]
        except pipeline.Duplicate as e:
            doc_id, dup, res = e.doc_id, True, {}
    meta = (f"수집: {src_names}" + (f" · DOI {d['doi']}" if d.get("doi") else "") +
            (f" · {d['url']}" if d.get("url") else "") + (f" · 라이선스 {d['license']}" if d.get("license") else "") +
            (" · 원문 PDF(오픈 액세스)" if got_pdf else (" · 오픈 액세스 전문(XML→글)" if fulltext else " · 서지·초록만")))
    if pdf_note and not dup:
        meta += f"\n{pdf_note}"
    if not dup:
        _record_meta(doc_id, d, meta)
    else:
        with db.tx() as c:
            c.execute("UPDATE source SET doi=COALESCE(doi, ?), license=COALESCE(license, ?) "
                      "WHERE source_id=(SELECT source_id FROM document WHERE doc_id=?)",
                      (d.get("doi"), d.get("license"), doc_id))
    with db.tx() as c:
        c.execute("UPDATE collect_item SET status='ingested', doc_id=? WHERE item_id=?", (doc_id, item_id))
    msg = ("이미 자료함에 있는 파일이라 그 자료에 연결했습니다." if dup else
           ("원문 PDF를 받아 자료함에 넣었습니다." if got_pdf else
            "오픈 액세스 전문을 글로 바꿔 자료함에 넣었습니다." if fulltext else
            "서지·초록을 자료함에 넣었습니다" + (" (PDF는 받지 못함)." if pdf_note else ".")))
    return {"item_id": item_id, "doc_id": doc_id, "pdf": got_pdf, "fulltext": bool(fulltext), "duplicate": dup, "message": msg,
            "chunks": res.get("chunks", 0), "error": res.get("error")}


def bulk(item_ids: list[str], action: str, project: str | None = None, confidentiality: str = "일반",
         job_id: str | None = None) -> dict:
    """여러 항목에 같은 동작. action: accept|reject|later|new|ingest. 반환 {"done", "failed", "errors": [...]}"""
    status = {"accept": "accepted", "later": "accepted", "reject": "rejected", "new": "new"}.get(action)
    if action != "ingest" and not status:
        raise CollectError("동작은 accept(보관)·reject(거절)·later(나중에)·new(새 항목으로)·ingest(자료함에 넣기) 중 하나입니다.")
    out = {"action": action, "total": len(item_ids), "done": 0, "failed": 0, "errors": []}
    for iid in item_ids:
        try:
            if action == "ingest":
                ingest(iid, project, confidentiality)
            else:
                set_status(iid, status)
            out["done"] += 1
        except Exception as e:  # noqa: BLE001
            out["failed"] += 1
            out["errors"].append({"item_id": iid, "error": "항목이 없습니다." if isinstance(e, KeyError) else str(e)})
        if job_id:
            _update_job(job_id, stats=out)
    if job_id:
        _update_job(job_id, stats=out, status="error" if out["failed"] and not out["done"] else "done",
                    error="\n".join(e["error"] for e in out["errors"][:10]) or None)
    return out


# ---------------------------------------------------------------- 저장 검색(collect_query)
# sources_json에는 {"sources": [...], "limit_per_source": n, "since_year": y}를 저장한다(예전 형식: 목록만).

def _query_out(r: dict) -> dict:
    r = dict(r)
    raw = json.loads(r.pop("sources_json") or "[]")
    if isinstance(raw, list):
        raw = {"sources": raw}
    r["sources"] = raw.get("sources") or []
    r["limit_per_source"] = raw.get("limit_per_source") or 20
    r["since_year"] = raw.get("since_year")
    r["auto"] = bool(r["auto"])
    r["running"] = r["query_id"] in _running_queries
    nxt = next_run_at(r)
    r["next_run_at"] = _ts(nxt) if nxt else None
    return r


def next_run_at(q: dict) -> datetime | None:
    if not q.get("auto"):
        return None
    last = _parse_ts(q.get("last_run_at"))
    return (last + timedelta(hours=int(q.get("interval_h") or 24))) if last else _parse_ts(q.get("created_at")) or utcnow()


def list_queries() -> list[dict]:
    out = []
    for r in db.rows("SELECT * FROM collect_query ORDER BY created_at DESC, rowid DESC"):
        q = _query_out(r)
        last = db.one("SELECT job_id, status, stats_json, error, finished_at FROM collect_job WHERE query_id=? "
                      "ORDER BY started_at DESC, rowid DESC LIMIT 1", (q["query_id"],))
        if last:
            st = json.loads(last.pop("stats_json") or "{}")
            last["total"] = st.get("total")
            q["last_job"] = last
        out.append(q)
    return out


def get_query(query_id: str) -> dict | None:
    r = db.one("SELECT * FROM collect_query WHERE query_id=?", (query_id,))
    return _query_out(r) if r else None


def save_query(data: dict) -> dict:
    """새 저장 검색(query_id 없음) 또는 수정. 필드: name, query, sources, project, auto, interval_h,
    limit_per_source, since_year"""
    qid = data.get("query_id")
    old = get_query(qid) if qid else None
    if qid and not old:
        raise KeyError(qid)
    base = old or {"name": "", "query": "", "sources": [], "project": None, "auto": False, "interval_h": 24,
                   "limit_per_source": 20, "since_year": None}
    merged = {k: (data[k] if k in data and data[k] is not None else base.get(k)) for k in base}
    if "since_year" in data:
        merged["since_year"] = data["since_year"] or None
    if "project" in data:
        merged["project"] = data["project"] or None
    query = (merged["query"] or "").strip()
    if not query:
        raise CollectError("저장할 검색어를 입력하세요.")
    sources = validate_sources(merged["sources"])
    name = (merged["name"] or "").strip() or query[:40]
    interval = int(merged["interval_h"] or 24)
    if interval < 1 or interval > 24 * 90:
        raise CollectError("자동 실행 간격은 1시간~2160시간(90일) 사이로 정하세요.")
    limit = max(1, min(int(merged["limit_per_source"] or 20), MAX_LIMIT))
    sj = json.dumps({"sources": sources, "limit_per_source": limit,
                     "since_year": int(merged["since_year"]) if merged["since_year"] else None}, ensure_ascii=False)
    with db.tx() as c:
        if old:
            c.execute("UPDATE collect_query SET name=?, query=?, sources_json=?, project=?, auto=?, interval_h=? "
                      "WHERE query_id=?", (name, query, sj, merged["project"], int(bool(merged["auto"])), interval, qid))
        else:
            qid = db.new_id()
            c.execute("INSERT INTO collect_query(query_id, name, query, sources_json, project, auto, interval_h, created_at) "
                      "VALUES (?,?,?,?,?,?,?,?)",
                      (qid, name, query, sj, merged["project"], int(bool(merged["auto"])), interval, _ts()))
    return get_query(qid)


def delete_query(query_id: str) -> None:
    if not db.one("SELECT 1 AS x FROM collect_query WHERE query_id=?", (query_id,)):
        raise KeyError(query_id)
    with db.tx() as c:
        c.execute("DELETE FROM collect_query WHERE query_id=?", (query_id,))   # 수집함 항목은 남긴다(query_id만 비움)


def begin_query(query_id: str, now: datetime | None = None) -> dict:
    """저장 검색 실행 예약: 동시 실행을 막고 last_run_at을 지금으로 적은 뒤 (질의, 작업 ID)를 돌려준다."""
    q = get_query(query_id)
    if not q:
        raise KeyError(query_id)
    with _run_lock:
        if query_id in _running_queries:
            raise Busy(f"'{q['name']}' 검색이 이미 실행 중입니다. 끝난 뒤 다시 누르세요.")
        _running_queries.add(query_id)
    try:
        with db.tx() as c:
            c.execute("UPDATE collect_query SET last_run_at=? WHERE query_id=?", (_ts(now), query_id))
        jid = create_job("search", q["query"], q["sources"], query_id)
    except Exception:
        finish_query(query_id)
        raise
    return {"query": q, "job_id": jid}


def finish_query(query_id: str) -> None:
    with _run_lock:
        _running_queries.discard(query_id)


def run_query(query_id: str, now: datetime | None = None, begun: dict | None = None) -> dict:
    """저장 검색을 지금 실행한다(같은 저장 검색이 실행 중이면 Busy)."""
    b = begun or begin_query(query_id, now)
    q = b["query"]
    try:
        return run_search(q["query"], q["sources"], q["limit_per_source"], q["since_year"], q["project"],
                          query_id, job_id=b["job_id"])
    except Exception as e:
        _update_job(b["job_id"], status="error", error=str(e))
        raise
    finally:
        finish_query(query_id)


def due_queries(now: datetime | None = None) -> list[dict]:
    now = now or utcnow()
    out = []
    for r in db.rows("SELECT * FROM collect_query WHERE auto=1"):
        q = _query_out(r)
        nxt = next_run_at(q)
        if q["running"] or nxt is None:
            continue
        if nxt <= now:
            out.append(q)
    return out
