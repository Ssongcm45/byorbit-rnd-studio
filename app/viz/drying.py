"""건조 방식 모델: 공정 단계·일반 조건·기전·예상 효과, 물의 상평형도와 공정 경로,
전처리 표기 파서, 방식별 측정값 비교, 3D 입자 단면 모델 파라미터.

여기 적힌 조건·효과는 문헌에서 흔히 보고되는 '일반 경향'이다. 측정값이 아니다.
측정값은 compare()만 DB에서 읽는다.
"""
from __future__ import annotations

import math
import re
import statistics

from .. import db

GENERAL_NOTE = "일반 문헌 경향을 요약한 참고값입니다. 실제 시료의 측정값이 아닙니다."
ILLUSTRATIVE_NOTE = "입자 단면은 방식 간 차이를 보여주기 위한 개념도(정성적)입니다. 실제 미세구조 측정값이 아닙니다."

ORDER = ["동결건조", "열풍건조", "진공건조", "분무건조", "자연건조"]

METHODS: dict[str, dict] = {
    "동결건조": {
        "en": "Freeze drying", "kind": "freeze",
        "summary": "얼린 뒤 감압해 얼음을 바로 수증기로 승화시킨다. 열을 거의 받지 않아 형태·성분 보존이 가장 좋다.",
        "stages": [
            {"name": "예비동결", "desc": "시료를 -40 ~ -80 ℃로 얼려 수분을 얼음 결정으로 만든다.", "temp_c": [-80, -40], "pressure_pa": [101325, 101325], "time_h": [2, 6]},
            {"name": "1차 건조(승화)", "desc": "10 ~ 30 Pa로 감압하고 선반을 살짝 데워 얼음을 승화시킨다. 수분 대부분이 이 단계에서 빠진다.", "temp_c": [-40, -20], "pressure_pa": [5, 30], "time_h": [12, 48]},
            {"name": "2차 건조(탈착)", "desc": "온도를 20 ~ 40 ℃로 올려 결합수를 탈착시킨다.", "temp_c": [20, 40], "pressure_pa": [1, 10], "time_h": [4, 12]},
        ],
        "params": {"temp_c": [-50, 40], "pressure_pa": [1, 30], "time_h": [24, 72]},
        "mechanism": "삼중점(0.01 ℃, 611.657 Pa) 아래에서 고체 → 기체 승화. 얼음 결정이 빠진 자리가 기공으로 남는다.",
        "effects": {"다공성": "매우 높음 — 얼음 결정 자리가 열린 기공으로 남음",
                    "색·갈변": "갈변 거의 없음, 원래 색 유지",
                    "열에 약한 폴리페놀 보존": "가장 높음",
                    "수축": "매우 적음(형태 유지)",
                    "재수화·보수력": "빠르고 높음",
                    "비용·시간": "장비·전력비가 가장 큼, 1 ~ 3일"},
    },
    "열풍건조": {
        "en": "Hot-air drying", "kind": "hotair",
        "summary": "뜨거운 공기를 불어 표면에서 수분을 증발시킨다. 싸고 빠르지만 열·산소 노출이 크다.",
        "stages": [
            {"name": "예열(초기 조정)", "desc": "시료 온도가 열풍 습구온도까지 오른다.", "temp_c": [20, 40], "pressure_pa": [101325, 101325], "time_h": [0.2, 0.5]},
            {"name": "항률 건조", "desc": "표면이 젖어 있는 동안 증발 속도가 일정하다(표면 증발 지배).", "temp_c": [40, 60], "pressure_pa": [101325, 101325], "time_h": [1, 4]},
            {"name": "감률 건조", "desc": "내부 수분 확산이 느려지며 표면이 굳고(표면 경화) 품온이 열풍 온도에 가까워진다.", "temp_c": [55, 80], "pressure_pa": [101325, 101325], "time_h": [4, 20]},
        ],
        "params": {"temp_c": [50, 80], "pressure_pa": [101325, 101325], "time_h": [6, 24]},
        "mechanism": "대기압에서 액체 → 기체 증발. 열은 대류로 들어오고 수분은 표면으로 확산해 나간다.",
        "effects": {"다공성": "낮음 — 세포벽이 무너지며 조밀해짐",
                    "색·갈변": "마이야르·효소적 갈변으로 어두워짐(온도·시간에 비례)",
                    "열에 약한 폴리페놀 보존": "낮음 ~ 중간(고온·장시간일수록 감소)",
                    "수축": "큼(부피 50 ~ 80% 감소 보고)",
                    "재수화·보수력": "느리고 낮음",
                    "비용·시간": "가장 저렴, 반나절 ~ 하루"},
    },
    "진공건조": {
        "en": "Vacuum drying", "kind": "vacuum",
        "summary": "감압으로 물의 끓는점을 낮춰 낮은 온도에서 증발시킨다. 산소가 적어 산화가 덜하다.",
        "stages": [
            {"name": "감압", "desc": "챔버를 2 ~ 20 kPa로 낮춘다(물 끓는점 약 17 ~ 60 ℃).", "temp_c": [20, 30], "pressure_pa": [2000, 20000], "time_h": [0.2, 0.5]},
            {"name": "가열 증발", "desc": "선반 전도로 40 ~ 70 ℃를 주며 낮은 끓는점에서 증발시킨다.", "temp_c": [40, 70], "pressure_pa": [2000, 20000], "time_h": [4, 12]},
            {"name": "마무리 건조", "desc": "압력을 더 낮춰 남은 수분을 뺀다.", "temp_c": [50, 70], "pressure_pa": [500, 5000], "time_h": [1, 4]},
        ],
        "params": {"temp_c": [40, 70], "pressure_pa": [500, 20000], "time_h": [6, 18]},
        "mechanism": "감압으로 포화 증기압 곡선을 아래로 넘어 낮은 온도에서 액체 → 기체. 산소 분압이 낮다.",
        "effects": {"다공성": "중간 — 감압 팽화로 약간의 기공",
                    "색·갈변": "열풍보다 적음(산소가 적음)",
                    "열에 약한 폴리페놀 보존": "중간 ~ 높음",
                    "수축": "중간",
                    "재수화·보수력": "중간",
                    "비용·시간": "중간, 반나절 ~ 하루"},
    },
    "분무건조": {
        "en": "Spray drying", "kind": "spray",
        "summary": "액상(추출액·슬러리)을 미세 액적으로 뿜어 뜨거운 공기 속에서 몇 초 만에 말린다. 분말이 바로 나온다.",
        "stages": [
            {"name": "분무(미립화)", "desc": "노즐·회전 원판으로 10 ~ 200 µm 액적을 만든다.", "temp_c": [20, 40], "pressure_pa": [101325, 101325], "time_h": [0, 0.001]},
            {"name": "액적 건조", "desc": "입구 150 ~ 200 ℃ 열풍 속에서 증발 냉각으로 액적 온도는 40 ~ 60 ℃에 머문다. 수 초.", "temp_c": [40, 60], "pressure_pa": [101325, 101325], "time_h": [0.0003, 0.003]},
            {"name": "분말 회수", "desc": "출구 70 ~ 90 ℃, 사이클론으로 분말을 모은다. 껍질이 먼저 굳어 속이 빈 입자가 흔하다.", "temp_c": [70, 90], "pressure_pa": [101325, 101325], "time_h": [0.001, 0.01]},
        ],
        "params": {"temp_c": [150, 200], "pressure_pa": [101325, 101325], "time_h": [0.0003, 0.01], "outlet_c": [70, 90]},
        "mechanism": "대기압 증발. 체류 시간이 매우 짧고 증발 냉각으로 입자 온도가 열풍보다 훨씬 낮다. 당이 많으면 벽면 부착(유리전이) 문제가 생겨 덱스트린 등 담체를 쓴다.",
        "effects": {"다공성": "중간 — 속이 빈 구형(껍질 + 공동)",
                    "색·갈변": "적음 ~ 중간(체류가 짧음)",
                    "열에 약한 폴리페놀 보존": "중간 ~ 높음(담체로 캡슐화 시 높음)",
                    "수축": "껍질이 주름질 수 있음",
                    "재수화·보수력": "용해성 좋음",
                    "비용·시간": "연속 공정, 대량에 유리. 고형분 액상만 가능"},
    },
    "자연건조": {
        "en": "Sun / air drying", "kind": "sun",
        "summary": "햇볕·바람(천일건조·양건) 또는 그늘(음건)에서 상온으로 말린다. 비용은 없지만 시간이 길고 위생·날씨 영향이 크다.",
        "stages": [
            {"name": "펼치기", "desc": "얇게 펴서 통풍이 잘 되게 한다.", "temp_c": [10, 30], "pressure_pa": [101325, 101325], "time_h": [0.5, 1]},
            {"name": "주간 증발", "desc": "일사·바람으로 표면 증발. 낮에는 시료 온도가 30 ~ 45 ℃까지 오를 수 있다.", "temp_c": [20, 45], "pressure_pa": [101325, 101325], "time_h": [24, 120]},
            {"name": "야간 재흡습", "desc": "밤에는 습도가 올라 일부 재흡습. 날씨에 따라 기간이 크게 달라진다.", "temp_c": [5, 20], "pressure_pa": [101325, 101325], "time_h": [24, 120]},
        ],
        "params": {"temp_c": [10, 45], "pressure_pa": [101325, 101325], "time_h": [48, 336]},
        "mechanism": "대기압·상온 증발. 자외선과 장시간 산소 노출, 미생물 증식 위험이 있다.",
        "effects": {"다공성": "낮음",
                    "색·갈변": "자외선·효소적 갈변으로 퇴색·갈변",
                    "열에 약한 폴리페놀 보존": "낮음 ~ 중간(열보다 시간·광산화 영향)",
                    "수축": "큼",
                    "재수화·보수력": "낮음",
                    "비용·시간": "비용 거의 없음, 수일 ~ 2주"},
    },
}

# 3D 입자 단면 — 정성적 예시 파라미터(색은 밝은·어두운 화면 모두에서 보이는 중간 톤)
PARTICLE: dict[str, dict] = {
    "동결건조": {"porosity": 0.85, "shrinkage": 0.95, "roughness": 0.25, "tint": "#d9c49a", "pore_mean": 0.1, "pore_sd": 0.04, "hollow": False, "pore_count": 170},
    "열풍건조": {"porosity": 0.18, "shrinkage": 0.55, "roughness": 0.55, "tint": "#8a5a34", "pore_mean": 0.05, "pore_sd": 0.02, "hollow": False, "pore_count": 18},
    "진공건조": {"porosity": 0.45, "shrinkage": 0.75, "roughness": 0.35, "tint": "#b58a55", "pore_mean": 0.08, "pore_sd": 0.03, "hollow": False, "pore_count": 50},
    "분무건조": {"porosity": 0.5, "shrinkage": 0.8, "roughness": 0.45, "tint": "#e2cfa6", "pore_mean": 0.05, "pore_sd": 0.02, "hollow": True, "pore_count": 12},
    "자연건조": {"porosity": 0.15, "shrinkage": 0.5, "roughness": 0.7, "tint": "#7a5536", "pore_mean": 0.04, "pore_sd": 0.02, "hollow": False, "pore_count": 14},
}

# 표기 → 방식 (긴 것부터 맞춘다). 영문 약어는 단어 경계를 지킨다.
SYNONYMS: dict[str, list[str]] = {
    "동결건조": ["동결건조", "동결 건조", "냉동건조", "냉동 건조", "freeze-drying", "freeze drying", "freeze-dried",
                "freeze dried", "lyophilization", "lyophilisation", "lyophilized", "lyophilised", "FD"],
    "열풍건조": ["열풍건조", "열풍 건조", "열풍", "hot-air drying", "hot air drying", "hot-air dried", "hot air dried",
                "hot-air", "hot air", "convective drying", "oven-dried", "oven dried", "oven drying", "HAD", "HA"],
    "진공건조": ["진공건조", "진공 건조", "감압건조", "감압 건조", "vacuum drying", "vacuum-dried", "vacuum dried", "VD"],
    "분무건조": ["분무건조", "분무 건조", "spray drying", "spray-drying", "spray-dried", "spray dried", "SD"],
    "자연건조": ["자연건조", "자연 건조", "천일건조", "천일 건조", "양건", "음건", "햇볕 건조", "sun drying", "sun-drying",
                "sun-dried", "sun dried", "air-dried", "air dried", "air drying", "shade-dried", "shade dried", "open-air drying"],
}
_SHORT_AMBIG = {"SD", "HA", "VD"}  # 너무 흔한 약어 — 단독 표기(CoA 칸)일 때만 인정


def _db_labels() -> dict[str, str]:
    """시소러스(DB)의 건조 개념 표기도 쓴다. A가 개념을 추가했든 안 했든 동작한다."""
    out: dict[str, str] = {}
    try:
        for r in db.rows("SELECT l.label, c.pref_label_ko FROM concept_label l JOIN concept c ON c.concept_id=l.concept_id "
                         "WHERE c.pref_label_ko IN (%s) AND c.status='active'" % ",".join("?" * len(ORDER)), ORDER):
            if r["label"] and len(r["label"]) >= 2:
                out[r["label"]] = r["pref_label_ko"]
    except Exception:  # noqa: BLE001 - DB 없음
        pass
    return out


def _surface_table(include_ambiguous: bool = False) -> list[tuple[str, str]]:
    tab = {}
    for m, syns in SYNONYMS.items():
        for s in syns:
            if s in _SHORT_AMBIG and not include_ambiguous:
                continue
            tab[s] = m
    for s, m in _db_labels().items():
        if s in _SHORT_AMBIG and not include_ambiguous:
            continue
        tab.setdefault(s, m)
    return sorted(tab.items(), key=lambda x: len(x[0]), reverse=True)


def find_methods(text: str, include_ambiguous: bool = False) -> list[tuple[int, int, str]]:
    """본문에서 건조 방식 언급을 찾는다 → [(start, end, 방식)] 위치순."""
    if not text:
        return []
    low = text.lower()
    taken = [False] * len(text)
    out = []
    for surf, m in _surface_table(include_ambiguous):
        s = surf.lower()
        ascii_word = re.fullmatch(r"[a-z0-9 .\-]+", s) is not None
        start = 0
        while True:
            i = low.find(s, start)
            if i < 0:
                break
            j = i + len(s)
            start = i + 1
            if ascii_word and ((i > 0 and low[i - 1].isascii() and low[i - 1].isalnum())
                               or (j < len(low) and low[j].isascii() and low[j].isalnum())):
                continue
            if any(taken[i:j]):
                continue
            for k in range(i, j):
                taken[k] = True
            out.append((i, j, m))
    return sorted(out)


def canonical(label: str | None) -> str | None:
    if not label:
        return None
    label = label.strip()
    if label in METHODS:
        return label
    hits = find_methods(label, include_ambiguous=True)
    return hits[0][2] if hits else None


# ---------------------------------------------------------------- 전처리 표기 파서

_NUM = r"[-−–]?\s?\d+(?:[.,]\d+)?"
_TEMP_UNIT = r"(?:℃|°\s*C|º\s*C|˚\s*C|도\b|degC|deg\s*C)"
_RANGE_TEMP = re.compile(rf"(?<![\d.])({_NUM})\s*(?:~|〜|–|to|-)\s*({_NUM})\s*{_TEMP_UNIT}", re.I)
_TEMP = re.compile(rf"(?<![\d.])({_NUM})\s*{_TEMP_UNIT}", re.I)
_TIME = re.compile(r"(?<![\d.])(\d+(?:[.,]\d+)?)\s*(?:(?:~|–|to|-)\s*(\d+(?:[.,]\d+)?)\s*)?"
                   r"(hours?|hrs?|h\b|시간|minutes?|mins?|min\b|분\b|분간|days?|d\b|일\b|일간|주\b|weeks?)", re.I)
_PRES = re.compile(r"(?<![\d.])(\d+(?:[.,]\d+)?)\s*(mTorr|Torr|mmHg|mbar|kPa|MPa|Pa|atm)\b", re.I)
_P_FACTOR = {"pa": 1.0, "kpa": 1000.0, "mpa": 1e6, "mbar": 100.0, "torr": 133.322, "mtorr": 0.133322,
             "mmhg": 133.322, "atm": 101325.0}


def _f(s: str) -> float:
    return float(s.replace("−", "-").replace("–", "-").replace(" ", "").replace(",", "."))


def parse_pretreatment(text: str | None, concept_label: str | None = None) -> dict:
    """'동결건조; -50 ℃; 48 h' 같은 표준 형식과 자유 표기(논문 본문)를 모두 받는다.
    → {method, temp_c, time_h, pressure_pa?, temp_range?} (모르는 값은 None)"""
    text = (text or "").strip()
    out: dict = {"method": canonical(concept_label), "temp_c": None, "time_h": None, "raw": text or None}
    if not out["method"] and text:
        first = re.split(r"[;,/]", text)[0]
        out["method"] = canonical(first) or (find_methods(text)[0][2] if find_methods(text) else None)
    if not text:
        return out
    # 시간을 먼저 빼서 '48 h'의 숫자가 온도로 잡히지 않게 한다
    work = text
    m = _RANGE_TEMP.search(work)
    if m:
        a, b = _f(m.group(1)), _f(m.group(2))
        # '40-60 ℃'의 하이픈은 범위, '-50 ℃'의 하이픈은 음수 — 앞 숫자가 있을 때만 범위로 본다
        out["temp_range"] = [min(a, b), max(a, b)]
        out["temp_c"] = round((a + b) / 2, 2)
    else:
        m = _TEMP.search(work)
        if m:
            out["temp_c"] = _f(m.group(1))
    t = _TIME.search(work)
    if t:
        v = _f(t.group(1))
        if t.group(2):
            v = (v + _f(t.group(2))) / 2
        u = t.group(3).lower()
        if u.startswith(("min", "분")):
            v /= 60
        elif u.startswith(("day", "일")) or u == "d":
            v *= 24
        elif u.startswith(("week", "주")):
            v *= 168
        out["time_h"] = round(v, 3)
    p = _PRES.search(work)
    if p:
        out["pressure_pa"] = round(_f(p.group(1)) * _P_FACTOR[p.group(2).lower()], 3)
    return out


# ---------------------------------------------------------------- 물의 상평형도

T_TRIPLE_K, P_TRIPLE = 273.16, 611.657
T_CRIT_K, P_CRIT = 647.096, 22.064e6


def p_sub(t_k: float) -> float:
    """얼음 승화 압력 (Murphy & Koop 2005), Pa"""
    return math.exp(9.550426 - 5723.265 / t_k + 3.53068 * math.log(t_k) - 0.00728332 * t_k)


def p_vap(t_k: float) -> float:
    """물 포화 증기압 (Wagner & Pruss, IAPWS-95 보조식), Pa"""
    tau = 1 - t_k / T_CRIT_K
    a = (-7.85951783, 1.84408259, -11.7866497, 22.6807411, -15.9618719, 1.80122502)
    s = a[0] * tau + a[1] * tau ** 1.5 + a[2] * tau ** 3 + a[3] * tau ** 3.5 + a[4] * tau ** 4 + a[5] * tau ** 7.5
    return P_CRIT * math.exp(T_CRIT_K / t_k * s)


def p_melt(t_k: float) -> float:
    """얼음 Ih 융해 곡선 (IAPWS 2011), Pa. 251.165 K ~ 273.16 K"""
    th = t_k / T_TRIPLE_K
    return P_TRIPLE * (1 - 0.626e6 * (1 - th ** -3) + 0.197135e6 * (1 - th ** 21.2))


def phase_diagram() -> dict:
    sub = [{"t": round(t - 273.15, 2), "p": round(p_sub(t), 6)} for t in [173.15 + i * 2.5 for i in range(41)] if t <= T_TRIPLE_K]
    sub.append({"t": 0.01, "p": P_TRIPLE})
    vap = [{"t": 0.01, "p": P_TRIPLE}] + [{"t": float(c), "p": round(p_vap(c + 273.15), 3)} for c in range(5, 375, 5)]
    vap.append({"t": 373.946, "p": P_CRIT})
    melt = []
    for i in range(0, 41):
        t = T_TRIPLE_K - i * (T_TRIPLE_K - 251.165) / 40
        melt.append({"t": round(t - 273.15, 3), "p": round(p_melt(t), 1)})
    paths = {
        "동결건조": [
            {"t": 20, "p": 101325, "label": "시작"}, {"t": -45, "p": 101325, "label": "예비동결"},
            {"t": -45, "p": 15, "label": "감압", "pos": "l"}, {"t": -30, "p": 15, "label": "1차 건조(승화)"},
            {"t": 30, "p": 5, "label": "2차 건조(탈착)"}],
        "열풍건조": [
            {"t": 20, "p": 101325, "label": "시작"}, {"t": 45, "p": 101325, "label": "항률 건조"},
            {"t": 65, "p": 101325, "label": "감률 건조"}],
        "진공건조": [
            {"t": 20, "p": 101325, "label": "시작"}, {"t": 25, "p": 8000, "label": "감압"},
            {"t": 55, "p": 8000, "label": "가열 증발"}, {"t": 60, "p": 2000, "label": "마무리"}],
        "분무건조": [
            {"t": 20, "p": 101325, "label": "액상 공급"}, {"t": 50, "p": 101325, "label": "액적(증발 냉각)"},
            {"t": 80, "p": 101325, "label": "출구 분말"}],
        "자연건조": [
            {"t": 15, "p": 101325, "label": "시작"}, {"t": 35, "p": 101325, "label": "주간"},
            {"t": 12, "p": 101325, "label": "야간"}],
    }
    return {
        "triple_point": {"t": 0.01, "p": P_TRIPLE}, "critical_point": {"t": 373.946, "p": P_CRIT},
        "curves": {"sublimation": sub, "vaporization": vap, "melting": melt},
        "regions": [{"name": "고체(얼음)", "t": -66, "p": 3000}, {"name": "액체(물)", "t": 45, "p": 3e6},
                    {"name": "기체(수증기)", "t": 130, "p": 30}],
        "paths": paths,
        "note": ("승화 곡선 Murphy & Koop(2005), 증발 곡선 Wagner & Pruss(IAPWS-95 보조식), 융해 곡선 IAPWS(2011). "
                 "경로의 압력은 챔버 압력(열풍·자연·분무는 대기압)이며, 대기압 건조에서 수분은 끓지 않고 "
                 "수증기 분압 차로 증발합니다. 공정 경로는 일반적인 예시입니다."),
    }


def methods() -> dict:
    out = []
    for name in ORDER:
        m = METHODS[name]
        out.append({"name": name, **m, "particle": PARTICLE[name]})
    return {"methods": out, "note": GENERAL_NOTE, "particle_note": ILLUSTRATIVE_NOTE}


# ---------------------------------------------------------------- 방식별 측정값 비교

def _target_clause(target: str) -> tuple[str, list]:
    try:
        from .. import thesaurus
        syn = thesaurus.expand(target)
    except Exception:  # noqa: BLE001
        syn = [target]
    sql = ("(" + " OR ".join(["m.target_text LIKE ?"] * len(syn)) +
           " OR m.target_concept_id IN (SELECT concept_id FROM concept_label WHERE label IN (%s)))" % ",".join("?" * len(syn)))
    return sql, [f"%{s}%" for s in syn] + syn


def _byproduct_clause(byproduct: str) -> tuple[str, list]:
    try:
        from .. import thesaurus
        hits = [h for h in thesaurus.lookup(byproduct) if h["scheme"] == "부산물"]
    except Exception:  # noqa: BLE001
        hits = []
    if not hits:
        return "0", []
    ids = [h["concept_id"] for h in hits]
    labels = sorted({lab for h in hits for lab in h["labels"]})
    q = ",".join("?" * len(ids))
    # 추출값(논문)은 byproduct_id가 비어 있다 → 같은 자료에 그 부산물 라벨이나 표기가 있으면 포함
    sql = (f"(m.byproduct_id IN (SELECT byproduct_id FROM byproduct WHERE concept_id IN ({q})) OR "
           f"(m.byproduct_id IS NULL AND m.doc_id IS NOT NULL AND (m.doc_id IN (SELECT c.doc_id FROM annotation a "
           f"JOIN chunk c ON c.chunk_id=a.chunk_id WHERE a.concept_id IN ({q}) AND a.status!='rejected') OR "
           f"m.doc_id IN (SELECT doc_id FROM chunk WHERE " + " OR ".join(["text LIKE ?"] * len(labels)) + "))))")
    return sql, ids + ids + [f"%{lab}%" for lab in labels]


def _method_for_extracted(r: dict, doc_cache: dict) -> tuple[str | None, str]:
    """추출값: 같은 청크에서 값 바로 앞의 건조 표기 → 뒤의 표기 → 자료 전체에 방식이 하나뿐이면 그것."""
    if r.get("chunk_text"):
        found = find_methods(r["chunk_text"])
        pos = r.get("span_start")
        if found and pos is not None:
            before = [f for f in found if f[1] <= pos]
            if before:
                return before[-1][2], "같은 문단(값 앞 표기)"
            return found[0][2], "같은 문단(값 뒤 표기)"
        if found and len({f[2] for f in found}) == 1:
            return found[0][2], "같은 문단"
    did = r.get("doc_id")
    if did:
        if did not in doc_cache:
            ms = set()
            for c in db.rows("SELECT text FROM chunk WHERE doc_id=?", (did,)):
                ms |= {f[2] for f in find_methods(c["text"])}
            doc_cache[did] = ms
        if len(doc_cache[did]) == 1:
            return next(iter(doc_cache[did])), "같은 자료"
    return None, "건조 방식 표기를 찾지 못함"


def compare(byproduct: str | None = None, targets: list[str] | None = None, project: str | None = None) -> dict:
    """측정값을 건조 방식별로 묶는다. 시료는 '시료 n'으로만 — 로트·공급처·시료번호는 넣지 않는다."""
    targets = [t for t in (targets or ["식이섬유", "폴리페놀"]) if t and t.strip()]
    alias: dict[str, str] = {}
    doc_alias: dict[str, str] = {}
    doc_cache: dict = {}
    result = []
    for target in targets:
        where, params = [], []
        w, p = _target_clause(target)
        where.append(w)
        params += p
        if byproduct:
            w, p = _byproduct_clause(byproduct)
            where.append(w)
            params += p
        if project:
            where.append("(m.doc_id IN (SELECT entity_id FROM project_item pi JOIN project pr ON pr.project_id=pi.project_id "
                         "WHERE pr.name=? AND pi.entity_type='document') OR m.sample_id IN (SELECT entity_id FROM project_item pi "
                         "JOIN project pr ON pr.project_id=pi.project_id WHERE pr.name=? AND pi.entity_type='sample'))")
            params += [project, project]
        rows = db.rows(
            "SELECT m.meas_id, m.value, m.unit_text, m.entry, m.sample_id, m.doc_id, m.basis, "
            "s.pretreatment_text, pc.pref_label_ko AS pre_concept, a.span_start, c.text AS chunk_text "
            "FROM measurement m LEFT JOIN sample s ON s.sample_id=m.sample_id "
            "LEFT JOIN concept pc ON pc.concept_id=s.pretreatment_concept_id "
            "LEFT JOIN annotation a ON a.ann_id=m.ann_id LEFT JOIN chunk c ON c.chunk_id=a.chunk_id "
            "WHERE m.value IS NOT NULL AND " + " AND ".join(where) + " ORDER BY m.created_at LIMIT 2000", params)
        groups: dict[tuple, dict] = {}
        for r in rows:
            if r["sample_id"]:
                parsed = parse_pretreatment(r["pretreatment_text"], r["pre_concept"])
                method, how = parsed["method"], "CoA 전처리"
                who = alias.setdefault(r["sample_id"], f"시료 {len(alias) + 1}")
            else:
                method, how = _method_for_extracted(r, doc_cache)
                parsed = None
                who = doc_alias.setdefault(r["doc_id"] or r["meas_id"], f"문헌 {len(doc_alias) + 1}")
            method = method or "미상"
            unit = (r["unit_text"] or "").strip() or "-"
            g = groups.setdefault((method, unit), {"method": method, "unit": unit, "values": [], "samples": [],
                                                    "entries": {}, "how": set(), "conditions": []})
            g["values"].append(r["value"])
            if who not in g["samples"]:
                g["samples"].append(who)
            g["entries"][r["entry"]] = g["entries"].get(r["entry"], 0) + 1
            g["how"].add(how)
            if parsed and (parsed.get("temp_c") is not None or parsed.get("time_h") is not None):
                cond = {"sample": who, "temp_c": parsed.get("temp_c"), "time_h": parsed.get("time_h"),
                        "pressure_pa": parsed.get("pressure_pa")}
                if cond not in g["conditions"]:
                    g["conditions"].append(cond)
        out = []
        for (method, unit), g in groups.items():
            v = g.pop("values")
            g.update({"n": len(v), "mean": round(statistics.fmean(v), 3), "min": min(v), "max": max(v),
                      "sd": round(statistics.stdev(v), 3) if len(v) > 1 else None, "how": sorted(g["how"])})
            out.append(g)
        rank = {m: i for i, m in enumerate(ORDER + ["미상"])}
        out.sort(key=lambda g: (rank.get(g["method"], 99), g["unit"]))
        result.append({"target": target, "groups": out, "n": sum(g["n"] for g in out)})
    total = sum(t["n"] for t in result)
    note = None if total else ("비교할 측정값이 없습니다. CoA에 전처리(건조 방법)를 적어 올리거나, "
                               "논문의 수치 라벨을 '라벨 검토'에서 승인하면 여기에 모입니다.")
    return {"byproduct": byproduct, "targets": result, "note": note,
            "privacy": "시료는 '시료 n', 논문 값은 '문헌 n'으로만 표시합니다(로트·공급처·시료번호 없음)."}


# ---------------------------------------------------------------- 설비 모델(3D·P&ID 공용 부품 목록과 단계별 계기값)
# 실험실·파일럿 규모 대표 설비의 '일반적인' 구성과 설정 범위다. 특정 제조사 장비가 아니다.
# stages[i]는 METHODS[방식]["stages"][i]와 같은 순서다.
#   gauges: {계기 키: [단계 시작값, 단계 끝값]} — 화면이 단계 진행에 따라 보간한다(단위가 Pa면 로그 보간).
#   anim:   {애니메이션 키: [시작, 끝]} — 0~1 정규값(얼음 양·성에·수증기 흐름·히터 출력 등).
# condition: 시료 조건(온도·압력)을 어느 계기에 얹을지. temp_low는 그 값보다 낮을 때 쓰는 계기(동결건조 콘덴서).
EQUIPMENT_NOTE = ("실험실·파일럿 규모 설비의 대표 구성과 일반 설정 범위를 보여주는 모형입니다. "
                  "계기값은 단계별 예시이며 실제 운전 기록이 아닙니다.")


def _part(pid: str, name: str, role: str, setting: str, note: str, variant: str | None = None) -> dict:
    d = {"id": pid, "name": name, "role": role, "setting": setting, "note": note}
    if variant:
        d["variant"] = variant
    return d


EQUIPMENT: dict[str, dict] = {
    "동결건조": {
        "title": "파일럿 동결건조기 — 선반 4단 · 외부 콘덴서형",
        "scale": "선반 면적 약 0.5 ㎡ · 콘덴서 얼음 용량 약 10 kg",
        "cut_default": False,
        "gauges": [
            {"key": "p_ch", "tag": "PI-101", "label": "챔버 압력", "unit": "Pa", "part": "gauge"},
            {"key": "t_shelf", "tag": "TIC-102", "label": "선반 온도", "unit": "℃", "part": "shelves"},
            {"key": "t_prod", "tag": "TI-103", "label": "품온", "unit": "℃", "part": "trays"},
            {"key": "t_cond", "tag": "TI-104", "label": "콘덴서 온도", "unit": "℃", "part": "condenser"},
        ],
        "stages": [
            {"gauges": {"p_ch": [101325, 101325], "t_shelf": [20, -40], "t_prod": [20, -38], "t_cond": [20, -60]},
             "anim": {"ice": [0.15, 1], "frost": [0, 0], "vapor": [0, 0], "vac": [0, 0], "cool": [1, 1], "heat": [0, 0]}},
            {"gauges": {"p_ch": [40, 15], "t_shelf": [-30, -10], "t_prod": [-38, -30], "t_cond": [-62, -65]},
             "anim": {"ice": [1, 0.08], "frost": [0.05, 0.9], "vapor": [1, 0.7], "vac": [1, 1], "cool": [1, 1], "heat": [0.4, 0.6]}},
            {"gauges": {"p_ch": [15, 5], "t_shelf": [0, 30], "t_prod": [-25, 28], "t_cond": [-65, -66]},
             "anim": {"ice": [0.08, 0], "frost": [0.9, 1], "vapor": [0.4, 0.1], "vac": [1, 1], "cool": [1, 1], "heat": [0.7, 1]}},
        ],
        "condition": {"temp": "t_shelf", "temp_low": "t_cond", "pressure": "p_ch", "stage": 1},
        "parts": [
            _part("chamber", "건조 챔버", "시료를 넣고 진공을 유지하는 스테인리스 용기. 선반과 트레이가 들어간다.",
                  "1차 건조 10 ~ 30 Pa, 2차 건조 1 ~ 10 Pa",
                  "작은 누설만 있어도 압력이 내려가지 않아 승화가 느려지고, 품온이 올라 시료가 녹아 무너진다(붕괴)."),
            _part("door", "투명 도어(아크릴)", "가스켓으로 밀봉되는 앞문. 건조 중 시료가 녹거나 부풀지 않는지 눈으로 본다.",
                  "닫힘 상태에서 진공 유지",
                  "부산물은 당·유기산이 많아 붕괴 온도가 낮다. 표면이 젖어 보이거나 꺼지면 선반 온도를 낮춘다."),
            _part("shelves", "가열 선반", "실리콘 오일이 흐르는 판. 예비동결 때는 식히고, 건조 때는 승화열을 공급한다.",
                  "-50 ~ +50 ℃ (1차 -30 ~ -10 ℃, 2차 +20 ~ +40 ℃)",
                  "선반이 너무 뜨거우면 품온이 붕괴 온도를 넘는다. 과일박처럼 당이 많은 시료는 1차 건조 선반을 -20 ℃ 안팎으로 둔다."),
            _part("trays", "트레이·시료", "시료를 10 ~ 15 mm 두께로 펴 담는 스테인리스 트레이. 품온 센서를 시료에 꽂는다.",
                  "시료 두께 10 ~ 15 mm, 적재량 10 ~ 15 kg/㎡",
                  "건조 시간은 두께의 제곱에 가깝게 늘어난다. 두께를 고르게 펴는 것이 가장 싼 단축 방법이다."),
            _part("valve", "메인 격리 밸브", "챔버와 콘덴서 사이를 여닫는 버터플라이 밸브(공압 작동).",
                  "건조 중 열림, 압력 상승 시험 때 잠깐 닫음",
                  "잠시 닫았을 때 챔버 압력이 거의 오르지 않으면 얼음이 다 빠진 것 — 1차 건조 종료 판정에 쓴다."),
            _part("duct", "증기 덕트", "챔버에서 생긴 수증기가 콘덴서로 가는 굵은 통로.",
                  "구경 100 ~ 150 mm, 짧고 곧게", "덕트가 가늘면 수증기가 막혀 챔버 압력이 올라간다(초크 흐름)."),
            _part("condenser", "콘덴서(얼음 포집기)", "-60 ~ -80 ℃ 냉각 코일에 수증기를 얼려 붙잡는다. 코일에 성에가 자란다.",
                  "-60 ~ -80 ℃, 얼음 용량 약 10 kg",
                  "콘덴서가 시료보다 충분히 차가워야 증기가 흘러간다. 용량을 넘기면 압력이 오르니 회차마다 해동·배수한다."),
            _part("vacpump", "진공 펌프(로터리 베인)", "챔버와 콘덴서의 공기를 빼 압력을 낮춘다.",
                  "도달 압력 1 Pa 이하, 배기 속도 약 10 ㎥/h",
                  "수증기가 펌프 오일에 섞이면 성능이 떨어진다. 가스 밸러스트를 쓰고 오일을 자주 바꾼다."),
            _part("refrig", "냉동기(압축기)", "콘덴서 코일과 선반 오일을 식히는 2단 냉동 사이클.",
                  "콘덴서 -60 ~ -80 ℃까지 냉각",
                  "예비동결 속도가 얼음 결정 크기를 정한다. 천천히 얼리면 결정이 커져 기공이 크고 건조가 빠르다."),
            _part("gauge", "진공 게이지", "챔버 압력을 재는 정전용량식 게이지(피라니 게이지와 함께 씀).",
                  "측정 0.1 ~ 1,000 Pa",
                  "피라니 값이 정전용량식 값으로 내려와 같아지면 수증기가 거의 없다는 뜻 — 1차 건조 끝 신호."),
            _part("panel", "제어반", "단계별 선반 온도·압력·시간 레시피를 돌리고 기록한다.",
                  "레시피 3단계(예비동결 → 1차 → 2차)", "CoA 전처리 칸에 적을 조건(온도·압력·시간)이 이 레시피다."),
        ],
    },
    "열풍건조": {
        "title": "캐비닛형 열풍 트레이 건조기 — 대차식 · 횡류",
        "scale": "트레이 8단(약 0.9 × 0.85 m) · 처리량 약 30 ~ 60 kg/회",
        "cut_default": True,
        "gauges": [
            {"key": "t_in", "tag": "TIC-201", "label": "열풍 입구 온도", "unit": "℃", "part": "heater"},
            {"key": "rh", "tag": "RHI-202", "label": "배기 상대습도", "unit": "%", "part": "sensor"},
            {"key": "t_prod", "tag": "TI-203", "label": "품온", "unit": "℃", "part": "trays"},
            {"key": "moisture", "tag": "MI", "label": "시료 수분(습량)", "unit": "%", "part": "trays"},
        ],
        "stages": [
            {"gauges": {"t_in": [25, 60], "rh": [60, 75], "t_prod": [18, 32], "moisture": [80, 79]},
             "anim": {"heat": [1, 1], "fan": [1, 1], "vapor": [0.2, 0.5], "damper": [0.3, 0.4], "moisture": [1, 0.98]}},
            {"gauges": {"t_in": [60, 60], "rh": [80, 70], "t_prod": [32, 34], "moisture": [79, 45]},
             "anim": {"heat": [0.9, 0.9], "fan": [1, 1], "vapor": [1, 0.9], "damper": [0.6, 0.6], "moisture": [0.98, 0.7]}},
            {"gauges": {"t_in": [60, 60], "rh": [55, 25], "t_prod": [38, 57], "moisture": [45, 8]},
             "anim": {"heat": [0.7, 0.5], "fan": [1, 1], "vapor": [0.6, 0.1], "damper": [0.4, 0.15], "moisture": [0.7, 0.45]}},
        ],
        "condition": {"temp": "t_in", "stage": 1},
        "parts": [
            _part("cabinet", "단열 캐비닛", "안팎 철판 사이에 단열재를 채운 건조실. 열풍이 새지 않게 막는다.",
                  "벽 두께 50 ~ 75 mm, 사용 온도 40 ~ 90 ℃", "단열이 약하면 벽 쪽 트레이가 덜 마르고 전력비가 오른다."),
            _part("door", "도어", "대차를 넣고 빼는 앞문. 실리콘 가스켓과 잠금 손잡이로 밀봉한다.",
                  "건조 중 닫힘", "중간에 자주 열면 온도가 떨어지고 습한 외기가 들어와 시간이 늘어난다."),
            _part("trolley", "트레이 대차", "트레이를 여러 단으로 꽂아 통째로 넣고 빼는 바퀴 달린 랙.",
                  "단 간격 80 ~ 100 mm", "단 간격이 좁으면 공기가 잘 안 흘러 가운데 트레이가 늦게 마른다."),
            _part("trays", "타공 트레이·시료", "구멍 뚫린 트레이에 시료를 얇게 편다. 공기가 위아래로 닿는다.",
                  "두께 5 ~ 10 mm, 적재 5 ~ 10 kg/㎡", "두껍게 쌓으면 겉만 굳고 속은 젖은 채로 남는다(표면 경화)."),
            _part("heater", "히터 뱅크(핀 히터)", "핀이 달린 전기 히터가 순환 공기를 데운다.",
                  "입구 공기 50 ~ 80 ℃ (부산물은 보통 50 ~ 60 ℃)",
                  "온도를 10 ℃ 올리면 빨리 마르지만 갈변·폴리페놀 손실이 커진다. 품질 목표와 시간의 맞교환."),
            _part("fan", "순환 송풍기", "공기를 히터 → 트레이 → 다시 송풍기로 돌린다.",
                  "트레이 위 풍속 1 ~ 3 m/s",
                  "항률 건조 구간 속도는 풍속에 크게 좌우된다. 감률 구간에서는 효과가 작아 풍속을 낮춰 전력을 아낀다."),
            _part("duct", "공기 분배판·덕트", "타공판으로 공기를 각 단에 고르게 나누고, 반대편에서 모아 되돌린다.",
                  "단별 풍속 차이 ±10 % 이내", "분배가 고르지 않으면 단마다 수분이 달라 품질 편차가 생긴다. 중간에 트레이 위치를 바꿔 준다."),
            _part("inlet", "외기 흡입 댐퍼", "건조한 바깥 공기를 들여 습한 순환 공기를 묽게 한다.",
                  "개도 10 ~ 60 %", "외기를 너무 많이 넣으면 데우는 전력이 크게 늘고, 너무 적으면 습도가 차 건조가 멈춘다."),
            _part("exhaust", "배기 댐퍼·연통", "수분을 머금은 공기를 밖으로 내보낸다.",
                  "배기 습도 30 ~ 70 %에 맞춰 개도 조절", "초기(항률)에는 크게 열어 습기를 빼고, 후반(감률)에는 줄여 열을 아낀다."),
            _part("sensor", "온습도 센서", "되돌아오는 공기의 온도·상대습도를 잰다.",
                  "측정 0 ~ 100 % RH, 0 ~ 100 ℃", "배기 습도가 외기 수준까지 떨어지면 시료에서 더 나오는 물이 거의 없다는 뜻 — 종료 판단에 쓴다."),
            _part("panel", "제어반", "입구 온도·시간·댐퍼 개도를 설정하고 기록한다.",
                  "온도 PID 제어 ±1 ℃", "CoA 전처리 칸의 '열풍건조; 60 ℃; 12 h'가 이 설정이다."),
        ],
    },
    "진공건조": {
        "title": "진공 선반 건조기 — 온수 가열 선반 3단 · 외부 응축기",
        "scale": "챔버 약 0.25 ㎥ · 선반 3단",
        "cut_default": True,
        "gauges": [
            {"key": "p_ch", "tag": "PI-301", "label": "챔버 압력", "unit": "Pa", "part": "gauge"},
            {"key": "boil", "tag": "TY-301", "label": "물 끓는점(계산)", "unit": "℃", "part": "gauge", "derive": "boil", "from": "p_ch"},
            {"key": "t_plate", "tag": "TIC-302", "label": "선반 온도", "unit": "℃", "part": "plates"},
            {"key": "t_prod", "tag": "TI-303", "label": "품온", "unit": "℃", "part": "trays"},
            {"key": "moisture", "tag": "MI", "label": "시료 수분(습량)", "unit": "%", "part": "trays"},
        ],
        "stages": [
            {"gauges": {"p_ch": [101325, 8000], "t_plate": [25, 40], "t_prod": [20, 22], "moisture": [80, 80]},
             "anim": {"vac": [1, 1], "heat": [0.2, 0.5], "bubble": [0, 0.2], "vapor": [0, 0.2], "moisture": [1, 1]}},
            {"gauges": {"p_ch": [8000, 8000], "t_plate": [60, 60], "t_prod": [38, 42], "moisture": [80, 25]},
             "anim": {"vac": [1, 1], "heat": [1, 1], "bubble": [1, 0.6], "vapor": [1, 0.7], "moisture": [1, 0.75]}},
            {"gauges": {"p_ch": [8000, 2000], "t_plate": [60, 60], "t_prod": [45, 58], "moisture": [25, 6]},
             "anim": {"vac": [1, 1], "heat": [0.8, 0.6], "bubble": [0.3, 0.05], "vapor": [0.3, 0.1], "moisture": [0.75, 0.65]}},
        ],
        "condition": {"temp": "t_plate", "pressure": "p_ch", "stage": 1},
        "parts": [
            _part("chamber", "진공 챔버", "두꺼운 철판 상자. 대기압과의 차이(약 10 t/㎡)를 견딘다.",
                  "2 ~ 20 kPa (끓는점 약 17 ~ 60 ℃)", "압력을 낮출수록 낮은 온도에서 물이 끓어 열에 약한 성분이 덜 상한다."),
            _part("door", "도어·관찰창", "강화유리 관찰창이 달린 두꺼운 문. 손잡이 볼트로 가스켓을 눌러 밀봉한다.",
                  "닫힘 상태에서 누설 < 0.1 kPa/min", "끓어오름(거품)이 심하면 시료가 튀어 넘친다. 관찰창으로 보며 감압 속도를 늦춘다."),
            _part("plates", "가열 선반(온수 재킷)", "속에 온수가 흐르는 판. 진공에서는 대류가 없어 전도로만 열을 준다.",
                  "40 ~ 70 ℃", "진공에서는 트레이와 선반이 밀착해야 열이 들어간다. 휜 트레이는 건조 편차의 주원인."),
            _part("trays", "트레이·시료", "시료를 얇게 편 트레이. 감압하면 시료 속 물이 끓으며 거품이 일어난다.",
                  "두께 5 ~ 15 mm", "감압 팽화로 약간의 기공이 생겨 열풍보다 재수화가 낫다."),
            _part("circulator", "온수 순환기", "선반에 일정 온도의 온수를 돌린다.",
                  "40 ~ 80 ℃, ±0.5 ℃", "선반 온도가 곧 시료 최고 온도의 상한이다. CoA 조건의 '온도'는 보통 이 값."),
            _part("condenser", "응축기", "냉각수로 수증기를 물로 되돌려 모은다. 펌프로 수증기가 가지 않게 막는다.",
                  "냉각수 5 ~ 15 ℃", "응축기가 없으면 수증기가 펌프로 들어가 진공도가 떨어지고 펌프가 상한다."),
            _part("vacpump", "진공 펌프", "챔버의 공기와 응축되지 않은 기체를 뺀다.",
                  "도달 압력 0.5 ~ 2 kPa", "펌프 성능보다 누설과 응축기 온도가 실제 압력을 정하는 경우가 많다."),
            _part("gauge", "압력계", "챔버 압력을 kPa로 보여준다. 제어반이 이 값으로 끓는점을 계산한다.",
                  "0 ~ 101 kPa", "같은 60 ℃라도 압력에 따라 끓음 여부가 갈린다. 온도와 압력을 함께 기록해야 재현된다."),
            _part("valve", "진공 해제 밸브", "건조가 끝나면 천천히 공기(또는 질소)를 넣어 대기압으로 되돌린다.",
                  "해제 시간 2 ~ 5분", "갑자기 열면 가루가 날리고, 산소에 갑자기 닿는다. 질소로 해제하면 산화를 더 줄인다."),
            _part("panel", "제어반", "압력·선반 온도·시간을 설정하고 기록한다.",
                  "압력 단계 2단(가열 증발 → 마무리)", "CoA 전처리 칸에 압력(kPa)도 함께 적으면 상평형도에 정확한 위치가 찍힌다."),
        ],
    },
    "분무건조": {
        "title": "파일럿 분무건조기 — 회전 원판 분무 · 병류 · 사이클론 회수",
        "scale": "건조탑 지름 약 1 m · 물 증발량 약 5 ~ 10 kg/h",
        "cut_default": True,
        "gauges": [
            {"key": "t_in", "tag": "TIC-401", "label": "입구 공기 온도", "unit": "℃", "part": "ti_in"},
            {"key": "t_out", "tag": "TI-402", "label": "출구 공기 온도", "unit": "℃", "part": "ti_out"},
            {"key": "feed", "tag": "FIC-403", "label": "원료액 공급", "unit": "mL/min", "part": "feedpump"},
            {"key": "rpm", "tag": "SI-404", "label": "분무 원판 회전", "unit": "rpm", "part": "atomizer"},
        ],
        "stages": [
            {"gauges": {"t_in": [180, 180], "t_out": [95, 82], "feed": [0, 120], "rpm": [0, 24000]},
             "anim": {"heat": [1, 1], "fan": [1, 1], "spray": [0.15, 1], "powder": [0, 0.05], "atom": [0.2, 1]}},
            {"gauges": {"t_in": [180, 180], "t_out": [82, 80], "feed": [120, 120], "rpm": [24000, 24000]},
             "anim": {"heat": [1, 1], "fan": [1, 1], "spray": [1, 1], "powder": [0.05, 0.5], "atom": [1, 1]}},
            {"gauges": {"t_in": [180, 180], "t_out": [80, 80], "feed": [120, 120], "rpm": [24000, 24000]},
             "anim": {"heat": [1, 1], "fan": [1, 1], "spray": [1, 1], "powder": [0.5, 0.95], "atom": [1, 1]}},
        ],
        "condition": {"temp": "t_in", "stage": 1},
        "parts": [
            _part("feedtank", "원료액 탱크", "추출액·슬러리를 담고 교반기로 고르게 섞는다. 덱스트린 등 담체를 여기서 녹인다.",
                  "고형분 10 ~ 40 %, 40 ~ 60 ℃로 유지", "고형분이 높을수록 생산성은 좋지만 점도가 올라 분무가 거칠어진다."),
            _part("feedpump", "연동 펌프", "롤러가 튜브를 눌러 원료액을 일정하게 보낸다.",
                  "50 ~ 300 mL/min (파일럿)", "공급량을 늘리면 출구 온도가 떨어지고 수분이 남는다. 출구 온도로 공급량을 맞춘다."),
            _part("filter", "공기 필터", "들어오는 공기의 먼지를 거른다(식품 등급).",
                  "F7 ~ H13 필터", "필터가 막히면 풍량이 줄어 출구 온도·수분이 흔들린다."),
            _part("blower", "급기 송풍기", "건조 공기를 히터와 건조탑으로 밀어 넣는다.",
                  "풍량 약 300 ~ 600 ㎥/h", "풍량은 증발 능력과 체류 시간을 함께 바꾼다."),
            _part("heater", "공기 가열기", "전기 히터로 입구 공기를 데운다.",
                  "입구 150 ~ 200 ℃", "입구 온도는 높아도 액적은 증발 냉각으로 40 ~ 60 ℃에 머문다. 위험한 건 출구 온도와 벽 부착."),
            _part("atomizer", "회전 원판 분무기", "고속 회전 원판이 원료액을 10 ~ 200 µm 액적으로 흩뿌린다.",
                  "15,000 ~ 30,000 rpm", "회전이 빠를수록 액적이 작아져 빨리 마르지만 미분이 늘어 회수율이 떨어진다."),
            _part("chamber", "건조탑(원통 + 원뿔)", "액적이 열풍과 함께 내려가며 몇 초 만에 마른다.",
                  "체류 시간 약 5 ~ 30초", "당이 많은 부산물 추출액은 벽에 달라붙는다(유리전이). 담체 비율을 높이거나 출구 온도를 낮춘다."),
            _part("ti_in", "입구 온도계", "건조탑으로 들어가는 열풍 온도를 잰다(히터 제어 기준).",
                  "150 ~ 200 ℃", "CoA의 '분무건조; 180 ℃'는 보통 이 입구 온도다."),
            _part("ti_out", "출구 온도계", "건조탑을 나가는 공기 온도. 분말의 최종 수분을 가장 잘 알려준다.",
                  "70 ~ 90 ℃", "출구 온도가 낮으면 분말이 눅눅해 덩어리지고, 높으면 갈변·향 손실이 커진다."),
            _part("cyclone", "사이클론", "회전 흐름의 원심력으로 분말을 벽으로 밀어 아래로 떨어뜨린다.",
                  "입구 풍속 15 ~ 25 m/s, 10 µm 이상 회수", "미세 분말은 빠져나가 회수율이 떨어진다(파일럿 70 ~ 90 %)."),
            _part("jar", "분말 수집병", "사이클론 아래에서 분말을 받는다.",
                  "주기적으로 교체·밀봉", "분말은 흡습성이 커서 바로 밀봉하지 않으면 뭉친다. 수분·수분활성도를 바로 잰다."),
            _part("bagfilter", "백 필터", "사이클론을 빠져나온 미세 분말을 걸러 배기를 깨끗하게 한다.",
                  "차압 0.5 ~ 1.5 kPa", "차압이 오르면 털어주기(펄스)를 한다. 걸린 분말도 회수량에 넣는다."),
            _part("exhaust", "배기 송풍기", "건조탑 안을 약한 음압으로 유지하며 공기를 내보낸다.",
                  "탑 내부 -50 ~ -200 Pa", "음압이면 분말이 밖으로 새지 않는다."),
            _part("panel", "제어반", "입구 온도·공급량·회전수를 설정하고 출구 온도를 감시한다.",
                  "출구 온도 목표로 공급량 자동 조절", "CoA에 입구·출구 온도와 담체(종류·비율)를 함께 적어야 결과를 비교할 수 있다."),
        ],
    },
    "자연건조": {
        "title": "자연건조 — 노지 천일건조 / 하우스형 태양열 건조기",
        "scale": "건조대 1.6 × 0.9 m × 3개 / 터널 약 4.5 × 1 m",
        "cut_default": False,
        "variants": [{"id": "open", "name": "노지 천일건조"}, {"id": "solar", "name": "하우스형 태양열 건조기"}],
        "gauges": [
            {"key": "t_air", "tag": "TI-501", "label": "외기 온도", "unit": "℃", "part": "station"},
            {"key": "t_dry", "tag": "TI-502", "label": "건조부 공기 온도", "unit": "℃", "part": "cover", "variant": "solar"},
            {"key": "rh", "tag": "RHI-503", "label": "상대습도", "unit": "%", "part": "station"},
            {"key": "solar", "tag": "RI-504", "label": "일사량", "unit": "W/㎡", "part": "sun"},
            {"key": "moisture", "tag": "MI", "label": "시료 수분(습량)", "unit": "%", "part": "racks", "variant": "open"},
            {"key": "moisture", "tag": "MI", "label": "시료 수분(습량)", "unit": "%", "part": "trays", "variant": "solar"},
        ],
        "stages": [
            {"gauges": {"t_air": [18, 24], "t_dry": [20, 35], "rh": [70, 55], "solar": [200, 550], "moisture": [80, 79]},
             "anim": {"sun": [0.12, 0.3], "wind": [0.4, 0.5], "night": [0, 0], "vapor": [0.1, 0.4], "moisture": [1, 0.98], "fan": [0.4, 0.8]}},
            {"gauges": {"t_air": [26, 30], "t_dry": [50, 55], "rh": [45, 35], "solar": [800, 700], "moisture": [79, 35]},
             "anim": {"sun": [0.35, 0.85], "wind": [0.6, 0.7], "night": [0, 0], "vapor": [1, 0.7], "moisture": [0.98, 0.65], "fan": [1, 1]}},
            {"gauges": {"t_air": [16, 12], "t_dry": [15, 12], "rh": [80, 92], "solar": [0, 0], "moisture": [35, 38]},
             "anim": {"sun": [1.1, 1.1], "wind": [0.3, 0.2], "night": [1, 1], "vapor": [0, 0], "moisture": [0.65, 0.67], "fan": [0, 0]}},
        ],
        "condition": {"temp": "t_air", "stage": 1},
        "parts": [
            _part("racks", "건조대(망 선반)", "바닥에서 띄운 망 위에 시료를 편다. 아래로도 바람이 통한다.",
                  "높이 0.7 ~ 1 m, 적재 2 ~ 5 kg/㎡",
                  "바닥에 바로 펴면 흙·미생물 오염과 재흡습이 커진다. 식품 원료로 쓰려면 띄운 망이 기본.", "open"),
            _part("net", "방충망 덮개", "곤충·새·먼지를 막는 가는 망.",
                  "망눈 1 ~ 2 mm", "위생 기준(이물·미생물)을 맞추려면 덮개가 필요하다. 바람은 조금 줄어든다.", "open"),
            _part("tarp", "비가림 덮개", "밤이나 비 올 때 덮는 방수포.",
                  "해 진 뒤·강수 예보 시 덮음", "야간 재흡습과 비 맞음이 자연건조 품질 편차의 가장 큰 원인이다.", "open"),
            _part("sun", "태양(일사)", "복사열로 시료 표면을 데운다. 하루 동안 각도와 세기가 바뀐다.",
                  "맑은 날 정오 700 ~ 1,000 W/㎡",
                  "자외선은 색소(카로티노이드·안토시아닌)를 바래게 한다. 색이 중요하면 음건·하우스형이 낫다."),
            _part("wind", "바람", "시료 주변의 습한 공기를 걷어내 증발을 돕는다.",
                  "1 ~ 3 m/s가 적당", "바람이 없으면 시료 위에 습한 공기층이 머물러 건조가 크게 느려진다.", "open"),
            _part("station", "온습도계(백엽상)", "백엽상 안에서 외기 온도·습도를 잰다.",
                  "기록 간격 10 ~ 30분", "자연건조 CoA에는 날짜·기간과 함께 평균 온습도를 적어야 다른 회차와 비교할 수 있다."),
            _part("pv", "태양광 패널", "송풍기를 돌릴 전기를 만든다. 해가 강할수록 바람도 세진다.",
                  "약 40 ~ 100 W", "전력망이 없어도 강제 통풍이 되어 노지보다 2 ~ 3배 빠르다.", "solar"),
            _part("fan", "직류 송풍기", "바깥 공기를 집열부로 밀어 넣는다.",
                  "풍속 0.5 ~ 1.5 m/s", "풍량이 너무 많으면 공기가 덜 데워지고, 너무 적으면 습기가 빠지지 않는다.", "solar"),
            _part("collector", "태양열 집열부", "검은 흡열판이 햇볕을 받아 지나가는 공기를 데운다.",
                  "공기 온도 상승 +15 ~ +30 ℃", "시료가 직사광선을 덜 받아 색 손실이 줄고, 데운 공기로 습도가 낮아진다.", "solar"),
            _part("cover", "투명 아치 덮개(건조부)", "자외선 차단 필름·폴리카보네이트 덮개. 비·먼지·곤충을 막고 열을 가둔다.",
                  "내부 40 ~ 60 ℃(맑은 날)", "덮개 안이 너무 뜨거우면(65 ℃ 이상) 갈변이 생긴다. 송풍량으로 조절한다.", "solar"),
            _part("trays", "건조 망·시료", "터널 바닥에 깐 망 위에 시료를 편다.",
                  "두께 5 ~ 10 mm", "출구 쪽은 습한 공기를 받아 늦게 마른다. 중간에 앞뒤를 바꿔 준다.", "solar"),
            _part("chimney", "배기구", "습해진 공기가 빠져나가는 출구. 망으로 곤충을 막는다.",
                  "출구 습도 50 ~ 80 %", "출구 습도가 입구와 비슷해지면 시료가 거의 다 마른 것이다.", "solar"),
        ],
    },
}


def equipment(method: str, variant: str | None = None) -> dict | None:
    """설비 모델(3D·P&ID 공용): 부품·계기·단계별 값. variant(자연건조 open/solar)를 주면 그 형태만 남긴다."""
    name = method if method in EQUIPMENT else canonical(method)
    if not name or name not in EQUIPMENT:
        return None
    e = EQUIPMENT[name]
    if variant is None and e.get("variants"):
        variant = e["variants"][0]["id"]
    keep = lambda x: not x.get("variant") or x["variant"] == variant  # noqa: E731
    stages = [{"name": s["name"], "time_h": s["time_h"], **e["stages"][i]} for i, s in enumerate(METHODS[name]["stages"])]
    return {"method": name, "title": e["title"], "scale": e["scale"], "cut_default": e["cut_default"],
            "variants": e.get("variants", []), "variant": variant,
            "gauges": [g for g in e["gauges"] if keep(g)], "parts": [p for p in e["parts"] if keep(p)],
            "stages": stages, "condition": e["condition"], "note": EQUIPMENT_NOTE}
