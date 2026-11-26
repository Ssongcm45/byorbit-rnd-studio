"""시소러스: 표기 → 개념 매칭과 동의어 확장.

문서 작업대에서 배운 것도 여기서 반영한다.
- 배운 동의어: concept_label(alt)로 들어가므로 다른 표기와 똑같이 찾힌다(add_alt_label).
- 부정 사례: label_example(kind='negative', enabled=1). 사람이 거절한 사전 라벨의 표기는
  같은 문맥(바로 앞 또는 뒤 낱말이 같을 때)에서 다시 붙이지 않는다. scope='everywhere'면 어디서나 건너뛴다.
"""
from __future__ import annotations

import json
import re
import threading

from . import db

_cache: dict | None = None
_lock = threading.Lock()


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _load() -> dict:
    """{정규화된 표기: [(concept_id, 표준명, 체계)]} 와 {concept_id: [표기...]}"""
    global _cache
    with _lock:
        if _cache is None:
            surf: dict[str, list] = {}
            by_concept: dict[str, dict] = {}
            for r in db.rows(
                "SELECT l.label, c.concept_id, c.pref_label_ko, s.name AS scheme "
                "FROM concept_label l JOIN concept c ON c.concept_id=l.concept_id "
                "LEFT JOIN concept_scheme s ON s.scheme_id=c.scheme_id WHERE c.status='active'"):
                k = _norm(r["label"])
                if not k:
                    continue
                surf.setdefault(k, [])
                if r["concept_id"] not in [x[0] for x in surf[k]]:
                    surf[k].append((r["concept_id"], r["pref_label_ko"], r["scheme"]))
                info = by_concept.setdefault(r["concept_id"], {"pref": r["pref_label_ko"], "scheme": r["scheme"], "labels": []})
                info["labels"].append(r["label"])
            negs: dict[str, list] = {}
            try:
                for r in db.rows("SELECT ex_id, surface, concept_id, value_json, context FROM label_example "
                                 "WHERE kind='negative' AND enabled=1"):
                    try:
                        v = json.loads(r["value_json"] or "{}") or {}
                    except ValueError:
                        v = {}
                    negs.setdefault(_norm(r["surface"]), []).append(
                        {"ex_id": r["ex_id"], "concept_id": r["concept_id"], "scope": v.get("scope", "context"),
                         "left": v.get("left") or "", "right": v.get("right") or "",
                         "context": r["context"] or ""})
            except Exception:  # noqa: BLE001 — 표가 없는 오래된 DB
                negs = {}
            _cache = {"surf": surf, "concept": by_concept, "neg": negs}
        return _cache


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def lookup(term: str) -> list[dict]:
    """정확히 일치하는 표기 → 개념 목록. 없으면 부분 일치 상위 10개."""
    c = _load()
    k = _norm(term)
    hits = c["surf"].get(k)
    exact = True
    if not hits:
        exact = False
        hits = []
        for s, lst in c["surf"].items():
            if k and (k in s or (len(s) >= 2 and s in k)):
                for h in lst:
                    if h not in hits:
                        hits.append(h)
            if len(hits) >= 10:
                break
    out = []
    for cid, pref, scheme in hits:
        info = c["concept"][cid]
        out.append({"concept_id": cid, "pref_label": pref, "scheme": scheme,
                    "labels": sorted(set(info["labels"])), "exact": exact})
    return out


def expand(term: str) -> list[str]:
    """검색어 하나를 같은 개념의 모든 표기로 넓힌다. 개념이 없으면 원래 말만."""
    c = _load()
    hits = c["surf"].get(_norm(term))
    if not hits:
        return [term]
    out = [term]
    for cid, _, _ in hits:
        for lab in c["concept"][cid]["labels"]:
            if lab.lower() not in [o.lower() for o in out]:
                out.append(lab)
    return out


def _ascii_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


_PUNCT = " \t\r\n.,;:!?()[]{}<>\"'·…~-—–/"


def neighbors(text: str, i: int, j: int) -> tuple[str, str]:
    """표기 [i, j) 바로 앞·뒤 낱말. 붙어 있는 조사·접두어가 있으면 그것, 없으면 띄어 쓴 다음 낱말."""
    left_s, right_s = text[:i], text[j:]
    lt = re.split(r"\s+", left_s.rstrip())[-1] if left_s.strip() else ""
    rt = re.split(r"\s+", right_s.lstrip())[0] if right_s.strip() else ""
    return lt.strip(_PUNCT)[-12:].lower(), rt.strip(_PUNCT)[:12].lower()


def _negative_hit(c: dict, surf: str, cid: str, text: str, i: int, j: int) -> bool:
    """부정 사례와 맞는가. 문맥(context): 저장한 앞 낱말 또는 뒤 낱말 중 하나라도 같으면(2글자 이상만 비교)."""
    for n in c.get("neg", {}).get(surf, ()):
        if n["concept_id"] not in (None, cid):
            continue
        keys = [k for k in (n["left"], n["right"]) if len(k) >= 2]
        if n["scope"] == "everywhere":
            return True
        if not keys:  # 앞뒤 낱말이 너무 짧으면 주변 글(앞뒤 15자)이 저장한 문맥 안에 있을 때만
            if n.get("context") and text[max(0, i - 15):j + 15] in n["context"]:
                return True
            continue
        lt, rt = neighbors(text, i, j)
        if (len(n["left"]) >= 2 and n["left"] == lt) or (len(n["right"]) >= 2 and n["right"] == rt):
            return True
    return False


def add_alt_label(concept_id: str, label: str) -> str | None:
    """개념에 동의어(alt) 하나를 더한다. 이미 그 개념의 표기면 None. 캐시를 비운다."""
    label = re.sub(r"\s+", " ", (label or "").strip())
    if not label:
        raise ValueError("빈 표기는 동의어로 배울 수 없습니다.")
    have = db.one("SELECT label_id FROM concept_label WHERE concept_id=? AND lower(label)=lower(?)", (concept_id, label))
    if have:
        return None
    lid = db.new_id()
    with db.tx() as t:
        t.execute("INSERT INTO concept_label(label_id, concept_id, label, lang, label_type) VALUES (?,?,?,?, 'alt')",
                  (lid, concept_id, label, None))
        db.log_change(t, "concept_label", lid, None,
                      {"concept_id": concept_id, "label": label, "label_type": "alt", "origin": "mine", "learned": True})
    invalidate()
    return lid


def find_mentions(text: str, min_len: int = 2, negatives: bool = True) -> list[dict]:
    """본문에서 시소러스 표기를 찾는다(사전 라벨링). 긴 표기를 먼저, 겹치면 긴 쪽을 남긴다.
    negatives=True면 사람이 거절해 배운 부정 사례(같은 문맥의 같은 표기)는 건너뛴다."""
    c = _load()
    low = text.lower()
    found = []
    taken = [False] * len(text)
    for surf in sorted(c["surf"].keys(), key=len, reverse=True):
        if len(surf) < min_len:
            continue
        # 영문 약어는 단어 경계를 지킨다 (예: 'FD', 'TPC')
        ascii_word = re.fullmatch(r"[a-z0-9 .\-/%]+", surf) is not None
        start = 0
        while True:
            i = low.find(surf, start)
            if i < 0:
                break
            j = i + len(surf)
            start = i + 1
            if ascii_word:
                if (i > 0 and _ascii_alnum(low[i - 1])) or (j < len(low) and _ascii_alnum(low[j])):
                    continue
            if any(taken[i:j]):
                continue
            cid, pref, scheme = c["surf"][surf][0]
            if negatives and _negative_hit(c, surf, cid, text, i, j):
                continue
            for k in range(i, j):
                taken[k] = True
            found.append({"start": i, "end": j, "surface": text[i:j], "concept_id": cid,
                          "pref_label": pref, "scheme": scheme})
    return sorted(found, key=lambda x: x["start"])
