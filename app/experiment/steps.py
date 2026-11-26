"""공정 단계 목록과 질량·수분·성분 흐름 모델.

흐름(stream) = {습량 kg, 건물 kg, 물 kg, 수분 % 습량, TPC·TDF(원료 대비 남은 비율), 입자 크기}.
단계마다 simulate(stream, params, ctx) → 새 흐름 + 예측값 + 근거 + 밝힌 손실을 돌려준다.

원칙
- 건물(고형분)은 보존한다. 줄어드는 것은 단계가 '손실'(losses)이나 '분리'(side)로 밝힌 만큼뿐이다.
- 건조 단계는 app/viz/predict.py의 predict()를 그대로 부른다 → 건조 방식 탭과 같은 값·같은 근거.
- 그 밖의 계수는 steps_sources.json에서만 온다. 문헌 값은 읽은 곳(locator)이 있어야 하고, 아니면 '가정'이다.
- 사용자가 넣은 값(런 조건)은 근거 종류 'input'(내 입력)으로 표시한다.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from ..viz import drying
from ..viz import predict as P

SOURCES_FILE = Path(__file__).with_name("steps_sources.json")
R_GAS = P.R_GAS


class StepError(ValueError):
    pass


# ---------------------------------------------------------------- 근거 목록

_reg: dict = {"mtime": None, "data": None}


def registry() -> dict:
    m = SOURCES_FILE.stat().st_mtime
    if _reg["mtime"] != m:
        _reg["data"] = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        _reg["mtime"] = m
    return _reg["data"]


def sv(pid: str):
    p = registry()["parameters"][pid]
    return P.pv(p["ref"]) if p.get("ref") else p["value"]


def sparam(pid: str, value=None, label: str | None = None, unit: str | None = None) -> dict:
    """predict.param()과 같은 모양 {key, label, value, unit, band?, evidence}."""
    p = registry()["parameters"][pid]
    if p.get("ref"):
        out = P.param(p["ref"], value=value, label=label or p.get("label"), unit=unit)
        out["key"] = pid
        return out
    ev = dict(p["evidence"])
    src = registry()["sources"].get(ev.get("source") or "") or P.registry()["sources"].get(ev.get("source") or "")
    e = {"type": ev["type"], "citation": None, "doi": None, "verified": False, "verified_at": None, "url": None,
         "locator": ev.get("locator"), "note": ev.get("note"), "validity": ev.get("validity") or {}}
    if src:
        e.update({"citation": src["citation"], "doi": src["doi"], "verified": bool(src["verified"]),
                  "verified_at": src["verified_at"], "url": src.get("url"), "source_id": ev["source"], "read": src.get("read")})
    out = {"key": pid, "label": label or p["label"], "value": p["value"] if value is None else value,
           "unit": unit or p["unit"], "evidence": e}
    if p.get("band") is not None:
        out["band"] = p["band"]
    return out


def input_param(key: str, label: str, value, unit: str, where: str = "흐름·런 조건") -> dict:
    """사용자가 넣은 값 — 계수가 아니라 입력이다."""
    return {"key": key, "label": label, "value": value, "unit": unit,
            "evidence": {"type": "input", "citation": None, "doi": None, "verified": False, "verified_at": None,
                         "locator": where, "note": "내가 넣은 값(가정 계수를 이 값으로 바꿈)", "validity": {}}}


def measured_default(key: str, label: str, value, unit: str, n: int, aliases: list[str], note: str) -> dict:
    return P.measured_param(label, value, unit, n, aliases, note, key)


# ---------------------------------------------------------------- 흐름(stream)

def make_stream(wet_kg: float, moisture_pct: float, tpc: float | None, tdf: float | None) -> dict:
    dm = wet_kg * (1 - moisture_pct / 100.0)
    return {"wet_kg": wet_kg, "dm_kg": dm, "water_kg": wet_kg - dm, "moisture_pct": moisture_pct,
            "moisture_lo": moisture_pct, "moisture_hi": moisture_pct,
            "tpc_rel": 1.0, "tpc_rel_lo": 1.0, "tpc_rel_hi": 1.0, "tdf_rel": 1.0,
            "feed_dm_kg": dm, "feed_tpc": tpc, "feed_tdf": tdf, "particle_mm": None}


def _set(s: dict, dm: float | None = None, water: float | None = None) -> dict:
    s = dict(s)
    if dm is not None:
        s["dm_kg"] = max(dm, 0.0)
    if water is not None:
        s["water_kg"] = max(water, 0.0)
    s["wet_kg"] = s["dm_kg"] + s["water_kg"]
    s["moisture_pct"] = 100.0 * s["water_kg"] / s["wet_kg"] if s["wet_kg"] > 0 else 0.0
    return s


def _water_for(dm: float, moisture_pct: float) -> float:
    m = min(max(moisture_pct, 0.0), 99.0) / 100.0
    return dm * m / (1 - m)


def conc(s: dict, which: str, rel_key: str | None = None) -> float | None:
    """건량 기준 농도 = 원료 농도 × 남은 비율 × 원료 건물 ÷ 지금 건물"""
    feed = s.get(f"feed_{which}")
    if feed is None or s["dm_kg"] <= 0:
        return None
    return feed * s[rel_key or f"{which}_rel"] * s["feed_dm_kg"] / s["dm_kg"]


def stream_view(s: dict) -> dict:
    def r(x, d=3):
        return None if x is None else round(x, d)
    tpc, tlo, thi = conc(s, "tpc"), conc(s, "tpc", "tpc_rel_lo"), conc(s, "tpc", "tpc_rel_hi")
    return {"wet_kg": r(s["wet_kg"]), "dm_kg": r(s["dm_kg"]), "water_kg": r(s["water_kg"]),
            "moisture_pct": r(s["moisture_pct"], 2), "moisture_lo": r(s["moisture_lo"], 2), "moisture_hi": r(s["moisture_hi"], 2),
            "tpc_mg_g": r(tpc), "tpc_lo": r(tlo), "tpc_hi": r(thi),
            "tpc_ret_pct": r(s["tpc_rel"] * 100, 2), "tpc_ret_lo": r(s["tpc_rel_lo"] * 100, 2), "tpc_ret_hi": r(s["tpc_rel_hi"] * 100, 2),
            "tdf_g_100g": r(conc(s, "tdf")), "dm_yield_pct": r(100 * s["dm_kg"] / s["feed_dm_kg"], 2) if s["feed_dm_kg"] else None,
            "particle_mm": s.get("particle_mm")}


# ---------------------------------------------------------------- 대상(예측·실측이 만나는 이름)

TARGETS: dict[str, dict] = {
    "moisture": {"label": "수분", "unit": "% 습량"},
    "mass": {"label": "질량", "unit": "kg 습량"},
    "dm_yield": {"label": "건물 수율(원료 대비)", "unit": "%"},
    "tpc": {"label": "TPC", "unit": "mg GAE/g 건량"},
    "tpc_ret": {"label": "TPC 잔존율(원료 대비)", "unit": "%"},
    "tdf": {"label": "TDF", "unit": "g/100 g 건량"},
    "time_target": {"label": "목표 수분 도달 시간", "unit": "h"},
    "energy": {"label": "비에너지", "unit": "kWh/kg 물"},
    "energy_total": {"label": "건조 에너지 합계", "unit": "kWh"},
    "sieve_yield": {"label": "체 통과 수율", "unit": "%"},
    "tpc_extract_yield": {"label": "TPC 추출 수율", "unit": "% TPC"},
    "extract_tpc": {"label": "추출 TPC(투입 분말 1 g당)", "unit": "mg GAE/g 건량"},
    "extract_solids": {"label": "추출 고형분 수율", "unit": "% 건물"},
    # 펙틴·제품 수율처럼 모델이 예측하지 않는 측정 수율(비교·보정 없이 기록·통계 분석용)
    "product_yield": {"label": "수율", "unit": "%"},
}


# ---------------------------------------------------------------- 단계 정의

def _num(key, label, unit, lo, hi, default, step=1, optional=False, help=None):  # noqa: A002
    d = {"key": key, "label": label, "unit": unit, "type": "number", "min": lo, "max": hi, "step": step, "default": default}
    if optional:
        d["optional"] = True
    if help:
        d["help"] = help
    return d


PACKAGES = ["방습(알루미늄)", "일반 PE", "개방"]
THICK_SOURCES = ["층 두께", "분쇄 입자 크기"]

# 범주 조건(기록·통계 분석용). 목록에서 고르거나 직접 입력(free) — 모델 계산에는 쓰지 않는다(근거 없음).
ACIDS = ["구연산", "염산", "질산", "황산", "옥살산", "초산", "젖산", "사과산", "없음"]
SOLVENTS = ["에탄올 수용액", "물", "에탄올", "메탄올", "아세톤 수용액", "산 수용액"]
CHOICE_ALIASES = {  # 비교용 열쇠(소문자·공백 제거) → 목록 이름
    "acid": {"citric": "구연산", "citricacid": "구연산", "시트르산": "구연산", "hcl": "염산", "hydrochloric": "염산",
             "hydrochloricacid": "염산", "염화수소산": "염산", "nitric": "질산", "nitricacid": "질산", "hno3": "질산",
             "sulfuric": "황산", "sulfuricacid": "황산", "sulphuric": "황산", "h2so4": "황산", "oxalic": "옥살산",
             "oxalicacid": "옥살산", "acetic": "초산", "aceticacid": "초산", "아세트산": "초산", "lactic": "젖산",
             "lacticacid": "젖산", "malic": "사과산", "malicacid": "사과산", "none": "없음", "-": "없음", "무": "없음"},
    "solvent": {"water": "물", "h2o": "물", "증류수": "물", "정제수": "물", "탈이온수": "물", "ethanol": "에탄올",
                "etoh": "에탄올", "주정": "에탄올", "methanol": "메탄올", "meoh": "메탄올", "aqueousethanol": "에탄올 수용액",
                "에탄올수용액": "에탄올 수용액", "함수에탄올": "에탄올 수용액", "아세톤수용액": "아세톤 수용액",
                "aqueousacetone": "아세톤 수용액", "산수용액": "산 수용액", "acidicwater": "산 수용액", "dilutedacid": "산 수용액"},
}


def _choice(key, label, label_en, options, help_):  # noqa: A002
    return {"key": key, "label": label, "label_en": label_en, "type": "select", "free": True, "optional": True,
            "default": None, "options": options, "recorded": True, "help": help_}


def canon_choice(spec: dict, raw) -> str | None:
    """범주 값 정리: 목록 이름 그대로 → 별칭(영문·화학식) → 직접 입력(앞뒤 공백 제거, 40자). 빈칸은 None."""
    if raw is None:
        return None
    v = " ".join(str(raw).split())
    if not v:
        return None
    if v in (spec.get("options") or []):
        return v
    k = v.lower().replace(" ", "").replace("_", "").replace("-", "") or v
    hit = CHOICE_ALIASES.get(spec.get("key"), {}).get(k)
    if hit:
        return hit
    for o in spec.get("options") or []:
        if o.replace(" ", "") == v.replace(" ", ""):
            return o
    return v[:40]

STEP_TYPES: dict[str, dict] = {
    "feed": {"label": "원료 투입", "group": "원료", "desc": "원료의 양·수분·성분. 비워 두면 내 CoA 실측 평균 → 가정 순으로 채운다.",
             "params": [_num("mass_kg", "투입량", "kg 습량", 0.001, 1e6, 100, 1),
                        _num("moisture_pct", "원료 수분", "% 습량", 5, 98, None, 0.1, True, "비우면 CoA 생시료 수분 평균 → 가정 78%"),
                        _num("tpc_mg_g", "원료 TPC", "mg GAE/g 건량", 0, 500, None, 0.01, True, "비우면 동결건조 CoA 평균(있으면)"),
                        _num("tdf_g_100g", "원료 TDF", "g/100 g 건량", 0, 100, None, 0.1, True, "비우면 CoA 평균(있으면)")]},
    "wash": {"label": "세척", "group": "전처리", "desc": "물로 씻어 이물·표면 당을 뺀다. 표면 물이 남고, 수용성 고형분·폴리페놀이 조금 녹아 나간다(가정).",
             "params": [_num("water_ratio", "물 비율", "L/kg", 0, 50, 3, 0.5, help="기록용 — 계산에 쓰지 않음"),
                        _num("time_min", "세척 시간", "min", 0, 240, 5, 1, help="기록용 — 계산에 쓰지 않음"),
                        _num("uptake_pct", "남는 표면 물", "% 습량", 0, 30, None, 0.1, True, "비우면 가정 3%"),
                        _num("solids_loss_pct", "고형분 손실", "% 건물", 0, 20, None, 0.1, True, "비우면 가정 1%"),
                        _num("tpc_loss_pct", "TPC 손실", "% TPC", 0, 50, None, 0.1, True, "비우면 가정 2%")]},
    "press": {"label": "탈수·압착", "group": "전처리", "desc": "눌러 물을 짜낸다. 짜낸 물에 녹은 고형분·폴리페놀이 함께 나간다(가정 농도).",
              "params": [_num("target_moisture_pct", "압착 후 수분", "% 습량", 20, 95, 65, 0.5),
                         _num("dissolved_pct", "압착액 용해 고형분", "% w/w", 0, 30, None, 0.1, True, "비우면 가정 8%")]},
    "mill": {"label": "분쇄", "group": "전처리", "desc": "입자를 작게 만든다. 건조 단계에서 입자 크기를 건조 두께로 쓸 수 있다.",
             "params": [_num("particle_mm", "입자 크기", "mm", 0.05, 50, 3, 0.05),
                        _num("holdup_pct", "분쇄기 잔류 손실", "% 습량", 0, 10, None, 0.1, True, "비우면 가정 0.5%")]},
    "dry": {"label": "건조", "group": "건조", "desc": "건조 방식 탭의 예측 모델을 그대로 쓴다(같은 값·같은 근거).",
            "params": [{"key": "method", "label": "건조 방식", "type": "select", "options": list(P.ORDER), "default": "열풍건조"}]},
    "sieve": {"label": "분쇄·체분리", "group": "분말화", "desc": "말린 것을 갈아 체로 거른다. 체를 통과한 분말만 다음 단계로 간다.",
              "params": [_num("mesh_um", "체 눈 크기", "µm", 45, 2000, 250, 5),
                         _num("yield_pct", "체 통과 수율 설정", "%", 1, 100, None, 0.1, True, "내가 잰 통과 수율을 계산에 쓰려면 넣으세요. 비우면 체 눈 크기별 가정 표"),
                         _num("holdup_pct", "회수 손실", "% 습량", 0, 10, None, 0.1, True, "비우면 가정 1%")]},
    "extract": {"label": "추출", "group": "추출", "desc": "에탄올 수용액으로 폴리페놀을 뽑는다. 계수는 모두 가정(내 추출 실측으로 바꾸세요).",
                "params": [_num("ethanol_pct", "에탄올 농도", "% v/v", 0, 100, 60, 1),
                           _num("temp_c", "추출 온도", "℃", 4, 90, 50, 1),
                           _num("time_min", "추출 시간", "min", 1, 1440, 60, 1),
                           _num("ratio_ml_g", "용매 비율", "mL/g", 1, 200, 20, 1),
                           _choice("solvent", "용매 종류", "Solvent", SOLVENTS,
                                   "계산에 쓰지 않음(기록·통계 분석용). 모델은 에탄올 수용액만 계산한다 — 목록에서 고르거나 직접 입력"),
                           _choice("acid", "산 종류", "Acid type", ACIDS,
                                   "계산에 쓰지 않음(기록·통계 분석용). 산의 효과는 근거가 없어 예측에 넣지 않는다 — 목록에서 고르거나 직접 입력")]},
    "store": {"label": "포장·저장", "group": "저장", "desc": "포장해 보관한다. 수분이 저장 습도의 평형으로 다가가고 TPC가 천천히 준다(가정 속도).",
              "params": [{"key": "package", "label": "포장", "type": "select", "options": PACKAGES, "default": "방습(알루미늄)"},
                         _num("days", "저장 기간", "일", 0, 1095, 90, 1),
                         _num("temp_c", "저장 온도", "℃", -20, 50, 25, 1),
                         _num("rh", "저장 습도", "%RH", 5, 95, 60, 1)]},
}
DEFAULT_LABELS = {k: v["label"] for k, v in STEP_TYPES.items()}


def dry_specs(method: str) -> list[dict]:
    """건조 방식별 입력 — predict.INPUTS 그대로 + 목표 수분 + 두께 기준(층 두께 / 분쇄 입자 크기)."""
    specs = [{"key": "method", "label": "건조 방식", "type": "select", "options": list(P.ORDER), "default": method}]
    specs += [{"type": "number", **s} for s in P.INPUTS[method]]
    tm = next(s for s in P.COMMON_MOIST if s["key"] == "target_moisture")
    specs.append({"type": "number", **tm})
    if any(s["key"] == "thickness_mm" for s in P.INPUTS[method]):
        specs.append({"key": "thickness_source", "label": "두께 기준", "type": "select", "options": THICK_SOURCES,
                      "default": "층 두께", "help": "'분쇄 입자 크기'를 고르면 앞 분쇄 단계의 입자 크기를 건조 두께로 쓴다(가정)"})
    return specs


def specs_for(step_type: str, params: dict | None = None) -> list[dict]:
    if step_type == "dry":
        return dry_specs(P.method_or_error((params or {}).get("method") or "열풍건조"))
    return [dict(s) for s in STEP_TYPES[step_type]["params"]]


def catalog() -> dict:
    return {"steps": [{"type": k, "label": v["label"], "group": v["group"], "desc": v["desc"],
                       "params": specs_for(k)} for k, v in STEP_TYPES.items()],
            "dry_methods": {m: dry_specs(m) for m in P.ORDER},
            "targets": [{"key": k, **v} for k, v in TARGETS.items()],
            "evidence": {pid: sparam(pid) for pid in registry()["parameters"]}}


def clean_params(step_type: str, params: dict | None, label: str = "") -> dict:
    """기본값을 채우고 범위를 확인한다. 선택(optional) 칸은 비우면 None."""
    if step_type not in STEP_TYPES:
        raise StepError(f"'{step_type}'는 없는 공정 단계입니다. {', '.join(DEFAULT_LABELS.values())} 중에서 고르세요.")
    raw = dict(params or {})
    if step_type == "dry":
        try:
            raw["method"] = P.method_or_error(raw.get("method") or "열풍건조")
        except P.PredictError as ex:
            raise StepError(str(ex)) from ex
    out = {}
    where = f"'{label}' 단계의 " if label else ""
    for s in specs_for(step_type, raw):
        v = raw.get(s["key"])
        if s.get("type") == "select":
            v = s["default"] if v in (None, "") else v
            if s.get("free"):
                out[s["key"]] = canon_choice(s, v)
                continue
            if v not in s["options"]:
                raise StepError(f"{where}'{s['label']}' 값 '{v}'는 고를 수 없습니다. {', '.join(s['options'])} 중 하나를 고르세요.")
            out[s["key"]] = v
            continue
        if v in (None, ""):
            out[s["key"]] = s["default"]
            continue
        try:
            v = float(v)
        except (TypeError, ValueError) as ex:
            raise StepError(f"{where}'{s['label']}' 값이 숫자가 아닙니다. {s['min']:g}–{s['max']:g} {s['unit']} 사이 숫자를 넣으세요.") from ex
        if not math.isfinite(v) or v < s["min"] or v > s["max"]:
            raise StepError(f"{where}'{s['label']}' {v:g} {s['unit']}는 범위 밖입니다. {s['min']:g}–{s['max']:g} {s['unit']} 사이로 넣으세요.")
        out[s["key"]] = v
    return out


# ---------------------------------------------------------------- 결과 조립 도우미

def _r(x, d=3):
    return None if x is None else round(x, d)


def _out(key: str, value, low=None, high=None, params=None, formula: str = "", model: str = "", warnings=None,
         basis: str | None = None, status: str = "ok", label: str | None = None) -> dict:
    t = TARGETS[key]
    return {"key": key, "label": label or t["label"], "value": value, "low": value if low is None else low,
            "high": value if high is None else high, "unit": t["unit"], "basis": basis, "status": status,
            "params": params or [], "formula": {"text": formula, "model": model}, "warnings": warnings or []}


def common_outputs(s: dict, params: list[dict], note: str, moisture_formula: str = "", tpc_formula: str = "") -> dict:
    v = stream_view(s)
    carry = "이전 단계의 근거는 그 단계에서 보세요."
    outs = {
        "mass": _out("mass", v["wet_kg"], params=params, formula="m = 건물 + 물", model=note + " " + carry),
        "moisture": _out("moisture", v["moisture_pct"], v["moisture_lo"], v["moisture_hi"], params=params,
                         formula=moisture_formula or "수분 = 물 ÷ (건물 + 물)", model=note + " " + carry, basis="습량"),
        "dm_yield": _out("dm_yield", v["dm_yield_pct"], params=params, formula="건물 수율 = 지금 건물 ÷ 원료 건물",
                         model="밝힌 손실(세척·압착·분쇄·체분리·추출 분리)만 건물을 줄인다. " + carry),
        "tpc_ret": _out("tpc_ret", v["tpc_ret_pct"], v["tpc_ret_lo"], v["tpc_ret_hi"], params=params,
                        formula=tpc_formula or "잔존율 = Π(단계별 남는 비율)", model=note + " " + carry),
    }
    if v["tpc_mg_g"] is not None:
        outs["tpc"] = _out("tpc", v["tpc_mg_g"], v["tpc_lo"], v["tpc_hi"], params=params, basis="건량",
                           formula="TPC = 원료 TPC × 잔존율 × 원료 건물 ÷ 지금 건물", model=note + " " + carry)
    if v["tdf_g_100g"] is not None:
        outs["tdf"] = _out("tdf", v["tdf_g_100g"], params=params, basis="건량",
                           formula="TDF = 원료 TDF × 원료 건물 ÷ 지금 건물(식이섬유 질량 보존)",
                           model="식이섬유(불용성)는 세척·압착·건조에서 보존된다고 본다(건조는 Llavata 2022 §3.4의 AIR 수율 무변화 근거). " + carry)
    return outs


def _pick(params: dict, key: str, pid: str, label: str, unit: str) -> tuple[float, dict]:
    """사용자가 넣었으면 그 값(내 입력), 비었으면 근거 목록의 가정값."""
    if params.get(key) is not None:
        return float(params[key]), input_param(key, label, params[key], unit)
    return float(sv(pid)), sparam(pid)


def _band(pid: str) -> list | None:
    return registry()["parameters"][pid].get("band")


# ---------------------------------------------------------------- 단계별 모의

def sim_feed(s_in, p, ctx) -> dict:
    meas = ctx.get("meas") or {}
    params, notes = [], []
    mass = float(p["mass_kg"])
    params.append(input_param("mass_kg", "투입량", mass, "kg 습량") if mass != 100 else sparam("f_mass"))
    if p.get("moisture_pct") is not None:
        m = float(p["moisture_pct"])
        params.append(input_param("moisture_pct", "원료 수분", m, "% 습량"))
    elif meas.get("initial_moisture"):
        im = meas["initial_moisture"]
        m = round(im["value"], 2)
        params.append(measured_default("f_moisture_meas", "원료 수분(CoA·실험 생시료 수분 평균)", m, "% 습량", im["n"],
                                       [x["alias"] for x in meas.get("samples", []) if x.get("moist_init") is not None],
                                       "원료 수분을 비워 둬서 내 실측 평균을 씀"))
    else:
        m = float(sv("f_moisture"))
        params.append(sparam("f_moisture"))
    tpc = p.get("tpc_mg_g")
    if tpc is not None:
        params.append(input_param("tpc_mg_g", "원료 TPC", tpc, "mg GAE/g 건량"))
    elif meas.get("tpc_ref"):
        ref = meas["tpc_ref"]
        tpc = round(ref["value"], 3)
        params.append(measured_default("f_tpc_meas", "원료 TPC(동결건조 실측 평균으로 근사)", tpc, "mg GAE/g 건량", ref["n"],
                                       ref.get("samples", []), "동결건조를 잔존율 1로 두는 건조 예측과 같은 기준. CoA 시료는 이미 앞 공정을 거친 것일 수 있으니 원료 TPC를 재서 넣으세요"))
    else:
        notes.append("원료 TPC를 모릅니다 — TPC는 잔존율(원료 대비 %)로만 계산합니다. 원료 TPC를 넣으면 mg GAE/g 값이 나옵니다.")
    tdf = p.get("tdf_g_100g")
    if tdf is not None:
        params.append(input_param("tdf_g_100g", "원료 TDF", tdf, "g/100 g 건량"))
    else:
        vals = [x["tdf"] for x in meas.get("samples", []) if x.get("tdf") is not None]
        if vals:
            tdf = round(sum(vals) / len(vals), 2)
            params.append(measured_default("f_tdf_meas", "원료 TDF(실측 평균)", tdf, "g/100 g 건량", len(vals),
                                           [x["alias"] for x in meas["samples"] if x.get("tdf") is not None],
                                           "식이섬유 보존 가정으로 건조 시료 TDF를 원료 값으로 씀. 그 시료가 이미 세척·압착을 거쳤다면 여기서 다시 농축되어 높게 나올 수 있음 — 원료 TDF를 재서 넣으세요"))
    s = make_stream(mass, m, tpc, tdf)
    outs = common_outputs(s, params, "원료 값.")
    return {"stream": s, "outputs": outs, "losses": [], "side": [], "notes": notes, "warnings": [], "params": params}


def sim_wash(s_in, p, ctx) -> dict:
    up, ev_up = _pick(p, "uptake_pct", "w_water_uptake", "남는 표면 물", "% 습량")
    sl, ev_sl = _pick(p, "solids_loss_pct", "w_solids_loss", "고형분 손실", "% 건물")
    tl, ev_tl = _pick(p, "tpc_loss_pct", "w_tpc_loss", "TPC 손실", "% TPC")
    params = [ev_up, ev_sl, ev_tl]
    lost_dm = s_in["dm_kg"] * sl / 100
    s = _set(s_in, dm=s_in["dm_kg"] - lost_dm, water=s_in["water_kg"] + s_in["wet_kg"] * up / 100)
    keep = 1 - tl / 100
    s["tpc_rel"] *= keep
    # 폭: 가정값일 때만 band로
    b_up = _band("w_water_uptake") if p.get("uptake_pct") is None else [up, up]
    b_tl = _band("w_tpc_loss") if p.get("tpc_loss_pct") is None else [tl, tl]
    lo_s = _set(s_in, dm=s["dm_kg"], water=s_in["water_kg"] + s_in["wet_kg"] * b_up[0] / 100)
    hi_s = _set(s_in, dm=s["dm_kg"], water=s_in["water_kg"] + s_in["wet_kg"] * b_up[1] / 100)
    s["moisture_lo"] = lo_s["moisture_pct"]
    s["moisture_hi"] = hi_s["moisture_pct"]
    s["tpc_rel_lo"] = s_in["tpc_rel_lo"] * (1 - b_tl[1] / 100)
    s["tpc_rel_hi"] = s_in["tpc_rel_hi"] * (1 - b_tl[0] / 100)
    s["tdf_rel"] = s_in["tdf_rel"]  # 불용성 식이섬유는 남는다
    outs = common_outputs(s, params, "세척: 표면 물이 더해지고 수용성 고형분·TPC가 일부 빠진다(가정).",
                          "물_후 = 물_전 + 습량 × 남는 표면 물 %", "잔존율_후 = 잔존율_전 × (1 − TPC 손실 %)")
    return {"stream": s, "outputs": outs, "params": params, "notes": [], "warnings": [], "side": [],
            "losses": [{"what": "세척수로 녹아 나간 고형분", "dm_kg": lost_dm, "wet_kg": lost_dm}]}


def sim_press(s_in, p, ctx) -> dict:
    target = float(p["target_moisture_pct"])
    dis, ev_dis = _pick(p, "dissolved_pct", "p_dissolved", "압착액 용해 고형분", "% w/w")
    params = [input_param("target_moisture_pct", "압착 후 수분", target, "% 습량"), ev_dis, sparam("p_tpc_partition"), sparam("p_min_moisture")]
    warns = []
    if target >= s_in["moisture_pct"]:
        warns.append({"kind": "info", "text": f"압착 후 수분 {target:g}%가 들어온 수분 {s_in['moisture_pct']:.1f}%보다 높아 짜낼 물이 없습니다. "
                                              "압착 후 수분을 낮추거나 이 단계를 끄세요."})
        s = dict(s_in)
        return {"stream": s, "outputs": common_outputs(s, params, "압착: 변화 없음."), "params": params, "notes": [],
                "warnings": warns, "side": [], "losses": []}
    if target < sv("p_min_moisture"):
        warns.append({"kind": "info", "text": f"압착 후 수분 {target:g}%는 기계 압착으로 흔히 낮출 수 있는 수준({sv('p_min_moisture'):g}%)보다 낮습니다. 설비 값을 확인하세요."})
    # 액 L kg(물 + 용해 고형분 c) → 남는 건물 dm' = dm − c·L, 남는 물 w' = w − (1−c)·L, w'/(dm'+w') = target
    c, t = dis / 100, target / 100
    dm, w = s_in["dm_kg"], s_in["water_kg"]
    if 1 - c - t <= 0:
        raise StepError(f"압착 후 수분 {target:g}%와 압착액 용해 고형분 {dis:g}%의 합이 100%를 넘어 계산할 수 없습니다. 둘 중 하나를 낮추세요.")
    # w − (1−c)L = t(dm + w − L)  →  L = (w − t(dm + w)) / (1 − c − t)
    liquid = max((w - t * (dm + w)) / (1 - c - t), 0.0)
    lost_dm = min(c * liquid, dm * 0.5)
    s = _set(s_in, dm=dm - lost_dm, water=w - (1 - c) * liquid)
    part = sv("p_tpc_partition")
    frac = lost_dm / dm if dm else 0.0
    keep = max(0.0, 1 - frac * part)
    pb = _band("p_tpc_partition")
    s["tpc_rel"] = s_in["tpc_rel"] * keep
    s["tpc_rel_lo"] = s_in["tpc_rel_lo"] * max(0.0, 1 - frac * pb[1])
    s["tpc_rel_hi"] = s_in["tpc_rel_hi"] * max(0.0, 1 - frac * pb[0])
    s["moisture_lo"] = s["moisture_hi"] = s["moisture_pct"]
    outs = common_outputs(s, params, "압착: 짜낸 액(물 + 용해 고형분)이 빠진다. 압착 후 수분은 내가 정한 값.",
                          "압착액 L: (물 − (1−c)L) ÷ (건물 − cL + 물 − (1−c)L) = 압착 후 수분",
                          "잔존율_후 = 잔존율_전 × (1 − (잃은 건물 ÷ 건물) × 배율)")
    return {"stream": s, "outputs": outs, "params": params, "notes": [f"압착액 {liquid:.2f} kg(용해 고형분 {lost_dm:.3f} kg)"],
            "warnings": warns, "side": [{"name": "압착액", "wet_kg": liquid, "dm_kg": lost_dm}],
            "losses": [{"what": "압착액으로 나간 용해 고형분", "dm_kg": lost_dm, "wet_kg": liquid}]}


def sim_mill(s_in, p, ctx) -> dict:
    hold, ev_hold = _pick(p, "holdup_pct", "m_holdup", "분쇄기 잔류 손실", "% 습량")
    params = [input_param("particle_mm", "입자 크기", p["particle_mm"], "mm"), ev_hold]
    f = 1 - hold / 100
    s = _set(s_in, dm=s_in["dm_kg"] * f, water=s_in["water_kg"] * f)
    for k in ("moisture_lo", "moisture_hi", "tpc_rel", "tpc_rel_lo", "tpc_rel_hi", "tdf_rel"):
        s[k] = s_in[k]
    lost = s_in["dm_kg"] - s["dm_kg"]
    # 잔류 손실은 성분이 같은 덩어리가 빠지는 것 → 농도 불변: 남은 비율은 질량 비율만큼 준다
    s["tpc_rel"] *= f
    s["tpc_rel_lo"] *= f
    s["tpc_rel_hi"] *= f
    s["tdf_rel"] *= f
    s["particle_mm"] = float(p["particle_mm"])
    outs = common_outputs(s, params, "분쇄: 입자 크기만 바뀌고 성분은 그대로, 기계 안에 조금 남는다(가정).")
    outs["tpc_ret"]["formula"]["model"] += " 잔류 손실분만큼 TPC 총량도 준다(농도는 그대로)."
    return {"stream": s, "outputs": outs, "params": params, "notes": [], "warnings": [], "side": [],
            "losses": [{"what": "분쇄기 잔류", "dm_kg": lost, "wet_kg": s_in["wet_kg"] - s["wet_kg"]}]}


def _strip_predict(r: dict, keep_charts: bool) -> dict:
    outs = []
    for o in r["outputs"]:
        o = dict(o)
        if not keep_charts:
            o.pop("chart", None)
            o.pop("sensitivity", None)
        outs.append(o)
    return {"method": r["method"], "byproduct": r["byproduct"], "inputs": r["inputs"], "stage": r.get("stage"),
            "outputs": outs, "summary": r["summary"], "disclaimer": r["disclaimer"]}


def dry_inputs(s_in: dict, p: dict) -> tuple[dict, list[dict], list[dict]]:
    """흐름과 단계 값 → predict 입력. (입력, 추가 근거, 경고)"""
    method = p["method"]
    inp = {k: p[k] for k in (s["key"] for s in P.INPUTS[method]) if p.get(k) is not None}
    inp["target_moisture"] = p["target_moisture"]
    extra, warns = [], []
    m_in = round(s_in["moisture_pct"], 2)
    spec = next(s for s in P.input_specs(method) if s["key"] == "initial_moisture")
    if not spec["min"] <= m_in <= spec["max"]:
        raise StepError(f"건조에 들어오는 수분 {m_in:g}%가 예측 입력 범위({spec['min']}–{spec['max']}%) 밖입니다. "
                        "앞 단계(압착 후 수분·원료 수분)를 확인하세요.")
    inp["initial_moisture"] = m_in
    if p.get("thickness_source") == "분쇄 입자 크기":
        if s_in.get("particle_mm"):
            tspec = next(s for s in P.INPUTS[method] if s["key"] == "thickness_mm")
            th = min(max(s_in["particle_mm"], tspec["min"]), tspec["max"])
            if th != s_in["particle_mm"]:
                warns.append({"kind": "info", "text": f"입자 크기 {s_in['particle_mm']:g} mm를 예측 입력 범위에 맞춰 {th:g} mm로 썼습니다."})
            inp["thickness_mm"] = th
            extra.append(sparam("m_particle_thickness", value=th, unit="mm"))
        else:
            warns.append({"kind": "info", "text": "두께 기준이 '분쇄 입자 크기'인데 앞에 분쇄 단계가 없어 층 두께 값을 썼습니다."})
    return inp, extra, warns


def sim_dry(s_in, p, ctx) -> dict:
    method = p["method"]
    inp, extra, warns = dry_inputs(s_in, p)
    try:
        r = P.predict(method, inp, ctx.get("byproduct"), ctx.get("project"), calib=ctx.get("calib"))
    except P.PredictError as ex:
        raise StepError(f"건조 예측을 하지 못했습니다: {ex}") from ex
    o = {x["key"]: x for x in r["outputs"]}
    mo, to, eo = o["moisture"], o["tpc"], o["energy"]
    dm = s_in["dm_kg"]
    s = _set(s_in, water=_water_for(dm, mo["value"]))
    s["moisture_lo"], s["moisture_hi"] = mo["low"], mo["high"]
    ret, rlo, rhi = to["value"] / 100, to["low"] / 100, to["high"] / 100
    s["tpc_rel"] = s_in["tpc_rel"] * ret
    s["tpc_rel_lo"] = s_in["tpc_rel_lo"] * rlo
    s["tpc_rel_hi"] = s_in["tpc_rel_hi"] * rhi
    removed = max(s_in["water_kg"] - s["water_kg"], 0.0)
    outs = {
        "mass": _out("mass", _r(s["wet_kg"]), params=mo["params"] + extra, formula="m = 건물 + 건물 × X_end",
                     model="건물은 그대로, 물만 건조 예측의 공정 끝 수분까지 준다."),
        "moisture": {**_out("moisture", mo["value"], mo["low"], mo["high"], basis="습량"),
                     "params": mo["params"] + extra, "formula": mo["formula"], "warnings": mo["warnings"] + warns,
                     "calibration": mo.get("calibration"), "value_label": mo.get("value_label")},
        "dm_yield": _out("dm_yield", _r(100 * s["dm_kg"] / s["feed_dm_kg"], 2), formula="건조는 건물을 줄이지 않는다",
                         model="건조 중 고형분 손실(분진 등)은 계산하지 않는다."),
        "tpc_ret": {**_out("tpc_ret", _r(s["tpc_rel"] * 100, 2), _r(s["tpc_rel_lo"] * 100, 2), _r(s["tpc_rel_hi"] * 100, 2)),
                    "params": to["params"], "formula": {"text": "잔존율_후 = 잔존율_전 × R_건조;  " + to["formula"]["text"],
                                                       "model": to["formula"]["model"]},
                    "warnings": to["warnings"], "calibration": to.get("calibration"),
                    "step_value": to["value"], "step_low": to["low"], "step_high": to["high"]},
    }
    tv = conc(s, "tpc")
    if tv is not None:
        outs["tpc"] = {**_out("tpc", _r(tv), _r(conc(s, "tpc", "tpc_rel_lo")), _r(conc(s, "tpc", "tpc_rel_hi")), basis="건량"),
                       "params": to["params"], "formula": {"text": "TPC = 원료 TPC × 잔존율 × 원료 건물 ÷ 지금 건물;  R_건조는 아래 식",
                                                          "model": to["formula"]["model"]},
                       "warnings": to["warnings"], "calibration": to.get("calibration")}
    if conc(s, "tdf") is not None:
        td = o["tdf"]
        outs["tdf"] = _out("tdf", _r(conc(s, "tdf")), params=td["params"], basis="건량",
                           formula="TDF_후 = TDF_전(건량 보존)", model=td["formula"]["model"])
    hl = mo.get("headline")
    if hl:
        outs["time_target"] = {**_out("time_target", hl["value"], hl["low"], hl["high"],
                                      status="ok" if hl["reachable"] else "unreachable", label=hl["label"] + " 시간"),
                               "params": mo["params"] + extra, "formula": mo["formula"], "warnings": mo["warnings"]}
    if eo.get("value") is not None:
        outs["energy"] = {**_out("energy", eo["value"], eo["low"], eo["high"]), "params": eo["params"], "formula": eo["formula"],
                          "warnings": eo["warnings"], "value_label": eo.get("value_label")}
        outs["energy_total"] = _out("energy_total", _r(eo["value"] * removed, 2), _r(eo["low"] * removed, 2), _r(eo["high"] * removed, 2),
                                    params=eo["params"], formula="E = 비에너지 × 제거한 물(이 흐름의 양)",
                                    model="비에너지는 설비 사양 기준(목표 수분까지). 이 흐름의 물 제거량을 곱한 값이다.")
    return {"stream": s, "outputs": outs, "params": mo["params"] + extra, "side": [], "losses": [],
            "notes": [f"제거한 물 {removed:.2f} kg"], "warnings": warns,
            "predict": _strip_predict(r, ctx.get("keep_charts", False)), "drying_method": method}


def sieve_yield(mesh: float) -> float:
    tbl = sorted((float(k), float(v)) for k, v in sv("s_yield_table").items())
    if mesh <= tbl[0][0]:
        return tbl[0][1]
    if mesh >= tbl[-1][0]:
        return tbl[-1][1]
    for (a, ya), (b, yb) in zip(tbl, tbl[1:]):
        if a <= mesh <= b:
            return ya + (yb - ya) * (mesh - a) / (b - a)
    return tbl[-1][1]


def sim_sieve(s_in, p, ctx) -> dict:
    mesh = float(p["mesh_um"])
    warns = []
    if p.get("yield_pct") is not None:
        y = float(p["yield_pct"])
        ev_y = input_param("yield_pct", "체 통과 수율", y, "%")
    else:
        y = sieve_yield(mesh)
        ev_y = sparam("s_yield_table")
        rng = ev_y["evidence"]["validity"].get("mesh_um")
        if rng and not rng[0] <= mesh <= rng[1]:
            warns.append({"kind": "extrapolation", "input": "mesh_um", "range": rng,
                          "text": f"외삽 — 근거 범위 밖: 체 눈 {mesh:g} µm는 가정 표 범위 {rng[0]}–{rng[1]} µm 밖입니다."})
    hold, ev_h = _pick(p, "holdup_pct", "s_holdup", "회수 손실", "% 습량")
    params = [input_param("mesh_um", "체 눈 크기", mesh, "µm"), ev_y, ev_h, sparam("s_no_fractionation")]
    f = y / 100 * (1 - hold / 100)
    s = _set(s_in, dm=s_in["dm_kg"] * f, water=s_in["water_kg"] * f)
    for k in ("moisture_lo", "moisture_hi"):
        s[k] = s_in[k]
    for k in ("tpc_rel", "tpc_rel_lo", "tpc_rel_hi", "tdf_rel"):
        s[k] = s_in[k] * f
    over_dm = s_in["dm_kg"] * (1 - y / 100)
    over_wet = s_in["wet_kg"] * (1 - y / 100)
    hold_dm = s_in["dm_kg"] * y / 100 * hold / 100
    outs = common_outputs(s, params, "체분리: 체를 통과한 분말만 남는다. 성분 농도는 같다고 본다(가정).")
    outs["tpc_ret"]["formula"]["model"] += " 잔존율은 '원료 TPC 총량 대비 이 분말에 남은 TPC'라서 체 위 잔류분만큼 준다."
    outs["sieve_yield"] = _out("sieve_yield", _r(y, 2), params=[ev_y],
                               formula="통과 수율 = 체 통과분 ÷ 들어온 양", model="실측을 넣으면 그 값, 아니면 체 눈 크기별 가정 표(선형 보간).",
                               warnings=warns)
    return {"stream": s, "outputs": outs, "params": params, "notes": [], "warnings": warns,
            "side": [{"name": "체 위 잔류분", "wet_kg": over_wet, "dm_kg": over_dm}],
            "losses": [{"what": "체 위 잔류분(분리)", "dm_kg": over_dm, "wet_kg": over_wet},
                       {"what": "회수 손실", "dm_kg": hold_dm, "wet_kg": s_in["wet_kg"] * y / 100 * hold / 100}]}


def extract_yield(etoh: float, temp_c: float, time_min: float, ymax=None, opt=None, width=None, k_ref=None, ea=None) -> float:
    """Y = Ymax · exp(−((c − c_opt)/σ)²/2) · (1 − e^(−k(T)·t)),  k(T) = k_ref·exp(−Ea/R(1/T − 1/323.15))"""
    ymax = sv("e_ymax") if ymax is None else ymax
    opt = sv("e_etoh_opt") if opt is None else opt
    width = sv("e_etoh_width") if width is None else width
    k_ref = sv("e_k_ref") if k_ref is None else k_ref
    ea = sv("e_ea") if ea is None else ea
    f_c = math.exp(-0.5 * ((etoh - opt) / width) ** 2)
    k = P.arrhenius(k_ref, ea * 1000, temp_c, 50.0)
    return ymax * f_c * (1 - math.exp(-k * time_min))


def sim_extract(s_in, p, ctx) -> dict:
    c, t, tm, ratio = float(p["ethanol_pct"]), float(p["temp_c"]), float(p["time_min"]), float(p["ratio_ml_g"])
    params = [input_param("ethanol_pct", "에탄올 농도", c, "% v/v"), input_param("temp_c", "추출 온도", t, "℃"),
              input_param("time_min", "추출 시간", tm, "min"), input_param("ratio_ml_g", "용매 비율", ratio, "mL/g"),
              sparam("e_ymax"), sparam("e_etoh_opt"), sparam("e_etoh_width"), sparam("e_k_ref"), sparam("e_ea"),
              sparam("e_solids"), sparam("e_min_ratio")]
    warns = []
    y = extract_yield(c, t, tm)
    corners = []
    for ym in _band("e_ymax"):
        for w in _band("e_etoh_width"):
            for kr in _band("e_k_ref"):
                for e in _band("e_ea"):
                    corners.append(extract_yield(c, t, tm, ym, None, w, kr, e))
    ylo, yhi = min(corners + [y]), max(corners + [y])
    vr = registry()["parameters"]["e_k_ref"]["evidence"]["validity"]["temp_c"]
    if not vr[0] <= t <= vr[1]:
        warns.append({"kind": "extrapolation", "input": "temp_c", "range": vr,
                      "text": f"외삽 — 근거 범위 밖: 추출 온도 {t:g} ℃는 가정 범위 {vr[0]}–{vr[1]} ℃ 밖입니다."})
    if ratio < sv("e_min_ratio"):
        warns.append({"kind": "info", "text": f"용매 비율 {ratio:g} mL/g가 {sv('e_min_ratio'):g} mL/g보다 적어 포화로 수율이 더 낮을 수 있습니다(계산에 반영 안 함)."})
    warns.append({"kind": "info", "text": "추출 계수는 모두 가정입니다. 내 추출 실측(TPC 추출 수율)을 넣고 비교하세요."})
    solvent, acid = p.get("solvent"), p.get("acid")
    if solvent == "물" and c > 0:
        warns.append({"kind": "info", "text": f"용매 종류가 '물'인데 에탄올 농도가 {c:g}%입니다. 물 추출이면 에탄올 농도를 0으로 두세요(계산은 에탄올 농도로 함)."})
    elif solvent and solvent not in ("에탄올 수용액", "에탄올", "물"):
        warns.append({"kind": "info", "text": f"용매 종류 '{solvent}'는 기록만 합니다 — 이 추출 모델은 에탄올 수용액(에탄올 농도)만 계산하므로 "
                                              "이 예측을 그 용매의 결과로 보지 마세요."})
    if acid and acid != "없음":
        warns.append({"kind": "info", "text": f"산 종류 '{acid}'는 기록·통계 분석용입니다 — 산에 따른 수율 차이를 뒷받침하는 근거(문헌·내 실측 보정)가 "
                                              "없어 예측에는 넣지 않습니다. 산별 차이는 통계 분석(회귀·t검정)으로 보세요."})
    k = P.arrhenius(sv("e_k_ref"), sv("e_ea") * 1000, t, 50.0)
    frac_eq = 1 - math.exp(-k * tm)
    sol = sv("e_solids") / 100 * frac_eq * math.exp(-0.5 * ((c - sv("e_etoh_opt")) / sv("e_etoh_width")) ** 2)
    sol = min(sol, 0.6)
    dm_in = s_in["dm_kg"]
    ext_dm = dm_in * sol
    tpc_in = conc(s_in, "tpc")
    ext_tpc = None if tpc_in is None else tpc_in * y / 100  # 투입 분말 1 g(건량)당 mg
    s = _set(s_in, dm=dm_in - ext_dm, water=s_in["water_kg"] * (dm_in - ext_dm) / dm_in if dm_in else 0.0)  # 잔사 수분은 용매를 뺀 기준으로 그대로 둔다
    s["tpc_rel"] = s_in["tpc_rel"] * (1 - y / 100)
    s["tpc_rel_lo"] = s_in["tpc_rel_lo"] * (1 - yhi / 100)
    s["tpc_rel_hi"] = s_in["tpc_rel_hi"] * (1 - ylo / 100)
    s["tdf_rel"] = s_in["tdf_rel"]
    s["moisture_lo"] = s["moisture_hi"] = s["moisture_pct"]
    model = ("1차 접근식 Y(t) = Y_eq(1 − e^(−kt)), Y_eq = Ymax·exp(−½((c − c_opt)/σ)²), k = k_ref·exp(−Ea/R(1/T − 1/T_ref)). "
             "용매 비율·입자 크기·교반 효과와 고온 장시간의 분해는 계산하지 않는다. 모든 계수가 가정이다.")
    outs = common_outputs(s, params, "추출 뒤 남은 고형분(잔사) 흐름. 추출물은 따로 보인다.")
    outs["tpc_ret"]["formula"]["model"] = "잔사에 남은 TPC(원료 대비). " + model
    outs["tpc_extract_yield"] = _out("tpc_extract_yield", _r(y, 2), _r(ylo, 2), _r(yhi, 2), params=params,
                                     formula="Y = Ymax·exp(−½((c − c_opt)/σ)²)·(1 − e^(−k(T)·t))", model=model, warnings=warns)
    if ext_tpc is not None:
        outs["extract_tpc"] = _out("extract_tpc", _r(ext_tpc, 3), _r(tpc_in * ylo / 100, 3), _r(tpc_in * yhi / 100, 3), params=params,
                                   basis="투입 분말 건량", formula="추출 TPC = 투입 분말 TPC × Y", model=model, warnings=warns)
    outs["extract_solids"] = _out("extract_solids", _r(sol * 100, 2), params=params, formula="고형분 수율 = e_solids × f(c) × (1 − e^(−kt))",
                                  model="함께 녹아 나오는 고형분(가정).", warnings=warns)
    return {"stream": s, "outputs": outs, "params": params, "notes": [], "warnings": warns,
            "side": [{"name": "추출물(용매 제외 고형분)", "wet_kg": ext_dm, "dm_kg": ext_dm,
                      "tpc_mg": None if ext_tpc is None else ext_tpc * dm_in * 1000}],
            "losses": [{"what": "추출물로 분리된 고형분", "dm_kg": ext_dm, "wet_kg": ext_dm}]}


def sim_store(s_in, p, ctx) -> dict:
    pk, days, t, rh = p["package"], float(p["days"]), float(p["temp_c"]), float(p["rh"])
    kp = sv("st_k_pack")[pk]
    xe = P.gab_xe(rh / 100)
    x0 = P.wb_to_db(s_in["moisture_pct"])
    params = [input_param("package", "포장", pk, ""), input_param("days", "저장 기간", days, "일"),
              input_param("temp_c", "저장 온도", t, "℃"), input_param("rh", "저장 습도", rh, "%RH"),
              sparam("st_k_pack"), sparam("st_gab"), sparam("st_tpc_k25"), sparam("st_q10")]
    x = xe + (x0 - xe) * math.exp(-kp * days)
    b = _band("st_k_pack")
    xs = [xe + (x0 - xe) * math.exp(-kp * f * days) for f in b]
    s = _set(s_in, water=_water_for(s_in["dm_kg"], P.db_to_wb(x)))
    s["moisture_lo"] = min(P.db_to_wb(v) for v in xs + [x])
    s["moisture_hi"] = max(P.db_to_wb(v) for v in xs + [x])
    k25, q10 = sv("st_tpc_k25"), sv("st_q10")
    k = k25 * q10 ** ((t - 25) / 10)
    kb, qb = _band("st_tpc_k25"), _band("st_q10")
    ks = [a * q ** ((t - 25) / 10) for a in kb for q in qb]
    s["tpc_rel"] = s_in["tpc_rel"] * math.exp(-k * days)
    s["tpc_rel_lo"] = s_in["tpc_rel_lo"] * math.exp(-max(ks) * days)
    s["tpc_rel_hi"] = s_in["tpc_rel_hi"] * math.exp(-min(ks) * days)
    s["tdf_rel"] = s_in["tdf_rel"]
    warns = []
    vr = registry()["parameters"]["st_tpc_k25"]["evidence"]["validity"]["temp_c"]
    if not vr[0] <= t <= vr[1]:
        warns.append({"kind": "extrapolation", "input": "temp_c", "range": vr,
                      "text": f"외삽 — 근거 범위 밖: 저장 온도 {t:g} ℃는 가정 범위 {vr[0]}–{vr[1]} ℃ 밖입니다."})
    gv = P.evidence("gab")["validity"].get("byproduct")
    if gv and ctx.get("byproduct") and ctx["byproduct"] != gv:
        warns.append({"kind": "byproduct", "text": f"GAB 상수는 {gv} 자료입니다. '{ctx['byproduct']}'에는 빌려 써서 오차가 클 수 있습니다."})
    outs = common_outputs(s, params, "저장: 수분이 저장 습도의 평형 수분(GAB)으로 다가가고, TPC가 1차로 준다(속도 가정).",
                          "X(t) = Xe(RH) + (X0 − Xe)·e^(−k_포장·t)", "잔존율_후 = 잔존율_전 × e^(−k25·Q10^((T−25)/10)·t)")
    outs["moisture"]["warnings"] = warns
    outs["tpc_ret"]["warnings"] = warns
    return {"stream": s, "outputs": outs, "params": params, "notes": [f"저장 습도 {rh:g}%의 평형 수분 {P.db_to_wb(xe):.1f}%"],
            "warnings": warns, "side": [], "losses": []}


SIMS = {"feed": sim_feed, "wash": sim_wash, "press": sim_press, "mill": sim_mill, "dry": sim_dry,
        "sieve": sim_sieve, "extract": sim_extract, "store": sim_store}


def simulate_step(step_type: str, stream: dict | None, params: dict, ctx: dict) -> dict:
    if step_type != "feed" and stream is None:
        raise StepError("흐름의 첫 단계는 '원료 투입'이어야 합니다. 맨 앞에 원료 투입 단계를 넣으세요.")
    return SIMS[step_type](stream, params, ctx)


def drying_method_label(params: dict) -> str | None:
    return drying.canonical(params.get("method")) if params else None
