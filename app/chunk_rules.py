"""청킹 규칙 배우기·적용 (모델 미세조정 없음 — 사람이 고친 것에서 규칙을 뽑아 비슷한 자료에 쓴다).

규칙 종류(chunk_rule.kind)
- heading     : pattern(정규식)에 맞는 줄을 섹션 제목으로 올린다.           (사람이 줄을 제목으로 올린 데서 배움)
- noise       : pattern에 맞는 줄을 지운다(머리글·바닥글·쪽 번호).          (사람이 잡음 줄·청크를 지운 데서 배움)
- merge_short : params.min_len보다 짧은 본문 조각을 앞 청크에 붙인다.         (짧은 조각을 합친 데서 배움)
- table       : params.keep_together — 같은 표의 청크를 하나로 묶는다(다시 파싱할 때 표를 나누지 않음).
- length      : params.target·overlap·min_len·max_len — 청커 크기를 덮어쓰고, 너무 긴 청크를 나눈다.

범위(scope_json.type, 좁은 것이 우선): doc(이 자료) > file_pattern(파일 이름 꼴) > title_prefix(같은 출처 제목 앞부분)
> format(같은 형식) > global(모든 자료).

pipeline(P 묶음)과의 약속
- apply(doc_id) -> report : 다시 파싱해 청크가 바뀐 뒤 부른다. 켜진 규칙 중 범위가 맞는 것만 적용.
- apply_on_ingest(doc_id) -> report|None : 새로 들어온 자료에 부를 수 있다(규칙이 없으면 아무것도 안 함, 오류는 삼킴).
- chunker_params(doc_id) -> dict : chunker.build(blocks, **params)에 넘길 크기·표 처리 값.
- prepare_blocks(doc_id, blocks) -> blocks : 청킹 전에 제목·잡음 규칙을 블록에 미리 적용(선택).
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from pathlib import PurePath

from . import chunk_edit as E, db
from .ingest import chunker

KINDS = {"heading": "제목 줄", "noise": "잡음 줄", "merge_short": "짧은 조각 합치기", "table": "표 묶기",
         "length": "청크 길이"}
SCOPES = ("doc", "file_pattern", "title_prefix", "format", "global")
_SPECIFIC = {s: i for i, s in enumerate(SCOPES)}
MAX_PATTERN = 300
MAX_STEPS = 400


class RuleError(E.WbError):
    pass


# ---------------------------------------------------------------- 자료 정보와 범위

def doc_info(doc_id: str) -> dict:
    d = db.one("SELECT d.doc_id, d.file_name, s.title, s.source_type, s.confidentiality FROM document d "
               "JOIN source s ON s.source_id=d.source_id WHERE d.doc_id=?", (doc_id,))
    if not d:
        raise E.NotFound("자료를 찾지 못했습니다. 자료함을 새로고침하세요.")
    d["ext"] = PurePath(d["file_name"] or "").suffix.lower()
    return d


def _title_prefix(title: str | None) -> str | None:
    words = (title or "").split()
    if not words:
        return None
    p = " ".join(words[:2])
    p = re.sub(r"[\s\d_\-.()호권판차]+$", "", p) if re.search(r"\d", p) else p  # '보고서_2026_01' → '보고서'
    return p if len(p) >= 2 else None


def _file_pattern(name: str) -> str:
    p = PurePath(name)
    stem = re.sub(r"\d+", "*", p.stem)
    if stem == p.stem:  # 숫자가 없으면 첫 구분자까지 + *
        m = re.match(r"^(.+?[_\-\s])", stem)
        stem = (m.group(1) if m else stem) + "*"
    stem = re.sub(r"\*+", "*", stem)
    return stem + p.suffix.lower()


def scope_options(doc_id: str) -> list[dict]:
    d = doc_info(doc_id)
    out = [{"type": "doc", "value": doc_id, "label": f"이 자료만 ({d['file_name']})"}]
    out.append({"type": "file_pattern", "value": _file_pattern(d["file_name"]),
                "label": f"파일 이름이 '{_file_pattern(d['file_name'])}' 꼴인 자료"})
    tp = _title_prefix(d["title"])
    if tp:
        out.append({"type": "title_prefix", "value": tp, "label": f"제목이 '{tp}'(으)로 시작하는 자료"})
    if d["ext"]:
        out.append({"type": "format", "value": d["ext"], "label": f"모든 {d['ext'].lstrip('.').upper()} 자료"})
    out.append({"type": "global", "value": None, "label": "모든 자료"})
    return out


def scope_label(scope: dict) -> str:
    t, v = scope.get("type", "global"), scope.get("value")
    if t == "doc":
        r = db.one("SELECT file_name FROM document WHERE doc_id=?", (v,))
        return f"이 자료만 ({r['file_name'] if r else '지워진 자료'})"
    return {"file_pattern": f"파일 이름 '{v}'", "title_prefix": f"제목 '{v}…'",
            "format": f"모든 {str(v or '').lstrip('.').upper()} 자료", "global": "모든 자료"}.get(t, t)


def _check_scope(scope: dict | None) -> dict:
    scope = dict(scope or {"type": "global"})
    t = scope.get("type") or "global"
    if t not in SCOPES:
        raise RuleError(f"범위는 {', '.join(SCOPES)} 중 하나입니다.")
    if t != "global" and not str(scope.get("value") or "").strip():
        raise RuleError("범위 값이 비었습니다. 이 자료·파일 이름 꼴·제목 앞부분·형식 중 하나를 고르세요.")
    scope["type"] = t
    if t == "format":
        v = str(scope["value"]).strip().lower()
        scope["value"] = v if v.startswith(".") else "." + v
    return scope


def scope_matches(scope: dict, info: dict) -> bool:
    t, v = scope.get("type", "global"), scope.get("value")
    if t == "global":
        return True
    if t == "doc":
        return v == info["doc_id"]
    if t == "format":
        return (v or "").lower() == info["ext"]
    if t == "file_pattern":
        return fnmatch.fnmatch((info["file_name"] or "").lower(), str(v or "").lower())
    if t == "title_prefix":
        return (info.get("title") or "").strip().lower().startswith(str(v or "").strip().lower())
    return False


# ---------------------------------------------------------------- 규칙 저장소

def _parse(r: dict) -> dict:
    r = dict(r)
    r["scope"] = json.loads(r.pop("scope_json") or "{}") or {"type": "global"}
    r["params"] = json.loads(r.pop("params_json") or "{}") or {}
    r["enabled"] = bool(r["enabled"])
    r["kind_label"] = KINDS.get(r["kind"], r["kind"])
    r["scope_label"] = scope_label(r["scope"])
    return r


def _validate(kind: str, pattern: str | None, params: dict | None) -> tuple[str | None, dict]:
    if kind not in KINDS:
        raise RuleError(f"규칙 종류는 {', '.join(KINDS)} 중 하나입니다.")
    params = dict(params or {})
    if kind in ("heading", "noise"):
        if not (pattern or "").strip():
            raise RuleError("제목·잡음 규칙에는 줄 모양(정규식)이 필요합니다.")
        if len(pattern) > MAX_PATTERN:
            raise RuleError(f"정규식이 너무 깁니다({MAX_PATTERN}자 이하).")
        try:
            re.compile(pattern)
        except re.error as e:
            raise RuleError(f"정규식이 올바르지 않습니다: {e}. 예: ^\\d+\\.\\s+\\S.*$") from e
    else:
        pattern = None
    for k in ("min_len", "max_len", "target", "overlap", "table_rows"):
        if k in params and params[k] not in (None, ""):
            try:
                params[k] = int(params[k])
            except (TypeError, ValueError) as e:
                raise RuleError(f"{k}는 정수(글자 수)여야 합니다.") from e
            if params[k] < 0:
                raise RuleError(f"{k}는 0 이상이어야 합니다.")
    if kind == "merge_short" and not params.get("min_len"):
        raise RuleError("짧은 조각 합치기에는 min_len(이보다 짧으면 합침)이 필요합니다.")
    if kind == "table":
        params.setdefault("keep_together", True)
    return pattern, params


def list_rules(doc_id: str | None = None) -> list[dict]:
    """모든 규칙(doc_id를 주면 그 자료에 맞는 것만) + 적용된 자료 목록."""
    rules = [_parse(r) for r in db.rows("SELECT * FROM chunk_rule ORDER BY created_at DESC, rowid DESC")]
    info = doc_info(doc_id) if doc_id else None
    out = []
    for r in rules:
        if info and not scope_matches(r["scope"], info):
            continue
        docs = {}
        for x in db.rows("SELECT after_json, at FROM change_log WHERE table_name='chunk_rule_apply' AND row_id=? "
                         "ORDER BY log_id DESC LIMIT 200", (r["rule_id"],)):
            a = json.loads(x["after_json"] or "{}")
            if a.get("doc_id") and a["doc_id"] not in docs:
                docs[a["doc_id"]] = {"doc_id": a["doc_id"], "changes": a.get("changes", 0), "at": x["at"]}
        names = {d["doc_id"]: d["file_name"] for d in db.rows(
            "SELECT doc_id, file_name FROM document WHERE doc_id IN (%s)" % ",".join("?" * len(docs)), list(docs))} if docs else {}
        r["docs"] = [{**d, "file_name": names.get(k, "(지워진 자료)")} for k, d in docs.items()]
        out.append(r)
    return out


def get_rule(rule_id: str) -> dict:
    r = db.one("SELECT * FROM chunk_rule WHERE rule_id=?", (rule_id,))
    if not r:
        raise E.NotFound("규칙을 찾지 못했습니다. 규칙 목록을 새로고침하세요.")
    return _parse(r)


def create_rule(kind: str, pattern: str | None = None, params: dict | None = None, scope: dict | None = None,
                origin: str = "manual", note: str | None = None, enabled: bool = True) -> dict:
    pattern, params = _validate(kind, pattern, params)
    scope = _check_scope(scope)
    if origin not in ("learned", "manual"):
        origin = "manual"
    rid = db.new_id()
    with db.tx() as t:
        t.execute("INSERT INTO chunk_rule(rule_id, kind, scope_json, pattern, params_json, origin, enabled, note) "
                  "VALUES (?,?,?,?,?,?,?,?)",
                  (rid, kind, json.dumps(scope, ensure_ascii=False), pattern, json.dumps(params, ensure_ascii=False),
                   origin, int(bool(enabled)), note))
        db.log_change(t, "chunk_rule", rid, None, {"kind": kind, "pattern": pattern, "params": params, "scope": scope,
                                                   "origin": origin})
    return get_rule(rid)


def update_rule(rule_id: str, **upd) -> dict:
    r = get_rule(rule_id)
    kind = r["kind"]
    pattern = upd.get("pattern", r["pattern"])
    params = upd.get("params") if upd.get("params") is not None else r["params"]
    pattern, params = _validate(kind, pattern, params)
    scope = _check_scope(upd["scope"]) if upd.get("scope") is not None else r["scope"]
    enabled = r["enabled"] if upd.get("enabled") is None else bool(upd["enabled"])
    note = upd.get("note", r["note"])
    with db.tx() as t:
        t.execute("UPDATE chunk_rule SET pattern=?, params_json=?, scope_json=?, enabled=?, note=? WHERE rule_id=?",
                  (pattern, json.dumps(params, ensure_ascii=False), json.dumps(scope, ensure_ascii=False),
                   int(enabled), note, rule_id))
        db.log_change(t, "chunk_rule", rule_id,
                      {"pattern": r["pattern"], "params": r["params"], "scope": r["scope"], "enabled": r["enabled"]},
                      {"pattern": pattern, "params": params, "scope": scope, "enabled": enabled})
    return get_rule(rule_id)


def delete_rule(rule_id: str) -> dict:
    r = get_rule(rule_id)
    with db.tx() as t:
        t.execute("DELETE FROM chunk_rule WHERE rule_id=?", (rule_id,))
        db.log_change(t, "chunk_rule", rule_id, {k: r[k] for k in ("kind", "pattern", "params", "scope", "origin")}, None)
    return {"ok": True}


def rules_for(doc_id: str, rule_ids: list[str] | None = None, include_disabled: bool = False) -> list[dict]:
    info = doc_info(doc_id)
    rules = [_parse(r) for r in db.rows("SELECT * FROM chunk_rule ORDER BY created_at, rowid")]
    if rule_ids is not None:
        rules = [r for r in rules if r["rule_id"] in set(rule_ids)]
        return [r for r in rules if include_disabled or r["enabled"]]
    return [r for r in rules if r["enabled"] and scope_matches(r["scope"], info)]


def _most_specific(rules: list[dict]) -> list[dict]:
    return sorted(rules, key=lambda r: _SPECIFIC.get(r["scope"].get("type"), 9))


def chunker_params(doc_id: str) -> dict:
    """이 자료에 맞는 청커 값(좁은 범위 규칙이 우선). chunker.build(blocks, **chunker_params(doc_id))."""
    out: dict = {}
    try:
        rules = _most_specific(rules_for(doc_id))
    except E.NotFound:
        return out
    for r in reversed(rules):  # 넓은 것부터 쓰고 좁은 것으로 덮는다
        p = r["params"]
        if r["kind"] == "length":
            for k in ("target", "overlap"):
                if p.get(k):
                    out[k] = int(p[k])
        if r["kind"] == "table":
            if p.get("keep_together"):
                out["keep_tables"] = True
            if p.get("table_rows"):
                out["table_rows"] = int(p["table_rows"])
    return out


def limits(doc_id: str) -> tuple[int, int]:
    """검사에 쓰는 (최소, 최대) 글자 수."""
    lo, hi = E.MIN_LEN, E.MAX_LEN
    try:
        rules = _most_specific(rules_for(doc_id))
    except E.NotFound:
        return lo, hi
    for r in reversed(rules):
        p = r["params"]
        if r["kind"] == "length":
            if p.get("min_len"):
                lo = int(p["min_len"])
            if p.get("max_len"):
                hi = int(p["max_len"])
            elif p.get("target"):
                hi = int(int(p["target"]) * 1.6)
        if r["kind"] == "merge_short" and p.get("min_len"):
            lo = int(p["min_len"])
    return lo, hi


# ---------------------------------------------------------------- 적용

def _match(rx: re.Pattern, line: str) -> bool:
    s = line.strip()
    return bool(s) and len(s) <= 200 and rx.fullmatch(s) is not None


def _apply_rule(op: E.Op, rule: dict, changes: list) -> int:
    c, doc_id, kind, p = op.c, op.doc_id, rule["kind"], rule["params"]
    n = 0

    def note(ch, action, before, after=None):
        changes.append({"rule_id": rule.get("rule_id"), "kind": kind, "ord": ch["ord"], "chunk_id": ch["chunk_id"],
                        "action": action, "before": before[:300], "after": (after or "")[:300]})

    if kind == "noise":
        rx = re.compile(rule["pattern"])
        for ch in E.doc_chunks(c, doc_id):
            hit = [ln.strip() for ln in E.body(ch).split("\n") if _match(rx, ln)]
            if hit:
                before = ch["text"]
                E.drop_lines(op, ch, lambda ln: _match(rx, ln))
                for h in hit:
                    note(ch, "잡음 줄 지움", h)
                n += len(hit)
    elif kind == "heading":
        rx = re.compile(rule["pattern"])
        skip: set = set()
        for _ in range(MAX_STEPS):
            found = None
            for ch in E.doc_chunks(c, doc_id):
                if ch["chunk_type"] != "text":
                    continue
                for ln in E.body(ch).split("\n"):
                    s = ln.strip()
                    if (_match(rx, s) and len(s) <= 120 and s != (ch.get("heading") or "")
                            and (ch["chunk_id"], s) not in skip):
                        found = (ch, s)
                        break
                if found:
                    break
            if not found:
                break
            ch, s = found
            try:
                E.promote_heading(op, ch, s)
            except E.WbError:
                skip.add((ch["chunk_id"], s))
                continue
            note(ch, "제목으로 올림", "", s)
            n += 1
    elif kind == "merge_short":
        lo = int(p.get("min_len") or E.MIN_LEN)
        for _ in range(MAX_STEPS):
            chunks = E.doc_chunks(c, doc_id)
            pair = None
            for i, ch in enumerate(chunks):
                if ch["chunk_type"] != "text" or len(E.body(ch).strip()) >= lo or len(chunks) < 2:
                    continue
                prev = chunks[i - 1] if i > 0 else None
                nxt = chunks[i + 1] if i + 1 < len(chunks) else None
                if prev and prev["chunk_type"] == "text" and prev["section_id"] == ch["section_id"]:
                    pair = (prev, ch)
                elif nxt and nxt["chunk_type"] == "text" and nxt["section_id"] == ch["section_id"]:
                    pair = (ch, nxt)
                if pair:
                    break
            if not pair:
                break
            a, b = pair
            short = b if len(E.body(b).strip()) < lo else a
            note(short, "짧은 조각 합침", E.body(short).strip())
            E.merge(op, a, b)
            n += 1
    elif kind == "table":
        if not p.get("keep_together", True):
            return 0
        for _ in range(MAX_STEPS):
            chunks = E.doc_chunks(c, doc_id)
            pair = next(((a, b) for a, b in zip(chunks, chunks[1:]) if a["table_id"] and a["table_id"] == b["table_id"]
                         and a["chunk_type"] == "table" and b["chunk_type"] == "table"), None)
            if not pair:
                break
            note(pair[1], "같은 표 청크 묶음", E.body(pair[1])[:80])
            E.merge(op, pair[0], pair[1], sep="\n", dedupe_table_header=True)
            n += 1
    elif kind == "length":
        hi = int(p.get("max_len") or (int(p["target"]) * 1.6 if p.get("target") else E.MAX_LEN))
        tgt = int(p.get("target") or max(200, hi // 1.6))
        for _ in range(MAX_STEPS):
            ch = next((x for x in E.doc_chunks(c, doc_id) if x["chunk_type"] == "text" and len(E.body(x)) > hi), None)
            if not ch:
                break
            pre = E.heading_prefix(ch)
            cut = len(pre) + chunker.cut_point(E.body(ch), tgt)
            note(ch, "긴 청크 나눔", f"{len(E.body(ch))}자")
            try:
                E.split(op, ch, cut)
            except E.WbError:
                break
            n += 1
    return n


_ORDER = {"noise": 0, "heading": 1, "merge_short": 2, "table": 3, "length": 4}


def _apply(c, doc_id: str, rules: list[dict], origin: str) -> dict:
    op = E.Op(c, doc_id, "rules", {"rule_ids": [r.get("rule_id") for r in rules], "origin": origin})
    changes: list = []
    hits = {}
    for r in sorted(rules, key=lambda r: _ORDER.get(r["kind"], 9)):
        hits[r.get("rule_id")] = _apply_rule(op, r, changes)
    log_id = op.log()
    return {"doc_id": doc_id, "log_id": log_id, "changes": changes, "total": sum(hits.values()),
            "rules": [{"rule_id": r.get("rule_id"), "kind": r["kind"], "kind_label": KINDS[r["kind"]],
                       "hits": hits.get(r.get("rule_id"), 0)} for r in rules], "report": op.report}


def apply(doc_id: str, rule_ids: list[str] | None = None, origin: str = "manual") -> dict:
    """켜진 규칙 중 이 자료 범위에 맞는 것(또는 rule_ids)을 적용한다. 되돌리기 한 번에 모두 되돌아간다."""
    rules = rules_for(doc_id, rule_ids)
    if not rules:
        return {"doc_id": doc_id, "log_id": None, "changes": [], "total": 0, "rules": [], "report": None}
    with db.tx() as c:
        rep = _apply(c, doc_id, rules, origin)
        for r in rep["rules"]:
            if r["hits"] and r["rule_id"]:
                c.execute("UPDATE chunk_rule SET hits=hits+? WHERE rule_id=?", (r["hits"], r["rule_id"]))
                db.log_change(c, "chunk_rule_apply", r["rule_id"], None,
                              {"doc_id": doc_id, "changes": r["hits"], "origin": origin})
    return rep


def preview(doc_id: str, rule_ids: list[str] | None = None, rules: list[dict] | None = None) -> dict:
    """적용하면 무엇이 바뀌는지(아무것도 저장하지 않음). rules에 저장 전 규칙(제안)을 넘길 수도 있다."""
    if rules is None:
        rules = rules_for(doc_id, rule_ids, include_disabled=rule_ids is not None)
    else:
        rules = [{**r, "pattern": _validate(r["kind"], r.get("pattern"), r.get("params"))[0],
                  "params": _validate(r["kind"], r.get("pattern"), r.get("params"))[1]} for r in rules]
    if not rules:
        return {"doc_id": doc_id, "changes": [], "total": 0, "rules": [], "before": 0, "after": 0}
    with db._lock:
        conn = db.connect()
        try:
            before = conn.execute("SELECT COUNT(*) FROM chunk WHERE doc_id=?", (doc_id,)).fetchone()[0]
            rep = _apply(conn, doc_id, rules, "preview")
            rep["before"] = before
            rep["after"] = conn.execute("SELECT COUNT(*) FROM chunk WHERE doc_id=?", (doc_id,)).fetchone()[0]
        finally:
            conn.rollback()
            conn.close()
    rep.pop("log_id", None)
    return rep


def apply_on_ingest(doc_id: str) -> dict | None:
    """새 자료·다시 파싱한 자료에 규칙을 조용히 적용한다(규칙이 없거나 실패하면 None)."""
    try:
        if not rules_for(doc_id):
            return None
        return apply(doc_id, origin="ingest")
    except Exception:  # noqa: BLE001 — 투입을 막지 않는다
        return None


def prepare_blocks(doc_id: str, blocks: list[dict]) -> list[dict]:
    """청킹 전에 잡음 줄을 지우고 제목 규칙에 맞는 줄을 제목 블록으로 뗀다(파서 블록 형식 그대로)."""
    try:
        rules = rules_for(doc_id)
    except E.NotFound:
        return blocks
    noise = [re.compile(r["pattern"]) for r in rules if r["kind"] == "noise"]
    heads = [re.compile(r["pattern"]) for r in rules if r["kind"] == "heading"]
    if not noise and not heads:
        return blocks
    out = []
    for b in blocks:
        if b.get("type") != "text":
            out.append(b)
            continue
        buf = []
        for ln in (b.get("text") or "").split("\n"):
            if any(_match(rx, ln) for rx in noise):
                continue
            if any(_match(rx, ln) for rx in heads):
                if buf:
                    out.append({**b, "text": "\n".join(buf)})
                    buf = []
                out.append({**b, "type": "heading", "text": ln.strip(), "level": 1})
                continue
            buf.append(ln)
        if "\n".join(buf).strip():
            out.append({**b, "text": "\n".join(buf)})
    return out


# ---------------------------------------------------------------- 고친 것에서 규칙 제안

def generalize_noise(line: str) -> str:
    """'- 3 -' → ^-\\s*\\d+\\s*-$ · 'J. Food Sci. 2023, 45(2)' → 숫자만 일반화."""
    parts = re.split(r"(\d+)", line.strip())
    out = []
    for i, p in enumerate(parts):
        if i % 2:
            out.append(r"\d+")
        else:
            out.append(r"\s*".join(re.escape(w) for w in re.split(r"\s+", p)) if p.strip() else (r"\s*" if p else ""))
    return "^" + "".join(out) + "$"


_NUMBERING = [
    # 숫자 번호: 문장(마침표로 끝남)·수치 줄(60 ℃ …)은 맞지 않게 — 번호 뒤 첫 글자는 숫자가 아니고, 뒤에 마침표가 없다
    (re.compile(r"^\d+(?:\.\d+)*\.\s+[^\d\s]"), r"^\d+(?:\.\d+)*\.\s+[^\d\s][^.]{0,60}$", "숫자 번호 제목(예: 3. 결과)"),
    (re.compile(r"^\d+(?:\.\d+)+\s+[^\d\s]"), r"^\d+(?:\.\d+)+\s+[^\d\s][^.]{0,60}$", "숫자 번호 제목(예: 3.1 결과)"),
    (re.compile(r"^[IVXⅠ-Ⅻ]+\.\s+\S"), r"^[IVXⅠ-Ⅻ]+\.\s+\S[^.]{0,60}$", "로마 숫자 번호 제목(예: Ⅱ. 재료)"),
    (re.compile(r"^제\s*\d+\s*[장절편]"), r"^제\s*\d+\s*[장절편].{0,80}$", "'제n장·절' 제목"),
    (re.compile(r"^[가-하]\.\s+\S"), r"^[가-하]\.\s+\S[^.]{0,60}$", "'가.' 번호 제목"),
    (re.compile(r"^\(\d+\)\s*\S"), r"^\(\d+\)\s*\S.{0,80}$", "'(1)' 번호 제목"),
    (re.compile(r"^[■□●○◆◇▶▷◎]\s*\S"), r"^[■□●○◆◇▶▷◎]\s*\S.{0,80}$", "기호로 시작하는 제목"),
    (re.compile(r"^\[[^\]]{1,40}\]$"), r"^\[[^\]]{1,40}\]$", "대괄호 제목"),
]


def generalize_heading(line: str) -> tuple[str, str]:
    s = line.strip()
    for test, pattern, label in _NUMBERING:
        if test.search(s):
            return pattern, label
    return "^" + re.escape(s) + "$", "같은 글자의 제목 줄"


def _pid(kind: str, pattern: str | None, params: dict) -> str:
    return hashlib.sha1(json.dumps([kind, pattern, params], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def _count_lines(doc_id: str, rx: re.Pattern, skip_headings: bool = True) -> tuple[int, set]:
    n, pages = 0, set()
    conn = db.connect()
    try:
        for ch in E.doc_chunks(conn, doc_id):
            for ln in E.body(ch).split("\n"):
                if _match(rx, ln) and not (skip_headings and ln.strip() == (ch.get("heading") or "")):
                    n += 1
                    pages.add(ch["page"])
    finally:
        conn.close()
    return n, pages


def propose(doc_id: str) -> list[dict]:
    """이 자료에서 사람이 고친 작업(되돌리지 않은 것)으로 규칙 후보를 만든다. 이미 있는 규칙은 뺀다."""
    existing = {(r["kind"], r["pattern"] or "", json.dumps(r["params"], sort_keys=True)) for r in list_rules()}
    existing_kp = {(k, p) for k, p, _ in existing}
    props: dict[str, dict] = {}

    def add(kind, pattern, params, note, evidence):
        if (kind, pattern or "") in existing_kp and kind in ("heading", "noise"):
            return
        if (kind, pattern or "", json.dumps(params, sort_keys=True)) in existing:
            return
        pid = _pid(kind, pattern, params)
        p = props.setdefault(pid, {"proposal_id": pid, "kind": kind, "kind_label": KINDS[kind], "pattern": pattern,
                                   "params": params, "note": note, "evidence": []})
        if evidence not in p["evidence"]:
            p["evidence"].append(evidence)

    merges_short, merges_table, splits = [], 0, []
    for o in E.ops(doc_id, limit=500):
        for l in o["learn"]:
            k = l.get("kind")
            if k == "noise" and l.get("line"):
                add("noise", generalize_noise(l["line"]), {}, "지운 잡음 줄과 같은 모양의 줄을 지웁니다.",
                    f"지운 줄: {l['line'][:60]}")
            elif k == "drop" and l.get("lines") == 1 and 0 < len(l.get("text") or "") <= 80:
                add("noise", generalize_noise(l["text"]), {}, "지운 한 줄짜리 청크와 같은 모양의 줄을 지웁니다.",
                    f"지운 청크: {l['text'][:60]}")
            elif k == "heading" and l.get("line"):
                pat, label = generalize_heading(l["line"])
                add("heading", pat, {}, f"{label}을 섹션 제목으로 올립니다.", f"제목으로 올린 줄: {l['line'][:60]}")
            elif k == "merge":
                if l.get("same_table"):
                    merges_table += 1
                elif l.get("a_type") == "text" and l.get("b_type") == "text":
                    short = min(l.get("a_len", 0), l.get("b_len", 0))
                    if short < 400:
                        merges_short.append(short)
            elif k == "split" and l.get("len_before"):
                splits.append(l)
    if merges_short:
        lo = int(min(400, (max(merges_short) // 20 + 2) * 20))
        add("merge_short", None, {"min_len": lo}, f"{lo}자보다 짧은 본문 조각을 앞 청크에 붙입니다.",
            f"짧은 조각을 {len(merges_short)}번 합침(가장 긴 조각 {max(merges_short)}자)")
    if merges_table:
        add("table", None, {"keep_together": True}, "같은 표의 청크를 하나로 묶고, 다시 파싱할 때 표를 나누지 않습니다.",
            f"같은 표 청크를 {merges_table}번 합침")
    if splits:
        parts = [x for s in splits for x in s.get("parts", []) if x]
        if parts:
            mx = int(max(parts) * 1.2 // 50 * 50) or 400
            tgt = max(200, int(sum(parts) / len(parts)) // 50 * 50)
            add("length", None, {"target": tgt, "max_len": max(mx, tgt + 100)},
                f"청크 목표 {tgt}자, {max(mx, tgt + 100)}자보다 길면 나눕니다(다시 파싱할 때 청커 크기도 이 값).",
                f"긴 청크를 {len(splits)}번 나눔")
    out = []
    for p in props.values():
        if p["kind"] in ("heading", "noise"):
            n, pages = _count_lines(doc_id, re.compile(p["pattern"]))
            p["matches"] = n
            p["pages"] = len([x for x in pages if x is not None])
            p["evidence"].append(f"이 자료에서 아직 {n}줄이 이 모양과 맞습니다" + (f"({p['pages']}쪽)" if p["pages"] else ""))
        out.append(p)
    return out


def accept(proposal: dict, scope: dict, note: str | None = None) -> dict:
    """제안을 규칙으로 저장한다(origin='learned'). 범위는 사용자가 고른다."""
    return create_rule(proposal["kind"], proposal.get("pattern"), proposal.get("params"), scope, origin="learned",
                       note=note or proposal.get("note"))
