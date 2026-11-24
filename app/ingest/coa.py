"""CoA(성적서) 엑셀 → 시료 정보 + 측정값. LLM 없이 템플릿(머리글 별칭)으로 읽는다.

실제 CoA 양식을 받으면 COA_TEMPLATE의 별칭만 늘리면 된다.
"""
from __future__ import annotations

import re
from pathlib import Path

COA_TEMPLATE = {
    # 측정표 머리글 별칭
    "item": ["시험항목", "분석항목", "항목", "검사항목", "item", "parameter", "test item", "analyte"],
    "value": ["결과", "결과값", "분석결과", "측정값", "시험결과", "result", "value"],
    "unit": ["단위", "unit"],
    "method": ["시험방법", "분석방법", "방법", "method", "test method"],
    "basis": ["기준", "기준(건량/습량)", "basis"],
    "spec": ["규격", "기준치", "spec", "specification"],
    # 머리부 메타 별칭 → sample 컬럼
    "meta": {
        "sample_name": ["시료명", "제품명", "품명", "sample name", "product"],
        "lot_no": ["lot no", "lot no.", "lot", "로트", "로트번호", "제조번호", "batch no"],
        "supplier": ["공급처", "의뢰처", "의뢰인", "제조사", "supplier", "client"],
        "collected_at": ["채취일", "시료채취일", "접수일", "제조일", "sampling date", "date received"],
        "sample_code": ["시료번호", "접수번호", "성적서번호", "sample no", "sample id", "report no"],
        "pretreatment": ["전처리", "건조방법", "pretreatment"],
    },
}

_NUM = re.compile(r"^[<>≤≥]?\s*-?\d+(?:[.,]\d+)?")


def _norm(s) -> str:
    return re.sub(r"[\s:：]+", " ", str(s or "")).strip().lower()


def _match(cell, aliases) -> bool:
    n = _norm(cell)
    return bool(n) and any(n == a or n.startswith(a + " ") or n.rstrip(".") == a for a in aliases)


def looks_like_coa(path: Path) -> bool:
    try:
        return read(path, probe=True)["header_found"]
    except Exception:
        return False


def read(path: Path, probe: bool = False) -> dict:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    try:
        for ws in wb.worksheets:
            grid = [[c for c in r] for r in ws.iter_rows(values_only=True)]
            res = _read_grid(grid)
            if res["header_found"]:
                res["sheet"] = ws.title
                return res
        return {"header_found": False, "sample": {}, "items": []}
    finally:
        wb.close()


def _read_grid(grid: list[list]) -> dict:
    T = COA_TEMPLATE
    header_row, cols = None, {}
    for ri, row in enumerate(grid[:60]):
        found = {}
        for ci, cell in enumerate(row):
            for key in ("item", "value", "unit", "method", "basis", "spec"):
                if key not in found and _match(cell, T[key]):
                    found[key] = ci
        if "item" in found and "value" in found:
            header_row, cols = ri, found
            break
    if header_row is None:
        return {"header_found": False, "sample": {}, "items": []}

    # 메타: 머리글 위쪽(그리고 표 아래 서명부 전까지) '라벨 | 값' 쌍
    sample = {}
    for row in grid[:header_row]:
        for ci, cell in enumerate(row):
            for key, aliases in T["meta"].items():
                if key in sample or not _match(cell, aliases):
                    continue
                val = next((v for v in row[ci + 1:] if v not in (None, "")), None)
                if val is None and ":" in str(cell):
                    val = str(cell).split(":", 1)[1].strip() or None
                if val is not None:
                    sample[key] = str(val).strip()

    items = []
    for row in grid[header_row + 1:]:
        if not row or all(v in (None, "") for v in row):
            continue
        get = lambda k: row[cols[k]] if k in cols and cols[k] < len(row) else None  # noqa: E731
        item = get("item")
        raw = get("value")
        if item in (None, "") or raw in (None, ""):
            continue
        item = str(item).strip()
        if _match(item, ["비고", "remarks", "판정", "종합판정", "시험자", "확인자", "작성자"]):
            break
        raw_s = str(raw).strip()
        value = None
        if isinstance(raw, (int, float)):
            value = float(raw)
        else:
            m = _NUM.match(raw_s.replace(",", ""))
            if m:
                try:
                    value = float(re.sub(r"[<>≤≥\s]", "", m.group(0)))
                except ValueError:
                    value = None
        items.append({
            "item": item, "value": value, "value_text": raw_s,
            "unit": (str(get("unit")).strip() if get("unit") not in (None, "") else None),
            "method": (str(get("method")).strip() if get("method") not in (None, "") else None),
            "basis": (str(get("basis")).strip() if get("basis") not in (None, "") else None),
        })
    return {"header_found": True, "sample": sample, "items": items, "header_row": header_row + 1}
