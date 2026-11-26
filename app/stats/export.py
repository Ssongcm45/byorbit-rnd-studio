"""재현 패키지(Python·R·Stata)와 논문용 묶음 ZIP.

- data.csv: UTF-8(BOM — 엑셀에서 한글이 깨지지 않게), ASCII 열 이름, 결측은 빈칸. 숫자는 왕복 손실 없는 표기(repr).
- codebook.csv: 변수 이름·한국어/영어 이름·단위·형식·수준·역할.
- analysis.py: app/stats/core.py 소스를 그대로 넣어 앱과 **같은 숫자**를 낸다(시험에서 실제로 실행해 확인).
- analysis.R / analysis.do: 표준 명령만 쓴 보수적인 스크립트. 이 PC에는 R·Stata가 없어 **실행해 보지 않았다**(README에 밝힘).
"""
from __future__ import annotations

import csv
import io
import json
import pathlib
import zipfile
from datetime import datetime

from . import fmt as F, report as R

CORE_PATH = pathlib.Path(__file__).with_name("core.py")


def _json_default(o):
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    return str(o)


def data_csv(r) -> bytes:
    df = r.ds.df
    return ("﻿" + df.to_csv(index=False, lineterminator="\n")).encode("utf-8")


def roles(r) -> dict[str, str]:
    sp = r.spec
    out = {sp["outcome"]: "outcome"}
    for c in sp["continuous"]:
        out[c] = "continuous predictor"
    for c in sp["categorical"]:
        out[c["name"]] = f"categorical predictor (reference = {c['reference']})"
    if sp.get("group"):
        out[sp["group"]] = out.get(sp["group"], "") + ("; " if sp["group"] in out else "") + "group comparison"
    out.setdefault(r.ds.id_col, "id")
    return out


def codebook_csv(r) -> bytes:
    rl = roles(r)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["name", "label_ko", "label_en", "unit", "type", "levels", "role", "source", "missing_n"])
    for v in r.ds.codebook:
        lv = " | ".join(f"{x['value']}={x['label_ko']}/{x['label_en']}" for x in v.get("levels") or [])
        w.writerow([v["name"], v["label_ko"], v["label_en"], v.get("unit", ""), v["type"], lv, rl.get(v["name"], "unused"),
                    v.get("source", ""), len(r.ds.missing.get(v["name"], {}))])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _core_spec(r) -> dict:
    return json.loads(json.dumps(r.spec["core_spec"], default=_json_default))


def extra_columns(r) -> list[dict]:
    """교호작용·2차항 열 — 앱 설계 행렬의 열 이름(col)과 R·Stata에서 만들 변수 이름(name), 곱할 조각(parts).
    조각: ("c", 연속 변수) = (x − 표본 평균), ("d", 범주 변수, 수준, 수준 번호(1 = 기준)) = 그 수준이면 1."""
    sp = _core_spec(r)
    lv = r.core["levels"]
    out, n = [], 0
    for c in sp.get("quadratic") or []:
        out.append({"col": f"{c}^2", "name": f"sq_{c}"[:32], "parts": [("c", c), ("c", c)]})

    def parts(v):
        if v in lv:
            return [(f"{v}[{x}]", ("d", v, x, i + 1)) for i, x in enumerate(lv[v]) if i > 0]
        return [(v, ("c", v))]
    for a, b in sp.get("interactions") or []:
        for na, pa in parts(a):
            for nb, pb in parts(b):
                n += 1
                out.append({"col": f"{na}:{nb}", "name": f"ix{n}_{a}_{b}"[:32], "parts": [pa, pb]})
    return out


def _centered(r) -> list[str]:
    seen = []
    for e in extra_columns(r):
        for p in e["parts"]:
            if p[0] == "c" and p[1] not in seen:
                seen.append(p[1])
    return seen


# ---------------------------------------------------------------- Python

def analysis_py(r) -> str:
    core_src = CORE_PATH.read_text(encoding="utf-8").replace("from __future__ import annotations\n", "")
    spec = _core_spec(r)
    cats = [c["name"] for c in spec["categorical"]] + ([spec["group"]] if spec.get("group") else [])
    v = r.out["software"]
    return f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R&D Studio V0.5 — 통계 분석 재현 스크립트 (Python)
만든 때: {datetime.now():%Y-%m-%d %H:%M} · 데이터: {r.ds.title_ko}{' (예시·가짜 데이터)' if r.ds.is_demo else ''}

실행:   python analysis.py            (같은 폴더의 data.csv를 읽어 요약을 출력하고 results.json을 씁니다)
필요:   pip install numpy pandas scipy statsmodels
앱에서 쓴 버전: Python {v['python']}, numpy {v['numpy']}, pandas {v['pandas']}, scipy {v['scipy']}, statsmodels {v['statsmodels']}

아래 '계산 핵심'은 앱의 app/stats/core.py와 글자 하나 다르지 않은 코드라, 같은 버전이면 앱과 같은 숫자가 나옵니다.
"""
from __future__ import annotations

SPEC = {json.dumps(spec, ensure_ascii=False, indent=4)}
CATEGORICAL = {json.dumps(sorted(set(cats)))}
ID_COLS = {json.dumps([r.ds.id_col])}

# =============================== 계산 핵심 (app/stats/core.py) ===============================
{core_src}
# =============================== 실행 ===============================


def _fmt_p(p):
    return "< .001" if p < 0.001 else f"{{p:.3f}}"


def main():
    import json as _json
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    df = pd.read_csv(os.path.join(here, "data.csv"), encoding="utf-8-sig",
                     dtype={{c: str for c in CATEGORICAL + ID_COLS}}, keep_default_na=True)
    res = analyze(df, SPEC)
    print(f"n total = {{res['n_total']}}, n used = {{res['n_used']}} (listwise deletion: {{len(res['dropped_index'])}} rows)")
    reg = res["regression"]
    if reg:
        f = reg["fit"]
        print("\\n[OLS] " + SPEC["outcome"] + " ~ " + " + ".join(SPEC["continuous"] + [c["name"] for c in SPEC["categorical"]]
                                                          + [q + "^2" for q in SPEC.get("quadratic") or []]
                                                          + [":".join(p) for p in SPEC.get("interactions") or []]))
        print(f"{{'term':<24}}{{'B':>10}}{{'SE':>10}}{{'t':>8}}{{'p':>8}}  95% CI            beta   HC3 SE")
        for c in reg["coef"]:
            beta = "" if c["beta"] is None else f"{{c['beta']:.3f}}"
            print(f"{{c['term']:<24}}{{c['B']:>10.4f}}{{c['SE']:>10.4f}}{{c['t']:>8.2f}}{{_fmt_p(c['p']):>8}}  "
                  f"[{{c['ci'][0]:.4f}}, {{c['ci'][1]:.4f}}]  {{beta:>6}}  {{c['robust']['SE']:.4f}}")
        print(f"R2 = {{f['r2']:.4f}}, adj R2 = {{f['adj_r2']:.4f}}, F({{f['df_model']:.0f}}, {{f['df_resid']:.0f}}) = {{f['F']:.3f}}, "
              f"p = {{_fmt_p(f['F_p'])}}, RMSE = {{f['rmse']:.4f}}")
        if reg["shapiro"]:
            print(f"Shapiro-Wilk (residuals): W = {{reg['shapiro']['W']:.4f}}, p = {{_fmt_p(reg['shapiro']['p'])}}")
        print(f"Breusch-Pagan (Koenker): LM = {{reg['bp']['LM']:.4f}}, df = {{reg['bp']['df']}}, p = {{_fmt_p(reg['bp']['p'])}}")
        print("VIF/GVIF:", {{k: round(v["vif_equiv"], 3) for k, v in reg["gvif"].items()}})
        cut = 4 / f["n"]
        ids = df.loc[res["used_index"], ID_COLS[0]].tolist() if ID_COLS[0] in df else res["used_index"]
        print("Cook's D > 4/n:", [ids[i] for i, d in enumerate(reg["cooks"]) if d > cut])
    g = res["groups"]
    if g:
        print("\\n[Groups] " + SPEC["group"] + ": " + ", ".join(f"{{d['level']}} n={{d['n']}} M={{d['mean']:.3f}} SD={{d['sd']:.3f}}" for d in g["desc"]))
        lv = g["levene"]
        print(f"Levene (median): F({{lv['df1']}}, {{lv['df2']}}) = {{lv['F']:.3f}}, p = {{_fmt_p(lv['p'])}}")
        if g["kind"] == "t":
            for k in ("welch", "student"):
                t = g[k]
                print(f"{{k}} t({{t['df']:.2f}}) = {{t['t']:.3f}}, p = {{_fmt_p(t['p'])}}, diff = {{t['diff']:.4f}} "
                      f"[{{t['ci'][0]:.4f}}, {{t['ci'][1]:.4f}}], Hedges g = {{t['hedges_g']:.3f}}")
            mw = g["mann_whitney"]
            print(f"Mann-Whitney U = {{mw['U']:.1f}}, p = {{_fmt_p(mw['p'])}}")
        else:
            a, w = g["anova"], g["welch_anova"]
            print(f"ANOVA F({{a['df1']}}, {{a['df2']}}) = {{a['F']:.3f}}, p = {{_fmt_p(a['p'])}}; Welch F({{w['df1']:.0f}}, {{w['df2']:.2f}}) = {{w['F']:.3f}}, p = {{_fmt_p(w['p'])}}")
            for p in g["pairwise"]:
                print(f"  {{p['a']}} - {{p['b']}}: diff = {{p['diff']:.4f}}, t({{p['df']:.2f}}) = {{p['t']:.3f}}, p = {{_fmt_p(p['p'])}}, p_holm = {{_fmt_p(p['p_holm'])}}")
    out = {{k: v for k, v in res.items()}}
    with open(os.path.join(here, "results.json"), "w", encoding="utf-8") as fh:
        _json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    print("\\nresults.json written.")


if __name__ == "__main__":
    main()
'''


# ---------------------------------------------------------------- R

def _rq(s) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def analysis_r(r) -> str:
    sp = _core_spec(r)
    y, cont, cats, g = sp["outcome"], sp["continuous"], sp["categorical"], sp.get("group")
    lv = r.core["levels"]
    glv = r.out["groups"]["levels"] if r.out["groups"] else []
    vars_ = [y] + cont + [c["name"] for c in cats] + ([g] if g and g not in [c["name"] for c in cats] else [])
    extras = extra_columns(r)
    rhs = " + ".join(cont + [c["name"] for c in cats] + [e["name"] for e in extras]) or "1"
    test = sp.get("test", "welch")
    idc = r.ds.id_col
    L = []
    A = L.append

    def r_part(p, z="z"):
        return f"({z}${p[1]} - m_{p[1]})" if p[0] == "c" else f"({z}${p[1]} == {_rq(p[2])})"
    A(f"# R&D Studio V0.5 — 통계 분석 재현 스크립트 (R)  {datetime.now():%Y-%m-%d}")
    A("# !! 이 스크립트는 R이 설치되지 않은 PC에서 만들어져 실행해 보지 않았습니다. 처음 실행할 때 결과를 app_results.json의 값과 비교하세요.")
    A("# 실행: R 또는 RStudio에서 작업 폴더를 이 파일이 있는 폴더로 정한 뒤  source(\"analysis.R\", echo = TRUE)")
    A("# 선택 패키지(있으면 씀): install.packages(c(\"car\", \"lmtest\", \"ggplot2\")) — 없으면 같은 값을 기본 R로 직접 계산합니다.")
    A("")
    A('d0 <- read.csv("data.csv", fileEncoding = "UTF-8-BOM", stringsAsFactors = FALSE, na.strings = c("", "NA"))')
    A(f"vars <- c({', '.join(_rq(v) for v in vars_)})")
    A("d <- d0[complete.cases(d0[, vars]), ]   # 목록별 삭제(앱과 같은 표본)")
    A('cat("n total =", nrow(d0), " n used =", nrow(d), "\\n")')
    for c in cats:
        A(f"d${c['name']} <- factor(d${c['name']}, levels = c({', '.join(_rq(x) for x in lv[c['name']])}))   # 첫 수준 = 기준")
    if g and g not in [c["name"] for c in cats]:
        A(f"d${g} <- factor(d${g}, levels = c({', '.join(_rq(x) for x in glv)}))")
    if extras:
        A("# 교호작용·2차항: 앱과 같게 연속 변수를 분석 표본 평균으로 중심화한 곱(주효과 열은 그대로)")
        for c in _centered(r):
            A(f"m_{c} <- mean(d${c})")
        A("add_terms <- function(z) {")
        for e in extras:
            A(f"  z${e['name']} <- {' * '.join(r_part(p) for p in e['parts'])}   # {e['col']}")
        A("  z")
        A("}")
        A("d <- add_terms(d)")
    if cont or cats:
        A("")
        A("## 1. 회귀 (OLS)")
        A(f"m <- lm({y} ~ {rhs}, data = d)")
        A("print(summary(m))")
        A("print(confint(m))")
        if cont:
            A(f"sdy <- sd(d${y})")
            A(f"beta <- c({', '.join(f'{c} = unname(coef(m)[{_rq(c)}]) * sd(d${c}) / sdy' for c in cont)})")
            A('cat("standardized beta (continuous only):\\n"); print(round(beta, 4))')
        A("# HC3 강건 표준오차 (sandwich 패키지 없이 직접 계산; sandwich::vcovHC(m, type = \"HC3\")와 같음)")
        A("X <- model.matrix(m); e <- residuals(m); h <- hatvalues(m)")
        A("XtXi <- solve(crossprod(X))")
        A("V_hc3 <- XtXi %*% crossprod(X * (e / (1 - h))) %*% XtXi")
        A("se_hc3 <- sqrt(diag(V_hc3))")
        A("t_hc3 <- coef(m) / se_hc3")
        A("p_hc3 <- 2 * pt(abs(t_hc3), df = df.residual(m), lower.tail = FALSE)")
        A('print(cbind(B = coef(m), SE_HC3 = se_hc3, t = t_hc3, p = p_hc3))')
        A("")
        A("## 2. 가정 점검")
        A("print(shapiro.test(residuals(m)))   # 잔차 정규성")
        A("# 등분산: Breusch–Pagan (Koenker 학생화 판 = lmtest::bptest 기본값 = 앱)")
        A('if (requireNamespace("lmtest", quietly = TRUE)) print(lmtest::bptest(m)) else {')
        A("  aux <- lm(residuals(m)^2 ~ X[, -1, drop = FALSE]); LM <- nrow(d) * summary(aux)$r.squared")
        A('  cat("BP (Koenker) LM =", LM, " df =", ncol(X) - 1, " p =", pchisq(LM, ncol(X) - 1, lower.tail = FALSE), "\\n") }')
        A("# 다중공선성: car::vif(3수준 이상 범주는 GVIF) — 없으면 상관행렬로 직접(1자유도 항만 VIF와 같음)")
        A('if (ncol(X) > 2) { if (requireNamespace("car", quietly = TRUE)) print(car::vif(m)) else print(diag(solve(cor(X[, -1])))) }')
        A("cd <- cooks.distance(m)")
        A(f'cat("Cook\'s D > 4/n:", as.character(d${idc}[cd > 4 / nrow(d)]), "\\n")' if idc in r.ds.df.columns else 'print(which(cd > 4 / nrow(d)))')
        for c in cont:
            if c in (sp.get("quadratic") or []):
                continue  # 2차항이 이미 모형에 있음
            A(f"m_q <- update(m, . ~ . + I(({c} - mean({c}))^2)); print(tail(summary(m_q)$coefficients, 1))   # 선형성: 2차항")
    if g:
        A("")
        A("## 3. 집단 비교")
        A(f"print(aggregate({y} ~ {g}, data = d, FUN = function(x) c(n = length(x), mean = mean(x), sd = sd(x))))")
        A(f"print(tapply(d${y}, d${g}, function(x) if (length(x) >= 3) shapiro.test(x)$p.value else NA))   # 집단별 Shapiro–Wilk p")
        A("# Levene(중앙값 기준 = car::leveneTest 기본값 = 앱)")
        A(f'if (requireNamespace("car", quietly = TRUE)) print(car::leveneTest({y} ~ {g}, data = d)) else '
          f'print(anova(lm(abs(d${y} - ave(d${y}, d${g}, FUN = median)) ~ d${g})))')
        if len(glv) == 2:
            ve = "TRUE" if test == "student" else "FALSE"
            if test == "auto":
                A(f"lev_p <- anova(lm(abs(d${y} - ave(d${y}, d${g}, FUN = median)) ~ d${g}))[1, 5]")
                ve = f"lev_p >= {sp.get('alpha', 0.05)}"
            A(f"tt <- t.test({y} ~ {g}, data = d, var.equal = {ve})   # 주의: R은 '기준 − 비교' 순서라 t·차이의 부호가 앱과 반대")
            A("print(tt)")
            A(f"a <- d${y}[d${g} == {_rq(glv[1])}]; b <- d${y}[d${g} == {_rq(glv[0])}]")
            A("sp <- sqrt(((length(a) - 1) * var(a) + (length(b) - 1) * var(b)) / (length(a) + length(b) - 2))")
            A("dd <- (mean(a) - mean(b)) / sp; g_h <- dd * (1 - 3 / (4 * (length(a) + length(b)) - 9))")
            A('cat("Cohen d =", dd, " Hedges g =", g_h, "\\n")')
            A(f"print(wilcox.test({y} ~ {g}, data = d, exact = FALSE, correct = TRUE))   # W = 기준 집단의 U (앱 U = n1*n2 − W)")
        else:
            ve = "TRUE" if test == "student" else "FALSE"
            A(f"print(oneway.test({y} ~ {g}, data = d, var.equal = {ve}))   # FALSE = Welch ANOVA")
            A(f"print(summary(aov({y} ~ {g}, data = d)))")
            A(f"print(pairwise.t.test(d${y}, d${g}, p.adjust.method = \"holm\", pool.sd = {'TRUE' if ve == 'TRUE' else 'FALSE'}))   # 쌍별 t + Holm")
            A(f"print(kruskal.test({y} ~ {g}, data = d))")
    # 그림
    xv = R._xvar(r.spec)
    A("")
    A("## 4. 그림 1 (ggplot2가 있으면 두 패널을 따로 저장)")
    A('if (requireNamespace("ggplot2", quietly = TRUE)) {')
    A("  library(ggplot2)")
    A('  pal <- c("#0072B2", "#D55E00", "#009E73", "#CC79A7")')
    if xv and (cont or cats):
        nd = [f"{xv} = rep(seq(min(d${xv}), max(d${xv}), length.out = 50), times = {max(len(glv), 1)})"]
        for c in cont:
            if c != xv:
                nd.append(f"{c} = mean(d${c})")
        for c in cats:
            if c["name"] == g:
                nd.append(f"{g} = factor(rep(levels(d${g}), each = 50), levels = levels(d${g}))")
            else:
                nd.append(f"{c['name']} = factor(levels(d${c['name']})[1], levels = levels(d${c['name']}))")
        A(f"  nd <- data.frame({', '.join(nd)})")
        if extras:
            A("  nd <- add_terms(nd)")
        A("  nd$fit <- predict(m, newdata = nd)")
        col = f", colour = {g}, shape = {g}" if g else ""
        A(f"  pa <- ggplot(d, aes(x = {xv}, y = {y}{col})) + geom_point(position = position_dodge(width = 1.5), size = 1.6) +")
        A(f"    geom_line(data = nd, aes(y = fit{', colour = ' + g if g and g in [c['name'] for c in cats] else ''})) + scale_colour_manual(values = pal) +")
        A(f'    labs(x = {_rq(R._u(r.labels.var(xv, "en"), "en"))}, y = {_rq(R._u(r.labels.var(y, "en"), "en"))}) + theme_classic(base_size = 8)')
        A('  ggsave("Figure1a_R.png", pa, width = 85, height = 70, units = "mm", dpi = 300)')
    if g:
        A("  ci_fun <- function(x) { m <- mean(x); h <- qt(0.975, length(x) - 1) * sd(x) / sqrt(length(x)); data.frame(y = m, ymin = m - h, ymax = m + h) }")
        A(f"  pb <- ggplot(d, aes(x = {g}, y = {y}, colour = {g})) + geom_boxplot(outlier.shape = NA, width = 0.5) +")
        A("    geom_jitter(width = 0.1, size = 1.2, alpha = 0.7) + stat_summary(fun.data = ci_fun, colour = \"black\", position = position_nudge(x = 0.33)) +")
        A(f'    scale_colour_manual(values = pal, guide = "none") + labs(x = {_rq(r.labels.var(g, "en", unit=False))}, y = {_rq(R._u(r.labels.var(y, "en"), "en"))}) + theme_classic(base_size = 8)')
        A('  ggsave("Figure1b_R.png", pb, width = 85, height = 70, units = "mm", dpi = 300)')
    A('} else cat("ggplot2가 없어 그림을 건너뜁니다: install.packages(\\"ggplot2\\")\\n")')
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- Stata

def analysis_do(r) -> str:
    sp = _core_spec(r)
    y, cont, cats, g = sp["outcome"], sp["continuous"], sp["categorical"], sp.get("group")
    lv = dict(r.core["levels"])
    glv = r.out["groups"]["levels"] if r.out["groups"] else []
    if g and g not in lv:
        lv[g] = glv
    idc = r.ds.id_col
    first_col = list(r.ds.df.columns)[0]
    L = []
    A = L.append
    A(f"* R&D Studio V0.5 — 통계 분석 재현 (Stata 15 이상)  {datetime.now():%Y-%m-%d}")
    A("* !! 이 do 파일은 Stata가 설치되지 않은 PC에서 만들어져 실행해 보지 않았습니다. 처음 실행할 때 결과를 app_results.json의 값과 비교하세요.")
    A("* 실행: Stata에서 cd \"이 폴더\" 후  do analysis.do")
    A("version 15")
    A("clear all")
    A("set more off")
    A('import delimited using "data.csv", encoding("utf-8") varnames(1) case(preserve) clear')
    A("* BOM 때문에 첫 열 이름이 깨졌으면 바로잡는다")
    A("quietly ds")
    A("local first : word 1 of `r(varlist)'")
    A(f'if "`first\'" != "{first_col}" rename `first\' {first_col}')
    miss = " | ".join([f"missing({v})" for v in [y] + cont] + [f'{c} == ""' for c in lv])
    A(f"drop if {miss}   // 목록별 삭제(앱과 같은 표본)")
    fv = {}
    for name, levels in lv.items():
        lab = f"{name}_lbl"
        A(f"label define {lab} " + " ".join(f'{i + 1} "{x}"' for i, x in enumerate(levels)))
        A(f"encode {name}, generate({name}_f) label({lab}) noextend   // 1 = 기준 수준")
        fv[name] = f"{name}_f"
    extras = extra_columns(r)
    if extras:
        A("* 교호작용·2차항: 앱과 같게 연속 변수를 분석 표본 평균으로 중심화한 곱(주효과 변수는 그대로)")
        for c in _centered(r):
            A(f"quietly summarize {c}")
            A(f"scalar c_{c[:28]} = r(mean)")

        def s_part(p):
            return f"({p[1]} - c_{p[1][:28]})" if p[0] == "c" else f"({fv[p[1]]} == {p[3]})"
        for e in extras:
            A(f"generate double {e['name']} = {' * '.join(s_part(p) for p in e['parts'])}   // {e['col']}")
    rhs = " ".join(cont + [f"ib1.{fv[c['name']]}" for c in cats] + [e["name"] for e in extras])
    if cont or cats:
        A("")
        A("* 1. 회귀 (OLS)")
        A(f"regress {y} {rhs}")
        A("estat hettest, rhs iid    // Koenker(학생화) Breusch–Pagan = 앱·R lmtest::bptest 기본과 같은 통계량")
        A("estat vif                 // 3수준 이상 범주는 가변수마다 VIF(앱·R은 항별 GVIF)")
        A(f"regress {y} {rhs}, beta   // 표준화 β (Stata는 가변수에도 보임 — 앱은 연속 변수만)")
        A(f"regress {y} {rhs}, vce(hc3)   // HC3 강건 표준오차")
        A(f"quietly regress {y} {rhs}")
        A("predict double r, residuals")
        A("predict double cooksd, cooksd")
        A("swilk r                   // Stata swilk는 근사식이 달라 p가 R·Python과 조금 다를 수 있음")
        A(f"list {idc} cooksd if cooksd > 4/e(N) & !missing(cooksd)" if idc in r.ds.df.columns else "list cooksd if cooksd > 4/e(N) & !missing(cooksd)")
        for c in cont:
            if c in (sp.get("quadratic") or []):
                continue  # 2차항이 이미 모형에 있음
            A(f"quietly summarize {c}")
            A(f"generate double {c[:26]}_sq = ({c} - r(mean))^2")
            A(f"regress {y} {rhs} {c[:26]}_sq   // 선형성: 2차항의 p")
    if g:
        gf = fv[g]
        A("")
        A("* 2. 집단 비교")
        A(f"tabstat {y}, by({gf}) statistics(n mean sd)")
        A(f"robvar {y}, by({gf})      // W50 = 중앙값 기준 Levene(Brown–Forsythe) = 앱 값")
        A(f"bysort {gf}: swilk {y}")
        if len(glv) == 2:
            opt = "" if sp.get("test") == "student" else " unequal"
            A(f"ttest {y}, by({gf}){opt}   // unequal = Welch(Satterthwaite df). Stata 차이 = 기준 − 비교(부호가 앱과 반대)")
            A(f"esize twosample {y}, by({gf}) cohensd hedgesg")
            A(f"ranksum {y}, by({gf})")
        else:
            k = len(glv)
            npairs = k * (k - 1) // 2
            A(f"oneway {y} {gf}, tabulate   // 고전 일원분산분석(Stata에는 Welch ANOVA 기본 명령이 없음 — 필요하면 ssc install wanova)")
            A(f"kwallis {y}, by({gf})")
            A("* 쌍별 Welch t + Holm 보정")
            A(f"matrix P = J({npairs}, 3, .)")
            A("local k = 0")
            A(f"forvalues i = 1/{k - 1} {{")
            A(f"    forvalues j = `=`i'+1'/{k} {{")
            A("        local ++k")
            A(f"        quietly ttest {y} if inlist({gf}, `i', `j'), by({gf}){'' if sp.get('test') == 'student' else ' unequal'}")
            A("        matrix P[`k', 1] = `i'")
            A("        matrix P[`k', 2] = `j'")
            A("        matrix P[`k', 3] = r(p)")
            A("    }")
            A("}")
            A("mata:")
            A('P = st_matrix("P")')
            A("m = rows(P)")
            A("o = order(P[., 3], 1)")
            A("adj = J(m, 1, .)")
            A("run = 0")
            A("for (k = 1; k <= m; k++) {")
            A("    a = min(((m - k + 1) * P[o[k], 3], 1))")
            A("    run = max((run, a))")
            A("    adj[o[k]] = run")
            A("}")
            A('st_matrix("P", (P, adj))')
            A("end")
            A("matrix colnames P = level_a level_b p p_holm")
            A("matrix list P")
    xv = R._xvar(r.spec)
    A("")
    A("* 3. 그림 1")
    cols = ['"0 114 178"', '"213 94 0"', '"0 158 115"', '"204 121 167"']
    syms = ["O", "S", "T", "D"]
    if xv and (cont or cats):
        A(f"quietly regress {y} {rhs}")
        expr = "_b[_cons]" + "".join(f" + _b[{c}]*{c}" if c == xv else f" + _b[{c}]*r(mean_{i})" for i, c in enumerate(cont))
        for i, c in enumerate(cont):
            if c != xv:
                A(f"quietly summarize {c}")
                A(f"scalar m_{i} = r(mean)")
                expr = expr.replace(f"r(mean_{i})", f"m_{i}")
        if g and g in [c["name"] for c in cats]:
            gf = fv[g]
            expr += "".join(f" + _b[{j + 1}.{gf}]*({gf} == {j + 1})" for j in range(1, len(glv)))
        ci = {c: i for i, c in enumerate(cont)}
        for e in extras:  # 예측선: 가로축 변수는 그 값, 다른 연속 변수는 평균, 범주는 집단 변수만 그 수준(나머지는 기준 = 0)
            fac = []
            for p in e["parts"]:
                if p[0] == "c":
                    fac.append(f"({p[1] if p[1] == xv else 'm_' + str(ci[p[1]])} - c_{p[1][:28]})")
                elif p[1] == g:
                    fac.append(f"({fv[p[1]]} == {p[3]})")
                else:
                    fac = None
                    break
            if fac:
                expr += f" + _b[{e['name']}]*" + "*".join(fac)
        A(f"generate double yhat_mean = {expr}")
        if g:
            gf = fv[g]
            sc = " ".join(f'(scatter {y} {xv} if {gf} == {j + 1}, mcolor({cols[j % 4]}) msymbol({syms[j % 4]}) msize(small))' for j in range(len(glv)))
            ln = " ".join(f"(line yhat_mean {xv} if {gf} == {j + 1}, sort lcolor({cols[j % 4]}))" for j in range(len(glv)))
            leg = " ".join(f'{j + 1} "{r.labels.level(g, x, "en")}"' for j, x in enumerate(glv))
            A(f"twoway {sc} {ln}, legend(order({leg}) ring(0) pos(11) cols(1)) ytitle(\"{R._u(r.labels.var(y, 'en'), 'en')}\") "
              f"xtitle(\"{R._u(r.labels.var(xv, 'en'), 'en')}\") graphregion(color(white)) name(fa, replace)")
        else:
            A(f"twoway (scatter {y} {xv}) (line yhat_mean {xv}, sort), name(fa, replace)")
    if g:
        A(f"graph box {y}, over({fv[g]}) ytitle(\"{R._u(r.labels.var(y, 'en'), 'en')}\") graphregion(color(white)) name(fb, replace)")
    names = " ".join(x for x, ok in (("fa", bool(xv and (cont or cats))), ("fb", bool(g))) if ok)
    if names:
        A(f"graph combine {names}, cols(2) xsize(6.9) ysize(3) graphregion(color(white))")
        A('graph export "Figure1_Stata.png", width(2000) replace')
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- README·ZIP

def readme(r) -> str:
    v = r.out["software"]
    demo = "\n!! 예시 데이터는 가짜(모의)입니다 — 논문에 쓰지 마세요.\n" if r.ds.is_demo else ""
    return f"""R&D Studio V0.5 — 통계 분석 재현 패키지
만든 때: {datetime.now():%Y-%m-%d %H:%M}
데이터: {r.ds.title_ko}{demo}
분석 n = {r.core['n_used']} (전체 {r.core['n_total']}, 목록별 삭제 {len(r.core['dropped_index'])})

들어 있는 파일
  data.csv          분석 데이터(UTF-8 BOM, 결측 = 빈칸, 열 이름은 R·Stata용 ASCII)
  codebook.csv      변수 이름 · 한국어/영어 이름 · 단위 · 형식 · 수준 · 역할
  analysis.py       Python 재현(앱의 계산 코드와 같음) — 실행해 앱과 같은 숫자가 나오는 것을 확인함
  analysis.R        R 재현 — 이 PC에 R이 없어 실행해 보지 않음
  analysis.do       Stata 재현 — 이 PC에 Stata가 없어 실행해 보지 않음
  app_results.json  앱이 낸 숫자(비교용)

실행
  Python : pip install numpy pandas scipy statsmodels  →  python analysis.py
           (앱 버전: Python {v['python']}, numpy {v['numpy']}, pandas {v['pandas']}, scipy {v['scipy']}, statsmodels {v['statsmodels']})
  R      : RStudio에서 이 폴더를 작업 폴더로 → source("analysis.R", echo = TRUE)
           선택 패키지 car·lmtest·ggplot2가 있으면 쓰고, 없으면 같은 값을 기본 R로 계산합니다.
  Stata  : cd "이 폴더" → do analysis.do   (Stata 15 이상)

{_readme_terms(r)}알아 둘 차이
  - t검정의 부호: 앱·Python은 '비교 수준 − 기준', R t.test와 Stata ttest는 '기준 − 비교'로 부호가 반대입니다(p는 같음).
  - Levene: 앱·R car::leveneTest는 중앙값 기준(Brown–Forsythe) — Stata robvar의 W50과 같습니다.
  - Breusch–Pagan: 앱·R lmtest::bptest(기본)·Stata estat hettest, rhs iid 는 같은 Koenker 판입니다.
  - VIF: 3수준 이상 범주는 앱·R car::vif가 항별 GVIF, Stata estat vif는 가변수별 VIF를 냅니다.
  - Shapiro–Wilk: Stata swilk는 근사식이 달라 p가 조금 다를 수 있습니다.
  - Welch ANOVA: Stata에는 기본 명령이 없습니다(ssc install wanova). 쌍별 Welch t + Holm은 do 파일이 직접 계산합니다.
  - Mann–Whitney: 앱 U는 비교 수준의 U, R wilcox.test의 W는 기준 집단의 U(= n1·n2 − U). 둘 다 점근·연속성 보정.
"""


def _readme_terms(r) -> str:
    ex = extra_columns(r)
    if not ex:
        return ""
    lines = "\n".join(f"  {e['name']:<28} = 앱의 '{e['col']}'" for e in ex)
    return ("교호작용·2차항\n  연속 변수를 분석 표본 평균으로 중심화한 곱으로 만든 열입니다(주효과 열은 그대로). R·Stata 스크립트가 직접 만듭니다.\n"
            + lines + "\n\n")


def reproduce_files(r) -> dict[str, bytes]:
    app_res = {"spec": r.spec["core_spec"], "n_total": r.core["n_total"], "n_used": r.core["n_used"],
               "regression": r.core["regression"] and {k: r.core["regression"][k] for k in ("coef", "fit", "term_tests", "shapiro", "bp", "gvif", "linearity")},
               "groups": r.core["groups"], "primary_se": r.out["primary_se"], "software": r.out["software"]}
    return {"data.csv": data_csv(r), "codebook.csv": codebook_csv(r), "analysis.py": analysis_py(r).encode("utf-8"),
            "analysis.R": analysis_r(r).encode("utf-8"), "analysis.do": analysis_do(r).encode("utf-8"),
            "README.txt": readme(r).encode("utf-8"),
            "app_results.json": json.dumps(app_res, ensure_ascii=False, indent=1, default=_json_default).encode("utf-8")}


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def reproduce_zip(r) -> bytes:
    return _zip(reproduce_files(r))


def bundle_zip(r, lang: str = "ko", width: str = "double", zero: str | None = None) -> bytes:
    other = "en" if lang == "ko" else "ko"
    files = {
        "Table1.docx": R.table1_docx(r, lang, zero), "Table1.html": R.table1_html(r, lang, zero, standalone=True).encode("utf-8"),
        "Table1.csv": R.table1_csv(r, lang, zero).encode("utf-8"), "Table1.tex": R.table1_latex(r, lang, zero).encode("utf-8"),
        "Table1.md": R.table1_markdown(r, lang, zero).encode("utf-8"),
        "Figure1.png": R.figure1(r, lang, width, "png", zero), "Figure1.svg": R.figure1(r, lang, width, "svg", zero),
        "Figure1.pdf": R.figure1(r, lang, width, "pdf", zero),
        "caption.txt": (R.caption(r, lang, zero) + "\n\n" + R.caption(r, other, zero) + "\n").encode("utf-8"),
        "interpretation_ko.txt": (" ".join(R.interpretation(r, "ko", zero)) + "\n").encode("utf-8"),
        "interpretation_en.txt": (" ".join(R.interpretation(r, "en", zero)) + "\n").encode("utf-8"),
        "methods.txt": (r.out["methods"]["ko"] + "\n\n" + r.out["methods"]["en"] + "\n").encode("utf-8"),
        "assumptions.docx": R.assumptions_docx(r, lang), "assumptions.html": R.assumptions_html(r, lang).encode("utf-8"),
    }
    if r.core["regression"]:
        files["diagnostics.png"] = R.diagnostics(r, lang, "png")
    for k, v in reproduce_files(r).items():
        files["reproduce/" + k] = v
    return _zip(files)


def json_safe(obj):
    return json.loads(json.dumps(obj, default=_json_default))


__all__ = ["data_csv", "codebook_csv", "analysis_py", "analysis_r", "analysis_do", "readme", "reproduce_zip", "bundle_zip", "F"]
