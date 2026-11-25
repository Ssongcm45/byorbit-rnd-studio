"""Codex CLI를 헤드리스(codex exec --json)로 불러 일을 맡긴다 — 보조 엔진.

이 PC에 설치되어 로그인된 Codex CLI를 그대로 쓴다. 자료는 MCP 서버 'byorbit-rd'를 통해서만 읽게 하고,
셸·파일 보기·브라우저·플러그인 같은 내장 기능은 끈다.

보안(Claude Code의 --tools "" 에 해당하는 것)
- --ignore-user-config: 사용자 ~/.codex/config.toml의 MCP 서버(node_repl 등)·플러그인을 싣지 않는다.
  로그인 정보는 CODEX_HOME의 auth.json을 그대로 쓴다.
- --disable <기능>: 셸(shell_tool·unified_exec), 이미지 파일 보기(view_image), 브라우저·컴퓨터 제어,
  코드 실행 호스트, 플러그인·앱, 하위 에이전트 등을 끈다. web_search도 끈다.
- -s read-only: 혹시 남은 실행 경로가 있어도 쓰기는 막는다.
- MCP 서버마다 enabled_tools(허용 목록)를 준다. 식품 서버의 extract_label_table(파일·URL 읽기)은
  허용 목록에서 빼고 disabled_tools에도 넣는다.
- 실제 시험 결과는 PROBE에 남긴다. 파일 읽기가 막히지 않은 것으로 확인되면 FORCE_BLOCK을 켜서
  Codex 실행 동안 MCP 서버의 CoA 규칙을 '보내지 않기'(block)로 강제하고, 기밀 자료가 있으면 실행을 거부한다.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .. import config, db
from . import food_mcp
from .claude_code import READ_TOOLS, SERVER, WRITE_TOOLS, agent_instructions

# 끄는 기능. 이 버전(codex-cli 0.171.0)의 `codex features list`에 있는 이름만 넣는다 — 모르는 이름은 CLI가 오류를 낸다.
DISABLED_FEATURES = [
    "shell_tool", "unified_exec",                # 셸 — 디스크 전체를 읽을 수 있다
    "view_image",                                # 로컬 이미지 파일 읽기
    "browser_use", "browser_use_external", "in_app_browser", "computer_use",
    "apps", "plugins", "remote_plugin", "tool_suggest", "skill_mcp_dependency_install",
    "multi_agent", "image_generation", "hooks", "memories", "goals",
]
EXTRA_CONFIG = [
    'web_search="disabled"',
    'approval_policy="never"',   # 묻지 않고 진행(묻는 순간 헤드리스 실행이 멈춘다). 쓰기는 read-only가 막는다
]

FORCE_ENV = "BYORBIT_FORCE_COA_RULE"
ALLOW_CONF_ENV = "BYORBIT_CODEX_ALLOW_CONFIDENTIAL"
MODEL_ENV = "BYORBIT_CODEX_MODEL"

# 실제 CLI로 한 보안 시험 결과(위 설정 그대로). 바뀌면 다시 시험하고 고친다.
PROBE = {
    "date": "2026-11-24",
    "cli_version": "codex-cli 0.171.0",
    "shell_disabled": True,       # 셸 도구(shell·exec_command)가 도구 목록에 없었다
    "file_read_blocked": True,    # 데이터 폴더의 카나리아 파일을 어떤 방법으로도 못 읽었다
    "tools_seen": ["functions.exec(코드 모드 JS)", "functions.wait", "request_user_input_async",
                   "send_message_to_user_async", "clock.sleep", "collaboration.*(spawn_agent 등)",
                   "exec 안: apply_patch, list/read_mcp_resource(s), clock__curr_time, "
                   "mcp__byorbit_rd__{search_chunks,get_chunk,lookup_concept,query_measurements}"],
    "note": ("코드 모드 JS에는 require·process·Deno·fetch가 없고(globalThis: tools,text,store,load 등), "
             "require('fs')·fetch('file://')·import('node:fs') 모두 실패. 파일 경로를 받는 도구 없음. "
             "lookup_concept('사과 포마스') → 사과박 성공."),
}
# 파일 읽기가 막히지 않았으면(또는 확인되지 않았으면) CoA를 '보내지 않기'로 강제한다.
# 2026-11-24 시험에서 막힘이 확인되어 지금은 꺼져 있다(평소 CoA 규칙을 따른다). 강제 장치는 그대로 둔다.
FORCE_BLOCK = PROBE["file_read_blocked"] is not True


FORCE_BLOCK_ENV = "BYORBIT_CODEX_FORCE_BLOCK"  # =1 이면 시험 결과와 관계없이 강제(사용자 선택)


def force_block() -> bool:
    return FORCE_BLOCK or os.environ.get(FORCE_BLOCK_ENV) == "1"


def policy() -> dict:
    return {"force_coa_block": force_block(), "refuse_if_confidential": FORCE_BLOCK,
            "disabled_features": list(DISABLED_FEATURES), "probe": dict(PROBE)}


# ---------------------------------------------------------------- 실행 파일

def executable() -> str | None:
    return os.environ.get("BYORBIT_CODEX") or shutil.which("codex")


def _native_from_shim(shim: str) -> str | None:
    """npm 설치(codex.cmd)면 그 안의 네이티브 codex.exe를 찾는다.
    .cmd를 거치면 cmd.exe가 -c 값의 따옴표·% 를 망가뜨리고, 시간 초과 때 자식 codex.exe가 남는다."""
    base = Path(shim).resolve().parent / "node_modules" / "@openai" / "codex"
    name = "codex.exe" if sys.platform == "win32" else "codex"
    pats = [base / "node_modules" / "@openai" / "codex-*" / "vendor" / "*" / "bin" / name,
            base / "vendor" / "*" / "bin" / name]
    for pat in pats:
        hits = sorted(glob.glob(str(pat)))
        if hits:
            return hits[0]
    return None


def command_prefix() -> list[str] | None:
    exe = executable()
    if not exe:
        return None
    if Path(exe).suffix.lower() in (".cmd", ".bat", ".ps1", "") and sys.platform == "win32":
        native = _native_from_shim(exe)
        if native:
            return [native]
    return [exe]


def version() -> dict:
    pre = command_prefix()
    if not pre:
        return {"installed": False, "message": "Codex CLI(codex)를 찾지 못했습니다. 보조 엔진이라 없어도 됩니다. "
                                               "쓰려면 'npm i -g @openai/codex' 후 터미널에서 'codex login'을 하세요."}
    try:
        p = subprocess.run(pre + ["--version"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
        return {"installed": p.returncode == 0, "path": pre[0], "version": (p.stdout or p.stderr).strip()}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"installed": False, "path": pre[0], "message": str(e)}


# ---------------------------------------------------------------- 명령 만들기

def toml_str(s: str) -> str:
    """TOML 기본 문자열. JSON 문자열 이스케이프(\\\\, \\", \\uXXXX)는 TOML과 같다 — Windows 경로의 \\ 도 안전."""
    return json.dumps(str(s), ensure_ascii=False)


def toml_list(items) -> str:
    return "[" + ",".join(toml_str(i) for i in items) + "]"


def toml_table(d: dict) -> str:
    return "{" + ",".join(f"{toml_str(k)}={toml_str(v)}" for k, v in d.items()) + "}"


def mcp_env(force: bool | None = None) -> dict:
    env = {"PYTHONPATH": str(config.APP_ROOT), "BYORBIT_HOME": str(config.data_home()),
           "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    if force_block() if force is None else force:
        env[FORCE_ENV] = "block"
    return env


def server_args(write: bool = False, force: bool | None = None) -> list[str]:
    """MCP 서버를 -c 로 지정한다(사용자 설정 파일은 건드리지 않는다)."""
    rd = f"mcp_servers.{SERVER}"
    tools = READ_TOOLS + (WRITE_TOOLS if write else [])
    args = ["-c", f"{rd}.command={toml_str(sys.executable)}",
            "-c", f"{rd}.args={toml_list(['-m', 'app.mcp_server'])}",
            "-c", f"{rd}.env={toml_table(mcp_env(force))}",
            "-c", f"{rd}.enabled_tools={toml_list(tools)}",
            "-c", f"{rd}.default_tools_approval_mode=\"approve\"",  # approval_policy=never면 승인 필요 도구는 실패한다
            "-c", f"{rd}.startup_timeout_sec=60"]
    food = food_mcp.server_config()
    if food:
        fd = f"mcp_servers.{food_mcp.SERVER}"
        args += ["-c", f"{fd}.command={toml_str(food['command'])}",
                 "-c", f"{fd}.args={toml_list(food['args'])}",
                 "-c", f"{fd}.enabled_tools={toml_list(food_mcp.TOOLS)}",
                 "-c", f"{fd}.disabled_tools={toml_list(food_mcp.EXCLUDED)}",
                 "-c", f"{fd}.default_tools_approval_mode=\"approve\""]
    return args


def build_command(prefix: list[str], write: bool = False, model: str | None = None,
                  force: bool | None = None) -> list[str]:
    cmd = list(prefix) + ["exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config",
                          "--ignore-rules", "-s", "read-only", "-C", str(config.data_home()), "--color", "never"]
    for f in DISABLED_FEATURES:
        cmd += ["--disable", f]
    for c in EXTRA_CONFIG:
        cmd += ["-c", c]
    cmd += server_args(write, force)
    if model:
        cmd += ["-m", model]
    cmd.append("-")  # 프롬프트는 표준입력
    return cmd


def build_prompt(prompt: str, role: str | None) -> str:
    parts = []
    role_text = agent_instructions(role)
    if role_text:
        parts.append(role_text)
    if food_mcp.active():
        parts.append(food_mcp.GUIDE)
    parts.append("자료는 byorbit-rd MCP 도구로만 읽으세요. 파일을 직접 열거나 명령을 실행하지 마세요.")
    return "\n\n".join(parts) + "\n\n---\n\n" + prompt


# ---------------------------------------------------------------- 기밀 자료 확인

def has_confidential() -> bool:
    try:
        r = db.one("SELECT 1 AS x FROM source WHERE confidentiality='기밀' LIMIT 1")
        if r:
            return True
        r = db.one("SELECT 1 AS x FROM sample WHERE coa_doc_id IS NOT NULL LIMIT 1")
        return bool(r)
    except Exception:  # noqa: BLE001 — DB가 없으면 기밀 자료도 없다
        return False


def refusal() -> str | None:
    if not FORCE_BLOCK or os.environ.get(ALLOW_CONF_ENV) == "1":
        return None
    if has_confidential():
        return ("데이터 폴더에 기밀(CoA) 자료가 있어 Codex로는 실행하지 않습니다. Codex는 내장 기능을 꺼도 "
                "파일을 직접 읽을 수 있는 것으로 확인되어, 가림 처리 없이 원본이 나갈 수 있습니다. "
                "설정 → AI 엔진을 Claude Code로 바꿔 실행하세요. 위험을 알고도 쓰려면 환경 변수 "
                f"{ALLOW_CONF_ENV}=1 을 지정하세요(이때도 CoA 수치는 '보내지 않기'로 강제됩니다).")
    return None


# ---------------------------------------------------------------- 실행

def run(prompt: str, role: str | None = None, write: bool = True, max_turns: int | None = None,
        timeout: int | None = None, task: str = "ask", run_id: str | None = None,
        runner=subprocess.run) -> dict:
    """반환: {"ok", "result", "session_id", "duration_ms", "usage", "tool_calls", "raw_events"}.
    max_turns는 Codex CLI에 해당 옵션이 없어 쓰지 않는다(계약 맞춤용)."""
    pre = command_prefix()
    if not pre:
        return {"ok": False, "error": "Codex CLI를 찾지 못했습니다. 설정 → AI 엔진을 Claude Code로 두거나 Codex를 설치하세요."}
    msg = refusal()
    if msg:
        return {"ok": False, "error": msg, "refused": True}
    timeout = timeout or int(config.load_settings().get("claude_timeout_sec", 600))
    model = os.environ.get(MODEL_ENV) or None
    cmd = build_command(pre, write=write, model=model)
    stdin = build_prompt(prompt, role)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    t0 = time.time()
    try:
        p = runner(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                   timeout=timeout, cwd=str(config.data_home()), env=env)
    except subprocess.TimeoutExpired:
        _usage(run_id, None, task, int((time.time() - t0) * 1000), False)
        return {"ok": False, "error": f"{timeout}초 안에 끝나지 않았습니다."}
    except OSError as e:
        _usage(run_id, None, task, int((time.time() - t0) * 1000), False)
        return {"ok": False, "error": f"Codex를 실행하지 못했습니다: {e}"}
    dur = int((time.time() - t0) * 1000)
    out = parse_events(p.stdout)
    if not out["events"]:
        _usage(run_id, None, task, dur, False)
        return {"ok": False, "error": (p.stderr or p.stdout or "응답 없음").strip()[-2000:], "returncode": p.returncode}
    ok = p.returncode == 0 and not out["error"] and out["result"] is not None
    _usage(run_id, out["session_id"], task, dur, ok)
    res = {"ok": ok, "result": out["result"] or "", "session_id": out["session_id"], "duration_ms": dur,
           "cost_usd": None, "usage": out["usage"], "tool_calls": out["tool_calls"],
           "raw_events": out["events"][-50:]}
    if not ok:
        res["error"] = out["error"] or (p.stderr or "").strip()[-2000:] or "Codex가 답을 내지 않았습니다."
        res["returncode"] = p.returncode
    return res


def parse_events(stdout: str | None) -> dict:
    """--json 이벤트(JSONL). 모르는 이벤트·JSON이 아닌 줄은 건너뛴다.
    thread.started{thread_id} / item.completed{item{type: agent_message|mcp_tool_call|...}} /
    turn.completed{usage} / turn.failed{error{message}} / error{message}"""
    res = {"events": [], "result": None, "session_id": None, "usage": None, "error": None, "tool_calls": []}
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        res["events"].append(ev)
        t = ev.get("type") or ""
        if t in ("thread.started", "session.created", "session_configured"):
            res["session_id"] = ev.get("thread_id") or ev.get("session_id") or res["session_id"]
        elif t.startswith("item."):
            item = ev.get("item") or {}
            it = item.get("type") or item.get("item_type")
            if t == "item.completed" and it in ("agent_message", "assistant_message"):
                text = item.get("text")
                if text is None and isinstance(item.get("content"), list):
                    text = "".join(c.get("text", "") for c in item["content"] if isinstance(c, dict))
                if text is not None:
                    res["result"] = text
            elif t == "item.completed" and it and it not in ("reasoning",):
                res["tool_calls"].append({k: item.get(k) for k in
                                          ("type", "server", "tool", "status", "command", "error") if k in item})
            if t == "item.completed" and it == "error":
                res["error"] = item.get("message") or res["error"]
        elif t == "turn.completed":
            res["usage"] = ev.get("usage") or res["usage"]
            res["error"] = None if res["result"] is not None else res["error"]
        elif t == "turn.failed":
            err = ev.get("error")
            res["error"] = (err.get("message") if isinstance(err, dict) else str(err or "")) or "실행 실패"
        elif t == "error":
            res["error"] = ev.get("message") or str(ev.get("error") or "오류")
    return res


def _usage(run_id, session_id, task, dur, ok):
    try:
        with db.tx() as c:
            c.execute("INSERT INTO usage_log(usage_id, run_id, engine, session_id, task, duration_ms, ok) "
                      "VALUES (?,?, 'codex', ?,?,?,?)", (db.new_id(), run_id, session_id, task, dur, int(ok)))
    except Exception:
        pass


# ---------------------------------------------------------------- 점검

SMOKE_PROMPT = ("byorbit-rd 도구 lookup_concept을 term='사과 포마스'로 한 번 호출하고, "
                "결과의 첫 번째 pref_label 값만 한 단어로 답하세요. 다른 말은 하지 마세요.")


def check(smoke: bool = True, runner=subprocess.run) -> dict:
    """① 설치·버전 ② 보안 설정(꺼진 기능·강제 규칙·시험 결과) ③ (선택) 실제로 도구를 불러 '사과박'을 받는지."""
    v = version()
    res = {"engine": "codex", "cli": v, "smoke": None, "food": food_mcp.status(),
           "shell_disabled": PROBE["shell_disabled"], "file_read_blocked": PROBE["file_read_blocked"],
           "probe_date": PROBE["date"], "policy": policy()}
    if not v.get("installed") or not smoke:
        res["ok"] = bool(v.get("installed")) and not smoke
        return res
    r = run(SMOKE_PROMPT, role=None, write=False, timeout=180, task="check", runner=runner)
    passed = r.get("ok") and "사과박" in (r.get("result") or "")
    res["smoke"] = {"passed": bool(passed), "answer": (r.get("result") or r.get("error") or "")[:500],
                    "duration_ms": r.get("duration_ms"), "tool_calls": r.get("tool_calls")}
    msg = (r.get("error") or r.get("result") or "").lower()
    if not passed and r.get("refused"):
        res["hint"] = r.get("error")
    elif not passed and any(k in msg for k in ("login", "auth", "api key", "401", "unauthorized", "credit",
                                               "subscription", "not logged")):
        res["hint"] = "터미널에서 'codex login'을 한 번 실행해 로그인하세요."
    elif not passed:
        res["hint"] = ("도구 호출이 확인되지 않았습니다. 터미널에서 'codex exec \"hi\"'가 되는지, "
                       "설정 → 연결 점검의 Claude Code 점검이 통과하는지(같은 MCP 서버) 확인하세요.")
    res["ok"] = bool(passed)
    return res
