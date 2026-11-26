"""HWPX 기본 파서(parsers.parse_hwpx) — ZIP 안의 본문 XML을 직접 읽는다. 쪽 번호는 없다."""
from __future__ import annotations

from .. import parsers
from .base import Tool


def _parse(path, options: dict) -> dict:
    return parsers.parse_hwpx(path)


TOOL = Tool(
    key="hwpx", name="HWPX 기본", formats={".hwpx"}, kind="local",
    description="한글 HWPX(새 형식)의 문단·표를 직접 읽습니다. 쪽 번호 정보는 없습니다.",
    strengths="추가 설치 없음 · 빠름 · 표 읽기",
    install_hint="설치가 필요 없습니다.",
    parse_fn=_parse, status_fn=lambda: {"ready": True}, version_fn=lambda: parsers.PARSER_VER,
)
