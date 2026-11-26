"""파일 → 구조화된 블록. LLM을 쓰지 않는다.

반환 형식: {"blocks": [{"type": "heading|text|table", "text": str, "page": int|None,
                       "level": int (heading), "rows": [[...]] (table)}], "meta": {...}}

OCR(로컬, 선택 설치): 스캔 PDF 쪽과 사진·스캔 이미지는 RapidOCR이 설치되어 있을 때만 글자를 읽는다.
이미지가 이 PC 밖으로 나가는 일은 없다(완전히 로컬 처리). 설치: install-ocr.bat.
"""
from __future__ import annotations

import re
import statistics
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

PARSER_VER = "m2-ocr-1"
SUPPORTED = {".pdf", ".hwpx", ".xlsx", ".xlsm", ".txt", ".md", ".csv",
             ".png", ".jpg", ".jpeg", ".tif", ".tiff"}

OCR_DPI = 250                # 스캔 쪽을 이미지로 찍는 해상도(200~300dpi 권장)
OCR_CONF_THRESHOLD = 0.6     # 이보다 신뢰도가 낮은 줄은 버린다
_SCAN_CHARS_PER_PAGE = 50    # 기존 스캔본 판정 기준(쪽당 글자 수) — OCR 대상 쪽 판정에도 그대로 쓴다


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
    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        return parse_image(path)
    if ext == ".hwp":
        raise UnsupportedFile("HWP(구 형식)는 기본 파서로 읽지 못합니다. install-kordoc.bat으로 kordoc 도구를 설치하거나 "
                              "한글에서 'HWPX로 저장' 후 넣어 주세요.")
    raise UnsupportedFile(f"지원하지 않는 형식: {ext}")


# ---------------------------------------------------------------- OCR (로컬, 선택 설치)

def ocr_available() -> bool:
    """RapidOCR 설치 여부만 확인한다(지연 임포트). 미설치여도 앱이 죽지 않는다."""
    try:
        import rapidocr  # noqa: F401
    except ImportError:
        return False
    return True


_ocr_engine = None  # 모듈 수준에서 1회만 만든다(모델 로딩 비용이 크다)


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import LangRec, ModelType, OCRVersion

        # 기본 인식 모델은 중국어·영어 위주라 한국어 인식 모델(PP-OCRv5, mobile)을 지정해 고른다.
        # 처음 쓸 때 모델을 인터넷에서 내려받는다(install-ocr.bat 참고).
        _ocr_engine = RapidOCR(params={
            "Rec.lang_type": LangRec.KOREAN,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
            "Rec.model_type": ModelType.MOBILE,
        })
    return _ocr_engine


def _ocr_lines(image) -> list[dict]:
    """image: 파일 경로(str/Path), PNG 등 bytes, numpy 배열 모두 받는다.
    반환: [{"text": str, "box": [[x,y]*4], "score": float}, ...] — 신뢰도가 낮은 줄은 버린다.
    시험에서는 이 함수를 모킹해 실제 엔진 없이 이후(단락 묶기·표 복원) 로직을 검증한다.
    """
    engine = _get_ocr_engine()
    result = engine(image)
    if not result or not result.txts:
        return []
    out = []
    for txt, box, score in zip(result.txts, result.boxes, result.scores):
        if score < OCR_CONF_THRESHOLD:
            continue
        out.append({"text": txt, "box": [[float(x), float(y)] for x, y in box], "score": float(score)})
    return out


def _xcenter(line: dict) -> float:
    xs = [p[0] for p in line["box"]]
    return (min(xs) + max(xs)) / 2


def _width(line: dict) -> float:
    xs = [p[0] for p in line["box"]]
    return max(xs) - min(xs) or 1.0


def _ycenter(line: dict) -> float:
    ys = [p[1] for p in line["box"]]
    return (min(ys) + max(ys)) / 2


def _height(line: dict) -> float:
    ys = [p[1] for p in line["box"]]
    return max(ys) - min(ys) or 1.0


def _rows_from_ocr_lines(lines: list[dict]) -> list[list[dict]]:
    """OCR 줄 상자를 세로 위치로 묶어 화면상의 '행'을 만든다(위→아래, 각 행은 왼→오로 정렬)."""
    rows: list[list[dict]] = []
    for ln in sorted(lines, key=_ycenter):
        yc, h = _ycenter(ln), _height(ln)
        for row in rows:
            ref = row[0]
            if abs(yc - _ycenter(ref)) < 0.6 * max(h, _height(ref)):
                row.append(ln)
                break
        else:
            rows.append([ln])
    for row in rows:
        row.sort(key=_xcenter)
    return rows


def _reconstruct_table(lines: list[dict]) -> list[list[str]] | None:
    """행·열이 맞춰진 OCR 상자를 표로 복원한다(≥2행 × ≥2열일 때만). 맞지 않으면 None(단락으로 처리)."""
    rows = _rows_from_ocr_lines(lines)
    if len(rows) < 2:
        return None
    ref_row = max(rows, key=len)
    if len(ref_row) < 2:
        return None
    centers = sorted(_xcenter(c) for c in ref_row)
    avg_w = sum(_width(c) for c in ref_row) / len(ref_row)
    cols: list[float] = []
    for xc in centers:
        if cols and xc - cols[-1] < avg_w * 0.8:
            cols[-1] = (cols[-1] + xc) / 2  # 가까운 기준 열은 하나로 합친다
        else:
            cols.append(xc)
    if len(cols) < 2:
        return None
    table_rows, used_cols = [], set()
    for row in rows:
        cells = [""] * len(cols)
        for cell in row:
            idx = min(range(len(cols)), key=lambda i: abs(cols[i] - _xcenter(cell)))
            cells[idx] = (cells[idx] + " " + cell["text"]).strip() if cells[idx] else cell["text"]
            used_cols.add(idx)
        table_rows.append(cells)
    if len(used_cols) < 2:
        return None
    return table_rows


def _paragraphs_from_ocr_lines(lines: list[dict], page: int | None) -> list[dict]:
    """표가 아닌 OCR 줄을 세로 간격 기준으로 단락으로 묶는다(간격이 줄 높이의 1.2배를 넘으면 새 단락)."""
    rows = _rows_from_ocr_lines(lines)
    if not rows:
        return []
    median_h = statistics.median(max(_height(c) for c in row) for row in rows)
    blocks, buf, prev_bottom = [], [], None
    for row in rows:
        top = min(min(p[1] for p in c["box"]) for c in row)
        bottom = max(max(p[1] for p in c["box"]) for c in row)
        text = " ".join(c["text"] for c in row)
        if prev_bottom is not None and (top - prev_bottom) > median_h * 1.2 and buf:
            blocks.append({"type": "text", "text": " ".join(buf), "page": page})
            buf = []
        buf.append(text)
        prev_bottom = bottom
    if buf:
        blocks.append({"type": "text", "text": " ".join(buf), "page": page})
    return blocks


def _blocks_from_ocr(lines: list[dict], page: int | None) -> list[dict]:
    """표 복원을 먼저 시도하고, 표가 아니면 단락으로 묶는다."""
    if not lines:
        return []
    table = _reconstruct_table(lines)
    if table:
        return [{"type": "table", "rows": table, "page": page, "text": _rows_text(table)}]
    return _paragraphs_from_ocr_lines(lines, page)


def parse_image(path: Path) -> dict:
    """사진·스캔 이미지(.png/.jpg/.jpeg/.tif/.tiff) → OCR → 블록. 표처럼 줄맞춰진 글자는 표로 묶는다."""
    if not ocr_available():
        raise UnsupportedFile("이미지는 로컬 OCR 확장이 있어야 읽을 수 있습니다. install-ocr.bat을 실행하세요.")
    lines = _ocr_lines(str(path))
    blocks = _blocks_from_ocr(lines, None)
    meta = {"ocr": True, "ocr_lines": len(lines),
            "ocr_mean_conf": round(sum(ln["score"] for ln in lines) / len(lines), 4) if lines else None}
    return {"blocks": blocks, "meta": meta}


# ---------------------------------------------------------------- PDF

_HEADING = re.compile(r"^(\d+(\.\d+)*\.?|[IVX]+\.|제\s*\d+\s*[장절]|Abstract|ABSTRACT|초록|서론|결론|"
                      r"Introduction|Results?|Discussion|Conclusions?|Materials and [Mm]ethods|참고문헌|References)\b")


_SENT_END = re.compile(r"[.!?。:)\]」』]\s*$|다\.?\s*$")


def parse_pdf(path: Path) -> dict:
    import pymupdf

    blocks = []
    low_text_pages, ocr_pages, ocr_scores = [], [], []
    can_ocr = ocr_available()
    with pymupdf.open(str(path)) as doc:
        meta = {"pages": doc.page_count, "title": (doc.metadata or {}).get("title") or None}
        text_chars = 0
        for pno, page in enumerate(doc, start=1):
            page_blocks = []
            # 표 먼저 찾고, 표 영역의 글자는 본문에서 뺀다
            table_rects = []
            try:
                for t in page.find_tables().tables:
                    rows = [[(c or "").strip() for c in r] for r in t.extract()]
                    rows = [r for r in rows if any(r)]
                    if len(rows) >= 2:
                        page_blocks.append({"type": "table", "rows": rows, "page": pno, "text": _rows_text(rows)})
                        table_rects.append(pymupdf.Rect(t.bbox))
            except Exception:  # 표 인식 실패는 본문만으로 진행
                pass
            page_chars = 0
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
                page_chars += len(txt)
                if len(txt) < 80 and "\n" not in txt and _HEADING.match(txt):
                    page_blocks.append({"type": "heading", "text": txt, "level": 1, "page": pno})
                elif (page_blocks and page_blocks[-1]["type"] == "text" and not _SENT_END.search(page_blocks[-1]["text"])):
                    page_blocks[-1]["text"] += " " + txt   # 문장이 끝나지 않은 블록은 이어 붙인다(줄·단·쪽 넘김)
                else:
                    page_blocks.append({"type": "text", "text": txt, "page": pno})
            text_chars += page_chars
            if page_chars < _SCAN_CHARS_PER_PAGE:
                low_text_pages.append(pno)
                if can_ocr:
                    try:
                        png = page.get_pixmap(dpi=OCR_DPI).tobytes("png")
                        ocr_lines = _ocr_lines(png)
                    except Exception:
                        ocr_lines = []
                    if ocr_lines:
                        page_blocks.extend(_blocks_from_ocr(ocr_lines, pno))
                        ocr_pages.append(pno)
                        ocr_scores.extend(ln["score"] for ln in ocr_lines)
            blocks.extend(page_blocks)
        unresolved = [p for p in low_text_pages if p not in ocr_pages]
        meta["needs_ocr"] = bool(unresolved)  # OCR이 없거나 실패해 글자를 못 채운 쪽이 남아 있을 때만
        if ocr_pages:
            meta["ocr_pages"] = ocr_pages
            meta["ocr_mean_conf"] = round(sum(ocr_scores) / len(ocr_scores), 4) if ocr_scores else None
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
