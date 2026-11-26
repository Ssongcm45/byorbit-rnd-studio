"""텍스트(.txt/.md/.csv) 기본 파서(parsers.parse_text) — 빈 줄로 단락을 나누고 '#'은 제목."""
from __future__ import annotations

from .. import parsers
from .base import Tool


def _parse(path, options: dict) -> dict:
    return parsers.parse_text(path)


TOOL = Tool(
    key="text", name="텍스트 기본", formats={".txt", ".md", ".csv"}, kind="local",
    description="빈 줄로 단락을 나누고 '#'으로 시작하는 줄을 제목으로 봅니다. UTF-8·CP949를 자동으로 고릅니다.",
    strengths="추가 설치 없음",
    install_hint="설치가 필요 없습니다.",
    parse_fn=_parse, status_fn=lambda: {"ready": True}, version_fn=lambda: parsers.PARSER_VER,
)
