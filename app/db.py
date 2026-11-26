"""SQLite 연결, 스키마 초기화, 표준 시드 적재."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import config
from .seed import seed_data as S

SCHEMA = Path(__file__).with_name("schema.sql")
_lock = threading.RLock()


def new_id() -> str:
    return uuid.uuid4().hex


def connect(db_file: Path | None = None) -> sqlite3.Connection:
    f = db_file or config.db_path()
    f.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(f), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def tx():
    """쓰기 트랜잭션. 앱 안의 동시 쓰기를 한 줄로 세운다."""
    with _lock:
        conn = connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def rows(sql: str, params=()) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def one(sql: str, params=()) -> dict | None:
    r = rows(sql, params)
    return r[0] if r else None


def table_names() -> list[str]:
    return [r["name"] for r in rows(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "AND name NOT LIKE 'chunk_fts%' ORDER BY name")]


# ---------------------------------------------------------------- 초기화

def init(seed: bool = True) -> dict:
    """데이터 폴더·DB·시드·기본 프로젝트를 만든다. 여러 번 실행해도 안전하다."""
    config.ensure_dirs()
    with tx() as c:
        c.executescript(SCHEMA.read_text(encoding="utf-8"))
    seeded = 0
    # 빈 DB면 시드 전체, 시드 버전이 올라갔으면 빠진 개념·동의어·관계만 더한다(기존 개념·사용자 확장은 그대로)
    if seed and (not one("SELECT 1 AS x FROM concept LIMIT 1") or
                 one("SELECT 1 AS x FROM concept_scheme WHERE version IS NOT ? LIMIT 1", (SEED_VERSION,)) or
                 len(S.SCHEME_CLASS) > (one("SELECT COUNT(*) AS n FROM concept_scheme")["n"])):
        seeded = load_seed()
        export_seed_ttl()
    mine = config.path("ontology", "mine.ttl")
    if not mine.exists():
        mine.write_text(TTL_PREFIX + "\n# 내 확장 개념 — 앱에서 제안·추가한 개념이 여기에 쌓인다\n", encoding="utf-8")
    settings = config.load_settings()
    if not config.settings_file().exists():
        config.save_settings({})
    ensure_project(settings["default_project"])
    _copy_agents()
    return {"data_home": str(config.data_home()), "tables": len(table_names()), "seeded_concepts": seeded}


# 기록(.shipped.json)이 생기기 전에 배포한 지침의 해시(줄바꿈 LF 기준) — 이 사본은 손대지 않은 것으로 본다
_SHIPPED_BEFORE = {"labeler.md": {"24188c13c9f7007e33847eec38f392e4cf2ce4a57f0f6519ffd2ca4ea0a8f3b5"}}


def _copy_agents() -> None:
    """에이전트 지침을 데이터 폴더로 복사한다. 앱의 지침이 새로 바뀌었을 때,
    사용자가 고치지 않은 사본(지난번에 복사한 그대로)이면 새 버전으로 바꾸고, 고친 사본은 그대로 둔다."""
    import hashlib
    src = config.APP_ROOT / "agents"
    dst = config.path("agents")
    ledger_f = dst / ".shipped.json"
    try:
        ledger = json.loads(ledger_f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        ledger = {}
    h = lambda b: hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()  # noqa: E731 — 줄바꿈 차이는 무시
    changed = False
    for f in src.glob("*.md"):
        new = f.read_bytes()
        target = dst / f.name
        if not target.exists():
            target.write_bytes(new)
        else:
            cur = target.read_bytes()
            old_ok = h(cur) == ledger.get(f.name) or h(cur) in _SHIPPED_BEFORE.get(f.name, ())
            if h(cur) != h(new) and old_ok:  # 사용자가 손대지 않은 옛 사본 → 갱신
                target.write_bytes(new)
            elif h(cur) != h(new):
                continue  # 사용자가 고친 사본은 건드리지 않는다
        ledger[f.name] = h(new)
        changed = True
    if changed:
        ledger_f.write_text(json.dumps(ledger, indent=1), encoding="utf-8")


def ensure_project(name: str, description: str = "") -> str:
    p = one("SELECT project_id FROM project WHERE name = ?", (name,))
    if p:
        return p["project_id"]
    pid = new_id()
    with tx() as c:
        c.execute("INSERT INTO project(project_id, name, description) VALUES (?,?,?)", (pid, name, description))
    return pid


# ---------------------------------------------------------------- 시드

def _slug(s: str) -> str:
    s = re.sub(r"[^0-9A-Za-z가-힣]+", "-", s).strip("-")
    return s or new_id()[:8]


SEED_VERSION = "seed-2"  # seed_data.py를 고치면 올린다 → 기존 DB에 증분 적재


def _add_missing_labels(c, cid, labels) -> None:
    have = {r[0].lower() for r in c.execute("SELECT label FROM concept_label WHERE concept_id=?", (cid,))}
    for lab, lang, t in labels:
        if lab.lower() not in have:
            have.add(lab.lower())
            c.execute("INSERT INTO concept_label(label_id, concept_id, label, lang, label_type) VALUES (?,?,?,?,?)",
                      (new_id(), cid, lab, lang, t))


def _get_or_make(c, cache, scheme_ids, class_ids, scheme, ko, en=None, alts=(), hidden=(), iri=None, origin="seed"):
    key = (scheme, ko)
    if key in cache:
        cid = cache[key]
        if cid in cache.get("_existing", ()):  # 이미 DB에 있던 개념: 새로 생긴 동의어만 더한다
            labels = ([(en, "en", "pref")] if en else []) + [(a, None, "alt") for a in alts] +                      [(h, None, "hidden") for h in hidden]
            _add_missing_labels(c, cid, labels)
        return cid
    cid = new_id()
    cls = S.SCHEME_CLASS[scheme][0]
    c.execute(
        "INSERT INTO concept(concept_id, scheme_id, class_id, iri, pref_label_ko, pref_label_en, origin, status) "
        "VALUES (?,?,?,?,?,?,?, 'active')",
        (cid, scheme_ids[scheme], class_ids[cls], iri or f"byo:{cls}/{_slug(en or ko)}", ko, en, origin))
    labels = [(ko, "ko", "pref")]
    if en:
        labels.append((en, "en", "pref"))
    labels += [(a, None, "alt") for a in alts] + [(h, None, "hidden") for h in hidden]
    seen = set()
    for lab, lang, t in labels:
        if lab.lower() in seen:
            continue
        seen.add(lab.lower())
        c.execute("INSERT INTO concept_label(label_id, concept_id, label, lang, label_type) VALUES (?,?,?,?,?)",
                  (new_id(), cid, lab, lang, t))
    cache[key] = cid
    cache["_created"] = cache.get("_created", 0) + 1
    return cid


def load_seed() -> int:
    with tx() as c:
        scheme_ids, class_ids = {}, {}
        for scheme, (cls, cls_ko, _) in S.SCHEME_CLASS.items():
            sid = new_id()
            c.execute("INSERT OR IGNORE INTO concept_scheme(scheme_id, name, version) VALUES (?,?,?)",
                      (sid, scheme, SEED_VERSION))
            c.execute("UPDATE concept_scheme SET version=? WHERE name=?", (SEED_VERSION, scheme))
            scheme_ids[scheme] = c.execute("SELECT scheme_id FROM concept_scheme WHERE name=?", (scheme,)).fetchone()[0]
            if cls not in class_ids:
                kid = new_id()
                c.execute("INSERT OR IGNORE INTO onto_class(class_id, iri, label_ko, label_en) VALUES (?,?,?,?)",
                          (kid, f"byo:{cls}", cls_ko, cls))
                class_ids[cls] = c.execute("SELECT class_id FROM onto_class WHERE iri=?", (f"byo:{cls}",)).fetchone()[0]
        # 이미 있는 개념은 (체계, 한글 표준명)으로 재사용한다 — 다시 실행해도 중복이 생기지 않는다
        cache: dict = {"_existing": set()}
        for r in c.execute("SELECT s.name, k.pref_label_ko, k.concept_id FROM concept k "
                           "JOIN concept_scheme s ON s.scheme_id=k.scheme_id"):
            cache[(r[0], r[1])] = r[2]
            cache["_existing"].add(r[2])
        mk = lambda *a, **k: _get_or_make(c, cache, scheme_ids, class_ids, *a, **k)  # noqa: E731
        rel = lambda a, b, t: c.execute(  # noqa: E731
            "INSERT OR IGNORE INTO concept_relation(concept_id, target_concept_id, rel_type) VALUES (?,?,?)", (a, b, t))

        for scheme, items in S.THESAURUS.items():
            for ko, en, alts in items:
                mk(scheme, ko, en, alts)

        for sec_id, sec_ko, sec_en, mids in S.TAXONOMY:
            sec = mk("분류", sec_ko, sec_en, iri=f"byo:Category/{sec_id}")
            for mid_id, mid_ko, leaves in mids:
                mid = mk("분류", mid_ko, None, iri=f"byo:Category/{mid_id}")
                rel(mid, sec, "broader")
                for leaf in leaves:
                    ko, en, alts, hidden, com, gen, cons = S.BYPRODUCTS[leaf]
                    bp = mk("부산물", ko, en, alts, hidden, iri=f"byo:Byproduct/{leaf}")
                    rel(bp, mid, "broader")
                    com_id = mk("원물", com)
                    gen_id = mk("공정", gen)
                    rel(bp, com_id, "derivedFrom")
                    rel(bp, gen_id, "generatedBy")
                    for k in cons:
                        rel(bp, mk("성분", k), "contains")
                    c.execute("INSERT OR IGNORE INTO byproduct(byproduct_id, concept_id, sector, commodity_concept_id, "
                              "generating_process_concept_id) VALUES (?,?,?,?,?)",
                              (new_id(), bp, sec_ko, com_id, gen_id))
        return cache.get("_created", 0)


TTL_PREFIX = """@prefix byo: <https://byorbit.kr/onto/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix mine: <https://byorbit.kr/onto/mine/> .
"""


def _ttl_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def concept_ttl(cid: str) -> str:
    c = one("SELECT * FROM concept WHERE concept_id=?", (cid,))
    labs = rows("SELECT label, lang, label_type FROM concept_label WHERE concept_id=?", (cid,))
    rels = rows("SELECT r.rel_type, t.iri FROM concept_relation r JOIN concept t ON t.concept_id=r.target_concept_id "
                "WHERE r.concept_id=?", (cid,))
    iri = c["iri"] if c["iri"].startswith(("byo:", "mine:")) else f"byo:{_slug(c['iri'])}"
    lines = [f"<{iri.replace('byo:', 'https://byorbit.kr/onto/').replace('mine:', 'https://byorbit.kr/onto/mine/')}> a skos:Concept"]
    for l in labs:
        pred = {"pref": "skos:prefLabel", "alt": "skos:altLabel", "hidden": "skos:hiddenLabel"}[l["label_type"]]
        lang = f"@{l['lang']}" if l["lang"] else ""
        lines.append(f"  {pred} {_ttl_str(l['label'])}{lang}")
    for r in rels:
        pred = "skos:broader" if r["rel_type"] == "broader" else f"byo:{r['rel_type']}"
        tgt = r["iri"].replace("byo:", "https://byorbit.kr/onto/").replace("mine:", "https://byorbit.kr/onto/mine/")
        lines.append(f"  {pred} <{tgt}>")
    return " ;\n".join(lines) + " .\n"


def export_seed_ttl() -> Path:
    out = config.path("ontology", "seed.ttl")
    parts = [TTL_PREFIX, "# 표준 시드 — 앱이 생성한 파일. 직접 고치지 말고 내 확장(mine.ttl)을 쓰세요.\n"]
    for r in rows("SELECT concept_id FROM concept WHERE origin='seed' ORDER BY pref_label_ko"):
        parts.append(concept_ttl(r["concept_id"]))
    out.write_text("\n".join(parts), encoding="utf-8")
    return out


def log_change(c, table: str, row_id: str, before, after) -> None:
    c.execute("INSERT INTO change_log(table_name, row_id, before_json, after_json) VALUES (?,?,?,?)",
              (table, row_id, json.dumps(before, ensure_ascii=False) if before is not None else None,
               json.dumps(after, ensure_ascii=False) if after is not None else None))
