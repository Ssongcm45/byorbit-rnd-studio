"""흐름 모의, 예측 대 실측 비교(잔차·패리티·오차 요약), 민감도(단계 값 하나를 훑기)."""
from __future__ import annotations

import math
import statistics
import time

from ..viz import predict as P
from . import steps as S, store, units as U

IN_SAMPLE_NOTE = "보정에 쓴 런과 같은 런을 비교하면 표본 내 오차라 실제 예측 오차보다 작게 보입니다."


def _ctx(byproduct: str | None, project: str | None, calib: dict | None, keep_charts: bool = False) -> dict:
    bp = P._canon_byproduct(byproduct)
    cs = calib if calib is not None else P.calibration_settings(bp)
    return {"byproduct": bp, "project": project, "calib": cs, "keep_charts": keep_charts,
            "meas": P.measured(bp, project, tuple(cs.get("experiments") or ()))}


def run_flow(steps: list[dict], conditions: dict | None = None, byproduct: str | None = None, project: str | None = None,
             calib: dict | None = None, keep_charts: bool = False, until: str | None = None, ctx: dict | None = None) -> dict:
    """흐름을 차례로 모의한다. 꺼진 단계는 건너뛰고, 오류가 난 단계는 흐름을 그대로 넘긴다(오류는 그 단계에 표시)."""
    t0 = time.perf_counter()
    ctx = ctx or _ctx(byproduct, project, calib, keep_charts)
    conditions = conditions or {}
    stream, results = None, []
    for st in steps:
        base = {"key": st["key"], "type": st["type"], "label": st["label"], "enabled": st.get("enabled", True)}
        if not base["enabled"]:
            results.append({**base, "skipped": True, "stream_in": None if stream is None else S.stream_view(stream)})
        else:
            s_in = stream
            try:
                p = S.clean_params(st["type"], {**st.get("params", {}), **(conditions.get(st["key"]) or {})}, st["label"])
                r = S.simulate_step(st["type"], s_in, p, ctx)
            except S.StepError as ex:
                results.append({**base, "error": str(ex), "stream_in": None if s_in is None else S.stream_view(s_in),
                                "stream_out": None if s_in is None else S.stream_view(s_in), "outputs": {}})
            else:
                stream = r["stream"]
                bal = None
                if s_in is not None:
                    declared = sum(x["dm_kg"] for x in r["losses"])
                    bal = {"dm_in": round(s_in["dm_kg"], 6), "dm_out": round(stream["dm_kg"], 6), "declared_loss": round(declared, 6),
                           "closure": round(s_in["dm_kg"] - stream["dm_kg"] - declared, 9)}
                results.append({**base, "params": p, "stream_in": None if s_in is None else S.stream_view(s_in),
                                "stream_out": S.stream_view(stream), "outputs": r["outputs"], "losses": r["losses"], "side": r["side"],
                                "notes": r["notes"], "warnings": r["warnings"], "balance": bal,
                                **({"predict": r["predict"], "drying_method": r["drying_method"]} if "predict" in r else {})})
        if until and st["key"] == until:
            break
    return {"steps": results, "final": None if stream is None else S.stream_view(stream), "byproduct": ctx["byproduct"],
            "calib": {"experiments": list(ctx["calib"].get("experiments") or []), "ea_fit": bool(ctx["calib"].get("ea_fit"))},
            "summary": evidence_summary(results), "disclaimer": P.DISCLAIMER,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}


def evidence_summary(results: list[dict]) -> dict:
    lit, meas, equip, assum, inp = {}, set(), set(), set(), set()
    for r in results:
        for o in (r.get("outputs") or {}).values():
            for p in o.get("params") or []:
                ev = p["evidence"]
                t = ev["type"]
                if t == "literature":
                    lit[ev.get("doi")] = ev.get("verified")
                elif t == "measured":
                    meas.update(ev.get("samples") or [p["key"]])
                elif t == "equipment":
                    equip.add(p["key"])
                elif t == "input":
                    inp.add((r["key"], p["key"]))
                else:
                    assum.add(p["key"])
    nv = sum(1 for v in lit.values() if v)
    return {"literature": len(lit), "literature_verified": nv, "measured": len(meas), "equipment": len(equip),
            "assumption": len(assum), "input": len(inp),
            "text": f"이 모의의 근거: 문헌 {len(lit)}건(DOI 확인 {nv}) · 실측 {len(meas)}건 · 설비 사양 {len(equip)}개 · "
                    f"가정 {len(assum)}개 · 내 입력 {len(inp)}개"}


def simulate_flow(wf_id: str | None = None, steps: list[dict] | None = None, conditions: dict | None = None,
                  byproduct: str | None = None, project: str | None = None, calib: dict | None = None) -> dict:
    if wf_id:
        f = store.get_flow(wf_id)
        steps = steps or f["steps"]
        byproduct = byproduct or f["byproduct"]
    if not steps:
        raise store.StoreError("모의할 단계가 없습니다. 흐름을 고르거나 단계를 보내세요.")
    steps = store.validate_steps(steps)
    return run_flow(steps, conditions, byproduct, project, calib, keep_charts=False)


# ---------------------------------------------------------------- 비교

def _db_value(target: str, v: dict, moist: float | None) -> tuple[float | None, str | None]:
    """TPC·TDF 실측이 습량 기준이면 같은 단계 수분으로 건량으로 바꾼다."""
    if target in ("tpc", "tdf") and v.get("basis") == "습량" and v["value"] is not None:
        if moist is None:
            return None, "습량 기준 값인데 수분을 몰라 건량으로 바꾸지 못함"
        return v["value"] / (1 - moist / 100), f"습량 → 건량(수분 {moist:.1f}%)"
    return v["value"], None


def compare(exp_id: str, calib: dict | None = None, project: str | None = None) -> dict:
    t0 = time.perf_counter()
    exp = store.get_experiment(exp_id)
    steps = exp["flow"]["steps"]
    labels = {s["key"]: s["label"] for s in steps}
    ctx = _ctx(exp["byproduct"], project, calib)
    runs, pairs_all, evidence = [], [], {}
    for run in exp["runs"]:
        sim = run_flow(steps, run["conditions"], ctx=ctx)
        by = {r["key"]: r for r in sim["steps"]}
        pairs = []
        measured = [v for v in run["values"] if v["kind"] == "measured"]
        moist_meas = {v["step_key"]: v["value"] for v in measured if v["target_key"] == "moisture" and v["value"] is not None}
        for v in measured:
            tk = v["target_key"]
            sr = by.get(v["step_key"])
            pr = {"step_key": v["step_key"], "step_label": labels.get(v["step_key"], v["step_key"] or "-"), "target": tk,
                  "label": v["target"], "unit": S.TARGETS[tk]["unit"] if tk else v["unit"], "measured": v["value"],
                  "measured_text": v["value_text"], "run": run["alias"], "run_label": run["label"], "xrun_id": run["xrun_id"]}
            if not tk:
                pr["note"] = "모델에 없는 대상이라 비교하지 않음"
            elif not sr or sr.get("skipped"):
                pr["note"] = "단계가 꺼져 있거나 없어서 비교하지 않음"
            elif sr.get("error"):
                pr["note"] = "이 단계 모의 오류: " + sr["error"]
            elif tk not in (sr.get("outputs") or {}):
                pr["note"] = "이 단계에서는 이 대상을 예측하지 않음" + (" (원료 TPC·TDF를 모르면 mg 값이 없음)" if tk in ("tpc", "tdf") else "")
            else:
                o = sr["outputs"][tk]
                pr.update(predicted=o["value"], low=o["low"], high=o["high"], status=o.get("status"),
                          warnings=[w for w in o.get("warnings") or [] if w.get("kind") in ("extrapolation", "calibration", "byproduct")])
                evk = f"{v['step_key']}:{tk}"
                if evk not in evidence:
                    evidence[evk] = {"step_label": pr["step_label"], "label": o["label"], "params": o["params"], "formula": o["formula"],
                                     "calibration": o.get("calibration")}
                pr["ev"] = evk
                mval, conv = _db_value(tk, v, moist_meas.get(v["step_key"], (sr.get("stream_out") or {}).get("moisture_pct")))
                if conv:
                    pr["conversion"] = conv
                if v["value_text"] and v["value"] is None:
                    pr["note"] = f"'{v['value_text']}'(불검출)라 잔차를 계산하지 않음"
                elif v["value_text"] and str(v["value_text"]).strip()[:1] in "<>≤≥":
                    pr["note"] = f"'{v['value_text']}'(검출 한계)라 잔차를 계산하지 않음"
                    pr["censored"] = True
                elif mval is not None and o["value"] is not None:
                    pr["measured_db"] = round(mval, 4) if conv else None
                    pr["residual"] = round(mval - o["value"], 4)
                    has_band = o["low"] is not None and o["high"] is not None and o["low"] != o["high"]
                    pr["within_band"] = (min(o["low"], o["high"]) <= mval <= max(o["low"], o["high"])) if has_band else None
            pairs.append(pr)
        pairs_all += pairs
        runs.append({"xrun_id": run["xrun_id"], "alias": run["alias"], "label": run["label"], "conditions": run["conditions"],
                     "pairs": pairs, "final": sim["final"],
                     "errors": [{"step": r["label"], "error": r["error"]} for r in sim["steps"] if r.get("error")]})
    summary, parity = error_summary(pairs_all)
    in_sample = exp_id in (ctx["calib"].get("experiments") or [])
    return {"experiment": {k: exp[k] for k in ("exp_id", "name", "byproduct", "confidentiality")}, "runs": runs,
            "summary": summary, "parity": parity, "evidence": evidence, "calib": {"experiments": ctx["calib"].get("experiments") or [],
                                                                                    "ea_fit": bool(ctx["calib"].get("ea_fit"))},
            "in_sample": in_sample, "notes": [IN_SAMPLE_NOTE] if in_sample else [],
            "disclaimer": P.DISCLAIMER, "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}


def error_summary(pairs: list[dict]) -> tuple[dict, dict]:
    groups: dict[str, list[dict]] = {}
    for p in pairs:
        if p.get("residual") is not None:
            groups.setdefault(p["target"], []).append(p)
    summary, parity = {}, {}
    for tk, ps in groups.items():
        res = [p["residual"] for p in ps]
        meas = [(p.get("measured_db") if p.get("measured_db") is not None else p["measured"]) for p in ps]
        n = len(res)
        mape = [abs(r) / abs(m) * 100 for r, m in zip(res, meas) if m]
        summary[tk] = {"label": S.TARGETS[tk]["label"], "unit": S.TARGETS[tk]["unit"], "n": n,
                       "mae": round(statistics.fmean(abs(r) for r in res), 4), "rmse": round(math.sqrt(statistics.fmean(r * r for r in res)), 4),
                       "bias": round(statistics.fmean(res), 4), "mape": round(statistics.fmean(mape), 2) if mape else None,
                       "within_band": sum(1 for p in ps if p.get("within_band")), "with_band": sum(1 for p in ps if p.get("within_band") is not None),
                       "note": "n ≤ 2 — 오차 요약을 믿기 어렵습니다" if n <= 2 else None}
        parity[tk] = [{"pred": p["predicted"], "meas": m, "low": p.get("low"), "high": p.get("high"), "run": p["run"],
                       "step": p["step_label"]} for p, m in zip(ps, meas)]
    return summary, parity


# ---------------------------------------------------------------- 민감도

def sensitivity(exp_id: str, step_key: str, param: str, target: str, target_step: str | None = None,
                base_run: str | None = None, n: int = 21, calib: dict | None = None, project: str | None = None,
                lo: float | None = None, hi: float | None = None) -> dict:
    t0 = time.perf_counter()
    exp = store.get_experiment(exp_id)
    steps = exp["flow"]["steps"]
    by = {s["key"]: s for s in steps}
    if step_key not in by:
        raise store.StoreError(f"'{step_key}' 단계가 흐름에 없습니다. 흐름의 단계 중에서 고르세요.")
    target_step = target_step or step_key
    if target_step not in by:
        raise store.StoreError(f"결과 단계 '{target_step}'가 흐름에 없습니다.")
    order = [s["key"] for s in steps]
    if order.index(target_step) < order.index(step_key):
        raise store.StoreError("결과 단계는 바꾸는 단계와 같거나 그 뒤여야 합니다. 결과 단계를 뒤쪽 단계로 고르세요.")
    tk = U.canon_target(target)
    if not tk:
        raise store.StoreError(f"'{target}'는 모의 결과에 없는 대상입니다. 수분·TPC·TPC 잔존율·TDF 등에서 고르세요.")
    run0 = next((r for r in exp["runs"] if r["xrun_id"] == base_run), None) if base_run else None
    base_cond = {k: dict(v) for k, v in (run0["conditions"] if run0 else {}).items()}
    st = by[step_key]
    merged = store.merged_params(st, run0)
    spec = next((s for s in S.specs_for(st["type"], merged) if s["key"] == param), None)
    if not spec or spec.get("type") != "number":
        raise store.StoreError(f"'{st['label']}' 단계의 '{param}'는 숫자 값이 아니라 훑을 수 없습니다. 숫자 조건을 고르세요.")
    a = spec["min"] if lo is None else max(spec["min"], float(lo))
    b = spec["max"] if hi is None else min(spec["max"], float(hi))
    if b <= a:
        raise store.StoreError("훑을 범위가 비어 있습니다. 최솟값을 최댓값보다 작게 넣으세요.")
    n = max(5, min(int(n), 41))
    ctx = _ctx(exp["byproduct"], project, calib)
    pts, errs = [], set()
    for i in range(n):
        x = a + (b - a) * i / (n - 1)
        cond = {k: dict(v) for k, v in base_cond.items()}
        cond.setdefault(step_key, {})[param] = x
        sim = run_flow(steps, cond, ctx=ctx, until=target_step)
        r = next((s for s in sim["steps"] if s["key"] == target_step), None)
        if r and r.get("error"):
            errs.add(r["error"])
        o = ((r or {}).get("outputs") or {}).get(tk)
        if o and o.get("value") is not None:
            pts.append([round(x, 4), o["value"], o["low"], o["high"]])
    measured = []
    for run in exp["runs"]:
        x = store.merged_params(st, run).get(param)
        if x is None:
            x = spec.get("default")
        for v in run["values"]:
            if v["kind"] == "measured" and v["step_key"] == target_step and v["target_key"] == tk and v["value"] is not None \
                    and not (v["value_text"] and str(v["value_text"])[:1] in "<>≤≥"):
                measured.append({"x": x, "y": v["value"], "label": f"{run['alias']}({run['label']}): {spec['label']} {x:g} → {v['value']:g}"})
    cur_x = merged.get(param, spec.get("default"))
    cur = None
    if cur_x is not None:
        cond = {k: dict(v) for k, v in base_cond.items()}
        sim = run_flow(steps, cond, ctx=ctx, until=target_step)
        r = next((s for s in sim["steps"] if s["key"] == target_step), None)
        o = ((r or {}).get("outputs") or {}).get(tk)
        cur = [cur_x, o["value"] if o else None]
    others = [r for r in exp["runs"] if r is not run0]
    note = "다른 조건은 " + (f"{run0['alias']}의 조건" if run0 else "흐름 기본값") + "으로 둠."
    if measured and others:
        note += " 실측 점은 런마다 다른 조건에서 잰 값이라 곡선과 조건이 다를 수 있습니다."
    return {"x_label": f"{st['label']} · {spec['label']} ({spec['unit']})", "y_label": f"{by[target_step]['label']} · {S.TARGETS[tk]['label']} ({S.TARGETS[tk]['unit']})",
            "points": pts, "measured": measured, "current": cur, "note": note, "errors": sorted(errs)[:3],
            "param": {**spec, "step_key": step_key}, "target": tk, "target_step": target_step,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}


def numeric_params(exp_id: str) -> list[dict]:
    """민감도 화면의 고를 거리: 켜진 단계의 숫자 값들"""
    exp = store.get_experiment(exp_id)
    out = []
    for st in exp["flow"]["steps"]:
        if not st.get("enabled", True):
            continue
        for s in S.specs_for(st["type"], st["params"]):
            if s.get("type") == "number" and not s.get("help", "").startswith("기록용"):
                out.append({"step_key": st["key"], "step_label": st["label"], "param": s["key"], "label": s["label"], "unit": s["unit"]})
    return out
