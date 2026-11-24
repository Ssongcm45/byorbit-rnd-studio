"""청크 검색: 시소러스로 동의어를 넓히고, 3글자 이상은 FTS5 trigram, 짧은 말은 LIKE.

검색어를 공백으로 나눈 각 묶음(=개념)은 AND, 묶음 안의 동의어는 OR.
"""
from __future__ import annotations

import re

from . import db, thesaurus


def _groups(query: str) -> list[list[str]]:
    query = query.strip()
    if not query:
        return []
    # 따옴표로 묶은 구절은 한 덩어리로
    parts = re.findall(r'"([^"]+)"|(\S+)', query)
    terms = [a or b for a, b in parts]
    # 공백이 있는 시소러스 표기(예: '사과 착즙박')를 먼저 붙여 본다
    merged, i = [], 0
    while i < len(terms):
        took = False
        for n in (3, 2):
            if i + n <= len(terms):
                cand = " ".join(terms[i:i + n])
                if thesaurus.lookup(cand) and thesaurus.lookup(cand)[0]["exact"]:
                    merged.append(cand)
                    i += n
                    took = True
                    break
        if not took:
            merged.append(terms[i])
            i += 1
    return [thesaurus.expand(t) for t in merged]


def _fts_quote(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def search(query: str, project: str | None = None, limit: int = 20, doc_id: str | None = None) -> dict:
    groups = _groups(query)
    if not groups:
        return {"query": query, "expanded": [], "results": []}

    where, params = [], []
    for syns in groups:
        long_ = [s for s in syns if len(s) >= 3]
        short = [s for s in syns if len(s) < 3]
        ors = []
        if long_:
            ors.append("c.rowid IN (SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ?)")
            params.append(" OR ".join(_fts_quote(s) for s in long_))
        for s in short:
            ors.append("c.text LIKE ?")
            params.append(f"%{s}%")
        where.append("(" + " OR ".join(ors) + ")")

    if project:
        where.append("c.doc_id IN (SELECT entity_id FROM project_item pi JOIN project p ON p.project_id=pi.project_id "
                     "WHERE pi.entity_type='document' AND p.name=?)")
        params.append(project)
    if doc_id:
        where.append("c.doc_id = ?")
        params.append(doc_id)

    sql = ("SELECT c.chunk_id, c.doc_id, c.chunk_type, c.page, c.text, d.file_name, s.confidentiality "
           "FROM chunk c JOIN document d ON d.doc_id=c.doc_id JOIN source s ON s.source_id=d.source_id "
           "WHERE " + " AND ".join(where) + " LIMIT ?")
    params.append(limit * 5)
    hits = db.rows(sql, params)

    # 간단 점수: 동의어 출현 횟수 합. 표준명/원문 표기에 가중치
    flat = [s.lower() for g in groups for s in g]
    for h in hits:
        low = h["text"].lower()
        h["score"] = sum(low.count(s) for s in flat)
        h["snippet"] = _snippet(h["text"], flat)
    hits.sort(key=lambda h: -h["score"])
    for h in hits:
        del h["text"]
    return {"query": query, "expanded": groups, "results": hits[:limit]}


def _snippet(text: str, terms: list[str], width: int = 160) -> str:
    low = text.lower()
    pos = min([low.find(t) for t in terms if low.find(t) >= 0] or [0])
    a = max(0, pos - width // 3)
    s = text[a:a + width].replace("\n", " ")
    return ("…" if a else "") + s + ("…" if a + width < len(text) else "")
