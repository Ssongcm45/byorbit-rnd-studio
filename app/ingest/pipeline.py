"""자료 투입 파이프라인: 복사 → 파싱 → 정규화 → 청킹 → 사전 라벨링 → 적재 (+CoA 측정값)."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
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
        parsed = parsers.parse(dest)
        _set(doc_id, status, "parse", "done")
        if parsed["meta"].get("needs_ocr"):
            _note(doc_id, "글자가 거의 없는 PDF입니다(스캔본 추정). OCR 확장 설치 후 다시 처리하세요.")

        stage = "normalize"
        for b in parsed["blocks"]:
            b["text"] = normalize_text(b["text"])
            if b["type"] == "table":
                b["rows"] = [[normalize_text(x) for x in r] for r in b["rows"]]
        _set(doc_id, status, "normalize", "done")

        stage = "chunk"
        built = chunker.build(parsed["blocks"])
        stage = "load"
        with db.tx() as c:
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


def load_coa(path: Path, doc_id: str, project_id: str) -> int:
    data = coa.read(path)
    if not data["header_found"]:
        _note(doc_id, "CoA 머리글(시험항목·결과)을 찾지 못해 측정값은 넣지 않았습니다.")
        return 0
    s = data["sample"]
    bp_concept = _concept(s.get("sample_name"), ("부산물",))
    byproduct = db.one("SELECT byproduct_id FROM byproduct WHERE concept_id=?", (bp_concept,)) if bp_concept else None
    bp_id = byproduct["byproduct_id"] if byproduct else None
    sample_id = db.new_id()
    with db.tx() as c:
        c.execute("INSERT INTO sample(sample_id, byproduct_id, supplier, collected_at, pretreatment_concept_id, "
                  "pretreatment_text, lot_no, sample_code, confidentiality, coa_doc_id) VALUES (?,?,?,?,?,?,?,?, '기밀', ?)",
                  (sample_id, bp_id, s.get("supplier"), s.get("collected_at"),
                   _concept(s.get("pretreatment"), ("공정",)), s.get("pretreatment"),
                   s.get("lot_no"), s.get("sample_code"), doc_id))
        c.execute("INSERT OR IGNORE INTO project_item(project_id, entity_type, entity_id) VALUES (?, 'sample', ?)",
                  (project_id, sample_id))
        for it in data["items"]:
            c.execute("INSERT INTO measurement(meas_id, byproduct_id, sample_id, target_concept_id, target_text, value, "
                      "value_text, unit_concept_id, unit_text, basis, method_concept_id, method_text, doc_id, entry) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'coa')",
                      (db.new_id(), bp_id, sample_id, _concept(it["item"], ("성분", "물성")), it["item"],
                       it["value"], it["value_text"], _concept(it["unit"], ("단위",)), it["unit"], it["basis"],
                       _concept(it["method"], ("시험법",)), it["method"], doc_id))
    if not bp_id:
        _note(doc_id, f"시료명 '{s.get('sample_name') or '?'}'을 부산물 개념에 연결하지 못했습니다. 측정값 화면에서 지정하세요.")
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
    if remove_file:
        p = Path(d["file_uri"])
        if p.exists():
            p.unlink()
