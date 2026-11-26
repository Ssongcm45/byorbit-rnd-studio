"""파서 결과 저장·비교·선택.

- parse_with(doc_id, tool, options, confirm_cloud): 저장된 원본 파일을 도구로 파싱 → 블록 JSON을
  데이터 폴더 parsed/<doc_id>/<tool>-<id8>.json에 저장 + parse_result 행(통계). 같은 도구의 이전 결과(선택 안 된 것)는 지운다.
- compare(doc_id, a, b, page): 결과별 통계 + 고른 쪽(page)의 블록을 나란히.
- choose(doc_id, result_id): 그 결과로 다시 청킹(pipeline.reprocess_from_blocks) + chosen 표시.
클라우드 도구는 여기서 한 번 더 막는다: '기밀' → CloudBlocked, '내부' + 미확인 → NeedsConfirm.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from ... import config, db
from . import CloudBlocked, NeedsConfirm, ToolError, get, run, stats, tools
from . import upstage_tool

PREVIEW_TEXT = 1500     # 비교 화면 블록 하나의 최대 글자
PREVIEW_ROWS = 40       # 비교 화면 표 하나의 최대 행


class NotFound(ToolError):
    pass


def parsed_dir(doc_id: str) -> Path:
    return config.path("parsed", doc_id)


def doc_info(doc_id: str) -> dict:
    d = db.one("SELECT d.doc_id, d.file_name, d.file_uri, d.parse_status, d.parser_ver, d.note, s.confidentiality, "
               "s.source_type, s.title FROM document d JOIN source s ON s.source_id=d.source_id WHERE d.doc_id=?",
               (doc_id,))
    if not d:
        raise NotFound("자료를 찾지 못했습니다. 자료함에서 다시 고르세요.")
    st = json.loads(d.pop("parse_status") or "{}")
    d["ext"] = Path(d["file_name"]).suffix.lower()
    d["tool"] = st.get("tool")
    d["tool_ver"] = st.get("tool_ver")
    d["status"] = {k: v for k, v in st.items() if k not in ("tool", "tool_ver")}
    d["file_exists"] = Path(d.pop("file_uri")).exists()
    d["counts"] = impact(doc_id)
    return d


def impact(doc_id: str) -> dict:
    """다시 청킹하면 영향을 받는 것: 청크·라벨(방법별)·사용자 라벨·라벨에 연결된 측정값."""
    a = db.rows("SELECT a.method, a.status, COUNT(*) AS n FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id "
                "WHERE c.doc_id=? GROUP BY a.method, a.status", (doc_id,))
    by_method: dict[str, int] = {}
    manual = reviewed = 0
    for r in a:
        by_method[r["method"]] = by_method.get(r["method"], 0) + r["n"]
        if r["method"] == "human":
            manual += r["n"]
        elif r["status"] == "accepted":
            reviewed += r["n"]
    m = db.one("SELECT COUNT(*) AS n FROM measurement m JOIN annotation a ON a.ann_id=m.ann_id "
               "JOIN chunk c ON c.chunk_id=a.chunk_id WHERE c.doc_id=?", (doc_id,))["n"]
    return {"chunks": db.one("SELECT COUNT(*) AS n FROM chunk WHERE doc_id=?", (doc_id,))["n"],
            "annotations": sum(by_method.values()), "by_method": by_method, "manual": manual,
            "reviewed": reviewed, "linked_measurements": m}


def _source_file(doc_id: str) -> tuple[dict, Path]:
    d = db.one("SELECT d.file_uri, d.file_name, s.confidentiality FROM document d JOIN source s "
               "ON s.source_id=d.source_id WHERE d.doc_id=?", (doc_id,))
    if not d:
        raise NotFound("자료를 찾지 못했습니다. 자료함에서 다시 고르세요.")
    p = Path(d["file_uri"])
    if not p.exists():
        raise NotFound("원본 파일이 라이브러리 폴더에 없습니다. 파일을 다시 넣어 주세요.")
    return d, p


def precheck(doc_id: str, tool: str, confirm_cloud: bool = False) -> dict:
    """실행 전 확인(동기). 문서·형식·클라우드 보안 등급. 통과하면 doc 정보를 돌려준다."""
    d, p = _source_file(doc_id)
    t = get(tool)
    if p.suffix.lower() not in t.formats:
        raise ToolError(f"{t.name}은(는) {p.suffix.lower()} 파일을 읽지 못합니다.")
    if t.kind == "cloud":
        upstage_tool.guard(d["confidentiality"], confirm_cloud)
    return d


def estimate(doc_id: str, tool: str, options: dict | None = None) -> dict:
    d, p = _source_file(doc_id)
    t = get(tool)
    out = {"tool": t.key, "kind": t.kind, "confidentiality": d["confidentiality"],
           "blocked": t.kind == "cloud" and d["confidentiality"] == "기밀",
           "needs_confirm": t.kind == "cloud" and d["confidentiality"] != "일반"}
    if t.estimate_fn:
        out.update(t.estimate_fn(p, options or {}))
    if out["blocked"]:
        out["message"] = upstage_tool.BLOCK_MSG
    return out


def _normalize(blocks: list[dict]) -> list[dict]:
    from ..pipeline import normalize_blocks
    return normalize_blocks(blocks)


def parse_with(doc_id: str, tool: str, options: dict | None = None, confirm_cloud: bool = False) -> dict:
    """도구로 파싱해 저장한다. 실패해도 parse_result(status=error)를 남기고 그 행을 돌려준다.
    클라우드 차단·확인 필요·모르는 도구·문서 없음은 예외로 올린다(API가 403/409/400/404로 바꾼다)."""
    d = precheck(doc_id, tool, confirm_cloud)
    t = get(tool)
    p = Path(db.one("SELECT file_uri FROM document WHERE doc_id=?", (doc_id,))["file_uri"])
    opts = dict(options or {})
    if t.kind == "cloud":   # 도구 모듈도 스스로 한 번 더 확인한다
        opts["confidentiality"] = d["confidentiality"]
        opts["confirm_cloud"] = bool(confirm_cloud)
    rid = db.new_id()
    t0 = time.perf_counter()
    try:
        parsed = run(tool, p, opts)
    except (CloudBlocked, NeedsConfirm):
        raise
    except Exception as e:  # noqa: BLE001 — 실패도 결과로 남겨 비교 표에서 보인다
        st = {"duration_ms": int((time.perf_counter() - t0) * 1000), "warnings": []}
        with db.tx() as c:
            c.execute("INSERT INTO parse_result(result_id, doc_id, tool, tool_ver, status, stats_json, error) "
                      "VALUES (?,?,?,?, 'error', ?, ?)",
                      (rid, doc_id, tool, t.version(), json.dumps(st, ensure_ascii=False), str(e)[:2000]))
        _prune(doc_id, tool, keep=rid)
        return get_result(rid)
    return save_result(doc_id, parsed, rid=rid, options=opts)


def save_result(doc_id: str, parsed: dict, rid: str | None = None, chosen: bool = False,
                options: dict | None = None) -> dict:
    """블록을 파일로, 통계를 parse_result로. ingest도 이것으로 '처음 쓴 도구' 결과를 남긴다(chosen=1)."""
    rid = rid or db.new_id()
    meta = parsed.get("meta") or {}
    tool = meta.get("tool") or "builtin"
    blocks = _normalize(parsed.get("blocks") or [])
    st = stats({"blocks": blocks, "meta": meta})
    st["options"] = {k: v for k, v in (options or {}).items() if k not in ("confidentiality",)}
    if meta.get("fallback_from"):
        st["fallback_from"] = meta["fallback_from"]
    if meta.get("billed_pages"):
        st["billed_pages"] = meta["billed_pages"]
    out_dir = parsed_dir(doc_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    f = out_dir / f"{tool}-{rid[:8]}.json"
    keep_meta = {k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool, list, type(None)))}
    f.write_text(json.dumps({"blocks": blocks, "meta": keep_meta}, ensure_ascii=False), encoding="utf-8")
    with db.tx() as c:
        if chosen:
            c.execute("UPDATE parse_result SET chosen=0 WHERE doc_id=?", (doc_id,))
        c.execute("INSERT INTO parse_result(result_id, doc_id, tool, tool_ver, status, blocks_path, stats_json, chosen) "
                  "VALUES (?,?,?,?, 'ok', ?, ?, ?)",
                  (rid, doc_id, tool, meta.get("tool_ver"), str(f), json.dumps(st, ensure_ascii=False), int(chosen)))
    _prune(doc_id, tool, keep=rid)
    return get_result(rid)


def _prune(doc_id: str, tool: str, keep: str) -> None:
    """같은 도구의 이전 결과는 하나만 남긴다(선택된 결과는 지우지 않는다)."""
    old = db.rows("SELECT result_id, blocks_path FROM parse_result WHERE doc_id=? AND tool=? AND result_id<>? AND chosen=0",
                  (doc_id, tool, keep))
    if not old:
        return
    with db.tx() as c:
        for r in old:
            c.execute("DELETE FROM parse_result WHERE result_id=?", (r["result_id"],))
    for r in old:
        if r["blocks_path"]:
            Path(r["blocks_path"]).unlink(missing_ok=True)


def _row(r: dict) -> dict:
    r = dict(r)
    r["stats"] = json.loads(r.pop("stats_json") or "{}")
    r["chosen"] = bool(r["chosen"])
    t = tools().get(r["tool"])
    r["name"] = t.name if t else r["tool"]
    r["kind"] = t.kind if t else "local"
    r.pop("blocks_path", None)
    return r


def get_result(result_id: str) -> dict:
    r = db.one("SELECT * FROM parse_result WHERE result_id=?", (result_id,))
    if not r:
        raise NotFound("파싱 결과를 찾지 못했습니다. 목록을 새로 고치세요.")
    return _row(r)


def list_results(doc_id: str) -> list[dict]:
    return [_row(r) for r in db.rows("SELECT * FROM parse_result WHERE doc_id=? ORDER BY created_at, rowid", (doc_id,))]


def load_blocks(result_id: str) -> tuple[dict, list[dict], dict]:
    r = db.one("SELECT * FROM parse_result WHERE result_id=?", (result_id,))
    if not r:
        raise NotFound("파싱 결과를 찾지 못했습니다. 목록을 새로 고치세요.")
    if r["status"] != "ok" or not r["blocks_path"] or not Path(r["blocks_path"]).exists():
        raise ToolError("이 결과에는 블록이 없습니다(실패했거나 파일이 지워짐). 도구를 다시 실행하세요.")
    data = json.loads(Path(r["blocks_path"]).read_text(encoding="utf-8"))
    return r, data.get("blocks") or [], data.get("meta") or {}


def _preview(b: dict) -> dict:
    out = {"type": b.get("type"), "page": b.get("page")}
    if b.get("type") == "table":
        rows = b.get("rows") or []
        out["rows"] = [[str(c)[:200] for c in r] for r in rows[:PREVIEW_ROWS]]
        out["more_rows"] = max(0, len(rows) - PREVIEW_ROWS)
        if b.get("caption"):
            out["caption"] = b["caption"]
    else:
        t = b.get("text") or ""
        out["text"] = t[:PREVIEW_TEXT]
        out["more_chars"] = max(0, len(t) - PREVIEW_TEXT)
        if b.get("type") == "heading":
            out["level"] = b.get("level") or 1
    return out


def compare(doc_id: str, a: str | None = None, b: str | None = None, page: int | None = None,
            max_blocks: int = 80) -> dict:
    """결과별 통계 + 쪽별 글자 수, 그리고 두 결과(a·b)의 page 쪽 블록. page=0은 '쪽 정보 없음' 블록."""
    info = doc_info(doc_id)
    results = list_results(doc_id)
    ok = [r for r in results if r["status"] == "ok"]
    if not a and ok:
        a = next((r["result_id"] for r in ok if r["chosen"]), ok[0]["result_id"])
    if not b and len(ok) > 1:
        b = next((r["result_id"] for r in reversed(ok) if r["result_id"] != a), None)
    per_page: dict[str, dict[int, int]] = {}
    sides = {}
    loaded = {}
    for r in ok:
        try:
            _, blocks, _ = load_blocks(r["result_id"])
        except ToolError:
            continue
        loaded[r["result_id"]] = blocks
        pp: dict[int, int] = {}
        for blk in blocks:
            pg = blk.get("page") or 0
            pp[pg] = pp.get(pg, 0) + len(blk.get("text") or "")
        per_page[r["result_id"]] = pp
    pages = sorted({p for pp in per_page.values() for p in pp})
    if page is None:
        page = pages[0] if pages else 0
    for side, rid in (("a", a), ("b", b)):
        if not rid or rid not in loaded:
            sides[side] = None
            continue
        blks = [x for x in loaded[rid] if (x.get("page") or 0) == page]
        sides[side] = {"result_id": rid, "page": page, "total": len(blks),
                       "blocks": [_preview(x) for x in blks[:max_blocks]],
                       "more_blocks": max(0, len(blks) - max_blocks)}
    page_chars = [{"page": p, **{rid: per_page[rid].get(p, 0) for rid in per_page}} for p in pages]
    return {"doc": info, "results": results, "pages": pages, "page": page, "page_chars": page_chars,
            "a": sides.get("a"), "b": sides.get("b")}


def choose(doc_id: str, result_id: str) -> dict:
    """그 결과의 블록으로 다시 청킹한다. 사용자 라벨은 옮기고, 옮기지 못한 것·끊긴 측정값 연결을 보고한다."""
    from .. import pipeline
    r, blocks, meta = load_blocks(result_id)
    if r["doc_id"] != doc_id:
        raise ToolError("이 문서의 결과가 아닙니다.")
    report = pipeline.reprocess_from_blocks(doc_id, blocks, r["tool"], r["tool_ver"], meta)
    with db.tx() as c:
        c.execute("UPDATE parse_result SET chosen=CASE WHEN result_id=? THEN 1 ELSE 0 END WHERE doc_id=?",
                  (result_id, doc_id))
    report["result"] = get_result(result_id)
    return report


def remove_doc(doc_id: str) -> None:
    """문서를 지울 때 저장한 블록 파일도 지운다(parse_result 행은 document와 함께 연쇄 삭제)."""
    d = parsed_dir(doc_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
