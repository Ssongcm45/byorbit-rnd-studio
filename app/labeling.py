"""AI 라벨링 실행: 청크를 몇 개씩 묶어 엔진(Claude Code)에 맡기고, 진행률·재시도·취소·이어하기를 DB에 남긴다.

저장 위치 (스키마는 바꾸지 않는다)
- run       : 실행 하나. status = running | done | error | cancelled | interrupted
- run_step  : node_key='doc'   → 실행 정보. input_json = {"doc_id", "batch_size", "max_chunks", "force"}
              node_key=<chunk_id> → 청크 하나. agent_key='labeler'
                status = waiting(아직) | ok | error | skipped
                output_json = {"saved", "pending", "attempts"} 또는 {"error", "attempts"} 또는 {"reason"}

성공 판정은 모델의 답 글이 아니라, 그 호출 동안 그 청크에 method='llm' 라벨이 새로 생겼는지로 한다.

AI에 보내는 프롬프트 끝에는 '참고 사례'(사람이 만들거나 고친 라벨, 최대 8개)를 붙인다 — examples_section().
기밀 자료의 사례는 CoA 규칙대로 가리거나(mask) 뺀다(block, Codex는 늘 block).

아래쪽 '문서 작업대' 부분: 사람 라벨 만들기·고치기·지우기, 검토(승인→측정값), 사전 라벨 다시,
동의어·부정 사례·라벨 사례 배우기와 끄기.
"""
from __future__ import annotations

import json
import re
import threading
import time

from . import config, db, engines, thesaurus, tools

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
          force: bool = False, background: bool = True, chunk_ids: list[str] | None = None) -> str:
    """새 실행을 만들고(청크마다 대기 단계) 백그라운드에서 돌린다. chunk_ids를 주면 그 청크만. 반환: run_id"""
    if not db.one("SELECT 1 AS x FROM document WHERE doc_id=?", (doc_id,)):
        raise LabelError("자료가 없습니다. 자료함을 새로고침하세요.")
    limit = max(1, min(int(max_chunks or MAX_CHUNKS), MAX_CHUNKS))
    chunks = [r["chunk_id"] for r in db.rows("SELECT chunk_id FROM chunk WHERE doc_id=? ORDER BY ord LIMIT ?",
                                             (doc_id, MAX_CHUNKS if chunk_ids else limit))]
    if chunk_ids:
        want = set(chunk_ids)
        chunks = [c for c in chunks if c in want][:limit]
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

def _prompt(chunk_ids: list[str], examples: str = "") -> str:
    p = ("다음 청크들을 하나씩 get_chunk로 읽고, 지침에 따라 청크마다 save_annotations로 라벨을 저장하세요. "
         "수치 측정값을 놓치지 마세요. 다 끝나면 저장 건수만 한 줄로 보고하세요.\n" + "\n".join(chunk_ids))
    return p + ("\n\n" + examples if examples else "")


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
        try:
            ex = examples_section(left, _engine_name(eng))
        except Exception:  # noqa: BLE001 — 사례가 없어도 라벨링은 한다
            ex = ""
        t0 = time.time()
        try:
            r = eng.run(_prompt(left, ex), role=AGENT, write=True, max_turns=6 + 4 * len(left),
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


# ================================================================ 문서 작업대: 사람 라벨·검토·학습

EX_LIMIT = 8          # AI 프롬프트에 붙이는 사례 수
CONTEXT = 60          # 사례에 남기는 앞뒤 글자 수
_BASIS = [("건량", "건량"), ("건물", "건량"), ("dry", "건량"), ("DW", "건량"), ("d.w.", "건량"),
          ("습량", "습량"), ("생시료", "습량"), ("wet", "습량"), ("FW", "습량"), ("f.w.", "습량")]
_NUM = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")


class ManualError(LabelError):
    pass


def _doc_byproduct(t, doc_id: str) -> str | None:
    """자료의 부산물: CoA 시료 → 없으면 그 자료에 가장 많이 붙은 부산물 라벨(거절 제외). (server.py와 같은 규칙)"""
    r = t.execute("SELECT byproduct_id FROM sample WHERE coa_doc_id=? AND byproduct_id IS NOT NULL LIMIT 1",
                  (doc_id,)).fetchone()
    if r:
        return r[0]
    r = t.execute("SELECT b.byproduct_id, COUNT(*) AS n FROM annotation a JOIN chunk c ON c.chunk_id=a.chunk_id "
                  "JOIN byproduct b ON b.concept_id=a.concept_id WHERE c.doc_id=? AND a.status!='rejected' "
                  "GROUP BY b.byproduct_id ORDER BY n DESC, MIN(c.ord) LIMIT 1", (doc_id,)).fetchone()
    return r[0] if r else None


def promote_measurement(t, a: dict) -> str | None:
    """승인된 수치 라벨 → 측정값(entry='extracted'). 라벨 검토(server.py)와 작업대가 같이 쓴다. 반환: meas_id"""
    if not a.get("normalized_value"):
        return None
    v = json.loads(a["normalized_value"])
    doc = t.execute("SELECT doc_id FROM chunk WHERE chunk_id=?", (a["chunk_id"],)).fetchone()[0]
    try:
        value = float(str(v.get("value")).replace(",", ""))
    except (TypeError, ValueError):
        value = None
    target = v.get("target") or a["surface_text"]
    meas = db.new_id()
    t.execute("INSERT INTO measurement(meas_id, byproduct_id, target_concept_id, target_text, value, value_text, "
              "unit_concept_id, unit_text, basis, ann_id, doc_id, entry, verified_at) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?, 'extracted', datetime('now'))",
              (meas, _doc_byproduct(t, doc), a["concept_id"], target, value, str(v.get("value")),
               a["unit_concept_id"], v.get("unit"), v.get("basis"), a["ann_id"], doc))
    return meas


def _remove_extracted(t, ann_id: str) -> int:
    n = 0
    for (mid,) in t.execute("SELECT meas_id FROM measurement WHERE ann_id=? AND entry='extracted'", (ann_id,)).fetchall():
        t.execute("DELETE FROM measurement WHERE meas_id=?", (mid,))
        db.log_change(t, "measurement", mid, {"ann_id": ann_id, "entry": "extracted"}, None)
        n += 1
    return n


def review_annotation(ann_id: str, status: str, learn: bool = False) -> dict:
    """라벨 검토 한 건(server.py의 /api/annotations/{id}와 같은 동작).
    learn=True(작업대)면 거절한 사전 라벨을 부정 사례로 배운다(배운 것 목록에서 끌 수 있음)."""
    if status not in ("accepted", "rejected", "pending", "auto"):
        raise ManualError("status는 accepted·rejected 또는 되돌리기용 pending·auto 중 하나입니다")
    a = db.one("SELECT * FROM annotation WHERE ann_id=?", (ann_id,))
    if not a:
        raise KeyError(ann_id)
    meas = None
    undo = status in ("pending", "auto")
    with db.tx() as t:
        t.execute("UPDATE annotation SET status=?, reviewed_at=CASE WHEN ? THEN NULL ELSE datetime('now') END "
                  "WHERE ann_id=?", (status, int(undo), ann_id))
        db.log_change(t, "annotation", ann_id, {"status": a["status"]}, {"status": status})
        removed = _remove_extracted(t, ann_id)  # 되돌리기·재결정: 승인을 두 번 눌러도 한 건만 남는다
        if status == "accepted":
            meas = promote_measurement(t, a)
    out = {"ok": True, "measurement_id": meas, "removed_measurements": removed}
    if learn and status == "rejected" and a["method"] == "dict":
        out["negative_example"] = learn_negative(ann_id=ann_id)
    if learn and undo and a["method"] == "dict":  # 거절을 되돌리면 그 거절로 배운 부정 사례도 끈다
        out["negatives_disabled"] = _disable_negatives_for(ann_id)
    return out


def parse_value(text: str, context: str = "") -> dict:
    """선택한 글('54.2 g/100 g')에서 값·단위·기준을 읽는다. 못 읽으면 빈 값."""
    t = (text or "").strip()
    m = _NUM.search(t)
    out: dict = {"value": None, "unit": None, "basis": None}
    if m:
        out["value"] = m.group(0).replace(",", "")
        rest = t[m.end():].strip()
        unit = re.split(r"[;\n]|\s(?:이고|이며|였다|이다|으로|로)\b", rest)[0].strip(" ,.)(")
        out["unit"] = unit[:20] or None
    hay = f"{context} {t}"
    for key, basis in _BASIS:
        if key.lower() in hay.lower():
            out["basis"] = basis
            break
    return out


def _target_before(text: str, start: int) -> str | None:
    """수치 앞에서 가장 가까운 성분·물성 표기 → 표준명."""
    ms = [m for m in thesaurus.find_mentions(text[:start]) if m["scheme"] in ("성분", "물성")]
    return ms[-1]["pref_label"] if ms else None


def suggest(chunk_id: str, start: int, end: int) -> dict:
    """선택 영역에 대한 제안: 표기, 값·단위·기준·항목(수치면), 맞는 개념 후보."""
    c = db.one("SELECT text FROM chunk WHERE chunk_id=?", (chunk_id,))
    if not c:
        raise ManualError("청크를 찾지 못했습니다. 작업대를 새로고침하세요.")
    text = c["text"]
    start, end = max(0, int(start)), min(len(text), int(end))
    surf = text[start:end]
    if not surf.strip():
        raise ManualError("라벨을 붙일 글을 선택하세요.")
    ctx = text[max(0, start - 40):min(len(text), end + 40)]
    val = parse_value(surf, ctx)
    is_num = val["value"] is not None and len(_NUM.sub("", surf).strip()) <= 20
    hits = thesaurus.lookup(surf.strip())[:8]
    lt = None
    if is_num:
        lt = "VALUE"
    elif hits and hits[0]["exact"]:
        from .ingest.pipeline import _label_type  # 같은 체계→라벨 종류 대응
        lt = _label_type(hits[0]["scheme"])
    return {"surface": surf, "start": start, "end": end, "label_type": lt, "concepts": hits,
            "value": val if is_num else None, "target": _target_before(text, start) if is_num else None}


def _ctx(text: str, s: int | None, e: int | None) -> str:
    if s is None or e is None:
        return ""
    return text[max(0, s - CONTEXT):min(len(text), e + CONTEXT)]


def _source_conf(t, chunk_id: str) -> tuple[str | None, str]:
    r = t.execute("SELECT c.doc_id, s.confidentiality FROM chunk c JOIN document d ON d.doc_id=c.doc_id "
                  "JOIN source s ON s.source_id=d.source_id WHERE c.chunk_id=?", (chunk_id,)).fetchone()
    return (r[0], r[1]) if r else (None, "내부")


def _add_example(t, a: dict, text: str, kind: str = "positive", note: str | None = None, extra: dict | None = None) -> str:
    doc_id, conf = _source_conf(t, a["chunk_id"])
    v = json.loads(a["normalized_value"]) if a.get("normalized_value") else {}
    v = {k: v.get(k) for k in ("value", "unit", "target", "basis") if v.get(k) not in (None, "")}
    bp = _doc_byproduct(t, doc_id) if doc_id else None
    if bp:
        v["byproduct_id"] = bp
    v.update(extra or {})
    ex = db.new_id()
    t.execute("INSERT INTO label_example(ex_id, ann_id, chunk_id, label_type, surface, context, concept_id, value_json, "
              "kind, confidentiality, enabled, note) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
              (ex, a["ann_id"], a["chunk_id"], a["label_type"], a["surface_text"],
               _ctx(text, a.get("span_start"), a.get("span_end")), a.get("concept_id"),
               json.dumps(v, ensure_ascii=False), kind, conf or "내부", note))
    db.log_change(t, "label_example", ex, None, {"kind": kind, "surface": a["surface_text"], "ann_id": a["ann_id"]})
    return ex


def _norm_value(label_type: str, value, unit, target, basis) -> str | None:
    if value in (None, ""):
        return None
    try:
        float(str(value).replace(",", ""))
    except ValueError as e:
        raise ManualError("값은 숫자여야 합니다(예: 54.2). 'ND'·'<0.01' 같은 표시는 표기에 두고 값은 비우세요.") from e
    return json.dumps({"value": str(value).replace(",", ""), "unit": unit or None, "target": target or None,
                       "basis": basis or None}, ensure_ascii=False)


def _unit_id(unit: str | None) -> str | None:
    if not unit:
        return None
    m = [h for h in thesaurus.lookup(unit) if h["exact"] and h["scheme"] == "단위"]
    return m[0]["concept_id"] if m else None


def _concept_ok(concept_id: str | None) -> None:
    if concept_id and not db.one("SELECT 1 AS x FROM concept WHERE concept_id=?", (concept_id,)):
        raise ManualError("고른 개념이 없습니다. 개념을 다시 찾아 고르세요.")


def _synonym_offer(concept_id: str | None, surface: str) -> dict | None:
    if not concept_id or not (surface or "").strip():
        return None
    labels = [r["label"].lower() for r in db.rows("SELECT label FROM concept_label WHERE concept_id=?", (concept_id,))]
    s = re.sub(r"\s+", " ", surface.strip())
    if s.lower() in labels or _NUM.fullmatch(s):
        return None
    c = db.one("SELECT pref_label_ko FROM concept WHERE concept_id=?", (concept_id,))
    pref = c["pref_label_ko"] if c else ""
    return {"concept_id": concept_id, "pref_label": pref, "surface": s,
            "message": f"'{s}'은(는) 아직 '{pref}'의 동의어가 아닙니다. 동의어로 배우면 사전 라벨·검색이 이 표기도 찾습니다."}


def create_manual(chunk_id: str, label_type: str, start: int | None = None, end: int | None = None,
                  surface: str | None = None, occurrence: int = 0, concept_id: str | None = None,
                  value=None, unit: str | None = None, target: str | None = None, basis: str | None = None) -> dict:
    """사람 라벨(method='human', status='accepted'). 위치(start·end) 또는 표기(surface + 몇 번째, 0부터) 중 하나.
    수치면 측정값으로 바로 올리고(라벨 검토의 승인과 같은 방식), 라벨 사례(positive)로 남긴다."""
    if label_type not in tools.LABEL_TYPES:
        raise ManualError(f"라벨 종류는 {', '.join(sorted(tools.LABEL_TYPES))} 중 하나입니다.")
    c = db.one("SELECT text FROM chunk WHERE chunk_id=?", (chunk_id,))
    if not c:
        raise ManualError("청크를 찾지 못했습니다. 작업대를 새로고침하세요.")
    text = c["text"]
    if start is not None and end is not None:
        start, end = int(start), int(end)
        if not (0 <= start < end <= len(text)):
            raise ManualError("선택 위치가 청크 범위를 벗어났습니다. 다시 선택하세요.")
        if surface and text[start:end] != surface:
            raise ManualError("선택한 글이 청크 본문과 다릅니다(그 사이 청크가 바뀌었을 수 있음). 새로고침 뒤 다시 선택하세요.")
        surface = text[start:end]
    elif surface:
        k = -1
        for _ in range(max(0, int(occurrence or 0)) + 1):
            k = text.find(surface, k + 1)
            if k < 0:
                break
        if k < 0:
            raise ManualError(f"'{surface[:30]}'을(를) 이 청크 본문에서 찾지 못했습니다. 본문 글자를 그대로 넣으세요.")
        start, end = k, k + len(surface)
    else:
        raise ManualError("라벨을 붙일 글을 선택하거나 표기를 넣으세요.")
    if not surface.strip():
        raise ManualError("빈칸에는 라벨을 붙일 수 없습니다.")
    _concept_ok(concept_id)
    if label_type == "VALUE" and value in (None, ""):
        value = parse_value(surface)["value"]
    norm = _norm_value(label_type, value, unit, target, basis)
    ann_id = db.new_id()
    with db.tx() as t:
        t.execute("INSERT INTO annotation(ann_id, chunk_id, span_start, span_end, surface_text, label_type, concept_id, "
                  "normalized_value, unit_concept_id, confidence, method, status, engine, reviewed_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?, 1.0, 'human', 'accepted', 'manual', datetime('now'))",
                  (ann_id, chunk_id, start, end, surface, label_type, concept_id, norm, _unit_id(unit)))
        a = dict(t.execute("SELECT * FROM annotation WHERE ann_id=?", (ann_id,)).fetchone())
        db.log_change(t, "annotation", ann_id, None, {"method": "human", "surface": surface, "label_type": label_type})
        meas = promote_measurement(t, a)
        ex = _add_example(t, a, text, note="사람 라벨")
    return {"ok": True, "ann_id": ann_id, "measurement_id": meas, "example_id": ex,
            "offer_synonym": _synonym_offer(concept_id, surface)}


def update_label(ann_id: str, label_type: str | None = None, concept_id: str | None = None, clear_concept: bool = False,
                 value=None, unit: str | None = None, target: str | None = None, basis: str | None = None,
                 start: int | None = None, end: int | None = None) -> dict:
    """라벨 고치기. 사전·AI 라벨을 고치면 '고친 라벨'로 승인되고 사례로 남는다(사전 라벨의 개념을 바꾸면 부정 사례도)."""
    a = db.one("SELECT * FROM annotation WHERE ann_id=?", (ann_id,))
    if not a:
        raise KeyError(ann_id)
    if label_type and label_type not in tools.LABEL_TYPES:
        raise ManualError(f"라벨 종류는 {', '.join(sorted(tools.LABEL_TYPES))} 중 하나입니다.")
    _concept_ok(concept_id)
    text = db.one("SELECT text FROM chunk WHERE chunk_id=?", (a["chunk_id"],))["text"]
    new = dict(a)
    if label_type:
        new["label_type"] = label_type
    if clear_concept:
        new["concept_id"] = None
    elif concept_id:
        new["concept_id"] = concept_id
    if start is not None and end is not None:
        start, end = int(start), int(end)
        if not (0 <= start < end <= len(text)):
            raise ManualError("새 위치가 청크 범위를 벗어났습니다. 다시 선택하세요.")
        new.update(span_start=start, span_end=end, surface_text=text[start:end])
    old_v = json.loads(a["normalized_value"]) if a["normalized_value"] else {}
    if any(x is not None for x in (value, unit, target, basis)):
        merged = {"value": value if value is not None else old_v.get("value"),
                  "unit": unit if unit is not None else old_v.get("unit"),
                  "target": target if target is not None else old_v.get("target"),
                  "basis": basis if basis is not None else old_v.get("basis")}
        new["normalized_value"] = _norm_value(new["label_type"], merged["value"], merged["unit"], merged["target"],
                                              merged["basis"])
        new["unit_concept_id"] = _unit_id(merged["unit"])
    corrected = a["method"] != "human"
    out: dict = {"ok": True, "ann_id": ann_id}
    with db.tx() as t:
        t.execute("UPDATE annotation SET label_type=?, concept_id=?, normalized_value=?, unit_concept_id=?, span_start=?, "
                  "span_end=?, surface_text=?, status='accepted', reviewed_at=datetime('now') WHERE ann_id=?",
                  (new["label_type"], new["concept_id"], new["normalized_value"], new["unit_concept_id"],
                   new["span_start"], new["span_end"], new["surface_text"], ann_id))
        keys = ("label_type", "concept_id", "normalized_value", "span_start", "span_end", "status")
        db.log_change(t, "annotation", ann_id, {k: a[k] for k in keys}, {**{k: new[k] for k in keys}, "status": "accepted"})
        _remove_extracted(t, ann_id)
        new["status"] = "accepted"
        out["measurement_id"] = promote_measurement(t, new)
        out["example_id"] = _add_example(t, new, text, note="고친 라벨" if corrected else "사람 라벨 수정")
    if a["method"] == "dict" and a["concept_id"] and new["concept_id"] != a["concept_id"]:
        out["negative_example"] = learn_negative(chunk_id=a["chunk_id"], surface=a["surface_text"],
                                                 concept_id=a["concept_id"], start=a["span_start"], end=a["span_end"],
                                                 label_type=a["label_type"], ann_id_ref=ann_id)
    out["offer_synonym"] = _synonym_offer(new["concept_id"], new["surface_text"])
    return out


def delete_label(ann_id: str, learn_negative_: bool = False) -> dict:
    a = db.one("SELECT * FROM annotation WHERE ann_id=?", (ann_id,))
    if not a:
        raise KeyError(ann_id)
    neg = learn_negative(ann_id=ann_id) if learn_negative_ and a["method"] == "dict" else None
    with db.tx() as t:
        removed = _remove_extracted(t, ann_id)
        t.execute("DELETE FROM annotation WHERE ann_id=?", (ann_id,))
        db.log_change(t, "annotation", ann_id, {k: a[k] for k in ("chunk_id", "surface_text", "label_type", "method",
                                                                  "status", "concept_id")}, None)
    return {"ok": True, "removed_measurements": removed, "negative_example": neg}


# ---------------------------------------------------------------- 배우기: 동의어·부정 사례

def learn_synonym(concept_id: str, surface: str, ann_id: str | None = None) -> dict:
    """표기를 개념의 동의어(alt)로 배운다 — 사용자가 확인한 뒤에만 부른다. 사전 라벨·검색에 바로 쓰인다."""
    if not concept_id:
        raise ManualError("동의어를 붙일 개념을 고르세요.")
    _concept_ok(concept_id)
    try:
        lid = thesaurus.add_alt_label(concept_id, surface)
    except ValueError as e:
        raise ManualError(str(e)) from e
    if ann_id:
        a = db.one("SELECT concept_id FROM annotation WHERE ann_id=?", (ann_id,))
        if a and not a["concept_id"]:
            with db.tx() as t:
                t.execute("UPDATE annotation SET concept_id=? WHERE ann_id=?", (concept_id, ann_id))
    c = db.one("SELECT pref_label_ko FROM concept WHERE concept_id=?", (concept_id,))
    return {"ok": True, "label_id": lid, "already": lid is None, "concept": c["pref_label_ko"] if c else None,
            "surface": (surface or "").strip()}


def learn_negative(ann_id: str | None = None, chunk_id: str | None = None, surface: str | None = None,
                   concept_id: str | None = None, start: int | None = None, end: int | None = None,
                   label_type: str | None = None, scope: str = "context", ann_id_ref: str | None = None) -> str:
    """'이 표기에 이 개념을 붙이지 말 것'을 배운다(label_example kind='negative'). 사전 라벨링(thesaurus.find_mentions)이 따른다.
    scope='context'(기본): 같은 앞·뒤 낱말일 때만 / 'everywhere': 어디서나."""
    if scope not in ("context", "everywhere"):
        raise ManualError("부정 사례 범위는 context(같은 문맥) 또는 everywhere(어디서나)입니다.")
    if ann_id:
        a = db.one("SELECT * FROM annotation WHERE ann_id=?", (ann_id,))
        if not a:
            raise KeyError(ann_id)
        chunk_id, surface, concept_id = a["chunk_id"], a["surface_text"], a["concept_id"]
        start, end, label_type = a["span_start"], a["span_end"], a["label_type"]
    if not (chunk_id and surface):
        raise ManualError("부정 사례로 배울 라벨(또는 청크와 표기)이 필요합니다.")
    text = (db.one("SELECT text FROM chunk WHERE chunk_id=?", (chunk_id,)) or {}).get("text") or ""
    if start is None or end is None or text[start:end] != surface:
        k = text.find(surface)
        start, end = (k, k + len(surface)) if k >= 0 else (None, None)
    left, right = thesaurus.neighbors(text, start, end) if start is not None else ("", "")
    fake = {"ann_id": ann_id or ann_id_ref, "chunk_id": chunk_id, "label_type": label_type or "OTHER",
            "surface_text": surface, "concept_id": concept_id, "normalized_value": None,
            "span_start": start, "span_end": end}
    with db.tx() as t:
        ex = _add_example(t, fake, text, kind="negative", note="거절한 사전 라벨",
                          extra={"scope": scope, "left": left if scope == "context" else "",
                                 "right": right if scope == "context" else ""})
    thesaurus.invalidate()
    return ex


def set_negative_scope(ex_id: str, scope: str) -> dict:
    """부정 사례 범위 바꾸기: context(같은 문맥) ↔ everywhere(어디서나)."""
    if scope not in ("context", "everywhere"):
        raise ManualError("부정 사례 범위는 context(같은 문맥) 또는 everywhere(어디서나)입니다.")
    r = db.one("SELECT value_json FROM label_example WHERE ex_id=? AND kind='negative'", (ex_id,))
    if not r:
        raise KeyError(ex_id)
    v = json.loads(r["value_json"] or "{}") or {}
    v["scope"] = scope
    with db.tx() as t:
        t.execute("UPDATE label_example SET value_json=? WHERE ex_id=?", (json.dumps(v, ensure_ascii=False), ex_id))
    thesaurus.invalidate()
    return {"ok": True}


def _disable_negatives_for(ann_id: str) -> int:
    with db.tx() as t:
        n = t.execute("UPDATE label_example SET enabled=0 WHERE ann_id=? AND kind='negative' AND enabled=1",
                      (ann_id,)).rowcount
    thesaurus.invalidate()
    return n


def add_concept(label: str, scheme: str, alt_labels: list[str] | None = None) -> dict:
    """작업대에서 새 개념 제안 → 사용자가 확인했으므로 바로 활성(내 확장, mine.ttl에 남김)."""
    r = tools.propose_concept((label or "").strip(), scheme, alt_labels or [])
    if r.get("error"):
        raise ManualError(r["error"])
    if r.get("exists"):
        return {"ok": True, "concept_id": r["exists"]["concept_id"], "exists": True,
                "pref_label": r["exists"]["pref_label"]}
    cid = r["concept_id"]
    with db.tx() as t:
        t.execute("UPDATE concept SET status='active' WHERE concept_id=?", (cid,))
        db.log_change(t, "concept", cid, {"status": "proposed"}, {"status": "active", "via": "workbench"})
    thesaurus.invalidate()
    thesaurus._sync_mine_ttl()   # mine.ttl을 DB에서 다시 만든다(덧붙이지 않음)
    return {"ok": True, "concept_id": cid, "pref_label": label, "exists": False}


# ---------------------------------------------------------------- 배운 것 목록·끄기

def _learned_label_ids() -> dict[str, str]:
    out = {}
    for r in db.rows("SELECT row_id, after_json, at FROM change_log WHERE table_name='concept_label' "
                     "AND before_json IS NULL ORDER BY log_id DESC"):
        try:
            a = json.loads(r["after_json"] or "{}")
        except ValueError:
            continue
        if a.get("learned") and r["row_id"] not in out:
            out[r["row_id"]] = r["at"]
    return out


def learned() -> dict:
    syn = []
    for lid, at in _learned_label_ids().items():
        lab = db.one("SELECT l.label_id, l.label, c.concept_id, c.pref_label_ko, s.name AS scheme FROM concept_label l "
                     "JOIN concept c ON c.concept_id=l.concept_id LEFT JOIN concept_scheme s ON s.scheme_id=c.scheme_id "
                     "WHERE l.label_id=?", (lid,))
        if lab:
            syn.append({**lab, "at": at})
    ex = db.rows("SELECT e.ex_id, e.kind, e.label_type, e.surface, e.context, e.value_json, e.confidentiality, e.enabled, "
                 "e.note, e.created_at, e.chunk_id, k.pref_label_ko AS concept, c.doc_id, d.file_name FROM label_example e "
                 "LEFT JOIN concept k ON k.concept_id=e.concept_id LEFT JOIN chunk c ON c.chunk_id=e.chunk_id "
                 "LEFT JOIN document d ON d.doc_id=c.doc_id ORDER BY e.created_at DESC, e.rowid DESC LIMIT 500")
    for e in ex:
        e["value"] = json.loads(e.pop("value_json") or "{}") or {}
        e["enabled"] = bool(e["enabled"])
    from . import chunk_rules
    return {"synonyms": syn, "negatives": [e for e in ex if e["kind"] == "negative"],
            "examples": [e for e in ex if e["kind"] == "positive"], "rules": chunk_rules.list_rules()}


def set_example(ex_id: str, enabled: bool) -> dict:
    r = db.one("SELECT enabled FROM label_example WHERE ex_id=?", (ex_id,))
    if not r:
        raise KeyError(ex_id)
    with db.tx() as t:
        t.execute("UPDATE label_example SET enabled=? WHERE ex_id=?", (int(bool(enabled)), ex_id))
        db.log_change(t, "label_example", ex_id, {"enabled": r["enabled"]}, {"enabled": int(bool(enabled))})
    thesaurus.invalidate()
    return {"ok": True}


def delete_example(ex_id: str) -> dict:
    r = db.one("SELECT kind, surface FROM label_example WHERE ex_id=?", (ex_id,))
    if not r:
        raise KeyError(ex_id)
    with db.tx() as t:
        t.execute("DELETE FROM label_example WHERE ex_id=?", (ex_id,))
        db.log_change(t, "label_example", ex_id, dict(r), None)
    thesaurus.invalidate()
    return {"ok": True}


def remove_synonym(label_id: str) -> dict:
    """배운 동의어를 지운다(시드·직접 만든 표준명은 여기서 지우지 않는다)."""
    r = db.one("SELECT * FROM concept_label WHERE label_id=?", (label_id,))
    if not r:
        raise KeyError(label_id)
    if label_id not in _learned_label_ids() or r["label_type"] == "pref":
        raise ManualError("작업대에서 배운 동의어만 여기서 지울 수 있습니다. 다른 표기는 개념 화면에서 관리하세요.")
    with db.tx() as t:
        t.execute("DELETE FROM concept_label WHERE label_id=?", (label_id,))
        db.log_change(t, "concept_label", label_id, {"label": r["label"], "concept_id": r["concept_id"]}, None)
    thesaurus.invalidate()
    thesaurus._sync_mine_ttl()   # 지운 동의어가 mine.ttl에서도 빠진다
    return {"ok": True}


# ---------------------------------------------------------------- 자동 라벨(사전)·AI 사례

def dict_relabel(doc_id: str, chunk_ids: list[str] | None = None) -> dict:
    """사전 라벨 다시: 아직 사람이 손대지 않은 사전 라벨(auto·pending)을 지우고 지금 시소러스(배운 동의어·부정 사례 포함)로
    다시 붙인다. 승인·거절한 라벨과 사람·AI 라벨은 그대로 두고, 그 자리와 겹치는 표기는 건너뛴다."""
    from .ingest.pipeline import DICT_CONF, _label_type
    rows = db.rows("SELECT chunk_id, text FROM chunk WHERE doc_id=? ORDER BY ord", (doc_id,))
    if chunk_ids:
        want = set(chunk_ids)
        rows = [r for r in rows if r["chunk_id"] in want]
    if not rows:
        raise ManualError("다시 라벨할 청크가 없습니다. 자료함에서 '다시 처리'를 해 보세요.")
    removed = added = 0
    with db.tx() as t:
        for r in rows:
            removed += t.execute("DELETE FROM annotation WHERE chunk_id=? AND method='dict' AND status IN ('auto','pending')",
                                 (r["chunk_id"],)).rowcount
            kept = [(a[0], a[1]) for a in t.execute("SELECT span_start, span_end FROM annotation WHERE chunk_id=? "
                                                    "AND span_start IS NOT NULL", (r["chunk_id"],)).fetchall()]
            for m in thesaurus.find_mentions(r["text"]):
                if any(m["start"] < e and s < m["end"] for s, e in kept):
                    continue
                t.execute("INSERT INTO annotation(ann_id, chunk_id, span_start, span_end, surface_text, label_type, "
                          "concept_id, confidence, method, status) VALUES (?,?,?,?,?,?,?,?, 'dict', 'auto')",
                          (db.new_id(), r["chunk_id"], m["start"], m["end"], m["surface"], _label_type(m["scheme"]),
                           m["concept_id"], DICT_CONF))
                added += 1
        db.log_change(t, "document", doc_id, {"dict_removed": removed}, {"dict_added": added, "via": "workbench"})
    return {"ok": True, "removed": removed, "added": added, "chunks": len(rows)}


def examples_for(chunk_ids: list[str], engine: str = "claude", limit: int = EX_LIMIT) -> dict:
    """이 청크들과 관련 높은 사례(같은 개념 > 같은 부산물 > 같은 라벨 종류). Codex는 기밀 사례를 늘 뺀다."""
    if not chunk_ids:
        return {"examples": [], "excluded_confidential": 0}
    ph = ",".join("?" * len(chunk_ids))
    anns = db.rows(f"SELECT label_type, concept_id FROM annotation WHERE chunk_id IN ({ph}) AND status!='rejected'",
                   chunk_ids)
    docs = {r["doc_id"] for r in db.rows(f"SELECT DISTINCT doc_id FROM chunk WHERE chunk_id IN ({ph})", chunk_ids)}
    conn = db.connect()
    try:
        bps = {b for b in (_doc_byproduct(conn, d) for d in docs) if b}
    finally:
        conn.close()
    rule = "block" if "codex" in (engine or "") else None
    return tools.label_examples([a["label_type"] for a in anns], [a["concept_id"] for a in anns if a["concept_id"]],
                                list(bps), limit=limit, rule=rule)


def examples_section(chunk_ids: list[str], engine: str = "claude", limit: int = EX_LIMIT) -> str:
    """AI 라벨러 프롬프트 끝에 붙는 '참고 사례' 절(Markdown). 사례가 없으면 빈 문자열."""
    exs = examples_for(chunk_ids, engine, limit)["examples"]
    if not exs:
        return ""
    lines = ["## 참고 사례 (이 PC의 사람이 만들거나 고친 라벨)",
             "형식과 판단 기준을 보여 주는 예입니다. 여기의 표기·수치를 지금 청크에 옮겨 적지 마세요. "
             "surface는 언제나 지금 청크 본문 그대로 씁니다."]
    for i, e in enumerate(exs, 1):
        ctx = re.sub(r"\s+", " ", e.get("context") or "").strip()
        tail = f" — 문맥: …{ctx[:120]}…" if ctx else ""
        if e["kind"] == "negative":
            lines.append(f"{i}. 붙이지 말 것: \"{e['surface']}\" → {e['concept'] or e['label_type']} (사람이 거절함){tail}")
            continue
        v = e.get("value") or {}
        val = ", ".join(f"{k} {v[k]}" for k in ("value", "unit", "target", "basis") if v.get(k))
        lines.append(f"{i}. \"{e['surface']}\" → {e['label_type']}"
                     f"{' · 개념 ' + e['concept'] if e.get('concept') else ''}{' · ' + val if val else ''}{tail}")
    return "\n".join(lines)
