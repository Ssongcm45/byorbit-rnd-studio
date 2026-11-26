"""새 PC 설치·Claude Code 연결 — 이 PC의 Claude Code를 찾고, 로그인 상태를 보고, 자료 도구를 등록·해제한다.

- 찾기: PATH, npm 설치(claude.cmd → 실제 claude.exe), 공식 설치(~/.local/bin/claude.exe), WinGet 링크,
  환경 변수 BYORBIT_CLAUDE. 앱이 실제로 쓰는 것은 claude_code.executable()이 고른 하나다.
- 로그인: `claude auth status --json`(2.1.x). 질문을 보내지 않으므로 사용량이 들지 않는다.
  이 명령이 없는 오래된 CLI는 '모름'으로 두고, 실제 호출 점검(사용자가 누를 때만)으로 확인하게 한다.
- 등록: `claude mcp add-json --scope user byorbit-rd '<json>'` — 사용자가 단추·설치 프로그램에서 고를 때만.
  JSON은 표준입력이 아니라 인자로 넘긴다(2.1.x는 Claude Code 세션 안에서 표준입력 JSON을 거절한다).
  add-json이 없는 오래된 CLI는 `claude mcp add --scope user byorbit-rd -e K=V … -- python -m app.mcp_server`.
  (-e는 값을 여러 개 받으므로 이름을 -e보다 앞에 둬야 한다 — 2.1.332에서 확인)
- 시험에서는 RUNNER(=subprocess.run)를 가짜로 바꾼다. 실제 ~/.claude.json은 시험이 건드리지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .. import config
from . import claude_code

SERVER = claude_code.SERVER
SCOPES = ("user", "local")
RUNNER = subprocess.run

INSTALL_COMMANDS = [
    {"label": "공식 설치 (권장 · PowerShell)", "cmd": "irm https://claude.ai/install.ps1 | iex"},
    {"label": "npm으로 설치 (Node.js가 있을 때)", "cmd": "npm install -g @anthropic-ai/claude-code"},
]
LOGIN_COMMAND = "claude"
USAGE_EXAMPLE = "byorbit-rd로 사과박 식이섬유 자료 찾아줘"
SECURITY_NOTE = (
    "내 Claude Code 대화창에서는 Claude가 자기 파일 읽기(Read·Grep)·셸 같은 내장 도구도 함께 씁니다. "
    "그래서 내장 도구를 모두 끄고 실행하는 앱 안 ‘AI에 묻기’보다 기밀 원본 보호가 약합니다 — "
    "Claude가 데이터 폴더의 CoA 원본 파일을 직접 읽으면(권한을 허락했거나 묻지 않는 모드일 때) 가림이 적용되지 않습니다. "
    "byorbit-rd 도구 자체는 CoA 규칙(식별 정보 가림·보내지 않기)을 그대로 지킵니다. 기밀 자료는 앱 안 ‘AI에 묻기’로 다루세요.")
TOOLS_NOTE = ("도구 7개: 읽기 4개(search_chunks·get_chunk·lookup_concept·query_measurements)와 "
              "쓰기 3개(save_annotations·save_report_draft·propose_concept). 쓰기 도구는 DB를 직접 고치지 않고 "
              "라벨·리포트 초안·개념 제안을 남깁니다(수치 라벨과 개념 제안은 검토 대기).")
KIND_LABEL = {"npm": "npm 설치", "native": "공식 설치", "winget": "WinGet 설치", "override": "BYORBIT_CLAUDE 지정",
              "other": "기타"}
AUTH_LABEL = {"claude.ai": "Claude 계정(구독)", "oauth": "Claude 계정", "api_key": "API 키",
              "apiKey": "API 키", "console": "Anthropic Console(API 키)", "none": "없음"}


# ---------------------------------------------------------------- 찾기

def classify(path: str) -> str:
    low = str(path).replace("/", "\\").lower()
    if "node_modules" in low or low.endswith((".cmd", ".bat", ".ps1")) or "\\npm\\" in low:
        return "npm"
    if "\\.local\\bin\\" in low:
        return "native"
    if "\\winget\\" in low:
        return "winget"
    return "other"


def resolve_shim(path: str, exists=os.path.isfile) -> str:
    """npm의 claude.cmd는 콘솔 없는 백그라운드 서버에서 실패할 수 있어, 옆의 실제 claude.exe를 쓴다(claude_code._real_exe와 같은 규칙)."""
    p = Path(path)
    if p.suffix.lower() in (".cmd", ".bat"):
        real = p.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
        if exists(str(real)):
            return str(real)
    return str(path)


def candidates(env=None, which=shutil.which, home=None) -> list[tuple[str, str | None]]:
    env = os.environ if env is None else env
    home = Path(home) if home else Path.home()
    out: list[tuple[str, str | None]] = []
    if env.get("BYORBIT_CLAUDE"):
        out.append((env["BYORBIT_CLAUDE"], "override"))
    w = which("claude", path=env.get("PATH"))
    if w:
        out.append((w, None))
    out += [(str(home / ".local" / "bin" / "claude.exe"), "native"), (str(home / ".local" / "bin" / "claude"), "native")]
    if env.get("APPDATA"):
        out.append((str(Path(env["APPDATA"]) / "npm" / "claude.cmd"), "npm"))
    if env.get("LOCALAPPDATA"):
        out.append((str(Path(env["LOCALAPPDATA"]) / "Microsoft" / "WinGet" / "Links" / "claude.exe"), "winget"))
    return out


def find_installs(env=None, which=shutil.which, home=None, exists=os.path.isfile) -> list[dict]:
    """이 PC에 있는 Claude Code 실행 파일 전부(같은 파일은 한 번). path는 실제로 실행할 파일, shim은 거쳐 온 claude.cmd."""
    seen, res = set(), []
    for path, kind in candidates(env, which, home):
        if not path or not exists(path):
            continue
        real = resolve_shim(path, exists)
        key = os.path.normcase(os.path.normpath(real))
        if key in seen:
            continue
        seen.add(key)
        k = kind or classify(path)
        if k != "override" and classify(real) == "npm":
            k = "npm"
        item = {"path": real, "kind": k, "kind_label": KIND_LABEL.get(k, k)}
        if real != path:
            item["shim"] = path
        res.append(item)
    return res


# ---------------------------------------------------------------- 실행 도우미

def _run(args: list[str], timeout: int = 60, runner=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    home = config.data_home()
    kw = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace", "timeout": timeout,
          "stdin": subprocess.DEVNULL, "env": env}
    if home.is_dir():
        kw["cwd"] = str(home)  # local 범위 등록이 엉뚱한 폴더(앱 폴더 등)에 붙지 않게 늘 같은 곳에서 실행
    return (runner or RUNNER)(args, **kw)


def _out(p) -> str:
    return ((p.stdout or "") + ("\n" + p.stderr if p.stderr else "")).strip()


def cli_version(exe: str, runner=None) -> dict:
    try:
        p = _run([exe, "--version"], timeout=30, runner=runner)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "message": f"실행하지 못했습니다: {e}"}
    out = _out(p)
    if p.returncode != 0:
        return {"ok": False, "version": out[:200],
                "message": f"Claude Code를 실행했지만 실패했습니다(종료 코드 {p.returncode}). {out[:200] or '출력 없음'}"}
    return {"ok": True, "version": out.splitlines()[0] if out else ""}


# ---------------------------------------------------------------- 로그인

def parse_auth_status(stdout: str | None, stderr: str | None = "", returncode: int = 0) -> dict:
    """`claude auth status --json` 결과 해석. logged_in: True/False/None(모름). 이메일·조직명은 담지 않는다."""
    s = (stdout or "").strip()
    obj = None
    if s:
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", s, re.S)
            if m:
                try:
                    obj = json.loads(m.group(0))
                except json.JSONDecodeError:
                    obj = None
    if isinstance(obj, dict) and "loggedIn" in obj:
        method = obj.get("authMethod")
        res = {"logged_in": bool(obj.get("loggedIn")), "method": method,
               "method_label": AUTH_LABEL.get(method or "", method or ""),
               "plan": obj.get("subscriptionType"), "expires": obj.get("loginExpiresAt"),
               "provider": obj.get("apiProvider")}
        prov = (obj.get("apiProvider") or "firstParty")
        if not res["logged_in"] and prov != "firstParty":
            # Bedrock·Vertex 같은 클라우드 공급자는 환경 변수로 인증 — 여기서는 판단하지 못한다
            res.update(logged_in=None, reason=f"클라우드 공급자({prov}) 설정이라 로그인 상태를 여기서 알 수 없습니다.")
        return res
    text = (s + "\n" + (stderr or "")).lower()
    if "unknown command" in text or "unknown option" in text or "did you mean" in text:
        return {"logged_in": None, "reason": "이 버전의 Claude Code에는 로그인 상태 명령이 없습니다."}
    if "not logged in" in text or "not authenticated" in text or "please run /login" in text:
        return {"logged_in": False}
    if re.search(r"\blogged in\b", text):
        return {"logged_in": True}
    return {"logged_in": None, "reason": "로그인 상태를 읽지 못했습니다."}


def login_status(exe: str, runner=None) -> dict:
    try:
        p = _run([exe, "auth", "status", "--json"], timeout=30, runner=runner)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"logged_in": None, "reason": f"상태 명령을 실행하지 못했습니다: {e}"}
    return parse_auth_status(p.stdout, p.stderr, p.returncode)


# ---------------------------------------------------------------- 등록 상태

def _norm(p: str | None) -> str:
    return os.path.normcase(os.path.normpath(p)) if p else ""


def parse_mcp_get(out: str, returncode: int = 0) -> dict | None:
    """`claude mcp get byorbit-rd` 출력. 없으면 registered False, 읽을 수 없으면 None."""
    if re.search(r"No MCP server (named|found)", out, re.I):
        return {"registered": False}
    fields, env, in_env = {}, {}, False
    for line in out.splitlines():
        if in_env:
            m = re.match(r"^\s{3,}([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
            if m:
                env[m.group(1)] = m.group(2).strip()
                continue
            in_env = False
        m = re.match(r"^\s+([A-Za-z][A-Za-z ]*?):\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1).strip().lower(), m.group(2).strip()
        if key == "environment":
            in_env = True
        else:
            fields[key] = val
    if "scope" not in fields and "command" not in fields:
        return None
    sc = fields.get("scope", "").lower()
    first = sc.split()[0] if sc else ""  # "Local config (private to you in this project)" — 첫 낱말이 범위
    scope = first if first in ("user", "local", "project") else (sc or None)
    return {"registered": True, "scope": scope, "connected": _connected(fields.get("status", "")),
            "status_text": fields.get("status", ""), "issue": fields.get("issue"), "type": fields.get("type"),
            "command": fields.get("command"), "args": fields.get("args", ""), "env": env}


def _connected(s: str) -> bool | None:
    low = s.lower()
    if "fail" in low or "✘" in s or "error" in low:
        return False
    if "connected" in low or "✔" in s or "✓" in s:
        return True
    return None


def parse_mcp_list(out: str) -> dict:
    for line in out.splitlines():
        if line.strip().startswith(f"{SERVER}:"):
            rest = line.split(":", 1)[1]
            return {"registered": True, "scope": None, "connected": _connected(rest),
                    "status_text": rest.rsplit(" - ", 1)[-1].strip() if " - " in rest else ""}
    return {"registered": False}


def compare_registration(reg: dict, spec: dict | None = None) -> dict:
    """등록된 명령·데이터 폴더가 지금 앱과 같은지(앱이나 데이터 폴더를 옮기면 달라진다)."""
    if not reg.get("registered") or reg.get("command") is None:
        return reg
    spec = spec or claude_code.rd_server_config()
    same_cmd = _norm(reg.get("command")) == _norm(spec["command"])
    same_args = " ".join((reg.get("args") or "").split()) == " ".join(spec["args"])
    home = (reg.get("env") or {}).get("BYORBIT_HOME")
    same_home = _norm(home) == _norm(spec["env"]["BYORBIT_HOME"]) if home else False
    reg = dict(reg, current=same_cmd and same_args and same_home)
    if not reg["current"]:
        why = []
        if not (same_cmd and same_args):
            why.append("다른 파이썬·앱 폴더")
        if not same_home:
            why.append(f"다른 데이터 폴더({home or '지정 없음'})")
        reg["mismatch"] = " · ".join(why)
    return reg


def registration_status(exe: str, runner=None) -> dict:
    """등록 여부. `claude mcp get`은 서버를 잠깐 띄워 상태를 확인한다(이 PC 안에서만, 질문은 보내지 않음)."""
    try:
        p = _run([exe, "mcp", "get", SERVER], timeout=90, runner=runner)
    except subprocess.TimeoutExpired:
        return {"registered": None, "reason": "확인이 90초 안에 끝나지 않았습니다."}
    except OSError as e:
        return {"registered": None, "reason": f"실행하지 못했습니다: {e}"}
    reg = parse_mcp_get(_out(p), p.returncode)
    if reg is None:
        try:
            q = _run([exe, "mcp", "list"], timeout=90, runner=runner)
            reg = parse_mcp_list(_out(q))
        except (OSError, subprocess.TimeoutExpired) as e:
            return {"registered": None, "reason": f"등록 상태를 읽지 못했습니다: {e}"}
    return compare_registration(reg)


# ---------------------------------------------------------------- 등록·해제

def add_json_command(exe: str, spec: dict, scope: str = "user") -> list[str]:
    return [exe, "mcp", "add-json", "--scope", scope, SERVER, json.dumps(spec, ensure_ascii=False)]


def add_command(exe: str, spec: dict, scope: str = "user") -> list[str]:
    """add-json이 없는 오래된 CLI용. 이름을 -e 앞에 둔다(-e가 뒤 인자를 값으로 삼켜서)."""
    cmd = [exe, "mcp", "add", "--scope", scope, SERVER]
    for k, v in spec.get("env", {}).items():
        cmd += ["-e", f"{k}={v}"]
    return cmd + ["--", spec["command"], *spec.get("args", [])]


def remove_command(exe: str, scope: str = "user") -> list[str]:
    return [exe, "mcp", "remove", "--scope", scope, SERVER]


def manual_command(spec: dict | None = None, scope: str = "user") -> str:
    """사람이 PowerShell·명령 프롬프트에 붙여 넣을 수 있는 한 줄(경로에 빈칸이 있어도 되게 큰따옴표)."""
    spec = spec or claude_code.rd_server_config()
    q = lambda s: f'"{s}"' if re.search(r'[\s&()^|<>]', s) else s  # noqa: E731
    env = " ".join(f'-e {q(f"{k}={v}")}' for k, v in spec["env"].items())
    return f'claude mcp add --scope {scope} {SERVER} {env} -- {q(spec["command"])} {" ".join(spec["args"])}'


def _check_scope(scope: str) -> str:
    if scope not in SCOPES:
        raise ValueError(f"scope는 {' 또는 '.join(SCOPES)}만 됩니다")
    return scope


def register(scope: str = "user", exe: str | None = None, runner=None) -> dict:
    """내 Claude Code(사용자 범위)에 byorbit-rd를 넣는다. 같은 이름이 있으면 그 범위에서 빼고 다시 넣는다(경로 갱신)."""
    _check_scope(scope)
    exe = exe or claude_code.executable()
    if not exe:
        return {"ok": False, "message": "Claude Code를 찾지 못해 등록하지 못했습니다. 먼저 설치하세요."}
    spec = claude_code.rd_server_config()
    claude_code.write_mcp_config()  # 앱 쪽 mcp.json도 같은 값으로 맞춘다
    try:
        _run(remove_command(exe, scope), runner=runner)  # 없으면 실패하지만 상관없다
        p = _run(add_json_command(exe, spec, scope), runner=runner)
        used = "add-json"
        if p.returncode != 0 and re.search(r"unknown command|too many arguments|did you mean", _out(p), re.I):
            p = _run(add_command(exe, spec, scope), runner=runner)
            used = "add"
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "message": f"등록 명령을 실행하지 못했습니다: {e}"}
    out = _out(p)
    _CACHE.clear()
    if p.returncode != 0:
        return {"ok": False, "used": used, "output": out[:1000],
                "message": f"등록하지 못했습니다(종료 코드 {p.returncode}). {out[:300]}"}
    where = "사용자 설정(모든 폴더의 대화에서 보임)" if scope == "user" else "데이터 폴더의 로컬 설정"
    return {"ok": True, "used": used, "scope": scope, "output": out[:1000],
            "message": f"내 Claude Code {where}에 {SERVER}를 등록했습니다. 새로 연 Claude Code 대화부터 쓸 수 있습니다."}


def unregister(scope: str = "user", exe: str | None = None, runner=None) -> dict:
    _check_scope(scope)
    exe = exe or claude_code.executable()
    if not exe:
        return {"ok": False, "message": "Claude Code를 찾지 못했습니다."}
    try:
        p = _run(remove_command(exe, scope), runner=runner)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "message": f"해제 명령을 실행하지 못했습니다: {e}"}
    out = _out(p)
    _CACHE.clear()
    if p.returncode == 0:
        return {"ok": True, "message": f"내 Claude Code에서 {SERVER}를 뺐습니다. 앱 안의 AI 기능은 그대로 됩니다.", "output": out[:1000]}
    if re.search(r"No MCP server", out, re.I):
        return {"ok": True, "already": True, "message": "등록되어 있지 않습니다(뺄 것이 없음).", "output": out[:1000]}
    return {"ok": False, "message": f"해제하지 못했습니다(종료 코드 {p.returncode}). {out[:300]}", "output": out[:1000]}


# ---------------------------------------------------------------- 전체 상태

_CACHE: dict = {}
CACHE_SEC = 60


def next_steps(st: dict) -> list[str]:
    if not st.get("installed"):
        return ["Claude Code를 설치하세요. PowerShell에서:  " + INSTALL_COMMANDS[0]["cmd"],
                "  (또는 Node.js가 있으면:  " + INSTALL_COMMANDS[1]["cmd"] + ")",
                "설치가 끝나면 새 PowerShell 창에서 'claude'를 실행해 로그인을 마치세요.",
                "그다음 check-claude.bat 또는 앱의 설정 → Claude Code 연결 마법사에서 다시 확인하세요."]
    steps = []
    if st.get("logged_in") is False:
        steps += ["로그인이 필요합니다. PowerShell에서 'claude'를 실행하고 안내대로 로그인을 마치세요.",
                  "그다음 check-claude.bat 또는 앱의 설정 → Claude Code 연결 마법사에서 다시 확인하세요."]
    elif st.get("logged_in") is None:
        steps.append("로그인 상태를 알 수 없습니다. 앱의 설정 → Claude Code 연결 마법사 → ③ 연결 점검(실제 호출)으로 확인하세요.")
    reg = st.get("registration") or {}
    if reg.get("registered") is False:
        steps.append("내 Claude Code 대화창에서도 자료를 쓰려면 ④ 자료 도구 등록을 하세요(선택).")
    elif reg.get("registered") and reg.get("current") is False:
        steps.append(f"등록된 자료 도구가 지금 앱과 다릅니다({reg.get('mismatch')}). 다시 등록하세요.")
    return steps


def status(cached: bool = True, registration: bool = True, runner=None) -> dict:
    """마법사 한 번에 쓰는 상태. 돈이 드는 호출은 하지 않는다(실제 호출 점검은 따로, 사용자가 누를 때만)."""
    key = "full" if registration else "fast"
    if cached:
        # 빠른 확인은 전체 확인 결과로도 답할 수 있다 — 둘 중 더 새것(다시 확인·등록 뒤의 값)을 쓴다
        hits = [h for h in (_CACHE.get(key), None if registration else _CACHE.get("full")) if h]
        hit = max(hits, key=lambda h: h[0]) if hits else None
        if hit and time.time() - hit[0] < CACHE_SEC:
            return dict(hit[1], cached=True)
    else:
        _CACHE.clear()  # 다시 확인: 예전 빠른 확인 값이 남아 새 값을 가리지 않게
    exe = claude_code.executable()
    installs = find_installs()
    st: dict = {"installed": False, "path": exe, "installs": installs, "server_name": SERVER,
                "install_commands": INSTALL_COMMANDS, "login_command": LOGIN_COMMAND,
                "usage_example": USAGE_EXAMPLE, "security_note": SECURITY_NOTE, "tools_note": TOOLS_NOTE,
                "manual_command": manual_command(), "mcp_config": str(claude_code.mcp_config_path()),
                "logged_in": None, "login": None, "registration": None}
    if exe:
        kind = "override" if os.environ.get("BYORBIT_CLAUDE") else classify(exe)
        st.update(kind=kind, kind_label=KIND_LABEL.get(kind, kind))
        v = cli_version(exe, runner)
        st["installed"] = v["ok"]
        st["version"] = v.get("version")
        if not v["ok"]:
            st["message"] = v.get("message")
    else:
        st["message"] = "이 PC에서 Claude Code(claude)를 찾지 못했습니다."
    if st["installed"]:
        st["login"] = login_status(exe, runner)
        st["logged_in"] = st["login"].get("logged_in")
        if registration:
            st["registration"] = registration_status(exe, runner)
    if len(installs) > 1:
        st["hint"] = (f"Claude Code가 {len(installs)}군데 설치되어 있습니다. 앱은 위 경로의 것을 씁니다. "
                      "다른 것을 쓰려면 환경 변수 BYORBIT_CLAUDE에 경로를 넣으세요.")
    elif st.get("kind") == "npm" and str(exe).lower().endswith((".cmd", ".bat")):
        st["hint"] = ("npm 설치의 claude.cmd를 그대로 씁니다. 앱(백그라운드)에서 실패하면 "
                      "'npm install -g @anthropic-ai/claude-code'로 업데이트하거나 공식 설치로 바꾸세요.")
    st["ready"] = bool(st["installed"] and st["logged_in"] is not False)
    st["next_steps"] = next_steps(st)
    _CACHE[key] = (time.time(), st)
    return dict(st, cached=False)


# ---------------------------------------------------------------- 명령줄 출력(설치 프로그램·check-claude.bat)

# 1은 쓰지 않는다 — 파이썬이 오류로 끝날 때의 종료 코드라서, 설치 프로그램이 오류를 '준비됨'으로 오해하지 않게
EXIT_READY, EXIT_NOT_LOGGED_IN, EXIT_NOT_INSTALLED, EXIT_UNKNOWN_LOGIN, EXIT_REGISTERED = 0, 2, 3, 4, 5


def exit_code(st: dict) -> int:
    """설치 프로그램이 등록을 물을지 고르는 데 쓴다: 0·4면 묻고, 5면 이미 등록됨, 2·3이면 안내만(1 등 그 밖은 오류)."""
    if not st.get("installed"):
        return EXIT_NOT_INSTALLED
    if st.get("logged_in") is False:
        return EXIT_NOT_LOGGED_IN
    reg = st.get("registration") or {}
    if reg.get("registered") and reg.get("current"):
        return EXIT_REGISTERED
    return EXIT_READY if st.get("logged_in") else EXIT_UNKNOWN_LOGIN


def describe(st: dict) -> str:
    L = []
    if st.get("installed"):
        L.append(f"  ① 설치     : 있음 — {st.get('version') or ''} ({st.get('kind_label') or ''})")
        L.append(f"               {st.get('path')}")
    else:
        L.append(f"  ① 설치     : 없음 — {st.get('message') or ''}")
    if st.get("hint"):
        L.append(f"               참고: {st['hint']}")
    if st.get("installed"):
        lg = st.get("login") or {}
        if st.get("logged_in") is True:
            extra = " · ".join(x for x in (lg.get("method_label"), lg.get("plan")) if x)
            L.append(f"  ② 로그인   : 됨{f' ({extra})' if extra else ''}")
        elif st.get("logged_in") is False:
            L.append("  ② 로그인   : 안 됨")
        else:
            L.append(f"  ② 로그인   : 모름 — {lg.get('reason') or ''}")
        reg = st.get("registration")
        if reg is not None:
            if reg.get("registered") is None:
                L.append(f"  ④ 자료 도구: 확인 못 함 — {reg.get('reason') or ''}")
            elif not reg.get("registered"):
                L.append(f"  ④ 자료 도구: 내 Claude Code에 아직 등록 안 됨 ({SERVER})")
            else:
                sc = {"user": "사용자 범위", "local": "로컬 범위", "project": "프로젝트 범위"}.get(reg.get("scope"), reg.get("scope") or "")
                state = "연결됨" if reg.get("connected") else "연결 실패" if reg.get("connected") is False else "상태 모름"
                cur = "" if reg.get("current") in (True, None) else f" — 지금 앱과 다름({reg.get('mismatch')})"
                L.append(f"  ④ 자료 도구: 등록됨 ({sc} · {state}){cur}")
    steps = st.get("next_steps") or []
    if steps:
        L.append("")
        L.append("  다음 할 일:")
        L += [f"   - {s}" if not s.startswith("  ") else f"     {s.strip()}" for s in steps]
    return "\n".join(L)
