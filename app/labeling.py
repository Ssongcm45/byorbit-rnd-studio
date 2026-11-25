"""AI 라벨링 실행: 청크를 몇 개씩 묶어 엔진(Claude Code)에 맡기고, 진행률·재시도·취소·이어하기를 DB에 남긴다.

저장 위치 (스키마는 바꾸지 않는다)
- run       : 실행 하나. status = running | done | error | cancelled | interrupted
- run_step  : node_key='doc'   → 실행 정보. input_json = {"doc_id", "batch_size", "max_chunks", "force"}
              node_key=<chunk_id> → 청크 하나. agent_key='labeler'
                status = waiting(아직) | ok | error | skipped
                output_json = {"saved", "pending", "attempts"} 또는 {"error", "attempts"} 또는 {"reason"}

성공 판정은 모델의 답 글이 아니라, 그 호출 동안 그 청크에 method='llm' 라벨이 새로 생겼는지로 한다.
"""
from __future__ import annotations

import json
import threading
import time

from . import db, engines

AGENT = "labeler"
DEFAULT_BATCH = 5
MAX_RETRIES = 2          # 실패한 청크를 다시 묶어 최대 2번 더 시도한다
EMPTY_CONFIRM = 2        # 엔진은 정상인데 저장이 없으면 이 횟수만큼 확인하고 '건너뜀'
MAX_CHUNKS = 500

_cancel: set[str] = set()
_threads: dict[str, threading.Thread] = {}
_active: set[str] = set()   # execute()가 지금 돌고 있는 실행
_lock = threading.Lock()


class LabelError(Exception):
    pass


# ---------------------------------------------------------------- 시작·취소·이어하기

def start(doc_id: str, max_chunks: int | None = None, batch_size: int = DEFAULT_BATCH,
          force: bool = False, background: bool = True) -> str:
    """새 실행을 만들고(청크마다 대기 단계) 백그라운드에서 돌린다. 반환: run_id"""
    if not db.one("SELECT 1 AS x FROM document WHERE doc_id=?", (doc_id,)):
        raise LabelError("자료가 없습니다. 자료함을 새로고침하세요.")
    limit = max(1, min(int(max_chunks or MAX_CHUNKS), MAX_CHUNKS))
    chunks = [r["chunk_id"] for r in db.rows("SELECT chunk_id FROM chunk WHERE doc_id=? ORDER BY ord LIMIT ?",
                                             (doc_id, limit))]
    if not chunks:
        raise LabelError("이 자료에는 청크가 없습니다. 자료함에서 '다시 처리'를 해 보세요.")
    batch_size = max(1, min(int(batch_size or DEFAULT_BATCH), 20))
    done_llm = set() if force else {r["chunk_id"] for r in db.rows(
        "SELECT DISTINCT chunk_id FROM annotation WHERE method='llm' AND chunk_id IN (%s)" % ",".join("?" * len(chunks)),
        chunks)}
    run_id = db.new_id()
    with db.tx() as t:
        t.execute("INSERT INTO run(run_id, status) VALUES (?, 'running')", (run_id,))
        t.execute("INSERT INTO run_step(step_id, run_id, node_key, agent_key, input_json, status) "
                  "VALUES (?,?, 'doc', ?, ?, 'doc')",
                  (db.new_id(), run_id, AGENT, json.dumps({"doc_id": doc_id, "batch_size": batch_size,
                                                            "max_chunks": max_chunks, "force": force})))
        for cid in chunks:
            skipped = cid in done_llm
            t.execute("INSERT INTO run_step(step_id, run_id, node_key, agent_key, status, output_json) "
                      "VALUES (?,?,?,?,?,?)",
                      (db.new_id(), run_id, cid, AGENT, "skipped" if skipped else "waiting",
                       json.dumps({"reason": "이미 AI 라벨이 있어 건너뜀"}, ensure_ascii=False) if skipped else None))
    _launch(run_id, background)
    return run_id


def cancel(run_id: str) -> dict:
    r = _run(run_id)
    if r["status"] != "running":
        return {"ok": False, "status": r["status"], "message": "실행 중이 아닙니다."}
    alive = _alive(run_id)
    if alive:
        _cancel.add(run_id)  # 지금 돌고 있는 묶음이 끝나면 멈춘다
        return {"ok": True, "status": "cancelling", "message": "지금 처리 중인 묶음이 끝나면 멈춥니다."}
    _finish(run_id, "cancelled")
    return {"ok": True, "status": "cancelled"}


def resume(run_id: str, background: bool = True) -> dict:
    """끝나지 않은 청크(대기·오류)만 다시 처리한다."""
    r = _run(run_id)
    if r["status"] == "running" and _alive(run_id):
        raise LabelError("이미 실행 중입니다. 끝나거나 취소한 뒤 다시 시도하세요.")
    left = db.one("SELECT COUNT(*) AS n FROM run_step WHERE run_id=? AND node_key!='doc' "
                  "AND status IN ('waiting','error')", (run_id,))["n"]
    if not left:
        return {"ok": False, "run_id": run_id, "message": "다시 처리할 청크가 없습니다."}
    with db.tx() as t:
        t.execute("UPDATE run_step SET status='waiting' WHERE run_id=? AND node_key!='doc' AND status='error'", (run_id,))
        t.execute("UPDATE run SET status='running', finished_at=NULL WHERE run_id=?", (run_id,))
    _cancel.discard(run_id)
    _launch(run_id, background)
    return {"ok": True, "run_id": run_id, "remaining": left}


def mark_interrupted() -> int:
    """앱을 다시 켰을 때 '실행 중'으로 남은 라벨 실행을 '중단됨'으로 바꾼다."""
    with db.tx() as t:
        cur = t.execute("UPDATE run SET status='interrupted', finished_at=datetime('now') WHERE status='running' "
                        "AND run_id IN (SELECT run_id FROM run_step WHERE node_key='doc' AND agent_key=?)", (AGENT,))
        return cur.rowcount


def _launch(run_id: str, background: bool) -> None:
    if not background:
        execute(run_id)
        return
    th = threading.Thread(target=execute, args=(run_id,), daemon=True, name=f"label-{run_id[:8]}")
    with _lock:
        _threads[run_id] = th
    th.start()


def _alive(run_id: str) -> bool:
    with _lock:
        th = _threads.get(run_id)
        return run_id in _active or bool(th and th.is_alive())


# ---------------------------------------------------------------- 실행

def _prompt(chunk_ids: list[str]) -> str:
    return ("다음 청크들을 하나씩 get_chunk로 읽고, 지침에 따라 청크마다 save_annotations로 라벨을 저장하세요. "
            "수치 측정값을 놓치지 마세요. 다 끝나면 저장 건수만 한 줄로 보고하세요.\n" + "\n".join(chunk_ids))


def _llm_anns(chunk_ids: list[str]) -> dict[str, dict[str, str]]:
    """청크별 {ann_id: status} (method=llm)."""
    out: dict[str, dict[str, str]] = {c: {} for c in chunk_ids}
    if chunk_ids:
        for r in db.rows("SELECT ann_id, chunk_id, status FROM annotation WHERE method='llm' AND chunk_id IN (%s)"
                         % ",".join("?" * len(chunk_ids)), chunk_ids):
            out[r["chunk_id"]][r["ann_id"]] = r["status"]
    return out


def _engine_name(eng) -> str:
    name = getattr(eng, "__name__", "") or type(eng).__name__
    return "codex" if "codex" in name else "claude" if "claude" in name else name.rsplit(".", 1)[-1]


def execute(run_id: str) -> str:
    """대기 중인 청크를 묶음별로 처리한다. 반환: 최종 상태"""
    with _lock:
        _active.add(run_id)
    try:
        return _execute(run_id)
    finally:
        with _lock:
            _active.discard(run_id)


def _execute(run_id: str) -> str:
    meta = json.loads(db.one("SELECT input_json FROM run_step WHERE run_id=? AND node_key='doc'", (run_id,))["input_json"])
    batch_size = int(meta.get("batch_size") or DEFAULT_BATCH)
    try:
        waiting = [r["node_key"] for r in db.rows(
            "SELECT s.node_key FROM run_step s LEFT JOIN chunk c ON c.chunk_id=s.node_key "
            "WHERE s.run_id=? AND s.node_key!='doc' AND s.status='waiting' ORDER BY c.ord", (run_id,))]
        for i in range(0, len(waiting), batch_size):
            if run_id in _cancel:
                break
            _process_batch(run_id, waiting[i:i + batch_size])
    except Exception as e:  # noqa: BLE001 — 예기치 못한 오류도 실행 기록에 남긴다
        _finish(run_id, "error", note=str(e))
        return "error"
    if run_id in _cancel:
        _cancel.discard(run_id)
        _finish(run_id, "cancelled")
        return "cancelled"
    errors = db.one("SELECT COUNT(*) AS n FROM run_step WHERE run_id=? AND node_key!='doc' AND status IN ('error','waiting')",
                    (run_id,))["n"]
    status = "error" if errors else "done"
    _finish(run_id, status)
    if status == "done":
        _mark_doc(meta["doc_id"])
    return status


def _process_batch(run_id: str, chunk_ids: list[str]) -> None:
    left = list(chunk_ids)
    attempts = 0
    last_err = ""
    empty_ok: dict[str, int] = {}
    while left and attempts <= MAX_RETRIES:
        if attempts and run_id in _cancel:
            return  # 취소: 남은 청크는 대기로 둔다(이어하기 가능)
        attempts += 1
        before = _llm_anns(left)
        eng = engines.get()
        t0 = time.time()
        try:
            r = eng.run(_prompt(left), role=AGENT, write=True, max_turns=6 + 4 * len(left),
                        task="label", run_id=run_id) or {}
        except Exception as e:  # noqa: BLE001
            r = {"ok": False, "error": str(e)}
        dur = int((time.time() - t0) * 1000)
        after = _llm_anns(left)
        still = []
        for cid in left:
            new = {a: s for a, s in after[cid].items() if a not in before[cid]}
            if new:
                _step(run_id, cid, "ok", _engine_name(eng), r.get("session_id"), dur,
                      {"saved": len(new), "pending": sum(1 for s in new.values() if s == "pending"),
                       "attempts": attempts})
            elif r.get("ok"):
                # 엔진은 정상 종료했는데 저장이 없다 — 정말 라벨할 것이 없는 청크일 수 있다.
                # 한 번만 다시 확인하고, 그래도 없으면 오류가 아니라 '건너뜀'으로 둔다(불필요한 재호출 비용 방지).
                empty_ok[cid] = empty_ok.get(cid, 0) + 1
                if empty_ok[cid] >= EMPTY_CONFIRM:
                    _step(run_id, cid, "skipped", _engine_name(eng), r.get("session_id"), dur,
                          {"reason": "AI가 라벨할 내용을 찾지 못했습니다(2번 확인).", "attempts": attempts})
                else:
                    still.append(cid)
            else:
                still.append(cid)
        if still:
            last_err = (r.get("error") or ("" if r.get("ok") else r.get("result")) or
                        "AI가 이 청크에 라벨을 저장하지 않았습니다.")
        left = still
    for cid in left:
        _step(run_id, cid, "error", None, None, None, {"error": str(last_err)[:500], "attempts": attempts})


def _step(run_id, chunk_id, status, engine, session_id, duration_ms, output) -> None:
    with db.tx() as t:
        t.execute("UPDATE run_step SET status=?, engine=COALESCE(?, engine), session_id=COALESCE(?, session_id), "
                  "duration_ms=COALESCE(?, duration_ms), output_json=? WHERE run_id=? AND node_key=?",
                  (status, engine, session_id, duration_ms, json.dumps(output, ensure_ascii=False), run_id, chunk_id))


def _finish(run_id: str, status: str, note: str | None = None) -> None:
    with db.tx() as t:
        t.execute("UPDATE run SET status=?, finished_at=datetime('now') WHERE run_id=?", (status, run_id))
        if note:
            t.execute("UPDATE run_step SET output_json=? WHERE run_id=? AND node_key='doc'",
                      (json.dumps({"error": note[:1000]}, ensure_ascii=False), run_id))


def _mark_doc(doc_id: str) -> None:
    d = db.one("SELECT parse_status FROM document WHERE doc_id=?", (doc_id,))
    if not d:
        return
    st = json.loads(d["parse_status"] or "{}")
    st["label"] = "llm"
    with db.tx() as t:
        t.execute("UPDATE document SET parse_status=? WHERE doc_id=?", (json.dumps(st), doc_id))


# ---------------------------------------------------------------- 조회

def _run(run_id: str) -> dict:
    r = db.one("SELECT * FROM run WHERE run_id=?", (run_id,))
    if not r or not db.one("SELECT 1 AS x FROM run_step WHERE run_id=? AND node_key='doc' AND agent_key=?",
                           (run_id, AGENT)):
        raise KeyError(run_id)
    return r


def status(run_id: str) -> dict:
    r = _run(run_id)
    meta_row = db.one("SELECT input_json, output_json FROM run_step WHERE run_id=? AND node_key='doc'", (run_id,))
    meta = json.loads(meta_row["input_json"] or "{}")
    steps = db.rows("SELECT s.node_key AS chunk_id, c.ord, s.status, s.engine, s.session_id, s.duration_ms, "
                    "s.output_json FROM run_step s LEFT JOIN chunk c ON c.chunk_id=s.node_key "
                    "WHERE s.run_id=? AND s.node_key!='doc' ORDER BY c.ord", (run_id,))
    for s in steps:
        s["output"] = json.loads(s.pop("output_json") or "null")
    cnt = {k: sum(1 for s in steps if s["status"] == k) for k in ("ok", "error", "skipped", "waiting")}
    ids = [s["chunk_id"] for s in steps]
    pending = db.one("SELECT COUNT(*) AS n FROM annotation WHERE method='llm' AND status='pending' AND chunk_id IN (%s)"
                     % ",".join("?" * len(ids)), ids)["n"] if ids else 0
    st = r["status"]
    if st == "running" and run_id in _cancel:
        st = "cancelling"
    return {"run_id": run_id, "doc_id": meta.get("doc_id"), "status": st, "started_at": r["started_at"],
            "finished_at": r["finished_at"], "batch_size": meta.get("batch_size"), "force": meta.get("force"),
            "total": len(steps), "done": cnt["ok"] + cnt["error"] + cnt["skipped"], "ok": cnt["ok"],
            "error": cnt["error"], "skipped": cnt["skipped"], "waiting": cnt["waiting"],
            "pending_labels": pending, "note": json.loads(meta_row["output_json"] or "null"), "steps": steps}


def list_runs(doc_id: str | None = None, limit: int = 50) -> list[dict]:
    rows = db.rows("SELECT r.run_id, r.status, r.started_at, r.finished_at, s.input_json FROM run r "
                   "JOIN run_step s ON s.run_id=r.run_id AND s.node_key='doc' AND s.agent_key=? "
                   "ORDER BY r.started_at DESC, r.rowid DESC", (AGENT,))
    out = []
    for r in rows:
        meta = json.loads(r.pop("input_json") or "{}")
        if doc_id and meta.get("doc_id") != doc_id:
            continue
        c = {x["status"]: x["n"] for x in db.rows(
            "SELECT status, COUNT(*) AS n FROM run_step WHERE run_id=? AND node_key!='doc' GROUP BY status", (r["run_id"],))}
        r.update({"doc_id": meta.get("doc_id"), "total": sum(c.values()), "ok": c.get("ok", 0),
                  "error": c.get("error", 0), "skipped": c.get("skipped", 0), "waiting": c.get("waiting", 0)})
        if r["status"] == "running" and r["run_id"] in _cancel:
            r["status"] = "cancelling"
        out.append(r)
        if len(out) >= limit:
            break
    return out
