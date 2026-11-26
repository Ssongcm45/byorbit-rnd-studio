"""RapidOCR — 모든 쪽을 이미지로 찍어 로컬 OCR로 읽는다(글자층을 믿지 않는다).

글자층이 깨진 PDF(복사하면 이상한 글자가 나오는 PDF)·스캔본·CoA 사진에 쓴다. 이미지는 PC 밖으로 나가지 않는다.
OCR 줄 → 단락·표 복원은 parsers의 기존 함수(_ocr_lines·_blocks_from_ocr)를 그대로 쓴다.
"""
from __future__ import annotations

from pathlib import Path

from .. import parsers
from .base import IMAGE_EXTS, NotReady, Tool, pkg_version

HINT = "install-ocr.bat을 실행해 로컬 OCR(RapidOCR)을 설치하세요. 처음 실행할 때 한국어 인식 모델(약 20~25MB)을 받습니다."


def _status() -> dict:
    if not parsers.ocr_available():
        return {"ready": False, "message": "RapidOCR이 설치되어 있지 않습니다.", "hint": HINT}
    return {"ready": True}


def _parse(path, options: dict) -> dict:
    if not parsers.ocr_available():
        raise NotReady("RapidOCR이 설치되어 있지 않습니다. " + HINT)
    path = Path(path)
    if path.suffix.lower() in IMAGE_EXTS:
        out = parsers.parse_image(path)
        out["meta"]["pages"] = 1
        out["meta"]["ocr_pages"] = [1] if out["blocks"] else []
        for b in out["blocks"]:
            b["page"] = b.get("page") or 1
        return out
    import pymupdf

    dpi = int(options.get("dpi") or parsers.OCR_DPI)
    max_pages = int(options.get("max_pages") or 0)
    blocks, ocr_pages, scores, warnings = [], [], [], []
    with pymupdf.open(str(path)) as doc:
        n = doc.page_count
        for pno, page in enumerate(doc, start=1):
            if max_pages and pno > max_pages:
                warnings.append(f"{max_pages}쪽까지만 읽었습니다(전체 {n}쪽).")
                break
            try:
                png = page.get_pixmap(dpi=dpi).tobytes("png")
                lines = parsers._ocr_lines(png)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"{pno}쪽 OCR 실패: {e}")
                continue
            if not lines:
                warnings.append(f"{pno}쪽에서 글자를 찾지 못했습니다.")
                continue
            blocks.extend(_with_headings(parsers._blocks_from_ocr(lines, pno)))
            ocr_pages.append(pno)
            scores.extend(ln["score"] for ln in lines)
    meta = {"pages": n, "ocr": True, "ocr_pages": ocr_pages, "dpi": dpi, "warnings": warnings,
            "ocr_mean_conf": round(sum(scores) / len(scores), 4) if scores else None}
    return {"blocks": blocks, "meta": meta}


def _with_headings(blocks: list[dict]) -> list[dict]:
    from .base import looks_like_heading
    for b in blocks:
        if b["type"] == "text" and looks_like_heading(b["text"]):
            b["type"], b["level"] = "heading", 1
    return blocks


TOOL = Tool(
    key="rapidocr", name="RapidOCR (전 쪽 OCR)", formats={".pdf"} | IMAGE_EXTS, kind="local",
    description="모든 쪽을 그림으로 찍어 로컬 OCR로 읽습니다. 글자층이 없거나 깨진 PDF, 스캔본, 사진에 씁니다.",
    strengths="스캔본·사진 · 깨진 글자층 PDF · 완전 로컬",
    install_hint=HINT, parse_fn=_parse, status_fn=_status,
    version_fn=lambda: pkg_version("rapidocr"), slow=True,
    options=[{"key": "dpi", "label": "해상도(dpi)", "type": "select", "choices": [200, 250, 300], "default": 250}],
)
