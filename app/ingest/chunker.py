"""블록 → 섹션·표·청크. 제목 경계를 지키고, 표는 행 단위 문장으로 풀어 따로 둔다."""
from __future__ import annotations

TARGET = 1200   # 청크 목표 글자 수
OVERLAP = 150   # 앞 청크 끝을 다음 청크 앞에 겹치는 글자 수
TABLE_ROWS = 25  # 표 청크 하나에 넣을 최대 행 수


def build(blocks: list[dict]) -> dict:
    """반환: {"sections": [...], "tables": [...], "chunks": [...]} — id는 순번(로드할 때 UUID로 바꾼다)."""
    sections, tables, chunks = [], [], []
    cur_sec = {"key": 0, "heading": "(머리말)", "page_from": None, "page_to": None}
    sections.append(cur_sec)
    buf, buf_page = "", None

    def flush(final=False):
        nonlocal buf, buf_page
        text = buf.strip()
        while len(text) > TARGET * 1.3 or (final and text):
            if len(text) <= TARGET * 1.3:
                cut = len(text)
            else:
                cut = _cut_point(text, TARGET)
            piece = text[:cut].strip()
            if piece:
                chunks.append({"type": "text", "section": cur_sec["key"], "text": _with_heading(cur_sec, piece),
                               "page": buf_page})
            if cut >= len(text):
                text = ""
                break
            text = text[max(0, cut - OVERLAP):].lstrip()
        buf = text
        if final:
            buf = ""

    for b in blocks:
        page = b.get("page")
        if b["type"] == "heading":
            flush(final=True)
            cur_sec = {"key": len(sections), "heading": b["text"], "page_from": page, "page_to": page}
            sections.append(cur_sec)
            buf_page = page
            continue
        if page is not None:
            cur_sec["page_from"] = cur_sec["page_from"] or page
            cur_sec["page_to"] = page
        if b["type"] == "table":
            flush(final=True)
            tkey = len(tables)
            rows = b["rows"]
            tables.append({"key": tkey, "section": cur_sec["key"], "rows": rows, "page": page,
                           "caption": b.get("sheet") or cur_sec["heading"]})
            header, body = rows[0], rows[1:] or []
            for i in range(0, max(1, len(body)), TABLE_ROWS):
                part = body[i:i + TABLE_ROWS]
                lines = [_row_sentence(header, r) for r in part] if part else [" | ".join(header)]
                chunks.append({"type": "table", "section": cur_sec["key"], "table": tkey, "page": page,
                               "text": _with_heading(cur_sec, "[표] " + " | ".join(header) + "\n" + "\n".join(lines))})
            continue
        if not buf:
            buf_page = page
        buf += ("\n\n" if buf else "") + b["text"]
        if len(buf) > TARGET * 1.3:
            flush()
    flush(final=True)
    sections = [s for s in sections if s["key"] == 0 and any(c["section"] == 0 for c in chunks) or s["key"] != 0]
    return {"sections": sections, "tables": tables, "chunks": chunks}


def _with_heading(sec: dict, text: str) -> str:
    h = sec["heading"]
    return text if h == "(머리말)" else f"{h}\n{text}"


def _row_sentence(header: list[str], row: list[str]) -> str:
    pairs = []
    for h, v in zip(header, row):
        if v:
            pairs.append(f"{h}: {v}" if h else v)
    return "; ".join(pairs)


def _cut_point(text: str, target: int) -> int:
    """target 근처의 문장·문단 경계."""
    window = text[int(target * 0.7): int(target * 1.3)]
    base = int(target * 0.7)
    for sep in ("\n\n", ". ", "다. ", "。", "; ", ", ", " "):
        i = window.rfind(sep)
        if i >= 0:
            return base + i + len(sep)
    return target
