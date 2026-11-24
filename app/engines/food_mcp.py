"""식품 영양 DB(ByOrbit Food MCP)를 Claude Code 실행에 함께 붙인다(선택).

옆 프로젝트 04_byorbit-agent의 stdio 서버 `node mcp/food-db-server.mjs`를 그대로 쓴다.
농진청 원물·식약처 식품 성분 DB를 조회하는 읽기 전용 도구만 허용한다.
DATABASE_URL은 그 서버가 자기 폴더의 .env.local에서 직접 읽는다 — 이 앱은 그 값을 읽거나 넘기지 않는다.

보안: extract_label_table은 로컬 파일 경로(path)나 URL을 받아 읽는다. 이것을 열면 --tools ""로 막은
파일 읽기가 우회되어 library\\의 기밀 원본을 가림 없이 읽을 수 있으므로 허용 목록에서 빼고 차단 목록에 늘 넣는다.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .. import config

SERVER = "byorbit-food"
TOOLS = ["search_food", "get_food", "compare_foods", "db_stats",
         "search_food_item", "get_food_item", "food_item_stats",
         "verify_nutrition", "verify_food_claim", "nutrition_analysis", "nutrition_research", "dietary_reference"]
EXCLUDED = ["extract_label_table"]
SCRIPT = ("mcp", "food-db-server.mjs")

GUIDE = """## 식품 영양 DB 도구 (byorbit-food)

농진청 원물·식약처 식품 성분 DB를 조회하는 도구를 함께 쓸 수 있습니다.
- 부산물의 측정 성분을 원물 기준값과 견줄 때: search_food → get_food로 농진청 원물 값을 찾고, compare_foods로 비교합니다.
- 주장된 영양 성분 값이 그럴듯한지 볼 때: verify_nutrition을 씁니다.
- 표시·강조 표시 기준을 볼 때: nutrition_analysis, verify_food_claim, dietary_reference를 씁니다.

규칙:
- 식품 DB 값은 참고 기준값입니다. 자료(청크)·측정값 근거와 섞지 말고 "식품 DB(출처명)"로 따로 밝히세요.
- 식품 도구 인자에는 식품명과 성분값만 넣으세요. `[가림]` 표시, 로트번호, 공급처, 시료번호, 파일명은 절대 넣지 마세요."""

_ENV_DIR = "BYORBIT_FOOD_MCP_DIR"


def _has_script(d: Path) -> bool:
    return d.joinpath(*SCRIPT).is_file()


def resolve_dir() -> Path | None:
    """설정 food_mcp_dir → 환경 변수 BYORBIT_FOOD_MCP_DIR → 옆 폴더 04_byorbit-agent 순서로 찾는다."""
    cands = []
    s = str(config.load_settings().get("food_mcp_dir") or "").strip()
    if s:
        cands.append(Path(s).expanduser())
    e = os.environ.get(_ENV_DIR, "").strip()
    if e:
        cands.append(Path(e).expanduser())
    cands.append(config.APP_ROOT.parent / "04_byorbit-agent")
    for d in cands:
        try:
            if _has_script(d):
                return d.resolve()
        except OSError:
            continue
    return None


def node_executable() -> str | None:
    return os.environ.get("BYORBIT_NODE") or shutil.which("node")


def status() -> dict:
    enabled = bool(config.load_settings().get("food_mcp"))
    d = resolve_dir()
    node = node_executable()
    script_exists = bool(d and _has_script(d))
    # .env.local은 있는지만 본다(내용은 읽지 않는다)
    env_local = bool(d and (d / ".env.local").exists())
    ready = bool(d and script_exists and node)
    if not d:
        msg = ("Food MCP 폴더를 찾지 못했습니다. 아래에 04_byorbit-agent 폴더 경로를 넣거나 "
               "환경 변수 BYORBIT_FOOD_MCP_DIR를 지정하세요.")
    elif not node:
        msg = "Node.js(node)를 찾지 못했습니다. Node.js를 설치하거나 환경 변수 BYORBIT_NODE에 node.exe 경로를 지정하세요."
    elif not env_local:
        msg = (f"{d / '.env.local'} 파일이 없습니다. 그 폴더에 DATABASE_URL을 넣은 .env.local을 두어야 "
               "식품 DB를 조회할 수 있습니다.")
    elif not enabled:
        msg = "연결 준비가 되었습니다. '식품 DB 쓰기'를 켜고 저장하면 AI 실행에 붙습니다."
    else:
        msg = "켜짐 — AI 실행에 식품 DB 도구가 함께 붙습니다."
    return {"enabled": enabled, "dir": str(d) if d else None, "node": node, "script_exists": script_exists,
            "env_local_exists": env_local, "ready": ready, "active": enabled and ready, "message": msg}


def active() -> bool:
    return status()["active"]


def server_config() -> dict | None:
    """mcp.json에 넣을 서버 설정. 서버는 자기 파일 위치로 루트를 찾으므로 절대 경로 하나면 된다.
    시크릿은 넣지 않는다 — DATABASE_URL은 서버가 자기 .env.local에서 읽는다."""
    st = status()
    if not st["active"]:
        return None
    return {"type": "stdio", "command": st["node"], "args": [str(Path(st["dir"]).joinpath(*SCRIPT))], "env": {}}


def allowed_tools() -> list[str]:
    return [f"mcp__{SERVER}__{n}" for n in TOOLS] if active() else []


def blocked_tools() -> list[str]:
    """켜져 있든 아니든 늘 차단 목록에 넣는다."""
    return [f"mcp__{SERVER}__{n}" for n in EXCLUDED]


def check(timeout: int = 30, popen=subprocess.Popen) -> dict:
    """서버를 띄워 initialize → tools/list까지 주고받는다. tools/list는 DB에 붙지 않는다.
    Windows 파이프에는 select를 못 쓰므로 읽기 스레드 + 큐로 시간 제한을 둔다."""
    st = status()
    if not st["ready"]:
        return {"ok": False, "tools": [], "missing": list(TOOLS), "error": st["message"], "duration_ms": 0,
                "status": st}
    script = Path(st["dir"]).joinpath(*SCRIPT)
    t0 = time.time()
    out_q: queue.Queue = queue.Queue()
    err_lines: list[str] = []
    proc = None

    def _ms():
        return int((time.time() - t0) * 1000)

    def _stderr_tail():
        return "".join(err_lines).strip()[-1500:]

    try:
        proc = popen([st["node"], str(script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", cwd=st["dir"])

        def _read_out():
            for line in proc.stdout:
                out_q.put(line)
            out_q.put(None)

        def _read_err():
            for line in proc.stderr:
                err_lines.append(line)

        threading.Thread(target=_read_out, daemon=True).start()
        err_t = threading.Thread(target=_read_err, daemon=True)
        err_t.start()

        def _send(msg):
            proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            proc.stdin.flush()

        deadline = t0 + timeout

        def _wait(rid):
            while True:
                left = deadline - time.time()
                if left <= 0:
                    raise TimeoutError
                try:
                    line = out_q.get(timeout=left)
                except queue.Empty:
                    raise TimeoutError
                if line is None:
                    raise EOFError
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == rid:
                    return msg

        try:
            _send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "byorbit-rd-check", "version": config.APP_VERSION}}})
            init = _wait(1)
            if "error" in init:
                return {"ok": False, "tools": [], "missing": list(TOOLS), "duration_ms": _ms(),
                        "error": f"initialize 실패: {init['error']}"}
            _send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            _send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            resp = _wait(2)
        except TimeoutError:  # OSError의 하위 클래스라 먼저 잡는다
            tail = _stderr_tail()
            return {"ok": False, "tools": [], "missing": list(TOOLS), "duration_ms": _ms(),
                    "error": f"{timeout}초 안에 응답이 없었습니다." + (f" 서버 메시지: {tail}" if tail else "")}
        except (OSError, ValueError, EOFError):
            # 서버가 먼저 끝났다(예: DATABASE_URL 없음) — stderr를 조금 더 기다려 모은다
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            err_t.join(timeout=2)
            tail = _stderr_tail()
            return {"ok": False, "tools": [], "missing": list(TOOLS), "duration_ms": _ms(),
                    "error": "Food MCP 서버가 응답 없이 끝났습니다." + (f" 서버 메시지: {tail}" if tail else "")}
        if "error" in resp:
            return {"ok": False, "tools": [], "missing": list(TOOLS), "duration_ms": _ms(),
                    "error": f"tools/list 실패: {resp['error']}"}
        names = [t.get("name") for t in (resp.get("result") or {}).get("tools", []) if isinstance(t, dict)]
        missing = [n for n in TOOLS if n not in names]
        msg = f"도구 {len(names)}개를 확인했습니다. 이 중 {len(TOOLS) - len(missing)}개를 허용합니다."
        if missing:
            msg += f" 없는 도구: {', '.join(missing)}"
        return {"ok": True, "tools": names, "missing": missing,
                "blocked": [n for n in EXCLUDED if n in names], "message": msg, "duration_ms": _ms()}
    except OSError as e:
        return {"ok": False, "tools": [], "missing": list(TOOLS), "duration_ms": _ms(),
                "error": f"Food MCP 서버를 띄우지 못했습니다: {e}"}
    finally:
        if proc is not None:
            try:
                proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
