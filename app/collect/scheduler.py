"""저장 검색 자동 실행 — 앱이 켜져 있는 동안 약 10분마다 확인해, 간격(interval_h)이 지난 자동 검색을 돌린다.

- 서버 시작 때 start(), 끌 때 stop(). 환경 변수 BYORBIT_COLLECT_SCHEDULER=0이면 시작하지 않는다(시험·점검용).
- 일시 정지 상태는 데이터 폴더 config/collect_scheduler.json {"paused": true}에 둔다(설정 파일과 분리).
- 같은 저장 검색은 동시에 두 번 돌지 않는다(store.begin_query가 막음). 수동 '지금 실행'과도 공유한다.
- 시험은 tick(now=가짜 시각)으로 직접 돌린다(스레드·시계 없이).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime

from .. import config
from . import store

log = logging.getLogger(__name__)
CHECK_EVERY_SEC = 600
FIRST_DELAY_SEC = 90          # 앱을 켜자마자 바로 밖에 나가지 않도록 잠시 기다린다

_thread: threading.Thread | None = None
_stop = threading.Event()
_state_lock = threading.Lock()
_last_tick: dict = {}


def state_file():
    return config.path("config", "collect_scheduler.json")


def load_state() -> dict:
    try:
        return {"paused": False, **json.loads(state_file().read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return {"paused": False}


def set_paused(paused: bool) -> dict:
    with _state_lock:
        st = load_state()
        st["paused"] = bool(paused)
        f = state_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    return status()


def status() -> dict:
    return {"paused": load_state()["paused"], "running": bool(_thread and _thread.is_alive()),
            "check_every_min": CHECK_EVERY_SEC // 60, "last_tick": dict(_last_tick)}


def tick(now: datetime | None = None, run=None) -> list[dict]:
    """지금 실행할 자동 검색을 모두 돌린다(순서대로). 반환: [{query_id, job_id|None, status, error?}]

    run: 시험용 대체 실행 함수(query_id, begun) → job dict. 기본은 store.run_query."""
    now = now or store.utcnow()
    _last_tick.update(at=store._ts(now), ran=0)
    if load_state()["paused"]:
        _last_tick["paused"] = True
        return []
    _last_tick["paused"] = False
    out = []
    for q in store.due_queries(now):
        if _stop.is_set() and _thread is not None:
            break
        try:
            begun = store.begin_query(q["query_id"], now)
        except store.Busy:
            out.append({"query_id": q["query_id"], "job_id": None, "status": "busy"})
            continue
        except KeyError:
            continue
        try:
            job = (run or (lambda qid, b: store.run_query(qid, now, begun=b)))(q["query_id"], begun)
            out.append({"query_id": q["query_id"], "job_id": begun["job_id"], "status": (job or {}).get("status", "done")})
        except Exception as e:  # noqa: BLE001 — 한 검색이 실패해도 다음 검색은 돈다
            log.warning("자동 수집 %s 실패: %s", q["name"], e)
            out.append({"query_id": q["query_id"], "job_id": begun["job_id"], "status": "error", "error": str(e)})
        finally:
            store.finish_query(q["query_id"])
    _last_tick["ran"] = len(out)
    return out


def _loop() -> None:
    if _stop.wait(FIRST_DELAY_SEC):
        return
    while not _stop.is_set():
        try:
            tick()
        except Exception as e:  # noqa: BLE001
            log.warning("자동 수집 확인 실패: %s", e)
        if _stop.wait(CHECK_EVERY_SEC):
            return


def start() -> bool:
    global _thread
    if os.environ.get("BYORBIT_COLLECT_SCHEDULER", "1") == "0":
        return False
    if _thread and _thread.is_alive():
        return True
    store.mark_interrupted()
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="collect-scheduler", daemon=True)
    _thread.start()
    return True


def stop(timeout: float = 5.0) -> None:
    global _thread
    _stop.set()
    if _thread:
        _thread.join(timeout)
    _thread = None
