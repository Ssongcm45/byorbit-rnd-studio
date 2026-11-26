"""파서 도구 공통형 — 도구 하나 = 모듈 하나(전역 TOOL).

모든 도구의 parse(path, options)는 app.ingest.parsers.parse와 같은 블록 형식을 돌려준다:
  {"blocks": [{"type": "heading|text|table", "text": str, "page": int|None, "level": int, "rows": [[...]]}],
   "meta": {...}}
registry.run()이 meta에 tool·tool_ver·duration_ms·warnings를 채운다.
"""
from __future__ import annotations

import importlib.metadata
import re
from dataclasses import dataclass, field
from typing import Callable

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


class ToolError(Exception):
    """도구 실행 실패(사용자에게 그대로 보여 줄 한국어 메시지)."""


class NotReady(ToolError):
    """설치가 안 되었거나 키가 없다 — 메시지에 해결 방법을 넣는다."""


class CloudBlocked(ToolError):
    """'기밀' 문서를 클라우드 파서로 보내려 했다 — 무조건 막는다."""


class NeedsConfirm(ToolError):
    """클라우드 파서: 화면에서 '보낸다'를 확인해야 한다('내부' 문서)."""


@dataclass
class Tool:
    key: str
    name: str
    formats: set[str]
    kind: str                                  # local | cloud
    description: str
    strengths: str
    install_hint: str
    parse_fn: Callable[[object, dict], dict]
    status_fn: Callable[[], dict]
    version_fn: Callable[[], str | None]
    options: list[dict] = field(default_factory=list)   # 화면에 그릴 선택 사항 [{key,label,type,choices,default}]
    slow: bool = False
    estimate_fn: Callable[[object, dict], dict] | None = None

    def status(self) -> dict:
        try:
            st = dict(self.status_fn())
        except Exception as e:  # noqa: BLE001 — 상태 확인이 앱을 죽이지 않게
            st = {"ready": False, "message": f"상태를 확인하지 못했습니다: {e}"}
        st.setdefault("message", "사용할 수 있습니다." if st.get("ready") else self.install_hint)
        if not st.get("ready"):
            st.setdefault("hint", self.install_hint)
        return st

    def version(self) -> str | None:
        try:
            return self.version_fn()
        except Exception:  # noqa: BLE001
            return None

    def parse(self, path, options: dict | None = None) -> dict:
        return self.parse_fn(path, dict(options or {}))

    def info(self) -> dict:
        st = self.status()
        return {"key": self.key, "name": self.name, "formats": sorted(self.formats), "kind": self.kind,
                "description": self.description, "strengths": self.strengths, "install_hint": self.install_hint,
                "ready": bool(st.get("ready")), "message": st.get("message"), "hint": st.get("hint"),
                "detail": st.get("detail"), "version": self.version() if st.get("ready") else None,
                "options": self.options, "slow": self.slow,
                "sends_file": self.kind == "cloud"}


def pkg_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def rows_text(rows: list[list[str]]) -> str:
    return "\n".join(" | ".join(r) for r in rows)


_HEADING = re.compile(r"^(\d+(\.\d+)*\.?|[IVX]+\.|제\s*\d+\s*[장절]|Abstract|ABSTRACT|초록|서론|결론|"
                      r"Introduction|Results?|Discussion|Conclusions?|Materials and [Mm]ethods|참고문헌|References)\b")


def looks_like_heading(text: str, max_len: int = 80) -> bool:
    """기존 파서와 같은 제목 판정(번호·고정 제목어). 도구가 제목 정보를 주지 않을 때 쓴다."""
    t = (text or "").strip()
    if not t or len(t) >= max_len or "\n" in t:
        return False
    m = _HEADING.match(t)
    if not m:
        return False
    rest = t[m.end():]
    if rest[:1] in (",", ")", "%") or rest[:1].isdigit():   # '991.43, 총폴리페놀은…' 같은 수치 문장
        return False
    return not re.search(r"(다\.?|요\.)$", t)   # 문장으로 끝나면 제목이 아니다


def table_block(rows: list[list], page: int | None, **extra) -> dict | None:
    rows = [["" if c is None else str(c).strip() for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return None
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    return {"type": "table", "rows": rows, "page": page, "text": rows_text(rows), **extra}


def grid_from_spans(cells: list[list[dict]], n_rows: int | None = None, n_cols: int | None = None) -> list[list[str]]:
    """병합 셀(colSpan·rowSpan)이 있는 표 → 사각 격자. 병합된 칸은 빈 칸으로 둔다(값은 첫 칸에만).
    cells가 이미 완전한 격자(모든 행 길이 = 열 수)이면 그대로 글자만 꺼낸다."""
    if not cells:
        return []
    n_cols = n_cols or max(sum(int(c.get("colSpan") or 1) for c in r) for r in cells)
    if all(len(r) == n_cols for r in cells):
        return [[str(c.get("text") or "").strip() for c in r] for r in cells]
    n_rows = max(n_rows or 0, len(cells))
    grid: list[list[str | None]] = [[None] * n_cols for _ in range(n_rows)]
    for ri, r in enumerate(cells):
        ci = 0
        for c in r:
            while ci < n_cols and grid[ri][ci] is not None:
                ci += 1
            if ci >= n_cols:
                break
            cs, rs = max(1, int(c.get("colSpan") or 1)), max(1, int(c.get("rowSpan") or 1))
            for dr in range(rs):
                for dc in range(cs):
                    if ri + dr < n_rows and ci + dc < n_cols:
                        grid[ri + dr][ci + dc] = ""
            grid[ri][ci] = str(c.get("text") or "").strip()
            ci += cs
    return [[x or "" for x in r] for r in grid]


def stats(parsed: dict) -> dict:
    """비교 표에 쓰는 통계: 쪽·블록(종류별)·표·셀·글자·OCR 쪽·경고."""
    blocks = parsed.get("blocks") or []
    meta = parsed.get("meta") or {}
    by_type: dict[str, int] = {}
    chars = cells = 0
    pages_seen = set()
    for b in blocks:
        by_type[b.get("type", "?")] = by_type.get(b.get("type", "?"), 0) + 1
        chars += len(b.get("text") or "")
        if b.get("type") == "table":
            cells += sum(len(r) for r in b.get("rows") or [])
        if b.get("page") is not None:
            pages_seen.add(b["page"])
    ocr_pages = meta.get("ocr_pages") or []
    return {"pages": meta.get("pages") or (max(pages_seen) if pages_seen else None),
            "pages_with_text": len(pages_seen), "blocks": len(blocks), "by_type": by_type,
            "headings": by_type.get("heading", 0), "texts": by_type.get("text", 0),
            "tables": by_type.get("table", 0), "table_cells": cells, "chars": chars,
            "ocr_pages": len(ocr_pages) if isinstance(ocr_pages, list) else int(ocr_pages or 0),
            "warnings": list(meta.get("warnings") or []), "duration_ms": meta.get("duration_ms"),
            "needs_ocr": bool(meta.get("needs_ocr"))}


def table_or_text(rows: list[list], page: int | None) -> dict | None:
    """한 칸·한 줄짜리 '표'는 한글 문서의 글상자(제목 상자 등)인 경우가 많다 — 본문(또는 제목) 블록으로 바꾼다."""
    blk = table_block(rows, page)
    if not blk:
        return None
    rows = blk["rows"]
    if len(rows) >= 2 and len(rows[0]) >= 2:
        return blk
    text = "\n".join(" ".join(c for c in r if c) for r in rows).strip()
    if not text:
        return None
    if looks_like_heading(text, 60):
        return {"type": "heading", "text": text, "level": 1, "page": page}
    return {"type": "text", "text": text, "page": page}
