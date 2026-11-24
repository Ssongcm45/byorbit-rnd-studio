"""파일 → 구조화된 블록. LLM을 쓰지 않는다.

반환 형식: {"blocks": [{"type": "heading|text|table", "text": str, "page": int|None,
                       "level": int (heading), "rows": [[...]] (table)}], "meta": {...}}
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

PARSER_VER = "m1-1"
SUPPORTED = {".pdf", ".hwpx", ".xlsx", ".xlsm", ".txt", ".md", ".csv"}


class UnsupportedFile(Exception):
    pass


def parse(path: Path) -> dict:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return parse_pdf(path)
    if ext == ".hwpx":
        return parse_hwpx(path)
    if ext in (".xlsx", ".xlsm"):
        return parse_xlsx(path)
    if ext in (".txt", ".md", ".csv"):
        return parse_text(path)
    if ext == ".hwp":
        raise UnsupportedFile("HWP(구 형식)는 1단계에서 지원하지 않습니다. 한글에서 'HWPX로 저장' 후 넣어 주세요.")
    raise UnsupportedFile(f"지원하지 않는 형식: {ext}")


# ---------------------------------------------------------------- PDF

_HEADING = re.compile(r"^(\d+(\.\d+)*\.?|[IVX]+\.|제\s*\d+\s*[장절]|Abstract|ABSTRACT|초록|서론|결론|"
                      r"Introduction|Results?|Discussion|Conclusions?|Materials and [Mm]ethods|참고문헌|References)\b")


_SENT_END = re.compile(r"[.!?。:)\]」』]\s*$|다\.?\s*$")


def parse_pdf(path: Path) -> dict:
    import pymupdf

    blocks = []
    with pymupdf.open(str(path)) as doc:
        meta = {"pages": doc.page_count, "title": (doc.metadata or {}).get("title") or None}
        text_chars = 0
        for pno, page in enumerate(doc, start=1):
            # 표 먼저 찾고, 표 영역의 글자는 본문에서 뺀다
            table_rects = []
            try:
                for t in page.find_tables().tables:
                    rows = [[(c or "").strip() for c in r] for r in t.extract()]
                    rows = [r for r in rows if any(r)]
                    if len(rows) >= 2:
                        blocks.append({"type": "table", "rows": rows, "page": pno, "text": _rows_text(rows)})
                        table_rects.append(pymupdf.Rect(t.bbox))
            except Exception:  # 표 인식 실패는 본문만으로 진행
                pass
            for b in page.get_text("blocks"):
                x0, y0, x1, y1, txt = b[0], b[1], b[2], b[3], b[4]
                if b[6] != 0:  # 이미지 블록
                    continue
                r = pymupdf.Rect(x0, y0, x1, y1)
                if any(r.intersects(tr) for tr in table_rects):
                    continue
                txt = _clean(txt)
                if not txt:
                    continue
                text_chars += len(txt)
                if len(txt) < 80 and "\n" not in txt and _HEADING.match(txt):
                    blocks.append({"type": "heading", "text": txt, "level": 1, "page": pno})
                elif (blocks and blocks[-1]["type"] == "text" and not _SENT_END.search(blocks[-1]["text"])):
                    blocks[-1]["text"] += " " + txt   # 문장이 끝나지 않은 블록은 이어 붙인다(줄·단·쪽 넘김)
                else:
                    blocks.append({"type": "text", "text": txt, "page": pno})
        meta["needs_ocr"] = text_chars < 50 * max(1, meta["pages"])
    return {"blocks": blocks, "meta": meta}


def _clean(s: str) -> str:
    s = s.replace("­", "")
    s = re.sub(r"-\n(?=[a-z])", "", s)          # 영어 하이픈 줄바꿈
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n(?!\n)", " ", s)             # 블록 안 줄바꿈은 공백으로
    return s.strip()


def _rows_text(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(r) for r in rows)


# ---------------------------------------------------------------- HWPX

_NS_P = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def parse_hwpx(path: Path) -> dict:
    blocks = []
    with zipfile.ZipFile(path) as z:
        sections = sorted(n for n in z.namelist() if re.match(r"Contents/section\d+\.xml$", n))
        if not sections:
            raise UnsupportedFile("HWPX 안에서 본문(section)을 찾지 못했습니다.")
        for name in sections:
            root = ET.fromstring(z.read(name))
            _walk_hwpx(root, blocks)
    return {"blocks": blocks, "meta": {"sections": len(sections)}}


def _walk_hwpx(el, blocks, in_table=False):
    for child in el:
        tag = child.tag
        if tag == f"{_NS_P}tbl":
            rows = []
            for tr in child.iter(f"{_NS_P}tr"):
                row = []
                for tc in tr.findall(f"{_NS_P}tc"):
                    row.append(" ".join(_hwpx_text(p) for p in tc.iter(f"{_NS_P}p")).strip())
                rows.append(row)
            rows = [r for r in rows if any(r)]
            if rows:
                blocks.append({"type": "table", "rows": rows, "page": None, "text": _rows_text(rows)})
        elif tag == f"{_NS_P}p" and not in_table:
            # 문단 안에 표가 들어있으면 표를 따로 꺼낸다
            if child.find(f".//{_NS_P}tbl") is not None:
                _walk_hwpx(child, blocks)
                continue
            t = _hwpx_text(child).strip()
            if t:
                kind = "heading" if (len(t) < 60 and _HEADING.match(t)) else "text"
                blocks.append({"type": kind, "text": t, "page": None, "level": 1})
        else:
            _walk_hwpx(child, blocks, in_table)


def _hwpx_text(p) -> str:
    return "".join((t.text or "") for t in p.iter(f"{_NS_P}t"))


# ---------------------------------------------------------------- XLSX / 텍스트

def parse_xlsx(path: Path) -> dict:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    blocks = []
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True):
            vals = ["" if v is None else str(v).strip() for v in r]
            if any(vals):
                rows.append(vals)
        if rows:
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            blocks.append({"type": "heading", "text": f"시트: {ws.title}", "level": 1, "page": None})
            blocks.append({"type": "table", "rows": rows, "page": None, "text": _rows_text(rows), "sheet": ws.title})
    wb.close()
    return {"blocks": blocks, "meta": {"sheets": len(wb.sheetnames)}}


def parse_text(path: Path) -> dict:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949", "euc-kr", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    blocks = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if para.startswith("#"):
            blocks.append({"type": "heading", "text": para.lstrip("# ").strip(), "level": 1, "page": None})
        else:
            blocks.append({"type": "text", "text": para, "page": None})
    return {"blocks": blocks, "meta": {}}
