"""Codex CLI 어댑터 — 1단계에서는 설치 확인만 한다. 실제 작업 위임은 2단계에서 연결한다.

연결 예정 방식: codex exec --json, MCP 서버는 -c mcp_servers.byorbit-rd.command=... 로 지정.
"""
from __future__ import annotations

import shutil
import subprocess


def executable() -> str | None:
    return shutil.which("codex")


def version() -> dict:
    exe = executable()
    if not exe:
        return {"installed": False, "message": "Codex CLI(codex)를 찾지 못했습니다. 보조 엔진이라 없어도 됩니다."}
    try:
        p = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        return {"installed": p.returncode == 0, "path": exe, "version": (p.stdout or p.stderr).strip()}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"installed": False, "path": exe, "message": str(e)}


def check(smoke: bool = False, runner=None) -> dict:
    v = version()
    return {"engine": "codex", "cli": v, "ok": bool(v.get("installed")),
            "note": "Codex 작업 위임은 2단계에서 연결합니다."}


def run(prompt: str, **kw) -> dict:
    return {"ok": False, "error": "Codex 연결은 2단계에서 제공합니다. 설정에서 기본 엔진을 Claude Code로 두세요."}
