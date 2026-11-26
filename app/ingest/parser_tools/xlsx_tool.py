"""엑셀(.xlsx/.xlsm) 기본 파서(parsers.parse_xlsx) — 시트마다 제목 + 표 하나."""
from __future__ import annotations

from .. import parsers
from .base import Tool, pkg_version


def _parse(path, options: dict) -> dict:
    return parsers.parse_xlsx(path)


TOOL = Tool(
    key="xlsx", name="엑셀 기본", formats={".xlsx", ".xlsm"}, kind="local",
    description="시트마다 '시트: 이름' 제목과 표 하나를 만듭니다. CoA 측정값은 파서와 따로 읽습니다.",
    strengths="추가 설치 없음 · 수식은 계산된 값으로 읽음",
    install_hint="install.bat에 포함되어 있습니다.",
    parse_fn=_parse, status_fn=lambda: {"ready": True}, version_fn=lambda: pkg_version("openpyxl"),
)
