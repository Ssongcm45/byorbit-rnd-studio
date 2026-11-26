"""자료 투입 파이프라인: 복사 → 파싱 → 정규화 → 청킹 → 사전 라벨링 → 적재 (+CoA 측정값)."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import time
import traceback
import unicodedata
from pathlib import Path

from .. import config, db, thesaurus
from . import chunker, coa, parsers

STAGES = ["parse", "normalize", "chunk", "label", "load"]
DICT_CONF = 0.95


class Duplicate(Exception):
    def __init__(self, doc_id: str):
        super().__init__("이미 들어온 파일입니다")
        self.doc_id = doc_id


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", s).strip() or "기본"


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("​", "").replace("﻿", "")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def normalize_blocks(blocks: list[dict]) -> list[dict]:
    """블록 글자·표 셀 정규화(NFKC·공백). 여러 번 해도 결과가 같다."""
    for b in blocks:
        b["text"] = normalize_text(b.get("text") or "")
        if b.get("type") == "table":
            b["rows"] = [[normalize_text(str(x)) for x in r] for r in b.get("rows") or []]
    return blocks


def _chunk_params(doc_id: str) -> dict:
    """작업대(L)의 학습 규칙이 정한 청커 값. 모듈이 없거나 실패하면 기본값."""
    try:
        from .. import chunk_rules
        fn = getattr(chunk_rules, "chunker_params", None)
        return dict(fn(doc_id) or {}) if fn else {}
    except Exception:  # noqa: BLE001
        return {}


def _build(blocks: list[dict], params: dict) -> dict:
    if params:
        try:
            return chunker.build(blocks, **params)
        except TypeError:   # 청커가 매개변수를 받지 않는 판
            pass
    return chunker.build(blocks)


def _load_built(c, doc_id: str, built: dict) -> list[tuple[str, str]]:
    """chunker.build 결과 → doc_section·doc_table·chunk 행. 반환: [(chunk_id, text)]."""
    sec_ids, tab_ids = {}, {}
    for i, s in enumerate(built["sections"]):
        sid = db.new_id()
        sec_ids[s["key"]] = sid
        c.execute("INSERT INTO doc_section(section_id, doc_id, heading, ord, page_from, page_to) VALUES (?,?,?,?,?,?)",
                  (sid, doc_id, s["heading"], i, s["page_from"], s["page_to"]))
    for t in built["tables"]:
        tid = db.new_id()
        tab_ids[t["key"]] = tid
        c.execute("INSERT INTO doc_table(table_id, doc_id, section_id, caption, page, cells_json) VALUES (?,?,?,?,?,?)",
                  (tid, doc_id, sec_ids.get(t["section"]), t["caption"], t["page"],
                   json.dumps(t["rows"], ensure_ascii=False)))
    chunk_rows = []
    for i, ch in enumerate(built["chunks"]):
        cid = db.new_id()
        chunk_rows.append((cid, ch["text"]))
        c.execute("INSERT INTO chunk(chunk_id, doc_id, section_id, table_id, chunk_type, ord, text, page) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  (cid, doc_id, sec_ids.get(ch["section"]), tab_ids.get(ch.get("table")),
                   ch["type"], i, ch["text"], ch["page"]))
    return chunk_rows


def _parse_new(dest: Path) -> dict:
    """새 파일: 형식별 기본 파서 도구(사용자 설정 가능) → 실패·미설치면 기존 파서."""
    try:
        from . import parser_tools
    except Exception:  # noqa: BLE001 — 도구 목록이 깨져도 투입은 기존대로
        parsed = parsers.parse(dest)
        parsed.setdefault("meta", {})["tool"] = "builtin"
        return parsed
    return parser_tools.parse_default(dest)


def ingest_file(src: Path, project: str | None = None, confidentiality: str = "내부",
                title: str | None = None, year: int | None = None, authors: str | None = None,
                move: bool = False, as_coa: bool | None = None) -> dict:
    """파일 하나를 넣는다. 반환: {"doc_id", "status", "chunks", "annotations", "measurements"}"""
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(src)
    ext = src.suffix.lower()
    if ext not in parsers.SUPPORTED and ext != ".hwp":
        raise parsers.UnsupportedFile(f"지원하지 않는 형식: {ext}")
    project = project or config.load_settings()["default_project"]
    project_id = db.ensure_project(project)

    digest = sha256(src)
    dup = db.one("SELECT doc_id FROM document WHERE sha256=?", (digest,))
    if dup:
        _link(project_id, "document", dup["doc_id"])
        raise Duplicate(dup["doc_id"])

    # 1) 라이브러리로 복사 (원본은 건드리지 않는다. 받은편지함에서 온 파일만 옮긴다)
    dest_dir = config.path("library", _safe_name(project))
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    n = 1
    while dest.exists():
        dest = dest_dir / f"{src.stem} ({n}){src.suffix}"
        n += 1
    (shutil.move if move else shutil.copy2)(str(src), str(dest))

    is_coa = as_coa if as_coa is not None else (ext in (".xlsx", ".xlsm") and coa.looks_like_coa(dest))
    source_type = "coa" if is_coa else {"pdf": "paper", "hwpx": "report"}.get(ext.lstrip("."), "file")
    if is_coa:
        confidentiality = "기밀"

    source_id, doc_id = db.new_id(), db.new_id()
    status = {s: "waiting" for s in STAGES}
    with db.tx() as c:
        c.execute("INSERT INTO source(source_id, source_type, title, authors, year, confidentiality) VALUES (?,?,?,?,?,?)",
                  (source_id, source_type, title or src.stem, authors, year, confidentiality))
        c.execute("INSERT INTO document(doc_id, source_id, file_uri, file_name, mime, sha256, parse_status, parser_ver) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  (doc_id, source_id, str(dest), dest.name, mimetypes.guess_type(dest.name)[0], digest,
                   json.dumps(status), parsers.PARSER_VER))
        c.execute("INSERT INTO project_item(project_id, entity_type, entity_id) VALUES (?, 'document', ?)",
                  (project_id, doc_id))

    result = {"doc_id": doc_id, "file_name": dest.name, "project": project, "source_type": source_type,
              "chunks": 0, "annotations": 0, "measurements": 0}
    stage = "parse"
    try:
        parsed = _parse_new(dest)
        meta = parsed.get("meta") or {}
        status["tool"], status["tool_ver"] = meta.get("tool") or "builtin", meta.get("tool_ver")
        result["parser_tool"] = status["tool"]
        with db.tx() as c:
            c.execute("UPDATE document SET parser_ver=? WHERE doc_id=?",
                      (_parser_ver(status["tool"], status["tool_ver"]), doc_id))
        _set(doc_id, status, "parse", "done")
        if meta.get("needs_ocr"):
            _note(doc_id, "글자가 거의 없는 PDF입니다(스캔본 추정). OCR 확장 설치 후 다시 처리하세요.")
        if meta.get("fallback_from"):
            _note(doc_id, f"기본 파서 도구 '{meta['fallback_from']}'를 쓸 수 없어 기존 파서로 읽었습니다.")

        stage = "normalize"
        normalize_blocks(parsed["blocks"])
        _set(doc_id, status, "normalize", "done")
        _record_parse(doc_id, parsed)

        stage = "chunk"
        built = _build(parsed["blocks"], _chunk_params(doc_id))
        stage = "load"
        with db.tx() as c:
            chunk_rows = _load_built(c, doc_id, built)
        result["chunks"] = len(chunk_rows)
        _set(doc_id, status, "chunk", "done")

        stage = "label"
        result["annotations"] = dict_label(chunk_rows)
        _set(doc_id, status, "label", "dict")  # 사전 단계까지. LLM 라벨링은 Claude Code가 이어서 한다

        if is_coa:
            result["measurements"] = load_coa(dest, doc_id, project_id)
        _set(doc_id, status, "load", "done")
    except Exception as e:  # 실패한 단계를 표시하고 원인을 남긴다
        _set(doc_id, status, stage, "error")
        _note(doc_id, f"{stage} 단계 실패: {e}")
        result["error"] = str(e)
        (config.path("logs") / f"ingest-{doc_id}.log").write_text(traceback.format_exc(), encoding="utf-8")
    result["status"] = status
    return result


def _link(project_id, etype, eid):
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO project_item(project_id, entity_type, entity_id) VALUES (?,?,?)",
                  (project_id, etype, eid))


def _set(doc_id, status, stage, value):
    status[stage] = value
    with db.tx() as c:
        c.execute("UPDATE document SET parse_status=? WHERE doc_id=?", (json.dumps(status), doc_id))


def _note(doc_id, msg):
    with db.tx() as c:
        c.execute("UPDATE document SET note = COALESCE(note || char(10), '') || ? WHERE doc_id=?", (msg, doc_id))


def _parser_ver(tool: str | None, ver: str | None) -> str:
    """document.parser_ver: '<도구>/<도구 판>' (기존 파서 판 표시는 parsers.PARSER_VER 그대로 붙인다)."""
    return f"{tool or 'builtin'}/{ver or parsers.PARSER_VER}"


def _record_parse(doc_id: str, parsed: dict) -> None:
    """처음 쓴 파서의 블록을 파서 비교용 결과로 남긴다(선택됨). 실패해도 투입은 계속한다."""
    try:
        from .parser_tools import results
        results.save_result(doc_id, {"blocks": [dict(b) for b in parsed["blocks"]], "meta": parsed.get("meta") or {}},
                            chosen=True)
    except Exception as e:  # noqa: BLE001
        _note(doc_id, f"파서 결과 기록 실패(청킹에는 영향 없음): {e}")


# ---------------------------------------------------------------- 다른 파서 결과로 다시 청킹

MANUAL_METHODS = ("human", "manual")   # 스키마의 사용자 라벨은 method='human'


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _locate(surface: str, old_rel: float, old_page, new_chunks: list[dict], total: int) -> tuple[dict, int] | None:
    """새 청크들에서 surface가 나오는 자리 중, 문서 안 상대 위치가 old_rel에 가장 가깝고 쪽이 같은 곳.
    반환: (청크, 청크 안 시작 위치) 또는 None."""
    best, best_score = None, None
    for ch in new_chunks:
        start = 0
        while True:
            i = ch["text"].find(surface, start)
            if i < 0:
                break
            rel = (ch["offset"] + i) / max(1, total)
            score = abs(rel - old_rel)
            if old_page is not None and ch["page"] is not None and ch["page"] != old_page:
                score += 0.5
            if best_score is None or score < best_score:
                best, best_score = (ch, i), score
            start = i + 1
    return best


def _chunks_with_offsets(c, doc_id: str) -> tuple[list[dict], int]:
    rows = c.execute("SELECT chunk_id, text, page, ord FROM chunk WHERE doc_id=? ORDER BY ord, rowid",
                     (doc_id,)).fetchall()
    out, off = [], 0
    for r in rows:
        out.append({"chunk_id": r["chunk_id"], "text": r["text"], "page": r["page"], "ord": r["ord"], "offset": off})
        off += len(r["text"]) + 1
    return out, off


def reprocess_from_blocks(doc_id: str, blocks: list[dict], parser_tool: str, tool_ver: str | None = None,
                          meta: dict | None = None, keep_reviewed: bool = True) -> dict:
    """같은 document·source를 그대로 두고, 주어진 블록으로 섹션·표·청크를 새로 만든다.

    - 사전·AI 라벨(dict·regex·llm)은 지우고 사전 라벨은 다시 만든다(AI 라벨은 'AI 라벨'을 다시 돌려야 한다).
    - 사용자 라벨(method='human')과 검토에서 승인한 AI 라벨(keep_reviewed)은 같은 표기가 같은 자리 근처에 있는 새 청크로
      옮긴다(ann_id 유지 → 측정값 연결도 유지). 못 옮긴 것은 lost로 보고한다.
    - 지운 라벨에 연결된 측정값은 지우지 않는다. 외래키(ON DELETE SET NULL)로 ann_id만 비고, 개수를 보고한다.
    - CoA(엑셀) 측정값은 파서와 무관하므로 그대로 둔다(없으면 새로 읽는다).
    - 작업대 규칙(app.chunk_rules)이 있으면 청커 값(chunker_params)과 apply(doc_id)를 쓴다.
    - 시작 전에 옮길 라벨을 parsed/<doc_id>/rechunk-backup-*.json에 적어 둔다(중간에 꺼져도 되살릴 수 있게).
    """
    d = db.one("SELECT d.doc_id, d.file_uri, d.parse_status, s.source_type FROM document d "
               "JOIN source s ON s.source_id=d.source_id WHERE d.doc_id=?", (doc_id,))
    if not d:
        raise KeyError(doc_id)
    blocks = normalize_blocks([dict(b) for b in blocks])
    built = _build(blocks, _chunk_params(doc_id))
    if not built["chunks"]:
        raise ValueError("이 결과로는 청크가 하나도 나오지 않습니다(글자가 없음). 다른 파서 결과를 고르세요.")

    # 1) 옮길 라벨과 영향 범위 미리 읽기
    conn = db.connect()
    try:
        old_chunks, old_total = _chunks_with_offsets(conn, doc_id)
    finally:
        conn.close()
    by_id = {ch["chunk_id"]: ch for ch in old_chunks}
    cond = "a.method IN (?,?)" + (" OR a.status='accepted'" if keep_reviewed else "")
    keep = db.rows(f"SELECT a.* FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id WHERE c.doc_id=? AND ({cond})",
                   (doc_id, *MANUAL_METHODS))
    keep_ids = {a["ann_id"] for a in keep}
    all_anns = db.rows("SELECT a.ann_id, a.method FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id WHERE c.doc_id=?",
                       (doc_id,))
    links = {}
    for a in keep:
        links[a["ann_id"]] = {
            "meas": [r["meas_id"] for r in db.rows("SELECT meas_id FROM measurement WHERE ann_id=?", (a["ann_id"],))],
            "conv": [r["conv_id"] for r in db.rows("SELECT conv_id FROM conversion_run WHERE ann_id=?", (a["ann_id"],))],
            "ex": [r["ex_id"] for r in db.rows("SELECT ex_id FROM label_example WHERE ann_id=?", (a["ann_id"],))],
        }
    rels = db.rows("SELECT * FROM relation_annotation WHERE head_ann_id IN (SELECT a.ann_id FROM annotation a JOIN chunk c "
                   "ON c.chunk_id=a.chunk_id WHERE c.doc_id=?)", (doc_id,))
    dropped_ids = [a["ann_id"] for a in all_anns if a["ann_id"] not in keep_ids]
    meas_unlinked = 0
    if dropped_ids:
        q = ",".join("?" * len(dropped_ids))
        meas_unlinked = db.one(f"SELECT COUNT(*) AS n FROM measurement WHERE ann_id IN ({q})", dropped_ids)["n"]
    backup = config.path("parsed", doc_id, f"rechunk-backup-{int(time.time())}.json")
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(json.dumps({"annotations": keep, "links": links, "relations": rels,
                                  "old_chunks": [{k: ch[k] for k in ("chunk_id", "ord", "page", "text")} for ch in old_chunks]},
                                 ensure_ascii=False), encoding="utf-8")

    # 2) 옛 청크·섹션·표 지우기 + 새로 넣기(한 트랜잭션)
    status = json.loads(d["parse_status"] or "{}")
    with db.tx() as c:
        cit = c.execute("UPDATE report_citation SET chunk_id=NULL WHERE chunk_id IN "
                        "(SELECT chunk_id FROM chunk WHERE doc_id=?)", (doc_id,)).rowcount
        c.execute("UPDATE chunk SET parent_chunk_id=NULL WHERE doc_id=?", (doc_id,))
        c.execute("DELETE FROM chunk WHERE doc_id=?", (doc_id,))      # 라벨 연쇄 삭제, 측정값 ann_id → NULL
        c.execute("DELETE FROM doc_table WHERE doc_id=?", (doc_id,))
        c.execute("UPDATE doc_section SET parent_section_id=NULL WHERE doc_id=?", (doc_id,))
        c.execute("DELETE FROM doc_section WHERE doc_id=?", (doc_id,))
        _load_built(c, doc_id, built)
        status.update({"tool": parser_tool, "tool_ver": tool_ver, "chunk": "done", "label": "dict"})
        c.execute("UPDATE document SET parse_status=?, parser_ver=? WHERE doc_id=?",
                  (json.dumps(status), _parser_ver(parser_tool, tool_ver), doc_id))
        db.log_change(c, "document", doc_id, {"rechunk_from": "previous"},
                      {"parser_tool": parser_tool, "tool_ver": tool_ver, "chunks": len(built["chunks"])})

    # 3) 작업대 규칙 적용(L 묶음, 없으면 건너뜀)
    rules = None
    try:
        from .. import chunk_rules
        if hasattr(chunk_rules, "apply"):
            try:
                rules = chunk_rules.apply(doc_id, origin="reparse")
            except TypeError:
                rules = chunk_rules.apply(doc_id)
    except ImportError:
        rules = "skipped"
    except Exception as e:  # noqa: BLE001 — 규칙 실패가 다시 청킹을 망치지 않게
        rules = {"error": str(e)}

    # 4) 사용자 라벨 옮기기 (같은 ann_id로 다시 넣고 측정값·사례·전환 기록 연결 복구)
    moved, lost = [], []
    with db.tx() as c:
        new_chunks, new_total = _chunks_with_offsets(c, doc_id)
        cols = ("ann_id", "span_start", "span_end", "surface_text", "label_type", "concept_id", "normalized_value",
                "unit_concept_id", "confidence", "method", "status", "engine", "reviewed_at", "created_at")
        for a in keep:
            och = by_id.get(a["chunk_id"])
            old_rel = ((och["offset"] if och else 0) + (a["span_start"] or 0)) / max(1, old_total)
            surface = a["surface_text"] or ""
            found = surface
            hit = _locate(surface, old_rel, och["page"] if och else None, new_chunks, new_total) if surface else None
            if not hit and surface and _norm_ws(surface) != surface:
                found = _norm_ws(surface)
                hit = _locate(found, old_rel, och["page"] if och else None, new_chunks, new_total)
            if not hit:
                lost.append({"ann_id": a["ann_id"], "surface": surface, "label_type": a["label_type"],
                             "method": a["method"], "old_ord": och["ord"] if och else None,
                             "measurements": len(links[a["ann_id"]]["meas"])})
                continue
            ch, i = hit
            vals = dict(a, span_start=i, span_end=i + len(found), surface_text=found)
            c.execute(f"INSERT INTO annotation(chunk_id, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))})",
                      (ch["chunk_id"], *[vals[k] for k in cols]))
            lk = links[a["ann_id"]]
            for mid in lk["meas"]:
                c.execute("UPDATE measurement SET ann_id=? WHERE meas_id=?", (a["ann_id"], mid))
            for cid_ in lk["conv"]:
                c.execute("UPDATE conversion_run SET ann_id=? WHERE conv_id=?", (a["ann_id"], cid_))
            for ex in lk["ex"]:
                c.execute("UPDATE label_example SET ann_id=?, chunk_id=? WHERE ex_id=?", (a["ann_id"], ch["chunk_id"], ex))
            moved.append({"ann_id": a["ann_id"], "surface": surface, "label_type": a["label_type"],
                          "method": a["method"], "new_ord": ch["ord"]})
        moved_ids = {m["ann_id"] for m in moved}
        rel_back = 0
        for r in rels:
            if r["head_ann_id"] in moved_ids and r["tail_ann_id"] in moved_ids:
                c.execute("INSERT OR IGNORE INTO relation_annotation(rel_id, head_ann_id, tail_ann_id, rel_type, confidence, "
                          "status) VALUES (?,?,?,?,?,?)", (r["rel_id"], r["head_ann_id"], r["tail_ann_id"],
                                                           r["rel_type"], r["confidence"], r["status"]))
                rel_back += 1
        new_rows = [(ch["chunk_id"], ch["text"]) for ch in new_chunks]

    # 5) 사전 라벨 다시 + 옮긴 라벨과 같은 자리의 사전 라벨은 빼기
    n_dict = dict_label(new_rows)
    with db.tx() as c:
        dup = c.execute("DELETE FROM annotation WHERE method='dict' AND status='auto' AND chunk_id IN "
                        "(SELECT chunk_id FROM chunk WHERE doc_id=?) AND EXISTS (SELECT 1 FROM annotation h "
                        "WHERE h.chunk_id=annotation.chunk_id AND h.ann_id<>annotation.ann_id "
                        "AND h.span_start=annotation.span_start AND h.span_end=annotation.span_end "
                        "AND (h.method<>'dict' OR h.status<>'auto'))", (doc_id,)).rowcount

    # 6) CoA: 측정값은 파일에서 따로 읽으므로 이미 있으면 그대로
    coa_state = None
    if d["source_type"] == "coa":
        if db.one("SELECT 1 AS x FROM sample WHERE coa_doc_id=?", (doc_id,)):
            coa_state = "kept"
        else:
            proj = db.one("SELECT project_id FROM project_item WHERE entity_type='document' AND entity_id=?", (doc_id,))
            n = load_coa(Path(d["file_uri"]), doc_id, proj["project_id"] if proj else db.ensure_project(
                config.load_settings()["default_project"]))
            coa_state = f"loaded:{n}"

    lost_meas = sum(x["measurements"] for x in lost)
    msgs = [f"청크 {len(new_rows)}개로 다시 나눴습니다({parser_tool})."]
    if moved:
        msgs.append(f"사용자·승인 라벨 {len(moved)}개를 새 청크로 옮겼습니다.")
    if lost:
        msgs.append(f"라벨 {len(lost)}개는 같은 표기를 새 청크에서 찾지 못해 옮기지 못했습니다(목록 참고).")
    if meas_unlinked + lost_meas:
        msgs.append(f"측정값 {meas_unlinked + lost_meas}개는 지우지 않았고, 라벨 연결만 끊겼습니다(측정값 표에 그대로 있음).")
    if cit:
        msgs.append(f"리포트 인용 {cit}건의 청크 연결이 끊겼습니다(인용 문장은 남음).")
    dropped_auto = len(dropped_ids)
    if dropped_auto:
        msgs.append(f"사전·AI 라벨 {dropped_auto}개를 지웠고 사전 라벨 {n_dict - dup}개를 새로 만들었습니다. "
                    "AI 라벨이 필요하면 'AI 라벨'을 다시 실행하세요.")
    return {"doc_id": doc_id, "parser_tool": parser_tool, "tool_ver": tool_ver,
            "chunks": len(new_rows), "sections": len(built["sections"]), "tables": len(built["tables"]),
            "annotations_dict": n_dict - dup, "auto_dropped": dropped_auto,
            "manual_moved": len(moved), "manual_lost": lost, "moved": moved,
            "measurements_unlinked": meas_unlinked + lost_meas, "relations_restored": rel_back,
            "citations_unlinked": cit, "rules": rules, "coa": coa_state, "backup": str(backup),
            "message": " ".join(msgs)}


def dict_label(chunk_rows: list[tuple[str, str]]) -> int:
    """시소러스 표기 일치 → annotation(method=dict, status=auto)."""
    n = 0
    with db.tx() as c:
        for cid, text in chunk_rows:
            for m in thesaurus.find_mentions(text):
                c.execute("INSERT INTO annotation(ann_id, chunk_id, span_start, span_end, surface_text, label_type, "
                          "concept_id, confidence, method, status) VALUES (?,?,?,?,?,?,?,?, 'dict', 'auto')",
                          (db.new_id(), cid, m["start"], m["end"], m["surface"], _label_type(m["scheme"]),
                           m["concept_id"], DICT_CONF))
                n += 1
    return n


_LABEL = {"부산물": "BYPRODUCT", "원물": "COMMODITY", "공정": "PROCESS", "성분": "CONSTITUENT",
          "물성": "PROPERTY", "단위": "UNIT", "시험법": "METHOD", "용도": "APPLICATION", "분류": "CATEGORY"}


def _label_type(scheme: str | None) -> str:
    return _LABEL.get(scheme or "", "OTHER")


def _concept(term: str | None, schemes: tuple[str, ...]) -> str | None:
    if not term:
        return None
    for h in thesaurus.lookup(term):
        if h["exact"] and h["scheme"] in schemes:
            return h["concept_id"]
    return None


_META_NOTE = [("variety", "품종"), ("region", "산지"), ("harvest", "수확시기"), ("lab", "분석기관"),
              ("analyzed_at", "분석일")]


def byproduct_for(term: str | None) -> str | None:
    """표기 → byproduct_id. 정확히 맞지 않으면 문장 속 부산물 표기를 찾는다('사과박 분말 A' → 사과박)."""
    if not term:
        return None
    cid = _concept(term, ("부산물",))
    if not cid:
        cid = next((m["concept_id"] for m in thesaurus.find_mentions(str(term)) if m["scheme"] == "부산물"), None)
    if not cid:
        return None
    r = db.one("SELECT byproduct_id FROM byproduct WHERE concept_id=?", (cid,))
    return r["byproduct_id"] if r else None


def _target_concept(item: str) -> str | None:
    # '수분(생시료)'·'수분(건조 후)'은 둘 다 개념 '수분' — 항목명(target_text)으로 구분한다
    return _concept(item, ("성분", "물성")) or _concept(re.sub(r"\s*\(.*\)\s*$", "", item), ("성분", "물성"))


def load_coa(path: Path, doc_id: str, project_id: str) -> int:
    data = coa.read(path)
    if not data["header_found"]:
        _note(doc_id, "CoA 머리글(시험항목·결과)을 찾지 못해 측정값은 넣지 않았습니다.")
        return 0
    s = data["sample"]
    bp_id = byproduct_for(s.get("byproduct")) or byproduct_for(s.get("sample_name"))
    drying = s.get("drying")
    pre_concept = _concept(drying, ("공정",)) if drying and drying != "없음" else None
    sample_id = db.new_id()
    with db.tx() as c:
        c.execute("INSERT INTO sample(sample_id, byproduct_id, supplier, collected_at, pretreatment_concept_id, "
                  "pretreatment_text, lot_no, sample_code, confidentiality, coa_doc_id) VALUES (?,?,?,?,?,?,?,?, '기밀', ?)",
                  (sample_id, bp_id, s.get("supplier"), s.get("collected_at") or s.get("harvest"),
                   pre_concept, s.get("pretreatment_text"), s.get("lot_no"), s.get("sample_code"), doc_id))
        c.execute("INSERT OR IGNORE INTO project_item(project_id, entity_type, entity_id) VALUES (?, 'sample', ?)",
                  (project_id, sample_id))
        for it in data["items"]:
            c.execute("INSERT INTO measurement(meas_id, byproduct_id, sample_id, target_concept_id, target_text, value, "
                      "value_text, unit_concept_id, unit_text, basis, method_concept_id, method_text, doc_id, entry) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'coa')",
                      (db.new_id(), bp_id, sample_id, _target_concept(it["item"]), it["item"],
                       it["value"], it["value_text"], _concept(it["unit"], ("단위",)), it["unit"], it["basis"],
                       _concept(it["method"], ("시험법",)), it["method"], doc_id))
    info = [f"{label} {s[k]}" for k, label in _META_NOTE if s.get(k)]
    if info:
        _note(doc_id, "CoA 정보 — " + " · ".join(info))
    if not bp_id:
        name = s.get("byproduct") or s.get("sample_name") or "?"
        _note(doc_id, f"시료명 '{name}'을 부산물 개념에 연결하지 못했습니다. 개념 화면에서 동의어로 추가한 뒤 '다시 처리'하세요.")
    return len(data["items"])


def reprocess(doc_id: str) -> dict:
    """같은 파일을 다시 처리한다(파서 개선 후 등). 기존 청크·라벨·CoA 측정값을 지우고 다시 만든다."""
    d = db.one("SELECT d.*, s.confidentiality, s.title, s.year, s.authors FROM document d "
               "JOIN source s ON s.source_id=d.source_id WHERE d.doc_id=?", (doc_id,))
    if not d:
        raise KeyError(doc_id)
    proj = db.one("SELECT p.name FROM project_item pi JOIN project p ON p.project_id=pi.project_id "
                  "WHERE pi.entity_type='document' AND pi.entity_id=?", (doc_id,))
    path = Path(d["file_uri"])
    tmp = config.path("inbox", f".reprocess-{doc_id[:8]}{path.suffix}")
    shutil.copy2(path, tmp)
    delete_document(doc_id, remove_file=True)
    try:
        return ingest_file(tmp, proj["name"] if proj else None, d["confidentiality"], d["title"], d["year"],
                           d["authors"], move=True)
    finally:
        if tmp.exists():
            tmp.unlink()


def delete_document(doc_id: str, remove_file: bool = False) -> None:
    d = db.one("SELECT source_id, file_uri FROM document WHERE doc_id=?", (doc_id,))
    if not d:
        return
    with db.tx() as c:
        c.execute("DELETE FROM project_item WHERE entity_type='document' AND entity_id=?", (doc_id,))
        c.execute("DELETE FROM project_item WHERE entity_type='sample' AND entity_id IN "
                  "(SELECT sample_id FROM sample WHERE coa_doc_id=?)", (doc_id,))
        c.execute("DELETE FROM measurement WHERE doc_id=?", (doc_id,))
        c.execute("DELETE FROM sample WHERE coa_doc_id=?", (doc_id,))
        c.execute("DELETE FROM source WHERE source_id=?", (d["source_id"],))  # document·chunk·annotation 연쇄 삭제
        db.log_change(c, "document", doc_id, {"file_uri": d["file_uri"]}, None)
    try:
        from .parser_tools import results as _parse_results
        _parse_results.remove_doc(doc_id)   # 저장해 둔 파서 결과 블록 파일
    except Exception:  # noqa: BLE001
        pass
    if remove_file:
        p = Path(d["file_uri"])
        if p.exists():
            p.unlink()
