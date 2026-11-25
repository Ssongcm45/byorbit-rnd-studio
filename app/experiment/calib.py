"""내 실험 실측을 건조 예측(app/viz/predict.py)의 보정 근거로 쓰기.

- 건조 단계(흐름의 첫 번째 켜진 건조 단계)의 조건과, 그 앞뒤에서 잰 수분·TPC로 '시료'를 만든다.
  이름은 '실험 <이름> · 런 n' — 런 이름(사용자가 붙인 라벨)·로트·공급처·시료번호는 쓰지 않는다.
- 건조 전 수분: 건조 앞 단계에서 잰 수분 → 런 조건으로 넣은 원료 수분·압착 후 수분을 앞 단계 모델로 이은 값 순서.
  둘 다 없으면 그 런은 건조 속도 보정에 쓰지 않는다(뒷받침할 자료가 없음).
- 보정은 사용자가 '보정에 적용'한 실험만 쓴다(config/calibration.json). 적용 전후는 preview()로 보인다.
"""
from __future__ import annotations

import threading

from ..viz import predict as P

_gen = {"n": 0}
_lock = threading.Lock()


def generation() -> int:
    return _gen["n"]


def bump() -> None:
    """실험·런·값·흐름이 바뀌면 predict.measured()의 캐시를 무효로 만든다."""
    with _lock:
        _gen["n"] += 1


def _vals(run: dict) -> dict[tuple, dict]:
    return {(v["step_key"], v["target_key"]): v for v in run["values"]
            if v["kind"] == "measured" and v["target_key"] and v["value"] is not None
            and not (v["value_text"] and str(v["value_text"]).strip()[:1] in "<>≤≥")}


def _to_db(v: dict, moist: float | None) -> float | None:
    if v.get("basis") == "습량":
        return None if moist is None else v["value"] / (1 - moist / 100)
    return v["value"]


def run_samples(exp: dict) -> tuple[list[dict], list[dict]]:
    """→ (시료 목록, 못 쓴 런과 이유)"""
    from . import steps as S, store
    flow = [s for s in exp["flow"]["steps"] if s.get("enabled", True)]
    dry_i = next((i for i, s in enumerate(flow) if s["type"] == "dry"), None)
    out, skipped = [], []
    if dry_i is None:
        return [], [{"run": "전체", "reason": "흐름에 켜진 건조 단계가 없습니다."}]
    dry = flow[dry_i]
    before = flow[:dry_i]
    for run in exp["runs"]:
        alias = f"실험 {exp['name']} · {run['alias']}"
        vals = _vals(run)
        try:
            p = S.clean_params("dry", store.merged_params(dry, run), dry["label"])
        except S.StepError as ex:
            skipped.append({"run": run["alias"], "reason": str(ex)})
            continue
        s = {"alias": alias, "source": "experiment", "exp_id": exp["exp_id"], "xrun_id": run["xrun_id"], "method": p["method"],
             "temp_c": p.get("temp_c"), "time_h": p.get("time_h"), "pressure_pa": p.get("pressure_pa"),
             "thickness_mm": p.get("thickness_mm"), "air_velocity_ms": p.get("air_velocity_ms")}
        # 건조 전 수분·TPC: 앞 단계 실측 → 런·흐름에 넣은 원료 값을 앞 단계 모델로 이음
        m_in = t_in = None
        src_m = src_t = None
        stop_m = stop_t = False
        for st in reversed(before):  # 가장 가까운 앞 단계 실측. 그 사이에 수분·성분을 바꾸는 단계가 있으면 그 실측은 못 쓴다
            if not stop_m and m_in is None and (st["key"], "moisture") in vals:
                m_in, src_m = vals[(st["key"], "moisture")]["value"], f"{st['label']} 실측"
            if not stop_t and t_in is None and (st["key"], "tpc") in vals:
                mv = vals.get((st["key"], "moisture"), {}).get("value")
                t_in = _to_db(vals[(st["key"], "tpc")], mv)
                src_t = f"{st['label']} 실측" if t_in is not None else None
            if st["type"] not in TRANSPARENT:
                stop_m = stop_m or m_in is None
                stop_t = stop_t or t_in is None
        if (m_in is None or t_in is None) and before:
            feed = store.merged_params(before[0], run)
            if feed.get("moisture_pct") is not None or feed.get("tpc_mg_g") is not None:
                stream = None
                try:
                    for st in before:
                        stream = S.simulate_step(st["type"], stream, S.clean_params(st["type"], store.merged_params(st, run), st["label"]),
                                                 {"meas": {}, "byproduct": exp["byproduct"]})["stream"]
                        if st["type"] == "mill" and stream.get("particle_mm") and p.get("thickness_source") == "분쇄 입자 크기":
                            s["thickness_mm"] = stream["particle_mm"]
                except S.StepError:
                    stream = None
                if stream is not None:
                    if m_in is None and feed.get("moisture_pct") is not None:
                        m_in, src_m = round(stream["moisture_pct"], 3), "원료 수분 + 앞 단계 모델"
                    if t_in is None and feed.get("tpc_mg_g") is not None:
                        t_in, src_t = S.conc(stream, "tpc"), "원료 TPC + 앞 단계 모델"
        dv = {k[1]: v for k, v in vals.items() if k[0] == dry["key"]}
        mf = dv.get("moisture", {}).get("value")
        if mf is not None:
            s["moist_final"] = mf
        if m_in is not None:
            s["moist_init"] = m_in
            s["init_from"] = src_m
        if "tpc" in dv:
            tv = _to_db(dv["tpc"], mf)
            if tv is not None:
                s["tpc"] = tv
                if t_in:
                    s["tpc_in"] = round(t_in, 4)
                    s["tpc_ret"] = tv / t_in
                    s["tpc_from"] = src_t
        if "tdf" in dv:
            td = _to_db(dv["tdf"], mf)
            if td is not None:
                s["tdf"] = td
        reasons = []
        if mf is None:
            reasons.append("건조 단계 수분 실측 없음")
        elif m_in is None:
            reasons.append("건조 전 수분을 알 수 없음(앞 단계 수분 실측이나 원료 수분 조건이 필요)")
        if "tpc" not in dv:
            reasons.append("건조 단계 TPC 실측 없음")
        if p["method"] != "열풍건조":
            reasons.append(f"{p['method']} — 속도 보정은 열풍건조만(동결건조 TPC는 기준값으로 씀)")
        s["usable"] = {"dry": p["method"] == "열풍건조" and mf is not None and m_in is not None,
                       "tpc": p["method"] == "열풍건조" and s.get("tpc") is not None,
                       "tpc_ref": p["method"] == "동결건조" and s.get("tpc") is not None}
        s["reasons"] = reasons
        out.append(s)
    return out, skipped


def drying_samples(byproduct: str | None, exp_ids) -> list[dict]:
    """predict.measured()가 부른다 — 이 부산물의, 보정에 적용한 실험의 런들."""
    from . import store
    bp = P._canon_byproduct(byproduct)
    out = []
    for eid in exp_ids or ():
        try:
            exp = store.get_experiment(eid)
        except store.NotFound:
            continue
        if exp["byproduct"] != bp:
            continue
        samples, _ = run_samples(exp)
        out += [{k: v for k, v in s.items() if k not in ("usable", "reasons")} for s in samples]
    return out


TRANSPARENT = {"mill", "sieve"}  # 수분·성분 농도를 바꾸지 않는 단계


def _cal_view(cal: dict | None) -> dict | None:
    if not cal:
        return None
    keep = ("applied", "factor", "n", "n_exp", "n_coa", "confidence", "message", "how", "rmse_ln", "points", "ref")
    v = {k: cal.get(k) for k in keep if k in cal}
    ea = cal.get("ea") or {}
    v["ea"] = {k: ea.get(k) for k in ("available", "applied", "n_temps", "temps", "ea_kj", "ea_lit_kj", "rmse_ln", "plausible", "message")}
    return v


def _drying_summary(cmp: dict, dry_key: str | None) -> dict:
    from . import sim
    return sim.error_summary([p for r in cmp["runs"] for p in r["pairs"] if dry_key is None or p["step_key"] == dry_key])[0]


def preview(exp_id: str, use_ea_fit: bool = False) -> dict:
    """이 실험을 보정에 넣기 전(지금 저장된 설정에서 이 실험을 뺀 것)과 넣은 뒤를 나란히 계산한다. 저장하지 않는다."""
    from . import sim, store
    exp = store.get_experiment(exp_id)
    bp = exp["byproduct"]
    saved = P.calibration_settings(bp)
    others = [x for x in saved["experiments"] if x != exp_id]
    before_cfg = {"experiments": others, "ea_fit": saved["ea_fit"] and bool(others)}
    after_cfg = {"experiments": others + [exp_id], "ea_fit": bool(use_ea_fit)}
    cb, ca = P.context(bp, None, before_cfg), P.context(bp, None, after_cfg)
    samples, skipped = run_samples(exp)
    dry = next((s for s in exp["flow"]["steps"] if s.get("enabled", True) and s["type"] == "dry"), None)
    cmp_b, cmp_a = sim.compare(exp_id, before_cfg), sim.compare(exp_id, after_cfg)
    dk = dry["key"] if dry else None
    n_dry = sum(1 for s in samples if s["usable"]["dry"])
    n_tpc = sum(1 for s in samples if s["usable"]["tpc"])
    temps = sorted({s["temp_c"] for s in samples if s["usable"]["dry"] and s.get("temp_c") is not None})
    lit_cfg = {"experiments": [], "ea_fit": False}
    cl = P.context(bp, None, lit_cfg)
    return {
        "experiment": {k: exp[k] for k in ("exp_id", "name", "byproduct", "confidentiality")},
        "applied": exp_id in saved["experiments"], "saved": saved,
        "literature_only": {"note": "문헌 맞춤값(보정 없음). 각 점의 'lit' 값이 이것이다.",
                            "dry_ea_kj": round(P.dry_fit()["ea_j"] / 1000, 2), "tpc_ea_kj": round(P.tpc_fit()["ea_j"] / 1000, 2),
                            "coa_dry": _cal_view(cl["dry_cal"]), "coa_tpc": _cal_view(cl["tpc_cal"])},
        "before": {"config": before_cfg, "dry": _cal_view(cb["dry_cal"]), "tpc": _cal_view(cb["tpc_cal"]),
                   "summary": _drying_summary(cmp_b, dk)},
        "after": {"config": after_cfg, "dry": _cal_view(ca["dry_cal"]), "tpc": _cal_view(ca["tpc_cal"]),
                  "summary": _drying_summary(cmp_a, dk)},
        "runs": [{"alias": s["alias"].split(" · ")[-1], "method": s["method"], "temp_c": s.get("temp_c"), "time_h": s.get("time_h"),
                  "moist_init": s.get("moist_init"), "init_from": s.get("init_from"), "moist_final": s.get("moist_final"),
                  "tpc": s.get("tpc"), "tpc_in": s.get("tpc_in"), "tpc_from": s.get("tpc_from"), "usable": s["usable"], "reasons": s["reasons"]}
                 for s in samples],
        "skipped": skipped, "n_usable": {"dry": n_dry, "tpc": n_tpc}, "distinct_temps": temps,
        "ea_possible": len(temps) >= 3,
        "rules": ["보정은 '보정에 적용'을 눌러야 저장되고, 건조 방식 탭의 예측에도 같은 보정이 쓰입니다.",
                  "건조 속도와 TPC는 열풍건조 런만 보정합니다(다른 방식은 문헌·가정 그대로).",
                  "배율은 기하평균. Ea는 서로 다른 온도가 3개 이상이고 'Ea도 맞춤'을 고를 때만 바꿉니다.",
                  "n ≤ 2이면 '보정 신뢰도 낮음'으로 표시하고 불확실 폭을 ×1.5, 그 밖에는 max(×1.2, e^RMSE) 넓힙니다.",
                  sim.IN_SAMPLE_NOTE],
    }


def apply(exp_id: str, include: bool = True, use_ea_fit: bool = False) -> dict:
    from . import store
    exp = store.get_experiment(exp_id)
    bp = exp["byproduct"]
    saved = P.calibration_settings(bp)
    lst = [x for x in saved["experiments"] if x != exp_id] + ([exp_id] if include else [])
    if include:
        samples, _ = run_samples(exp)
        if not any(s["usable"]["dry"] or s["usable"]["tpc"] or s["usable"]["tpc_ref"] for s in samples):
            from .store import StoreError
            raise StoreError("이 실험에는 보정에 쓸 수 있는 런이 없습니다. 건조 단계의 수분(또는 TPC) 실측과 "
                             "건조 전 수분(앞 단계 실측 또는 원료 수분 조건)을 넣으세요.")
    ea = bool(use_ea_fit) if include else (saved["ea_fit"] and bool(lst))
    P.save_calibration(bp, lst, ea)
    bump()
    return {"applied": include, "settings": P.calibration_settings(bp), "preview": preview(exp_id, ea)}
