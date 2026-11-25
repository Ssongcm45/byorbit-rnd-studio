"""Codex 엔진 어댑터 시험(가짜 실행기). 실제 CLI는 부르지 않는다."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

PRE = ["codex.exe"]


@pytest.fixture(scope="module")
def chome(tmp_path_factory):
    """이 모듈 전용 데이터 폴더. 끝나면 BYORBIT_HOME을 되돌린다(다른 시험 모듈과 섞이지 않게)."""
    from app import db, thesaurus
    old = os.environ.get("BYORBIT_HOME")
    h = tmp_path_factory.mktemp("codex_home")
    os.environ["BYORBIT_HOME"] = str(h)
    thesaurus.invalidate()
    db.init(seed=True)
    try:
        yield h
    finally:
        if old is None:
            os.environ.pop("BYORBIT_HOME", None)
        else:
            os.environ["BYORBIT_HOME"] = old
        thesaurus.invalidate()


@pytest.fixture
def cx(chome, monkeypatch):
    from app import config
    from app.engines import codex
    monkeypatch.setattr(codex, "command_prefix", lambda: list(PRE))
    for k in (codex.FORCE_ENV, codex.ALLOW_CONF_ENV, codex.MODEL_ENV, codex.FORCE_BLOCK_ENV):
        monkeypatch.delenv(k, raising=False)
    config.save_settings({"food_mcp": False, "food_mcp_dir": ""})
    yield codex
    config.save_settings({"food_mcp": False, "food_mcp_dir": ""})


class FakeProc:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def jl(*events):
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events)


OK_EVENTS = jl(
    {"type": "thread.started", "thread_id": "th-1"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "i0", "type": "agent_message", "text": "찾아볼게요."}},
    {"type": "item.completed", "item": {"id": "i1", "type": "mcp_tool_call", "server": "byorbit-rd",
                                        "tool": "lookup_concept", "status": "completed", "error": None}},
    {"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": "사과박"}},
    {"type": "turn.completed", "usage": {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 3}},
)


def capture(seen, stdout=OK_EVENTS, rc=0, stderr=""):
    def runner(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return FakeProc(stdout, rc, stderr)
    return runner


def _cfg(cmd, key):
    """-c key=value 의 value 목록."""
    return [cmd[i + 1].split("=", 1)[1] for i, a in enumerate(cmd[:-1])
            if a == "-c" and cmd[i + 1].split("=", 1)[0] == key]


def _toml(v):
    import tomllib
    return tomllib.loads(f"x={v}")["x"]


# ---------------------------------------------------------------- 명령

def test_command_construction(cx):
    from app import config
    seen = {}
    r = cx.run("질문", role="librarian", write=False, runner=capture(seen))
    assert r["ok"] and r["result"] == "사과박" and r["session_id"] == "th-1"
    cmd, kw = seen["cmd"], seen["kw"]
    assert cmd[:2] == ["codex.exe", "exec"] and cmd[-1] == "-"
    for flag in ("--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config"):
        assert flag in cmd
    assert cmd[cmd.index("-s") + 1] == "read-only"
    assert cmd[cmd.index("-C") + 1] == str(config.data_home())
    disabled = {cmd[i + 1] for i, a in enumerate(cmd) if a == "--disable"}
    assert {"shell_tool", "unified_exec", "view_image", "plugins", "apps", "computer_use",
            "browser_use", "multi_agent"} <= disabled
    assert "code_mode_host" not in disabled  # 끄면 MCP 도구도 못 부른다(시험으로 확인)
    assert _cfg(cmd, "web_search") == ['"disabled"']
    assert _cfg(cmd, "approval_policy") == ['"never"']
    # MCP 서버: TOML로 올바르게 읽히는지(Windows 경로의 백슬래시 포함)
    assert _toml(_cfg(cmd, "mcp_servers.byorbit-rd.command")[0]) == sys.executable
    assert _toml(_cfg(cmd, "mcp_servers.byorbit-rd.args")[0]) == ["-m", "app.mcp_server"]
    env = _toml(_cfg(cmd, "mcp_servers.byorbit-rd.env")[0])
    assert env["BYORBIT_HOME"] == str(config.data_home()) and env["PYTHONPATH"] == str(config.APP_ROOT)
    assert cx.FORCE_ENV not in env  # 시험에서 파일 읽기 막힘 확인 → 평소 CoA 규칙
    assert _toml(_cfg(cmd, "mcp_servers.byorbit-rd.enabled_tools")[0]) == cx.READ_TOOLS
    assert _toml(_cfg(cmd, "mcp_servers.byorbit-rd.default_tools_approval_mode")[0]) == "approve"
    assert "extract_label_table" not in " ".join(cmd)
    assert not any(a.startswith("mcp_servers.byorbit-food") for a in cmd)
    # 프롬프트는 표준입력, 역할 지침이 앞에 붙는다
    assert kw["input"].endswith("질문") and cx.agent_instructions("librarian") in kw["input"]
    assert kw["cwd"] == str(config.data_home())


def test_write_tools_and_model(cx, monkeypatch):
    monkeypatch.setenv(cx.MODEL_ENV, "gpt-test")
    seen = {}
    cx.run("Q", role=None, write=True, runner=capture(seen))
    cmd = seen["cmd"]
    assert _toml(_cfg(cmd, "mcp_servers.byorbit-rd.enabled_tools")[0]) == cx.READ_TOOLS + cx.WRITE_TOOLS
    assert cmd[cmd.index("-m") + 1] == "gpt-test"


def test_toml_quoting_windows_path():
    from app.engines.codex import toml_str, toml_table
    p = r"C:\Users\a b\new\tmp 'x'"
    assert _toml(toml_str(p)) == p
    assert _toml(toml_table({"A": p, "B": "한글"})) == {"A": p, "B": "한글"}


def test_food_attached_only_when_active(cx, tmp_path, monkeypatch):
    from app import config
    from app.engines import food_mcp
    d = tmp_path / "food-agent"
    (d / "mcp").mkdir(parents=True)
    (d / "mcp" / "food-db-server.mjs").write_text("// dummy\n", encoding="utf-8")
    monkeypatch.setattr(food_mcp, "node_executable", lambda: "node")
    config.save_settings({"food_mcp": True, "food_mcp_dir": str(d)})
    seen = {}
    assert cx.run("Q", role="librarian", runner=capture(seen))["ok"]
    cmd = seen["cmd"]
    fd = "mcp_servers.byorbit-food"
    assert _toml(_cfg(cmd, f"{fd}.command")[0]) == "node"
    assert _toml(_cfg(cmd, f"{fd}.args")[0]) == [str((d / "mcp" / "food-db-server.mjs").resolve())]
    enabled = _toml(_cfg(cmd, f"{fd}.enabled_tools")[0])
    assert enabled == food_mcp.TOOLS and "extract_label_table" not in enabled
    assert _toml(_cfg(cmd, f"{fd}.disabled_tools")[0]) == ["extract_label_table"]
    assert not _cfg(cmd, f"{fd}.env")  # 시크릿 없음
    assert food_mcp.GUIDE in seen["kw"]["input"]
    config.save_settings({"food_mcp": False})
    seen2 = {}
    cx.run("Q", role="librarian", runner=capture(seen2))
    assert not any(a.startswith(fd) for a in seen2["cmd"])
    assert food_mcp.GUIDE not in seen2["kw"]["input"]


# ---------------------------------------------------------------- 출력 해석

def test_parse_success_and_garbage():
    from app.engines.codex import parse_events
    out = parse_events("Reading prompt from stdin...\n" + OK_EVENTS + "\nnot json {\n{\"type\":\"future.event\",\"x\":1}\n[1,2]")
    assert out["result"] == "사과박" and out["session_id"] == "th-1" and out["error"] is None
    assert out["usage"]["output_tokens"] == 3
    assert out["tool_calls"] == [{"type": "mcp_tool_call", "server": "byorbit-rd", "tool": "lookup_concept",
                                  "status": "completed", "error": None}]


def test_run_error_events(cx):
    failed = jl({"type": "thread.started", "thread_id": "th-2"},
                {"type": "error", "message": "stream disconnected"},
                {"type": "turn.failed", "error": {"message": "401 Unauthorized: please run codex login"}})
    r = cx.run("Q", runner=capture({}, failed, rc=1))
    assert not r["ok"] and "401" in r["error"] and r["session_id"] == "th-2"


def test_run_no_events_uses_stderr(cx):
    r = cx.run("Q", runner=capture({}, "", rc=2, stderr="Error: failed to load bootstrap configuration"))
    assert not r["ok"] and "bootstrap" in r["error"] and r["returncode"] == 2


def test_run_without_final_message_is_not_ok(cx):
    ev = jl({"type": "thread.started", "thread_id": "t"}, {"type": "turn.completed", "usage": {}})
    r = cx.run("Q", runner=capture({}, ev))
    assert not r["ok"] and r["error"]


def test_timeout_logs_usage(cx):
    from app import db

    def runner(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    before = db.one("SELECT COUNT(*) AS n FROM usage_log WHERE engine='codex' AND ok=0")["n"]
    r = cx.run("Q", timeout=7, runner=runner)
    assert not r["ok"] and "7초" in r["error"]
    assert db.one("SELECT COUNT(*) AS n FROM usage_log WHERE engine='codex' AND ok=0")["n"] == before + 1


def test_usage_logged_as_codex(cx):
    from app import db
    cx.run("Q", task="t-codex", run_id=None, runner=capture({}))
    row = db.one("SELECT engine, session_id, ok FROM usage_log WHERE task='t-codex'")
    assert row == {"engine": "codex", "session_id": "th-1", "ok": 1}


def test_not_installed(chome, monkeypatch):
    from app.engines import codex
    monkeypatch.setattr(codex, "command_prefix", lambda: None)
    r = codex.run("Q")
    assert not r["ok"] and "Claude Code" in r["error"]


# ---------------------------------------------------------------- CoA 강제 규칙

def test_force_block_env_passed(cx, monkeypatch):
    seen = {}
    monkeypatch.setattr(cx, "FORCE_BLOCK", True)
    monkeypatch.setenv(cx.ALLOW_CONF_ENV, "1")
    cx.run("Q", runner=capture(seen))
    env = _toml(_cfg(seen["cmd"], "mcp_servers.byorbit-rd.env")[0])
    assert env[cx.FORCE_ENV] == "block"
    # 사용자가 환경 변수로 직접 켤 수도 있다
    monkeypatch.setattr(cx, "FORCE_BLOCK", False)
    monkeypatch.setenv(cx.FORCE_BLOCK_ENV, "1")
    seen2 = {}
    cx.run("Q", runner=capture(seen2))
    assert _toml(_cfg(seen2["cmd"], "mcp_servers.byorbit-rd.env")[0])[cx.FORCE_ENV] == "block"


def test_rule_honors_force_env(chome, monkeypatch):
    from app import config, tools
    config.save_settings({"coa_rule": "mask"})
    monkeypatch.delenv("BYORBIT_FORCE_COA_RULE", raising=False)
    assert tools._rule() == "mask" and tools._visible("기밀")
    monkeypatch.setenv("BYORBIT_FORCE_COA_RULE", "block")
    assert tools._rule() == "block" and not tools._visible("기밀") and tools._visible("내부")


def test_refuse_when_confidential_and_forced(cx, monkeypatch):
    from app import db
    sid = db.new_id()
    with db.tx() as c:
        c.execute("INSERT INTO source(source_id, source_type, title, confidentiality) VALUES (?,?,?,?)",
                  (sid, "coa", "시험 CoA", "기밀"))
    try:
        calls = []
        # 시험 결과(막힘 확인)대로면 거부하지 않는다
        assert cx.FORCE_BLOCK is False
        assert cx.run("Q", runner=lambda cmd, **kw: calls.append(1) or FakeProc(OK_EVENTS))["ok"]
        # 막히지 않는 것으로 판정되면 기밀 자료가 있을 때 실행 자체를 거부한다
        monkeypatch.setattr(cx, "FORCE_BLOCK", True)
        calls.clear()
        r = cx.run("Q", runner=lambda cmd, **kw: calls.append(1) or FakeProc(OK_EVENTS))
        assert not r["ok"] and r.get("refused") and "Claude Code" in r["error"] and calls == []
        monkeypatch.setenv(cx.ALLOW_CONF_ENV, "1")
        assert cx.run("Q", runner=lambda cmd, **kw: FakeProc(OK_EVENTS))["ok"]
    finally:
        with db.tx() as c:
            c.execute("DELETE FROM source WHERE source_id=?", (sid,))


# ---------------------------------------------------------------- 점검

def test_check_smoke_and_auth_hint(cx, monkeypatch):
    monkeypatch.setattr(cx, "version", lambda: {"installed": True, "path": "codex.exe", "version": "codex-cli 0.171.0"})
    ok = cx.check(runner=capture({}))
    assert ok["ok"] and ok["smoke"]["passed"] and ok["shell_disabled"] is True
    assert ok["file_read_blocked"] is True and ok["probe_date"] == "2026-11-24"
    assert ok["policy"]["force_coa_block"] is False
    bad = cx.check(runner=capture({}, jl({"type": "error", "message": "401 Unauthorized"}), rc=1))
    assert not bad["ok"] and "codex login" in bad["hint"]
    other = cx.check(runner=capture({}, jl({"type": "item.completed",
                                            "item": {"type": "agent_message", "text": "모름"}}, {"type": "turn.completed"})))
    assert not other["ok"] and "도구 호출" in other["hint"]
    nosmoke = cx.check(smoke=False)
    assert nosmoke["ok"] and nosmoke["smoke"] is None


def test_native_exe_from_npm_shim(tmp_path, monkeypatch):
    from app.engines import codex
    shim = tmp_path / "codex.cmd"
    shim.write_text("@echo off\n", encoding="utf-8")
    exe = (tmp_path / "node_modules" / "@openai" / "codex" / "node_modules" / "@openai" / "codex-win32-x64"
           / "vendor" / "x86_64-pc-windows-msvc" / "bin")
    exe.mkdir(parents=True)
    name = "codex.exe" if sys.platform == "win32" else "codex"
    (exe / name).write_text("", encoding="utf-8")
    assert codex._native_from_shim(str(shim)) == str(exe / name)
    monkeypatch.setenv("BYORBIT_CODEX", str(shim))
    if sys.platform == "win32":
        assert codex.command_prefix() == [str(exe / name)]
