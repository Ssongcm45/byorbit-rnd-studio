"""pdfplumber — 글자 하나하나의 위치로 줄·단락·표를 다시 짠다. 선이 있는 표를 잘 읽는다.

PyMuPDF와 다른 방식(pdfminer.six 글자 위치)이라, 표가 많은 문서에서 두 결과를 나란히 비교할 때 쓴다.
OCR은 하지 않는다(스캔본은 RapidOCR 도구).
"""
from __future__ import annotations

import re
import statistics

from .base import NotReady, Tool, looks_like_heading, pkg_version, table_block

HINT = "pdfplumber가 없습니다. install.bat을 다시 실행하거나 .venv\\Scripts\\python -m pip install -r requirements.txt 를 실행하세요."


def _status() -> dict:
    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        return {"ready": False, "message": "pdfplumber가 설치되어 있지 않습니다.", "hint": HINT}
    return {"ready": True}


def _inside(obj, boxes) -> bool:
    cx, cy = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
    return any(x0 <= cx <= x1 and t <= cy <= b for x0, t, x1, b in boxes)


def _join(lines: list[str]) -> str:
    out = ""
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        if out.endswith("-") and ln[:1].islower():
            out = out[:-1] + ln
        else:
            out = f"{out} {ln}" if out else ln
    return re.sub(r"[ \t]+", " ", out).strip()


def page_blocks(page, pno: int, table_settings: dict | None = None) -> list[dict]:
    """한 쪽 → 블록(위→아래 순서). 표 영역 안의 글자는 본문에서 뺀다."""
    items = []  # (top, block)
    boxes = []
    for t in page.find_tables(table_settings or {}):
        blk = table_block(t.extract(), pno)
        if blk and len(blk["rows"]) >= 2:
            items.append((t.bbox[1], blk))
            boxes.append(t.bbox)
    rest = page.filter(lambda o: o.get("object_type") != "char" or not _inside(o, boxes)) if boxes else page
    lines = rest.extract_text_lines(return_chars=True, strip=True)
    lines = [ln for ln in lines if ln.get("text", "").strip()]
    if lines:
        heights = [ln["bottom"] - ln["top"] for ln in lines]
        sizes = [statistics.mean(c["size"] for c in ln["chars"]) if ln.get("chars") else ln["bottom"] - ln["top"]
                 for ln in lines]
        med_h = statistics.median(heights) or 1.0
        med_size = statistics.median(sizes) or 1.0
        para, para_top, prev_bottom = [], None, None

        def flush():
            nonlocal para, para_top
            if para:
                items.append((para_top, {"type": "text", "text": _join(para), "page": pno}))
            para, para_top = [], None

        for ln, size in zip(lines, sizes):
            txt = ln["text"].strip()
            big = size > med_size * 1.15
            if (big and len(txt) < 100) or looks_like_heading(txt):
                flush()
                level = 1 if size > med_size * 1.3 else 2
                items.append((ln["top"], {"type": "heading", "text": txt, "level": level, "page": pno}))
                prev_bottom = ln["bottom"]
                continue
            if prev_bottom is not None and ln["top"] - prev_bottom > med_h * 1.0:
                flush()
            if para_top is None:
                para_top = ln["top"]
            para.append(txt)
            prev_bottom = ln["bottom"]
        flush()
    items.sort(key=lambda x: x[0])
    return [b for _, b in items]


def _parse(path, options: dict) -> dict:
    try:
        import pdfplumber
    except ImportError as e:
        raise NotReady(HINT) from e
    settings = {}
    if options.get("table_strategy") == "text":   # 선이 없는 표: 글자 정렬로 추정
        settings = {"vertical_strategy": "text", "horizontal_strategy": "text"}
    blocks, warnings, low = [], [], []
    with pdfplumber.open(str(path)) as pdf:
        n = len(pdf.pages)
        for pno, page in enumerate(pdf.pages, start=1):
            try:
                pb = page_blocks(page, pno, settings)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"{pno}쪽 읽기 실패: {e}")
                continue
            if sum(len(b.get("text") or "") for b in pb) < 50:
                low.append(pno)
            blocks.extend(pb)
            page.flush_cache()
        title = (pdf.metadata or {}).get("Title") or None
    if low:
        warnings.append(f"글자가 거의 없는 쪽: {', '.join(map(str, low[:20]))} — 스캔본이면 RapidOCR 도구를 쓰세요.")
    return {"blocks": blocks, "meta": {"pages": n, "title": title, "needs_ocr": bool(low), "warnings": warnings}}


TOOL = Tool(
    key="pdfplumber", name="pdfplumber", formats={".pdf"}, kind="local",
    description="글자 위치로 줄·단락·표를 다시 짭니다. 선이 그어진 표를 잘 읽고, 글자 크기로 제목을 찾습니다.",
    strengths="표가 많은 PDF · 셀 경계가 분명한 성적서·보고서 · 로컬",
    install_hint=HINT, parse_fn=_parse, status_fn=_status, version_fn=lambda: pkg_version("pdfplumber"),
    options=[{"key": "table_strategy", "label": "표 찾기", "type": "select",
              "choices": [["lines", "선 기준"], ["text", "글자 정렬 기준(선 없는 표)"]], "default": "lines"}],
)
