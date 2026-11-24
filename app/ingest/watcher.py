"""받은편지함(inbox) 감시. 파일을 넣으면 자동으로 처리해 library/<프로젝트>/로 옮긴다.

inbox 바로 아래 파일 → 기본 프로젝트, inbox/<프로젝트명>/ 아래 파일 → 그 프로젝트.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

from .. import config
from . import parsers, pipeline

log = logging.getLogger("byorbit.watch")
_events: "queue.Queue[Path]" = queue.Queue()
recent: list[dict] = []  # 화면에 보여줄 최근 처리 결과


def _ok(p: Path) -> bool:
    return (p.is_file() and not p.name.startswith((".", "~$")) and
            p.suffix.lower() in parsers.SUPPORTED | {".hwp"})


def _project_for(p: Path) -> str | None:
    inbox = config.path("inbox")
    rel = p.relative_to(inbox)
    return rel.parts[0] if len(rel.parts) > 1 else None


def _stable(p: Path, wait=1.0, tries=20) -> bool:
    """복사가 끝날 때까지(크기가 변하지 않을 때까지) 기다린다."""
    last = -1
    for _ in range(tries):
        try:
            size = p.stat().st_size
        except FileNotFoundError:
            return False
        if size == last and size > 0:
            return True
        last = size
        time.sleep(wait)
    return False


def process(p: Path) -> dict:
    proj = _project_for(p)
    try:
        r = pipeline.ingest_file(p, project=proj, move=True)
    except pipeline.Duplicate as d:
        dup_dir = config.path("inbox", ".duplicates")
        dup_dir.mkdir(exist_ok=True)
        p.replace(dup_dir / p.name)
        r = {"file_name": p.name, "duplicate_of": d.doc_id}
    except parsers.UnsupportedFile as e:
        r = {"file_name": p.name, "error": str(e)}
    recent.insert(0, {**r, "at": time.strftime("%H:%M:%S")})
    del recent[50:]
    return r


def scan_once() -> list[dict]:
    inbox = config.path("inbox")
    out = []
    for p in sorted(inbox.rglob("*")):
        if any(part.startswith(".") for part in p.relative_to(inbox).parts):
            continue
        if _ok(p):
            out.append(process(p))
    return out


def start() -> threading.Thread | None:
    """watchdog 감시 + 처리 스레드. 시작 시 이미 들어있는 파일도 처리한다."""
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        log.warning("watchdog 미설치 — 받은편지함 자동 감시를 끕니다")
        return None

    class H(FileSystemEventHandler):
        def on_created(self, e):
            if not e.is_directory:
                _events.put(Path(e.src_path))

        def on_moved(self, e):
            if not e.is_directory:
                _events.put(Path(e.dest_path))

    def worker():
        try:
            scan_once()
        except Exception:
            log.exception("초기 스캔 실패")
        while True:
            p = _events.get()
            try:
                inbox = config.path("inbox")
                if any(part.startswith(".") for part in p.relative_to(inbox).parts):
                    continue
                if _stable(p) and _ok(p):
                    process(p)
            except Exception:
                log.exception("처리 실패: %s", p)

    obs = Observer()
    obs.schedule(H(), str(config.path("inbox")), recursive=True)
    obs.daemon = True
    obs.start()
    t = threading.Thread(target=worker, daemon=True, name="inbox-worker")
    t.start()
    return t
