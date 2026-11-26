"""통계 계산 핵심 — numpy·pandas·scipy·statsmodels만 쓴다.

이 파일의 소스는 내보내기 패키지의 analysis.py에 그대로 들어간다(앱과 같은 숫자를 재현하기 위해).
그래서 앱의 다른 모듈을 import하지 않고, 글(해석·판정 문구)은 넣지 않는다 — 숫자만 돌려준다.

- 회귀: OLS (일반 SE + HC3 강건 SE), 표준화 β(연속 변수만, 표본 SD 비), 항별 F 검정, GVIF.
- 진단: Shapiro–Wilk(잔차), Breusch–Pagan(Koenker 학생화 판 = R lmtest::bptest 기본), Cook's D, 2차항 선형성 검정, Durbin–Watson.
- 집단 비교: Levene(중앙값 기준 = Brown–Forsythe = R car::leveneTest 기본), 집단별 Shapiro–Wilk,
  2수준 → Welch(기본)/Student t, 차이의 95% CI, Cohen's d·Hedges' g, Mann–Whitney U(점근, 연속성 보정);
  3수준 이상 → 고전·Welch 일원분산분석, 쌍별 Welch(또는 합동 SD) t + Holm 보정, Kruskal–Wallis.
"""
from __future__ import annotations

import math
from itertools import combinations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats as ss
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.oneway import anova_oneway
from statsmodels.stats.outliers_influence import OLSInfluence
from statsmodels.stats.stattools import durbin_watson

ALPHA = 0.05


class CoreError(ValueError):
    pass


def num(x):
    """JSON에 넣을 수 있는 float (NaN·inf → None)."""
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def complete_cases(df: pd.DataFrame, cols: list[str]) -> tuple[pd.DataFrame, list]:
    """목록별 삭제: cols 중 하나라도 비면 그 행을 뺀다. → (남은 표, 뺀 행 index)"""
    mask = df[cols].notna().all(axis=1)
    for c in cols:
        if df[c].dtype == object:
            mask &= df[c].astype(str).str.strip().ne("")
    return df.loc[mask].copy(), list(df.index[~mask])


def level_order(series: pd.Series, reference=None, levels=None) -> list[str]:
    """범주 수준 순서: 지정 순서 → 나머지 가나다순, 기준 수준을 맨 앞에."""
    present = sorted(set(series.dropna().astype(str)))
    order = [str(v) for v in (levels or []) if str(v) in present]
    order += [v for v in present if v not in order]
    if reference is not None:
        reference = str(reference)
        if reference not in order:
            raise CoreError(f"reference level '{reference}' not in data: {order}")
        order.remove(reference)
        order.insert(0, reference)
    return order


def design(d: pd.DataFrame, continuous: list[str], categorical: list[tuple[str, list[str]]]):
    """설계 행렬(절편 + 연속 + 처리 대비 가변수). 열 이름: '(Intercept)', 'temp_c', 'acid[HCl]'."""
    cols = {"(Intercept)": np.ones(len(d))}
    terms = {"(Intercept)": ["(Intercept)"]}
    for c in continuous:
        cols[c] = d[c].astype(float).to_numpy()
        terms[c] = [c]
    for name, lv in categorical:
        s = d[name].astype(str).to_numpy()
        terms[name] = []
        for level in lv[1:]:
            col = f"{name}[{level}]"
            cols[col] = (s == level).astype(float)
            terms[name].append(col)
    return pd.DataFrame(cols, index=d.index), terms


def gvif(X: pd.DataFrame, terms: dict) -> dict:
    """항별 GVIF (Fox & Monette 1992; 1자유도 항은 보통 VIF와 같음). R car::vif와 같은 정의."""
    Z = X.drop(columns=["(Intercept)"])
    names = list(Z.columns)
    out = {}
    if len(names) < 2:
        for t, cs in terms.items():
            if t != "(Intercept)":
                out[t] = {"gvif": 1.0, "df": len(cs), "gvif_adj": 1.0, "vif_equiv": 1.0}
        return out
    R = np.corrcoef(Z.to_numpy(), rowvar=False)
    detR = np.linalg.det(R)
    for t, cs in terms.items():
        if t == "(Intercept)":
            continue
        j = [names.index(c) for c in cs]
        rest = [i for i in range(len(names)) if i not in j]
        g = np.linalg.det(R[np.ix_(j, j)]) * (np.linalg.det(R[np.ix_(rest, rest)]) if rest else 1.0) / detR
        adj = g ** (1 / (2 * len(j)))
        out[t] = {"gvif": num(g), "df": len(j), "gvif_adj": num(adj), "vif_equiv": num(adj ** 2)}
    return out


def ols(d: pd.DataFrame, outcome: str, continuous: list[str], categorical: list[tuple[str, list[str]]],
        alpha: float = ALPHA) -> dict:
    y = d[outcome].astype(float)
    X, terms = design(d, continuous, categorical)
    n, k = X.shape
    if n <= k:
        raise CoreError(f"n={n} <= parameters={k}")
    if np.linalg.matrix_rank(X.to_numpy()) < k:
        raise CoreError("design matrix is rank deficient (constant or collinear predictor)")
    m = sm.OLS(y, X).fit()
    hc3 = m.get_robustcov_results(cov_type="HC3", use_t=True)
    tcrit = float(ss.t.ppf(1 - alpha / 2, m.df_resid))
    ci = m.conf_int(alpha)
    sdy = float(y.std(ddof=1))
    coef = []
    for i, col in enumerate(X.columns):
        b = float(m.params.iloc[i])
        se_r = float(hc3.bse[i])
        row = {"term": col, "B": num(b), "SE": num(m.bse.iloc[i]), "t": num(m.tvalues.iloc[i]), "p": num(m.pvalues.iloc[i]),
               "ci": [num(ci.iloc[i, 0]), num(ci.iloc[i, 1])], "beta": None,
               "robust": {"SE": num(se_r), "t": num(hc3.tvalues[i]), "p": num(hc3.pvalues[i]),
                          "ci": [num(b - tcrit * se_r), num(b + tcrit * se_r)]}}
        if col in continuous:
            row["beta"] = num(b * float(d[col].astype(float).std(ddof=1)) / sdy) if sdy > 0 else None
        coef.append(row)
    term_tests = []
    for t, cs in terms.items():
        if t == "(Intercept)":
            continue
        Rm = np.zeros((len(cs), k))
        for r, c in enumerate(cs):
            Rm[r, list(X.columns).index(c)] = 1
        ft, fr = m.f_test(Rm), hc3.f_test(Rm)
        term_tests.append({"term": t, "F": num(np.squeeze(ft.fvalue)), "df1": num(ft.df_num), "df2": num(ft.df_denom),
                           "p": num(np.squeeze(ft.pvalue)),
                           "robust": {"F": num(np.squeeze(fr.fvalue)), "p": num(np.squeeze(fr.pvalue))}})
    resid = m.resid.to_numpy()
    fitted = m.fittedvalues.to_numpy()
    infl = OLSInfluence(m)
    cooks = np.asarray(infl.cooks_distance[0])
    sw = ss.shapiro(resid) if 3 <= n <= 5000 else None
    bp = het_breuschpagan(resid, X.to_numpy())  # robust=True(기본): Koenker 학생화 판 n·R²
    lin = []
    for c in continuous:
        x = d[c].astype(float)
        if x.nunique() < 3:
            lin.append({"var": c, "testable": False, "levels": int(x.nunique())})
            continue
        X2 = X.copy()
        X2[c + "^2"] = (x - x.mean()) ** 2
        m2 = sm.OLS(y, X2).fit()
        lin.append({"var": c, "testable": True, "levels": int(x.nunique()), "B_quad": num(m2.params.iloc[-1]),
                    "t": num(m2.tvalues.iloc[-1]), "p": num(m2.pvalues.iloc[-1])})
    osm_osr, _fit = ss.probplot(resid / math.sqrt(m.mse_resid), dist="norm")
    return {
        "columns": list(X.columns), "terms": terms, "coef": coef, "term_tests": term_tests,
        "fit": {"n": int(n), "k": int(k), "df_model": num(m.df_model), "df_resid": num(m.df_resid), "r2": num(m.rsquared),
                "adj_r2": num(m.rsquared_adj), "F": num(m.fvalue), "F_p": num(m.f_pvalue), "rmse": num(math.sqrt(m.mse_resid)),
                "aic": num(m.aic), "sd_y": num(sdy)},
        "resid": [num(v) for v in resid], "fitted": [num(v) for v in fitted], "cooks": [num(v) for v in cooks],
        "leverage": [num(v) for v in infl.hat_matrix_diag], "stud_resid": [num(v) for v in infl.resid_studentized_internal],
        "shapiro": {"W": num(sw.statistic), "p": num(sw.pvalue)} if sw is not None else None,
        "bp": {"LM": num(bp[0]), "df": int(k - 1), "p": num(bp[1]), "F": num(bp[2]), "F_p": num(bp[3])},
        "gvif": gvif(X, terms), "linearity": lin, "dw": num(durbin_watson(resid)),
        "skew": num(ss.skew(resid)), "kurtosis_excess": num(ss.kurtosis(resid)),
        "qq": {"theoretical": [num(v) for v in osm_osr[0]], "sample": [num(v) for v in osm_osr[1]]},
    }


def _desc(y: np.ndarray, alpha: float) -> dict:
    n = len(y)
    mean = float(np.mean(y)) if n else None
    sd = float(np.std(y, ddof=1)) if n >= 2 else None
    se = sd / math.sqrt(n) if sd is not None else None
    tc = float(ss.t.ppf(1 - alpha / 2, n - 1)) if n >= 2 else None
    return {"n": n, "mean": num(mean), "sd": num(sd), "se": num(se), "median": num(np.median(y)) if n else None,
            "min": num(np.min(y)) if n else None, "max": num(np.max(y)) if n else None,
            "ci": [num(mean - tc * se), num(mean + tc * se)] if se is not None else [None, None]}


def welch_df(a: np.ndarray, b: np.ndarray) -> float:
    va, vb = np.var(a, ddof=1) / len(a), np.var(b, ddof=1) / len(b)
    return float((va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1)))


def two_sample(a: np.ndarray, b: np.ndarray, equal_var: bool, alpha: float = ALPHA) -> dict:
    """a − b. Welch(Satterthwaite df) 또는 Student(합동 분산)."""
    na, nb = len(a), len(b)
    va, vb = np.var(a, ddof=1), np.var(b, ddof=1)
    diff = float(np.mean(a) - np.mean(b))
    sp = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    if equal_var:
        se, df = sp * math.sqrt(1 / na + 1 / nb), float(na + nb - 2)
    else:
        se, df = math.sqrt(va / na + vb / nb), welch_df(a, b)
    r = ss.ttest_ind(a, b, equal_var=equal_var)
    tc = float(ss.t.ppf(1 - alpha / 2, df))
    d = diff / sp if sp > 0 else None
    J = 1 - 3 / (4 * (na + nb) - 9)
    return {"t": num(r.statistic), "df": num(df), "p": num(r.pvalue), "diff": num(diff), "se_diff": num(se),
            "ci": [num(diff - tc * se), num(diff + tc * se)], "cohen_d": num(d), "hedges_g": num(d * J) if d is not None else None,
            "sd_pooled": num(sp), "t_hand": num(diff / se) if se > 0 else None}


def group_compare(d: pd.DataFrame, outcome: str, group: str, levels: list[str], test: str = "welch",
                  alpha: float = ALPHA) -> dict:
    """test: 'welch'(기본) | 'student' | 'auto'(Levene p < α면 Welch)."""
    ys = [d.loc[d[group].astype(str) == lv, outcome].astype(float).to_numpy() for lv in levels]
    if len(levels) < 2:
        raise CoreError("need at least 2 groups")
    if any(len(y) < 2 for y in ys):
        raise CoreError("each group needs n >= 2")
    N, g = sum(len(y) for y in ys), len(ys)
    lev = ss.levene(*ys, center="median")
    out = {"levels": levels, "desc": [{"level": lv, **_desc(y, alpha)} for lv, y in zip(levels, ys)],
           "levene": {"F": num(lev.statistic), "df1": g - 1, "df2": N - g, "p": num(lev.pvalue), "center": "median"},
           "normality": [{"level": lv, "n": len(y), **({"W": num(s.statistic), "p": num(s.pvalue)} if len(y) >= 3 and np.ptp(y) > 0 else {"W": None, "p": None})}
                         for lv, y in zip(levels, ys) for s in [ss.shapiro(y) if len(y) >= 3 and np.ptp(y) > 0 else None]],
           "test_option": test}
    use_welch = test == "welch" or (test == "auto" and (lev.pvalue is not None and lev.pvalue < alpha))
    out["primary"] = "welch" if use_welch else "student"
    if g == 2:
        a, b = ys[1], ys[0]  # 비교 수준 − 기준 수준
        out["kind"] = "t"
        out["welch"] = two_sample(a, b, False, alpha)
        out["student"] = two_sample(a, b, True, alpha)
        mw = ss.mannwhitneyu(a, b, alternative="two-sided", method="asymptotic", use_continuity=True)
        out["mann_whitney"] = {"U": num(mw.statistic), "p": num(mw.pvalue),
                               "r_rb": num(2 * mw.statistic / (len(a) * len(b)) - 1)}
        return out
    out["kind"] = "anova"
    classic = ss.f_oneway(*ys)
    allv = np.concatenate(ys)
    grand = allv.mean()
    ssb = sum(len(y) * (y.mean() - grand) ** 2 for y in ys)
    sst = float(((allv - grand) ** 2).sum())
    msw = (sst - ssb) / (N - g)
    out["anova"] = {"F": num(classic.statistic), "df1": g - 1, "df2": N - g, "p": num(classic.pvalue),
                    "eta2": num(ssb / sst) if sst > 0 else None,
                    "omega2": num((ssb - (g - 1) * msw) / (sst + msw)) if sst > 0 else None}
    w = anova_oneway(ys, use_var="unequal", welch_correction=True)
    out["welch_anova"] = {"F": num(w.statistic), "df1": num(w.df_num), "df2": num(w.df_denom), "p": num(w.pvalue)}
    kw = ss.kruskal(*ys)
    out["kruskal"] = {"H": num(kw.statistic), "df": g - 1, "p": num(kw.pvalue)}
    pairs = []
    for i, j in combinations(range(g), 2):
        a, b = ys[j], ys[i]
        if use_welch:
            r = two_sample(a, b, False, alpha)
        else:  # R pairwise.t.test(pool.sd=TRUE): 모든 집단의 합동 SD, df = N − g
            r = two_sample(a, b, True, alpha)
            se = math.sqrt(msw * (1 / len(a) + 1 / len(b)))
            t = r["diff"] / se
            tc = float(ss.t.ppf(1 - alpha / 2, N - g))
            r.update(t=num(t), df=float(N - g), p=num(2 * ss.t.sf(abs(t), N - g)), se_diff=num(se),
                     ci=[num(r["diff"] - tc * se), num(r["diff"] + tc * se)])
        pairs.append({"a": levels[j], "b": levels[i], **r})
    adj = multipletests([p["p"] for p in pairs], method="holm")[1]
    for p, q in zip(pairs, adj):
        p["p_holm"] = num(q)
    out["pairwise"] = pairs
    return out


def analyze(df: pd.DataFrame, spec: dict) -> dict:
    """spec = {outcome, continuous: [..], categorical: [{name, reference, levels?}], group, test, alpha}
    목록별 삭제 후 같은 표본으로 회귀와 집단 비교를 한다."""
    outcome = spec["outcome"]
    cont = list(spec.get("continuous") or [])
    cats = list(spec.get("categorical") or [])
    group = spec.get("group")
    alpha = float(spec.get("alpha", ALPHA))
    cols = [outcome] + cont + [c["name"] for c in cats] + ([group] if group and group not in [c["name"] for c in cats] else [])
    d, dropped = complete_cases(df, cols)
    for c in [outcome] + cont:
        d[c] = d[c].astype(float)
    cat_levels = [(c["name"], level_order(d[c["name"]], c.get("reference"), c.get("levels"))) for c in cats]
    res = {"n_total": int(len(df)), "n_used": int(len(d)), "dropped_index": dropped, "used_index": list(d.index),
           "levels": {n: lv for n, lv in cat_levels}}
    res["regression"] = ols(d, outcome, cont, cat_levels, alpha) if (cont or cats) else None
    if group:
        gc = next((c for c in cats if c["name"] == group), {})
        glv = res["levels"].get(group) or level_order(d[group], gc.get("reference") or spec.get("group_reference"),
                                                    gc.get("levels") or spec.get("group_levels"))
        res["groups"] = group_compare(d, outcome, group, glv, spec.get("test", "welch"), alpha)
    else:
        res["groups"] = None
    return res
