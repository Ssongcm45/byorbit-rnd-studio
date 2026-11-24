"""Claude Code CLI를 헤드리스(-p)로 불러 일을 맡긴다.

이 PC에 설치되어 로그인된 Claude Code를 그대로 쓴다. 자료는 MCP 서버 'byorbit-rd'를 통해서만 읽고 쓰게 하고,
파일 수정·셸·웹 도구는 막는다. 설정에서 켜면 식품 영양 DB 서버 'byorbit-food'의 읽기 전용 도구도 함께 붙인다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .. import config, db
from . import food_mcp

SERVER = "byorbit-rd"
READ_TOOLS = ["search_chunks", "get_chunk", "lookup_concept", "query_measurements"]
WRITE_TOOLS = ["save_annotations", "save_report_draft", "propose_concept"]
# 주 방어는 --tools "" (내장 도구 전부 제거). 이 목록은 --tools를 모르는 오래된 CLI용 이중 방어다.
# Read·Glob·Grep을 열어 두면 library\의 CoA 원본을 가림 없이 읽을 수 있으므로 반드시 막는다.
BLOCKED = ("Bash,PowerShell,Edit,Write,MultiEdit,NotebookEdit,NotebookRead,Read,Glob,Grep,LS,"
           "WebFetch,WebSearch,Task,Agent")


def executable() -> str | None:
    # Windows: npm 설치는 claude.cmd, 네이티브 설치는 claude.exe — which가 PATHEXT로 둘 다 찾는다
    exe = os.environ.get("BYORBIT_CLAUDE") or shutil.which("claude")
    if not exe and sys.platform == "win32":
        for p in (Path.home() / ".local" / "bin" / "claude.exe",
                  Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd"):
            if p.exists():
                return str(p)
    return exe


def mcp_config_path() -> Path:
    return config.path("config", "mcp.json")


def write_mcp_config() -> Path:
    """Claude Code가 띄울 MCP 서버 설정. 지금 쓰는 파이썬(가상환경)으로 app.mcp_server를 실행한다.
    식품 DB가 켜져 있고 준비되었으면 byorbit-food도 넣는다(시크릿 없음 — 그 서버가 자기 .env.local을 읽는다)."""
    cfg = {"mcpServers": {SERVER: {
        "type": "stdio",
        "command": sys.executable,
        "args": ["-m", "app.mcp_server"],
        "env": {"PYTHONPATH": str(config.APP_ROOT), "BYORBIT_HOME": str(config.data_home()),
                "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    }}}
    food = food_mcp.server_config()
    if food:
        cfg["mcpServers"][food_mcp.SERVER] = food
    p = mcp_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def version() -> dict:
    exe = executable()
    if not exe:
        return {"installed": False, "message": "Claude Code(claude)를 찾지 못했습니다. 설치 후 터미널에서 'claude'로 로그인하세요."}
    try:
        p = subprocess.run([exe, "--version"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        return {"installed": p.returncode == 0, "path": exe, "version": (p.stdout or p.stderr).strip()}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"installed": False, "path": exe, "message": str(e)}


def allowed_tools(write: bool = True) -> list[str]:
    names = READ_TOOLS + (WRITE_TOOLS if write else [])
    return [f"mcp__{SERVER}__{n}" for n in names] + food_mcp.allowed_tools()


def disallowed_tools() -> str:
    # 식품 서버의 extract_label_table(파일·URL 읽기)은 켜짐 여부와 관계없이 늘 막는다
    return ",".join([BLOCKED] + food_mcp.blocked_tools())


def agent_instructions(role: str | None) -> str | None:
    if not role:
        return None
    for base in (config.path("agents"), config.APP_ROOT / "agents"):
        f = base / f"{role}.md"
        if f.exists():
            return f.read_text(encoding="utf-8")
    return None


def build_command(exe: str, role_file: Path | None, write: bool, max_turns: int | None,
                  model: str | None = None, no_builtin_tools: bool = True) -> list[str]:
    cmd = [exe, "-p", "--output-format", "json",
           "--mcp-config", str(mcp_config_path()), "--strict-mcp-config"]
    if no_builtin_tools:
        cmd += ["--tools", ""]  # 내장 도구(파일 읽기 포함) 없음 — 자료는 MCP 도구로만
    cmd += ["--allowedTools", ",".join(allowed_tools(write)),
            "--disallowedTools", disallowed_tools()]
    if role_file:
        cmd += ["--append-system-prompt-file", str(role_file)]
    if max_turns:
        cmd += ["--max-turns", str(max_turns)]
    if model:
        cmd += ["--model", model]
    return cmd


def run(prompt: str, role: str | None = None, write: bool = True, max_turns: int | None = 30,
        timeout: int | None = None, task: str = "ask", run_id: str | None = None,
        runner=subprocess.run) -> dict:
    """프롬프트는 표준입력으로 보낸다(Windows 명령줄 길이·따옴표 문제를 피하려고).
    반환: {"ok", "result", "session_id", "duration_ms", "cost_usd", "raw"}"""
    exe = executable()
    if not exe:
        return {"ok": False, "error": "Claude Code를 찾지 못했습니다."}
    write_mcp_config()  # 매번 새로 쓴다 — 식품 DB 켜기·끄기 같은 설정 변경이 바로 반영되도록
    timeout = timeout or int(config.load_settings().get("claude_timeout_sec", 600))
    role_text = agent_instructions(role)
    if role_text and food_mcp.active():
        role_text = f"{role_text}\n\n{food_mcp.GUIDE}"
    role_file = None
    if role_text:
        role_file = config.path("config", f".role-{role}.md")
        role_file.write_text(role_text, encoding="utf-8")

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    t0 = time.time()

    def _call(cmd, stdin):
        return runner(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                      timeout=timeout, cwd=str(config.data_home()), env=env)

    try:
        use_file, no_builtin, stdin = role_file, True, prompt
        p = _call(build_command(exe, use_file, write, max_turns, no_builtin_tools=no_builtin), stdin)
        # 오래된 CLI가 모르는 옵션이 있으면 그 옵션만 빼고 다시 시도(최대 2번)
        #  --append-system-prompt-file → 지시문을 프롬프트 앞에 붙인다
        #  --tools → 빼도 --disallowedTools가 Read·Glob·Grep 등을 막는다
        for _ in range(2):
            err = p.stderr or ""
            if p.returncode == 0:
                break
            if use_file and "append-system-prompt-file" in err:
                use_file, stdin = None, f"{role_text}\n\n---\n\n{prompt}"
            elif no_builtin and "unknown option" in err and "'--tools'" in err:
                no_builtin = False
            else:
                break
            p = _call(build_command(exe, use_file, write, max_turns, no_builtin_tools=no_builtin), stdin)
    except subprocess.TimeoutExpired:
        _usage(run_id, None, task, int((time.time() - t0) * 1000), False)
        return {"ok": False, "error": f"{timeout}초 안에 끝나지 않았습니다."}
    dur = int((time.time() - t0) * 1000)
    out = parse_output(p.stdout)
    if out is None:
        _usage(run_id, None, task, dur, False)
        return {"ok": False, "error": (p.stderr or p.stdout or "응답 없음").strip()[:2000], "returncode": p.returncode}
    ok = not out.get("is_error") and p.returncode == 0
    _usage(run_id, out.get("session_id"), task, dur, ok)
    return {"ok": ok, "result": out.get("result", ""), "session_id": out.get("session_id"),
            "duration_ms": out.get("duration_ms", dur), "cost_usd": out.get("total_cost_usd"),
            "num_turns": out.get("num_turns"), "subtype": out.get("subtype"), "raw": out}


def parse_output(stdout: str | None) -> dict | None:
    """--output-format json 결과. 앞뒤에 다른 줄이 섞여 있어도 마지막 result 객체를 찾는다."""
    if not stdout:
        return None
    s = stdout.strip()
    try:
        obj = json.loads(s)
        if isinstance(obj, list):  # 일부 버전은 메시지 배열을 낸다
            obj = next((m for m in reversed(obj) if isinstance(m, dict) and m.get("type") == "result"), None)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        for line in reversed(s.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "result":
                        return obj
                except json.JSONDecodeError:
                    continue
    return None


def _usage(run_id, session_id, task, dur, ok):
    try:
        with db.tx() as c:
            c.execute("INSERT INTO usage_log(usage_id, run_id, engine, session_id, task, duration_ms, ok) "
                      "VALUES (?,?, 'claude', ?,?,?,?)", (db.new_id(), run_id, session_id, task, dur, int(ok)))
    except Exception:
        pass


SMOKE_PROMPT = ("byorbit-rd 도구 lookup_concept을 term='사과 포마스'로 한 번 호출하고, "
                "결과의 첫 번째 pref_label 값만 한 단어로 답하세요. 다른 말은 하지 마세요.")


def check(smoke: bool = True, runner=subprocess.run) -> dict:
    """연결 점검: ① 설치·버전 ② MCP 설정 파일 ③ (선택) 실제로 도구를 불러 '사과박'을 받아오는지."""
    v = version()
    res = {"engine": "claude", "cli": v, "mcp_config": str(write_mcp_config()), "smoke": None,
           "food": food_mcp.status()}
    if not v.get("installed") or not smoke:
        res["ok"] = bool(v.get("installed")) and not smoke
        return res
    r = run(SMOKE_PROMPT, role=None, write=False, max_turns=4, timeout=180, task="check", runner=runner)
    passed = r.get("ok") and "사과박" in (r.get("result") or "")
    res["smoke"] = {"passed": bool(passed), "answer": (r.get("result") or r.get("error") or "")[:500],
                    "duration_ms": r.get("duration_ms")}
    msg = (r.get("error") or r.get("result") or "").lower()
    if not passed and any(k in msg for k in ("login", "auth", "api key", "credit", "subscription")):
        res["hint"] = "터미널에서 'claude'를 한 번 실행해 로그인하세요."
    elif not passed:
        res["hint"] = ("도구 호출이 확인되지 않았습니다. 'claude mcp list'로 서버가 보이는지, "
                       "설정 → 연결 점검의 MCP 설정 경로가 맞는지 확인하세요.")
    res["ok"] = bool(passed)
    return res
