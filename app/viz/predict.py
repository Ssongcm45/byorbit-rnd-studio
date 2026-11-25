"""건조 결과 예측 — 온도·시간·압력 등을 바꾸면 수분·폴리페놀·식이섬유·에너지 예상값이 바로 바뀐다.

원칙
- 예측에 쓰는 모든 수는 predict_sources.json(문헌·가정), 사용자 DB(실측), <data_home>/config/equipment.json(설비 사양)에서만 온다.
- 결과마다 식, 파라미터 값, 근거(종류·인용·DOI·확인 여부·읽은 곳·유효 범위)를 함께 돌려준다.
- 근거 범위 밖 입력은 '외삽' 경고를 붙인다. 시료는 '시료 n'으로만 — 로트·공급처·시료번호를 내보내지 않는다.
- 이것은 모델 추정이다. 측정값이 아니다.
"""
from __future__ import annotations

import json
import math
import statistics
import time
from datetime import date
from pathlib import Path

from .. import config, db
from . import drying

R_GAS = 8.314462618  # J/(mol·K)
M_WATER = 0.01801528  # kg/mol
SOURCES_FILE = Path(__file__).with_name("predict_sources.json")
ORDER = drying.ORDER
DEFAULT_BYPRODUCT = "사과박"
DISCLAIMER = ("예측값은 문헌 상수·가정·실측 보정으로 계산한 모델 추정치입니다. 측정값이 아니며, "
              "근거 범위 밖(외삽)에서는 오차가 커집니다. 중요한 결정 전에는 실제 시험으로 확인하세요.")
EQUIP_DEFAULT_NOTE = "일반 사양(가정) — 내 설비 값으로 바꾸세요"

# ---------------------------------------------------------------- 근거 목록

_reg_cache: dict = {"mtime": None, "data": None}


def registry() -> dict:
    m = SOURCES_FILE.stat().st_mtime
    if _reg_cache["mtime"] != m:
        _reg_cache["data"] = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        _reg_cache["mtime"] = m
        _fits.clear()
    return _reg_cache["data"]


def pv(pid: str):
    """파라미터 값"""
    return registry()["parameters"][pid]["value"]


def evidence(pid: str) -> dict:
    """파라미터의 근거를 펼친다 → {type, citation, doi, verified, verified_at, locator, note, validity, url}"""
    p = registry()["parameters"][pid]
    ev = dict(p["evidence"])
    src = registry()["sources"].get(ev.get("source") or "")
    out = {"type": ev["type"], "citation": None, "doi": None, "verified": False, "verified_at": None, "url": None,
           "locator": ev.get("locator"), "note": ev.get("note"), "validity": ev.get("validity") or {}}
    if src:
        out.update({"citation": src["citation"], "doi": src["doi"], "verified": bool(src["verified"]),
                    "verified_at": src["verified_at"], "url": src.get("url"), "source_id": ev["source"],
                    "read": src.get("read")})
    return out


REFERENCE_ONLY = {"ha_ea_paper", "ha_ea_araujo", "lab_energy_araujo"}  # 대조·불확실 폭용 — 외삽 판정에서 뺀다


def param(pid: str, value=None, label: str | None = None, unit: str | None = None, band=None) -> dict:
    p = registry()["parameters"][pid]
    out = {"key": pid, "label": label or p["label"], "value": p["value"] if value is None else value,
           "unit": unit or p["unit"], "evidence": evidence(pid)}
    if pid in REFERENCE_ONLY:
        out["role"] = "reference"
    b = band if band is not None else p.get("band")
    if b is not None:
        out["band"] = b
    return out


def derived(key: str, label: str, value, unit: str, from_pids: list[str], how: str, validity: dict | None = None) -> dict:
    """문헌 값에서 이 앱이 계산한 유도값. 근거 종류는 원래 문헌을 따른다(어떻게 계산했는지 note에 적는다)."""
    ev = evidence(from_pids[0])
    ev = {**ev, "note": how + (" — " + ev["note"] if ev.get("note") else ""), "derived": True,
          "validity": validity if validity is not None else ev.get("validity", {})}
    return {"key": key, "label": label, "value": value, "unit": unit, "evidence": ev}


# ---------------------------------------------------------------- 물성·기본식

def arrhenius(k_ref: float, ea_j: float, t_c: float, tref_c: float) -> float:
    """k(T) = k_ref · exp(−Ea/R · (1/T − 1/T_ref))"""
    return k_ref * math.exp(-ea_j / R_GAS * (1.0 / (t_c + 273.15) - 1.0 / (tref_c + 273.15)))


def fit_arrhenius(points: list[tuple[float, float]], tref_c: float) -> dict:
    """ln k = a + b/T 최소제곱 → {k_ref(T_ref), ea_j, rmse(ln k), residuals}"""
    xs = [1.0 / (t + 273.15) for t, _ in points]
    ys = [math.log(k) for _, k in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    a = my - b * mx
    res = [y - (a + b * x) for x, y in zip(xs, ys)]
    rmse = math.sqrt(sum(r * r for r in res) / max(n - 2, 1))
    return {"k_ref": math.exp(a + b / (tref_c + 273.15)), "ea_j": -b * R_GAS, "tref_c": tref_c, "rmse": rmse,
            "residuals": [{"temp_c": t, "k": k, "ln_resid": round(r, 4)} for (t, k), r in zip(points, res)],
            "range": [min(t for t, _ in points), max(t for t, _ in points)]}


def wb_to_db(w_pct: float) -> float:
    w = min(max(w_pct, 0.0), 99.0) / 100.0
    return w / (1.0 - w)


def db_to_wb(x: float) -> float:
    return 100.0 * x / (1.0 + x)


def gab_xe(aw: float) -> float:
    g = pv("gab")
    m0, c, k = g["m0"], g["C"], g["K"]
    aw = min(max(aw, 0.0), 0.95)
    return m0 * c * k * aw / ((1 - k * aw) * (1 - k * aw + c * k * aw))


def heated_air_aw(t_c: float, amb_t: float | None = None, amb_rh: float | None = None) -> float:
    """외기를 t_c까지 가열한 공기의 상대습도(= 평형 수분활성도)"""
    a = pv("a_ambient")
    amb_t = a["temp_c"] if amb_t is None else amb_t
    amb_rh = a["rh"] if amb_rh is None else amb_rh
    pw = amb_rh / 100.0 * drying.p_vap(amb_t + 273.15)
    return min(0.95, pw / drying.p_vap(max(t_c, amb_t) + 273.15))


def dh_sub_j_per_kg(t_k: float) -> float:
    """Murphy & Koop 얼음 증기압 식을 Clausius–Clapeyron으로 미분: ΔH = R·T²·d(ln p)/dT"""
    dlnp = 5723.265 / t_k ** 2 + 3.53068 / t_k - 0.00728332
    return R_GAS * t_k ** 2 * dlnp / M_WATER


# ---------------------------------------------------------------- 문헌 표에서 유도한 속도상수

_fits: dict = {}


def dry_fit() -> dict:
    """Llavata 2022 표 1 → Lewis k = −ln((X_f − X_e)/(X_0 − X_e))/t, 각 공기 온도에서. → Arrhenius 맞춤"""
    if "dry" not in _fits:
        x0, xf = pv("ha_x0_ref"), pv("ha_xf_ref")
        pts = []
        for t, minutes in sorted((float(k), v) for k, v in pv("ha_time_table").items()):
            xe = gab_xe(heated_air_aw(t))
            pts.append((t, -math.log((xf - xe) / (x0 - xe)) / (minutes / 60.0)))
        _fits["dry"] = fit_arrhenius(pts, 60.0)
    return _fits["dry"]


def tpc_fit() -> dict:
    """Llavata 2022 표 2 잔존율 R과 표 1 시간 t → 겉보기 1차 k = −ln(R)/t → Arrhenius 맞춤"""
    if "tpc" not in _fits:
        times = pv("ha_time_table")
        pts = [(float(t), -math.log(r / 100.0) / (times[t] / 60.0)) for t, r in pv("tpc_retention_table").items()]
        _fits["tpc"] = fit_arrhenius(sorted(pts), 60.0)
    return _fits["tpc"]


def k_dry_lit(t_c: float) -> float:
    f = dry_fit()
    return arrhenius(f["k_ref"], f["ea_j"], t_c, f["tref_c"])


def k_tpc_lit(t_c: float) -> float:
    f = tpc_fit()
    return arrhenius(f["k_ref"], f["ea_j"], t_c, f["tref_c"])


def _ea_band_factor(t_c: float, fit: dict) -> tuple[float, float]:
    """문헌 온도 범위 밖이면 Ea를 다른 문헌값(23.9–38.21 kJ/mol)으로 바꿨을 때의 k 배율 폭"""
    lo_t, hi_t = fit["range"]
    if lo_t <= t_c <= hi_t:
        return 1.0, 1.0
    edge = lo_t if t_c < lo_t else hi_t
    base = arrhenius(1.0, fit["ea_j"], t_c, edge)
    alts = [arrhenius(1.0, pv(p) * 1000, t_c, edge) / base for p in ("ha_ea_paper", "ha_ea_araujo")]
    return min(alts + [1.0]), max(alts + [1.0])


# ---------------------------------------------------------------- 입력 정의

COMMON_MOIST = [
    {"key": "initial_moisture", "label": "초기 수분", "unit": "% 습량", "min": 40, "max": 95, "step": 0.5, "default": 78.0},
    {"key": "target_moisture", "label": "목표 수분", "unit": "% 습량", "min": 2, "max": 20, "step": 0.5, "default": 8.0},
]
INPUTS: dict[str, list[dict]] = {
    "열풍건조": [
        {"key": "temp_c", "label": "열풍 온도", "unit": "℃", "min": 30, "max": 130, "step": 1, "default": 60},
        {"key": "time_h", "label": "건조 시간", "unit": "h", "min": 0.5, "max": 48, "step": 0.5, "default": 12},
        {"key": "air_velocity_ms", "label": "풍속", "unit": "m/s", "min": 0.3, "max": 3, "step": 0.1, "default": 0.9},
        {"key": "thickness_mm", "label": "층 두께", "unit": "mm", "min": 1, "max": 30, "step": 0.5, "default": 3},
    ],
    "동결건조": [
        {"key": "temp_c", "label": "선반 온도", "unit": "℃", "min": -30, "max": 50, "step": 1, "default": 20},
        {"key": "pressure_pa", "label": "챔버 압력", "unit": "Pa", "min": 5, "max": 100, "step": 1, "default": 20},
        {"key": "time_h", "label": "건조 시간", "unit": "h", "min": 4, "max": 96, "step": 1, "default": 48},
        {"key": "thickness_mm", "label": "층 두께", "unit": "mm", "min": 2, "max": 30, "step": 0.5, "default": 10},
    ],
    "진공건조": [
        {"key": "temp_c", "label": "선반 온도", "unit": "℃", "min": 30, "max": 90, "step": 1, "default": 60},
        {"key": "pressure_pa", "label": "챔버 압력", "unit": "Pa", "min": 1000, "max": 30000, "step": 500, "default": 8000},
        {"key": "time_h", "label": "건조 시간", "unit": "h", "min": 1, "max": 48, "step": 0.5, "default": 10},
        {"key": "thickness_mm", "label": "층 두께", "unit": "mm", "min": 1, "max": 30, "step": 0.5, "default": 3},
    ],
    "분무건조": [
        {"key": "temp_c", "label": "입구 온도", "unit": "℃", "min": 120, "max": 220, "step": 1, "default": 180},
        {"key": "outlet_c", "label": "출구 온도", "unit": "℃", "min": 60, "max": 100, "step": 1, "default": 80},
        {"key": "residence_s", "label": "체류 시간", "unit": "s", "min": 1, "max": 60, "step": 1, "default": 15},
    ],
    "자연건조": [
        {"key": "temp_c", "label": "기온(품온)", "unit": "℃", "min": 5, "max": 45, "step": 1, "default": 25},
        {"key": "time_h", "label": "건조 시간", "unit": "h", "min": 12, "max": 336, "step": 6, "default": 96},
        {"key": "air_velocity_ms", "label": "바람", "unit": "m/s", "min": 0.3, "max": 5, "step": 0.1, "default": 1.0},
        {"key": "rh", "label": "상대습도", "unit": "%", "min": 20, "max": 95, "step": 1, "default": 60},
        {"key": "thickness_mm", "label": "층 두께", "unit": "mm", "min": 1, "max": 30, "step": 0.5, "default": 5},
    ],
}
OUTPUTS = [
    {"key": "moisture", "label": "수분·목표 수분 도달 시간"},
    {"key": "tpc", "label": "총폴리페놀(TPC) 잔존율"},
    {"key": "tdf", "label": "총식이섬유(TDF)"},
    {"key": "color", "label": "색 변화(ΔE)·갈변"},
    {"key": "energy", "label": "비에너지 소비"},
]


class PredictError(ValueError):
    pass


def method_or_error(method: str | None) -> str:
    m = drying.canonical(method) if method else "열풍건조"
    if m not in INPUTS:
        raise PredictError(f"'{method}'는 예측할 수 없는 건조 방식입니다. {', '.join(ORDER)} 중에서 고르세요.")
    return m


def input_specs(method: str, measured: dict | None = None) -> list[dict]:
    specs = [dict(s) for s in INPUTS[method]] + [dict(s) for s in COMMON_MOIST]
    if method == "분무건조":
        for s in specs:
            if s["key"] == "initial_moisture":
                s.update({"label": "공급액 수분", "default": 85.0, "max": 98})
    if measured and measured.get("initial_moisture") and method != "분무건조":
        for s in specs:
            if s["key"] == "initial_moisture":
                s["default"] = round(measured["initial_moisture"]["value"], 1)
                s["default_from"] = f"실측(생시료 수분, n={measured['initial_moisture']['n']})"
    return specs


def clean_inputs(method: str, raw: dict | None, measured: dict | None = None) -> dict:
    raw = raw or {}
    out = {}
    for s in input_specs(method, measured):
        v = raw.get(s["key"], s["default"])
        try:
            v = float(v)
        except (TypeError, ValueError) as ex:
            raise PredictError(f"'{s['label']}' 값이 숫자가 아닙니다. {s['min']}–{s['max']} {s['unit']} 사이 숫자를 넣으세요.") from ex
        if not math.isfinite(v) or v < s["min"] or v > s["max"]:
            raise PredictError(f"'{s['label']}' {v:g} {s['unit']}는 입력 범위 밖입니다. "
                               f"{s['min']}–{s['max']} {s['unit']} 사이로 넣으세요.")
        out[s["key"]] = v
    if method != "분무건조" and out["target_moisture"] >= out["initial_moisture"]:
        raise PredictError("목표 수분은 초기 수분보다 낮아야 합니다. 목표 수분을 낮추거나 초기 수분을 확인하세요.")
    return out


# ---------------------------------------------------------------- 설비 사양

EQUIP_SPEC: dict[str, list[dict]] = {
    "열풍건조": [
        {"key": "heater_kw", "label": "히터 출력", "unit": "kW", "min": 0.1, "max": 500, "default": 9.0},
        {"key": "fan_kw", "label": "송풍기 출력", "unit": "kW", "min": 0, "max": 100, "default": 0.75},
        {"key": "duty", "label": "히터 평균 가동률", "unit": "0–1", "min": 0.05, "max": 1, "default": 0.7},
        {"key": "batch_wet_kg", "label": "1회 투입량(습량)", "unit": "kg", "min": 0.1, "max": 10000, "default": 30.0},
    ],
    "동결건조": [
        {"key": "refrigeration_kw", "label": "냉동기 출력", "unit": "kW", "min": 0.1, "max": 500, "default": 3.0},
        {"key": "vacuum_pump_kw", "label": "진공펌프 출력", "unit": "kW", "min": 0, "max": 100, "default": 0.75},
        {"key": "heater_kw", "label": "선반 가열 출력", "unit": "kW", "min": 0, "max": 200, "default": 2.0},
        {"key": "duty", "label": "평균 가동률", "unit": "0–1", "min": 0.05, "max": 1, "default": 0.8},
        {"key": "batch_wet_kg", "label": "1회 투입량(습량)", "unit": "kg", "min": 0.1, "max": 5000, "default": 10.0},
        {"key": "condenser_kg", "label": "콘덴서 용량(얼음)", "unit": "kg", "min": 0.1, "max": 5000, "default": 15.0},
        {"key": "pressure_min_pa", "label": "최저 도달 압력", "unit": "Pa", "min": 0.1, "max": 100, "default": 5.0},
    ],
    "진공건조": [
        {"key": "heater_kw", "label": "선반 가열 출력", "unit": "kW", "min": 0.1, "max": 300, "default": 4.0},
        {"key": "vacuum_pump_kw", "label": "진공펌프 출력", "unit": "kW", "min": 0, "max": 100, "default": 1.5},
        {"key": "duty", "label": "평균 가동률", "unit": "0–1", "min": 0.05, "max": 1, "default": 0.7},
        {"key": "batch_wet_kg", "label": "1회 투입량(습량)", "unit": "kg", "min": 0.1, "max": 5000, "default": 15.0},
    ],
    "분무건조": [
        {"key": "heater_kw", "label": "입구 공기 히터 출력", "unit": "kW", "min": 0.5, "max": 5000, "default": 18.0},
        {"key": "fan_kw", "label": "송풍기·분무기 출력", "unit": "kW", "min": 0, "max": 500, "default": 1.5},
        {"key": "evap_kg_h", "label": "수분 증발 능력", "unit": "kg/h", "min": 0.1, "max": 10000, "default": 10.0},
    ],
    "자연건조": [
        {"key": "fan_kw", "label": "보조 송풍기 출력(없으면 0)", "unit": "kW", "min": 0, "max": 50, "default": 0.0},
        {"key": "batch_wet_kg", "label": "1회 펼치는 양(습량)", "unit": "kg", "min": 0.1, "max": 10000, "default": 30.0},
    ],
}


def equipment_file() -> Path:
    return config.path("config", "equipment.json")


def _equip_defaults() -> dict:
    return {"values": {m: {s["key"]: s["default"] for s in specs} for m, specs in EQUIP_SPEC.items()}, "edited": {}}


def load_equipment() -> dict:
    """{values: {방식: {키: 값}}, edited: {방식: {키: 날짜}}} — 파일이 없으면 기본값으로 만든다."""
    f = equipment_file()
    data = _equip_defaults()
    if f.exists():
        try:
            saved = json.loads(f.read_text(encoding="utf-8"))
            for m, vals in (saved.get("values") or {}).items():
                if m in data["values"]:
                    for k, v in vals.items():
                        if k in data["values"][m] and isinstance(v, (int, float)):
                            data["values"][m][k] = float(v)
            data["edited"] = {m: dict(v) for m, v in (saved.get("edited") or {}).items() if m in EQUIP_SPEC}
        except (OSError, json.JSONDecodeError):
            pass
    else:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({**data, "note": EQUIP_DEFAULT_NOTE}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
    return data


def equipment_view(method: str | None = None) -> dict:
    data = load_equipment()
    out = {}
    for m, specs in EQUIP_SPEC.items():
        if method and m != method:
            continue
        out[m] = [{**s, "value": data["values"][m][s["key"]], "edited_at": data["edited"].get(m, {}).get(s["key"]),
                   "evidence": _equip_evidence(m, s["key"], data)} for s in specs]
    return {"equipment": out, "file": "config/equipment.json", "note": EQUIP_DEFAULT_NOTE}


def save_equipment(method: str, values: dict) -> dict:
    m = method_or_error(method)
    specs = {s["key"]: s for s in EQUIP_SPEC[m]}
    if not values:
        raise PredictError("바꿀 설비 값을 넣으세요. 예: {\"heater_kw\": 12}")
    data = load_equipment()
    today = date.today().isoformat()
    for k, v in values.items():
        if k not in specs:
            raise PredictError(f"'{k}'는 {m} 설비 항목이 아닙니다. 가능한 항목: {', '.join(specs)}")
        s = specs[k]
        try:
            v = float(v)
        except (TypeError, ValueError) as ex:
            raise PredictError(f"'{s['label']}' 값이 숫자가 아닙니다. {s['min']}–{s['max']} {s['unit']} 사이로 넣으세요.") from ex
        if not math.isfinite(v) or v < s["min"] or v > s["max"]:
            raise PredictError(f"'{s['label']}' {v:g}은 범위 밖입니다. {s['min']}–{s['max']} {s['unit']} 사이로 넣으세요.")
        data["values"][m][k] = v
        data["edited"].setdefault(m, {})[k] = today
    f = equipment_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({**data, "note": EQUIP_DEFAULT_NOTE}, ensure_ascii=False, indent=2), encoding="utf-8")
    return equipment_view(m)


def _equip_evidence(method: str, key: str, data: dict) -> dict:
    when = data["edited"].get(method, {}).get(key)
    return {"type": "equipment", "citation": None, "doi": None, "verified": False, "verified_at": when,
            "locator": "config/equipment.json", "validity": {},
            "note": f"내 설비 사양(사용자 입력, {when})" if when else EQUIP_DEFAULT_NOTE}


def equip_params(method: str, keys: list[str], data: dict) -> list[dict]:
    specs = {s["key"]: s for s in EQUIP_SPEC[method]}
    return [{"key": f"eq_{k}", "label": specs[k]["label"], "value": data["values"][method][k], "unit": specs[k]["unit"],
             "evidence": _equip_evidence(method, k, data)} for k in keys]


# ---------------------------------------------------------------- 실측(사용자 DB)

_meas_cache: dict = {}


def _q_rows(byproduct: str | None, project: str | None) -> list[dict]:
    where, params = ["m.value IS NOT NULL", "m.sample_id IS NOT NULL"], []
    if byproduct:
        w, p = drying._byproduct_clause(byproduct)
        where.append(w)
        params += p
    if project:
        where.append("m.sample_id IN (SELECT entity_id FROM project_item pi JOIN project pr ON pr.project_id=pi.project_id "
                     "WHERE pr.name=? AND pi.entity_type='sample') OR m.doc_id IN (SELECT entity_id FROM project_item pi "
                     "JOIN project pr ON pr.project_id=pi.project_id WHERE pr.name=? AND pi.entity_type='document')")
        where[-1] = "(" + where[-1] + ")"
        params += [project, project]
    tw = []
    for t in ("폴리페놀", "식이섬유", "수분"):
        w, p = drying._target_clause(t)
        tw.append(w)
        params += p
    where.append("(" + " OR ".join(tw) + ")")
    return db.rows(
        "SELECT m.sample_id, m.target_text, m.value, m.unit_text, m.basis, s.pretreatment_text, pc.pref_label_ko AS pre_concept "
        "FROM measurement m JOIN sample s ON s.sample_id=m.sample_id "
        "LEFT JOIN concept pc ON pc.concept_id=s.pretreatment_concept_id "
        "WHERE " + " AND ".join(where) + " ORDER BY m.created_at, m.rowid LIMIT 2000", params)


def _kind(target: str, unit: str) -> str | None:
    t = (target or "").replace(" ", "").lower()
    u = (unit or "").lower()
    if "폴리페놀" in t or "tpc" in t or "phenol" in t:
        return "tpc" if "gae" in u else None
    if "식이섬유" in t or "tdf" in t or "fiber" in t or "fibre" in t:
        return "tdf" if "100" in u or "%" in u else None
    if "수분" in t or "moisture" in t:
        if "%" not in u:
            return None
        return "moist_init" if any(w in t for w in ("생", "원료", "건조전", "건조 전", "raw", "initial", "fresh")) else "moist_final"
    return None


def measured(byproduct: str | None, project: str | None = None) -> dict:
    """시료별 실측 → {samples:[{alias, method, temp_c, time_h, tpc, tdf, moist_init, moist_final}], ...}.
    측정값 수가 바뀌면 다시 읽고, 아니면 캐시를 쓴다(슬라이더 응답 속도)."""
    stamp = db.one("SELECT COUNT(*) AS n, MAX(created_at) AS t, MAX(rowid) AS r FROM measurement")
    key = (byproduct, project, stamp["n"], stamp["t"], stamp["r"], str(config.db_path()))
    if key in _meas_cache:
        return _meas_cache[key]
    samples: dict[str, dict] = {}
    for r in _q_rows(byproduct, project):
        k = _kind(r["target_text"], r["unit_text"])
        if not k:
            continue
        s = samples.get(r["sample_id"])
        if s is None:
            parsed = drying.parse_pretreatment(r["pretreatment_text"], r["pre_concept"])
            s = samples[r["sample_id"]] = {"alias": f"시료 {len(samples) + 1}", "method": parsed["method"] or "미상",
                                           "temp_c": parsed.get("temp_c"), "time_h": parsed.get("time_h"),
                                           "pressure_pa": parsed.get("pressure_pa")}
        if k == "moist_final" and r["value"] > 40 and "moist_init" not in s:
            k = "moist_init"  # 건조 후 수분이 40%를 넘는 일은 드물다 → 생시료 수분으로 본다
        s.setdefault(k, float(r["value"]))
    lst = list(samples.values())
    out = {"samples": lst, "n_samples": len(lst)}
    inits = [s["moist_init"] for s in lst if s.get("moist_init") is not None]
    if inits:
        out["initial_moisture"] = {"value": statistics.fmean(inits), "n": len(inits)}
    fd = [s["tpc"] for s in lst if s["method"] == "동결건조" and s.get("tpc") is not None]
    if fd:
        out["tpc_ref"] = {"value": statistics.fmean(fd), "n": len(fd), "samples": [s["alias"] for s in lst
                          if s["method"] == "동결건조" and s.get("tpc") is not None]}
    if len(_meas_cache) > 32:
        _meas_cache.clear()
    _meas_cache[key] = out
    return out


def measured_param(label: str, value, unit: str, n: int, aliases: list[str], note: str, key: str) -> dict:
    return {"key": key, "label": label, "value": value, "unit": unit,
            "evidence": {"type": "measured", "citation": None, "doi": None, "verified": False, "verified_at": None,
                         "locator": "내 DB 측정값(CoA)", "n": n, "samples": aliases,
                         "note": note + (" — 실측 n=%d, 보정 신뢰도 낮음" % n if n <= 2 else ""), "validity": {}}}


# ---------------------------------------------------------------- 보정

def dry_calibration(meas: dict) -> dict | None:
    """열풍건조 시료(온도·시간·생시료/건조후 수분이 모두 있는 것)로 Lewis k를 맞춘다. Ea는 문헌 맞춤값 유지."""
    pts = []
    for s in meas["samples"]:
        if s["method"] != "열풍건조" or None in (s.get("temp_c"), s.get("time_h"), s.get("moist_init"), s.get("moist_final")):
            continue
        if s["time_h"] <= 0 or s["moist_final"] >= s["moist_init"]:
            continue
        x0, xf = wb_to_db(s["moist_init"]), wb_to_db(s["moist_final"])
        xe = gab_xe(heated_air_aw(s["temp_c"]))
        if xf <= xe:
            continue
        k_meas = -math.log((xf - xe) / (x0 - xe)) / s["time_h"]
        pts.append({"sample": s["alias"], "temp_c": s["temp_c"], "time_h": s["time_h"], "moist_init": s["moist_init"],
                    "moist_final": s["moist_final"], "k_meas": k_meas, "k_lit": k_dry_lit(s["temp_c"])})
    if not pts:
        return None
    factor = math.exp(statistics.fmean(math.log(p["k_meas"] / p["k_lit"]) for p in pts))
    for p in pts:
        x0 = wb_to_db(p["moist_init"])
        xe = gab_xe(heated_air_aw(p["temp_c"]))
        pred = xe + (x0 - xe) * math.exp(-p["k_lit"] * factor * p["time_h"])
        p["pred_final"] = round(db_to_wb(pred), 2)
        p["residual"] = round(p["moist_final"] - db_to_wb(pred), 2)
        p["k_meas"], p["k_lit"] = round(p["k_meas"], 4), round(p["k_lit"], 4)
    return {"applied": True, "factor": round(factor, 3), "n": len(pts), "points": pts,
            "how": "시료의 생시료→건조후 수분과 온도·시간에서 k를 역산해 문헌 k(T)에 곱할 배율을 구함(기하평균). Ea는 문헌 맞춤값 유지. "
                   "시료의 두께·풍속은 CoA에 없어 문헌 조건(3 mm, 0.9 m/s)으로 가정.",
            "confidence": "낮음" if len(pts) <= 2 else "보통",
            "message": (f"실측 n={len(pts)} — 보정 신뢰도 낮음" if len(pts) <= 2 else f"실측 n={len(pts)}로 보정")}


def tpc_calibration(meas: dict) -> dict | None:
    """동결건조 TPC 평균을 잔존율 1(기준)로 두고, 열풍건조 시료의 잔존율로 겉보기 k(T)의 배율을 맞춘다."""
    ref = meas.get("tpc_ref")
    if not ref:
        return None
    pts = []
    for s in meas["samples"]:
        if s["method"] != "열풍건조" or None in (s.get("temp_c"), s.get("time_h"), s.get("tpc")) or s["time_h"] <= 0:
            continue
        r = s["tpc"] / ref["value"]
        if not 0 < r < 1:
            continue
        pts.append({"sample": s["alias"], "temp_c": s["temp_c"], "time_h": s["time_h"], "tpc": s["tpc"],
                    "retention": round(r, 4), "k_meas": -math.log(r) / s["time_h"], "k_lit": k_tpc_lit(s["temp_c"])})
    if not pts:
        return {"applied": False, "n": 0, "ref": ref, "message": "열풍건조 TPC 실측(온도·시간 포함)이 없어 문헌 상수 그대로 씀"}
    factor = math.exp(statistics.fmean(math.log(p["k_meas"] / p["k_lit"]) for p in pts))
    for p in pts:
        pred = math.exp(-p["k_lit"] * factor * p["time_h"]) * ref["value"]
        p["pred_tpc"] = round(pred, 3)
        p["residual"] = round(p["tpc"] - pred, 3)
        p["k_meas"], p["k_lit"] = round(p["k_meas"], 4), round(p["k_lit"], 4)
    n = len(pts)
    return {"applied": True, "factor": round(factor, 3), "n": n, "ref": ref, "points": pts,
            "how": "동결건조 시료의 TPC 평균을 잔존율 1로 두고, 열풍건조 시료의 잔존율로 k를 역산해 문헌 k(T)에 곱할 배율을 구함. "
                   "Ea는 문헌 맞춤값 유지. 서로 다른 시료(로트)를 비교하므로 원료 차이가 보정에 섞인다.",
            "confidence": "낮음" if n <= 2 or ref["n"] <= 2 else "보통",
            "message": (f"실측 n={n}(기준 동결건조 n={ref['n']}) — 보정 신뢰도 낮음" if n <= 2 or ref["n"] <= 2
                        else f"실측 n={n}로 보정")}


# ---------------------------------------------------------------- 공정 모의

def _cal_widen(cal: dict | None) -> float:
    if not cal or not cal.get("applied"):
        return 1.0
    return 1.5 if cal["n"] <= 2 else 1.2


def _k_dry(method: str, inp: dict, cal: dict | None) -> tuple[float, float, float, float]:
    """→ (k, k_lo, k_hi, X_e) — 열풍·진공·자연 공통의 Lewis 속도상수"""
    t = inp["temp_c"]
    fit = dry_fit()
    k = k_dry_lit(t)
    lo = hi = math.exp(fit["rmse"])
    a, b = _ea_band_factor(t, fit)
    k_lo, k_hi = k / lo * a, k * hi * b
    n_exp, nb = pv("a_thickness_exp"), registry()["parameters"]["a_thickness_exp"]["band"]
    ratio_l = pv("ha_l_ref") / inp["thickness_mm"]
    fl = [ratio_l ** e for e in (n_exp, *nb)]
    k, k_lo, k_hi = k * fl[0], k_lo * min(fl), k_hi * max(fl)
    if method in ("열풍건조", "자연건조"):
        m_exp, mb = pv("a_velocity_exp"), registry()["parameters"]["a_velocity_exp"]["band"]
        rv = max(inp["air_velocity_ms"], 0.05) / pv("ha_v_ref")
        fv = [rv ** e for e in (m_exp, *mb)]
        k, k_lo, k_hi = k * fv[0], k_lo * min(fv), k_hi * max(fv)
    if method == "진공건조":
        f, fb = pv("a_vacuum_factor"), registry()["parameters"]["a_vacuum_factor"]["band"]
        k, k_lo, k_hi = k * f, k_lo * fb[0], k_hi * fb[1]
    if cal and cal.get("applied"):
        w = _cal_widen(cal)
        k, k_lo, k_hi = k * cal["factor"], k_lo * cal["factor"] / w, k_hi * cal["factor"] * w
    if method == "자연건조":
        xe = gab_xe(inp["rh"] / 100.0)
    elif method == "진공건조":
        xe = 0.0
    else:
        xe = gab_xe(heated_air_aw(t))
    return k, k_lo, k_hi, xe


def _lewis_time(x0: float, xt: float, xe: float, k: float) -> float | None:
    if xt <= xe or k <= 0:
        return None
    return math.log((x0 - xe) / (xt - xe)) / k


def _fd_primary(inp: dict, kv_f: float = 1.0, rp_f: float = 1.0) -> dict:
    """준정상 1차 건조: Kv(P)·(Ts − Tp) = ΔHs·J,  J = (p_ice(Tp) − Pc)/Rp  → Tp를 이분법으로 푼다."""
    ts, pc = inp["temp_c"], inp["pressure_pa"]
    kvp = pv("a_fd_kv")
    kv = (kvp["Kc"] + kvp["Kp"] * pc / (1 + kvp["Kd"] * pc)) * kv_f
    rp = pv("a_fd_rp") * rp_f
    hi_t = min(ts, -0.5)
    if drying.p_sub(hi_t + 273.15) <= pc:
        return {"ok": False, "kv": kv, "rp": rp, "reason": "선반 온도에서 얼음 증기압이 챔버 압력보다 낮아 승화가 일어나지 않습니다."}
    lo, hi = -90.0, hi_t
    for _ in range(60):
        mid = (lo + hi) / 2
        tk = mid + 273.15
        g = kv * (ts - mid) / dh_sub_j_per_kg(tk) - (drying.p_sub(tk) - pc) / rp
        if g > 0:
            lo = mid
        else:
            hi = mid
    tp = (lo + hi) / 2
    flux = max((drying.p_sub(tp + 273.15) - pc) / rp, 1e-12)  # kg/(m²·s)
    rho = pv("a_fd_density")
    x0 = wb_to_db(inp["initial_moisture"])
    dry_area = inp["thickness_mm"] / 1000.0 * rho / (1 + x0)  # kg 건물/m²
    xb = pv("a_fd_bound")
    ice = dry_area * max(x0 - xb, 0.0)
    tprim = ice / flux / 3600.0
    return {"ok": True, "tp": tp, "flux": flux, "kv": kv, "rp": rp, "t_primary": tprim, "dry_area": dry_area,
            "ice_per_m2": ice, "dh": dh_sub_j_per_kg(tp + 273.15)}


def _fd_moisture(inp: dict, prim: dict, t: float, k2: float) -> float:
    x0, xb = wb_to_db(inp["initial_moisture"]), pv("a_fd_bound")
    xe2 = pv("a_fd_secondary")["xe"]
    if not prim.get("ok"):
        return x0
    tp = prim["t_primary"]
    if t <= tp:
        return x0 - (x0 - min(xb, x0)) * t / tp
    xs = min(xb, x0)
    return xe2 + (xs - xe2) * math.exp(-k2 * (t - tp))


def _fd_k2(inp: dict, f: float = 1.0) -> float:
    s = pv("a_fd_secondary")
    return arrhenius(s["k25"], dry_fit()["ea_j"], max(inp["temp_c"], -20), 25.0) * f


def _fd_time_to(inp: dict, prim: dict, xt: float, k2: float) -> float | None:
    if not prim.get("ok"):
        return None
    x0, xb, xe2 = wb_to_db(inp["initial_moisture"]), pv("a_fd_bound"), pv("a_fd_secondary")["xe"]
    if xt >= x0:
        return 0.0
    if xt >= xb:
        return prim["t_primary"] * (x0 - xt) / (x0 - xb)
    if xt <= xe2:
        return None
    return prim["t_primary"] + math.log((min(xb, x0) - xe2) / (xt - xe2)) / k2


def simulate(method: str, inp: dict, ctx: dict) -> dict:
    """핵심 수치만(빠르게) — 민감도 계산에서 반복 호출한다."""
    x0, xt = wb_to_db(inp["initial_moisture"]), wb_to_db(inp["target_moisture"])
    out: dict = {}
    if method in ("열풍건조", "진공건조", "자연건조"):
        k, k_lo, k_hi, xe = _k_dry(method, inp, ctx.get("dry_cal"))
        out.update(k=k, k_lo=k_lo, k_hi=k_hi, xe=xe)
        out["t_target"] = _lewis_time(x0, xt, xe, k)
        out["t_target_lo"] = _lewis_time(x0, xt, xe, k_hi)
        out["t_target_hi"] = _lewis_time(x0, xt, xe, k_lo)
        th = inp["time_h"]
        out["x_end"] = xe + (x0 - xe) * math.exp(-k * th)
        out["x_end_lo"] = xe + (x0 - xe) * math.exp(-k_hi * th)
        out["x_end_hi"] = xe + (x0 - xe) * math.exp(-k_lo * th)
        # TPC: 겉보기 1차, 공정 시간 전체
        tc = ctx.get("tpc_cal")
        kt = k_tpc_lit(inp["temp_c"])
        fit = tpc_fit()
        a, b = _ea_band_factor(inp["temp_c"], fit)
        kt_lo, kt_hi = kt / math.exp(fit["rmse"]) * a, kt * math.exp(fit["rmse"]) * b
        if method == "진공건조":
            f, fb = pv("a_vacuum_oxygen"), registry()["parameters"]["a_vacuum_oxygen"]["band"]
            kt, kt_lo, kt_hi = kt * f, kt_lo * fb[0], kt_hi * fb[1]
        if tc and tc.get("applied"):
            w = _cal_widen(tc)
            kt, kt_lo, kt_hi = kt * tc["factor"], kt_lo * tc["factor"] / w, kt_hi * tc["factor"] * w
        out.update(kt=kt, kt_lo=kt_lo, kt_hi=kt_hi, ret=math.exp(-kt * th), ret_lo=math.exp(-kt_hi * th),
                   ret_hi=math.exp(-kt_lo * th))
        if out["t_target"] is not None:
            out["ret_at_target"] = math.exp(-kt * out["t_target"])
    elif method == "동결건조":
        prim = _fd_primary(inp)
        kvb = registry()["parameters"]["a_fd_kv"]["band"]
        rpb = registry()["parameters"]["a_fd_rp"]["band"]
        k2b = registry()["parameters"]["a_fd_secondary"]["band"]
        fast = _fd_primary(inp, kvb[1], rpb[0])
        slow = _fd_primary(inp, kvb[0], rpb[1])
        k2 = _fd_k2(inp)
        out.update(prim=prim, k2=k2)
        out["t_target"] = _fd_time_to(inp, prim, xt, k2)
        out["t_target_lo"] = _fd_time_to(inp, fast, xt, _fd_k2(inp, k2b[1]))
        out["t_target_hi"] = _fd_time_to(inp, slow, xt, _fd_k2(inp, k2b[0]))
        th = inp["time_h"]
        out["x_end"] = _fd_moisture(inp, prim, th, k2)
        out["x_end_lo"] = _fd_moisture(inp, fast, th, _fd_k2(inp, k2b[1])) if fast.get("ok") else out["x_end"]
        out["x_end_hi"] = _fd_moisture(inp, slow, th, _fd_k2(inp, k2b[0])) if slow.get("ok") else out["x_end"]
        rb = registry()["parameters"]["a_fd_retention"]["band"]
        out.update(ret=pv("a_fd_retention"), ret_lo=rb[0], ret_hi=rb[1])
        out["stage"] = ("1차 건조(승화)" if prim.get("ok") and th <= prim["t_primary"] else "2차 건조(탈착)") if prim.get("ok") else "승화 안 됨"
    elif method == "분무건조":
        mr = pv("a_spray_moisture")
        out.update(x_end=wb_to_db(sum(mr) / 2), x_end_lo=wb_to_db(mr[0]), x_end_hi=wb_to_db(mr[1]), t_target=None)
        th = inp["residence_s"] / 3600.0
        kt = k_tpc_lit(inp["outlet_c"])
        fit = tpc_fit()
        kt_hi = kt * math.exp(fit["rmse"]) * 3  # 액적 표면은 출구 온도보다 잠시 더 뜨거울 수 있다 — 폭을 넓게
        out.update(kt=kt, ret=math.exp(-kt * th), ret_lo=math.exp(-kt_hi * th), ret_hi=1.0)
    return out


# ---------------------------------------------------------------- 결과 조립

def _validity_warnings(params: list[dict], vals: dict, byproduct: str | None) -> list[dict]:
    """입력이 파라미터 근거의 유효 범위 밖이면 '외삽' 경고. 같은 입력·같은 범위는 한 줄로 묶는다."""
    names = {"temp_c": "온도", "air_velocity_ms": "풍속", "thickness_mm": "두께", "pressure_pa": "압력"}
    units = {"temp_c": "℃", "air_velocity_ms": "m/s", "thickness_mm": "mm", "pressure_pa": "Pa"}
    groups: dict[tuple, list[str]] = {}
    bp_warn = None
    for p in params:
        if p.get("role") == "reference":
            continue
        v = p["evidence"].get("validity") or {}
        for key, rng in v.items():
            if key == "byproduct":
                if rng == "사과박" and byproduct and byproduct != "사과박":
                    bp_warn = {"kind": "byproduct", "text": f"근거 문헌은 사과박 자료입니다. '{byproduct}'에는 사과박 상수를 빌려 써서 오차가 클 수 있습니다."}
                continue
            if key not in vals or vals[key] is None or not isinstance(rng, list):
                continue
            x = vals[key]
            if x < rng[0] or x > rng[1]:
                g = groups.setdefault((key, rng[0], rng[1]), [])
                if p["label"] not in g:
                    g.append(p["label"])
    warns = [bp_warn] if bp_warn else []
    for (key, lo, hi), labels in groups.items():
        u = units.get(key, "")
        warns.append({"kind": "extrapolation", "input": key, "range": [lo, hi], "params": labels,
                      "text": f"외삽 — 근거 범위 밖: {names.get(key, key)} {vals[key]:g} {u}는 근거 범위 {lo:g}–{hi:g} {u} 밖입니다 "
                              f"({', '.join(labels)})."})
    return warns


def _r(x, d=3):
    return None if x is None else round(x, d)


def _sweep(method: str, inp: dict, ctx: dict, fn, n: int = 25) -> list[list]:
    spec = next(s for s in INPUTS[method] if s["key"] == "temp_c")
    pts = []
    for i in range(n):
        t = spec["min"] + (spec["max"] - spec["min"]) * i / (n - 1)
        sim = simulate(method, {**inp, "temp_c": t}, ctx)
        y = fn(sim)
        if y is not None:
            pts.append([round(t, 2)] + [_r(v, 4) for v in y])
    return pts


def _temp_label(method: str) -> str:
    return next(s["label"] for s in INPUTS[method] if s["key"] == "temp_c") + " (℃)"


def _moisture_output(method, inp, sim, ctx, meas, byproduct) -> dict:
    x0, xt = wb_to_db(inp["initial_moisture"]), wb_to_db(inp["target_moisture"])
    params, warns, cal = [], [], None
    vals = {k: inp.get(k) for k in ("temp_c", "air_velocity_ms", "thickness_mm", "pressure_pa")}
    secondary = []
    if method in ("열풍건조", "진공건조", "자연건조"):
        fit = dry_fit()
        params.append(param("ha_time_table"))
        params.append(derived("k_ref", "Lewis 속도상수 k(60 ℃, 3 mm, 0.9 m/s)", round(fit["k_ref"], 4), "1/h", ["ha_time_table"],
                              "표 1 건조 시간에서 k = −ln((0.15 − Xe)/(0.76 − Xe))/t를 온도별로 역산해 ln k = a + b/T로 최소제곱 맞춤"))
        params.append(derived("ea_fit", "건조 활성화 에너지(이 앱 맞춤)", round(fit["ea_j"] / 1000, 2), "kJ/mol", ["ha_time_table"],
                              f"맞춤 잔차 RMSE(ln k) {fit['rmse']:.3f}. 문헌값 38.21(Llavata)·23.9(Araujo) kJ/mol 사이"))
        params += [param("ha_ea_paper"), param("ha_ea_araujo"), param("ha_x0_ref"), param("ha_xf_ref"), param("ha_l_ref"),
                   param("a_thickness_exp")]
        if method != "진공건조":
            params += [param("ha_v_ref"), param("a_velocity_exp"), param("gab")]
            params.append(param("a_ambient") if method == "열풍건조" else param("gab", label="GAB(자연건조: 입력 상대습도로 Xe)"))
        else:
            params.append(param("a_vacuum_factor"))
        cal = ctx.get("dry_cal")
        if cal:
            params.append(measured_param("열풍건조 실측 보정 배율", cal["factor"], "×", cal["n"], [p["sample"] for p in cal["points"]],
                                         "생시료·건조 후 수분과 공정 온도·시간으로 역산", "cal_dry"))
        formula = {
            "text": "MR(t) = (X − Xe)/(X0 − Xe) = exp(−k·t),  k = k_ref·exp(−Ea/R·(1/T − 1/T_ref))·(L_ref/L)^n"
                    + ("·(v/v_ref)^m" if method != "진공건조" else "·f_vac") + (" · c_실측" if cal else "")
                    + ";  목표까지 시간 t* = ln((X0 − Xe)/(X_t − Xe))/k",
            "latex": r"MR=\frac{X-X_e}{X_0-X_e}=e^{-kt},\; k=k_{ref}\,e^{-\frac{E_a}{R}\left(\frac1T-\frac1{T_{ref}}\right)}\left(\frac{L_{ref}}{L}\right)^{n}"
                     + (r"\left(\frac{v}{v_{ref}}\right)^{m}" if method != "진공건조" else r"f_{vac}")
                     + (r"\,c_{cal}" if cal else "") + r",\; t^*=\frac{1}{k}\ln\frac{X_0-X_e}{X_t-X_e}",
            "model": "Lewis(Newton) 박층 건조식 + Arrhenius 온도 의존. 문헌 표의 건조 시간에서 역산한 유도 상수를 쓴다 — 단순 모델이며 Page·확산 모델보다 곡선 모양이 거칠다.",
        }
        if method == "진공건조":
            bp = _boil_c(inp["pressure_pa"])
            secondary.append({"label": "챔버 압력에서 물 끓는점", "value": round(bp, 1), "unit": "℃"})
            formula["model"] += " 진공건조는 사과박 동역학 문헌을 찾지 못해 열풍 상수를 선반 온도로 빌려 썼다(가정)."
        if method == "자연건조":
            formula["model"] += " 자연건조는 낮·밤 온습도 변화와 일사를 무시하고 일정한 기온·습도로 근사한다."
        secondary.append({"label": "평형 수분 Xe", "value": round(db_to_wb(sim["xe"]), 2), "unit": "% 습량"})
        if xt <= sim["xe"]:
            warns.append({"kind": "info", "text": f"이 조건의 평형 수분({db_to_wb(sim['xe']):.1f}%)이 목표 수분보다 높아 목표에 도달하지 못합니다. "
                                                  "온도를 높이거나 습도를 낮추세요."})
        k, k_lo, k_hi, xe = sim["k"], sim["k_lo"], sim["k_hi"], sim["xe"]
        tmax = max(inp["time_h"], min(sim["t_target"] or 0, inp["time_h"] * 3)) * 1.05
        curve = []
        for i in range(61):
            t = tmax * i / 60
            curve.append([round(t, 3), round(db_to_wb(xe + (x0 - xe) * math.exp(-k * t)), 3),
                          round(db_to_wb(xe + (x0 - xe) * math.exp(-k_hi * t)), 3), round(db_to_wb(xe + (x0 - xe) * math.exp(-k_lo * t)), 3)])
    elif method == "동결건조":
        prim = sim["prim"]
        params += [param("p_ice"),
                   derived("dh_sub", "승화 잠열(품온에서)", round(prim.get("dh", dh_sub_j_per_kg(253.15)) / 1e6, 3), "MJ/kg", ["p_ice"],
                           "얼음 증기압 식을 Clausius–Clapeyron으로 미분", {"temp_c": [-100, 0]}),
                   param("a_fd_kv"), param("a_fd_rp"), param("a_fd_density"), param("a_fd_bound"), param("a_fd_secondary")]
        formula = {
            "text": "1차: Kv(P)·(Ts − Tp) = ΔHs·J,  J = (p_ice(Tp) − Pc)/Rp,  Kv = Kc + Kp·P/(1 + Kd·P),  t1 = m_ice/J;  "
                    "2차: X(t) = Xe2 + (Xb − Xe2)·exp(−k2·(t − t1))",
            "latex": r"K_v(P)(T_s-T_p)=\Delta H_s J,\; J=\frac{p_{ice}(T_p)-P_c}{R_p},\; t_1=\frac{m_{ice}}{J};\; X=X_{e2}+(X_b-X_{e2})e^{-k_2(t-t_1)}",
            "model": "준정상 열·물질전달 균형으로 승화 면 온도 Tp와 승화 속도를 푸는 단순 1차 건조 추정 + 지수형 2차 탈착. Kv·Rp는 설비·제품마다 달라 가정값이다.",
        }
        if prim.get("ok"):
            secondary += [{"label": "승화 면 품온 Tp", "value": round(prim["tp"], 1), "unit": "℃"},
                          {"label": "1차 건조 시간", "value": round(prim["t_primary"], 1), "unit": "h"},
                          {"label": "승화 속도", "value": round(prim["flux"] * 3600, 3), "unit": "kg/m²·h"},
                          {"label": "현재 단계", "value": sim["stage"], "unit": ""}]
            if prim["tp"] > -10:
                warns.append({"kind": "info", "text": f"승화 면 품온 {prim['tp']:.1f} ℃ — 붕괴(collapse) 위험이 있습니다. 선반 온도를 낮추거나 압력을 낮추세요."})
            ed = ctx["equip"]["values"]["동결건조"]
            if inp["pressure_pa"] < ed["pressure_min_pa"]:
                warns.append({"kind": "equipment", "text": f"챔버 압력 {inp['pressure_pa']:g} Pa는 내 설비 최저 도달 압력({ed['pressure_min_pa']:g} Pa)보다 낮습니다."})
        else:
            warns.append({"kind": "info", "text": prim["reason"] + " 선반 온도를 올리거나 압력을 낮추세요."})
        k2 = sim["k2"]
        tmax = max(inp["time_h"], (sim["t_target"] or 0)) * 1.05
        curve = []
        for i in range(61):
            t = tmax * i / 60
            curve.append([round(t, 3), round(db_to_wb(_fd_moisture(inp, prim, t, k2)), 3)])
        vals = {"pressure_pa": inp["pressure_pa"]}
        if not 0 <= inp["temp_c"] <= 50 and prim.get("ok"):
            warns.append({"kind": "extrapolation", "input": "temp_c", "range": [0, 50],
                          "text": f"외삽 — 근거 범위 밖: 선반 온도 {inp['temp_c']:g} ℃는 2차 건조 가정의 범위(0–50 ℃) 밖입니다."})
    else:  # 분무건조
        params.append(param("a_spray_moisture"))
        formula = {"text": "정량 건조 곡선 없음 — 분말 최종 수분을 가정 범위로 표시",
                   "latex": r"X_{end}\in[3,6]\,\%\;(\text{가정})",
                   "model": "분무건조는 액상(추출액·슬러리)에만 쓰고 체류가 수 초라 박층 건조식을 적용하지 않는다."}
        curve = []
        warns.append({"kind": "info", "text": "사과박 고형물 그대로는 분무건조할 수 없습니다 — 추출액·슬러리 기준의 가정값입니다."})
        vals = {}
    warns = _validity_warnings(params, vals, byproduct) + warns
    if cal and cal.get("confidence") == "낮음":
        warns.append({"kind": "calibration", "text": cal["message"]})
    # 민감도: 온도 → 목표까지 시간
    sens = None
    measured_pts = []
    if method != "분무건조":
        sens = {"x_label": _temp_label(method), "y_label": "목표 수분까지 시간 (h)",
                "points": _sweep(method, inp, ctx, lambda s: None if s.get("t_target") is None else
                                 (s["t_target"], s.get("t_target_lo"), s.get("t_target_hi")))}
        for s in meas["samples"]:
            if s["method"] == method and s.get("temp_c") is not None and s.get("time_h") is not None and s.get("moist_final") is not None:
                measured_pts.append({"x": s["temp_c"], "y": s["time_h"], "label": f"{s['alias']}: {s['time_h']:g} h → {s['moist_final']:g}%"})
        sens["current"] = [inp["temp_c"], _r(sim.get("t_target"))]
        sens["measured"] = measured_pts
        if measured_pts:
            sens["note"] = "실측 점: 그 시간 동안 건조해 적힌 수분이 됨(목표 수분과 다를 수 있음)."
    t_tar = sim.get("t_target")
    value = _r(db_to_wb(sim["x_end"]), 2)
    res = {
        "key": "moisture", "label": "수분·목표 수분 도달 시간", "status": "ok",
        "value": value, "low": _r(db_to_wb(sim["x_end_lo"]), 2), "high": _r(db_to_wb(sim["x_end_hi"]), 2), "unit": "% 습량",
        "value_label": "공정 끝 예상 수분" if method != "분무건조" else "분말 최종 수분(가정)",
        "headline": None if method == "분무건조" else {
            "label": f"목표 {inp['target_moisture']:g}%까지", "value": _r(t_tar, 2), "low": _r(sim.get("t_target_lo"), 2),
            "high": _r(sim.get("t_target_hi"), 2), "unit": "h", "reachable": t_tar is not None},
        "secondary": secondary,
        "chart": None if not curve else {"x_label": "시간 (h)", "y_label": "수분 (% 습량)", "points": curve,
                                         "target": inp["target_moisture"], "time_h": inp.get("time_h")},
        "sensitivity": sens, "formula": formula, "params": params, "calibration": cal, "warnings": warns,
    }
    return res


def _boil_c(p_pa: float) -> float:
    lo, hi = -10.0, 200.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if drying.p_vap(mid + 273.15) < p_pa:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _tpc_output(method, inp, sim, ctx, meas, byproduct) -> dict:
    params, warns = [], []
    tc = ctx.get("tpc_cal")
    ref = meas.get("tpc_ref")
    vals = {"temp_c": inp["temp_c"] if method != "분무건조" else inp["outlet_c"]}
    if method in ("열풍건조", "진공건조", "자연건조", "분무건조"):
        fit = tpc_fit()
        params += [param("tpc_retention_table"), param("ha_time_table"),
                   derived("kt_ref", "TPC 겉보기 1차 속도상수 k(60 ℃)", round(fit["k_ref"], 4), "1/h", ["tpc_retention_table"],
                           "표 2 잔존율 R과 표 1 시간 t로 k = −ln(R)/t를 온도별로 역산해 Arrhenius 맞춤"),
                   derived("ea_tpc", "TPC 손실 겉보기 활성화 에너지(이 앱 맞춤)", round(fit["ea_j"] / 1000, 2), "kJ/mol",
                           ["tpc_retention_table"], f"맞춤 잔차 RMSE(ln k) {fit['rmse']:.3f}")]
        if method == "진공건조":
            params.append(param("a_vacuum_oxygen"))
        formula = {"text": "R(t) = C/C_ref = exp(−∫k(T)dt) = exp(−k(T)·t),  k(T) = k_ref·exp(−Ea/R·(1/T − 1/T_ref))"
                           + (" · c_실측" if tc and tc.get("applied") else "") + ";  예상 TPC = R × TPC(동결건조 실측 평균)",
                   "latex": r"R=e^{-\int k(T)\,dt},\; k=k_{ref}e^{-\frac{E_a}{R}\left(\frac1T-\frac1{T_{ref}}\right)}"
                            + (r"c_{cal}" if tc and tc.get("applied") else "") + r",\; C=R\cdot C_{FD}",
                   "model": "겉보기 1차 손실(열분해 + 효소적 산화 합산). 온도는 문헌 기준대로 공기(가열) 온도이며 공정 중 일정하다고 본다."
                            + (" 분무건조는 출구 온도·체류 시간으로 계산하며 문헌 범위(장시간 박층 건조) 밖이다." if method == "분무건조" else "")}
    else:
        params.append(param("a_fd_retention"))
        formula = {"text": "R = 1 (동결건조를 기준으로 둠);  예상 TPC = 동결건조 실측 평균",
                   "latex": r"R_{FD}\equiv 1", "model": "동결건조는 열 손실이 거의 없는 기준점으로 둔다(가정)."}
    if ref:
        params.append(measured_param("기준 TPC(동결건조 실측 평균)", round(ref["value"], 3), "mg GAE/g 건량", ref["n"], ref["samples"],
                                     "동결건조 시료를 잔존율 1로 둔 기준값", "tpc_ref"))
    if tc and tc.get("applied") and method != "동결건조":
        params.append(measured_param("열풍건조 TPC 실측 보정 배율", tc["factor"], "×", tc["n"], [p["sample"] for p in tc["points"]],
                                     "열풍건조 시료 TPC ÷ 동결건조 기준으로 잔존율을 얻어 k를 역산", "cal_tpc"))
        if method != "열풍건조":
            warns.append({"kind": "info", "text": "열풍건조 실측 보정 배율을 이 방식에도 그대로 적용했습니다(같은 원료라는 가정)."})
    warns = _validity_warnings(params, vals, byproduct) + warns
    if tc and tc.get("applied") and tc.get("confidence") == "낮음" and method != "동결건조":
        warns.append({"kind": "calibration", "text": tc["message"]})
    secondary = []
    if ref:
        secondary.append({"label": "예상 TPC", "value": _r(sim["ret"] * ref["value"], 2), "low": _r(sim["ret_lo"] * ref["value"], 2),
                          "high": _r(sim["ret_hi"] * ref["value"], 2), "unit": "mg GAE/g 건량"})
    else:
        warns.append({"kind": "info", "text": "동결건조 TPC 실측이 없어 예상 TPC 값(mg GAE/g)은 계산하지 않고 잔존율만 보입니다. 동결건조 CoA를 올리면 계산됩니다."})
    if sim.get("ret_at_target") is not None:
        secondary.append({"label": "목표 수분 도달 시점에서 멈추면", "value": _r(sim["ret_at_target"] * 100, 1), "unit": "% 잔존"})
    # 민감도: 온도 → 잔존율(같은 공정 시간)
    sens = None
    if method != "동결건조":
        if method == "분무건조":
            spec = next(s for s in INPUTS[method] if s["key"] == "temp_c")
            sens = {"x_label": "출구 온도 (℃)", "y_label": "TPC 잔존율 (%)", "points": []}
            for i in range(25):
                t = 60 + 40 * i / 24
                s2 = simulate(method, {**inp, "outlet_c": t}, ctx)
                sens["points"].append([round(t, 2), _r(s2["ret"] * 100, 3), _r(s2["ret_lo"] * 100, 3), _r(s2["ret_hi"] * 100, 3)])
            sens["current"] = [inp["outlet_c"], _r(sim["ret"] * 100, 3)]
            del spec
        else:
            sens = {"x_label": _temp_label(method), "y_label": f"TPC 잔존율 (%, {inp['time_h']:g} h 공정)",
                    "points": _sweep(method, inp, ctx, lambda s: (s["ret"] * 100, s["ret_lo"] * 100, s["ret_hi"] * 100)),
                    "current": [inp["temp_c"], _r(sim["ret"] * 100, 2)]}
        sens["measured"] = []
        if tc and tc.get("points") and method == "열풍건조":
            for p in tc["points"]:
                sens["measured"].append({"x": p["temp_c"], "y": round(p["retention"] * 100, 2),
                                         "label": f"{p['sample']}: {p['temp_c']:g} ℃ {p['time_h']:g} h, 잔존 {p['retention'] * 100:.0f}%"})
        if method == "열풍건조":
            times, rets = pv("ha_time_table"), pv("tpc_retention_table")
            sens["literature"] = [{"x": float(t), "y": float(r), "label": f"Llavata 2022 표 2: {t} ℃, {times[t] / 60:.1f} h, {r}%"}
                                  for t, r in rets.items()]
            sens["note"] = "문헌 점(◇)은 각 온도의 건조 시간이 다르므로 같은 공정 시간 곡선과 직접 비교할 수 없습니다."
    chart = None
    if method in ("열풍건조", "진공건조", "자연건조"):
        th = max(inp["time_h"], 1e-6)
        chart = {"x_label": "시간 (h)", "y_label": "TPC 잔존율 (%)", "time_h": inp["time_h"],
                 "points": [[round(th * 1.2 * i / 40, 3), round(100 * math.exp(-sim["kt"] * th * 1.2 * i / 40), 3),
                             round(100 * math.exp(-sim["kt_hi"] * th * 1.2 * i / 40), 3),
                             round(100 * math.exp(-sim["kt_lo"] * th * 1.2 * i / 40), 3)] for i in range(41)]}
    return {"key": "tpc", "label": "총폴리페놀(TPC) 잔존율", "status": "ok", "value": _r(sim["ret"] * 100, 1),
            "low": _r(sim["ret_lo"] * 100, 1), "high": _r(sim["ret_hi"] * 100, 1), "unit": "% 잔존",
            "value_label": "공정 끝 잔존율(동결건조 기준 대비)", "secondary": secondary, "chart": chart, "sensitivity": sens,
            "formula": formula, "params": params, "calibration": tc if method != "동결건조" else None, "warnings": warns}


def _tdf_output(method, inp, sim, ctx, meas, byproduct) -> dict:
    vals = [s for s in meas["samples"] if s.get("tdf") is not None]
    same = [s for s in vals if s["method"] == method]
    params = [param("tdf_air_yield"), param("a_tdf_band")]
    # 문헌 근거(AIR 수율)는 40–120 ℃ 열풍 자료 — 동결·분무는 공정이 달라 온도 범위 비교를 하지 않는다
    tv = {"temp_c": inp["temp_c"]} if method in ("열풍건조", "진공건조", "자연건조") else {}
    warns = _validity_warnings(params, tv, byproduct)
    sens_meas = [{"x": s["temp_c"], "y": s["tdf"], "label": f"{s['alias']} ({s['method']}): {s['tdf']:g}"}
                 for s in vals if s.get("temp_c") is not None and s["method"] == method]
    use = same or vals
    if use:
        v = statistics.fmean(s["tdf"] for s in use)
        lo, hi = min(s["tdf"] for s in use), max(s["tdf"] for s in use)
        band = v * pv("a_tdf_band") / 100
        lo, hi = min(lo, v - band), max(hi, v + band)
        params.append(measured_param(f"TDF 실측({method if same else '전체 방식'} 평균)", round(v, 2), "g/100 g 건량", len(use),
                                     [s["alias"] for s in use], "식이섬유는 건조에서 대체로 보존된다고 보고 실측값에 고정", "tdf_meas"))
        if not same:
            warns.append({"kind": "info", "text": f"{method} TDF 실측이 없어 다른 방식 실측 평균을 썼습니다."})
        diffs = {}
        for s in vals:
            diffs.setdefault(s["method"], []).append(s["tdf"])
        secondary = [{"label": f"{m} 실측 평균", "value": round(statistics.fmean(x), 2), "unit": f"g/100 g (n={len(x)})"}
                     for m, x in diffs.items()]
        if len(diffs) > 1:
            secondary.append({"label": "참고", "value": "방식 간 차이는 서로 다른 시료(로트)의 원료 차이일 수 있음", "unit": ""})
        value, low, high, status = round(v, 2), round(lo, 2), round(hi, 2), "ok"
    else:
        value = low = high = None
        status = "unavailable"
        secondary = []
        warns.append({"kind": "info", "text": "TDF 실측이 없어 값 대신 '보존 경향'만 보입니다. TDF가 적힌 CoA를 올리면 값이 나옵니다."})
    spec = next(s for s in INPUTS[method] if s["key"] == "temp_c")
    sens = None if value is None else {
        "x_label": _temp_label(method), "y_label": "TDF (g/100 g 건량)",
        "points": [[spec["min"] + (spec["max"] - spec["min"]) * i / 10, value, low, high] for i in range(11)],
        "current": [inp["temp_c"], value], "measured": sens_meas,
        "note": "온도 의존 모델 없음 — 근거(문헌 AIR 수율 무변화)상 평평한 선으로 둔다."}
    return {"key": "tdf", "label": "총식이섬유(TDF)", "status": status, "value": value, "low": low, "high": high,
            "unit": "g/100 g 건량", "value_label": "예상 TDF(보존 가정, 실측 고정)", "secondary": secondary, "chart": None,
            "sensitivity": sens, "calibration": None, "params": params, "warnings": warns,
            "formula": {"text": "TDF_dry ≈ TDF_실측 (건량 기준 보존;  변화 폭 ± 가정 %)", "latex": r"TDF_{dry}\approx TDF_{meas}\,(1\pm\delta)",
                        "model": "식이섬유는 열에 안정해 건조에서 크게 변하지 않는다는 문헌 근거(AIR 수율 무변화)로 보존 모델을 쓴다. 온도별 정량 변화식은 쓰지 않는다."}}


def _color_output(method, inp) -> dict:
    eff = drying.METHODS[method]["effects"].get("색·갈변", "")
    return {"key": "color", "label": "색 변화(ΔE)·갈변", "status": "qualitative", "value": None, "low": None, "high": None,
            "unit": "ΔE", "value_label": "정량 예측 안 함", "qualitative": eff, "secondary": [], "chart": None, "sensitivity": None,
            "params": [param("a_color")], "calibration": None,
            "warnings": [{"kind": "info", "text": "신뢰할 만한 사과박 색 변화 속도식을 찾지 못해 수치를 내지 않습니다. 색차계(L*a*b*) 실측을 쌓으면 모델을 붙일 수 있습니다."}],
            "formula": {"text": "정량 식 없음 — 일반 경향(정성)", "latex": "", "model": "정성: " + eff}}


def _energy_output(method, inp, sim, ctx, byproduct) -> dict:
    eq = ctx["equip"]
    e = eq["values"][method]
    x0, xt = wb_to_db(inp["initial_moisture"]), wb_to_db(inp["target_moisture"])
    params, warns, secondary = [], [], []
    lit_lo = lit_hi = None
    if method == "열풍건조":
        params += [param("sec_convective_enterprise"), param("sec_convective")]
        lit_lo, lit_hi = pv("sec_convective_enterprise") / 3.6, pv("sec_convective") / 3.6
    elif method == "동결건조":
        params.append(param("sec_sublimation"))
        lit_lo = lit_hi = pv("sec_sublimation") / 3.6
    elif method == "진공건조":
        params.append(param("a_vacuum_sec"))
        lit_lo, lit_hi = pv("a_vacuum_sec")[0] / 3.6, pv("a_vacuum_sec")[1] / 3.6
    elif method == "분무건조":
        params.append(param("a_spray_sec"))
        lit_lo, lit_hi = pv("a_spray_sec")[0] / 3.6, pv("a_spray_sec")[1] / 3.6
    else:
        params.append(param("a_sun_sec"))
        lit_lo = lit_hi = 0.0
    params.append(param("latent_evap"))
    secondary.append({"label": "문헌·가정 범위", "value": f"{lit_lo:.2f}" + (f"–{lit_hi:.2f}" if lit_hi != lit_lo else ""), "unit": "kWh/kg 물"})
    secondary.append({"label": "이론 최소(증발 잠열)", "value": round(pv("latent_evap") / 3.6, 2), "unit": "kWh/kg 물"})

    def power(m):
        v = eq["values"][m]
        if m == "열풍건조":
            return v["heater_kw"] * v["duty"] + v["fan_kw"]
        if m == "동결건조":
            return (v["refrigeration_kw"] + v["vacuum_pump_kw"] + v["heater_kw"]) * v["duty"]
        if m == "진공건조":
            return v["heater_kw"] * v["duty"] + v["vacuum_pump_kw"]
        if m == "자연건조":
            return v["fan_kw"]
        return v["heater_kw"] + v["fan_kw"]

    keys = [s["key"] for s in EQUIP_SPEC[method]]
    params += equip_params(method, [k for k in keys if k not in ("condenser_kg", "pressure_min_pa")], eq)

    def sec_equip(s: dict, which: str = "t_target"):
        if method == "분무건조":
            return power(method) / e["evap_kg_h"]
        t = s.get(which)
        if t is None:
            return None
        water = e["batch_wet_kg"] / (1 + x0) * (x0 - xt)
        return power(method) * t / water if water > 0 else None

    v_eq = sec_equip(sim)
    lo_eq, hi_eq = sec_equip(sim, "t_target_lo"), sec_equip(sim, "t_target_hi")
    if method == "동결건조":
        ice = e["batch_wet_kg"] / (1 + x0) * max(x0 - pv("a_fd_bound"), 0)
        if ice > e["condenser_kg"]:
            warns.append({"kind": "equipment", "text": f"한 번에 얼려 붙일 얼음 {ice:.1f} kg이 콘덴서 용량 {e['condenser_kg']:g} kg보다 많습니다. 투입량을 줄이세요."})
    if method == "자연건조" and e["fan_kw"] == 0:
        v_eq = lo_eq = hi_eq = 0.0
    if v_eq is None:
        warns.append({"kind": "info", "text": "이 조건에서는 목표 수분에 도달하지 못해 설비 기반 비에너지를 계산할 수 없습니다."})
        value, low, high = _r(lit_lo, 2), _r(lit_lo, 2), _r(lit_hi, 2)
        label = "문헌·가정 범위(설비 계산 불가)"
    else:
        value, low, high = _r(v_eq, 2), _r(lo_eq if lo_eq is not None else v_eq, 2), _r(hi_eq if hi_eq is not None else v_eq, 2)
        label = "설비 사양 기반(목표 수분까지)" if method != "분무건조" else "설비 사양 기반(히터+송풍 ÷ 증발 능력)"
        if v_eq is not None and lit_hi and (v_eq < lit_lo * 0.5 or v_eq > lit_hi * 2):
            warns.append({"kind": "info", "text": f"설비 기반 값({v_eq:.2f})이 문헌·가정 범위({lit_lo:.2f}–{lit_hi:.2f} kWh/kg)와 크게 다릅니다. 설비 사양(출력·가동률·투입량)을 확인하세요."})
    if method == "열풍건조":
        params.append(param("lab_energy_araujo"))
        secondary.append({"label": "참고: 실험실 소형 오븐(Araujo 2024)", "value": "410.78–763.79", "unit": "kWh/kg (규모가 달라 비교 불가)"})
    sens = None
    if method not in ("분무건조",) and not (method == "자연건조" and e["fan_kw"] == 0):
        sens = {"x_label": _temp_label(method), "y_label": "비에너지 (kWh/kg 물)",
                "points": _sweep(method, inp, ctx, lambda s: None if sec_equip(s) is None else
                                 (sec_equip(s), sec_equip(s, "t_target_lo"), sec_equip(s, "t_target_hi"))),
                "current": [inp["temp_c"], value], "measured": [],
                "band_lit": [lit_lo, lit_hi], "note": "설비 사양으로 목표 수분까지 운전했을 때. 회색 띠는 문헌·가정 범위."}
    return {"key": "energy", "label": "비에너지 소비", "status": "ok", "value": value, "low": low, "high": high,
            "unit": "kWh/kg 물", "value_label": label, "secondary": secondary, "chart": None, "sensitivity": sens,
            "params": params, "calibration": None, "warnings": warns,
            "formula": {"text": "SEC = P_평균 × t*(목표까지) ÷ 제거한 물(m_건물 × (X0 − X_t)),  P_평균 = Σ(출력 × 가동률)",
                        "latex": r"SEC=\frac{\bar P\,t^*}{m_{dm}(X_0-X_t)}",
                        "model": "내 설비 사양과 건조 시간 예측으로 계산한 값과 문헌의 건조기 종류별 비에너지 범위를 함께 보인다. 열손실·예열은 가동률에 묶여 있다."}}


def _summary(outputs: list[dict]) -> dict:
    lit, meas, equip, assum = {}, set(), set(), set()
    for o in outputs:
        for p in o["params"]:
            ev = p["evidence"]
            if ev["type"] == "literature":
                lit[ev.get("doi")] = ev.get("verified")
            elif ev["type"] == "measured":
                meas.update(ev.get("samples") or [])
            elif ev["type"] == "equipment":
                equip.add(p["key"])
            else:
                assum.add(p["key"])
    n_ver = sum(1 for v in lit.values() if v)
    return {"literature": len(lit), "literature_verified": n_ver, "measured": len(meas), "equipment": len(equip),
            "assumption": len(assum),
            "text": f"이 예측의 근거: 문헌 {len(lit)}건(DOI 확인 {n_ver}) · 실측 {len(meas)}건 · 설비 사양 {len(equip)}개 · 가정 {len(assum)}개"}


def _canon_byproduct(b: str | None) -> str:
    b = (b or "").strip() or DEFAULT_BYPRODUCT
    try:
        from .. import thesaurus
        hits = [h for h in thesaurus.lookup(b) if h["scheme"] == "부산물"]
        if hits:
            return hits[0]["pref_label"]
    except Exception:  # noqa: BLE001
        pass
    return b


def context(byproduct: str | None, project: str | None) -> dict:
    meas = measured(byproduct, project)
    return {"meas": meas, "dry_cal": dry_calibration(meas), "tpc_cal": tpc_calibration(meas), "equip": load_equipment()}


def predict(method: str | None, inputs: dict | None = None, byproduct: str | None = None, project: str | None = None) -> dict:
    t0 = time.perf_counter()
    m = method_or_error(method)
    bp = _canon_byproduct(byproduct)
    ctx = context(bp, project)
    meas = ctx["meas"]
    inp = clean_inputs(m, inputs, meas)
    sim = simulate(m, inp, ctx)
    outs = [_moisture_output(m, inp, sim, ctx, meas, bp), _tpc_output(m, inp, sim, ctx, meas, bp),
            _tdf_output(m, inp, sim, ctx, meas, bp), _color_output(m, inp), _energy_output(m, inp, sim, ctx, bp)]
    return {"method": m, "byproduct": bp, "inputs": inp, "stage": sim.get("stage"), "outputs": outs,
            "summary": _summary(outs), "disclaimer": DISCLAIMER,
            "privacy": "시료는 '시료 n'으로만 표시합니다(로트·공급처·시료번호 없음).",
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}


def byproducts() -> list[str]:
    try:
        names = [r["pref_label_ko"] for r in db.rows(
            "SELECT c.pref_label_ko FROM byproduct b JOIN concept c ON c.concept_id=b.concept_id ORDER BY c.pref_label_ko")]
    except Exception:  # noqa: BLE001
        names = []
    if DEFAULT_BYPRODUCT in names:
        names.remove(DEFAULT_BYPRODUCT)
    return [DEFAULT_BYPRODUCT] + names


def models(method: str | None = None, byproduct: str | None = None, project: str | None = None) -> dict:
    m = method_or_error(method)
    bp = _canon_byproduct(byproduct)
    meas = measured(bp, project)
    reg = registry()
    used = {pid: {**{k: v for k, v in p.items() if k != "evidence"}, "evidence": evidence(pid)} for pid, p in reg["parameters"].items()}
    return {"method": m, "methods": ORDER, "byproduct": bp, "byproducts": byproducts(),
            "inputs": input_specs(m, meas), "outputs": OUTPUTS,
            "sources": reg["sources"], "parameters": used,
            "fits": {"drying": _fit_view(dry_fit()), "tpc": _fit_view(tpc_fit())},
            "measured": {"n_samples": meas["n_samples"], "tpc_ref": meas.get("tpc_ref"), "initial_moisture": meas.get("initial_moisture")},
            "equipment": equipment_view(m)["equipment"][m], "disclaimer": DISCLAIMER}


def _fit_view(f: dict) -> dict:
    return {"k_ref": round(f["k_ref"], 5), "ea_kj": round(f["ea_j"] / 1000, 3), "tref_c": f["tref_c"],
            "rmse_lnk": round(f["rmse"], 4), "range_c": f["range"], "points": f["residuals"]}


# ---------------------------------------------------------------- DOI 재확인(선택, 네트워크)

def verify_dois() -> list[dict]:
    """Crossref로 DOI가 살아 있고 제목이 맞는지 다시 확인한다. DOI만 보낸다(사용자 자료는 보내지 않는다)."""
    import urllib.request
    out = []
    for sid, s in registry()["sources"].items():
        try:
            with urllib.request.urlopen(f"https://api.crossref.org/works/{s['doi']}", timeout=15) as r:
                msg = json.loads(r.read().decode("utf-8"))["message"]
            title = (msg.get("title") or [""])[0]
            ok = title.strip().lower()[:40] == s["title"].strip().lower()[:40]
            out.append({"source": sid, "doi": s["doi"], "title_match": ok, "crossref_title": title})
        except Exception as ex:  # noqa: BLE001
            out.append({"source": sid, "doi": s["doi"], "error": str(ex)})
    return out


if __name__ == "__main__":  # python -m app.viz.predict verify
    import sys
    if sys.argv[1:] == ["verify"]:
        print(json.dumps(verify_dois(), ensure_ascii=False, indent=2))
