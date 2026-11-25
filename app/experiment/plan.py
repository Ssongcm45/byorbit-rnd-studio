"""다음 실험 조건 제안 — 예측의 불확실성을 줄이는 쪽으로.

1) 빈 온도 채우기: 근거 범위 안에서 지금 런들의 온도와 가장 먼 온도(Ea를 맞추려면 서로 다른 온도 3개 이상).
2) 2–3 수준 요인 배치: 온도 3수준 × 시간 2수준(건조), 에탄올 3수준 × 온도 2수준(추출).
각 조건의 예측값·불확실 폭을 함께 보인다. 제안일 뿐이다 — 실제 계획은 직접 판단한다.
"""
from __future__ import annotations

import json

from .. import db
from ..viz import predict as P
from . import sim, steps as S, store

DISCLAIMER = "제안입니다 — 모델의 불확실 폭과 지금까지의 런 조건만 보고 고른 조건이라, 설비·원료·안전 조건은 직접 확인하세요."


def _validity(method: str) -> tuple[list[float], str]:
    spec = next(s for s in P.INPUTS[method] if s["key"] == "temp_c")
    if method in ("열풍건조", "진공건조", "자연건조"):
        v = P.evidence("ha_time_table")["validity"]["temp_c"]
        return [max(v[0], spec["min"]), min(v[1], spec["max"])], "Llavata 2022 표 1의 온도 범위(문헌)"
    if method == "동결건조":
        v = P.evidence("a_fd_secondary")["validity"]["temp_c"]
        return [max(v[0], spec["min"]), min(v[1], spec["max"])], "2차 건조 가정의 온도 범위"
    return [spec["min"], spec["max"]], "입력 범위"


def _predict_point(exp: dict, steps: list[dict], step_key: str, cond: dict, ctx: dict) -> dict:
    r = sim.run_flow(steps, cond, ctx=ctx, until=step_key)
    st = next(s for s in r["steps"] if s["key"] == step_key)
    o = st.get("outputs") or {}

    def g(k):
        x = o.get(k)
        return None if not x else {"value": x["value"], "low": x["low"], "high": x["high"], "unit": x["unit"]}
    return {"moisture": g("moisture"), "tpc_ret": g("tpc_ret"), "time_target": g("time_target"),
            "tpc_extract_yield": g("tpc_extract_yield"), "error": st.get("error")}


def _width(p: dict | None) -> float:
    if not p or p.get("low") is None or p.get("high") is None:
        return 0.0
    return abs(p["high"] - p["low"])


def suggest(exp_id: str, max_new: int = 3) -> dict:
    exp = store.get_experiment(exp_id)
    steps = exp["flow"]["steps"]
    ctx = sim._ctx(exp["byproduct"], None, None)
    out = {"label": "제안", "disclaimer": DISCLAIMER, "gap_fill": [], "factorial": [], "notes": []}
    dry = next((s for s in steps if s["type"] == "dry" and s.get("enabled", True)), None)
    if dry:
        method = S.clean_params("dry", dry["params"])["method"]
        runs_m = []
        for r in exp["runs"]:
            p = S.clean_params("dry", store.merged_params(dry, r))
            if p["method"] == method:
                runs_m.append(p)
        base = S.clean_params("dry", dry["params"])
        rng, why = _validity(method)
        covered = sorted({round(p["temp_c"], 1) for p in runs_m})
        grid = [rng[0] + i * 5 for i in range(int((rng[1] - rng[0]) // 5) + 1)]
        cands = []
        for t in grid:
            dist = min((abs(t - c) for c in covered), default=999.0)
            if dist < 7.5:
                continue
            cond = {dry["key"]: {"temp_c": t}}
            pr = _predict_point(exp, steps, dry["key"], cond, ctx)
            score = min(dist, 60) * (1 + _width(pr["moisture"]) / 10 + _width(pr["tpc_ret"]) / 20)
            cands.append({"conditions": {dry["key"]: {"temp_c": t, "time_h": base.get("time_h")}}, "temp_c": t, "distance": dist,
                          "predicted": pr, "score": round(score, 3)})
        picked = []
        for c in sorted(cands, key=lambda c: -c["score"]):
            if all(abs(c["temp_c"] - p["temp_c"]) >= 10 for p in picked):
                picked.append(c)
            if len(picked) >= max_new:
                break
        need = max(0, 3 - len(covered))
        for c in sorted(picked, key=lambda c: c["temp_c"]):
            c["why"] = (f"지금 런 온도({', '.join(f'{x:g}' for x in covered) or '없음'} ℃)에서 {c['distance']:g} ℃ 떨어진 빈 곳"
                        + (", 예측 폭이 넓음" if _width(c["predicted"]["moisture"]) > 3 else ""))
            out["gap_fill"].append(c)
        out["validity"] = {"method": method, "temp_range": rng, "source": why, "covered_temps": covered}
        if method == "열풍건조":
            out["notes"].append(f"서로 다른 온도 {len(covered)}개 — " + (f"{need}개 더 있으면 Ea(활성화 에너지)도 내 자료로 맞출 수 있습니다." if need
                                                                     else "Ea를 내 자료로 맞출 수 있습니다(보정 화면)."))
        else:
            out["notes"].append(f"{method}는 속도 보정을 하지 않습니다(열풍건조만). 런은 예측 대 실측 비교에 쓰입니다.")
        # 요인 배치: 온도 3 × 시간 2
        t0 = base["temp_c"]
        temps = sorted({min(max(round((t0 + d) / 5) * 5, rng[0]), rng[1]) for d in (-15, 0, 15)})
        if "time_h" in base:
            pr0 = _predict_point(exp, steps, dry["key"], {}, ctx)
            tt = (pr0.get("time_target") or {}).get("value") or base["time_h"]
            spec = next(s for s in P.INPUTS[method] if s["key"] == "time_h")
            times = sorted({min(max(round(tt * f * 2) / 2, spec["min"]), spec["max"]) for f in (0.75, 1.25)})
            rows = []
            for t in temps:
                for h in times:
                    cond = {dry["key"]: {"temp_c": t, "time_h": h}}
                    pr = _predict_point(exp, steps, dry["key"], cond, ctx)
                    done = any(abs(p["temp_c"] - t) <= 2 and abs(p.get("time_h", 0) - h) <= 0.1 * h for p in runs_m)
                    rows.append({"conditions": cond, "temp_c": t, "time_h": h, "predicted": pr, "done": done})
            out["factorial"].append({"step_key": dry["key"], "step_label": dry["label"], "design": f"{len(temps)}×{len(times)} 요인 배치(온도 × 시간)",
                                     "factors": [{"key": "temp_c", "label": "온도", "unit": "℃", "levels": temps},
                                                 {"key": "time_h", "label": "시간", "unit": "h", "levels": times}],
                                     "rows": rows, "why": "시간 수준은 목표 수분 도달 예상 시간의 0.75·1.25배 — 목표 전후를 함께 잰다."})
    ext = next((s for s in steps if s["type"] == "extract" and s.get("enabled", True)), None)
    if ext:
        rows = []
        for c in (40, 60, 80):
            for t in (40, 60):
                cond = {ext["key"]: {"ethanol_pct": c, "temp_c": t}}
                pr = _predict_point(exp, steps, ext["key"], cond, ctx)
                rows.append({"conditions": cond, "ethanol_pct": c, "temp_c": t, "predicted": pr, "done": False})
        out["factorial"].append({"step_key": ext["key"], "step_label": ext["label"], "design": "3×2 요인 배치(에탄올 × 온도)",
                                 "factors": [{"key": "ethanol_pct", "label": "에탄올", "unit": "% v/v", "levels": [40, 60, 80]},
                                             {"key": "temp_c", "label": "추출 온도", "unit": "℃", "levels": [40, 60]}],
                                 "rows": rows, "why": "추출 계수가 모두 가정이라 실측이 가장 필요한 곳입니다."})
    if not dry and not ext:
        out["notes"].append("건조·추출 단계가 없어 제안할 조건이 없습니다.")
    return out


def save_plan(exp_id: str, design: dict) -> dict:
    """제안(요인 배치 하나)을 experiment_plan으로 남기고 실험에 잇는다."""
    exp = store.get_experiment(exp_id, with_runs=False)
    if not design or not design.get("factors"):
        raise store.StoreError("저장할 계획(요인과 수준)이 없습니다. 제안 목록에서 배치를 고르세요.")
    pid = db.new_id()
    with db.tx() as c:
        c.execute("INSERT INTO experiment_plan(exp_id, design_type, factors_json, responses_json, status) VALUES (?,?,?,?,?)",
                  (pid, design.get("design") or "제안", json.dumps({"step_key": design.get("step_key"), "factors": design["factors"],
                                                                    "rows": [r.get("conditions") for r in design.get("rows", [])]}, ensure_ascii=False),
                   json.dumps(["수분", "TPC 잔존율"], ensure_ascii=False), "제안"))
        c.execute("UPDATE experiment SET plan_id=? WHERE exp_id=?", (pid, exp_id))
    return {"plan_id": pid, "experiment": exp["name"], "design": design.get("design")}


def add_planned_runs(exp_id: str, design: dict) -> list[dict]:
    """요인 배치의 조건으로 빈 런(실측 없음)을 만든다 — 실험하면서 값을 채운다."""
    made = []
    for i, r in enumerate(design.get("rows") or []):
        if r.get("done"):
            continue
        cond = r.get("conditions") or {}
        lab = "계획 " + ", ".join(f"{v:g}" for c in cond.values() for v in c.values() if isinstance(v, (int, float)))
        made.append(store.add_run(exp_id, label=lab[:60], conditions=cond, note="제안된 조건(계획) — 실측을 채우세요"))
    return made
