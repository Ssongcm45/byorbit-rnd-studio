"""AI 엔진 어댑터. 기본은 Claude Code, Codex는 보조(2단계에서 연결)."""
from __future__ import annotations

from .. import config
from . import claude_code, codex

ENGINES = {"claude": claude_code, "codex": codex}


def get(name: str | None = None):
    return ENGINES.get(name or config.load_settings().get("engine", "claude"), claude_code)
