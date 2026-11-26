"""논문용 결과물: 표 1(패널 A 회귀 · 패널 B 집단 비교), 그림 1, 그림 설명, 해석 세 문장, 가정 점검 보고서.

- 표: 한 모델(table1_model)을 HTML·CSV·LaTeX(booktabs)·Markdown·DOCX로 그린다 — 숫자는 모두 같은 곳에서 나온다.
- 그림: matplotlib 객체 API(pyplot 안 씀 — 서버 스레드에서 안전), 300 dpi PNG·SVG·PDF, 85 mm(1단)·175 mm(2단),
  Okabe–Ito 색(색각 이상에도 구분) + 수준마다 다른 표식, 한국어는 맑은 고딕, 영어는 Arial.
- 해석: 숫자로만 만드는 틀 문장(LLM 안 씀), 정확히 세 문장. 가정이 어긋나거나 n이 작으면 자동으로 단서를 붙인다.
"""
from __future__ import annotations

import html
import io
import math
import threading

import numpy as np

from . import fmt as F

PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]  # Okabe–Ito
MARKERS = ["o", "s", "^", "D", "v", "P"]
WIDTH_MM = {"single": 85, "double": 175}
_mpl_lock = threading.Lock()
_fonts_ready = False


# ---------------------------------------------------------------- 공통 도우미

def _u(s: str, lang: str) -> str:
    """영어 출력에서는 ℃ 대신 °C(Times·Arial에 ℃ 글리프가 없는 경우가 있음)."""
    return s.replace("℃", "°C") if lang == "en" else s


def _lead(r, lang, zero=None) -> bool:
    return F.zero_for(lang, zero if zero is not None else r.spec.get("zero"))


def _coef_view(r, row) -> dict:
    """주 결과 SE(OLS 또는 HC3)로 본 계수."""
    if r.out["primary_se"] == "HC3":
        return {"B": row["B"], "SE": row["robust"]["SE"], "t": row["robust"]["t"], "p": row["robust"]["p"],
                "ci": row["robust"]["ci"], "beta": row["beta"], "term": row["term"]}
    return row


def _group_label(r, lang):
    return r.labels.var(r.spec["group"], lang, unit=False) if r.spec.get("group") else ""


def _pct_unit(unit: str, lang: str) -> str:
    if unit == "%":
        return "%p" if lang == "ko" else " percentage points"
    return (" " + unit) if unit else ""


# ---------------------------------------------------------------- 표 1 모델

def table1_model(r, lang: str = "ko", zero: str | None = None, minus: str = F.MINUS) -> dict:
    L, reg, grp, sp = r.labels, r.core["regression"], r.core["groups"], r.spec
    lead = _lead(r, lang, zero)
    ko = lang == "ko"
    y = L.var(sp["outcome"], lang, unit=False)
    hc3 = r.out["primary_se"] == "HC3"
    panels = []
    preds = [L.var(c, lang, unit=False) for c in sp["continuous"]] + [L.var(c["name"], lang, unit=False) for c in sp["categorical"]]
    if ko:
        title = f"{F.w('·'.join(preds), '이')} {y}에 미치는 영향" if preds else f"{_group_label(r, lang)}에 따른 {y} 비교"
        if reg and grp:
            title += f": (A) 다중 선형 회귀, (B) {_group_label(r, lang)}별 비교"
    else:
        names = [p.lower() for p in preds]
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + (", and " if len(names) > 2 else " and ") + names[-1] if names else ""
        title = f"Effects of {joined} on {y.lower()}" if names else f"Comparison of {y.lower()} by {_group_label(r, lang).lower()}"
        if reg and grp:
            title += f": (A) multiple linear regression and (B) comparison by {_group_label(r, lang).lower()}"
    if reg:
        rows = []
        cats = {c["name"]: c for c in sp["categorical"]}
        multi = {t["term"]: t for t in reg["term_tests"]}
        for row in reg["coef"]:
            v = _coef_view(r, row)
            d = F.dec_for(v["SE"])
            term = row["term"]
            if "[" in term:
                var = term.split("[", 1)[0]
                first = term == reg["terms"][var][0]
                if first:
                    ref = L.level(var, cats[var]["reference"], lang)
                    rows.append({"kind": "section", "cells": [f"{L.var(var, lang, unit=False)} ({'기준' if ko else 'ref.'}: {ref})", "", "", "", "", "", ""]})
            cells = [_u(L.term(term, lang), lang), F.n(v["B"], d, minus), F.n(v["SE"], d, minus),
                     F.bounded(v["beta"], 2, lead, minus) if v.get("beta") is not None else "—",
                     F.n(v["t"], 2, minus), F.p_val(v["p"], lead), F.ci(v["ci"][0], v["ci"][1], d, minus)]
            rows.append({"kind": "indent" if "[" in term else "row", "cells": cells})
        fit = reg["fit"]
        unit_y = L.unit(sp["outcome"])
        foot = [f"R² = {F.bounded(fit['r2'], 2, lead, minus)}", f"{'수정 R²' if ko else 'adjusted R²'} = {F.bounded(fit['adj_r2'], 2, lead, minus)}",
                f"F({F.df_str(fit['df_model'])}, {F.df_str(fit['df_resid'])}) = {F.n(fit['F'], 2, minus)}", F.p_txt(fit["F_p"], lead),
                f"n = {fit['n']}", f"RMSE = {F.n(fit['rmse'], 2, minus)}{(' ' + unit_y) if unit_y else ''}"]
        foot_txt = ", ".join(foot) + "."
        for name, t in multi.items():
            if name in cats and len(reg["terms"][name]) > 1:
                tt = t["robust"] if hc3 else t
                foot_txt += (f" {L.var(name, lang, unit=False)} {'전체' if ko else 'overall'}: F({F.df_str(t['df1'])}, {F.df_str(t['df2'])}) = "
                             f"{F.n(tt['F'], 2, minus)}, {F.p_txt(tt['p'], lead)}.")
        model = ("모형: OLS" if ko else "Model: OLS") + ("; SE = HC3 " + ("강건 표준오차(이분산)" if ko else "heteroscedasticity-consistent") if hc3 else
                                                         ("; SE = 일반(OLS) 표준오차" if ko else "; conventional SEs"))
        panels.append({"key": "A", "title": ("A. 다중 선형 회귀" if ko else "Panel A. Multiple linear regression") + f" — {y}{(' (' + unit_y + ')') if unit_y else ''}",
                       "header": ["변수" if ko else "Predictor", "B", "SE", "β", "t", "p", "95% CI"],
                       "rows": rows, "foot": foot_txt + " " + model + "."})
    if grp:
        g = sp["group"]
        unit_y = L.unit(sp["outcome"])
        two = grp["kind"] == "t"
        prim = grp[grp["primary"]] if two else None
        dmean = 2
        rows = []
        ref = grp["levels"][0]
        pairs = {} if two else {(p["a"], p["b"]): p for p in grp["pairwise"]}
        for x in grp["desc"]:
            lab = L.level(g, x["level"], lang)
            ms = f"{F.n(x['mean'], dmean, minus)} ± {F.n(x['sd'], dmean, minus)}"
            if x["level"] == ref:
                rows.append({"kind": "row", "cells": [f"{lab} ({'기준' if ko else 'ref.'})", str(x["n"]), ms, "—", "—", "—", "—"]})
                continue
            res = prim if two else pairs[(x["level"], ref)]
            pv = res["p"] if two else res["p_holm"]
            dd = F.dec_for(res["se_diff"])
            rows.append({"kind": "row", "cells": [lab, str(x["n"]), ms, f"{F.n(res['t'], 2, minus)} ({F.df_str(res['df'])})", F.p_val(pv, lead),
                                                  F.n(res["hedges_g"], 2, minus), f"{F.n(res['diff'], dd, minus)} {F.ci(res['ci'][0], res['ci'][1], dd, minus)}"]})
        if not two:
            for p in grp["pairwise"]:
                if p["b"] == ref:
                    continue
                dd = F.dec_for(p["se_diff"])
                rows.append({"kind": "indent", "cells": [f"{L.level(g, p['a'], lang)} − {L.level(g, p['b'], lang)}", "", "",
                                                         f"{F.n(p['t'], 2, minus)} ({F.df_str(p['df'])})", F.p_val(p["p_holm"], lead),
                                                         F.n(p["hedges_g"], 2, minus), f"{F.n(p['diff'], dd, minus)} {F.ci(p['ci'][0], p['ci'][1], dd, minus)}"]})
        lv = grp["levene"]
        lev_txt = f"Levene ({'중앙값 기준' if ko else 'median'}) F({lv['df1']}, {lv['df2']}) = {F.n(lv['F'], 2, minus)}, {F.p_txt(lv['p'], lead)}"
        from .analysis import test_name
        if two:
            mw = grp["mann_whitney"]
            foot = (f"{test_name(grp, lang)}{'(양측)' if ko else ' (two-sided)'}; Δ = {'비교 수준 − 기준' if ko else 'level − reference'}; "
                    f"{lev_txt}; Mann–Whitney U = {F.n(mw['U'], 1, minus)}, {F.p_txt(mw['p'], lead)}.")
        else:
            a = grp["welch_anova"] if grp["primary"] == "welch" else grp["anova"]
            kw = grp["kruskal"]
            foot = (f"{test_name(grp, lang)}: F({F.df_str(a['df1'])}, {F.df_str(a['df2'])}) = {F.n(a['F'], 2, minus)}, {F.p_txt(a['p'], lead)}; "
                    + ("쌍별 " + ("Welch t-검정" if grp["primary"] == "welch" else "t-검정(합동 SD)") + ", p는 Holm 보정값; " if ko else
                       "pairwise " + ("Welch t-tests" if grp["primary"] == "welch" else "t-tests (pooled SD)") + ", Holm-adjusted p; ")
                    + f"{lev_txt}; Kruskal–Wallis H({kw['df']}) = {F.n(kw['H'], 2, minus)}, {F.p_txt(kw['p'], lead)}.")
        panels.append({"key": "B", "title": (f"B. {_group_label(r, lang)}별 {y}" if ko else f"Panel B. {y} by {_group_label(r, lang).lower()}")
                       + (f" ({unit_y})" if unit_y else ""),
                       "header": [_group_label(r, lang), "n", "M ± SD", "t (df)", "p" + ("" if two else " (Holm)"), "Hedges' g", "Δ [95% CI]"],
                       "rows": rows, "foot": foot})
    if ko:
        note = ("B = 비표준화 계수; SE = 표준오차; β = 표준화 계수(연속 변수만); CI = 신뢰구간; M ± SD = 평균 ± 표준편차; Δ = 평균 차이(행 − 기준). "
                f"양측 검정, α = {F.bounded(sp['alpha'], 2, True)}. 결측 런은 목록별 삭제(n = {r.core['n_total']} 중 {len(r.core['dropped_index'])}개 제외).")
    else:
        note = ("B = unstandardized coefficient; SE = standard error; β = standardized coefficient (continuous predictors only); CI = confidence interval; "
                f"M ± SD = mean ± standard deviation; Δ = difference in means (row − reference). Two-sided tests, α = {F.bounded(sp['alpha'], 2, False)}. "
                f"Runs with missing values were excluded listwise ({len(r.core['dropped_index'])} of {r.core['n_total']}).")
    if r.ds.is_demo:
        note += " 예시(모의) 데이터 — 실제 측정값이 아님." if ko else " Simulated demo data — not real measurements."
    return {"label": "표 1." if ko else "Table 1", "title": _u(title, lang), "panels": panels, "note": _u(note, lang), "lang": lang}


# ---------------------------------------------------------------- 표 렌더러

APA_CSS = """
.apa-t{font-family:'Times New Roman',Times,'Malgun Gothic',serif;color:#000;background:#fff;padding:14px 16px;max-width:100%;overflow-x:auto;margin:0}
.apa-t.ko{font-family:'Malgun Gothic','맑은 고딕','Times New Roman',serif}
.apa-t .lab{font-weight:700;margin:0}
.apa-t .ttl{font-style:italic;margin:0 0 6px}
.apa-t.ko .ttl{font-style:normal}
.apa-t table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.35}
.apa-t th,.apa-t td{padding:3px 8px;text-align:center;white-space:nowrap;border:0;font-weight:400;color:#000;background:#fff;font-family:inherit}
.apa-t th:first-child,.apa-t td:first-child{text-align:left}
.apa-t thead tr:first-child th{border-top:1.5px solid #000}
.apa-t tr.hdr th{border-bottom:.75px solid #000;font-style:italic}
.apa-t tr.hdr th:first-child{font-style:normal}
.apa-t tr.panel td{font-style:italic;padding-top:8px;text-align:left}
.apa-t tr.sect td{text-align:left}
.apa-t tr.ind td:first-child{padding-left:22px}
.apa-t tr.foot td{font-size:11.5px;white-space:normal;text-align:left;padding-bottom:6px}
.apa-t tbody tr:last-child td{border-bottom:1.5px solid #000}
.apa-t .note{font-size:11.5px;margin:6px 0 0}
.apa-t .note i{font-style:italic}
"""


def _hdr_cell(c: str) -> str:
    """머리글: 통계 기호는 이탤릭(APA) — B, SE, t, p, n, M, SD, F, g."""
    e = html.escape(c)
    for sym in ("SE", "SD"):
        e = e.replace(sym, f"<i>{sym}</i>")
    for sym in ("B", "t", "p", "n", "M", "g", "β"):
        e = e.replace(f"{sym} ", f"<i>{sym}</i> ") if e.startswith(sym + " ") or f" {sym} " in e else e
        if e == sym:
            e = f"<i>{sym}</i>"
    return e


def table1_html(r, lang: str = "ko", zero: str | None = None, standalone: bool = False) -> str:
    t = table1_model(r, lang, zero)
    ncol = 7
    out = [f'<figure class="apa-t {lang}">', f'<p class="lab">{html.escape(t["label"])}' + (f' <span style="font-weight:400">{html.escape(t["title"])}</span></p>' if lang == "ko" else "</p>")]
    if lang != "ko":
        out.append(f'<p class="ttl">{html.escape(t["title"])}</p>')
    out.append("<table>")
    first = True
    for p in t["panels"]:
        if first:
            out.append("<thead>")
        out.append(f'<tr class="hdr">' + "".join(f"<th>{_hdr_cell(h)}</th>" for h in p["header"]) + "</tr>")
        if first:
            out.append("</thead><tbody>")
            first = False
        out.append(f'<tr class="panel"><td colspan="{ncol}">{html.escape(_u(p["title"], lang))}</td></tr>')
        for row in p["rows"]:
            cls = {"section": "sect", "indent": "ind", "row": ""}[row["kind"]]
            if row["kind"] == "section":
                out.append(f'<tr class="sect"><td colspan="{ncol}">{html.escape(row["cells"][0])}</td></tr>')
            else:
                out.append(f'<tr class="{cls}">' + "".join(f"<td>{html.escape(c)}</td>" for c in row["cells"]) + "</tr>")
        out.append(f'<tr class="foot"><td colspan="{ncol}">{html.escape(_u(p["foot"], lang))}</td></tr>')
    out.append("</tbody></table>")
    note_lab = "주." if lang == "ko" else "Note."
    out.append(f'<p class="note"><i>{note_lab}</i> {html.escape(t["note"])}</p></figure>')
    frag = "\n".join(out)
    # 머리글 행이 패널마다 다르므로 첫 패널 머리글만 thead에 두고, 둘째 패널 머리글은 본문 안 'hdr' 행으로 둔다
    if standalone:
        return _page(t["label"] + " " + t["title"], f"<style>{APA_CSS}body{{background:#fff;margin:24px}}</style>" + frag, lang)
    return f"<style>{APA_CSS}</style>" + frag


def _page(title: str, body: str, lang: str) -> str:
    return (f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{html.escape(title)}</title></head><body>{body}</body></html>")


def table1_csv(r, lang: str = "ko", zero: str | None = None) -> str:
    import csv
    t = table1_model(r, lang, zero, minus="-")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([f"{t['label']} {t['title']}"])
    for p in t["panels"]:
        w.writerow([p["title"]])
        w.writerow(p["header"])
        for row in p["rows"]:
            w.writerow([("  " if row["kind"] == "indent" else "") + row["cells"][0]] + row["cells"][1:])
        w.writerow([p["foot"]])
    w.writerow([("주. " if lang == "ko" else "Note. ") + t["note"]])
    return "\ufeff" + buf.getvalue()


def _tex(s: str) -> str:
    rep = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
           "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    s = "".join(rep.get(ch, ch) for ch in s)
    return (s.replace("±", r"$\pm$").replace("β", r"$\beta$").replace("Δ", r"$\Delta$").replace("−", r"$-$")
            .replace("R²", r"$R^2$").replace("°C", r"\textdegree{}C").replace("℃", r"\textdegree{}C").replace("–", "--")
            .replace("< ", r"$<$ ").replace("> ", r"$>$ ").replace("α", r"$\alpha$").replace("×", r"$\times$"))


def table1_latex(r, lang: str = "ko", zero: str | None = None) -> str:
    t = table1_model(r, lang, zero)
    lines = ["% 표 1 — booktabs 필요: \\usepackage{booktabs}" + ("; 한국어는 \\usepackage{kotex}" if lang == "ko" else ""),
             "\\begin{table}[htbp]", "\\centering", "\\small",
             f"\\caption{{{_tex(t['title'])}}}", "\\label{tab:table1}", "\\begin{tabular}{lcccccc}", "\\toprule"]
    for i, p in enumerate(t["panels"]):
        if i:
            lines.append("\\midrule")
        lines.append(" & ".join(f"\\textit{{{_tex(h)}}}" if h in ("B", "SE", "t", "p", "n", "β") else _tex(h) for h in p["header"]) + " \\\\")
        lines.append("\\midrule")
        lines.append(f"\\multicolumn{{7}}{{l}}{{\\textit{{{_tex(p['title'])}}}}} \\\\")
        for row in p["rows"]:
            if row["kind"] == "section":
                lines.append(f"\\multicolumn{{7}}{{l}}{{{_tex(row['cells'][0])}}} \\\\")
            else:
                c0 = ("\\quad " if row["kind"] == "indent" else "") + _tex(row["cells"][0])
                lines.append(" & ".join([c0] + [_tex(c) for c in row["cells"][1:]]) + " \\\\")
        lines.append(f"\\multicolumn{{7}}{{p{{0.95\\linewidth}}}}{{\\footnotesize {_tex(p['foot'])}}} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}",
              f"\\par\\smallskip\\parbox{{0.95\\linewidth}}{{\\footnotesize\\textit{{{'주.' if lang == 'ko' else 'Note.'}}} {_tex(t['note'])}}}",
              "\\end{table}"]
    return "\n".join(lines) + "\n"


def table1_markdown(r, lang: str = "ko", zero: str | None = None) -> str:
    t = table1_model(r, lang, zero)
    esc = lambda s: s.replace("|", "\\|")  # noqa: E731
    out = [f"**{t['label']}** {t['title']}", ""]
    for p in t["panels"]:
        out.append(f"*{esc(p['title'])}*")
        out.append("")
        out.append("| " + " | ".join(esc(h) for h in p["header"]) + " |")
        out.append("|" + "|".join([":---"] + [":---:"] * 6) + "|")
        for row in p["rows"]:
            c = row["cells"]
            if row["kind"] == "section":
                out.append(f"| {esc(c[0])} |" + " |" * 6)
            else:
                out.append("| " + ("&emsp;" if row["kind"] == "indent" else "") + " | ".join(esc(x) for x in c) + " |")
        out.append("")
        out.append(f"<small>{esc(p['foot'])}</small>")
        out.append("")
    out.append(f"*{'주.' if lang == 'ko' else 'Note.'}* {t['note']}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- DOCX

def _docx_base(lang: str):
    from docx import Document
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(sec, side, Mm(20))
    st = doc.styles["Normal"]
    latin = "Times New Roman"
    st.font.name = latin
    st.font.size = Pt(10)
    rpr = st.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs"):
        rf.set(qn(a), latin)
    rf.set(qn("w:eastAsia"), "Malgun Gothic")
    st.paragraph_format.space_after = Pt(2)
    return doc


def _cell_border(cell, **edges):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tcPr = cell._tc.get_or_add_tcPr()
    b = tcPr.find(qn("w:tcBorders"))
    if b is None:
        b = OxmlElement("w:tcBorders")
        tcPr.append(b)
    for edge in ("top", "left", "bottom", "right"):
        el = b.find(qn(f"w:{edge}"))
        if el is None:
            el = OxmlElement(f"w:{edge}")
            b.append(el)
        sz = edges.get(edge)
        el.set(qn("w:val"), "single" if sz else "nil")
        if sz:
            el.set(qn("w:sz"), str(sz))
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), "000000")


def _no_table_borders(table):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    tblPr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        b.append(el)
    tblPr.append(b)


def _para(cell_or_doc, text, size=9, bold=False, italic=False, align=None, first=True):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    p = cell_or_doc.paragraphs[0] if (first and hasattr(cell_or_doc, "paragraphs") and cell_or_doc.paragraphs and not cell_or_doc.paragraphs[0].text
                                       and not hasattr(cell_or_doc, "sections")) else cell_or_doc.add_paragraph()
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.bold, run.italic = bold, italic
    if align:
        p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER, "right": WD_ALIGN_PARAGRAPH.RIGHT}[align]
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.space_before = Pt(0)
    return p


def _docx_table1(doc, r, lang, zero=None):
    from docx.shared import Mm, Pt
    t = table1_model(r, lang, zero)
    if lang == "ko":
        p = doc.add_paragraph()
        a = p.add_run(t["label"] + " ")
        a.bold = True
        p.add_run(t["title"])
    else:
        p = doc.add_paragraph()
        p.add_run(t["label"]).bold = True
        p2 = doc.add_paragraph()
        p2.add_run(t["title"]).italic = True
    rows = []
    for i, pn in enumerate(t["panels"]):
        rows.append(("hdr", pn["header"], i))
        rows.append(("panel", [pn["title"]], i))
        for row in pn["rows"]:
            rows.append((row["kind"], row["cells"], i))
        rows.append(("foot", [pn["foot"]], i))
    table = doc.add_table(rows=len(rows), cols=7)
    _no_table_borders(table)
    table.autofit = True
    widths = [Mm(44), Mm(14), Mm(22), Mm(20), Mm(16), Mm(18), Mm(36)]
    for ri, (kind, cells, _pi) in enumerate(rows):
        tr = table.rows[ri]
        for ci, w in enumerate(widths):
            tr.cells[ci].width = w
        if kind in ("panel", "section", "foot"):
            m = tr.cells[0].merge(tr.cells[6])
            _para(m, cells[0], size=8 if kind == "foot" else 9, italic=kind == "panel", align="left")
        else:
            for ci, c in enumerate(cells):
                txt = ("    " if (kind == "indent" and ci == 0) else "") + c
                _para(tr.cells[ci], txt, size=9, italic=(kind == "hdr" and ci > 0 and c in ("B", "SE", "β", "t", "p", "n")),
                      align="left" if ci == 0 else "center")
    # 규칙선: 표 맨 위(굵게) · 머리글 아래(가늘게) · 표 맨 아래(굵게) — 세로선 없음
    for ri, (kind, _c, _pi) in enumerate(rows):
        for cell in table.rows[ri].cells:
            edges = {}
            if ri == 0:
                edges["top"] = 12
            if kind == "hdr":
                edges["bottom"] = 6
                if ri > 0:
                    edges["top"] = 6
            if ri == len(rows) - 1:
                edges["bottom"] = 12
            _cell_border(cell, **edges)
    n = doc.add_paragraph()
    run = n.add_run("주. " if lang == "ko" else "Note. ")
    run.italic = True
    run.font.size = Pt(8)
    rr = n.add_run(t["note"])
    rr.font.size = Pt(8)
    return table


def table1_docx(r, lang: str = "ko", zero: str | None = None) -> bytes:
    doc = _docx_base(lang)
    _docx_table1(doc, r, lang, zero)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- 해석 세 문장

def _hedges(r) -> list[tuple[str, str]]:
    """해석에 붙일 단서(한국어, 영어)."""
    st = {c["key"]: c["status"] for c in r.out["assumptions"]}
    out = []
    if st.get("normality") == "fail":
        out.append(("잔차 정규성 위반", "non-normal residuals"))
    if st.get("influence") == "fail":
        out.append(("영향이 큰 런", "highly influential runs"))
    if st.get("sample_size") in ("warn", "fail"):
        out.append((f"작은 표본(n = {r.core['n_used']})", f"the small sample (n = {r.core['n_used']})"))
    if st.get("linearity") == "warn":
        out.append(("곡선 관계 가능성", "possible non-linearity"))
    return out


def _join_ko(xs):
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + "과 " + xs[-1] if xs else ""


def _join_en(xs):
    return xs[0] if len(xs) == 1 else (", ".join(xs[:-1]) + (", and " if len(xs) > 2 else " and ") + xs[-1]) if xs else ""


def _lv(r, var, value, lang, mid=True):
    lab = r.labels.level(var, value, lang)
    return F.mid_en(lab) if (lang == "en" and mid) else lab


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def interpretation(r, lang: str = "ko", zero: str | None = None) -> list[str]:
    """정확히 세 문장: (1) 모형 적합, (2) 연속 설명 변수, (3) 집단(산 종류) 차이 + 보정 효과."""
    L, reg, sp = r.labels, r.core["regression"], r.spec
    ko = lang == "ko"
    lead = _lead(r, lang, zero)
    a = sp["alpha"]
    y = L.var(sp["outcome"], lang, unit=False)
    yl = y if ko else y.lower()
    uy = L.unit(sp["outcome"])
    hc3 = r.out["primary_se"] == "HC3"
    hedges = _hedges(r)
    # (1) 모형 적합
    if reg:
        fit = reg["fit"]
        stats_ = (f"R² = {F.bounded(fit['r2'], 2, lead)}, {'수정 R²' if ko else 'adjusted R²'} = {F.bounded(fit['adj_r2'], 2, lead)}, "
                  f"F({F.df_str(fit['df_model'])}, {F.df_str(fit['df_resid'])}) = {F.n(fit['F'], 2)}, {F.p_txt(fit['F_p'], lead)}, n = {fit['n']}")
        pct = round(fit["r2"] * 100)
        sig = fit["F_p"] is not None and fit["F_p"] < a
        preds = [L.var(c, lang, unit=False) for c in sp["continuous"]] + [L.var(c["name"], lang, unit=False) for c in sp["categorical"]]
        if ko:
            head = f"{F.w('·'.join(preds), '을')} 넣은 회귀 모형은 {yl} 변동의 {pct}%를 설명했"
            if not sig:
                head += "지만 전체적으로 유의하지 않았"
            notes = [h[0] for h in hedges] + (["이분산"] if hc3 else [])
            if hedges:
                s1 = f"{head}으나({stats_}), {_join_ko(notes)} 때문에 p값과 신뢰구간은 잠정적으로 해석해야 한다."
            elif hc3:
                s1 = f"{head}고({stats_}), 잔차의 이분산 때문에 표준오차는 HC3 강건 추정치를 썼다."
            else:
                s1 = f"{head}다({stats_})."
        else:
            s1 = (f"The regression model including {_join_en([p.lower() for p in preds])} explained {pct}% of the variance in {yl}"
                  + ("" if sig else ", although the overall model was not significant") + f" ({stats_})")
            if hc3:
                s1 += ", with HC3 heteroscedasticity-consistent standard errors"
            if hedges:
                s1 += f"; because of {_join_en([h[1] for h in hedges])}, p-values and confidence intervals should be interpreted with caution"
            s1 += "."
    else:
        g = _group_label(r, lang)
        s1 = (f"회귀 모형 없이 {g}에 따른 {yl} 차이만 비교했다(n = {r.core['n_used']})." if ko else
              f"Only the difference in {yl} by {g.lower()} was tested (no regression model; n = {r.core['n_used']}).")
    # (2) 연속 설명 변수
    if reg and sp["continuous"]:
        sigs, nss = [], []
        for c in sp["continuous"]:
            row = _coef_view(r, next(x for x in reg["coef"] if x["term"] == c))
            d = F.dec_for(row["SE"])
            st = f"B = {F.n(row['B'], d)}, 95% CI {F.ci(row['ci'][0], row['ci'][1], d)}, {F.p_txt(row['p'], lead)}"
            item = {"c": c, "B": row["B"], "d": d, "ux": _u(L.unit(c), lang), "st": st, "name": L.var(c, lang, unit=False)}
            (sigs if row["p"] is not None and row["p"] < a else nss).append(item)
        if ko:
            parts = []
            for i, it in enumerate(sigs):
                last = i == len(sigs) - 1 and not nss
                up = it["B"] > 0
                verb = ("증가했다" if up else "감소했다") if last else ("증가했고" if up else "감소했고")
                subj = f"{F.w(yl, '은')} " if i == 0 else ""
                parts.append(f"{F.w(it['name'], '이')} 1{(' ' + it['ux']) if it['ux'] else ''} 증가할 때마다 {subj}"
                             f"{F.n(abs(it['B']), it['d'])}{_pct_unit(uy, 'ko')}씩 {verb}({it['st']})")
            if nss:
                names = [it["name"] for it in nss]
                stl = "; ".join(it["st"] for it in nss)
                parts.append(f"{_join_ko(names)}의 효과는 유의하지 않았다({('각각 ' if len(nss) > 1 else '') + stl})")
            s2 = ("HC3 강건 표준오차 기준으로 " if hc3 else "") + ", ".join(parts) + "."
        else:
            parts = []
            prev_dir = None
            for i, it in enumerate(sigs):
                dirw = "increased" if it["B"] > 0 else "decreased"
                lead_txt = f"{yl} {dirw} by " if i == 0 else ("by " if dirw == prev_dir else f"{dirw} by ")
                parts.append(f"{lead_txt}{F.n(abs(it['B']), it['d'])}{_pct_unit(uy, 'en')} per {it['ux'] or 'unit'} of {it['name'].lower()} ({it['st']})")
                prev_dir = dirw
            s2 = _join_en(parts)
            if nss:
                names = [it["name"].lower() for it in nss]
                stl = "; ".join(it["st"] for it in nss)
                ns_txt = f"{_join_en(names)} had no significant effect ({('respectively ' if len(nss) > 1 else '') + stl})"
                s2 = f"{s2}, whereas {ns_txt}" if s2 else ns_txt
            s2 = ("Based on HC3 robust standard errors, " + s2 if hc3 else _cap(s2)) + "."
    else:
        s2 = ("연속 설명 변수(온도·시간 등)는 모형에 넣지 않았다." if ko else "No continuous predictors were included in the model.")
    return [s1, s2, _sentence3(r, lang, lead)]


def _sentence3(r, lang, lead) -> str:
    L, reg, grp, sp = r.labels, r.core["regression"], r.core["groups"], r.spec
    ko = lang == "ko"
    a = sp["alpha"]
    if not grp:
        return "집단 비교 변수를 고르지 않아 집단 차이는 검정하지 않았다." if ko else "No group comparison was performed."
    from .analysis import test_name
    g = sp["group"]
    uy = L.unit(sp["outcome"])
    y = L.var(sp["outcome"], lang, unit=False)
    yl = y if ko else y.lower()
    ref = grp["levels"][0]
    st = {c["key"]: c["status"] for c in r.out["assumptions"]}
    mn = min(x["n"] for x in grp["desc"])
    hk, he = [], []
    if st.get("group_n") in ("warn", "fail"):
        hk.append(f"집단 n이 작아(최소 {mn}) 잠정적")
        he.append(f"tentative given small groups (min n = {mn})")
    if st.get("group_normality") == "fail":
        hk.append("정규성 위반 — 비모수 검정도 확인")
        he.append("non-normal groups; see the non-parametric test")
    hedge_ko = "".join("; " + x for x in hk)
    hedge_en = "".join("; " + x for x in he)
    others = [L.var(c, lang, unit=False) for c in sp["continuous"]]
    others_ko = "·".join(others) if others else "다른 변수"
    others_en = _join_en([o.lower() for o in others]) if others else "other predictors"
    in_model = bool(reg) and g in [c["name"] for c in sp["categorical"]]
    hc3 = r.out["primary_se"] == "HC3"
    if grp["kind"] == "t":
        lv = grp["levels"][1]
        A, B = _lv(r, g, lv, lang), _lv(r, g, ref, lang)
        res = grp[grp["primary"]]
        da = next(x for x in grp["desc"] if x["level"] == lv)
        db = next(x for x in grp["desc"] if x["level"] == ref)
        dd = F.dec_for(res["se_diff"])
        sig = res["p"] is not None and res["p"] < a
        ms = f"{F.n(da['mean'], 2)} ± {F.n(da['sd'], 2)}{uy} {'대' if ko else 'vs'} {F.n(db['mean'], 2)} ± {F.n(db['sd'], 2)}{uy}"
        tsym = "Welch t" if grp["primary"] == "welch" else "Student t"
        tstat = f"{tsym}({F.df_str(res['df'])}) = {F.n(res['t'], 2)}, {F.p_txt(res['p'], lead)}, Hedges' g = {F.n(res['hedges_g'], 2)}"
        if in_model:
            co = _coef_view(r, next(x for x in reg["coef"] if x["term"] == f"{g}[{lv}]"))
            d2 = F.dec_for(co["SE"])
            adj_sig = co["p"] is not None and co["p"] < a
            adj = f"B = {F.n(co['B'], d2)}, 95% CI {F.ci(co['ci'][0], co['ci'][1], d2)}, {F.p_txt(co['p'], lead)}"
        if ko:
            mtxt = f"M ± SD {ms}, {tstat}"
            if sig:
                first = f"{F.w(A, '은')} {B}보다 {F.w(yl, '이')} {F.n(abs(res['diff']), dd)}{_pct_unit(uy, 'ko')} {'높았' if res['diff'] > 0 else '낮았'}"
            else:
                first = f"{F.w(A, '과')} {B}의 {yl} 차이는 유의하지 않았"
            if not in_model:
                return f"{first}다({mtxt}{hedge_ko})."
            ctrl = f"{F.w(others_ko, '을')} 보정한 회귀"
            if sig and adj_sig:
                return f"{first}으며({mtxt}), {ctrl}에서도 차이가 유지되었다({adj}{hedge_ko})."
            if sig:
                return f"{first}으나({mtxt}), {ctrl}에서는 차이가 유의하지 않았다({adj}{hedge_ko})."
            if adj_sig:
                return (f"{first}으나({mtxt}), {ctrl}에서는 {F.w(A, '이')} {F.n(abs(co['B']), d2)}{_pct_unit(uy, 'ko')} "
                        f"{'높았다' if co['B'] > 0 else '낮았다'}({adj}{hedge_ko}).")
            return f"{first}고({mtxt}), {ctrl}에서도 유의하지 않았다({adj}{hedge_ko})."
        mtxt = f"M ± SD = {ms}; {tstat}"
        if sig:
            first = (f"{_cap(A)} gave a {yl} {F.n(abs(res['diff']), dd)}{_pct_unit(uy, 'en')} {'higher' if res['diff'] > 0 else 'lower'} "
                     f"than {B} ({mtxt}")
        else:
            first = f"{_cap(yl)} did not differ significantly between {A} and {B} ({mtxt}"
        if not in_model:
            return f"{first}{hedge_en})."
        first += ")"
        if sig and adj_sig:
            tail = f"and the difference remained after adjusting for {others_en} ({adj}{hedge_en})"
        elif sig:
            tail = f"but it was not significant after adjusting for {others_en} ({adj}{hedge_en})"
        elif adj_sig:
            tail = (f"but after adjusting for {others_en}, {A} was {F.n(abs(co['B']), d2)}{_pct_unit(uy, 'en')} "
                    f"{'higher' if co['B'] > 0 else 'lower'} ({adj}{hedge_en})")
        else:
            tail = f"and it remained non-significant after adjusting for {others_en} ({adj}{hedge_en})"
        return f"{first}, {tail}."
    # 3수준 이상: 전체 검정 → Holm 쌍별 → 보정 효과
    om = grp["welch_anova"] if grp["primary"] == "welch" else grp["anova"]
    osig = om["p"] is not None and om["p"] < a
    tn = test_name(grp, lang)
    ostat = f"{tn}, F({F.df_str(om['df1'])}, {F.df_str(om['df2'])}) = {F.n(om['F'], 2)}, {F.p_txt(om['p'], lead)}"
    sigp = [p for p in grp["pairwise"] if p["p_holm"] is not None and p["p_holm"] < a]
    nsp = [p for p in grp["pairwise"] if p not in sigp]
    psym = "p_Holm"
    if in_model:
        tt = next(t for t in reg["term_tests"] if t["term"] == g)
        ts = tt["robust"] if hc3 else tt
        adj_sig = ts["p"] is not None and ts["p"] < a
        adj = f"F({F.df_str(tt['df1'])}, {F.df_str(tt['df2'])}) = {F.n(ts['F'], 2)}, {F.p_txt(ts['p'], lead)}"
    gl = _group_label(r, lang)
    if ko:
        bits = []
        for p in sigp:
            A, B = _lv(r, g, p["a"], "ko"), _lv(r, g, p["b"], "ko")
            bits.append(f"{F.w(A, '이')} {B}보다 {F.n(abs(p['diff']), F.dec_for(p['se_diff']))}{_pct_unit(uy, 'ko')} "
                        f"{'높았' if p['diff'] > 0 else '낮았'}({F.p_txt(p['p_holm'], lead, psym)})")
        if nsp:
            pairs = ", ".join(f"{_lv(r, g, p['a'], 'ko')}–{_lv(r, g, p['b'], 'ko')}" for p in nsp)
            bits.append(f"{pairs} 차이는 유의하지 않았({'; '.join(F.p_txt(p['p_holm'], lead, psym) for p in nsp)})")

        def conj(bit, ending):  # 어간 뒤·괄호 앞에 어미: '높았(p…)' → '높았고(p…)'
            i = bit.rfind("(")
            return bit[:i] + ending + bit[i:]
        joined = "".join(conj(b, "고") + " " for b in bits[:-1])
        s = (f"{gl}에 따라 {F.w(yl, '이')} " + ("달랐으며" if osig else "유의하게 다르지 않았으며") + f"({ostat}{hedge_ko}), "
             f"Holm 보정 쌍별 비교에서 {joined}")
        if in_model:
            s += conj(bits[-1], "으며") + f", {F.w(others_ko, '을')} 보정한 회귀에서 {gl} 전체 효과는 " + ("유의했다" if adj_sig else "유의하지 않았다") + f"({adj})."
        else:
            s += conj(bits[-1], "다") + "."
        return s
    s = f"{_cap(yl)} {'differed' if osig else 'did not differ significantly'} by {gl.lower()} ({ostat}{hedge_en})"
    bits = []
    for p in sigp:
        A, B = _lv(r, g, p["a"], "en"), _lv(r, g, p["b"], "en")
        amt = f"{F.n(abs(p['diff']), F.dec_for(p['se_diff']))}{_pct_unit(uy, 'en')}"
        bits.append(f"{A} {'exceeded' if p['diff'] > 0 else 'was below'} {B} by {amt} ({F.p_txt(p['p_holm'], lead, psym)})")
    if nsp:
        pairs = _join_en([f"{_lv(r, g, p['a'], 'en')} vs {_lv(r, g, p['b'], 'en')}" for p in nsp])
        bits.append(f"{pairs} did not differ ({'; '.join(F.p_txt(p['p_holm'], lead, psym) for p in nsp)})")
    s += "; in Holm-adjusted pairwise comparisons, " + _join_en(bits)
    if in_model:
        s += f"; after adjusting for {others_en}, the overall {gl.lower()} effect was {'significant' if adj_sig else 'not significant'} ({adj})"
    return s + "."


# ---------------------------------------------------------------- 그림

def _setup_fonts():
    global _fonts_ready
    if _fonts_ready:
        return
    from matplotlib import font_manager
    import os
    for f in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\malgunbd.ttf", r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"):
        if os.path.exists(f):
            try:
                font_manager.fontManager.addfont(f)
            except Exception:  # noqa: BLE001
                pass
    _fonts_ready = True


def _font_family(lang):
    from matplotlib import font_manager
    names = {f.name for f in font_manager.fontManager.ttflist}
    if lang == "ko":
        return [n for n in ("Malgun Gothic", "AppleGothic", "NanumGothic") if n in names] + ["DejaVu Sans"]
    return [n for n in ("Arial", "Helvetica", "Liberation Sans") if n in names] + ["DejaVu Sans"]


def _rc(lang, base=8):
    return {"font.family": "sans-serif", "font.sans-serif": _font_family(lang), "font.size": base, "axes.titlesize": base + 1,
            "axes.labelsize": base, "xtick.labelsize": base - 0.5, "ytick.labelsize": base - 0.5, "legend.fontsize": base - 0.5,
            "axes.linewidth": 0.6, "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.major.size": 3, "ytick.major.size": 3,
            "xtick.direction": "out", "ytick.direction": "out", "axes.spines.top": False, "axes.spines.right": False,
            "lines.linewidth": 1.2, "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "path", "axes.unicode_minus": False,
            "savefig.dpi": 300, "figure.dpi": 100, "legend.frameon": False}


def _save(fig, fmt_: str) -> bytes:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    FigureCanvasAgg(fig)
    buf = io.BytesIO()
    meta = {"png": {"Software": "ByOrbit R&D Studio"}, "pdf": {"Creator": "ByOrbit R&D Studio"}, "svg": {"Creator": "ByOrbit R&D Studio"}}[fmt_]
    fig.savefig(buf, format=fmt_, dpi=300, bbox_inches="tight", pad_inches=0.03, metadata=meta)
    return buf.getvalue()


def _panel_tag(ax, tag):
    ax.text(-0.16, 1.04, tag, transform=ax.transAxes, fontweight="bold", fontsize=9, va="bottom", ha="left")


def _bracket(ax, x1, x2, yv, h, text):
    ax.plot([x1, x1, x2, x2], [yv, yv + h, yv + h, yv], color="black", lw=0.6)
    ax.text((x1 + x2) / 2, yv + h * 1.3, text, ha="center", va="bottom", fontsize=7)


def figure1(r, lang: str = "ko", width: str = "double", fmt_: str = "png", zero: str | None = None) -> bytes:
    key = ("fig1", lang, width, fmt_, zero)
    if key in r.cache:
        return r.cache[key]
    from matplotlib.figure import Figure
    import matplotlib
    L, reg, grp, sp = r.labels, r.core["regression"], r.core["groups"], r.spec
    lead = _lead(r, lang, zero)
    d = r.ds.df.loc[r.core["used_index"]].copy()
    xvar = next((c for c in sp["continuous"] if c.startswith("temp")), sp["continuous"][0] if sp["continuous"] else None)
    g = sp["group"]
    levels = grp["levels"] if grp else ([c for c in r.core["levels"].values()][0] if r.core["levels"] else [])
    gvar = g or (sp["categorical"][0]["name"] if sp["categorical"] else None)
    has_a, has_b = reg is not None and xvar is not None, grp is not None
    npan = int(has_a) + int(has_b)
    if npan == 0:
        raise ValueError("그림으로 그릴 회귀·집단 비교가 없습니다.")
    wmm = WIDTH_MM.get(width, 175)
    stacked = width == "single" and npan == 2
    hmm = (128 if stacked else 66) if npan == 2 else 66
    if width == "single" and npan == 1:
        hmm = 66
    if width != "single" and npan == 1:
        wmm, hmm = 120, 80
    _setup_fonts()
    with _mpl_lock, matplotlib.rc_context(_rc(lang)):
        fig = Figure(figsize=(wmm / 25.4, hmm / 25.4))
        axes = fig.subplots(2, 1) if stacked else fig.subplots(1, npan)
        axes = list(np.atleast_1d(axes))
        tags = iter(["(a)", "(b)"])
        y = d[sp["outcome"]].astype(float).to_numpy()
        ylab = _u(L.var(sp["outcome"], lang), lang)
        if has_a:
            ax = axes.pop(0)
            x = d[xvar].astype(float).to_numpy()
            span = (np.nanmax(x) - np.nanmin(x)) or 1.0
            lvls = levels if gvar else [None]
            in_model = gvar in [c["name"] for c in sp["categorical"]]
            means = {c: float(d[c].astype(float).mean()) for c in sp["continuous"]}
            xs = np.linspace(np.nanmin(x), np.nanmax(x), 50)
            coefs = {c["term"]: c["B"] for c in reg["coef"]}
            for i, lv in enumerate(lvls):
                m = (d[gvar].astype(str) == lv).to_numpy() if lv is not None else np.ones(len(d), bool)
                off = (i - (len(lvls) - 1) / 2) * span * 0.018
                lab = L.level(gvar, lv, lang) if lv is not None else None
                col = PALETTE[i % len(PALETTE)]
                ax.scatter(x[m] + off, y[m], s=13, marker=MARKERS[i % len(MARKERS)], facecolor=col, edgecolor="white", linewidth=0.4,
                           alpha=0.9, label=lab, zorder=3)
                # 모형 예측선: 다른 연속 변수는 평균, 범주는 이 수준
                pred = np.full_like(xs, coefs["(Intercept)"])
                for c in sp["continuous"]:
                    pred = pred + coefs[c] * (xs if c == xvar else means[c])
                for cc in sp["categorical"]:
                    want = lv if (cc["name"] == gvar and lv is not None) else cc["reference"]
                    if f"{cc['name']}[{want}]" in coefs:
                        pred = pred + coefs[f"{cc['name']}[{want}]"]
                if in_model or lv is None:
                    ax.plot(xs, pred, color=col, lw=1.2, zorder=2)
            ax.set_xlabel(_u(L.var(xvar, lang), lang))
            ax.set_ylabel(ylab)
            ux = sorted(set(np.round(x, 6)))
            if len(ux) <= 6:
                ax.set_xticks(ux)
                ax.set_xticklabels([F.n(v, 0 if float(v).is_integer() else 1, "−") for v in ux])
            ax.set_xlim(np.nanmin(x) - span * 0.08, np.nanmax(x) + span * 0.08)
            if gvar:
                ax.legend(title=None, loc="upper left", handletextpad=0.3, borderaxespad=0.2, markerscale=1.1)
            others = [c for c in sp["continuous"] if c != xvar]
            if others:
                note = ", ".join(f"{L.var(c, lang, unit=False) if lang == 'ko' else L.var(c, lang, unit=False).lower()} = {F.n(means[c], 0 if means[c] >= 10 else 1)}{(' ' + _u(L.unit(c), lang)) if L.unit(c) else ''}" for c in others)
                ax.text(0.98, 0.03, ("선: 모형 예측 (" if lang == "ko" else "Lines: model at ") + note + (")" if lang == "ko" else ""),
                        transform=ax.transAxes, ha="right", va="bottom", fontsize=6.3, color="#444")
            _panel_tag(ax, next(tags))
        if has_b:
            ax = axes.pop(0)
            data_ = [d.loc[d[g].astype(str) == lv, sp["outcome"]].astype(float).to_numpy() for lv in levels]
            pos = np.arange(1, len(levels) + 1)
            bp = ax.boxplot(data_, positions=pos, widths=0.5, showfliers=False, patch_artist=True,
                            medianprops={"color": "black", "lw": 0.9}, whiskerprops={"lw": 0.6}, capprops={"lw": 0.6},
                            boxprops={"lw": 0.6})
            for i, patch in enumerate(bp["boxes"]):
                patch.set_facecolor(PALETTE[i % len(PALETTE)] + "22")
                patch.set_edgecolor(PALETTE[i % len(PALETTE)])
            rng = np.random.default_rng(7)
            for i, vals in enumerate(data_):
                jit = rng.uniform(-0.12, 0.12, len(vals))
                ax.scatter(pos[i] - 0.05 + jit, vals, s=9, marker=MARKERS[i % len(MARKERS)], color=PALETTE[i % len(PALETTE)],
                           alpha=0.75, linewidth=0, zorder=3)
                desc = grp["desc"][i]
                ax.errorbar(pos[i] + 0.33, desc["mean"], yerr=[[desc["mean"] - desc["ci"][0]], [desc["ci"][1] - desc["mean"]]],
                            fmt="D", ms=3.2, color="black", elinewidth=0.8, capsize=2, zorder=4)
            ax.set_xticks(pos)
            ax.set_xticklabels([L.level(g, lv, lang) for lv in levels])
            ax.set_xlim(0.4, len(levels) + 0.75)
            ax.set_ylabel(ylab)
            ax.set_xlabel(_u(L.var(g, lang, unit=False), lang))
            ymax = max(float(np.max(v)) for v in data_)
            ymin = min(float(np.min(v)) for v in data_)
            h = (ymax - ymin) * 0.04 or 0.1
            if grp["kind"] == "t":
                res = grp[grp["primary"]]
                lab = f"{'Welch ' if grp['primary'] == 'welch' else ''}t({F.df_str(res['df'])}) = {F.n(res['t'], 2, '−')}, {F.p_txt(res['p'], lead)}"
                _bracket(ax, 1, 2, ymax + h, h, lab)
                top = ymax + h * 4.5
            else:
                yv = ymax + h
                spans = sorted(grp["pairwise"], key=lambda p: (abs(levels.index(p["a"]) - levels.index(p["b"])), min(levels.index(p["a"]), levels.index(p["b"]))))
                for p in spans:
                    i1, i2 = sorted((levels.index(p["b"]) + 1, levels.index(p["a"]) + 1))
                    _bracket(ax, i1, i2, yv, h, F.p_txt(p["p_holm"], lead, "p (Holm)"))
                    yv += h * 4
                top = yv + h
                om = grp["welch_anova"] if grp["primary"] == "welch" else grp["anova"]
                ax.set_title(("Welch " if grp["primary"] == "welch" else "") + f"F({F.df_str(om['df1'])}, {F.df_str(om['df2'])}) = {F.n(om['F'], 2, '−')}, {F.p_txt(om['p'], lead)}",
                             fontsize=7, loc="right")
            ax.set_ylim(ymin - h * 2, top)
            _panel_tag(ax, next(tags))
        if r.ds.is_demo:
            fig.text(0.995, 0.002, "예시(모의) 데이터" if lang == "ko" else "Simulated demo data", ha="right", va="bottom", fontsize=5.5, color="#888")
        fig.tight_layout(pad=0.4, w_pad=1.6, h_pad=1.2)
        out = _save(fig, fmt_)
    r.cache[key] = out
    return out


def caption(r, lang: str = "ko", zero: str | None = None) -> str:
    L, reg, grp, sp = r.labels, r.core["regression"], r.core["groups"], r.spec
    lead = _lead(r, lang, zero)
    ko = lang == "ko"
    y = L.var(sp["outcome"], lang, unit=False)
    xvar = next((c for c in sp["continuous"] if c.startswith("temp")), sp["continuous"][0] if sp["continuous"] else None)
    g = sp["group"]
    parts = []
    tag = iter(["(a)", "(b)"])
    if reg and xvar:
        xl = L.var(xvar, lang, unit=False)
        others = [c for c in sp["continuous"] if c != xvar]
        d = r.ds.df.loc[r.core["used_index"]]
        at = ", ".join(f"{L.var(c, lang, unit=False)} {F.n(float(d[c].mean()), 1)} {L.unit(c)}".strip() for c in others)
        at_en = _join_en([f"{L.var(c, lang, unit=False).lower()} ({F.n(float(d[c].mean()), 1)} {L.unit(c)})".replace(" )", ")") for c in others])
        if ko:
            parts.append(f"{next(tag)} {xl}에 따른 {y}" + (f"({_group_label(r, 'ko')}별)" if g else "") + ". 점은 런 하나씩(겹치지 않게 수준별로 조금 옮김), 선은 OLS 모형 예측값"
                         + (f"({at} 평균에서)" if at else "") + ".")
        else:
            parts.append(f"{next(tag)} {y} versus {xl.lower()}" + (f" by {_group_label(r, 'en').lower()}" if g else "")
                         + "; points are individual runs (offset horizontally by group for visibility) and lines are OLS model predictions"
                         + (f" at the mean {at_en}" if at else "") + ".")
    if grp:
        if grp["kind"] == "t":
            res = grp[grp["primary"]]
            stat = f"{'Welch ' if grp['primary'] == 'welch' else ''}t({F.df_str(res['df'])}) = {F.n(res['t'], 2)}, {F.p_txt(res['p'], lead)}"
        else:
            om = grp["welch_anova"] if grp["primary"] == "welch" else grp["anova"]
            stat = (f"{'Welch ' if grp['primary'] == 'welch' else ''}F({F.df_str(om['df1'])}, {F.df_str(om['df2'])}) = {F.n(om['F'], 2)}, {F.p_txt(om['p'], lead)}; "
                    + ("괄호 선은 Holm 보정 쌍별 p" if ko else "brackets show Holm-adjusted pairwise p"))
        if ko:
            parts.append(f"{next(tag)} {_group_label(r, 'ko')}별 {y}. 상자는 중앙값과 사분위 범위, 수염은 1.5 × IQR, 점은 런, 검은 마름모는 평균 ± 95% CI; {stat}.")
        else:
            parts.append(f"{next(tag)} {y} by {_group_label(r, 'en').lower()}; boxes show the median and interquartile range, whiskers 1.5 × IQR, points individual runs, "
                         f"and black diamonds the mean ± 95% CI; {stat}.")
    nd = len(r.core["dropped_index"])
    tail = (f" n = {r.core['n_used']}런" + (f"(결측 {nd}런 제외)" if nd else "") + "." if ko else
            f" n = {r.core['n_used']} runs" + (f" ({nd} excluded for missing data)" if nd else "") + ".")
    if r.ds.is_demo:
        tail += " 예시(모의) 데이터." if ko else " Simulated demo data."
    head = (f"그림 1. 추출 조건과 {y}." if ko else f"Figure 1. Effects of extraction conditions on {y.lower()}.") if (reg and xvar) else \
        (f"그림 1. {_group_label(r, 'ko')}별 {y}." if ko else f"Figure 1. {y} by {_group_label(r, 'en').lower()}.")
    return _u(head + " " + " ".join(parts) + tail, lang)


def diagnostics(r, lang: str = "ko", fmt_: str = "png") -> bytes:
    """보조 그림(그림 1에 세지 않음): 잔차-적합값, 정규 Q–Q, Cook's D, 잔차-연속 변수."""
    key = ("diag", lang, fmt_)
    if key in r.cache:
        return r.cache[key]
    from matplotlib.figure import Figure
    import matplotlib
    reg = r.core["regression"]
    if not reg:
        raise ValueError("회귀 모형이 없어 진단 그림을 그릴 수 없습니다.")
    L, sp = r.labels, r.spec
    ko = lang == "ko"
    _setup_fonts()
    resid, fitted = np.asarray(reg["resid"]), np.asarray(reg["fitted"])
    labels = [r.ds.run_labels()[i] for i in r.core["used_index"]]
    with _mpl_lock, matplotlib.rc_context(_rc(lang)):
        fig = Figure(figsize=(175 / 25.4, 140 / 25.4))
        ax = fig.subplots(2, 2)
        a = ax[0, 0]
        a.scatter(fitted, resid, s=10, color=PALETTE[0], alpha=0.8, linewidth=0)
        a.axhline(0, color="#666", lw=0.6, ls="--")
        try:
            from statsmodels.nonparametric.smoothers_lowess import lowess
            lw = lowess(resid, fitted, frac=0.7)
            a.plot(lw[:, 0], lw[:, 1], color=PALETTE[1], lw=1)
        except Exception:  # noqa: BLE001
            pass
        a.set_xlabel("적합값" if ko else "Fitted values")
        a.set_ylabel("잔차" if ko else "Residuals")
        bp = reg["bp"]
        a.set_title(f"Breusch–Pagan LM = {F.n(bp['LM'], 2, '−')}, {F.p_txt(bp['p'], ko)}", fontsize=7, loc="right")
        _panel_tag(a, "(a)")
        b = ax[0, 1]
        q = reg["qq"]
        b.scatter(q["theoretical"], q["sample"], s=10, color=PALETTE[0], alpha=0.8, linewidth=0)
        lim = [min(q["theoretical"]), max(q["theoretical"])]
        b.plot(lim, lim, color="#666", lw=0.6, ls="--")
        b.set_xlabel("이론 분위수(정규)" if ko else "Theoretical quantiles")
        b.set_ylabel("표준화 잔차" if ko else "Standardized residuals")
        sw = reg["shapiro"] or {}
        if sw:
            b.set_title(f"Shapiro–Wilk W = {F.n(sw['W'], 3, '−')}, {F.p_txt(sw['p'], ko)}", fontsize=7, loc="right")
        _panel_tag(b, "(b)")
        c = ax[1, 0]
        cooks = np.asarray(reg["cooks"])
        cut = 4 / len(cooks)
        idx = np.arange(1, len(cooks) + 1)
        c.vlines(idx, 0, cooks, color=PALETTE[0], lw=0.8)
        c.axhline(cut, color=PALETTE[1], lw=0.7, ls="--")
        c.text(idx[-1], cut, " 4/n", color=PALETTE[1], fontsize=6.5, va="bottom", ha="right")
        for i in np.argsort(-cooks)[:3]:
            if cooks[i] > cut:
                c.annotate(labels[i], (idx[i], cooks[i]), fontsize=6, xytext=(2, 2), textcoords="offset points")
        c.set_xlabel("런(분석 순서)" if ko else "Observation")
        c.set_ylabel("Cook's D")
        _panel_tag(c, "(c)")
        dd = ax[1, 1]
        xvar = next((cc for cc in sp["continuous"] if cc.startswith("temp")), sp["continuous"][0] if sp["continuous"] else None)
        if xvar:
            xv = r.ds.df.loc[r.core["used_index"], xvar].astype(float).to_numpy()
            dd.scatter(xv, resid, s=10, color=PALETTE[0], alpha=0.8, linewidth=0)
            dd.axhline(0, color="#666", lw=0.6, ls="--")
            ux = sorted(set(np.round(xv, 6)))
            if len(ux) <= 6:
                dd.set_xticks(ux)
                dd.set_xticklabels([F.n(v, 0 if float(v).is_integer() else 1, "−") for v in ux])
            dd.set_xlabel(_u(L.var(xvar, lang), lang))
            dd.set_ylabel("잔차" if ko else "Residuals")
            lin = next((x for x in reg["linearity"] if x["var"] == xvar and x["testable"]), None)
            if lin:
                dd.set_title(("2차항 " if ko else "Quadratic term ") + F.p_txt(lin["p"], ko), fontsize=7, loc="right")
        else:
            sl = np.sqrt(np.abs(np.asarray(reg["stud_resid"])))
            dd.scatter(fitted, sl, s=10, color=PALETTE[0], alpha=0.8, linewidth=0)
            dd.set_xlabel("적합값" if ko else "Fitted values")
            dd.set_ylabel("√|표준화 잔차|" if ko else "√|Standardized residuals|")
        _panel_tag(dd, "(d)")
        if r.ds.is_demo:
            fig.text(0.995, 0.002, "예시(모의) 데이터" if ko else "Simulated demo data", ha="right", va="bottom", fontsize=5.5, color="#888")
        fig.tight_layout(pad=0.5, w_pad=2, h_pad=1.5)
        out = _save(fig, fmt_)
    r.cache[key] = out
    return out


# ---------------------------------------------------------------- 가정 점검 보고서

STATUS_TXT = {"ko": {"pass": "통과", "warn": "주의", "fail": "실패", "info": "설계로 판단"},
              "en": {"pass": "Pass", "warn": "Caution", "fail": "Fail", "info": "Design-based"}}


def assumption_rows(r, lang: str):
    ko = lang == "ko"
    for c in r.out["assumptions"]:
        yield [c["name_ko"] if ko else c["name_en"], c["test"], c["stat"], c["threshold"], STATUS_TXT[lang][c["status"]],
               c["text_ko"] if ko else c["text_en"]]


def assumptions_html(r, lang: str = "ko", standalone: bool = True) -> str:
    ko = lang == "ko"
    head = ["점검", "검정", "통계량", "기준", "판정", "설명"] if ko else ["Check", "Test", "Statistic", "Criterion", "Verdict", "Explanation"]
    css = APA_CSS + ".apa-t td:last-child{white-space:normal;text-align:left;min-width:260px}.apa-t td:nth-child(3){white-space:normal}" \
                    ".apa-t .s-pass{color:#1e6b3a}.apa-t .s-warn{color:#8a5200}.apa-t .s-fail{color:#a1241b}.apa-t .s-info{color:#444}"
    rows = []
    for c, row in zip(r.out["assumptions"], assumption_rows(r, lang)):
        rows.append("<tr>" + "".join(f'<td class="s-{c["status"]}">{html.escape(x)}</td>' if i == 4 else f"<td>{html.escape(x)}</td>"
                                     for i, x in enumerate(row)) + "</tr>")
    title = ("보조 표 S1. 가정 점검" if ko else "Supplementary Table S1. Assumption checks")
    m = r.out["methods"]["ko" if ko else "en"]
    body = (f'<figure class="apa-t {lang}"><p class="lab">{html.escape(title)}</p><table><thead><tr class="hdr">'
            + "".join(f"<th>{html.escape(h)}</th>" for h in head) + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
            f'<p class="note"><i>{"방법." if ko else "Methods."}</i> {html.escape(m)}</p>'
            + (f'<p class="note">{"검정이 유의하지 않다는 것은 위반의 근거가 없다는 뜻일 뿐, 가정이 맞다는 증명이 아닙니다(특히 n이 작을 때)." if ko else "A non-significant test indicates no evidence of a violation, not proof that the assumption holds (especially for small n)."}</p>')
            + "</figure>")
    if standalone:
        img = ""
        if r.core["regression"]:
            import base64
            img = ('<p><img alt="diagnostics" style="max-width:100%;height:auto" src="data:image/png;base64,'
                   + base64.b64encode(diagnostics(r, lang, "png")).decode() + '"></p>'
                   + f'<p class="note" style="font-family:inherit">{"보조 그림 S1. (a) 잔차-적합값(등분산), (b) 정규 Q–Q(정규성), (c) Cook의 거리(영향점), (d) 잔차-온도(선형성)." if ko else "Supplementary Figure S1. (a) Residuals vs fitted, (b) normal Q–Q, (c) Cook distance, (d) residuals vs temperature."}</p>')
        return _page(title, f"<style>{css}body{{background:#fff;margin:24px}}</style>" + body.replace("</figure>", img + "</figure>", 1), lang)
    return f"<style>{css}</style>" + body


def assumptions_docx(r, lang: str = "ko") -> bytes:
    from docx.shared import Mm, Pt
    ko = lang == "ko"
    doc = _docx_base(lang)
    p = doc.add_paragraph()
    p.add_run("보조 표 S1. 가정 점검" if ko else "Supplementary Table S1. Assumption checks").bold = True
    head = ["점검", "검정", "통계량", "기준", "판정", "설명"] if ko else ["Check", "Test", "Statistic", "Criterion", "Verdict", "Explanation"]
    rows = list(assumption_rows(r, lang))
    t = doc.add_table(rows=len(rows) + 1, cols=6)
    _no_table_borders(t)
    widths = [Mm(22), Mm(26), Mm(34), Mm(24), Mm(14), Mm(50)]
    for ri, row in enumerate([head] + rows):
        for ci, txt in enumerate(row):
            cell = t.rows[ri].cells[ci]
            cell.width = widths[ci]
            _para(cell, txt, size=7.5, bold=False, italic=False, align="left")
            edges = {}
            if ri == 0:
                edges = {"top": 12, "bottom": 6}
            if ri == len(rows):
                edges["bottom"] = 12
            _cell_border(cell, **edges)
    n = doc.add_paragraph()
    rr = n.add_run(("방법. " if ko else "Methods. "))
    rr.italic = True
    rr.font.size = Pt(8)
    n.add_run(r.out["methods"]["ko" if ko else "en"]).font.size = Pt(8)
    n2 = doc.add_paragraph()
    n2.add_run("검정이 유의하지 않다는 것은 위반의 근거가 없다는 뜻일 뿐, 가정이 맞다는 증명이 아닙니다(특히 n이 작을 때)." if ko else
               "A non-significant test indicates no evidence of a violation, not proof that the assumption holds (especially for small n).").font.size = Pt(8)
    if r.core["regression"]:
        doc.add_picture(io.BytesIO(diagnostics(r, lang, "png")), width=Mm(170))
        cap = doc.add_paragraph()
        cap.add_run("보조 그림 S1. (a) 잔차-적합값(등분산), (b) 정규 Q–Q(정규성), (c) Cook의 거리(영향점), (d) 잔차-연속 변수(선형성)." if ko else
                    "Supplementary Figure S1. (a) Residuals vs fitted, (b) normal Q–Q, (c) Cook distance, (d) residuals vs a continuous predictor.").font.size = Pt(8)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
