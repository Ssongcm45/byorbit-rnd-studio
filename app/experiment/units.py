"""대상(수분·TPC …)과 조건(온도·시간 …)의 이름 맞추기, 단위 환산, 값 읽기(ND·'< 0.01')."""
from __future__ import annotations

import re

from ..ingest import coa
from ..viz import predict as P
from .steps import TARGETS


def key(s) -> str:
    """비교용: 소문자, 공백·밑줄·하이픈·가운뎃점·괄호 속 제거."""
    s = re.sub(r"[\(\[（][^\)\]）]*[\)\]）]", " ", str(s or ""))
    return re.sub(r"[\s_\-·.:/]+", "", s.lower()).replace("−", "")


# 대상: 구체적인 것부터 확인한다(예: 'TPC 잔존율'이 'TPC'보다 먼저)
TARGET_ALIASES: list[tuple[str, list[str]]] = [
    ("tpc_extract_yield", ["tpc추출수율", "추출수율", "폴리페놀추출수율", "extractionyield"]),
    ("extract_tpc", ["추출tpc", "추출물tpc", "추출폴리페놀", "extracttpc"]),
    ("extract_solids", ["추출고형분", "추출물수율", "고형분추출수율", "extractyield"]),
    ("tpc_ret", ["tpc잔존율", "폴리페놀잔존율", "잔존율", "retention"]),
    ("tpc", ["tpc", "총폴리페놀", "폴리페놀", "총페놀", "phenolic", "polyphenol"]),
    ("tdf", ["tdf", "총식이섬유", "식이섬유", "dietaryfiber", "dietaryfibre", "fiber", "fibre"]),
    ("time_target", ["도달시간", "목표수분도달시간", "건조완료시간"]),
    ("energy_total", ["에너지합계", "전력량", "총에너지", "energytotal"]),
    ("energy", ["비에너지", "에너지", "sec", "specificenergy"]),
    ("dm_yield", ["건물수율", "고형분수율", "dmyield", "drymatteryield"]),
    ("sieve_yield", ["체통과수율", "통과수율", "체수율", "분말수율", "수율", "yield"]),
    ("moisture", ["수분", "함수율", "moisture", "watercontent", "mc"]),
    ("mass", ["질량", "무게", "중량", "mass", "weight"]),
]
LABEL_TO_KEY = {v["label"]: k for k, v in TARGETS.items()}


def canon_target(text) -> str | None:
    if text in TARGETS:
        return text
    if text in LABEL_TO_KEY:
        return LABEL_TO_KEY[text]
    k = key(text)
    if not k:
        return None
    for tk, aliases in TARGET_ALIASES:
        if any(a in k for a in aliases):
            return tk
    return None


def parse_cell(raw) -> tuple[float | None, str | None, str | None]:
    """칸 → (value, value_text, kind). kind: num | censored('< 0.01' — 값 0.01, 글자 보존) | nd(불검출) | text(숫자 아님) | None(빈칸)"""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, None, None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw), None, "num"
    s = str(raw).strip()
    v, t = coa.parse_value(s)
    if v is None:
        if t in ("ND", "불검출"):
            return None, t, "nd"
        return None, s, "text"
    if re.match(r"^[<>≤≥]", s) or re.search(r"(미만|이하|초과|이상)$", s):
        return v, s, "censored"
    return v, None, "num"


# ---------------------------------------------------------------- 단위

UNIT_FACTORS: dict[str, dict[str, float]] = {
    # 표준 단위로 바꾸는 곱셈 인자 (key → {단위 열쇠: 인자})
    "tpc": {"mggae/g": 1, "mg/g": 1, "ggae/kg": 1, "g/kg": 1, "mggae/100g": 0.01, "mg/100g": 0.01,
            "µg/g": 0.001, "ug/g": 0.001, "μg/g": 0.001, "mg/kg": 0.001, "mggae/kg": 0.001},
    "extract_tpc": {"mggae/g": 1, "mg/g": 1, "mggae/100g": 0.01, "mg/100g": 0.01},
    "tdf": {"%": 1, "g/100g": 1, "g/kg": 0.1},
    "moisture": {"%": 1, "g/100g": 1, "%wb": 1},
    "mass": {"kg": 1, "g": 0.001, "t": 1000, "ton": 1000},
    "time_h": {"h": 1, "hr": 1, "hour": 1, "시간": 1, "min": 1 / 60, "분": 1 / 60, "s": 1 / 3600, "초": 1 / 3600,
               "d": 24, "day": 24, "일": 24},
    "time_min": {"min": 1, "분": 1, "h": 60, "hr": 60, "시간": 60, "s": 1 / 60, "초": 1 / 60},
    "days": {"일": 1, "d": 1, "day": 1, "days": 1, "주": 7, "week": 7, "h": 1 / 24, "시간": 1 / 24, "월": 30, "개월": 30},
    "pressure_pa": {"pa": 1, "kpa": 1000, "mpa": 1e6, "mbar": 100, "torr": 133.322, "mtorr": 0.133322, "mmhg": 133.322, "atm": 101325},
    "energy": {"kwh/kg": 1, "kwh/kg물": 1, "mj/kg": 1 / 3.6, "mj/kg물": 1 / 3.6},
    "energy_total": {"kwh": 1, "mj": 1 / 3.6, "wh": 0.001},
    "residence_s": {"s": 1, "초": 1, "min": 60, "분": 60},
    "thickness_mm": {"mm": 1, "cm": 10, "m": 1000},
    "particle_mm": {"mm": 1, "µm": 0.001, "um": 0.001, "μm": 0.001, "cm": 10},
    "mesh_um": {"µm": 1, "um": 1, "μm": 1, "mm": 1000},
}
PCT_KEYS = {"tpc_ret", "dm_yield", "sieve_yield", "tpc_extract_yield", "extract_solids", "moisture_pct",
            "target_moisture_pct", "target_moisture", "initial_moisture", "yield_pct", "ethanol_pct", "rh",
            "uptake_pct", "solids_loss_pct", "tpc_loss_pct", "dissolved_pct", "holdup_pct"}
UNIT_FAMILY = {"time_target": "time_h", "time_h": "time_h", "time_min": "time_min", "days": "days",
               "tpc_mg_g": "tpc", "tdf_g_100g": "tdf", "mass_kg": "mass"}
TEMP_KEYS = {"temp_c", "outlet_c"}


def unit_key(u) -> str:
    return re.sub(r"[\s·]+", "", str(u or "").lower()).replace("℃", "c").replace("°c", "c")


def basis_of(text) -> str | None:
    k = str(text or "").lower()
    if any(w in k for w in ("건량", "건물", "dry basis", "d.b", "db)", "(db", " db", "dw")):
        return "건량"
    if any(w in k for w in ("습량", "생시료 기준", "wet basis", "w.b", "wb)", "(wb", " wb", "fw", "fresh weight")):
        return "습량"
    return None


def normalize(name: str, value: float | None, unit: str | None) -> tuple[float | None, str | None]:
    """값을 표준 단위로. → (값, 메모). 모르는 단위면 PredictError가 아니라 ValueError로 방향을 알린다."""
    if value is None:
        return None, None
    u = unit_key(unit)
    fam = UNIT_FAMILY.get(name, name)
    if not u:
        return value, None
    if name in TEMP_KEYS:
        if u in ("c", "도", "degc"):
            return value, None
        if u in ("f", "°f", "degf"):
            return (value - 32) * 5 / 9, "℉ → ℃"
        if u == "k":
            return value - 273.15, "K → ℃"
        raise ValueError(f"온도 단위 '{unit}'를 모릅니다. ℃·℉·K 중 하나로 적으세요.")
    if name == "moisture" and any(w in u for w in ("kg/kg", "kgwater/kgdm", "db", "건량")):
        return P.db_to_wb(value if "%" not in u else value / 100), "건량 기준 수분(kg/kg) → 습량 %"
    if name in PCT_KEYS or fam in PCT_KEYS:
        if u in ("%", "%wb", "percent", "퍼센트", "%v/v", "v/v", "%rh", "rh"):
            return value, None
        if u in ("0-1", "fraction", "비율"):
            return value * 100, "비율 → %"
    table = UNIT_FACTORS.get(fam)
    if table is None:
        return value, None
    for cand in (u, u.replace("gae", ""), u.replace("건량", "").replace("db", "")):
        if cand in table:
            f = table[cand]
            return value * f, (None if f == 1 else f"{unit} → 표준 단위(×{f:g})")
    raise ValueError(f"'{unit}' 단위를 모릅니다. 쓸 수 있는 단위: {', '.join(sorted(table))}")


def std_unit(name: str) -> str:
    if name in TARGETS:
        return TARGETS[name]["unit"]
    return {"time_h": "h", "time_min": "min", "days": "일", "temp_c": "℃", "outlet_c": "℃", "pressure_pa": "Pa",
            "residence_s": "s", "thickness_mm": "mm", "particle_mm": "mm", "mesh_um": "µm", "mass_kg": "kg",
            "tpc_mg_g": "mg GAE/g 건량", "tdf_g_100g": "g/100 g 건량"}.get(name, "%" if name in PCT_KEYS else "")
