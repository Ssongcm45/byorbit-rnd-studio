"""PyMuPDF — 지금까지 쓰던 기본 PDF 파서(parsers.parse_pdf). 빠르고, 글자가 적은 쪽만 로컬 OCR로 보충한다."""
from __future__ import annotations

from .. import parsers
from .base import Tool, pkg_version


def _status() -> dict:
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        return {"ready": False, "message": "PyMuPDF가 없습니다. install.bat을 다시 실행하세요."}
    return {"ready": True}


def _parse(path, options: dict) -> dict:
    return parsers.parse_pdf(path)


TOOL = Tool(
    key="pymupdf", name="PyMuPDF (기본)", formats={".pdf"}, kind="local",
    description="지금까지 쓰던 기본 PDF 파서. 글자 블록·선이 있는 표를 읽고, 글자가 거의 없는 쪽은 로컬 OCR(설치 시)로 보충합니다.",
    strengths="가장 빠름 · 일반 논문 PDF에 충분 · 추가 설치 없음",
    install_hint="install.bat에 포함되어 있습니다.",
    parse_fn=_parse, status_fn=_status, version_fn=lambda: pkg_version("pymupdf"),
)
