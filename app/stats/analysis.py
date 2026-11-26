"""분석 실행: 데이터 → 검사(한국어 안내) → core 계산 → 가정 점검 판정·설명 → 방법 문장·해석 재료.

판정은 pass(위반 근거 없음) · warn(주의) · fail(위반/부족) · info(자료로 검정할 수 없음)이고,
모든 판정은 쓴 검정·통계량·n·기준값을 함께 보인다. 검정이 유의하지 않다는 것만으로 '가정 충족'이라고 쓰지 않는다
(작은 n에서는 검정력이 낮다는 말을 붙인다).
"""
from __future__ import annotations

import math
import platform
import threading
import time
import uuid
from dataclasses import dataclass, field

import numpy as np

from . import core, data as D, fmt as F

STATUS_RANK = {"pass": 0, "info": 0, "warn": 1, "fail": 2}
SMALL_N_RESID = 30      # 잔차 정규성·등분산 검정의 검정력이 낮다고 알리는 n
SMALL_N_GROUP = 15      # 집단별 정규성 검정력이 낮다고 알리는 집단 n
_results: dict[str, "Result"] = {}
_lock = threading.Lock()
TTL_S = 3600


class StatsError(ValueError):
    pass


def versions() -> dict:
    import pandas
    import scipy
    import statsmodels
    return {"python": platform.python_version(), "numpy": np.__version__, "pandas": pandas.__version__,
            "scipy": scipy.__version__, "statsmodels": statsmodels.__version__}


# ---------------------------------------------------------------- 이름표

@dataclass
class Labels:
    ds: D.Dataset

    def var(self, name: str, lang: str = "ko", unit: bool = True) -> str:
        v = self.ds.var(name)
        lab = v.get("label_" + lang) or v.get("label_ko") or name
        return f"{lab} ({v['unit']})" if unit and v.get("unit") else lab

    def unit(self, name: str) -> str:
        return self.ds.var(name).get("unit") or ""

    def level(self, var: str, value: str, lang: str = "ko") -> str:
        for lv in self.ds.var(var).get("levels") or []:
            if str(lv["value"]) == str(value):
                return lv.get("label_" + lang) or lv.get("label_ko") or str(value)
        return str(value)

    def term(self, term: str, lang: str = "ko", unit: bool = True) -> str:
        """계수 열 이름 → 이름표: 'temp_c' → '추출 온도 (℃)', 'acid[HCl]' → '염산', 'temp_c^2' → '추출 온도²',
        'temp_c:acid[HCl]' → '추출 온도 × 염산', 항 이름 'temp_c:acid' → '추출 온도 × 산 종류'."""
        if term == "(Intercept)":
            return "(절편)" if lang == "ko" else "(Intercept)"
        if ":" in term:
            return " × ".join(self.term(p, lang, unit=False) for p in term.split(":"))
        if term.endswith("^2"):
            return self.var(term[:-2], lang, unit=False) + "²"
        if "[" in term:
            var, lv = term[:-1].split("[", 1)
            return self.level(var, lv, lang)
        return self.var(term, lang, unit=unit)

    def termname(self, term: str, lang: str = "ko") -> str:
        """항(term) 이름표 — 단위 없이."""
        return self.term(term, lang, unit=False)


# ---------------------------------------------------------------- 결과

@dataclass
class Result:
    rid: str
    ds: D.Dataset
    spec: dict
    core: dict
    out: dict
    created: float = field(default_factory=time.time)
    cache: dict = field(default_factory=dict)

    @property
    def labels(self) -> Labels:
        return Labels(self.ds)


def get(rid: str) -> Result:
    with _lock:
        r = _results.get(rid)
    if not r:
        raise StatsError("분석 결과가 만료되었습니다(1시간). '분석 실행'을 다시 누르세요.")
    return r


def _keep(r: Result) -> None:
    with _lock:
        now = time.time()
        for k in [k for k, v in _results.items() if now - v.created > TTL_S]:
            _results.pop(k, None)
        while len(_results) >= 20:
            _results.pop(min(_results, key=lambda k: _results[k].created))
        _results[r.rid] = r


# ---------------------------------------------------------------- 사양 검사

def resolve_spec(ds: D.Dataset, spec: dict | None) -> dict:
    s = {**D.suggest_spec(ds), **{k: v for k, v in (spec or {}).items() if v is not None}}
    L = Labels(ds)
    if not s.get("outcome"):
        raise StatsError("결과 변수(예: 수율)를 고르세요. 숫자로 된 연속 변수만 결과 변수가 될 수 있습니다.")
    out = ds.var(s["outcome"])
    if out["type"] != "continuous":
        raise StatsError(f"결과 변수 '{L.var(s['outcome'])}'가 숫자(연속) 변수가 아닙니다. 수율처럼 숫자로 잰 변수를 고르세요.")
    cont = [c for c in (s.get("continuous") or []) if c != s["outcome"]]
    for c in cont:
        if ds.var(c)["type"] != "continuous":
            raise StatsError(f"'{L.var(c)}'는 연속 변수가 아닙니다. 범주 변수 칸으로 옮기세요.")
    cats = []
    for c in s.get("categorical") or []:
        c = {"name": c} if isinstance(c, str) else dict(c)
        v = ds.var(c["name"])
        if v["type"] != "categorical":
            raise StatsError(f"'{L.var(c['name'])}'는 범주 변수가 아닙니다. 변수 역할을 '범주'로 바꾸세요.")
        if c["name"] == s["outcome"] or c["name"] in cont:
            raise StatsError(f"'{L.var(c['name'])}'를 두 역할에 동시에 넣었습니다. 한 역할만 고르세요.")
        lv = [x["value"] for x in v.get("levels") or []]
        if c.get("reference") in (None, ""):
            c["reference"] = lv[0] if lv else None
        if c["reference"] not in lv:
            raise StatsError(f"기준 수준 '{c['reference']}'가 '{L.var(c['name'])}'에 없습니다. {', '.join(map(str, lv))} 중에서 고르세요.")
        c.setdefault("levels", lv)
        cats.append(c)
    group = s.get("group") or None
    if group:
        gv = ds.var(group)
        if gv["type"] != "categorical":
            raise StatsError(f"집단 비교 변수 '{L.var(group)}'는 범주 변수여야 합니다(예: 산 종류).")
    test = s.get("test") or "welch"
    if test not in ("welch", "student", "auto"):
        raise StatsError("t검정 종류는 welch(기본)·student·auto 중 하나로 고르세요.")
    alpha = float(s.get("alpha") or 0.05)
    if not 0 < alpha < 0.5:
        raise StatsError("유의수준 α는 0과 0.5 사이로 넣으세요(보통 0.05).")
    if not cont and not cats and not group:
        raise StatsError("설명 변수가 없습니다. 연속(예: 온도·시간) 또는 범주(예: 산 종류) 변수를 하나 이상 고르세요.")
    zero = s.get("zero") or "auto"
    if zero not in ("auto", "apa", "leading"):
        raise StatsError("숫자 앞 0 표기는 auto(한국어 0.034·영어 .034)·apa(.034)·leading(0.034) 중 하나로 고르세요.")
    inter, quad = model_terms(ds, s, cont, [c["name"] for c in cats])
    xvar = s.get("xvar") or None
    if xvar and xvar not in cont:
        raise StatsError(f"그림 1의 가로축 '{xvar}'는 연속 설명 변수가 아닙니다. 연속 설명 변수 중에서 고르세요.")
    xvar = xvar or next((c for c in cont if c.startswith("temp")), cont[0] if cont else None)
    return {"outcome": s["outcome"], "continuous": cont, "categorical": cats, "group": group, "test": test, "alpha": alpha, "zero": zero,
            "interactions": inter, "quadratic": quad, "xvar": xvar,
            "group_reference": next((c["reference"] for c in cats if c["name"] == group), None)
            or (ds.var(group).get("levels") or [{}])[0].get("value") if group else None}


def model_terms(ds: D.Dataset, s: dict, cont: list[str], cat_names: list[str]) -> tuple[list[list[str]], list[str]]:
    """선택 항 검사: 교호작용 [[a, b], …](또는 'a:b'), 2차항 [연속 변수, …]. 기본은 없음(주효과만)."""
    L = Labels(ds)
    preds = cont + cat_names
    inter, seen = [], set()
    for it in s.get("interactions") or []:
        pair = it.split(":") if isinstance(it, str) else list(it)
        if len(pair) != 2:
            raise StatsError("교호작용은 두 변수의 짝으로 고르세요(예: 온도 × 산 종류).")
        a, b = (str(x).strip() for x in pair)
        for v in (a, b):
            if v not in preds:
                raise StatsError(f"교호작용의 '{v}'가 설명 변수에 없습니다. 연속·범주 설명 변수로 먼저 넣은 뒤 고르세요.")
        if a == b:
            raise StatsError(f"'{L.termname(a)}'끼리의 교호작용은 만들 수 없습니다 — 곡선은 2차항으로 넣으세요.")
        if a in cat_names and b in cont:  # 이름은 연속 × 범주 순서로 맞춘다
            a, b = b, a
        key = frozenset((a, b))
        if key in seen:
            continue
        seen.add(key)
        inter.append([a, b])
    quad = []
    for c in s.get("quadratic") or []:
        if c not in cont:
            raise StatsError(f"2차항 '{c}'는 연속 설명 변수가 아닙니다. 연속 설명 변수로 넣은 변수만 2차항을 넣을 수 있습니다.")
        if c not in quad:
            quad.append(c)
    return inter, quad


def _precheck(ds: D.Dataset, spec: dict) -> tuple:
    """목록별 삭제 뒤 표본으로 미리 확인 — 상수 변수, 수준 수, 수준별 n."""
    L = Labels(ds)
    cols = [spec["outcome"]] + spec["continuous"] + [c["name"] for c in spec["categorical"]]
    if spec["group"] and spec["group"] not in cols:
        cols.append(spec["group"])
    d, dropped = core.complete_cases(ds.df, cols)
    if len(d) < 3:
        raise StatsError(f"결측을 뺀 뒤 남은 런이 {len(d)}개뿐입니다. 결과·설명 변수가 모두 채워진 런을 3개 이상 넣으세요.")
    for c in spec["continuous"]:
        if d[c].astype(float).nunique() < 2:
            raise StatsError(f"'{L.var(c)}' 값이 모두 같아({F.n(float(d[c].iloc[0]), 2)}) 회귀에 넣을 수 없습니다 — 빼거나 다른 값으로 실험한 런을 넣으세요.")
    for c in spec["categorical"] + ([{"name": spec["group"]}] if spec["group"] else []):
        present = sorted(set(d[c["name"]].astype(str)))
        if len(present) < 2:
            only = L.level(c["name"], present[0]) if present else "없음"
            raise StatsError(f"{L.var(c['name'], unit=False)}가 1개뿐이라({only}) "
                             + ("t검정을 할 수 없습니다" if c["name"] == spec["group"] else "회귀에 넣을 수 없습니다")
                             + f" — 두 가지 이상의 {L.var(c['name'], unit=False)}로 실험한 런을 넣으세요.")
        if c.get("reference") and str(c["reference"]) not in present:
            raise StatsError(f"기준 수준 '{L.level(c['name'], c['reference'])}'의 런이 결측을 뺀 뒤 남지 않았습니다. 다른 기준 수준을 고르세요.")
    if spec["group"]:
        counts = d[spec["group"]].astype(str).value_counts()
        small = [k for k, v in counts.items() if v < 2]
        if small:
            raise StatsError(f"'{', '.join(L.level(spec['group'], k) for k in small)}' 수준의 런이 1개뿐입니다 — 수준마다 2개 이상(권장 3개 이상) 넣거나 그 수준의 런을 빼세요.")
    for c in spec.get("quadratic") or []:
        if d[c].astype(float).nunique() < 3:
            raise StatsError(f"'{L.var(c, unit=False)}'의 2차항을 넣으려면 서로 다른 값이 3개 이상 있어야 합니다(지금 {d[c].astype(float).nunique()}개). "
                             "2차항을 빼거나 수준을 늘리세요.")
    cat_lv = [(c["name"], core.level_order(d[c["name"]], c.get("reference"), c.get("levels"))) for c in spec["categorical"]]
    X, _terms = core.design(d, spec["continuous"], cat_lv, spec.get("interactions") or [], spec.get("quadratic") or [])
    k = X.shape[1]
    if len(d) <= k:
        raise StatsError(f"런 {len(d)}개로 회귀 계수 {k}개를 추정할 수 없습니다. 런을 더 넣거나 설명 변수를 줄이세요(계수보다 런이 많아야 합니다).")
    return d, dropped


# ---------------------------------------------------------------- 가정 점검

def _st(key, name_ko, name_en, status, test, stat, threshold, ko, en, data=None, test_en=None, stat_en=None, threshold_en=None):
    """test·stat·threshold는 한국어, *_en은 영어(없으면 한국어와 같음 — 기호·숫자만 있는 경우)."""
    return {"key": key, "name_ko": name_ko, "name_en": name_en, "status": status, "test": test, "stat": stat,
            "threshold": threshold, "text_ko": ko, "text_en": en, "data": data,
            "test_en": test_en or test, "stat_en": stat_en or stat, "threshold_en": threshold_en or threshold}


def assumptions(ds: D.Dataset, spec: dict, c: dict) -> list[dict]:
    L = Labels(ds)
    out = []
    reg, grp = c.get("regression"), c.get("groups")
    labels = ds.run_labels()
    used = c["used_index"]
    run_of = [labels[i] for i in used]
    if reg:
        n = reg["fit"]["n"]
        lowpow_ko = f" 다만 n = {n}으로 작아 검정력이 낮으므로 '위반 없음'을 보장하지는 않습니다." if n < SMALL_N_RESID else ""
        lowpow_en = f" With n = {n}, the test has low power, so this does not prove the assumption holds." if n < SMALL_N_RESID else ""
        # 1. 잔차 정규성
        sw = reg["shapiro"]
        if sw:
            W, p = sw["W"], sw["p"]
            stat = f"W = {F.n(W, 3)}, {F.p_txt(p, True)}, n = {n}"
            stat_en = f"W = {F.n(W, 3)}, {F.p_txt(p, False)}, n = {n}"
            sk = f"왜도 {F.n(reg['skew'], 2)}, 첨도(초과) {F.n(reg['kurtosis_excess'], 2)}"
            if p >= spec["alpha"]:
                st, ko, en = "pass", f"잔차가 정규분포에서 벗어났다는 근거가 없습니다({sk})." + lowpow_ko, \
                    "No evidence that residuals depart from normality." + lowpow_en
            elif n >= SMALL_N_RESID:
                st, ko, en = "warn", f"잔차가 정규분포와 다릅니다({sk}). n ≥ 30이라 계수 추정은 비교적 견고하지만 p값·신뢰구간은 근사로 보세요. Q–Q 그림에서 꼬리를 확인하세요.", \
                    "Residuals depart from normality; with n ≥ 30 coefficient inference is approximately valid, but treat p-values and CIs as approximate."
            else:
                st, ko, en = "fail", f"잔차가 정규분포와 다르고 n < 30입니다({sk}). p값·신뢰구간을 그대로 믿기 어렵습니다 — 이상치·변수 변환(로그 등)을 검토하세요.", \
                    "Residuals are non-normal and n < 30; p-values and CIs may be unreliable — check outliers or consider a transformation."
            out.append(_st("normality", "잔차 정규성", "Normality of residuals", st, "Shapiro–Wilk", stat, "p ≥ .05 (α = .05)", ko, en,
                           {"qq": reg["qq"]}, stat_en=stat_en))
        # 2. 등분산
        bp = reg["bp"]
        stat = f"LM = {F.n(bp['LM'], 2)}, df = {bp['df']}, {F.p_txt(bp['p'], True)}"
        stat_en = f"LM = {F.n(bp['LM'], 2)}, df = {bp['df']}, {F.p_txt(bp['p'], False)}"
        if bp["p"] >= spec["alpha"]:
            st, ko, en = "pass", "잔차의 퍼짐이 예측값·설명 변수에 따라 달라진다는 근거가 없습니다 — 일반(OLS) 표준오차를 주 결과로 씁니다." + lowpow_ko, \
                "No evidence of heteroscedasticity; conventional OLS standard errors are reported as primary." + lowpow_en
        else:
            st, ko, en = "fail", "잔차의 퍼짐이 일정하지 않습니다(이분산). 표 1에는 HC3 강건 표준오차(와 그로 계산한 t·p·95% CI)를 주 결과로 씁니다.", \
                "Heteroscedasticity detected; HC3 heteroscedasticity-consistent standard errors are reported as primary in Table 1."
        out.append(_st("homoscedasticity", "등분산(잔차)", "Homoscedasticity", st, "Breusch–Pagan (Koenker, studentized)", stat,
                       "p ≥ .05 (α = .05)", ko, en, {"fitted": reg["fitted"], "resid": reg["resid"], "run": run_of}, stat_en=stat_en))
        # 3. 다중공선성
        g = reg["gvif"]
        if g:
            items = sorted(((t, v["vif_equiv"]) for t, v in g.items()), key=lambda x: -(x[1] or 0))
            extra = [t for t, _v in items if ":" in t or t.endswith("^2")]
            # 판정은 주효과 항으로만 — 곱항·2차항은 (중심화해도) 원래 변수와 겹치는 것이 정상이다
            mx = max([(v or 1.0) for t, v in items if t not in extra] or [1.0])
            stat = ", ".join(f"{L.termname(t)} {F.n(v, 2)}" for t, v in items)
            stat_en = ", ".join(f"{L.termname(t, 'en')} {F.n(v, 2)}" for t, v in items)
            st = "pass" if mx <= 5 else "warn" if mx <= 10 else "fail"
            ko = {"pass": "설명 변수끼리 겹치는 정도가 작습니다.", "warn": "설명 변수끼리 꽤 겹칩니다 — 계수의 표준오차가 커졌을 수 있습니다.",
                  "fail": "설명 변수끼리 심하게 겹칩니다 — 계수를 따로 해석하기 어렵습니다. 겹치는 변수 하나를 빼거나 설계를 바꾸세요."}[st]
            en = {"pass": "Low multicollinearity.", "warn": "Moderate multicollinearity; standard errors may be inflated.",
                  "fail": "Severe multicollinearity; individual coefficients are not interpretable."}[st]
            if extra:
                ko += " 판정은 주효과 항으로만 했습니다(곱항·2차항은 원래 변수와 겹치는 것이 정상)."
                en += " The verdict uses main-effect terms only (product and quadratic terms are expected to overlap with their components)."
            has_multi = any(v["df"] > 1 for v in g.values())
            note = " (자유도 2 이상 항은 GVIF^(1/(2·df))의 제곱)" if has_multi else ""
            note_en = " (terms with df ≥ 2: squared GVIF^(1/(2·df)))" if has_multi else ""
            out.append(_st("vif", "다중공선성", "Multicollinearity", st, "VIF" + (" / GVIF" if has_multi else ""), stat + note,
                           "VIF ≤ 5 통과 · 5–10 주의 · > 10 실패", ko, en, stat_en=stat_en + note_en,
                           threshold_en="VIF ≤ 5 pass · 5–10 caution · > 10 fail"))
        # 4. 영향점
        cooks = reg["cooks"]
        cut = 4 / n
        big = [(run_of[i], d) for i, d in enumerate(cooks) if d is not None and d > cut]
        big.sort(key=lambda x: -x[1])
        mx = max((d for d in cooks if d is not None), default=0)
        stat = f"최대 D = {F.n(mx, 3)}; 4/n = {F.n(cut, 3)}; 넘은 런 {len(big)}개"
        stat_en = f"max D = {F.n(mx, 3)}; 4/n = {F.n(cut, 3)}; runs above 4/n: {len(big)}"
        if not big:
            st, ko, en = "pass", "Cook's D가 4/n을 넘는 런이 없습니다 — 한두 런에 좌우되는 결과는 아닙니다.", "No observation exceeds Cook's D > 4/n."
        else:
            lst = ", ".join(f"{r} ({F.n(d, 3)})" for r, d in big[:8]) + (" …" if len(big) > 8 else "")
            st = "fail" if mx > 1 else "warn"
            ko = f"영향이 큰 런: {lst}. 이 런들을 빼고 다시 돌려 결론이 바뀌는지 확인하세요(측정 오류가 확인될 때만 빼고, 뺐다면 논문에 밝히세요)."
            en = f"Influential runs: {lst}. Re-fit without them as a sensitivity check; exclude only with a documented reason."
        out.append(_st("influence", "영향점", "Influential observations", st, "Cook's distance", stat, "D > 4/n 주의 · D > 1 실패", ko, en,
                       {"cooks": cooks, "run": run_of, "cut": cut}, stat_en=stat_en, threshold_en="D > 4/n caution · D > 1 fail"))
        # 5. 선형성
        lin = [x for x in reg["linearity"] if x["testable"]]
        inq = [x["var"] for x in reg["linearity"] if x.get("in_model")]
        q_ko = (f" {', '.join(L.var(v, unit=False) for v in inq)}는 2차항을 모형에 넣어 따로 검정하지 않았습니다(계수표의 2차항 참고)." if inq else "")
        q_en = (f" {', '.join(L.var(v, 'en', unit=False) for v in inq)}: quadratic term already in the model (see its coefficient)." if inq else "")
        lin_test_en = "t-test of an added centred quadratic term (predictors with ≥ 3 levels)"
        if lin:
            bad = [x for x in lin if x["p"] is not None and x["p"] < spec["alpha"]]
            stat = "; ".join(f"{L.var(x['var'], unit=False)} 2차항 {F.p_txt(x['p'], True)}" for x in lin)
            stat_en = "; ".join(f"{L.var(x['var'], 'en', unit=False)} quadratic {F.p_txt(x['p'], False)}" for x in lin)
            if bad:
                st = "warn"
                ko = f"{F.w(', '.join(L.var(x['var'], unit=False) for x in bad), '과')} 결과 변수의 관계가 곧은 선이 아닐 수 있습니다 — 잔차-설명 변수 그림을 보고 2차항을 넣는 모형을 검토하세요."
                en = "Possible curvature for " + ", ".join(L.var(x["var"], "en", unit=False) for x in bad) + "; consider adding a quadratic term."
            else:
                st, ko, en = "pass", "중심화한 2차항을 더해도 유의하지 않아 곧은 선 관계와 어긋난다는 근거가 없습니다." + lowpow_ko, \
                    "Adding centred quadratic terms did not improve fit; no evidence against linearity." + lowpow_en
            out.append(_st("linearity", "선형성", "Linearity", st, "2차항 추가 t검정(수준 3개 이상인 연속 변수)", stat, "p ≥ .05", ko + q_ko, en + q_en,
                           {"by": {x["var"]: {"x": [float(v) for v in ds.df.loc[used, x["var"]]], "resid": reg["resid"]} for x in lin}},
                           test_en=lin_test_en, stat_en=stat_en))
        elif inq:
            out.append(_st("linearity", "선형성", "Linearity", "info", "모형의 2차항", "2차항을 모형에 넣음", "—",
                           q_ko.strip() + " 2차항이 유의하면 곧은 선이 아닌 곡선 관계입니다.",
                           q_en.strip() + " A significant quadratic term indicates curvature.",
                           test_en="Quadratic term in model", stat_en="quadratic term included"))
        else:
            out.append(_st("linearity", "선형성", "Linearity", "info", "—", "수준이 3개 이상인 연속 변수가 없음", "—",
                           "연속 변수의 값이 2가지뿐이라 곧은 선인지 자료로 확인할 수 없습니다(두 점은 늘 직선).",
                           "Continuous predictors have fewer than 3 distinct values; linearity cannot be checked.",
                           stat_en="no continuous predictor with ≥ 3 distinct values"))
        # 6. 독립성
        if "run_order" in ds.df.columns:
            ro = ds.df.loc[used, "run_order"].astype(float).to_numpy()
            r = np.asarray(reg["resid"])[np.argsort(ro, kind="stable")]
            dw = float(np.sum(np.diff(r) ** 2) / np.sum(r ** 2))
            st = "warn" if dw < 1.5 or dw > 2.5 else "info"
            stat = f"Durbin–Watson(실험 순서) = {F.n(dw, 2)}"
            stat_en = f"Durbin–Watson (run order) = {F.n(dw, 2)}"
            ko = ("실험 순서대로 놓은 잔차가 이웃끼리 닮아 있습니다 — 시간에 따른 표류(장비·시약)를 의심하세요."
                  if st == "warn" else "실험 순서로 본 잔차의 자기상관은 뚜렷하지 않습니다.") + \
                " 독립성은 자료만으로 증명할 수 없습니다 — 런 순서 무작위화, 반복이 같은 추출물의 반복 측정(기술 반복)이 아닌지로 판단하세요."
            en = "Independence cannot be established from the data; it follows from the design (randomised run order, true replicates)."
        else:
            dw = reg["dw"]
            st, stat = "info", f"Durbin–Watson(행 순서, 참고) = {F.n(dw, 2)}"
            stat_en = f"Durbin–Watson (row order, reference only) = {F.n(dw, 2)}"
            ko = "독립성은 자료만으로 검정할 수 없습니다 — 런 순서를 무작위로 했는지, 반복이 서로 다른 추출(생물·공정 반복)인지 같은 추출물의 반복 측정인지로 판단하세요. 행 순서가 실험 순서일 때만 DW 값이 뜻이 있습니다."
            en = "Independence is a design property and cannot be tested automatically (DW shown for row order is only meaningful if rows are in run order)."
        out.append(_st("independence", "독립성", "Independence", st, "설계로 판단", stat, "DW 1.5–2.5 (참고)", ko, en,
                       test_en="Design-based", stat_en=stat_en, threshold_en="DW 1.5–2.5 (reference)"))
        # 7. 표본 크기(회귀)
        p_cols = reg["fit"]["k"] - 1
        ratio = n / max(p_cols, 1)
        st = "pass" if ratio >= 10 else "warn" if ratio >= 5 else "fail"
        stat = f"n = {n}, 설명 계수 {p_cols}개 → 계수당 {F.n(ratio, 1)}"
        ko = {"pass": "계수 하나당 런이 10개 이상입니다.", "warn": "계수 하나당 런이 5–10개라 추정이 불안정할 수 있습니다 — 결과를 잠정적으로 쓰세요.",
              "fail": "계수 하나당 런이 5개 미만입니다 — 과적합 위험이 큽니다. 런을 늘리거나 변수를 줄이세요."}[st]
        en = {"pass": "At least 10 observations per coefficient.", "warn": "5–10 observations per coefficient; estimates may be unstable.",
              "fail": "Fewer than 5 observations per coefficient; high risk of overfitting."}[st]
        out.append(_st("sample_size", "표본 크기(회귀)", "Sample size (regression)", st, "계수당 n", stat, "≥ 10 통과 · 5–10 주의 · < 5 실패", ko, en,
                       test_en="n per coefficient", stat_en=f"n = {n}, {p_cols} coefficients → {F.n(ratio, 1)} per coefficient",
                       threshold_en="≥ 10 pass · 5–10 caution · < 5 fail"))
    if grp:
        gname = spec["group"]
        ns = [x["n"] for x in grp["desc"]]
        mn = min(ns)
        st = "pass" if mn >= 10 else "warn" if mn >= 5 else "fail"
        stat = ", ".join(f"{L.level(gname, x['level'])} n = {x['n']}" for x in grp["desc"])
        ko = {"pass": "집단마다 런이 10개 이상입니다.", "warn": "가장 작은 집단의 런이 5–9개라 검정력이 낮습니다 — 차이가 없다는 결론은 내리지 마세요.",
              "fail": "가장 작은 집단의 런이 5개 미만입니다 — 가정을 확인할 수 없고 검정력이 매우 낮습니다. 반복을 늘리세요."}[st]
        en = {"pass": "At least 10 runs per group.", "warn": "Smallest group has 5–9 runs; low power.",
              "fail": "Smallest group has fewer than 5 runs; assumptions cannot be checked and power is very low."}[st]
        out.append(_st("group_n", "표본 크기(집단)", "Sample size (groups)", st, "집단별 n", stat, "≥ 10 통과 · 5–9 주의 · < 5 실패", ko, en,
                       test_en="n per group", stat_en=", ".join(f"{L.level(gname, x['level'], 'en')} n = {x['n']}" for x in grp["desc"]),
                       threshold_en="≥ 10 pass · 5–9 caution · < 5 fail"))
        # 집단별 정규성
        norm = [x for x in grp["normality"] if x["p"] is not None]
        if norm:
            bad = [x for x in norm if x["p"] < spec["alpha"]]
            stat = "; ".join(f"{L.level(gname, x['level'])} W = {F.n(x['W'], 3)}, {F.p_txt(x['p'], True)}" for x in norm)
            small = min(x["n"] for x in norm) < SMALL_N_GROUP
            if not bad:
                st = "pass"
                ko = "집단마다 정규분포에서 벗어났다는 근거가 없습니다." + (f" 집단 n이 {SMALL_N_GROUP}보다 작아 검정력이 낮습니다 — 보조로 Mann–Whitney/Kruskal–Wallis 결과도 함께 봅니다." if small else "")
                en = "No evidence of non-normality within groups." + (" Group sizes are small, so power is low." if small else "")
            else:
                st = "warn" if min(x["n"] for x in bad) >= 30 else "fail"
                ko = f"{', '.join(L.level(gname, x['level']) for x in bad)} 집단이 정규분포와 다릅니다 — 비모수 검정(" + \
                    ("Mann–Whitney U" if grp["kind"] == "t" else "Kruskal–Wallis") + ") 결과를 민감도 분석으로 함께 보고하세요."
                en = "Non-normal distribution in " + ", ".join(L.level(gname, x["level"], "en") for x in bad) + \
                    "; report the non-parametric test as a sensitivity analysis."
            out.append(_st("group_normality", "집단별 정규성", "Normality within groups", st, "Shapiro–Wilk (집단별)", stat, "p ≥ .05", ko, en,
                           test_en="Shapiro–Wilk (per group)",
                           stat_en="; ".join(f"{L.level(gname, x['level'], 'en')} W = {F.n(x['W'], 3)}, {F.p_txt(x['p'], False)}" for x in norm)))
        # Levene
        lv = grp["levene"]
        stat = f"F({lv['df1']}, {lv['df2']}) = {F.n(lv['F'], 2)}, {F.p_txt(lv['p'], True)}"
        stat_en = f"F({lv['df1']}, {lv['df2']}) = {F.n(lv['F'], 2)}, {F.p_txt(lv['p'], False)}"
        welch = grp["primary"] == "welch"
        if lv["p"] is not None and lv["p"] >= spec["alpha"]:
            st = "pass"
            ko = "집단 간 분산이 다르다는 근거가 없습니다." + (" (Welch 검정은 등분산을 가정하지 않으므로 어느 쪽이든 주 결과는 그대로입니다.)" if welch else "")
            en = "No evidence of unequal variances." + (" Welch's test does not assume equal variances." if welch else "")
        else:
            st = "warn" if welch else "fail"
            ko = "집단 간 분산이 다릅니다. " + ("Welch 검정은 등분산을 가정하지 않으므로 주 결과로 그대로 씁니다." if welch
                                        else "Student t(등분산 가정)는 맞지 않습니다 — Welch 검정을 쓰세요.")
            en = "Unequal variances. " + ("Welch's test remains valid." if welch else "Student's t is not appropriate; use Welch's test.")
        out.append(_st("levene", "등분산(집단)", "Equal variances (groups)", st, "Levene (중앙값 기준, Brown–Forsythe)", stat, "p ≥ .05", ko, en,
                       test_en="Levene (median-centred, Brown–Forsythe)", stat_en=stat_en))
    return out


def overall(checks: list[dict]) -> str:
    return max((c["status"] for c in checks), key=lambda s: STATUS_RANK[s], default="pass")


# ---------------------------------------------------------------- 방법 문장

def test_name(grp: dict, lang: str) -> str:
    if not grp:
        return ""
    if grp["kind"] == "t":
        return ("Welch t-검정" if lang == "ko" else "Welch's t-test") if grp["primary"] == "welch" else \
            ("Student t-검정(등분산 가정)" if lang == "ko" else "Student's t-test (equal variances)")
    return ("Welch 일원분산분석" if lang == "ko" else "Welch's one-way ANOVA") if grp["primary"] == "welch" else \
        ("일원분산분석" if lang == "ko" else "one-way ANOVA")


def methods(ds: D.Dataset, spec: dict, c: dict, primary_se: str) -> dict:
    L = Labels(ds)
    reg, grp = c.get("regression"), c.get("groups")
    a = F.bounded(spec["alpha"], 2, False)
    a_ko = F.bounded(spec["alpha"], 2, True)
    dropped = len(c["dropped_index"])
    v = versions()
    sw = f"Python {v['python']}, statsmodels {v['statsmodels']}, SciPy {v['scipy']}, pandas {v['pandas']}"
    ko, en = [], []
    if reg:
        preds_ko = [L.var(x, unit=False) for x in spec["continuous"]] + \
            [f"{L.var(x['name'], unit=False)}(범주, 기준 = {L.level(x['name'], x['reference'])})" for x in spec["categorical"]]
        preds_en = [L.var(x, "en", unit=False).lower() for x in spec["continuous"]] + \
            [f"{L.var(x['name'], 'en', unit=False).lower()} (categorical; reference = {L.level(x['name'], x['reference'], 'en')})" for x in spec["categorical"]]
        ko.append(f"{F.w(L.var(spec['outcome'], unit=False), '을')} 결과 변수로, {F.w(', '.join(preds_ko), '을')} 설명 변수로 한 다중 선형 회귀(최소제곱법, OLS)를 적합했다.")
        en.append(f"{L.var(spec['outcome'], 'en', unit=False)} was regressed on {', '.join(preds_en)} using ordinary least squares (OLS).")
        extra_ko = [L.termname(f"{a}:{b}") + " 교호작용" for a, b in spec.get("interactions") or []] + \
            [L.var(c, unit=False) + "의 2차항" for c in spec.get("quadratic") or []]
        extra_en = [f"the {L.termname(f'{a}:{b}', 'en').lower()} interaction" for a, b in spec.get("interactions") or []] + \
            [f"a quadratic term for {L.var(c, 'en', unit=False).lower()}" for c in spec.get("quadratic") or []]
        if extra_ko:
            ko.append(f"모형에는 {', '.join(extra_ko)}을 더했고, 곱항·2차항은 연속 변수를 분석 표본 평균으로 중심화해 만들었다"
                      "(주효과 계수는 다른 연속 변수의 평균·범주의 기준 수준에서의 기울기·차이).")
            en.append(f"The model also included {', '.join(extra_en)}; continuous variables were mean-centred in product and quadratic terms, "
                      "so main-effect coefficients are slopes or differences at the mean of the other continuous predictors and the reference level.")
        ko.append("잔차의 정규성은 Shapiro–Wilk 검정, 등분산성은 Breusch–Pagan 검정(Koenker 학생화), 다중공선성은 VIF, 영향점은 Cook's D(> 4/n)로 점검했다"
                  + ("; 이분산이 확인되어 HC3 강건 표준오차를 보고했다." if primary_se == "HC3" else "."))
        en.append("Residual normality was assessed with the Shapiro–Wilk test, homoscedasticity with the studentized Breusch–Pagan test, "
                  "multicollinearity with variance inflation factors, and influence with Cook's distance (> 4/n)"
                  + ("; because of heteroscedasticity, HC3 robust standard errors are reported." if primary_se == "HC3" else "."))
    if grp:
        g = spec["group"]
        if grp["kind"] == "t":
            ko.append(f"{L.var(g, unit=False)}에 따른 {L.var(spec['outcome'], unit=False)} 차이는 {test_name(grp, 'ko')}(양측, α = {a_ko})으로 비교했고, "
                      f"효과 크기는 Hedges' g로, 등분산은 Levene 검정(중앙값 기준)으로 확인했으며 Mann–Whitney U 검정을 민감도 분석으로 함께 했다.")
            en.append(f"Differences in {L.var(spec['outcome'], 'en', unit=False).lower()} between {L.var(g, 'en', unit=False).lower()}s were tested with "
                      f"{test_name(grp, 'en')} (two-sided, α = {a}), with Hedges' g as the effect size, Levene's test (median-centred) for equality of variances, "
                      "and the Mann–Whitney U test as a sensitivity analysis.")
        else:
            ko.append(f"{L.var(g, unit=False)} {len(grp['levels'])}수준의 차이는 {test_name(grp, 'ko')}으로 검정한 뒤, 쌍별 "
                      + ("Welch t-검정" if grp["primary"] == "welch" else "t-검정(합동 SD)")
                      + f"에 Holm 보정을 적용했다(양측, α = {a_ko}); Kruskal–Wallis 검정을 민감도 분석으로 함께 했다.")
            en.append(f"Differences among the {len(grp['levels'])} {L.var(g, 'en', unit=False).lower()}s were tested with {test_name(grp, 'en')}, "
                      "followed by pairwise " + ("Welch t-tests" if grp["primary"] == "welch" else "t-tests (pooled SD)")
                      + f" with Holm adjustment (two-sided, α = {a}); the Kruskal–Wallis test served as a sensitivity analysis.")
    ko.append(f"결측이 있는 런은 목록별 삭제했다(전체 {c['n_total']}개 중 {dropped}개 제외, 분석 n = {c['n_used']}). 분석: {sw}.")
    en.append(f"Runs with missing values were excluded listwise ({dropped} of {c['n_total']} excluded; analysed n = {c['n_used']}). Software: {sw}.")
    nx = len(spec.get("interactions") or []) + len(spec.get("quadratic") or [])
    short_ko = " · ".join(x for x in [
        "OLS" + (f" + 교호작용·2차항 {nx}개" if nx else "") + (" (HC3 강건 SE)" if primary_se == "HC3" else "") if reg else "",
        (test_name(grp, "ko") + f", 양측, α = {a_ko}" + (", 쌍별 Holm 보정" if grp and grp["kind"] == "anova" else "")) if grp else ""] if x)
    short_en = " · ".join(x for x in [
        "OLS" + (f" + {nx} interaction/quadratic term{'s' if nx > 1 else ''}" if nx else "") + (" (HC3 robust SE)" if primary_se == "HC3" else "") if reg else "",
        (test_name(grp, "en") + f", two-sided, α = {a}" + (", Holm-adjusted pairwise tests" if grp and grp["kind"] == "anova" else "")) if grp else ""] if x)
    return {"ko": " ".join(ko), "en": " ".join(en), "short_ko": short_ko, "short_en": short_en}


def marginal_vs_adjusted(ds: D.Dataset, spec: dict, c: dict, primary_se: str) -> dict | None:
    reg, grp = c.get("regression"), c.get("groups")
    g = spec["group"]
    if not (reg and grp) or g not in [x["name"] for x in spec["categorical"]]:
        return None
    L = Labels(ds)
    u = L.unit(spec["outcome"])
    u_p = "%p" if u == "%" else u
    rows = []
    ref = grp["levels"][0]
    for lv in grp["levels"][1:]:
        m_other = next(x["mean"] for x in grp["desc"] if x["level"] == lv)
        m_ref = next(x["mean"] for x in grp["desc"] if x["level"] == ref)
        co = next(x for x in reg["coef"] if x["term"] == f"{g}[{lv}]")
        se = co["robust"] if primary_se == "HC3" else co
        rows.append({"level": lv, "marginal": m_other - m_ref, "adjusted": co["B"], "adjusted_ci": se["ci"], "adjusted_p": se["p"]})
    d = F.dec_for(next(x for x in reg["coef"] if x["term"] == f"{g}[{rows[0]['level']}]")["SE"])
    parts_ko = "; ".join(f"{L.level(g, r['level'])} − {L.level(g, ref)}: 단순 차이 {F.n(r['marginal'], d)} {u_p}, 보정 차이 {F.n(r['adjusted'], d)} {u_p}" for r in rows)
    parts_en = "; ".join(f"{F.mid_en(L.level(g, r['level'], 'en'))} − {F.mid_en(L.level(g, ref, 'en'))}: marginal {F.n(r['marginal'], d)}, adjusted {F.n(r['adjusted'], d)}" for r in rows)
    others = "·".join(L.var(x, unit=False) for x in spec["continuous"]) or "다른 변수"
    others_en = ", ".join(L.var(x, "en", unit=False).lower() for x in spec["continuous"]) or "other predictors"
    ko = (f"t검정(집단 비교)은 {F.w(others, '을')} 무시한 단순 평균 차이이고, 회귀의 {L.var(g, unit=False)} 계수는 {F.w(others, '을')} 같게 놓았을 때의 차이(보정 효과)입니다. "
          f"모든 조건 조합에 집단이 같은 수로 들어간 균형 설계면 두 값이 거의 같고, 불균형이면 달라집니다. 여기서는 {parts_ko}. "
          f"또한 회귀는 {F.w(others, '로')} 설명되는 변동을 빼므로 오차가 작아져 같은 차이도 더 작은 p값을 얻을 수 있습니다.")
    en = (f"The group comparison tests the marginal (unadjusted) mean difference, whereas the regression coefficient is the difference holding {others_en} constant. "
          f"In a balanced design the two coincide closely; here {parts_en}. The regression also removes variance explained by {others_en}, so it is usually more precise.")
    return {"rows": rows, "ko": ko, "en": en}


# ---------------------------------------------------------------- 실행

def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v)) or (isinstance(v, str) and not v.strip())


def run(source: dict, spec: dict | None = None, options: dict | None = None) -> Result:
    try:
        ds = D.load(source)
    except D.DataError as ex:
        raise StatsError(str(ex)) from ex
    try:
        sp = resolve_spec(ds, spec)
    except D.DataError as ex:
        raise StatsError(str(ex)) from ex
    _precheck(ds, sp)
    core_spec = {"outcome": sp["outcome"], "continuous": sp["continuous"],
                 "categorical": [{"name": x["name"], "reference": x["reference"], "levels": x["levels"]} for x in sp["categorical"]],
                 "group": sp["group"], "group_reference": sp["group_reference"], "test": sp["test"], "alpha": sp["alpha"],
                 "interactions": sp["interactions"], "quadratic": sp["quadratic"]}
    if sp["group"] and sp["group"] not in [x["name"] for x in sp["categorical"]]:
        core_spec["group_levels"] = [x["value"] for x in ds.var(sp["group"]).get("levels") or []]
    try:
        c = core.analyze(ds.df, core_spec)
    except core.CoreError as ex:
        raise StatsError(f"계산하지 못했습니다: {ex}. 상수 변수나 완전히 겹치는 변수(예: 산마다 온도가 하나씩)를 빼고 다시 하세요.") from ex
    sp["core_spec"] = core_spec
    checks = assumptions(ds, sp, c)
    hetero = next((x for x in checks if x["key"] == "homoscedasticity"), None)
    primary_se = "HC3" if hetero and hetero["status"] == "fail" else "OLS"
    labels = ds.run_labels()
    out = {
        "dataset": {"title": ds.title_ko, "title_en": ds.title_en, "is_demo": ds.is_demo, "source": {k: v for k, v in ds.source.items() if k != "mapping"},
                    "n_total": c["n_total"], "n_used": c["n_used"], "confidentiality": ds.confidentiality,
                    "dropped": [{"run": labels[i], "reasons": {k: ds.missing.get(k, {}).get(int(i), "빈칸") for k in
                                                               [sp["outcome"]] + sp["continuous"] + [x["name"] for x in sp["categorical"]] + ([sp["group"]] if sp["group"] else [])
                                                               if _blank(ds.df.loc[i, k])}}
                                for i in c["dropped_index"]],
                    "codebook": ds.codebook, "warnings": ds.warnings},
        "spec": {k: v for k, v in sp.items() if k != "core_spec"},
        "regression": c["regression"] and {k: c["regression"][k] for k in ("columns", "terms", "coef", "term_tests", "fit", "gvif", "linearity", "shapiro", "bp", "dw",
                                                                         "interactions", "quadratic", "centers")},
        "primary_se": primary_se,
        "groups": c["groups"],
        "levels": c["levels"],
        "assumptions": checks, "overall": overall(checks),
        "methods": methods(ds, sp, c, primary_se),
        "marginal_vs_adjusted": marginal_vs_adjusted(ds, sp, c, primary_se),
        "software": versions(),
    }
    if out["groups"] and out["groups"]["kind"] == "anova":
        out["t_test_note"] = {"ko": f"수준이 {len(out['groups']['levels'])}개라 t검정 하나로는 비교할 수 없습니다. 전체 차이를 일원분산분석으로 본 뒤, 모든 쌍을 t검정하고 "
                                    "여러 번 검정해서 생기는 우연한 유의(1종 오류)를 Holm 방법으로 보정했습니다 — 이것이 3수준 이상에서의 't검정'입니다.",
                              "en": "With three or more groups, a single t-test is not possible; an omnibus ANOVA is followed by all pairwise t-tests with Holm adjustment for multiple comparisons."}
    r = Result(rid=uuid.uuid4().hex[:16], ds=ds, spec=sp, core=c, out=out)
    from . import report
    out["interpretation"] = {"ko": report.interpretation(r, "ko"), "en": report.interpretation(r, "en")}
    out["table1"] = {lang: report.table1_html(r, lang) for lang in ("ko", "en")}
    out["assumption_html"] = {lang: report.assumptions_html(r, lang, standalone=False) for lang in ("ko", "en")}
    out["caption"] = {lang: report.caption(r, lang) for lang in ("ko", "en")}
    out["result_id"] = r.rid
    out["plots"] = {"qq": c["regression"]["qq"] if c["regression"] else None,
                    "fitted": c["regression"]["fitted"] if c["regression"] else None,
                    "resid": c["regression"]["resid"] if c["regression"] else None}
    _keep(r)
    return r
