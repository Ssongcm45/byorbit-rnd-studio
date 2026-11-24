"""MCP 서버 'byorbit-rd' (stdio). Claude Code·Codex가 --mcp-config로 띄워서 쓴다.

직접 실행: python -m app.mcp_server
"""
from __future__ import annotations

import logging
import sys

from mcp.server.mcpserver import MCPServer

from . import db, tools

INSTRUCTIONS = """ByOrbit 부산물 R&D 자료 서버입니다. 이 PC에 저장된 논문·보고서·CoA에서 찾은 내용만 근거로 쓰세요.
- 용어는 lookup_concept으로 표준명을 먼저 확인하고, search_chunks → get_chunk 순서로 원문을 읽으세요.
- 수치는 반드시 원문(청크) 또는 측정값(query_measurements)에서 가져오고, 근거 없이 숫자를 만들지 마세요.
- 라벨은 save_annotations로 저장합니다. surface는 원문 그대로, 수치가 있으면 사람 검토를 거칩니다.
- 리포트는 save_report_draft로 저장합니다. 수치 문장마다 [1] 같은 근거 번호를 다세요.
- [가림]으로 표시된 값은 기밀 식별 정보입니다. 추측하거나 복원하지 마세요."""


def build() -> MCPServer:
    server = MCPServer("byorbit-rd", instructions=INSTRUCTIONS, version="0.1.0", log_level="WARNING")
    for fn in tools.TOOLS:
        server.add_tool(fn)
    return server


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)  # stdout은 MCP 통신 전용
    db.init(seed=True)
    build().run(transport="stdio")


if __name__ == "__main__":
    main()
