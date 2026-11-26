"""분석용 정돈 표(tidy: 한 행 = 한 런) + 코드북 만들기.

출처 세 가지:
- 예시(demo): 사과박 펙틴 산 추출 수율 — **가짜(모의) 데이터**. 고정 시드로 늘 같은 값.
- 내 실험(experiment): 런마다 조건(단계별 값; 런에 비워 둔 칸은 흐름 값으로 채움) + 내가 잰 값 + 비고의 '이름=값' 꼬리표.
  범주 조건(추출 단계의 산 종류·용매 종류, 건조 방식 등)은 범주 변수가 된다(acid, solvent, method).
  예전 방식인 비고 꼬리표('산=구연산; 반복=2')도 그대로 읽는다 — 같은 이름의 조건이 있으면 그 런의 조건 칸이 비었을 때
  꼬리표 값을 쓴다(런 조건 > 런 비고 꼬리표 > 흐름 값).
- 파일(upload): CSV·XLSX(내 실험 가져오기와 같은 읽기 규칙 — UTF-8·CP949, 머리글 줄 찾기, ND·'< 0.01').

변수 이름은 R·Stata에서 바로 쓰도록 ASCII 소문자 snake_case(32자 이하). 한국어 이름·단위·수준은 코드북에 둔다.
결측: 빈칸·ND(불검출)·검출 한계('< x', 기본은 결측으로 처리)·숫자가 아닌 글자 — 칸마다 이유를 남겨 분석에서 목록별 삭제 수와 함께 보인다.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..experiment import importer, steps as S, store, units as U

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
TTL_S = 3600
_uploads: dict[str, dict] = {}
_lock = threading.Lock()


class DataError(ValueError):
    pass


@dataclass
class Dataset:
    df: pd.DataFrame
    codebook: list[dict]
    source: dict
    title_ko: str
    title_en: str
    id_col: str = "run"
    is_demo: bool = False
    confidentiality: str | None = None
    missing: dict[str, dict] = field(default_factory=dict)  # 열 → {행 번호: 이유}
    warnings: list[str] = field(default_factory=list)

    def var(self, name: str) -> dict:
        for v in self.codebook:
            if v["name"] == name:
                return v
        raise DataError(f"'{name}' 변수가 데이터에 없습니다. 미리보기의 변수 이름 중에서 고르세요.")

    def run_labels(self) -> list[str]:
        return [str(x) for x in self.df[self.id_col]] if self.id_col in self.df else [f"row {i + 1}" for i in range(len(self.df))]


# ---------------------------------------------------------------- 이름·수준

KNOWN_LEVELS = {  # 산 이름 → ASCII 코드(R·Stata 수준 이름), 한국어·영어 표시 이름
    "구연산": ("citric", "구연산", "Citric acid"), "citric": ("citric", "구연산", "Citric acid"), "citricacid": ("citric", "구연산", "Citric acid"),
    "염산": ("HCl", "염산", "HCl"), "hcl": ("HCl", "염산", "HCl"), "hydrochloricacid": ("HCl", "염산", "HCl"),
    "질산": ("nitric", "질산", "Nitric acid"), "nitric": ("nitric", "질산", "Nitric acid"), "hno3": ("nitric", "질산", "Nitric acid"), "nitricacid": ("nitric", "질산", "Nitric acid"),
    "황산": ("sulfuric", "황산", "Sulfuric acid"), "sulfuric": ("sulfuric", "황산", "Sulfuric acid"), "h2so4": ("sulfuric", "황산", "Sulfuric acid"),
    "옥살산": ("oxalic", "옥살산", "Oxalic acid"), "oxalic": ("oxalic", "옥살산", "Oxalic acid"),
    "초산": ("acetic", "초산", "Acetic acid"), "아세트산": ("acetic", "아세트산", "Acetic acid"), "acetic": ("acetic", "아세트산", "Acetic acid"),
    "젖산": ("lactic", "젖산", "Lactic acid"), "lactic": ("lactic", "젖산", "Lactic acid"),
    "사과산": ("malic", "사과산", "Malic acid"), "malic": ("malic", "사과산", "Malic acid"),
    "없음": ("none", "없음", "None"), "none": ("none", "없음", "None"),
    # 용매 종류
    "물": ("water", "물", "Water"), "water": ("water", "물", "Water"),
    "에탄올": ("ethanol", "에탄올", "Ethanol"), "ethanol": ("ethanol", "에탄올", "Ethanol"),
    "에탄올수용액": ("aq_ethanol", "에탄올 수용액", "Aqueous ethanol"), "aqethanol": ("aq_ethanol", "에탄올 수용액", "Aqueous ethanol"),
    "메탄올": ("methanol", "메탄올", "Methanol"), "methanol": ("methanol", "메탄올", "Methanol"),
    "아세톤수용액": ("aq_acetone", "아세톤 수용액", "Aqueous acetone"), "aqacetone": ("aq_acetone", "아세톤 수용액", "Aqueous acetone"),
    "산수용액": ("aq_acid", "산 수용액", "Acidified water"), "aqacid": ("aq_acid", "산 수용액", "Acidified water"),
    # 건조 방식
    "열풍건조": ("hot_air", "열풍건조", "Hot-air drying"), "hotair": ("hot_air", "열풍건조", "Hot-air drying"),
    "동결건조": ("freeze", "동결건조", "Freeze drying"), "freeze": ("freeze", "동결건조", "Freeze drying"),
    "진공건조": ("vacuum", "진공건조", "Vacuum drying"), "vacuum": ("vacuum", "진공건조", "Vacuum drying"),
    "분무건조": ("spray", "분무건조", "Spray drying"), "spray": ("spray", "분무건조", "Spray drying"),
    "자연건조": ("sun", "자연건조", "Sun/air drying"), "sun": ("sun", "자연건조", "Sun/air drying"),
}
KNOWN_NAMES = [  # 한국어 열 이름 조각 → (변수 이름, 영어 이름, 기본 단위). 위에서부터 확인.
    (["산종류", "산의종류", "사용산", "산", "acid", "acidtype"], "acid", "Acid type", ""),
    (["펙틴수율", "pectinyield"], "yield_pct", "Pectin yield", "%"),
    (["수율", "yield"], "yield_pct", "Yield", "%"),
    (["추출온도", "온도", "temperature", "temp"], "temp_c", "Temperature", "℃"),
    (["추출시간", "시간", "time"], "time_min", "Time", "min"),
    (["반복", "rep", "replicate"], "rep", "Replicate", ""),
    (["순서", "order", "runorder"], "run_order", "Run order", ""),
    (["런", "run", "시료", "시료명", "이름", "name", "id", "번호", "no"], "run", "Run", ""),
    (["ph"], "ph", "pH", ""),
    (["고액비", "용매비", "ratio"], "ratio_ml_g", "Liquid-to-solid ratio", "mL/g"),
    (["용매종류", "용매", "solvent", "solventtype"], "solvent", "Solvent", ""),
    (["농도", "conc"], "conc", "Concentration", ""),
]


def _k(s) -> str:
    return re.sub(r"[\s_\-·.:/()（）\[\]]+", "", str(s or "").lower())


def level_info(raw) -> tuple[str, str, str]:
    """원래 수준 글자 → (ASCII 코드, 한국어 이름, 영어 이름)."""
    s = str(raw).strip()
    hit = KNOWN_LEVELS.get(_k(s)) or KNOWN_LEVELS.get(s)
    if hit:
        return hit
    code = s if s.isascii() else s
    return code, s, s


def slug(text: str, fallback: str) -> str:
    s = re.sub(r"[\(（][^\)）]*[\)）]", " ", str(text or ""))
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    if not s or not s[0].isalpha():
        return fallback
    return s[:32]


def guess_name(header: str, fallback: str) -> tuple[str, str, str]:
    """열 이름 → (변수 이름, 영어 이름, 기본 단위)."""
    hk = _k(re.sub(r"[\(（][^\)）]*[\)）]", " ", header))
    for words, name, en, unit in KNOWN_NAMES:
        if hk in words or any(len(w) >= 2 and w in hk for w in words if w not in ("산", "no", "id", "ph")):
            if name == "time_min":
                u = (importer._unit_of(header) or "").lower()
                if u in ("h", "hr", "시간"):
                    return "time_h", en, "h"
            return name, en, unit
    return slug(header, fallback), slug(header, fallback).replace("_", " ").capitalize(), ""


def unique_names(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        if n in seen:
            seen[n] += 1
            n2 = f"{n[:29]}_{seen[n]}"
            while n2 in seen:
                seen[n] += 1
                n2 = f"{n[:29]}_{seen[n]}"
            seen[n2] = 1
            out.append(n2)
        else:
            seen[n] = 1
            out.append(n)
    return out


def check_name(n: str) -> str:
    n = str(n or "").strip()
    if not NAME_RE.match(n):
        raise DataError(f"변수 이름 '{n}'는 R·Stata에서 쓸 수 없습니다. 영문 소문자로 시작하는 32자 이하 영문 소문자·숫자·밑줄로 바꾸세요(예: yield_pct).")
    return n


# ---------------------------------------------------------------- 칸 읽기

def read_number(raw, censored: str = "exclude") -> tuple[float | None, str | None]:
    """칸 → (값, 결측 이유). censored: exclude(결측) | limit(검출 한계 값) | half(한계의 1/2)."""
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None, "빈칸"
    value, text, kind = U.parse_cell(raw)
    if kind is None:
        return None, "빈칸"
    if kind == "num":
        return value, None
    if kind == "nd":
        return None, "ND(불검출)"
    if kind == "censored":
        if censored == "limit":
            return value, None
        if censored == "half":
            return value / 2, None
        return None, f"검출 한계({text})"
    return None, f"숫자 아님('{str(text)[:20]}')"


# ---------------------------------------------------------------- 예시(가짜) 데이터

DEMO_SEED = 20261125
DEMO_ACIDS = [("citric", "구연산", "Citric acid", 0.0), ("HCl", "염산", "HCl", 1.9), ("nitric", "질산", "Nitric acid", 1.1)]


def demo(levels: int = 2) -> Dataset:
    """사과박 펙틴 산 추출 수율 — 모의 데이터(가짜). 3 온도 × 3 시간 × 산 × 반복 3, 고정 시드.
    참 모델(모의에 쓴 값): 수율 = 13.8 + 0.16·(T − 80) + 0.008·(t − 90) + 산 효과(HCl +1.9, 질산 +1.1) + N(0, 1.0²)."""
    levels = 3 if int(levels or 2) >= 3 else 2
    rng = np.random.default_rng(DEMO_SEED + levels)
    acids = DEMO_ACIDS[:levels]
    rows = []
    for code, _ko, _en, eff in acids:
        for T in (70, 80, 90):
            for t in (60, 90, 120):
                for rep in (1, 2, 3):
                    y = 13.8 + 0.16 * (T - 80) + 0.008 * (t - 90) + eff + rng.normal(0, 1.0)
                    rows.append({"run": f"{code[:3].upper()}-{T}-{t}-r{rep}", "temp_c": float(T), "time_min": float(t),
                                 "acid": code, "rep": rep, "yield_pct": round(float(y), 2)})
    order = rng.permutation(len(rows))
    for i, r in enumerate(rows):
        r["run_order"] = int(order[i]) + 1
    df = pd.DataFrame(rows)[["run", "run_order", "acid", "temp_c", "time_min", "rep", "yield_pct"]]
    lost = df.index[df["run"] == "CIT-90-120-r3"][0]  # 결측 처리 예시: 한 런의 시료 유실
    df.loc[lost, "yield_pct"] = np.nan
    cb = [
        {"name": "run", "label_ko": "런", "label_en": "Run", "unit": "", "type": "id", "source": "모의"},
        {"name": "run_order", "label_ko": "실험 순서", "label_en": "Run order", "unit": "", "type": "id", "source": "모의(무작위 순서)"},
        {"name": "acid", "label_ko": "산 종류", "label_en": "Acid type", "unit": "", "type": "categorical", "source": "모의",
         "levels": [{"value": c, "label_ko": ko, "label_en": en} for c, ko, en, _ in acids]},
        {"name": "temp_c", "label_ko": "추출 온도", "label_en": "Extraction temperature", "unit": "℃", "type": "continuous", "source": "모의"},
        {"name": "time_min", "label_ko": "추출 시간", "label_en": "Extraction time", "unit": "min", "type": "continuous", "source": "모의"},
        {"name": "rep", "label_ko": "반복", "label_en": "Replicate", "unit": "", "type": "id", "source": "모의"},
        {"name": "yield_pct", "label_ko": "펙틴 수율", "label_en": "Pectin yield", "unit": "%", "type": "continuous", "source": "모의",
         "note": "건조 사과박 대비 % (w/w)"},
    ]
    title = "사과박 펙틴 산 추출 수율 (예시·가짜 데이터)"
    return Dataset(df=df, codebook=cb, source={"kind": "demo", "levels": levels}, title_ko=title,
                   title_en="Apple pomace pectin yield by acid extraction (demo, simulated data)", is_demo=True,
                   missing={"yield_pct": {int(lost): "시료 유실(예시)"}},
                   warnings=["예시 데이터는 가짜(모의)입니다 — 실제 측정값이 아닙니다. 논문에 쓰지 마세요."])


# ---------------------------------------------------------------- 내 실험

# 영어 이름(표·그림·해석의 English 출력용): 단계 종류 + 조건 키, 실측 대상 키
STEP_EN = {"feed": "Raw material", "wash": "Washing", "press": "Pressing", "mill": "Milling", "dry": "Drying",
           "sieve": "Sieving", "extract": "Extraction", "store": "Storage"}
PARAM_EN = {"temp_c": "temperature", "time_min": "time", "time_h": "time", "ethanol_pct": "ethanol concentration",
            "ratio_ml_g": "liquid-to-solid ratio", "moisture_pct": "moisture", "tpc_mg_g": "TPC", "tdf_g_100g": "TDF",
            "mass_kg": "mass", "target_moisture_pct": "moisture after pressing", "particle_mm": "particle size", "mesh_um": "mesh size",
            "yield_pct": "set yield", "air_velocity_ms": "air velocity", "thickness_mm": "layer thickness", "pressure_pa": "pressure",
            "rh": "relative humidity", "days": "storage time", "outlet_c": "outlet temperature", "target_moisture": "target moisture",
            "method": "method", "package": "packaging", "acid": "acid type", "solvent": "solvent"}
TARGET_EN = {"moisture": "Moisture", "mass": "Mass", "dm_yield": "Dry-matter yield", "tpc": "TPC", "tpc_ret": "TPC retention",
             "tdf": "TDF", "time_target": "Time to target moisture", "energy": "Specific energy", "energy_total": "Drying energy",
             "sieve_yield": "Sieve yield", "tpc_extract_yield": "TPC extraction yield", "extract_tpc": "Extract TPC",
             "extract_solids": "Extract solids yield", "product_yield": "Yield"}


def _cond_en(step_type: str | None, key: str, spec: dict | None) -> str:
    if spec and spec.get("label_en"):
        return spec["label_en"]
    p = PARAM_EN.get(key)
    if not p:
        return f"{step_type or ''} {key}".strip()
    if key in ("acid", "solvent"):
        return p[:1].upper() + p[1:]
    s = STEP_EN.get(step_type or "", "")
    return f"{s} {p}" if s else p[:1].upper() + p[1:]


TAG_RE = re.compile(r"^\s*([^=:]{1,20}?)\s*[=:]\s*(.+?)\s*$")


def note_tags(note: str | None) -> dict[str, str]:
    out = {}
    for part in re.split(r"[;,\n]+", note or ""):
        m = TAG_RE.match(part)
        if m and m.group(2):
            out[m.group(1).strip()] = m.group(2).strip()
    return out


def _joinlab(step: str, item: str) -> str:
    """'추출' + '추출 온도' → '추출 온도' (단계 이름이 이미 들어 있으면 되풀이하지 않음)."""
    if not step or item.replace(" ", "").startswith(step.replace(" ", "")):
        return item
    return f"{step} · {item}"


def from_experiment(exp_id: str, censored: str = "exclude") -> Dataset:
    exp = store.get_experiment(exp_id)
    runs = exp["runs"]
    if not runs:
        raise DataError("이 실험에 런이 없습니다. '실험 데이터' 탭에서 런을 넣거나 CSV를 가져온 뒤 다시 고르세요.")
    steps = exp["flow"]["steps"]
    order = {s["key"]: i for i, s in enumerate(steps)}
    smap = {s["key"]: s for s in steps}
    type_count: dict[str, int] = {}
    for s in steps:
        type_count[s["type"]] = type_count.get(s["type"], 0) + 1

    def prefix(sk):
        st = smap.get(sk)
        if not st:
            return sk or "x"
        return st["type"] if type_count[st["type"]] == 1 else st["key"].lower()

    # 1) 조건: 어느 런에든 넣은 (단계, 조건)
    conds = []
    for r in runs:
        for sk, c in r["conditions"].items():
            for pk in c:
                if (sk, pk) not in conds:
                    conds.append((sk, pk))
    conds.sort(key=lambda x: order.get(x[0], 99))
    # 2) 실측값: (단계, 대상, 기준)
    vals = []
    for r in runs:
        for v in r["values"]:
            if v["kind"] == "measured" and (v["step_key"], v["target"], v["basis"]) not in vals:
                vals.append((v["step_key"], v["target"], v["basis"]))
    vals.sort(key=lambda x: order.get(x[0] or "", 99))
    # 3) 비고 꼬리표
    tags = []
    for r in runs:
        for k in note_tags(r["note"]):
            if k not in tags:
                tags.append(k)

    # 3') 같은 이름의 범주 조건이 있는 꼬리표(예: 조건 acid + 비고 '산=')는 따로 열을 만들지 않고 빈 조건 칸의 대신 값으로 쓴다
    sel_specs = {}
    for sk, pk in conds:
        st = smap.get(sk)
        spec = next((s for s in S.specs_for(st["type"], st["params"]) if s["key"] == pk), None) if st else None
        if spec and spec.get("type") == "select":
            sel_specs.setdefault(pk.lower(), (sk, pk))
    # 런 조건에는 없고 꼬리표로만 준 범주(예: 비고 '산=')도, 흐름에 같은 이름의 범주 조건 칸이 있으면 그 조건 열로 읽는다
    for st in steps:
        for spec in S.specs_for(st["type"], st["params"]):
            if spec.get("free") and spec["key"] not in sel_specs and any(guess_name(t, "tag")[0] == spec["key"] for t in tags):
                conds.append((st["key"], spec["key"]))
                sel_specs[spec["key"]] = (st["key"], spec["key"])
    conds.sort(key=lambda x: order.get(x[0], 99))
    tag_for: dict[tuple, str] = {}
    for t in list(tags):
        g = guess_name(t, "tag")[0]
        if g in sel_specs and sel_specs[g] not in tag_for:
            tag_for[sel_specs[g]] = t
            tags.remove(t)
    raw_names, cb, cols, missing, warn = [], [], {}, {}, []
    from_tag = 0
    filled = 0
    for sk, pk in conds:
        st = smap.get(sk)
        spec = next((s for s in S.specs_for(st["type"], st["params"]) if s["key"] == pk), None) if st else None
        raw_names.append(("cond", sk, pk, spec))
    for sk, tgt, basis in vals:
        raw_names.append(("val", sk, tgt, basis))
    for t in tags:
        raw_names.append(("tag", None, t, None))
    # 이름: 조건은 파라미터 키(겹치면 단계 앞말), 실측은 대상 키(겹치면 단계 앞말), 꼬리표는 알려진 이름
    base = []
    for kind, sk, a, b in raw_names:
        if kind == "cond":
            base.append(a.lower())
        elif kind == "val":
            tk = U.canon_target(a)
            base.append((tk or slug(a, "y")) + ("_wb" if b == "습량" and tk in ("tpc", "tdf") else ""))
        else:
            base.append(guess_name(a, "tag")[0])
    dup = {n for n in base if base.count(n) > 1}
    names = []
    for (kind, sk, a, b), n in zip(raw_names, base):
        names.append(f"{prefix(sk)}_{n}"[:32] if (n in dup and kind != "tag") else n)
    names = unique_names(["run"] + [n if NAME_RE.match(n) else f"v{i + 1}" for i, n in enumerate(names)])[1:]

    labels = [r["label"] or r["alias"] for r in runs]
    cols["run"] = labels
    cb.append({"name": "run", "label_ko": "런", "label_en": "Run", "unit": "", "type": "id", "source": "실험 런 이름"})
    for (kind, sk, a, b), name in zip(raw_names, names):
        st = smap.get(sk) if sk else None
        if kind == "cond":
            spec = b
            is_sel = bool(spec and spec.get("type") == "select")
            col, miss, lv = [], {}, []
            tag = tag_for.get((sk, a))
            for i, r in enumerate(runs):
                v = (r["conditions"].get(sk) or {}).get(a)
                if v in (None, "") and tag:
                    v = note_tags(r["note"]).get(tag)
                    if v not in (None, ""):
                        v = S.canon_choice(spec, v) if spec and spec.get("free") else v
                        from_tag += 1
                if v in (None, "") and st:
                    v = store.merged_params(st, r).get(a, spec.get("default") if spec else None)
                    if v not in (None, ""):
                        filled += 1
                if v in (None, ""):
                    miss[i] = "빈칸"
                    col.append(None)
                elif is_sel:
                    code, ko, en_l = level_info(v)
                    col.append(code)
                    if code not in [x["value"] for x in lv]:
                        lv.append({"value": code, "label_ko": ko, "label_en": en_l})
                else:
                    col.append(float(v))
            cols[name] = col
            if miss:
                missing[name] = miss
            entry = {"name": name, "label_ko": _joinlab(st["label"] if st else sk, spec["label"] if spec else a),
                     "label_en": _cond_en(st["type"] if st else None, a, spec), "unit": (spec or {}).get("unit", ""),
                     "type": "categorical" if is_sel else "continuous",
                     "source": f"조건 [{sk}] {a}" + (f" (빈 칸은 비고 꼬리표 '{tag}=')" if tag else "")}
            if is_sel:
                entry["levels"] = lv
            cb.append(entry)
        elif kind == "val":
            tgt, basis = a, b
            tk = U.canon_target(tgt)
            unit = S.TARGETS[tk]["unit"] if tk else ""
            if tk in ("tpc", "tdf", "moisture"):
                unit = unit.replace(" 건량", "").replace(" 습량", "") + (f" {basis}" if basis else "")
            col, miss = [], {}
            for i, r in enumerate(runs):
                v = next((x for x in r["values"] if x["kind"] == "measured" and x["step_key"] == sk and x["target"] == tgt
                          and x["basis"] == basis), None)
                if not v:
                    col.append(None)
                    miss[i] = "빈칸"
                    continue
                txt = v["value_text"]
                if v["value"] is None:
                    col.append(None)
                    miss[i] = "ND(불검출)" if txt in ("ND", "불검출") else f"숫자 아님('{txt}')"
                elif txt and str(txt)[:1] in "<>≤≥" or (txt and re.search(r"(미만|이하|초과|이상)$", str(txt))):
                    if censored == "limit":
                        col.append(float(v["value"]))
                    elif censored == "half":
                        col.append(float(v["value"]) / 2)
                    else:
                        col.append(None)
                        miss[i] = f"검출 한계({txt})"
                else:
                    col.append(float(v["value"]))
            cols[name] = col
            if miss:
                missing[name] = miss
            cb.append({"name": name, "label_ko": _joinlab(st["label"] if st else "", tgt), "label_en": TARGET_EN.get(tk) or slug(tgt, name),
                       "unit": unit, "type": "continuous", "source": f"실측 [{sk}] {tgt}" + (f" ({basis})" if basis else "")})
        else:
            raw = [note_tags(r["note"]).get(a) for r in runs]
            present = [x for x in raw if x not in (None, "")]
            numeric = present and all(U.parse_cell(x)[2] == "num" for x in present)
            name_guess, en, unit = guess_name(a, name)
            miss = {i: "빈칸" for i, x in enumerate(raw) if x in (None, "")}
            if numeric:
                cols[name] = [U.parse_cell(x)[0] if x not in (None, "") else None for x in raw]
                typ = "id" if name in ("rep", "run_order") else "continuous"
                cb.append({"name": name, "label_ko": a, "label_en": en, "unit": unit, "type": typ, "source": f"비고 꼬리표 '{a}='"})
            else:
                infos = {x: level_info(x) for x in present}
                cols[name] = [infos[x][0] if x not in (None, "") else None for x in raw]
                lv = []
                for x in present:
                    c, ko, en_l = infos[x]
                    if c not in [y["value"] for y in lv]:
                        lv.append({"value": c, "label_ko": ko, "label_en": en_l})
                cb.append({"name": name, "label_ko": a, "label_en": en, "unit": "", "type": "categorical", "levels": lv,
                           "source": f"비고 꼬리표 '{a}='"})
            if miss:
                missing[name] = miss
    df = pd.DataFrame(cols)
    for v in cb:
        if v["type"] == "continuous":
            df[v["name"]] = pd.to_numeric(df[v["name"]], errors="coerce").astype(float)
    if filled:
        warn.append(f"런에 비워 둔 조건 {filled}칸은 흐름에 넣은 값(또는 단계 기본값)으로 채웠습니다 — 런마다 실제 조건을 넣으면 더 정확합니다.")
    if from_tag:
        warn.append(f"조건 칸이 빈 {from_tag}칸은 런 비고 꼬리표(예: '산=구연산') 값으로 채웠습니다 — 실험 데이터 탭의 조건 칸(예: 추출 · 산 종류)에 넣으면 꼬리표 없이 읽습니다.")
    if not any(v["type"] == "categorical" for v in cb):
        warn.append("범주 변수(예: 산 종류)가 없습니다. 실험 데이터 탭에서 '열 추가 → 추출 · 산 종류'로 런마다 산을 넣으세요"
                    " (예전 방식: 런 비고에 '산=구연산'처럼 '이름=값').")
    if exp["confidentiality"] == "기밀":
        warn.append("기밀 실험입니다 — 내려받은 표·그림·데이터 파일은 이 PC 밖으로 보낼 때 등급에 맞게 다루세요(앱은 밖으로 보내지 않습니다).")
    return Dataset(df=df, codebook=cb, source={"kind": "experiment", "exp_id": exp_id}, title_ko=exp["name"], title_en=exp["name"],
                   confidentiality=exp["confidentiality"], missing=missing, warnings=warn)


# ---------------------------------------------------------------- 파일

def _gc() -> None:
    now = time.time()
    for k in [k for k, v in _uploads.items() if now - v["t"] > TTL_S]:
        _uploads.pop(k, None)
    while len(_uploads) > 20:
        _uploads.pop(min(_uploads, key=lambda k: _uploads[k]["t"]))


def upload(file_name: str, content: bytes) -> dict:
    """파일을 메모리에만 1시간 두고 열 대응(짐작)을 돌려준다."""
    try:
        grid = importer.read_grid(file_name, content)
    except importer.ImportError_ as ex:
        raise DataError(str(ex)) from ex
    hi = importer._header_row(grid)
    header = [importer._cell_str(c) for c in grid[hi]]
    data = [list(r) + [None] * (len(header) - len(r)) for r in grid[hi + 1:]]
    token = uuid.uuid4().hex
    with _lock:
        _gc()
        _uploads[token] = {"file_name": file_name, "header": header, "data": data, "t": time.time()}
    return {"token": token, "file_name": file_name, "n_rows": len(data), "mapping": guess_mapping(header, data)}


def guess_mapping(header: list[str], data: list[list]) -> list[dict]:
    out, names = [], []
    for i, h in enumerate(header):
        cells = [r[i] for r in data if i < len(r) and r[i] not in (None, "") and str(r[i]).strip()]
        kinds = [U.parse_cell(c)[2] for c in cells]
        numeric_share = sum(k in ("num", "censored", "nd") for k in kinds) / len(kinds) if kinds else 0
        name, en, unit0 = guess_name(h, f"x{i + 1}")
        unit = importer._unit_of(h) or unit0
        if name == "run" or (numeric_share < 0.8 and len(set(map(str, cells))) > max(10, len(cells) * 0.6)):
            typ = "id"
        elif numeric_share >= 0.8:
            typ = "id" if name in ("rep", "run_order") else "continuous"
        else:
            typ = "categorical"
        names.append(name)
        label = re.sub(r"\s*[\(（][^\)）]*[\)）]\s*", " ", h).strip() or f"열 {i + 1}"
        out.append({"index": i, "header": h, "name": name, "label_ko": label, "label_en": en, "unit": unit or "", "type": typ,
                    "sample": [importer._cell_str(r[i]) for r in data[:3] if i < len(r)]})
    for m, n in zip(out, unique_names(names)):
        m["name"] = n
    return out


def from_upload(token: str, mapping: list[dict] | None = None, censored: str = "exclude") -> Dataset:
    with _lock:
        up = _uploads.get(token)
    if not up:
        raise DataError("올린 파일이 만료되었습니다(1시간). 파일을 다시 올리세요.")
    header, data = up["header"], up["data"]
    mapping = mapping or guess_mapping(header, data)
    used = [m for m in mapping if m.get("type") not in (None, "ignore")]
    if not used:
        raise DataError("쓸 열이 없습니다. 열마다 역할(연속·범주·런 이름)을 고르세요.")
    names = [check_name(m["name"]) for m in used]
    if len(set(names)) != len(names):
        dup = sorted({n for n in names if names.count(n) > 1})
        raise DataError(f"변수 이름 {', '.join(dup)}이(가) 겹칩니다. 열마다 다른 이름을 쓰세요.")
    cols, cb, missing = {}, [], {}
    id_col = next((m["name"] for m in used if m["type"] == "id" and m["name"] == "run"), None) or \
        next((m["name"] for m in used if m["type"] == "id"), None)
    for m in used:
        i = int(m["index"])
        if i >= len(header):
            raise DataError(f"'{m['name']}' 열 번호 {i}가 파일에 없습니다. 파일을 다시 올리세요.")
        raw = [r[i] if i < len(r) else None for r in data]
        miss = {}
        entry = {"name": m["name"], "label_ko": m.get("label_ko") or m.get("header") or m["name"],
                 "label_en": m.get("label_en") or m["name"], "unit": m.get("unit") or "", "type": m["type"],
                 "source": f"파일 열 '{header[i]}'"}
        if m["type"] == "continuous":
            col = []
            for j, c in enumerate(raw):
                v, why = read_number(c, censored)
                col.append(v)
                if why:
                    miss[j] = why
            cols[m["name"]] = col
        elif m["type"] == "categorical":
            col, lv = [], []
            for j, c in enumerate(raw):
                s = importer._cell_str(c).strip()
                if not s:
                    col.append(None)
                    miss[j] = "빈칸"
                    continue
                code, ko, en = level_info(s)
                col.append(code)
                if code not in [x["value"] for x in lv]:
                    lv.append({"value": code, "label_ko": ko, "label_en": en})
            cols[m["name"]] = col
            entry["levels"] = lv
        else:
            cols[m["name"]] = [importer._cell_str(c) for c in raw]
        if miss:
            missing[m["name"]] = miss
        cb.append(entry)
    if id_col is None:
        cols = {"run": [f"row {j + 2}" for j in range(len(data))], **cols}
        cb.insert(0, {"name": "run", "label_ko": "행", "label_en": "Row", "unit": "", "type": "id", "source": "파일 행 번호"})
        id_col = "run"
    df = pd.DataFrame(cols)
    for v in cb:
        if v["type"] == "continuous":
            df[v["name"]] = pd.to_numeric(df[v["name"]], errors="coerce").astype(float)
    warn = []
    nd = sum(1 for col in missing.values() for why in col.values() if why.startswith("검출 한계"))
    if nd:
        warn.append(f"검출 한계('< x') 칸 {nd}개는 결측으로 두었습니다. 한계값이나 한계의 1/2로 넣으려면 '검출 한계 처리'를 바꾸세요.")
    return Dataset(df=df, codebook=cb, source={"kind": "upload", "token": token, "file_name": up["file_name"]},
                   title_ko=up["file_name"], title_en=up["file_name"], id_col=id_col, missing=missing, warnings=warn)


# ---------------------------------------------------------------- 공통

def load(source: dict) -> Dataset:
    source = source or {}
    kind = source.get("kind") or "demo"
    censored = source.get("censored") or "exclude"
    if censored not in ("exclude", "limit", "half"):
        raise DataError("검출 한계 처리는 exclude(결측)·limit(한계값)·half(한계의 1/2) 중 하나로 고르세요.")
    if kind == "demo":
        return demo(int(source.get("levels") or 2))
    if kind == "experiment":
        if not source.get("exp_id"):
            raise DataError("분석할 실험을 고르세요.")
        try:
            return from_experiment(source["exp_id"], censored)
        except store.NotFound as ex:
            raise DataError(str(ex)) from ex
    if kind == "upload":
        if not source.get("token"):
            raise DataError("먼저 CSV·XLSX 파일을 올리세요.")
        return from_upload(source["token"], source.get("mapping"), censored)
    raise DataError(f"'{kind}'는 없는 데이터 출처입니다. demo·experiment·upload 중 하나를 쓰세요.")


def suggest_spec(ds: Dataset) -> dict:
    cont = [v for v in ds.codebook if v["type"] == "continuous"]
    cats = [v for v in ds.codebook if v["type"] == "categorical" and len(v.get("levels") or []) >= 2]
    outcome = next((v["name"] for v in cont if "yield" in v["name"] or "수율" in v["label_ko"]), None) or (cont[-1]["name"] if cont else None)
    preds = [v["name"] for v in cont if v["name"] != outcome and ds.df[v["name"]].nunique(dropna=True) >= 2]
    cat_specs = [{"name": v["name"], "reference": v["levels"][0]["value"]} for v in cats[:1]]
    return {"outcome": outcome, "continuous": preds, "categorical": cat_specs,
            "group": cat_specs[0]["name"] if cat_specs else None, "test": "welch", "alpha": 0.05}


def preview(ds: Dataset, limit: int = 100) -> dict:
    rows = []
    for i, r in enumerate(ds.df.head(limit).to_dict("records")):
        rows.append({k: (None if (isinstance(v, float) and np.isnan(v)) else v) for k, v in r.items()})
    miss_count = {k: len(v) for k, v in ds.missing.items()}
    return {"title": ds.title_ko, "title_en": ds.title_en, "is_demo": ds.is_demo, "source": ds.source, "n": len(ds.df),
            "codebook": ds.codebook, "rows": rows, "missing": {k: {str(i): w for i, w in v.items()} for k, v in ds.missing.items()},
            "missing_count": miss_count, "warnings": ds.warnings, "suggested": suggest_spec(ds), "confidentiality": ds.confidentiality}
