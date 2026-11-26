"""새 PC 설치·Claude Code 연결: 설치 형태 찾기, 로그인 상태 해석, 내 Claude Code 등록 명령·결과 해석,
/api/setup/* , `app.cli setup-claude`, 설치 스크립트 모양.

실제 claude를 부르지 않는다 — 가짜 실행기(FakeCLI)가 2.1.332의 실제 출력 모양을 흉내 낸다.
그래서 이 PC의 실제 Claude Code 설정(~/.claude.json)은 건드리지 않는다."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVER = "byorbit-rd"


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    from app import db, thesaurus
    prev = os.environ.get("BYORBIT_HOME")
    h = tmp_path_factory.mktemp("byorbit home setup")  # 빈칸 있는 경로
    os.environ["BYORBIT_HOME"] = str(h)
    thesaurus.invalidate()
    db.init(seed=True)
    yield h
    if prev is None:
        os.environ.pop("BYORBIT_HOME", None)
    else:
        os.environ["BYORBIT_HOME"] = prev
    thesaurus.invalidate()


def R(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, out, err)


def get_text(spec: dict, status="✔ Connected", scope="User config (available in all your projects)") -> str:
    env = "\n".join(f"    {k}={v}" for k, v in spec["env"].items())
    return (f"{SERVER}:\n  Scope: {scope}\n  Status: {status}\n  Type: stdio\n  Command: {spec['command']}\n"
            f"  Args: {' '.join(spec['args'])}\n  Environment:\n{env}\n\n"
            f"To remove this server, run: claude mcp remove {SERVER} -s user\n")


class FakeCLI:
    """claude 명령 흉내. calls에 (인자, 키워드)를 남긴다."""

    def __init__(self, logged_in=True, registered: dict | None = None, add_json=True, version_rc=0, add_rc=0):
        self.calls, self.logged_in, self.reg = [], logged_in, registered
        self.add_json, self.version_rc, self.add_rc = add_json, version_rc, add_rc

    def args(self):
        return [c[0][1:] for c in self.calls]

    def __call__(self, args, **kw):
        self.calls.append((list(args), kw))
        a = list(args[1:])
        if a == ["--version"]:
            return R(self.version_rc, "2.1.332 (Claude Code)\n" if self.version_rc == 0 else "", "boom")
        if a[:2] == ["auth", "status"]:
            d = {"loggedIn": self.logged_in, "authMethod": "claude.ai" if self.logged_in else "none",
                 "apiProvider": "firstParty", "email": "someone@example.com", "orgName": "비밀 회사",
                 "subscriptionType": "max" if self.logged_in else None}
            return R(0 if self.logged_in else 1, json.dumps(d, indent=2))
        if a[:2] == ["mcp", "get"]:
            if self.reg:
                return R(0, get_text(self.reg))
            return R(1, f'No MCP server named "{SERVER}". Run `claude mcp add` to add one.\n')
        if a[:2] == ["mcp", "list"]:
            return R(0, "No MCP servers configured. Use `claude mcp add` to add a server.\n")
        if a[:2] == ["mcp", "remove"]:
            if self.reg:
                self.reg = None
                return R(0, f"Removed MCP server {SERVER} from user config\n")
            return R(1, f'No MCP server named "{SERVER}". Run `claude mcp add` to add one.\n')
        if a[:2] == ["mcp", "add-json"]:
            if not self.add_json:
                return R(1, "", "error: unknown command 'add-json'")
            if self.add_rc:
                return R(self.add_rc, "", "Invalid configuration")
            self.reg = json.loads(a[-1])
            return R(0, f"Added stdio MCP server {SERVER} to user config\n")
        if a[:2] == ["mcp", "add"]:
            i = a.index("--")
            env = dict(a[j + 1].split("=", 1) for j in range(i) if a[j] == "-e")
            self.reg = {"type": "stdio", "command": a[i + 1], "args": a[i + 2:], "env": env}
            return R(0, f"Added stdio MCP server {SERVER} with command: ... to user config\n")
        return R(1, "", f"error: unknown command '{a[0] if a else ''}'")


@pytest.fixture
def cs(home, monkeypatch):
    from app.engines import claude_code, claude_setup
    monkeypatch.delenv("BYORBIT_CLAUDE", raising=False)
    monkeypatch.setattr(claude_code, "executable", lambda: r"C:\Tools\claude.exe")
    monkeypatch.setattr(claude_setup, "find_installs", lambda *a, **k: [])
    claude_setup._CACHE.clear()
    yield claude_setup
    claude_setup._CACHE.clear()


# ---------------------------------------------------------------- 찾기

def _fs(*files):
    s = {os.path.normcase(str(f)) for f in files}
    return lambda p: os.path.normcase(str(p)) in s


def test_find_npm_shim_resolves_to_real_exe():
    from app.engines.claude_setup import find_installs
    appdata = r"C:\Users\x y\AppData\Roaming"
    shim = appdata + r"\npm\claude.CMD"
    real = appdata + r"\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe"
    env = {"APPDATA": appdata, "PATH": appdata + r"\npm"}
    found = find_installs(env=env, which=lambda n, path=None: shim, home=r"C:\Users\x y", exists=_fs(shim, real))
    assert len(found) == 1                                  # PATH의 claude.CMD와 %APPDATA%\npm\claude.cmd는 같은 것
    assert found[0]["path"] == real and found[0]["kind"] == "npm" and found[0]["shim"] == shim


def test_find_npm_shim_without_real_exe_keeps_shim():
    from app.engines.claude_setup import find_installs
    shim = r"C:\Users\a\AppData\Roaming\npm\claude.cmd"
    found = find_installs(env={"APPDATA": r"C:\Users\a\AppData\Roaming"}, which=lambda n, path=None: None,
                          home=r"C:\Users\a", exists=_fs(shim))
    assert found == [{"path": shim, "kind": "npm", "kind_label": "npm 설치"}]


def test_find_native_winget_override_and_missing():
    from app.engines.claude_setup import find_installs
    native = r"C:\Users\a\.local\bin\claude.exe"
    winget = r"C:\Users\a\AppData\Local\Microsoft\WinGet\Links\claude.exe"
    env = {"LOCALAPPDATA": r"C:\Users\a\AppData\Local", "BYORBIT_CLAUDE": r"D:\tools\claude.exe"}
    found = find_installs(env=env, which=lambda n, path=None: native, home=r"C:\Users\a",
                          exists=_fs(native, winget, r"D:\tools\claude.exe"))
    assert [(f["kind"], f["path"]) for f in found] == [
        ("override", r"D:\tools\claude.exe"), ("native", native), ("winget", winget)]
    assert find_installs(env={}, which=lambda n, path=None: None, home=r"C:\nobody", exists=lambda p: False) == []


def test_classify():
    from app.engines.claude_setup import classify
    assert classify(r"C:\Users\a\AppData\Roaming\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe") == "npm"
    assert classify(r"C:\Users\a\AppData\Roaming\npm\claude.cmd") == "npm"
    assert classify(r"C:\Users\a\.local\bin\claude.exe") == "native"
    assert classify("/home/a/.local/bin/claude") == "native"
    assert classify(r"C:\Users\a\AppData\Local\Microsoft\WinGet\Links\claude.exe") == "winget"
    assert classify(r"D:\x\claude.exe") == "other"


# ---------------------------------------------------------------- 로그인 상태

def test_parse_auth_status_json_logged_in_hides_personal_fields():
    from app.engines.claude_setup import parse_auth_status
    out = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty",
                      "email": "me@example.com", "orgName": "Org", "orgId": "x", "subscriptionType": "max",
                      "loginExpiresAt": "2026-12-15T15:01:26.104Z"})
    r = parse_auth_status(out, "", 0)
    assert r["logged_in"] is True and r["method_label"] == "Claude 계정(구독)" and r["plan"] == "max"
    assert "me@example.com" not in json.dumps(r) and "Org" not in json.dumps(r)


def test_parse_auth_status_variants():
    from app.engines.claude_setup import parse_auth_status
    out = '{\n  "loggedIn": false,\n  "authMethod": "none",\n  "apiProvider": "firstParty"\n}'
    assert parse_auth_status(out, "", 1)["logged_in"] is False
    assert parse_auth_status("Not logged in. Run claude auth login to authenticate.", "", 1)["logged_in"] is False
    assert parse_auth_status("Logged in as someone (Claude Max)", "", 0)["logged_in"] is True
    old = parse_auth_status("", "error: unknown command 'auth'", 1)
    assert old["logged_in"] is None and "상태 명령이 없습니다" in old["reason"]
    bedrock = parse_auth_status('{"loggedIn": false, "apiProvider": "bedrock"}', "", 1)
    assert bedrock["logged_in"] is None and "bedrock" in bedrock["reason"]
    assert parse_auth_status("", "", 1)["logged_in"] is None
    noisy = 'Warning: something\n{"loggedIn": true, "authMethod": "api_key"}'
    assert parse_auth_status(noisy)["logged_in"] is True and parse_auth_status(noisy)["method_label"] == "API 키"


# ---------------------------------------------------------------- 등록 명령

SPEC = {"type": "stdio", "command": r"C:\Program Files\R D\.venv\Scripts\python.exe", "args": ["-m", "app.mcp_server"],
        "env": {"PYTHONPATH": r"C:\Program Files\R D", "BYORBIT_HOME": r"C:\Users\김 연구\ByOrbit-RD",
                "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}}


def test_add_json_command_exact_args():
    from app.engines.claude_setup import add_json_command, remove_command
    cmd = add_json_command("claude.exe", SPEC)
    assert cmd[:6] == ["claude.exe", "mcp", "add-json", "--scope", "user", SERVER]
    assert len(cmd) == 7 and json.loads(cmd[6]) == SPEC
    assert remove_command("claude.exe") == ["claude.exe", "mcp", "remove", "--scope", "user", SERVER]


def test_add_command_puts_name_before_variadic_env():
    """2.1.332: `mcp add --scope user -e K=V byorbit-rd -- …`는 -e가 이름을 삼켜 실패한다 → 이름이 먼저."""
    from app.engines.claude_setup import add_command
    cmd = add_command("claude.exe", SPEC)
    assert cmd[:6] == ["claude.exe", "mcp", "add", "--scope", "user", SERVER]
    i = cmd.index("--")
    assert cmd[i + 1:] == [SPEC["command"], "-m", "app.mcp_server"]
    envs = [cmd[j + 1] for j in range(6, i) if cmd[j] == "-e"]
    assert envs == [f"{k}={v}" for k, v in SPEC["env"].items()] and len(cmd[6:i]) == 2 * len(envs)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 명령줄 따옴표 규칙")
def test_windows_command_line_roundtrip_with_spaces_quotes_and_korean():
    """subprocess가 만드는 명령줄을 Windows(CommandLineToArgvW)가 다시 같은 인자로 나누는지 — 빈칸·따옴표·한글·역슬래시."""
    import ctypes
    from ctypes import wintypes

    from app.engines.claude_setup import add_command, add_json_command
    f = ctypes.windll.shell32.CommandLineToArgvW
    f.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    f.restype = ctypes.POINTER(wintypes.LPWSTR)
    for cmd in (add_json_command(r"C:\Program Files\claude\claude.exe", SPEC),
                add_command(r"C:\Program Files\claude\claude.exe", SPEC)):
        line = subprocess.list2cmdline(cmd)
        n = ctypes.c_int()
        argv = f(line, ctypes.byref(n))
        back = [argv[i] for i in range(n.value)]
        ctypes.windll.kernel32.LocalFree(argv)
        assert back == cmd
    assert json.loads(add_json_command("c", SPEC)[-1])["env"]["BYORBIT_HOME"] == r"C:\Users\김 연구\ByOrbit-RD"


def test_manual_command_quotes_paths_with_spaces():
    from app.engines.claude_setup import manual_command
    s = manual_command(SPEC)
    assert s.startswith(f"claude mcp add --scope user {SERVER} -e ")
    assert f'-- "{SPEC["command"]}" -m app.mcp_server' in s
    assert '-e "BYORBIT_HOME=C:\\Users\\김 연구\\ByOrbit-RD"' in s and "-e PYTHONUTF8=1" in s


# ---------------------------------------------------------------- 등록 상태 해석

def test_parse_mcp_get_registered_real_output():
    from app.engines.claude_setup import parse_mcp_get
    r = parse_mcp_get(get_text(SPEC))
    assert r["registered"] and r["scope"] == "user" and r["connected"] is True
    assert r["command"] == SPEC["command"] and r["args"] == "-m app.mcp_server" and r["env"] == SPEC["env"]


def test_parse_mcp_get_failed_pending_missing_unreadable():
    from app.engines.claude_setup import parse_mcp_get
    failed = get_text(SPEC, status="✘ Failed to connect").replace(
        "  Type: stdio", "  Issue: CONNECTION_CLOSED: Connection closed\n  Type: stdio")
    r = parse_mcp_get(failed)
    assert r["connected"] is False and r["issue"] == "CONNECTION_CLOSED: Connection closed"
    assert parse_mcp_get(get_text(SPEC, status="⏸ Pending approval", scope="Local config"))["connected"] is None
    assert parse_mcp_get(get_text(SPEC, scope="Local config (private to you in this project)"))["scope"] == "local"
    assert parse_mcp_get(f'No MCP server named "{SERVER}". Run `claude mcp add` to add one.', 1) == {"registered": False}
    assert parse_mcp_get("something odd happened", 1) is None


def test_parse_mcp_list():
    from app.engines.claude_setup import parse_mcp_list
    out = ("Checking MCP server health…\n\nother: npx other-server - ✔ Connected\n"
           f"{SERVER}: C:\\x\\python.exe -m app.mcp_server - ✘ Failed to connect — CONNECTION_CLOSED\n")
    r = parse_mcp_list(out)
    assert r["registered"] and r["connected"] is False
    assert parse_mcp_list("other: npx other - ✔ Connected\n") == {"registered": False}
    assert parse_mcp_list("No MCP servers configured. Use `claude mcp add` to add a server.") == {"registered": False}
    assert parse_mcp_list(f"{SERVER}: python -m app.mcp_server - ✔ Connected")["connected"] is True


def test_compare_registration_detects_moved_folders():
    from app.engines.claude_setup import compare_registration, parse_mcp_get
    same = compare_registration(parse_mcp_get(get_text(SPEC)), SPEC)
    assert same["current"] is True
    moved = dict(SPEC, env=dict(SPEC["env"], BYORBIT_HOME=r"D:\old\ByOrbit-RD"))
    r = compare_registration(parse_mcp_get(get_text(moved)), SPEC)
    assert r["current"] is False and "다른 데이터 폴더" in r["mismatch"]
    other_py = dict(SPEC, command=r"C:\old\python.exe")
    assert "다른 파이썬" in compare_registration(parse_mcp_get(get_text(other_py)), SPEC)["mismatch"]
    # 대소문자·슬래시 차이는 같은 경로로 본다(Windows)
    if sys.platform == "win32":
        low = dict(SPEC, command=SPEC["command"].upper())
        assert compare_registration(parse_mcp_get(get_text(low)), SPEC)["current"] is True


# ---------------------------------------------------------------- 등록·해제 (가짜 실행기)

def test_register_removes_then_adds_json(cs, home):
    from app.engines import claude_code
    fake = FakeCLI(registered=None)
    r = cs.register(runner=fake)
    assert r["ok"] and r["used"] == "add-json" and "사용자 설정" in r["message"]
    assert fake.args() == [["mcp", "remove", "--scope", "user", SERVER],
                           ["mcp", "add-json", "--scope", "user", SERVER, json.dumps(claude_code.rd_server_config(), ensure_ascii=False)]]
    assert fake.reg == claude_code.rd_server_config()
    from app import config
    assert fake.reg["env"]["BYORBIT_HOME"] == str(config.data_home()) and fake.reg["command"] == sys.executable
    kw = fake.calls[1][1]
    assert kw["stdin"] is subprocess.DEVNULL and kw["cwd"] == str(config.data_home())   # 표준입력 JSON 금지, 데이터 폴더에서 실행
    # 앱 쪽 mcp.json도 같은 값
    cfg = json.loads((home / "config" / "mcp.json").read_text(encoding="utf-8"))
    assert cfg["mcpServers"][SERVER] == fake.reg


def test_register_falls_back_to_mcp_add_on_old_cli(cs):
    fake = FakeCLI(add_json=False)
    r = cs.register(runner=fake)
    assert r["ok"] and r["used"] == "add"
    assert fake.args()[-1][:6] == ["mcp", "add", "--scope", "user", SERVER, "-e"]
    from app.engines import claude_code
    assert fake.reg == claude_code.rd_server_config()


def test_register_failure_and_bad_scope(cs):
    r = cs.register(runner=FakeCLI(add_rc=1))
    assert not r["ok"] and "등록하지 못했습니다" in r["message"]
    with pytest.raises(ValueError):
        cs.register(scope="project", runner=FakeCLI())


def test_unregister(cs):
    from app.engines import claude_code
    fake = FakeCLI(registered=claude_code.rd_server_config())
    r = cs.unregister(runner=fake)
    assert r["ok"] and not r.get("already") and fake.reg is None
    assert fake.args() == [["mcp", "remove", "--scope", "user", SERVER]]
    r = cs.unregister(runner=fake)
    assert r["ok"] and r["already"]


def test_register_without_cli(cs, monkeypatch):
    from app.engines import claude_code
    monkeypatch.setattr(claude_code, "executable", lambda: None)
    assert not cs.register(runner=FakeCLI())["ok"]
    assert not cs.unregister(runner=FakeCLI())["ok"]


# ---------------------------------------------------------------- 전체 상태·종료 코드

def test_status_ready_not_registered(cs, monkeypatch):
    fake = FakeCLI()
    monkeypatch.setattr(cs, "RUNNER", fake)
    st = cs.status(cached=False)
    assert st["installed"] and st["version"] == "2.1.332 (Claude Code)" and st["kind"] == "other"
    assert st["logged_in"] is True and st["login"]["plan"] == "max"
    assert st["registration"] == {"registered": False} and st["ready"]
    assert cs.exit_code(st) == cs.EXIT_READY
    assert any("④" in s for s in st["next_steps"])
    assert "someone@example.com" not in json.dumps(st, ensure_ascii=False)
    # 돈이 드는 호출(-p)은 하지 않는다
    assert all("-p" not in a for a in fake.args())
    assert [a[:2] for a in fake.args()] == [["--version"], ["auth", "status"], ["mcp", "get"]]


def test_status_registered_current_and_cache(cs, monkeypatch):
    from app.engines import claude_code
    fake = FakeCLI(registered=claude_code.rd_server_config())
    monkeypatch.setattr(cs, "RUNNER", fake)
    st = cs.status(cached=False)
    assert st["registration"]["registered"] and st["registration"]["current"] is True
    assert cs.exit_code(st) == cs.EXIT_REGISTERED
    n = len(fake.calls)
    assert cs.status()["cached"] is True and len(fake.calls) == n          # 60초 안에는 다시 부르지 않는다
    assert cs.status(registration=False)["cached"] is True
    assert cs.status(cached=False)["cached"] is False and len(fake.calls) > n


def test_recheck_replaces_stale_fast_cache(cs, monkeypatch):
    """화면은 빠른 확인(registration=false)을 먼저 부른다 — '다시 확인' 뒤에 예전 빠른 값이 나오면 안 된다."""
    fake = FakeCLI(logged_in=False)
    monkeypatch.setattr(cs, "RUNNER", fake)
    assert cs.status(registration=False)["logged_in"] is False
    fake.logged_in = True                                            # 사용자가 터미널에서 로그인함
    assert cs.status(registration=False)["logged_in"] is False       # 60초 캐시
    assert cs.status(cached=False)["logged_in"] is True              # 다시 확인
    assert cs.status(registration=False)["logged_in"] is True


def test_status_fast_skips_registration(cs, monkeypatch):
    fake = FakeCLI()
    monkeypatch.setattr(cs, "RUNNER", fake)
    st = cs.status(cached=False, registration=False)
    assert st["registration"] is None and ["mcp", "get"] not in [a[:2] for a in fake.args()]


def test_status_not_logged_in_and_not_installed(cs, monkeypatch):
    from app.engines import claude_code
    monkeypatch.setattr(cs, "RUNNER", FakeCLI(logged_in=False))
    st = cs.status(cached=False)
    assert st["logged_in"] is False and cs.exit_code(st) == cs.EXIT_NOT_LOGGED_IN and not st["ready"]
    assert any("'claude'를 실행" in s for s in st["next_steps"])
    cs._CACHE.clear()
    monkeypatch.setattr(claude_code, "executable", lambda: None)
    st = cs.status(cached=False)
    assert not st["installed"] and cs.exit_code(st) == cs.EXIT_NOT_INSTALLED
    assert any("irm https://claude.ai/install.ps1 | iex" in s for s in st["next_steps"])
    assert any("npm install -g @anthropic-ai/claude-code" in s for s in st["next_steps"])


def test_status_broken_cli(cs, monkeypatch):
    monkeypatch.setattr(cs, "RUNNER", FakeCLI(version_rc=1))
    st = cs.status(cached=False)
    assert not st["installed"] and "종료 코드 1" in st["message"] and st["login"] is None


def test_status_unknown_login_exit_code(cs, monkeypatch):
    class OldCLI(FakeCLI):
        def __call__(self, args, **kw):
            if list(args[1:3]) == ["auth", "status"]:
                self.calls.append((list(args), kw))
                return R(1, "", "error: unknown command 'auth'")
            return super().__call__(args, **kw)
    monkeypatch.setattr(cs, "RUNNER", OldCLI())
    st = cs.status(cached=False)
    assert st["logged_in"] is None and st["ready"] and cs.exit_code(st) == cs.EXIT_UNKNOWN_LOGIN == 4
    assert any("연결 점검(실제 호출)" in s for s in st["next_steps"])


def test_describe_mentions_each_step(cs, monkeypatch):
    from app.engines import claude_code
    spec = dict(claude_code.rd_server_config(), env=dict(claude_code.rd_server_config()["env"], BYORBIT_HOME=r"D:\old"))
    monkeypatch.setattr(cs, "RUNNER", FakeCLI(registered=spec))
    txt = cs.describe(cs.status(cached=False))
    assert "① 설치" in txt and "② 로그인   : 됨" in txt and "④ 자료 도구: 등록됨" in txt and "지금 앱과 다름" in txt
    assert "다시 등록하세요" in txt


# ---------------------------------------------------------------- 웹 API

@pytest.fixture
def client(cs, monkeypatch):
    from fastapi.testclient import TestClient

    from app.server import app
    app.state.no_watch = True
    fake = FakeCLI()
    monkeypatch.setattr(cs, "RUNNER", fake)
    with TestClient(app) as c:
        c.fake = fake
        yield c


def test_api_status_register_unregister(client):
    from app.engines import claude_code
    s = client.get("/api/setup/status?registration=false").json()
    assert s["installed"] and s["registration"] is None and s["security_note"] and s["usage_example"]
    s = client.get("/api/setup/status").json()
    assert s["registration"] == {"registered": False}
    r = client.post("/api/setup/register", json={"scope": "user"}).json()
    assert r["ok"] and r["status"]["registration"]["registered"] and r["status"]["registration"]["current"]
    assert client.fake.reg == claude_code.rd_server_config()
    assert client.post("/api/setup/recheck").json()["registration"]["current"] is True
    r = client.post("/api/setup/unregister").json()                 # 본문 없이도 user 범위
    assert r["ok"] and r["status"]["registration"] == {"registered": False} and client.fake.reg is None


def test_api_rejects_bad_scope_and_foreign_origin(client):
    assert client.post("/api/setup/register", json={"scope": "project"}).status_code == 400
    local = {"host": "127.0.0.1:8765"}
    r = client.post("/api/setup/register", json={"scope": "user"}, headers={**local, "origin": "http://evil.example"})
    assert r.status_code == 403
    assert client.fake.reg is None and not any(a[:2] == ["mcp", "add-json"] for a in client.fake.args())


# ---------------------------------------------------------------- 명령줄

def test_cli_setup_claude_check_register_unregister(cs, monkeypatch, capsys):
    from app import cli
    fake = FakeCLI()
    monkeypatch.setattr(cs, "RUNNER", fake)
    with pytest.raises(SystemExit) as e:
        cli.main(["setup-claude", "--check"])
    out = capsys.readouterr().out
    assert e.value.code == 0 and "① 설치" in out and "아직 등록 안 됨" in out
    with pytest.raises(SystemExit) as e:
        cli.main(["setup-claude", "--register"])
    out = capsys.readouterr().out
    assert e.value.code == 0 and "[완료]" in out and "사과박 식이섬유" in out and "보호가 약합니다" in out
    with pytest.raises(SystemExit) as e:
        cli.main(["setup-claude"])                                    # 기본은 --check
    assert e.value.code == 5 and "등록됨" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        cli.main(["setup-claude", "--check", "--json"])
    d = json.loads(capsys.readouterr().out)
    assert d["exit_code"] == 5 and e.value.code == 5
    with pytest.raises(SystemExit) as e:
        cli.main(["setup-claude", "--unregister"])
    assert e.value.code == 0 and fake.reg is None
    with pytest.raises(SystemExit):
        cli.main(["setup-claude", "--register", "--unregister"])      # 함께 쓸 수 없음


def test_cli_register_failure_prints_manual_command(cs, monkeypatch, capsys):
    from app import cli
    monkeypatch.setattr(cs, "RUNNER", FakeCLI(add_rc=1))
    with pytest.raises(SystemExit) as e:
        cli.main(["setup-claude", "--register"])
    out = capsys.readouterr().out
    assert e.value.code == 1 and "claude mcp add --scope user byorbit-rd" in out


# ---------------------------------------------------------------- 설치 스크립트·화면 모양

def test_scripts_are_crlf_and_call_setup():
    ps1 = (ROOT / "install.ps1").read_bytes()
    assert ps1.startswith(b"\xef\xbb\xbf"), "install.ps1은 UTF-8 BOM이어야 한글이 PowerShell 5.1에서 깨지지 않는다"
    for name in ("install.ps1", "install.bat", "check-claude.bat", "start.bat"):
        b = (ROOT / name).read_bytes()
        assert b.count(b"\n") == b.count(b"\r\n"), f"{name}은 CRLF여야 한다"
    s = ps1.decode("utf-8-sig")
    assert "setup-claude --check" in s and "setup-claude --register" in s
    assert "(Y/n" in s and "Read-Host" in s and "$cc -eq 0 -or $cc -eq 4" in s
    bat = (ROOT / "check-claude.bat").read_bytes().decode("utf-8")
    assert "setup-claude --check" in bat and "(y/N)" in bat           # 실제 호출은 고를 때만
    assert "-ExecutionPolicy Bypass" in (ROOT / "install.bat").read_text(encoding="utf-8")


def test_wizard_ui_and_home_link():
    idx = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    for i in range(1, 6):
        assert f'id="cw{i}"' in idx
    assert "/api/setup/status" in idx and "/api/setup/register" in idx and "/api/setup/unregister" in idx
    assert "/api/setup/recheck" in idx
    assert 'onclick="openClaudeWizard()"' in idx and "window.openClaudeWizard" in idx
    for k in ("settings.cc.install", "settings.cc.login", "settings.cc.smoke", "settings.cc.register", "settings.cc.move"):
        assert f'data-help="{k}"' in idx


def test_readme_new_pc_section():
    s = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## 다른 PC에 설치하고 Claude Code와 연결하기" in s
    assert "git clone https://github.com/<계정>/byorbit-rnd-studio.git" in s
    assert "setup-claude" in s and "gh auth login" in s
