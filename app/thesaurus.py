"""시소러스: 표기 → 개념 매칭과 동의어 확장."""
from __future__ import annotations

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
            _cache = {"surf": surf, "concept": by_concept}
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


def find_mentions(text: str, min_len: int = 2) -> list[dict]:
    """본문에서 시소러스 표기를 찾는다(사전 라벨링). 긴 표기를 먼저, 겹치면 긴 쪽을 남긴다."""
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
            for k in range(i, j):
                taken[k] = True
            cid, pref, scheme = c["surf"][surf][0]
            found.append({"start": i, "end": j, "surface": text[i:j], "concept_id": cid,
                          "pref_label": pref, "scheme": scheme})
    return sorted(found, key=lambda x: x["start"])
