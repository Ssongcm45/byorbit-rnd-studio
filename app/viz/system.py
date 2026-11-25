"""'두 시스템을 묶은 구조' 지도와 자료 처리 파이프라인 집계.

상태는 값싼 확인만 쓴다(shutil.which·파일 존재·food_mcp.status()). 요청마다 프로세스를 띄우지 않는다.
이 지도의 핵심은 각 경계를 무엇이 넘는지(보안 설명)다.
"""
from __future__ import annotations

from .. import config, db
from ..engines import claude_code, food_mcp


def _codex_exe() -> str | None:
    try:
        from ..engines import codex
        return codex.executable()
    except Exception:  # noqa: BLE001
        return None


def system_map() -> dict:
    s = config.load_settings()
    rule = s.get("coa_rule", "mask")
    claude = claude_code.executable()
    fs = food_mcp.status()
    codex = _codex_exe()
    dbf = config.db_path()
    mcp_cfg = claude_code.mcp_config_path()
    food_state = "ok" if fs["active"] else ("off" if fs["ready"] else "missing")

    nodes = [
        {"id": "browser", "label": "브라우저 화면", "kind": "local", "status": "ok", "col": 0, "row": 1,
         "detail": "이 PC의 브라우저. 127.0.0.1 주소로만 앱에 붙습니다."},
        {"id": "fastapi", "label": "FastAPI 앱 (127.0.0.1)", "kind": "local", "status": "ok", "col": 1, "row": 1,
         "detail": f"로컬 웹 서버(포트 {s.get('port', 8765)}). 외부 네트워크에서는 열리지 않습니다."},
        {"id": "sqlite", "label": "SQLite DB", "kind": "local", "status": "ok" if dbf.exists() else "missing", "col": 2, "row": 2,
         "detail": f"{dbf} — 자료·청크·라벨·측정값·개념. 기밀 CoA 원본 값도 여기에만 있습니다."},
        {"id": "folder", "label": "데이터 폴더", "kind": "local", "status": "ok" if config.data_home().exists() else "missing",
         "col": 1, "row": 3, "detail": f"{config.data_home()} — library(원본 복사본)·reports·structures 캐시."},
        {"id": "watcher", "label": "받은편지함 감시", "kind": "local", "status": "ok" if s.get("watch_inbox") else "off",
         "col": 0, "row": 3, "detail": f"{config.path('inbox')}에 넣은 파일을 자동 처리합니다."
                                       + ("" if s.get("watch_inbox") else " (설정에서 꺼져 있음)")},
        {"id": "claude", "label": "Claude Code (headless, --tools \"\")", "kind": "local",
         "status": "ok" if claude else "missing", "col": 2, "row": 0,
         "detail": (f"{claude} — " if claude else "설치되지 않음. ") +
                   "내장 파일·셸·웹 도구를 모두 뺀 채(--tools \"\") 실행합니다. 자료는 MCP 도구로만 봅니다."},
        {"id": "mcp_rd", "label": f"MCP byorbit-rd ({len(claude_code.READ_TOOLS) + len(claude_code.WRITE_TOOLS)} tools)",
         "kind": "local", "status": "ok" if mcp_cfg.exists() else "missing", "col": 3, "row": 1,
         "tools": claude_code.READ_TOOLS + claude_code.WRITE_TOOLS,
         "detail": "읽기 4개(검색·청크·개념·측정값) + 쓰기 3개(라벨·리포트 초안·개념 제안). 쓰기는 모두 '검토 대기'로만 들어갑니다."},
        {"id": "mcp_food", "label": f"MCP byorbit-food ({len(food_mcp.TOOLS)} tools)", "kind": "local", "status": food_state,
         "col": 3, "row": 0, "tools": list(food_mcp.TOOLS), "blocked": list(food_mcp.EXCLUDED),
         "detail": fs["message"] + " extract_label_table(로컬 파일·URL 읽기)은 켜짐 여부와 관계없이 차단합니다."},
        {"id": "neon", "label": "Neon DB (식품 성분, 클라우드)", "kind": "cloud", "status": "ok" if fs["active"] else "off",
         "col": 4, "row": 0,
         "detail": "농진청 원물·식약처 식품 성분 DB. 접속 정보(DATABASE_URL)는 Food MCP 폴더의 .env.local에만 있고 이 앱은 읽지 않습니다."},
        {"id": "anthropic", "label": "Anthropic (Claude 모델)", "kind": "external", "status": "ok" if claude else "off",
         "col": 4, "row": 1, "detail": "Claude Code 로그인 계정으로 모델을 부릅니다."},
        {"id": "codex", "label": "Codex (선택 엔진)", "kind": "external", "status": "ok" if codex else "missing", "col": 2, "row": 3,
         "detail": (f"{codex}. " if codex else "설치되지 않음(없어도 됨). ") +
                   ("현재 기본 엔진입니다." if s.get("engine") == "codex" else "기본 엔진은 Claude Code입니다.")},
        {"id": "pubchem", "label": "PubChem (구조 보조)", "kind": "external", "status": "off", "col": 4, "row": 2,
         "detail": "분자 구조 화면에서 로컬에 없는 성분을 직접 '가져오기' 할 때만 씁니다."},
    ]
    coa_txt = ("기밀(CoA) 본문·측정값은 보내지 않음(규칙: 보내지 않기)" if rule == "block"
               else "기밀(CoA)은 로트·공급처·시료번호를 [가림] 처리한 뒤 필요한 값만")
    edges = [
        {"from": "browser", "to": "fastapi", "boundary": "local", "label": "화면 요청",
         "crosses": "PC 안(127.0.0.1)에서만 오갑니다. 업로드 파일도 PC 밖으로 나가지 않습니다."},
        {"from": "watcher", "to": "fastapi", "boundary": "local", "label": "새 파일",
         "crosses": "받은편지함 파일을 읽어 처리 파이프라인으로 넘깁니다."},
        {"from": "fastapi", "to": "folder", "boundary": "local", "label": "원본 복사",
         "crosses": "원본 파일을 library\\로 복사(원본은 그대로)."},
        {"from": "fastapi", "to": "sqlite", "boundary": "local", "label": "저장·조회",
         "crosses": "청크·라벨·측정값(기밀 값 포함)이 이 PC의 DB에만 저장됩니다."},
        {"from": "fastapi", "to": "claude", "boundary": "local", "label": "작업 지시",
         "crosses": "질문과 역할 지시만 넘깁니다. --tools \"\"로 파일 읽기·셸·웹 도구가 없습니다."},
        {"from": "claude", "to": "mcp_rd", "boundary": "local", "label": "stdio",
         "crosses": f"도구 7개로만 자료에 접근. {coa_txt}."},
        {"from": "mcp_rd", "to": "sqlite", "boundary": "local", "label": "읽기·쓰기",
         "crosses": "MCP 서버가 DB를 읽고, 쓰기는 pending 상태로만 넣습니다."},
        {"from": "claude", "to": "anthropic", "boundary": "cloud", "label": "질문·가림 처리된 본문",
         "crosses": f"PC 밖으로 나가는 것: 질문, MCP로 받은 청크 본문 일부와 측정값({coa_txt}), 모델 응답. "
                    "원본 파일·파일 경로 접근 권한은 넘어가지 않습니다."},
        {"from": "claude", "to": "mcp_food", "boundary": "local", "label": "stdio (선택)",
         "crosses": "식품명과 성분값만 인자로 넣습니다. [가림]·로트·공급처·시료번호·파일명은 넣지 않도록 지시합니다."},
        {"from": "mcp_food", "to": "neon", "boundary": "cloud", "label": "식품명 검색",
         "crosses": "식품명·성분 검색어가 Neon(클라우드) DB로 갑니다. 공개 식품 성분 데이터만 돌아옵니다."},
        {"from": "fastapi", "to": "codex", "boundary": "external", "label": "선택 엔진",
         "crosses": "Codex를 쓰면 셸을 끄고 실행하며, 파일 읽기가 막히지 않으면 CoA 규칙을 '보내지 않기'로 강제합니다."},
        {"from": "fastapi", "to": "pubchem", "boundary": "external", "label": "영문 성분명만",
         "crosses": "사용자가 '가져오기'를 누를 때만, 영문 성분명 하나만 보냅니다. 시료·공급처·로트 정보는 절대 보내지 않습니다."},
    ]
    return {"nodes": nodes, "edges": edges, "coa_rule": rule,
            "legend": {"local": "이 PC 안", "cloud": "클라우드(데이터가 PC 밖으로)", "external": "외부 서비스(선택)",
                       "ok": "동작", "off": "꺼짐", "missing": "없음·미설정"}}


def pipeline(project: str | None = None) -> dict:
    """투입 → 청크 → 라벨 → 측정값 → 리포트 개수. project가 있으면 그 프로젝트의 자료·시료만."""
    if project:
        p = db.one("SELECT project_id FROM project WHERE name=?", (project,))
        if not p:
            return {"project": project, "error": f"프로젝트 '{project}'가 없습니다. 위쪽 프로젝트 목록에서 고르세요."}
        pid = p["project_id"]
        docs = "(SELECT entity_id FROM project_item WHERE project_id=? AND entity_type='document')"
        dp: tuple = (pid,)
        meas_where = (f"(m.doc_id IN {docs} OR m.sample_id IN (SELECT entity_id FROM project_item "
                      "WHERE project_id=? AND entity_type='sample'))")
        mp: tuple = (pid, pid)
    else:
        docs, dp, meas_where, mp = "(SELECT doc_id FROM document)", (), "1=1", ()
    n_docs = db.one(f"SELECT COUNT(*) AS n FROM document WHERE doc_id IN {docs}", dp)["n"]
    n_coa = db.one(f"SELECT COUNT(*) AS n FROM document d JOIN source s ON s.source_id=d.source_id "
                   f"WHERE d.doc_id IN {docs} AND s.confidentiality='기밀'", dp)["n"]
    n_chunks = db.one(f"SELECT COUNT(*) AS n FROM chunk WHERE doc_id IN {docs}", dp)["n"]
    ann = db.rows(f"SELECT a.method, a.status, COUNT(*) AS n FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id "
                  f"WHERE c.doc_id IN {docs} GROUP BY a.method, a.status", dp)
    by_method: dict = {}
    by_status: dict = {}
    for r in ann:
        by_method[r["method"]] = by_method.get(r["method"], 0) + r["n"]
        by_status[r["status"]] = by_status.get(r["status"], 0) + r["n"]
    meas = {r["entry"]: r["n"] for r in db.rows(
        f"SELECT m.entry, COUNT(*) AS n FROM measurement m WHERE {meas_where} GROUP BY m.entry", mp)}
    reports = {r["status"]: r["n"] for r in db.rows("SELECT status, COUNT(*) AS n FROM report GROUP BY status")}
    stages = [
        {"id": "docs", "label": "투입(자료)", "n": n_docs, "detail": {"기밀(CoA 등)": n_coa, "일반·내부": n_docs - n_coa}},
        {"id": "chunks", "label": "청크", "n": n_chunks, "detail": {}},
        {"id": "labels", "label": "라벨", "n": sum(by_method.values()),
         "detail": {"사전(dict)": by_method.get("dict", 0) + by_method.get("regex", 0), "AI(llm)": by_method.get("llm", 0),
                    "사람": by_method.get("human", 0), "자동 확정": by_status.get("auto", 0),
                    "검토 대기": by_status.get("pending", 0), "승인": by_status.get("accepted", 0),
                    "거절": by_status.get("rejected", 0)}},
        {"id": "meas", "label": "측정값", "n": sum(meas.values()),
         "detail": {"CoA": meas.get("coa", 0), "논문 추출": meas.get("extracted", 0), "직접 입력": meas.get("manual", 0)}},
        {"id": "reports", "label": "리포트", "n": sum(reports.values()),
         "detail": {"초안": reports.get("draft", 0), "확정": sum(v for k, v in reports.items() if k != "draft")}},
    ]
    return {"project": project, "stages": stages,
            "note": "리포트는 프로젝트에 묶이지 않아 전체 개수입니다." if project else None}
