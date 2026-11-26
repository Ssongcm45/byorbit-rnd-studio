"""Docling (선택 설치) — 레이아웃 모델로 읽기 순서·제목 단계·표 구조를 복원한다(완전 로컬).

설치: install-docling.bat (requirements-docling.txt). 패키지가 크고(PyTorch 포함 약 1~2GB),
처음 변환할 때 레이아웃·표 모델(수백 MB)을 Hugging Face에서 내려받는다. 이후에는 인터넷이 필요 없다.
문서 파일은 PC 밖으로 나가지 않는다(내려받는 것은 모델 파일뿐).
"""
from __future__ import annotations

from .base import IMAGE_EXTS, NotReady, Tool, looks_like_heading, pkg_version, table_block

HINT = ("Docling이 설치되어 있지 않습니다. install-docling.bat을 실행하세요(약 1~2GB, 처음 변환 때 모델 수백 MB를 "
        "더 받습니다).")

# Docling 항목 라벨 → 우리 블록 종류. 나머지(그림·머리글·바닥글 등)는 건너뛰고 경고에 센다.
TEXT_LABELS = {"text", "paragraph", "list_item", "caption", "footnote", "formula", "code", "reference",
               "key_value_region", "form", "checkbox_selected", "checkbox_unselected"}
HEADING_LABELS = {"title", "section_header"}
SKIP_LABELS = {"page_header", "page_footer", "picture", "chart", "document_index"}

_converters: dict = {}


def _status() -> dict:
    try:
        import importlib.util
        ok = importlib.util.find_spec("docling") is not None
    except (ImportError, ValueError):
        ok = False
    if not ok:
        return {"ready": False, "message": "Docling이 설치되어 있지 않습니다(선택 설치).", "hint": HINT}
    return {"ready": True, "detail": "처음 변환할 때 모델을 내려받아 수 분 걸릴 수 있습니다."}


def _label(item) -> str:
    lab = getattr(item, "label", "")
    return str(getattr(lab, "value", lab) or "").lower()


def _page(item) -> int | None:
    prov = getattr(item, "prov", None) or []
    return getattr(prov[0], "page_no", None) if prov else None


def _table_rows(item) -> list[list[str]]:
    data = getattr(item, "data", None)
    grid = getattr(data, "grid", None) if data is not None else None
    if grid:
        out, seen = [], set()
        for r in grid:
            row = []
            for c in r:
                # 병합 셀은 격자 여러 칸에 같은 객체로 나온다 — 첫 칸에만 글자를 둔다
                key = id(c)
                row.append("" if key in seen else str(getattr(c, "text", "") or "").strip())
                if (getattr(c, "row_span", 1) or 1) > 1 or (getattr(c, "col_span", 1) or 1) > 1:
                    seen.add(key)
            out.append(row)
        return out
    cells = getattr(data, "table_cells", None) or []
    if cells:
        nr = getattr(data, "num_rows", 0) or (max(c.end_row_offset_idx for c in cells))
        nc = getattr(data, "num_cols", 0) or (max(c.end_col_offset_idx for c in cells))
        g = [[""] * nc for _ in range(nr)]
        for c in cells:
            g[c.start_row_offset_idx][c.start_col_offset_idx] = str(c.text or "").strip()
        return g
    return []


def convert_document(doc) -> dict:
    """DoclingDocument(또는 같은 모양의 가짜) → {"blocks", "meta"}. 시험은 가짜 객체로 이 함수만 검증한다."""
    blocks, skipped, captions = [], {}, set()
    for item, level in doc.iterate_items():
        lab = _label(item)
        page = _page(item)
        if lab == "table":
            blk = table_block(_table_rows(item), page)
            if blk:
                cap = ""
                try:
                    cap = item.caption_text(doc) if hasattr(item, "caption_text") else ""
                except Exception:  # noqa: BLE001
                    cap = ""
                if cap:
                    blk["caption"] = cap
                    captions.add(cap.strip())
                blocks.append(blk)
            continue
        text = str(getattr(item, "text", "") or "").strip()
        if lab == "caption" and text in captions:   # 표 캡션은 표 블록에 이미 붙였다
            continue
        if lab in SKIP_LABELS or not text:
            if lab:
                skipped[lab] = skipped.get(lab, 0) + 1
            continue
        if lab in HEADING_LABELS:
            lv = 1 if lab == "title" else int(getattr(item, "level", None) or level or 1)
            blocks.append({"type": "heading", "text": text, "level": max(1, min(lv, 6)), "page": page})
        else:  # TEXT_LABELS와 모르는 라벨은 본문으로
            if lab == "list_item":
                marker = str(getattr(item, "marker", "") or "").strip()
                text = f"{marker} {text}".strip() if marker and not text.startswith(marker) else text
            kind = "heading" if lab == "text" and looks_like_heading(text, 60) else "text"
            b = {"type": kind, "text": text, "page": page}
            if kind == "heading":
                b["level"] = 1
            blocks.append(b)
    pages = None
    try:
        pages = len(doc.pages) or None
    except Exception:  # noqa: BLE001
        pages = max((b["page"] for b in blocks if b.get("page")), default=None)
    warnings = ["건너뛴 항목: " +", ".join(f"{k} {v}개" for k, v in sorted(skipped.items()))] if skipped else []
    return {"blocks": blocks, "meta": {"pages": pages, "warnings": warnings}}


def _converter(ocr: bool):
    if ocr in _converters:
        return _converters[ocr]
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

    po = PdfPipelineOptions()
    po.do_ocr = bool(ocr)
    po.do_table_structure = True
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=po),
                                             InputFormat.IMAGE: ImageFormatOption(pipeline_options=po)})
    _converters[ocr] = conv
    return conv


def _parse(path, options: dict) -> dict:
    try:
        import docling  # noqa: F401
    except ImportError as e:
        raise NotReady(HINT) from e
    from pathlib import Path
    ocr = bool(options.get("ocr")) or Path(path).suffix.lower() in IMAGE_EXTS
    res = _converter(ocr).convert(str(path))
    out = convert_document(res.document)
    st = getattr(res, "status", None)
    st = str(getattr(st, "value", st) or "")
    if st and st not in ("success",):
        out["meta"]["warnings"].append(f"Docling 상태: {st}")
    for e in getattr(res, "errors", None) or []:
        out["meta"]["warnings"].append(str(getattr(e, "error_message", e))[:200])
    if ocr:
        out["meta"]["ocr"] = True
    return out


TOOL = Tool(
    key="docling", name="Docling (선택 설치)", formats={".pdf"} | IMAGE_EXTS, kind="local",
    description="레이아웃 모델(IBM Docling)로 읽기 순서·제목 단계·표 구조를 복원합니다. 2단 논문·복잡한 표에 강합니다.",
    strengths="2단 논문 · 복잡한 표(병합 셀) · 제목 단계 · 완전 로컬(모델만 처음에 내려받음)",
    install_hint=HINT, parse_fn=_parse, status_fn=_status, version_fn=lambda: pkg_version("docling"), slow=True,
    options=[{"key": "ocr", "label": "OCR도 함께(스캔본)", "type": "bool", "default": False}],
)
