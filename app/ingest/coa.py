"""CoA(성적서) 엑셀 → 시료 정보 + 측정값. LLM 없이 템플릿(머리글 별칭)으로 읽는다.

ByOrbit CoA 양식(02_byorbit-coa-v2 lib/coa/schema.ts)의 항목을 기준으로 한다.
- 머리부(메타): 시료명/부산물종, 품종, 산지, 수확시기, 분석기관, 분석일, 건조방법·온도·시간, 로트·의뢰처·성적서번호
- 측정표: 시험항목 | 결과 | 단위 | 기준 | 시험방법
새 양식을 받으면 COA_TEMPLATE·ITEMS의 별칭만 늘리면 된다.
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
    # 머리부 메타 별칭 → sample 컬럼(또는 자료 메모)
    "meta": {
        "sample_name": ["시료명", "제품명", "품명", "sample name", "product"],
        "byproduct": ["부산물종", "부산물 종류", "부산물", "byproduct type", "byproduct_type", "byproduct"],
        "variety": ["품종", "variety", "cultivar"],
        "region": ["산지", "원산지", "생산지", "region", "origin"],
        "harvest": ["수확시기", "수확 시기", "수확일", "harvest season", "harvest_season", "harvest"],
        "lab": ["분석기관", "시험기관", "검사기관", "lab", "laboratory"],
        "analyzed_at": ["분석일", "분석일자", "시험일", "시험일자", "검사일", "measured at", "measured_at",
                        "analysis date", "test date"],
        "lot_no": ["lot no", "lot no.", "lot", "로트", "로트번호", "제조번호", "batch no", "batch id", "batch_id"],
        "supplier": ["공급처", "의뢰처", "의뢰인", "제조사", "supplier", "client"],
        "collected_at": ["채취일", "시료채취일", "접수일", "제조일", "sampling date", "date received"],
        "sample_code": ["시료번호", "접수번호", "성적서번호", "sample no", "sample id", "report no"],
        "drying_method": ["건조방법", "건조 방법", "drying method", "drying_method"],
        "drying_temp": ["건조온도", "건조 온도", "drying temp", "drying temperature", "drying_temp_c"],
        "drying_time": ["건조시간", "건조 시간", "drying time", "drying_time_h"],
        "pretreatment": ["전처리", "pretreatment"],
    },
}

# 부산물 코드(CoA 앱의 byproduct_type) → 시소러스 표준명
BYPRODUCT_CODES = {"apple_pomace": "사과박", "coffee_grounds": "커피박", "citrus_pomace": "감귤박",
                   "cabbage_residue": "배추 외엽", "grape_pomace": "포도박", "pear_pomace": "배박"}

# 건조 방법 표준명(공정 체계 개념) ← 표기
DRYING = [
    ("동결건조", ["동결건조", "동결 건조", "동결", "freeze_dry", "freeze dry", "freeze-dry", "freeze drying",
              "freeze-drying", "freeze dried", "freeze-dried", "lyophilized", "fd"]),
    ("열풍건조", ["열풍건조", "열풍 건조", "열풍", "hot_air", "hot air", "hot-air", "hot air drying", "had"]),
    ("분무건조", ["분무건조", "분무 건조", "분무", "spray_dry", "spray dry", "spray-dry", "spray drying", "sd"]),
    ("자연건조", ["자연건조", "자연 건조", "자연(천일)", "자연", "천일건조", "천일", "양건", "일광건조", "sun_dry",
              "sun dry", "sun-dry", "sun drying", "sun dried", "natural drying"]),
    ("진공건조", ["진공건조", "진공 건조", "진공", "vacuum_dry", "vacuum dry", "vacuum drying", "vacuum"]),
    ("없음", ["없음", "건조 안 함", "미건조", "none", "no drying", "-"]),
]

# 측정 항목: (표준 항목명 = measurement.target_text, 별칭, 기본 단위)
ITEMS = [
    ("수분(생시료)", ["수분(생시료)", "생시료 수분", "생시료수분", "원료 수분", "fresh moisture", "fresh_moisture_pct",
                  "moisture (fresh)", "moisture(fresh)"], "%"),
    ("수분(건조 후)", ["수분(건조 후)", "수분(건조후)", "건조 후 수분", "건조후 수분", "건조물 수분", "dry moisture",
                   "dry_moisture_pct", "moisture (dried)", "moisture(dried)", "moisture (dry)"], "%"),
    ("총식이섬유", ["총식이섬유", "총 식이섬유", "식이섬유", "tdf", "total dietary fiber", "total dietary fibre",
               "tdf_g_per_100g"], "g/100 g"),
    ("총폴리페놀", ["총폴리페놀", "총 폴리페놀", "폴리페놀", "총페놀", "총 페놀", "tpc", "total phenolic content",
               "total phenolics", "tpc_mggae_per_g"], "mg GAE/g"),
    ("펙틴", ["펙틴", "pectin", "pectin_g_per_100g"], "g/100 g"),
    ("조단백", ["조단백", "조단백질", "단백질", "protein", "crude protein", "protein_g_per_100g"], "g/100 g"),
    ("당류", ["당류", "총당", "sugar", "sugars", "total sugar", "sugar_g_per_100g"], "g/100 g"),
    ("조지방", ["조지방", "지방", "fat", "crude fat", "fat_g_per_100g"], "g/100 g"),
    ("수분", ["수분", "moisture", "moisture content"], "%"),
    ("회분", ["회분", "조회분", "ash", "crude ash"], "%"),
    ("pH", ["ph", "수소이온농도"], None),
    ("납", ["납", "pb", "lead", "pb_ppm"], "ppm"),
    ("카드뮴", ["카드뮴", "cd", "cadmium", "cd_ppm"], "ppm"),
    ("비소", ["비소", "as", "arsenic", "as_ppm"], "ppm"),
    ("수은", ["수은", "hg", "mercury", "hg_ppm"], "ppm"),
    ("일반세균", ["일반세균", "일반세균수", "총균수", "total aerobic", "total aerobic count", "aerobic plate count",
              "total_aerobic_cfu_g", "apc"], "CFU/g"),
    ("대장균", ["대장균", "e. coli", "e.coli", "ecoli", "escherichia coli"], None),
    ("살모넬라", ["살모넬라", "salmonella"], None),
    ("리스테리아", ["리스테리아", "listeria", "listeria monocytogenes"], None),
]

ND_WORDS = ["불검출", "nd", "n.d.", "n.d", "not detected", "음성", "negative", "none detected", "검출되지 않음"]
DETECTED_WORDS = ["검출", "detected", "양성", "positive"]

_NUM = re.compile(r"^[<>≤≥]?\s*[-−]?\d+(?:[.,]\d+)?")
_SCI = re.compile(r"^([-−]?\d+(?:\.\d+)?)\s*[x×*]\s*10\s*\^?\s*([-−]?\d+|[⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+)$", re.I)
_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
_PAREN = re.compile(r"\s*[\(\[（][^\)\]）]*[\)\]）]\s*")


def _norm(s) -> str:
    return re.sub(r"[\s:：]+", " ", str(s or "")).strip().lower()


def _key(s) -> str:
    """항목·표기 비교용: 소문자, 공백·밑줄·하이픈·가운뎃점 제거."""
    return re.sub(r"[\s_\-·]+", "", str(s or "").lower()).replace("−", "")


def _match(cell, aliases) -> bool:
    n = _norm(cell)
    if not n:
        return False
    cands = {n, _PAREN.sub(" ", n).strip()}  # '건조온도(℃)' → '건조온도'
    return any(c == a or c.startswith(a + " ") or c.rstrip(".") == a for c in cands if c for a in aliases)


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


# ---------------------------------------------------------------- 값 해석

def to_number(raw) -> float | None:
    """'52.6', '< 0.01', '0.01 미만', '1.2×10^3', '60 ℃' → 숫자. 못 읽으면 None."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace(",", "").replace("−", "-")
    m = _SCI.match(s)
    if m:
        try:
            return float(m.group(1)) * 10 ** int(m.group(2).translate(_SUP))
        except ValueError:
            return None
    try:
        return float(s)  # 1.2E+03 같은 표기
    except ValueError:
        pass
    m = _NUM.match(s)
    if m:
        try:
            return float(re.sub(r"[<>≤≥\s]", "", m.group(0)))
        except ValueError:
            return None
    return None


def parse_value(raw) -> tuple[float | None, str]:
    """결과 칸 → (value, value_text). ND·검출은 값 없이 글자만 남긴다.
    '< 0.01'처럼 부등호가 붙으면 value는 숫자(0.01), value_text에 부등호를 그대로 둔다."""
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw), str(raw)
    s = str(raw).strip()
    low = s.lower()
    if low in ND_WORDS or low.replace(" ", "") in ("불검출", "n.d.", "nd"):
        return None, s if s in ("불검출", "ND") else "ND"
    if low in DETECTED_WORDS:
        return None, s if s == "검출" else "검출"
    m = re.match(r"^([-−]?\d+(?:[.,]\d+)?)\s*(미만|이하)$", s)
    if m:
        return float(m.group(1).replace(",", "").replace("−", "-")), s
    return to_number(s), s


def drying_method(text) -> str | None:
    """건조 방법 표기 → 표준명(동결건조·열풍건조·분무건조·자연건조·진공건조) 또는 '없음'. 모르면 None."""
    if text is None:
        return None
    k = _key(text)
    if not k:
        return None
    for std, aliases in DRYING:
        if any(k == _key(a) for a in aliases):
            return std
    for std, aliases in DRYING:  # '동결건조 후 분쇄'처럼 문장 속에 있으면
        if std != "없음" and any(len(_key(a)) >= 2 and not _key(a).isascii() and _key(a) in k for a in aliases):
            return std
    return None


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def pretreatment_text(method: str | None, temp: float | None, hours: float | None, raw: str | None = None) -> str | None:
    """계약 형식: '<방법 표준명>; <온도> ℃; <시간> h' — 모르는 칸은 뺀다."""
    parts = [method or (raw.strip() if raw else None)]
    if temp is not None:
        parts.append(f"{_fmt(temp)} ℃")
    if hours is not None:
        parts.append(f"{_fmt(hours)} h")
    parts = [p for p in parts if p]
    return "; ".join(parts) or None


_ITEM_INDEX = [(std, [_key(a) for a in aliases], unit) for std, aliases, unit in ITEMS]


def match_item(item: str) -> tuple[str | None, str | None, str | None]:
    """항목명 → (표준 항목명, 기본 단위, 괄호 속 단위). 모르는 항목은 (None, None, 괄호 단위)."""
    raw = str(item or "").strip()
    paren = re.findall(r"[\(\[（]([^\)\]）]*)[\)\]）]", raw)
    unit_in_paren = next((p.strip() for p in paren if re.search(r"(/|%|ppm|cfu|mg|g\b|℃)", p, re.I)), None)
    cands = [raw, _PAREN.sub(" ", raw).strip()]
    cands += [t for t in re.split(r"[\s/]+", cands[1]) if t]
    for c in cands:
        k = _key(c)
        for std, keys, unit in _ITEM_INDEX:
            if k in keys:
                return std, unit, unit_in_paren
    return None, None, unit_in_paren


# ---------------------------------------------------------------- 표 읽기

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

    # 메타: 머리글 위쪽 '라벨 | 값' 쌍
    sample = {}
    for row in grid[:header_row]:
        for ci, cell in enumerate(row):
            if not isinstance(cell, str):
                continue
            for key, aliases in T["meta"].items():
                if key in sample or not _match(cell, aliases):
                    continue
                val = next((v for v in row[ci + 1:] if v not in (None, "")), None)
                if val is None and ":" in str(cell):
                    val = str(cell).split(":", 1)[1].strip() or None
                if val is not None:
                    sample[key] = (val.strftime("%Y-%m-%d") if hasattr(val, "strftime") else str(val).strip())
                break
    for k in ("byproduct", "sample_name"):
        if sample.get(k) and sample[k].strip().lower() in BYPRODUCT_CODES:
            sample[k] = BYPRODUCT_CODES[sample[k].strip().lower()]

    # 건조 정보 → 계약 형식의 전처리 문자열
    method = drying_method(sample.get("drying_method")) or drying_method(sample.get("pretreatment"))
    temp, hours = to_number(sample.get("drying_temp")), to_number(sample.get("drying_time"))
    raw_pre = sample.get("drying_method") or sample.get("pretreatment")
    sample["drying"] = method
    sample["drying_temp_c"], sample["drying_time_h"] = temp, hours
    sample["pretreatment_text"] = pretreatment_text(None if method == "없음" else method, temp, hours,
                                                    "없음" if method == "없음" else raw_pre)

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
        value, value_text = parse_value(raw)
        std, default_unit, paren_unit = match_item(item)
        unit = str(get("unit")).strip() if get("unit") not in (None, "") else (paren_unit or default_unit)
        items.append({
            "item": std or item, "item_raw": item, "value": value, "value_text": value_text,
            "unit": unit,
            "method": (str(get("method")).strip() if get("method") not in (None, "") else None),
            "basis": (str(get("basis")).strip() if get("basis") not in (None, "") else None),
        })
    return {"header_found": True, "sample": sample, "items": items, "header_row": header_row + 1}
