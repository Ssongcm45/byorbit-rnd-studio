"""문서 작업대 — 청크 검사와 고치기.

할 수 있는 일: 글 고치기 · 커서 위치에서 나누기 · 앞뒤 청크와 합치기 · 종류(본문/표) · 섹션 바꾸기 ·
줄을 제목으로 올리기 · 잡음 줄 지우기 · 청크 지우기(잡음) · 마지막 작업 되돌리기.

원칙
- 모든 변경은 chunk 표를 UPDATE/INSERT/DELETE로만 고친다 → 전문검색(chunk_fts)은 스키마의 트리거가 맞춘다.
- 작업 하나 = change_log 한 줄(table_name='wb_op', row_id=doc_id). before_json에 고치기 전 청크·라벨·근거 연결을
  통째로 남겨 되돌리기에 쓰고, after_json의 'learn'은 규칙 배우기(app.chunk_rules.propose)가 읽는다.
  되돌린 작업은 change_log(table_name='wb_undo', row_id=<log_id>)로 표시한다.
- 라벨: 글이 바뀌어도 표기가 그대로 있으면 위치를 옮긴다. 사전·AI 라벨이 더는 맞지 않으면 지우고 보고한다.
  사람이 붙였거나 승인한 라벨(method='human' 또는 status='accepted')은 절대 조용히 지우지 않는다 —
  위치를 찾지 못하면 span을 비워(NULL) '위치 확인 필요'로 남긴다.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from . import db
from .ingest import chunker

MIN_LEN = 80                         # 이보다 짧은 본문 청크는 '너무 짧음'
MAX_LEN = int(chunker.TARGET * 1.6)  # 이보다 길면 '너무 김'
CHUNK_TYPES = ("text", "table")
OCR_LOW = 0.8

_PAGE_NO = re.compile(r"^\s*(?:[-–—]\s*)?(?:(?:p|pp|page)\.?\s*)?\d{1,4}(?:\s*/\s*\d{1,4})?(?:\s*[-–—])?\s*$", re.I)
_SENT_END = re.compile(r"[.!?。:;)\]」』\"'%]$|다$|요$|음$|함$|됨$")


class WbError(Exception):
    """사용자에게 그대로 보여 줄 한국어 오류(무엇을 하면 되는지 포함)."""


class NotFound(WbError):
    pass


# ---------------------------------------------------------------- 공통 도우미

def protected(a: dict) -> bool:
    """사람이 만든 라벨 또는 사람이 승인한 라벨 — 절대 조용히 지우지 않는다."""
    return a.get("method") == "human" or a.get("status") == "accepted"


def _row(c, sql, params=()) -> dict | None:
    r = c.execute(sql, params).fetchone()
    return dict(r) if r else None


def _rows(c, sql, params=()) -> list[dict]:
    return [dict(r) for r in c.execute(sql, params).fetchall()]


def get_chunk(c, chunk_id: str) -> dict:
    ch = _row(c, "SELECT c.*, s.heading FROM chunk c LEFT JOIN doc_section s ON s.section_id=c.section_id "
                 "WHERE c.chunk_id=?", (chunk_id,))
    if not ch:
        raise NotFound("청크를 찾지 못했습니다. 다른 곳에서 바뀌었을 수 있으니 작업대를 새로고침하세요.")
    return ch


def doc_chunks(c, doc_id: str) -> list[dict]:
    return _rows(c, "SELECT c.*, s.heading FROM chunk c LEFT JOIN doc_section s ON s.section_id=c.section_id "
                    "WHERE c.doc_id=? ORDER BY c.ord, c.rowid", (doc_id,))


def heading_prefix(ch: dict) -> str:
    """청크 앞에 붙은 섹션 제목 줄('제목\\n'). 없으면 ''."""
    h = ch.get("heading")
    if h and h != "(머리말)" and (ch["text"] or "").startswith(h + "\n"):
        return h + "\n"
    return ""


def body(ch: dict) -> str:
    return ch["text"][len(heading_prefix(ch)):]


def _anns(c, chunk_id: str) -> list[dict]:
    return _rows(c, "SELECT * FROM annotation WHERE chunk_id=? ORDER BY span_start", (chunk_id,))


def _offset_mapper(old: str, new: str):
    """old의 글자 위치 → new의 위치(바뀐 부분 안이면 None)."""
    blocks = [(i1, i2, j1) for tag, i1, i2, j1, _ in SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
              if tag == "equal"]

    def m(i: int) -> int | None:
        for i1, i2, j1 in blocks:
            if i1 <= i < i2:
                return j1 + (i - i1)
        return None
    return m


def relocate(a: dict, new_text: str, mapper=None) -> tuple[int, int] | None:
    """라벨의 새 위치. 1) 위치 대응으로 같은 표기 2) 가장 가까운 같은 표기 3) 없으면 None."""
    surf = a["surface_text"]
    s, e = a.get("span_start"), a.get("span_end")
    hint = 0
    if mapper and s is not None and e is not None and e > s:
        ns, ne = mapper(s), mapper(e - 1)
        if ns is not None and ne is not None and new_text[ns:ne + 1] == surf:
            return ns, ne + 1
        hint = ns if ns is not None else (ne if ne is not None else s)
    elif s is not None:
        hint = s
    occ, k = [], new_text.find(surf)
    while k >= 0 and surf:
        occ.append(k)
        k = new_text.find(surf, k + 1)
    if not occ:
        return None
    best = min(occ, key=lambda x: abs(x - hint))
    return best, best + len(surf)


def _ann_brief(a: dict) -> dict:
    return {"ann_id": a["ann_id"], "surface": a["surface_text"], "label_type": a["label_type"],
            "method": a["method"], "status": a["status"]}


# ---------------------------------------------------------------- 작업 기록(되돌리기·규칙 배우기)

class Op:
    """작업 하나. touch()로 고치기 전 상태를 남기고, 끝에 log()로 change_log에 쓴다."""

    def __init__(self, c, doc_id: str, kind: str, params: dict | None = None):
        self.c, self.doc_id, self.kind, self.params = c, doc_id, kind, params or {}
        self.chunks: dict[str, dict] = {}
        self.anns: dict[str, dict] = {}
        self.cits: list[dict] = []
        self.meas: list[dict] = []
        self.examples: list[dict] = []
        self.parents: list[dict] = []
        self.created: list[str] = []
        self.sections_created: list[str] = []
        self.ords = {r["chunk_id"]: r["ord"] for r in _rows(c, "SELECT chunk_id, ord FROM chunk WHERE doc_id=?", (doc_id,))}
        self.sec_ords = {r["section_id"]: r["ord"] for r in
                         _rows(c, "SELECT section_id, ord FROM doc_section WHERE doc_id=?", (doc_id,))}
        self.report = {"shifted": 0, "moved": 0, "dropped": [], "flagged": []}
        self.learn: list[dict] = []
        self.changes = 0

    def touch(self, chunk_id: str) -> None:
        if chunk_id in self.chunks or chunk_id in self.created:
            return
        ch = _row(self.c, "SELECT * FROM chunk WHERE chunk_id=?", (chunk_id,))
        if not ch:
            return
        self.chunks[chunk_id] = ch
        for a in _rows(self.c, "SELECT * FROM annotation WHERE chunk_id=?", (chunk_id,)):
            self.anns[a["ann_id"]] = a
            self.meas += _rows(self.c, "SELECT meas_id, ann_id FROM measurement WHERE ann_id=?", (a["ann_id"],))
        self.cits += _rows(self.c, "SELECT cit_id, chunk_id FROM report_citation WHERE chunk_id=?", (chunk_id,))
        self.examples += _rows(self.c, "SELECT ex_id, chunk_id FROM label_example WHERE chunk_id=?", (chunk_id,))
        self.parents += _rows(self.c, "SELECT chunk_id, parent_chunk_id FROM chunk WHERE parent_chunk_id=?", (chunk_id,))

    def drop_ann(self, a: dict, why: str) -> None:
        self.c.execute("DELETE FROM annotation WHERE ann_id=?", (a["ann_id"],))
        self.report["dropped"].append({**_ann_brief(a), "why": why})

    def flag_ann(self, a: dict, chunk_id: str, why: str) -> None:
        self.c.execute("UPDATE annotation SET chunk_id=?, span_start=NULL, span_end=NULL WHERE ann_id=?",
                       (chunk_id, a["ann_id"]))
        self.report["flagged"].append({**_ann_brief(a), "chunk_id": chunk_id, "why": why})

    def log(self) -> int | None:
        if not self.changes:
            return None
        before = {"chunks": list(self.chunks.values()), "anns": list(self.anns.values()), "cits": self.cits,
                  "meas": self.meas, "examples": self.examples, "parents": self.parents, "ords": self.ords,
                  "sec_ords": self.sec_ords}
        after_ids = [r[0] for r in self.c.execute("SELECT chunk_id FROM chunk WHERE doc_id=?", (self.doc_id,)).fetchall()]
        after = {"op": self.kind, "params": self.params, "created": self.created, "after_ids": after_ids,
                 "sections_created": self.sections_created, "report": self.report, "learn": self.learn}
        db.log_change(self.c, "wb_op", self.doc_id, before, after)
        return self.c.execute("SELECT last_insert_rowid()").fetchone()[0]


# ---------------------------------------------------------------- 기본 동작 (연결 c, 작업 op 위에서)

def set_text(op: Op, ch: dict, new_text: str, why: str = "글 고치기") -> None:
    old = ch["text"]
    if new_text == old:
        return
    if not new_text.strip():
        raise WbError("청크 글이 비었습니다. 지우려면 '청크 지우기(잡음)'를 쓰세요.")
    op.touch(ch["chunk_id"])
    mapper = _offset_mapper(old, new_text)
    for a in _anns(op.c, ch["chunk_id"]):
        if a["span_start"] is None and protected(a):
            pos = relocate(a, new_text)  # 위치 확인 필요였던 라벨도 표기가 다시 보이면 자리를 찾는다
            if pos:
                op.c.execute("UPDATE annotation SET span_start=?, span_end=? WHERE ann_id=?", (*pos, a["ann_id"]))
            continue
        pos = relocate(a, new_text, mapper)
        if pos:
            if pos != (a["span_start"], a["span_end"]):
                op.c.execute("UPDATE annotation SET span_start=?, span_end=? WHERE ann_id=?", (*pos, a["ann_id"]))
                op.report["shifted"] += 1
        elif protected(a):
            op.flag_ann(a, ch["chunk_id"], f"{why}: 표기가 본문에서 사라짐")
        else:
            op.drop_ann(a, f"{why}: 표기가 본문에서 사라짐")
    op.c.execute("UPDATE chunk SET text=? WHERE chunk_id=?", (new_text, ch["chunk_id"]))
    ch["text"] = new_text
    op.changes += 1


def _shift_ords(c, doc_id: str, after_ord: int, delta: int) -> None:
    c.execute("UPDATE chunk SET ord=ord+? WHERE doc_id=? AND ord>?", (delta, doc_id, after_ord))


def split(op: Op, ch: dict, pos: int, keep_heading: bool = True) -> str:
    """pos(글자 위치)에서 나눈다. 앞쪽은 원래 청크 id를 그대로 쓰고(리포트 근거가 유지됨) 뒤쪽은 새 청크. 반환: 새 청크 id"""
    text = ch["text"]
    pos = int(pos)
    a_txt, b_raw = text[:pos].rstrip(), text[pos:]
    b_txt = b_raw.lstrip()
    b_off = pos + (len(b_raw) - len(b_txt))
    pre = heading_prefix(ch)
    if (not (0 < pos < len(text)) or not b_txt.strip() or not a_txt.strip() or pos < len(pre)
            or (pre and a_txt.strip() == pre.strip())):
        raise WbError("나눌 위치의 앞과 뒤에 모두 글이 있어야 합니다. 커서를 문장 사이에 두고 다시 누르세요.")
    prefix = pre if keep_heading and pre and not b_txt.startswith(pre) else ""
    new_b = prefix + b_txt
    shift = len(prefix) - b_off
    op.touch(ch["chunk_id"])
    _shift_ords(op.c, ch["doc_id"], ch["ord"], 1)
    nid = db.new_id()
    op.c.execute("INSERT INTO chunk(chunk_id, doc_id, section_id, table_id, parent_chunk_id, chunk_type, ord, text, page, bbox) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (nid, ch["doc_id"], ch["section_id"], ch["table_id"], None, ch["chunk_type"], ch["ord"] + 1,
                  new_b, ch["page"], ch["bbox"]))
    op.created.append(nid)
    for a in _anns(op.c, ch["chunk_id"]):
        s, e = a["span_start"], a["span_end"]
        if s is None:
            continue
        if e <= len(a_txt):
            continue
        if s >= b_off:
            op.c.execute("UPDATE annotation SET chunk_id=?, span_start=?, span_end=? WHERE ann_id=?",
                         (nid, s + shift, e + shift, a["ann_id"]))
            op.report["moved"] += 1
        elif protected(a):
            op.flag_ann(a, ch["chunk_id"], "나누기: 라벨이 나눈 자리에 걸침")
        else:
            op.drop_ann(a, "나누기: 라벨이 나눈 자리에 걸침")
    op.c.execute("UPDATE chunk SET text=? WHERE chunk_id=?", (a_txt, ch["chunk_id"]))
    ch["text"] = a_txt
    op.changes += 1
    return nid


def _first_body_line(ch: dict) -> str:
    return body(ch).split("\n", 1)[0].strip()


def merge(op: Op, a: dict, b: dict, sep: str = "\n\n", dedupe_table_header: bool = False) -> None:
    """a(앞) 뒤에 b를 붙인다. a의 id가 남고 b는 지운다. b 앞의 같은 섹션 제목 줄은 한 번만 남긴다."""
    if a["doc_id"] != b["doc_id"]:
        raise WbError("다른 자료의 청크와는 합칠 수 없습니다.")
    op.touch(a["chunk_id"])
    op.touch(b["chunk_id"])
    bt = b["text"]
    k = 0
    bpre = heading_prefix(b)
    if bpre and (heading_prefix(a) == bpre or a["section_id"] == b["section_id"]):
        k = len(bpre)
    if dedupe_table_header:
        first = bt[k:].split("\n", 1)
        if len(first) == 2 and first[0].strip() and first[0].strip() == _first_body_line(a):
            k += len(first[0]) + 1
    a_txt = a["text"].rstrip()
    joined = a_txt + sep + bt[k:]
    base = len(a_txt) + len(sep) - k
    for ann in _anns(op.c, b["chunk_id"]):
        s, e = ann["span_start"], ann["span_end"]
        if s is not None and s >= k:
            op.c.execute("UPDATE annotation SET chunk_id=?, span_start=?, span_end=? WHERE ann_id=?",
                         (a["chunk_id"], s + base, e + base, ann["ann_id"]))
            op.report["moved"] += 1
            continue
        pos = relocate(ann, joined)
        if pos:
            op.c.execute("UPDATE annotation SET chunk_id=?, span_start=?, span_end=? WHERE ann_id=?",
                         (a["chunk_id"], *pos, ann["ann_id"]))
            op.report["moved"] += 1
        elif protected(ann):
            op.flag_ann(ann, a["chunk_id"], "합치기: 겹친 제목 줄에 붙어 있던 라벨")
        else:
            op.drop_ann(ann, "합치기: 겹친 제목 줄에 붙어 있던 라벨")
    c = op.c
    c.execute("UPDATE report_citation SET chunk_id=? WHERE chunk_id=?", (a["chunk_id"], b["chunk_id"]))
    c.execute("UPDATE label_example SET chunk_id=? WHERE chunk_id=?", (a["chunk_id"], b["chunk_id"]))
    c.execute("UPDATE chunk SET parent_chunk_id=? WHERE parent_chunk_id=?", (a["chunk_id"], b["chunk_id"]))
    new_type = "table" if a["chunk_type"] == "table" and b["chunk_type"] == "table" else (
        "text" if a["chunk_type"] != b["chunk_type"] else a["chunk_type"])
    page = a["page"] if a["page"] is not None else b["page"]
    c.execute("DELETE FROM chunk WHERE chunk_id=?", (b["chunk_id"],))
    _shift_ords(c, a["doc_id"], b["ord"], -1)
    c.execute("UPDATE chunk SET text=?, chunk_type=?, page=? WHERE chunk_id=?", (joined, new_type, page, a["chunk_id"]))
    a.update(text=joined, chunk_type=new_type, page=page)
    op.changes += 1


def _neighbors(c, ch: dict) -> tuple[dict | None, dict | None]:
    prev = _row(c, "SELECT c.*, s.heading FROM chunk c LEFT JOIN doc_section s ON s.section_id=c.section_id "
                   "WHERE c.doc_id=? AND c.ord<? ORDER BY c.ord DESC LIMIT 1", (ch["doc_id"], ch["ord"]))
    nxt = _row(c, "SELECT c.*, s.heading FROM chunk c LEFT JOIN doc_section s ON s.section_id=c.section_id "
                  "WHERE c.doc_id=? AND c.ord>? ORDER BY c.ord LIMIT 1", (ch["doc_id"], ch["ord"]))
    return prev, nxt


def drop(op: Op, ch: dict, force: bool = False, prefer: str = "prev") -> None:
    """청크를 잡음으로 지운다. 사람 라벨이 있으면 force일 때만 이웃 청크로 옮긴다(못 찾으면 '위치 확인 필요')."""
    c = op.c
    keep = [a for a in _anns(c, ch["chunk_id"]) if protected(a)]
    if c.execute("SELECT 1 FROM report_citation WHERE chunk_id=? LIMIT 1", (ch["chunk_id"],)).fetchone():
        raise WbError("리포트 초안의 근거로 쓰인 청크라 지울 수 없습니다. 이웃 청크와 '합치기'를 쓰면 근거가 함께 옮겨집니다.")
    prev, nxt = _neighbors(c, ch)
    target = (prev or nxt) if prefer == "prev" else (nxt or prev)
    if keep and not force:
        names = ", ".join(f"'{a['surface_text'][:20]}'" for a in keep[:3])
        raise WbError(f"사람이 붙였거나 승인한 라벨 {len(keep)}개({names})가 있어 지우지 않았습니다. "
                      "라벨을 먼저 정리하거나, '그래도 지우기'를 누르면 라벨을 이웃 청크로 옮기고 '위치 확인 필요'로 표시합니다.")
    if keep and not target:
        raise WbError("이 자료의 유일한 청크라 지울 수 없습니다. 글을 고치거나 자료를 지우세요.")
    op.touch(ch["chunk_id"])
    if target:
        op.touch(target["chunk_id"])
    for a in _anns(c, ch["chunk_id"]):
        if protected(a):
            pos = relocate(a, target["text"])
            if pos:
                c.execute("UPDATE annotation SET chunk_id=?, span_start=?, span_end=? WHERE ann_id=?",
                          (target["chunk_id"], *pos, a["ann_id"]))
                op.report["moved"] += 1
            else:
                op.flag_ann(a, target["chunk_id"], "청크 지우기: 이웃 청크로 옮김")
        else:
            op.report["dropped"].append({**_ann_brief(a), "why": "청크 지우기"})
    c.execute("UPDATE chunk SET parent_chunk_id=NULL WHERE parent_chunk_id=?", (ch["chunk_id"],))
    c.execute("DELETE FROM chunk WHERE chunk_id=?", (ch["chunk_id"],))  # 남은 라벨은 연쇄 삭제
    _shift_ords(c, ch["doc_id"], ch["ord"], -1)
    op.changes += 1


def _lines(text: str) -> list[str]:
    return text.split("\n")


def drop_lines(op: Op, ch: dict, match) -> int:
    """본문 줄 중 match(줄)가 참인 줄을 지운다(섹션 제목 줄은 건드리지 않음). 본문이 비면 청크를 지운다. 반환: 지운 줄 수"""
    pre = heading_prefix(ch)
    lines = _lines(ch["text"][len(pre):])
    keep = [ln for ln in lines if not (ln.strip() and match(ln.strip()))]
    n = len(lines) - len(keep)
    if not n:
        return 0
    rest = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", "\n".join(keep)).strip("\n")  # 지운 줄 자리의 빈 줄은 하나로
    if not rest.strip():
        drop(op, ch, force=True)
    else:
        set_text(op, ch, pre + rest, why="잡음 줄 지우기")
    return n


def new_section(op: Op, after_section_id: str | None, heading: str, page) -> str:
    c = op.c
    cur = _row(c, "SELECT ord FROM doc_section WHERE section_id=?", (after_section_id,)) if after_section_id else None
    base = cur["ord"] if cur and cur["ord"] is not None else (
        c.execute("SELECT COALESCE(MAX(ord), -1) FROM doc_section WHERE doc_id=?", (op.doc_id,)).fetchone()[0])
    c.execute("UPDATE doc_section SET ord=ord+1 WHERE doc_id=? AND ord>?", (op.doc_id, base))
    sid = db.new_id()
    c.execute("INSERT INTO doc_section(section_id, doc_id, heading, ord, page_from, page_to) VALUES (?,?,?,?,?,?)",
              (sid, op.doc_id, heading, base + 1, page, page))
    op.sections_created.append(sid)
    return sid


def _retitle(op: Op, ch: dict, new_sid: str, new_heading: str | None) -> None:
    """청크의 섹션을 바꾸고, 앞에 붙은 제목 줄도 새 제목으로 바꾼다."""
    op.touch(ch["chunk_id"])
    pre = heading_prefix(ch)
    rest = ch["text"][len(pre):]
    newpre = f"{new_heading}\n" if new_heading and new_heading != "(머리말)" else ""
    op.c.execute("UPDATE chunk SET section_id=? WHERE chunk_id=?", (new_sid, ch["chunk_id"]))
    ch["section_id"] = new_sid
    if (newpre + rest) != ch["text"]:
        set_text(op, ch, newpre + rest, why="섹션 바꾸기")
    ch["heading"] = new_heading
    op.changes += 1


def promote_heading(op: Op, ch: dict, line: str) -> str:
    """청크 안의 줄 하나를 새 섹션 제목으로 올린다. 그 줄부터 다음 섹션 전까지가 새 섹션이 된다. 반환: section_id"""
    line = line.strip()
    if not line:
        raise WbError("제목으로 올릴 줄을 고르세요(커서를 그 줄에 두거나 줄을 선택).")
    pre = heading_prefix(ch)
    if pre and pre.strip() == line:
        raise WbError("이미 이 청크의 섹션 제목입니다.")
    text = ch["text"]
    idx = None
    off = 0
    for ln in _lines(text):
        if off >= len(pre) and ln.strip() == line:
            idx = off
            break
        off += len(ln) + 1
    if idx is None:
        raise WbError("고른 줄을 청크 본문에서 찾지 못했습니다. 줄 전체를 그대로 선택하세요.")
    old_sid, old_heading = ch["section_id"], ch.get("heading")
    target = ch
    if text[len(pre):idx].strip():
        nid = split(op, ch, idx, keep_heading=False)
        target = get_chunk(op.c, nid)
    sid = new_section(op, old_sid, line, target["page"])
    # 제목 줄을 본문에서 빼고, 새 제목 줄을 앞에 붙인다
    t_pre = heading_prefix(target)
    rest_lines = _lines(target["text"][len(t_pre):])
    while rest_lines and not rest_lines[0].strip():
        rest_lines.pop(0)
    if rest_lines and rest_lines[0].strip() == line:
        rest_lines.pop(0)
    rest = "\n".join(rest_lines).strip("\n")
    following = [x for x in doc_chunks(op.c, op.doc_id) if x["ord"] > target["ord"]]
    if rest.strip():
        op.touch(target["chunk_id"])
        op.c.execute("UPDATE chunk SET section_id=? WHERE chunk_id=?", (sid, target["chunk_id"]))
        target["section_id"] = sid
        set_text(op, target, f"{line}\n{rest}", why="제목 올리기")
        target["heading"] = line
    else:
        drop(op, target, force=True, prefer="next")
    for x in following:  # 같은 (옛) 섹션이 이어지는 동안 새 섹션으로
        if x["section_id"] != old_sid:
            break
        _retitle(op, x, sid, line)
    op.learn.append({"kind": "heading", "line": line, "old_heading": old_heading})
    op.changes += 1
    return sid


def set_section(op: Op, ch: dict, section_id: str | None = None, heading: str | None = None) -> str:
    c = op.c
    if heading and not section_id:
        sid = new_section(op, ch["section_id"], heading.strip(), ch["page"])
        h = heading.strip()
    else:
        s = _row(c, "SELECT section_id, heading FROM doc_section WHERE section_id=? AND doc_id=?", (section_id, ch["doc_id"]))
        if not s:
            raise WbError("그 섹션이 이 자료에 없습니다. 섹션 목록을 새로고침하세요.")
        sid, h = s["section_id"], s["heading"]
    _retitle(op, ch, sid, h)
    return sid


def set_type(op: Op, ch: dict, chunk_type: str) -> None:
    if chunk_type not in CHUNK_TYPES:
        raise WbError("청크 종류는 본문(text) 또는 표(table)입니다. 제목은 '줄을 제목으로'를 쓰세요.")
    if chunk_type == ch["chunk_type"]:
        return
    op.touch(ch["chunk_id"])
    op.c.execute("UPDATE chunk SET chunk_type=? WHERE chunk_id=?", (chunk_type, ch["chunk_id"]))
    ch["chunk_type"] = chunk_type
    op.changes += 1


# ---------------------------------------------------------------- 공개 함수 (트랜잭션 하나 = 작업 하나)

def _run(chunk_id: str, kind: str, params: dict, fn) -> dict:
    with db.tx() as c:
        ch = get_chunk(c, chunk_id)
        op = Op(c, ch["doc_id"], kind, params)
        out = fn(op, ch) or {}
        log_id = op.log()
    return {"ok": True, "op": kind, "log_id": log_id, "doc_id": ch["doc_id"], "report": op.report, **out}


def edit_text(chunk_id: str, text: str) -> dict:
    text = (text or "").replace("\r\n", "\n")

    def go(op, ch):
        before_len = len(ch["text"])
        set_text(op, ch, text)
        op.learn.append({"kind": "edit", "len_before": before_len, "len_after": len(text)})
    return _run(chunk_id, "edit", {"chunk_id": chunk_id}, go)


def split_chunk(chunk_id: str, pos: int) -> dict:
    def go(op, ch):
        before_len = len(body(ch))
        nid = split(op, ch, pos)
        nb = get_chunk(op.c, nid)
        op.learn.append({"kind": "split", "len_before": before_len, "parts": [len(body(ch)), len(body(nb))]})
        return {"chunk_ids": [ch["chunk_id"], nid]}
    return _run(chunk_id, "split", {"chunk_id": chunk_id, "pos": pos}, go)


def merge_chunk(chunk_id: str, direction: str = "next") -> dict:
    if direction not in ("next", "prev"):
        raise WbError("합칠 방향은 next(다음) 또는 prev(이전)입니다.")

    def go(op, ch):
        prev, nxt = _neighbors(op.c, ch)
        a, b = (ch, nxt) if direction == "next" else (prev, ch)
        if not a or not b:
            raise WbError("합칠 " + ("다음" if direction == "next" else "이전") + " 청크가 없습니다.")
        info = {"kind": "merge", "a_len": len(body(a)), "b_len": len(body(b)), "a_type": a["chunk_type"],
                "b_type": b["chunk_type"], "same_section": a["section_id"] == b["section_id"],
                "same_table": bool(a["table_id"]) and a["table_id"] == b["table_id"], "direction": direction}
        both_table = a["chunk_type"] == "table" and b["chunk_type"] == "table"
        merge(op, a, b, sep="\n" if both_table else "\n\n", dedupe_table_header=both_table)
        op.learn.append(info)
        return {"chunk_ids": [a["chunk_id"]], "removed": b["chunk_id"]}
    return _run(chunk_id, "merge", {"chunk_id": chunk_id, "direction": direction}, go)


def set_chunk_type(chunk_id: str, chunk_type: str) -> dict:
    return _run(chunk_id, "type", {"chunk_id": chunk_id, "chunk_type": chunk_type},
                lambda op, ch: set_type(op, ch, chunk_type))


def set_chunk_section(chunk_id: str, section_id: str | None = None, heading: str | None = None) -> dict:
    if not section_id and not (heading or "").strip():
        raise WbError("옮길 섹션을 고르거나 새 섹션 제목을 넣으세요.")
    return _run(chunk_id, "section", {"chunk_id": chunk_id, "section_id": section_id, "heading": heading},
                lambda op, ch: {"section_id": set_section(op, ch, section_id, heading)})


def promote_line(chunk_id: str, line: str) -> dict:
    return _run(chunk_id, "heading", {"chunk_id": chunk_id, "line": line},
                lambda op, ch: {"section_id": promote_heading(op, ch, line)})


def drop_chunk(chunk_id: str, force: bool = False) -> dict:
    def go(op, ch):
        b = body(ch).strip()
        drop(op, ch, force=force)
        op.learn.append({"kind": "drop", "text": b[:200], "lines": len([x for x in b.split("\n") if x.strip()]),
                         "page": ch["page"]})
    return _run(chunk_id, "drop", {"chunk_id": chunk_id, "force": force}, go)


def drop_line(chunk_id: str, line: str) -> dict:
    target = (line or "").strip()
    if not target:
        raise WbError("지울 줄을 고르세요(커서를 그 줄에 두면 됩니다).")

    def go(op, ch):
        n = drop_lines(op, ch, lambda ln: ln == target)
        if not n:
            raise WbError("그 줄을 본문에서 찾지 못했습니다. 섹션 제목 줄은 지울 수 없고, 줄 전체가 같아야 합니다.")
        op.learn.append({"kind": "noise", "line": target, "page": ch["page"]})
        return {"removed_lines": n}
    return _run(chunk_id, "drop_line", {"chunk_id": chunk_id, "line": target}, go)


# ---------------------------------------------------------------- 되돌리기

def _undone_ids(c) -> set[int]:
    return {int(r[0]) for r in c.execute("SELECT row_id FROM change_log WHERE table_name='wb_undo'").fetchall()
            if str(r[0]).isdigit()}


def ops(doc_id: str, limit: int = 50, include_undone: bool = False) -> list[dict]:
    """이 자료의 작업 기록(최근 것부터). 규칙 배우기·되돌리기 목록에 쓴다."""
    conn = db.connect()
    try:
        undone = _undone_ids(conn)
        out = []
        for r in conn.execute("SELECT log_id, after_json, at FROM change_log WHERE table_name='wb_op' AND row_id=? "
                              "ORDER BY log_id DESC", (doc_id,)).fetchall():
            if r["log_id"] in undone and not include_undone:
                continue
            a = json.loads(r["after_json"] or "{}")
            out.append({"log_id": r["log_id"], "at": r["at"], "op": a.get("op"), "params": a.get("params"),
                        "report": a.get("report"), "learn": a.get("learn") or [], "undone": r["log_id"] in undone})
            if len(out) >= limit:
                break
        return out
    finally:
        conn.close()


def undo(doc_id: str) -> dict:
    """이 자료의 마지막 작업을 되돌린다(청크 글·순서·섹션·라벨 위치·지워진 사전/AI 라벨까지)."""
    with db.tx() as c:
        undone = _undone_ids(c)
        row = None
        for r in c.execute("SELECT log_id, before_json, after_json FROM change_log WHERE table_name='wb_op' AND row_id=? "
                           "ORDER BY log_id DESC", (doc_id,)).fetchall():
            if r["log_id"] not in undone:
                row = r
                break
        if not row:
            raise WbError("되돌릴 작업이 없습니다.")
        before, after = json.loads(row["before_json"]), json.loads(row["after_json"])
        known = {ch["chunk_id"] for ch in before["chunks"]} | set(after.get("created") or [])
        now = {r[0] for r in c.execute("SELECT chunk_id FROM chunk WHERE doc_id=?", (doc_id,)).fetchall()}
        stale = (set(after["after_ids"]) != now) if "after_ids" in after else \
            any(cid not in now and cid not in known for cid in before["ords"])
        if stale:  # 다시 파싱·다시 청킹으로 청크가 통째로 바뀌었다
            raise WbError("이 작업 뒤에 자료를 다시 파싱(다시 청킹)해서 청크가 바뀌었습니다. 이전 작업은 되돌릴 수 없습니다 — "
                          "필요하면 파싱 탭에서 이전 파싱 결과로 다시 청킹하세요.")
        cols = ("doc_id", "section_id", "table_id", "parent_chunk_id", "chunk_type", "ord", "text", "page", "bbox")
        for ch in before["chunks"]:
            if ch["chunk_id"] in now:
                c.execute("UPDATE chunk SET " + ", ".join(f"{k}=?" for k in cols) + " WHERE chunk_id=?",
                          [ch[k] for k in cols] + [ch["chunk_id"]])
            else:
                c.execute("INSERT INTO chunk(chunk_id, " + ", ".join(cols) + ") VALUES (?" + ",?" * len(cols) + ")",
                          [ch["chunk_id"]] + [ch[k] for k in cols])
        acols = [k for k in (before["anns"][0].keys() if before["anns"] else []) if k != "ann_id"]
        for a in before["anns"]:
            if c.execute("SELECT 1 FROM annotation WHERE ann_id=?", (a["ann_id"],)).fetchone():
                # 위치만 되돌린다(그 사이 검토한 상태는 그대로)
                c.execute("UPDATE annotation SET chunk_id=?, span_start=?, span_end=? WHERE ann_id=?",
                          (a["chunk_id"], a["span_start"], a["span_end"], a["ann_id"]))
            else:
                c.execute("INSERT INTO annotation(ann_id, " + ", ".join(acols) + ") VALUES (?" + ",?" * len(acols) + ")",
                          [a["ann_id"]] + [a[k] for k in acols])
        for m in before["meas"]:
            c.execute("UPDATE measurement SET ann_id=? WHERE meas_id=? AND ann_id IS NULL", (m["ann_id"], m["meas_id"]))
        for x in before["cits"]:
            c.execute("UPDATE report_citation SET chunk_id=? WHERE cit_id=?", (x["chunk_id"], x["cit_id"]))
        for x in before["examples"]:
            c.execute("UPDATE label_example SET chunk_id=? WHERE ex_id=?", (x["chunk_id"], x["ex_id"]))
        for x in before["parents"]:
            c.execute("UPDATE chunk SET parent_chunk_id=? WHERE chunk_id=?", (x["parent_chunk_id"], x["chunk_id"]))
        restored = {ch["chunk_id"] for ch in before["chunks"]}
        home = before["chunks"][0]["chunk_id"] if before["chunks"] else None
        for cid in after.get("created") or []:
            if cid in restored:
                continue
            # 작업 뒤에 새 청크에 붙은 라벨(예: 나눈 뒤 붙인 사람 라벨)은 원래 청크로 옮긴다
            for a in _rows(c, "SELECT * FROM annotation WHERE chunk_id=?", (cid,)):
                if not home:
                    continue
                txt = c.execute("SELECT text FROM chunk WHERE chunk_id=?", (home,)).fetchone()[0]
                pos = relocate(a, txt)
                if pos:
                    c.execute("UPDATE annotation SET chunk_id=?, span_start=?, span_end=? WHERE ann_id=?",
                              (home, *pos, a["ann_id"]))
                elif protected(a):
                    c.execute("UPDATE annotation SET chunk_id=?, span_start=NULL, span_end=NULL WHERE ann_id=?",
                              (home, a["ann_id"]))
            if home:
                c.execute("UPDATE report_citation SET chunk_id=? WHERE chunk_id=?", (home, cid))
                c.execute("UPDATE label_example SET chunk_id=? WHERE chunk_id=?", (home, cid))
            c.execute("UPDATE chunk SET parent_chunk_id=NULL WHERE parent_chunk_id=?", (cid,))
            c.execute("DELETE FROM chunk WHERE chunk_id=?", (cid,))
        for cid, o in before["ords"].items():
            c.execute("UPDATE chunk SET ord=? WHERE chunk_id=?", (o, cid))
        for sid in after.get("sections_created") or []:
            c.execute("UPDATE chunk SET section_id=NULL WHERE section_id=?", (sid,))
            c.execute("DELETE FROM doc_section WHERE section_id=?", (sid,))
        for sid, o in (before.get("sec_ords") or {}).items():
            c.execute("UPDATE doc_section SET ord=? WHERE section_id=?", (o, sid))
        db.log_change(c, "wb_undo", str(row["log_id"]), None, {"doc_id": doc_id, "op": after.get("op")})
    return {"ok": True, "undone": after.get("op"), "log_id": row["log_id"]}


# ---------------------------------------------------------------- 검사(품질 표시)

def _flag(code: str, level: str, msg: str, **kw) -> dict:
    return {"code": code, "level": level, "msg": msg, **kw}


def _norm_line(s: str) -> str:
    return re.sub(r"\d+", "#", re.sub(r"\s+", " ", s.strip()))


def inspect(doc_id: str, min_len: int | None = None, max_len: int | None = None) -> dict:
    """청크를 읽는 순서대로, 문제 표시와 함께. min_len·max_len이 없으면 이 자료에 맞는 길이 규칙을 쓴다."""
    if min_len is None or max_len is None:
        from . import chunk_rules  # 순환 가져오기 방지
        lo, hi = chunk_rules.limits(doc_id)
        min_len = lo if min_len is None else min_len
        max_len = hi if max_len is None else max_len
    conn = db.connect()
    try:
        chunks = doc_chunks(conn, doc_id)
        counts = {r["chunk_id"]: r for r in _rows(
            conn, "SELECT a.chunk_id, COUNT(*) AS n, SUM(CASE WHEN a.span_start IS NULL THEN 1 ELSE 0 END) AS lost, "
                  "SUM(CASE WHEN a.status='pending' THEN 1 ELSE 0 END) AS pending FROM annotation a "
                  "JOIN chunk c ON c.chunk_id=a.chunk_id WHERE c.doc_id=? GROUP BY a.chunk_id", (doc_id,))}
    finally:
        conn.close()
    # 여러 청크에 되풀이되는 줄 = 머리글·바닥글 후보(섹션 제목 줄은 원래 되풀이되므로 뺀다)
    line_chunks: dict[str, set] = {}
    bodies = {}
    for ch in chunks:
        b = body(ch)
        bodies[ch["chunk_id"]] = b
        for ln in b.split("\n"):
            s = ln.strip()
            if 2 <= len(s) <= 80:
                line_chunks.setdefault(_norm_line(s), set()).add(ch["chunk_id"])
    repeated = {k for k, v in line_chunks.items() if len(v) >= 3}
    seen_body: dict[str, int] = {}
    table_count: dict[str, int] = {}
    for ch in chunks:
        if ch["table_id"] and ch["chunk_type"] == "table":
            table_count[ch["table_id"]] = table_count.get(ch["table_id"], 0) + 1
    out = []
    for i, ch in enumerate(chunks):
        b = bodies[ch["chunk_id"]]
        flags = []
        n = len(b.strip())
        if ch["chunk_type"] == "text" and n < min_len and len(chunks) > 1:
            flags.append(_flag("short", "warn", f"너무 짧음({n}자) — 앞뒤 청크와 합치거나 잡음이면 지우세요."))
        if n > max_len:
            flags.append(_flag("long", "warn", f"너무 김({n}자) — 문장 사이에서 나누세요."))
        nxt = chunks[i + 1] if i + 1 < len(chunks) else None
        tail = b.rstrip()
        if (ch["chunk_type"] == "text" and nxt and nxt["chunk_type"] == "text" and nxt["section_id"] == ch["section_id"]
                and tail and not _SENT_END.search(tail)):
            flags.append(_flag("broken", "info", "문장이 중간에서 끊긴 채 다음 청크로 넘어감 — 다음 청크와 합칠지 보세요."))
        if ch["table_id"] and table_count.get(ch["table_id"], 0) > 1:
            flags.append(_flag("table_split", "info", f"표 하나가 청크 {table_count[ch['table_id']]}개로 나뉨 — 표 묶기 규칙을 쓸 수 있습니다."))
        noise = []
        for ln in b.split("\n"):
            s = ln.strip()
            if not s:
                continue
            if _PAGE_NO.match(s):
                noise.append({"line": s, "why": "쪽 번호"})
            elif _norm_line(s) in repeated and len(s) <= 80:
                noise.append({"line": s, "why": "여러 청크에 되풀이(머리글·바닥글)"})
        if noise:
            flags.append(_flag("noise", "warn", f"잡음으로 보이는 줄 {len(noise)}개 — 줄을 골라 '잡음 줄 지우기'.",
                               lines=noise[:10]))
        key = re.sub(r"\s+", " ", b.strip())
        if len(key) >= 30:
            if key in seen_body:
                flags.append(_flag("dup", "warn", f"#{seen_body[key] + 1} 청크와 글이 같음 — 하나를 지우세요."))
            else:
                seen_body[key] = ch["ord"]
        try:
            meta = json.loads(ch["bbox"]) if ch["bbox"] else None
        except ValueError:
            meta = None
        conf = None
        if isinstance(meta, dict):
            conf = meta.get("ocr_conf", meta.get("ocr_confidence"))
        if isinstance(conf, (int, float)) and conf < OCR_LOW:
            flags.append(_flag("ocr_low", "warn", f"글자 인식(OCR) 신뢰도가 낮음({conf:.2f}) — 원본과 대조해 고치세요."))
        cnt = counts.get(ch["chunk_id"]) or {}
        if cnt.get("lost"):
            flags.append(_flag("attention", "warn", f"위치를 잃은 사람 라벨 {cnt['lost']}개 — 라벨 탭에서 자리를 다시 잡으세요."))
        out.append({"chunk_id": ch["chunk_id"], "ord": ch["ord"], "page": ch["page"], "section_id": ch["section_id"],
                    "heading": ch["heading"], "chunk_type": ch["chunk_type"], "table_id": ch["table_id"],
                    "text": ch["text"], "prefix_len": len(heading_prefix(ch)), "length": n,
                    "annotations": cnt.get("n", 0), "pending": cnt.get("pending", 0) or 0,
                    "lost": cnt.get("lost", 0) or 0, "flags": flags})
    summary: dict[str, int] = {}
    for o in out:
        for f in o["flags"]:
            summary[f["code"]] = summary.get(f["code"], 0) + 1
    return {"doc_id": doc_id, "min_len": min_len, "max_len": max_len, "chunks": out, "summary": summary,
            "flagged_chunks": sum(1 for o in out if o["flags"])}
