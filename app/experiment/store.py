"""공정 흐름(workflow.graph_json)·실험·런·값 저장.

흐름 graph_json = {"kind": "process_flow", "version": 1, "byproduct": "사과박", "description": "...",
                   "steps": [{"key": "dry1", "type": "dry", "label": "건조", "enabled": true, "params": {...}}]}
- 단계 key는 한 번 정하면 바뀌지 않는다(순서를 바꿔도 런 조건·실측값이 그 단계를 계속 가리킨다).
- 기본 틀(is_template=1)은 고치지 않는다 — 틀로 새 흐름을 만든 뒤 고친다.
- 실험마다 자기 흐름(복사본)을 가진다. 지우기는 change_log에 남긴다.
"""
from __future__ import annotations

import json
import re

from .. import db
from ..viz import predict as P
from . import calib, steps as S, units as U

KIND = "process_flow"
CONF = ("일반", "내부", "기밀")


class StoreError(ValueError):
    pass


class NotFound(LookupError):
    pass


# ---------------------------------------------------------------- 기본 틀

def _st(key, type_, params=None, label=None, enabled=True):
    return {"key": key, "type": type_, "label": label or S.DEFAULT_LABELS[type_], "enabled": enabled, "params": params or {}}


TEMPLATES = [
    {"name": "사과박 동결건조 분말", "description": "원료 → 세척 → 압착 → 분쇄 → 동결건조 → 분쇄·체분리 → 포장·저장",
     "steps": [_st("feed1", "feed", {"mass_kg": 100}), _st("wash1", "wash"), _st("press1", "press", {"target_moisture_pct": 65}),
               _st("mill1", "mill", {"particle_mm": 5}),
               _st("dry1", "dry", {"method": "동결건조", "temp_c": 20, "pressure_pa": 20, "time_h": 48, "thickness_mm": 10, "target_moisture": 5}),
               _st("sieve1", "sieve", {"mesh_um": 250}), _st("store1", "store", {"package": "방습(알루미늄)", "days": 90, "temp_c": 25, "rh": 60})]},
    {"name": "사과박 열풍건조 분말", "description": "원료 → 세척 → 압착 → 분쇄 → 열풍건조 → 분쇄·체분리 → 포장·저장",
     "steps": [_st("feed1", "feed", {"mass_kg": 100}), _st("wash1", "wash"), _st("press1", "press", {"target_moisture_pct": 65}),
               _st("mill1", "mill", {"particle_mm": 3}),
               _st("dry1", "dry", {"method": "열풍건조", "temp_c": 60, "time_h": 12, "air_velocity_ms": 0.9, "thickness_mm": 3, "target_moisture": 8}),
               _st("sieve1", "sieve", {"mesh_um": 250}), _st("store1", "store", {"package": "일반 PE", "days": 90, "temp_c": 25, "rh": 60})]},
    {"name": "사과박 열풍건조 + 에탄올 추출", "description": "원료 → 압착 → 열풍건조 → 분쇄·체분리 → 에탄올 추출",
     "steps": [_st("feed1", "feed", {"mass_kg": 100}), _st("press1", "press", {"target_moisture_pct": 65}),
               _st("dry1", "dry", {"method": "열풍건조", "temp_c": 60, "time_h": 12, "air_velocity_ms": 0.9, "thickness_mm": 3, "target_moisture": 8}),
               _st("sieve1", "sieve", {"mesh_um": 500}),
               _st("extract1", "extract", {"ethanol_pct": 60, "temp_c": 50, "time_min": 60, "ratio_ml_g": 20})]},
]


def ensure_templates() -> None:
    have = {r["name"] for r in db.rows("SELECT name, graph_json FROM workflow WHERE is_template=1")
            if _is_flow(r["graph_json"])}
    missing = [t for t in TEMPLATES if t["name"] not in have]
    if not missing:
        return
    with db.tx() as c:
        for t in missing:
            g = {"kind": KIND, "version": 1, "byproduct": P.DEFAULT_BYPRODUCT, "description": t["description"], "steps": t["steps"]}
            c.execute("INSERT INTO workflow(wf_id, name, graph_json, version, is_template) VALUES (?,?,?,1,1)",
                      (db.new_id(), t["name"], json.dumps(g, ensure_ascii=False)))


def _is_flow(graph_json: str) -> bool:
    try:
        return json.loads(graph_json or "{}").get("kind") == KIND
    except json.JSONDecodeError:
        return False


# ---------------------------------------------------------------- 흐름

def validate_steps(steps: list[dict]) -> list[dict]:
    """단계 목록을 검사하고 key·이름·기본값을 채운다."""
    if not isinstance(steps, list) or not steps:
        raise StoreError("단계가 하나도 없습니다. 맨 앞에 '원료 투입'을 넣고 단계를 추가하세요.")
    out, seen = [], set()
    counters: dict[str, int] = {}
    for st in steps:
        if not isinstance(st, dict):
            raise StoreError("단계 형식이 잘못되었습니다. {type, label, params} 모양으로 보내세요.")
        t = st.get("type")
        if t not in S.STEP_TYPES:
            raise StoreError(f"'{t}'는 없는 공정 단계입니다. {', '.join(f'{k}({v})' for k, v in S.DEFAULT_LABELS.items())} 중에서 고르세요.")
        k = str(st.get("key") or "").strip()
        if not k:
            counters[t] = counters.get(t, 0) + 1
            k = f"{t}{counters[t]}"
            while k in seen or any(x.get("key") == k for x in steps):
                counters[t] += 1
                k = f"{t}{counters[t]}"
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,31}", k):
            raise StoreError(f"단계 키 '{k}'는 쓸 수 없습니다. 영문자로 시작하는 32자 이하 영문·숫자로 정하세요.")
        if k in seen:
            raise StoreError(f"단계 키 '{k}'가 두 번 나옵니다. 키는 흐름 안에서 하나씩만 쓰세요.")
        seen.add(k)
        label = str(st.get("label") or S.DEFAULT_LABELS[t]).strip()[:40]
        params = {pk: pv for pk, pv in (st.get("params") or {}).items() if pv not in ("",)}
        try:
            S.clean_params(t, params, label)  # 범위만 확인 — 저장은 사용자가 넣은 값만
        except S.StepError as ex:
            raise StoreError(str(ex)) from ex
        spec_map = {s["key"]: s for s in S.specs_for(t, params)}
        specs = set(spec_map)
        unknown = [pk for pk in params if pk not in specs]
        if unknown:
            raise StoreError(f"'{label}' 단계에 없는 값 {', '.join(unknown)}이 있습니다. 가능한 값: {', '.join(sorted(specs))}")
        for pk, pv in list(params.items()):  # 범주(직접 입력 가능) 값은 목록 이름으로 맞춰 저장
            if spec_map.get(pk, {}).get("free"):
                cv = S.canon_choice(spec_map[pk], pv)
                if cv is None:
                    params.pop(pk)
                else:
                    params[pk] = cv
        out.append({"key": k, "type": t, "label": label, "enabled": bool(st.get("enabled", True)), "params": params})
    if out[0]["type"] != "feed":
        raise StoreError("흐름의 첫 단계는 '원료 투입'이어야 합니다. 원료 투입을 맨 앞으로 옮기세요.")
    return out


def _flow_row(wf_id: str) -> dict:
    r = db.one("SELECT * FROM workflow WHERE wf_id=?", (wf_id,))
    if not r or not _is_flow(r["graph_json"]):
        raise NotFound("공정 흐름을 찾지 못했습니다. 목록을 새로고침하세요.")
    return r


def _flow_view(r: dict) -> dict:
    g = json.loads(r["graph_json"])
    used = db.rows("SELECT exp_id, name FROM experiment WHERE wf_id=?", (r["wf_id"],))
    return {"wf_id": r["wf_id"], "name": r["name"], "version": r["version"], "is_template": bool(r["is_template"]),
            "byproduct": g.get("byproduct") or P.DEFAULT_BYPRODUCT, "description": g.get("description") or "",
            "steps": g.get("steps") or [], "experiments": used}


def list_templates() -> list[dict]:
    ensure_templates()
    return [_flow_view(r) for r in db.rows("SELECT * FROM workflow WHERE is_template=1 ORDER BY rowid") if _is_flow(r["graph_json"])]


def list_flows(include_templates: bool = False) -> list[dict]:
    ensure_templates()
    q = "SELECT * FROM workflow" + ("" if include_templates else " WHERE is_template=0") + " ORDER BY is_template DESC, rowid"
    return [_flow_view(r) for r in db.rows(q) if _is_flow(r["graph_json"])]


def get_flow(wf_id: str) -> dict:
    return _flow_view(_flow_row(wf_id))


def create_flow(name: str, template_id: str | None = None, steps: list[dict] | None = None,
                byproduct: str | None = None, description: str | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise StoreError("흐름 이름을 넣으세요. 예: '사과박 열풍건조 60 ℃ 시험'")
    if template_id:
        src = get_flow(template_id)
        steps = steps or src["steps"]
        byproduct = byproduct or src["byproduct"]
        description = description if description is not None else src["description"]
    if not steps:
        steps = [S_feed()]
    clean = validate_steps(steps)
    g = {"kind": KIND, "version": 1, "byproduct": P._canon_byproduct(byproduct), "description": description or "", "steps": clean}
    wf = db.new_id()
    with db.tx() as c:
        c.execute("INSERT INTO workflow(wf_id, name, graph_json, version, is_template) VALUES (?,?,?,1,0)",
                  (wf, name[:80], json.dumps(g, ensure_ascii=False)))
    calib.bump()
    return get_flow(wf)


def S_feed() -> dict:  # noqa: N802
    return _st("feed1", "feed", {"mass_kg": 100})


def _values_per_step(wf_id: str) -> dict[str, int]:
    rows = db.rows("SELECT v.step_key, COUNT(*) AS n FROM experiment_value v JOIN experiment_run r ON r.xrun_id=v.xrun_id "
                   "JOIN experiment e ON e.exp_id=r.exp_id WHERE e.wf_id=? AND v.kind='measured' GROUP BY v.step_key", (wf_id,))
    return {r["step_key"]: r["n"] for r in rows}


def update_flow(wf_id: str, name: str | None = None, steps: list[dict] | None = None, force: bool = False,
                byproduct: str | None = None, description: str | None = None) -> dict:
    r = _flow_row(wf_id)
    if r["is_template"]:
        raise StoreError("기본 틀은 고칠 수 없습니다. '이 틀로 새 흐름 만들기'로 복사한 뒤 고치세요.")
    g = json.loads(r["graph_json"])
    before = dict(g)
    if steps is not None:
        clean = validate_steps(steps)
        removed = {s["key"] for s in g.get("steps", [])} - {s["key"] for s in clean}
        counts = _values_per_step(wf_id)
        lost = {k: counts[k] for k in removed if counts.get(k)}
        if lost and not force:
            raise StoreError("지우려는 단계에 기록된 실측값이 있습니다(" + ", ".join(f"{k}: {n}개" for k, n in lost.items())
                             + "). 지우지 말고 '끄기'를 쓰거나, 정말 지우려면 강제(force)로 다시 보내세요.")
        g["steps"] = clean
    if byproduct is not None:
        g["byproduct"] = P._canon_byproduct(byproduct)
    if description is not None:
        g["description"] = str(description)[:400]
    nm = (name.strip()[:80] if name and name.strip() else r["name"])
    with db.tx() as c:
        c.execute("UPDATE workflow SET name=?, graph_json=?, version=version+1 WHERE wf_id=?",
                  (nm, json.dumps(g, ensure_ascii=False), wf_id))
        if steps is not None and len(before.get("steps", [])) > len(g["steps"]):
            db.log_change(c, "workflow", wf_id, before, g)
    calib.bump()
    return get_flow(wf_id)


def flow_op(wf_id: str, op: str, **kw) -> dict:
    """단계 하나 바꾸기: add(type, index?, label?, params?) · remove(key, force?) · move(key, delta | index) ·
    enable(key, enabled) · params(key, params, replace?) · rename(key, label)"""
    f = get_flow(wf_id)
    steps = [dict(s, params=dict(s["params"])) for s in f["steps"]]
    idx = {s["key"]: i for i, s in enumerate(steps)}

    def need(k):
        if k not in idx:
            raise StoreError(f"'{k}' 단계가 이 흐름에 없습니다. 흐름을 새로고침하세요.")
        return idx[k]

    force = bool(kw.get("force"))
    if op == "add":
        t = kw.get("type")
        if t not in S.STEP_TYPES:
            raise StoreError(f"'{t}'는 없는 공정 단계입니다. {', '.join(S.STEP_TYPES)} 중에서 고르세요.")
        n = 1
        while f"{t}{n}" in idx:
            n += 1
        st = _st(f"{t}{n}", t, kw.get("params") or {}, kw.get("label"))
        pos = kw.get("index")
        pos = len(steps) if pos is None else max(1 if t != "feed" else 0, min(int(pos), len(steps)))
        steps.insert(pos, st)
    elif op == "remove":
        i = need(kw.get("key"))
        steps.pop(i)
    elif op == "move":
        i = need(kw.get("key"))
        j = int(kw["index"]) if kw.get("index") is not None else i + int(kw.get("delta") or 0)
        j = max(0, min(j, len(steps) - 1))
        st = steps.pop(i)
        steps.insert(j, st)
    elif op == "enable":
        i = need(kw.get("key"))
        if steps[i]["type"] == "feed" and not kw.get("enabled", True):
            raise StoreError("원료 투입 단계는 끌 수 없습니다. 원료 값만 바꾸세요.")
        steps[i]["enabled"] = bool(kw.get("enabled", True))
    elif op == "params":
        i = need(kw.get("key"))
        new = dict(kw.get("params") or {})
        if kw.get("replace"):
            steps[i]["params"] = {k: v for k, v in new.items() if v not in (None, "")}
        else:
            for k, v in new.items():
                if v in (None, ""):
                    steps[i]["params"].pop(k, None)
                else:
                    steps[i]["params"][k] = v
        if steps[i]["type"] == "dry" and "method" in new:
            specs = {s["key"]: s for s in S.dry_specs(P.method_or_error(steps[i]["params"].get("method") or "열풍건조"))}

            def fits(k, v):  # 새 방식에 없는 값·범위 밖 값은 지워서 그 방식의 기본값을 쓰게 한다
                sp = specs.get(k)
                if not sp:
                    return False
                if sp.get("type") == "select" or k in new:
                    return True
                try:
                    return sp["min"] <= float(v) <= sp["max"]
                except (TypeError, ValueError):
                    return False
            steps[i]["params"] = {k: v for k, v in steps[i]["params"].items() if fits(k, v)}
    elif op == "rename":
        i = need(kw.get("key"))
        lab = str(kw.get("label") or "").strip()
        if not lab:
            raise StoreError("단계 이름을 넣으세요.")
        steps[i]["label"] = lab[:40]
    else:
        raise StoreError(f"'{op}'는 할 수 없는 작업입니다. add·remove·move·enable·params·rename 중 하나를 쓰세요.")
    return update_flow(wf_id, steps=steps, force=force)


def delete_flow(wf_id: str) -> None:
    r = _flow_row(wf_id)
    if r["is_template"]:
        raise StoreError("기본 틀은 지울 수 없습니다.")
    used = db.rows("SELECT name FROM experiment WHERE wf_id=?", (wf_id,))
    if used:
        raise StoreError(f"이 흐름을 쓰는 실험이 있습니다({', '.join(u['name'] for u in used)}). 실험을 먼저 지우세요.")
    with db.tx() as c:
        db.log_change(c, "workflow", wf_id, json.loads(r["graph_json"]) | {"name": r["name"]}, None)
        c.execute("DELETE FROM workflow WHERE wf_id=?", (wf_id,))
    calib.bump()


# ---------------------------------------------------------------- 실험

def _bp_id(name: str) -> str | None:
    r = db.one("SELECT b.byproduct_id FROM byproduct b JOIN concept c ON c.concept_id=b.concept_id WHERE c.pref_label_ko=?", (name,))
    return r["byproduct_id"] if r else None


def _exp_row(exp_id: str) -> dict:
    r = db.one("SELECT e.*, c.pref_label_ko AS bp_name FROM experiment e LEFT JOIN byproduct b ON b.byproduct_id=e.byproduct_id "
               "LEFT JOIN concept c ON c.concept_id=b.concept_id WHERE e.exp_id=?", (exp_id,))
    if not r:
        raise NotFound("실험을 찾지 못했습니다. 목록을 새로고침하세요.")
    return r


def _check_conf(conf: str | None) -> str:
    conf = conf or "내부"
    if conf not in CONF:
        raise StoreError("보안 등급은 일반·내부·기밀 중 하나로 고르세요.")
    return conf


def create_experiment(name: str, template_id: str | None = None, flow_id: str | None = None, byproduct: str | None = None,
                      confidentiality: str = "내부", note: str | None = None, steps: list[dict] | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise StoreError("실험 이름을 넣으세요. 예: '사과박 열풍 온도 비교 1차'")
    conf = _check_conf(confidentiality)
    ensure_templates()
    if not (template_id or flow_id or steps):
        template_id = list_templates()[0]["wf_id"]
    src = get_flow(template_id or flow_id) if (template_id or flow_id) else None
    bp = P._canon_byproduct(byproduct or (src["byproduct"] if src else None))
    flow = create_flow(name, steps=steps or (src["steps"] if src else None), byproduct=bp,
                       description=(src["description"] if src else ""))
    eid = db.new_id()
    with db.tx() as c:
        c.execute("INSERT INTO experiment(exp_id, name, wf_id, byproduct_id, confidentiality, note) VALUES (?,?,?,?,?,?)",
                  (eid, name[:80], flow["wf_id"], _bp_id(bp), conf, note))
    calib.bump()
    return get_experiment(eid)


def _exp_view(r: dict, flow: dict | None = None) -> dict:
    flow = flow or (get_flow(r["wf_id"]) if r["wf_id"] else None)
    n = db.one("SELECT COUNT(*) AS n FROM experiment_run WHERE exp_id=?", (r["exp_id"],))["n"]
    cs = P.calibration_settings(r.get("bp_name") or (flow or {}).get("byproduct"))
    return {"exp_id": r["exp_id"], "name": r["name"], "wf_id": r["wf_id"], "confidentiality": r["confidentiality"],
            "byproduct": r.get("bp_name") or (flow or {}).get("byproduct") or P.DEFAULT_BYPRODUCT,
            "note": r["note"], "created_at": r["created_at"], "n_runs": n, "plan_id": r.get("plan_id"),
            "calibration_applied": r["exp_id"] in cs["experiments"],
            "flow_name": (flow or {}).get("name")}


def list_experiments() -> list[dict]:
    rows = db.rows("SELECT e.*, c.pref_label_ko AS bp_name FROM experiment e LEFT JOIN byproduct b ON b.byproduct_id=e.byproduct_id "
                   "LEFT JOIN concept c ON c.concept_id=b.concept_id ORDER BY e.created_at DESC, e.rowid DESC")
    return [_exp_view(r) for r in rows]


def get_experiment(exp_id: str, with_runs: bool = True) -> dict:
    r = _exp_row(exp_id)
    flow = get_flow(r["wf_id"])
    out = _exp_view(r, flow)
    out["flow"] = flow
    if with_runs:
        out["runs"] = list_runs(exp_id)
    return out


def update_experiment(exp_id: str, name: str | None = None, confidentiality: str | None = None, note: str | None = None,
                      byproduct: str | None = None) -> dict:
    r = _exp_row(exp_id)
    sets, vals = [], []
    if name is not None:
        if not name.strip():
            raise StoreError("실험 이름을 비울 수 없습니다.")
        sets.append("name=?")
        vals.append(name.strip()[:80])
    if confidentiality is not None:
        sets.append("confidentiality=?")
        vals.append(_check_conf(confidentiality))
    if note is not None:
        sets.append("note=?")
        vals.append(note)
    if byproduct is not None:
        bp = P._canon_byproduct(byproduct)
        sets.append("byproduct_id=?")
        vals.append(_bp_id(bp))
        update_flow(r["wf_id"], byproduct=bp)
    if sets:
        with db.tx() as c:
            c.execute(f"UPDATE experiment SET {', '.join(sets)} WHERE exp_id=?", (*vals, exp_id))
    calib.bump()
    return get_experiment(exp_id)


def delete_experiment(exp_id: str) -> None:
    exp = get_experiment(exp_id)
    with db.tx() as c:
        db.log_change(c, "experiment", exp_id, {"name": exp["name"], "runs": len(exp["runs"]), "flow": exp["flow"]["name"]}, None)
        c.execute("DELETE FROM experiment WHERE exp_id=?", (exp_id,))
        others = c.execute("SELECT COUNT(*) FROM experiment WHERE wf_id=?", (exp["wf_id"],)).fetchone()[0]
        if not others and not exp["flow"]["is_template"]:
            c.execute("DELETE FROM workflow WHERE wf_id=?", (exp["wf_id"],))
    cs = P.calibration_settings(exp["byproduct"])
    if exp_id in cs["experiments"]:
        P.save_calibration(exp["byproduct"], [x for x in cs["experiments"] if x != exp_id], cs["ea_fit"])
    calib.bump()


# ---------------------------------------------------------------- 런·값

def _flow_steps(exp_id: str) -> dict[str, dict]:
    return {s["key"]: s for s in get_experiment(exp_id, with_runs=False)["flow"]["steps"]}


def clean_conditions(steps: dict[str, dict], conditions: dict | None) -> dict:
    """{step_key: {param: value}} — 흐름에 있는 단계·값만, 범위 확인(합친 값으로)."""
    out = {}
    for k, cond in (conditions or {}).items():
        if not cond:
            continue
        if k not in steps:
            raise StoreError(f"조건의 단계 '{k}'가 흐름에 없습니다. 흐름의 단계 키({', '.join(steps)}) 중 하나를 쓰세요.")
        st = steps[k]
        cond = {pk: pv for pk, pv in cond.items() if pv not in (None, "")}
        merged = {**st["params"], **cond}
        specs = {s["key"]: s for s in S.specs_for(st["type"], merged)}
        bad = [pk for pk in cond if pk not in specs]
        if bad:
            raise StoreError(f"'{st['label']}' 단계에 없는 조건 {', '.join(bad)}입니다. 가능한 조건: {', '.join(specs)}")
        try:
            S.clean_params(st["type"], merged, st["label"])
        except S.StepError as ex:
            raise StoreError(str(ex)) from ex
        out[k] = {pk: (S.canon_choice(specs[pk], pv) if specs[pk].get("free") else pv if specs[pk].get("type") == "select" else float(pv))
                  for pk, pv in cond.items()}
        out[k] = {pk: pv for pk, pv in out[k].items() if pv is not None}
    return out


def clean_values(steps: dict[str, dict], values: list[dict] | None) -> list[dict]:
    """[{step_key, target, value | value_text, unit, basis}] → 표준 단위로 바꾼 행."""
    out = []
    for v in values or []:
        sk = v.get("step_key") or None
        if sk is not None and sk not in steps:
            raise StoreError(f"값의 단계 '{sk}'가 흐름에 없습니다. 흐름의 단계 키({', '.join(steps)}) 중 하나를 쓰세요.")
        tgt_raw = str(v.get("target") or v.get("target_text") or "").strip()
        if not tgt_raw:
            raise StoreError("값의 대상(수분·TPC 등)을 넣으세요.")
        tk = U.canon_target(tgt_raw)
        raw = v.get("value_text") if v.get("value") in (None, "") else v.get("value")
        value, text, kind = U.parse_cell(raw)
        if kind is None:
            continue
        if kind == "text":
            raise StoreError(f"'{tgt_raw}' 값 '{text}'를 숫자로 읽지 못했습니다. 숫자, ND(불검출), '< 0.01' 같은 형식으로 넣으세요.")
        unit = v.get("unit") or v.get("unit_text")
        basis = v.get("basis") or U.basis_of(unit) or (("건량" if tk in ("tpc", "tdf") else "습량" if tk == "moisture" else None))
        note = None
        if tk:
            try:
                value, note = U.normalize(tk, value, unit)
            except ValueError as ex:
                raise StoreError(f"'{tgt_raw}': {ex}") from ex
            unit = S.TARGETS[tk]["unit"].replace(" 건량", "").replace(" 습량", "") if tk in ("tpc", "tdf", "moisture") else S.TARGETS[tk]["unit"]
        if value is not None:
            value = float(f"{value:.6g}")
        if note and kind == "censored" and value is not None:  # '< 450 mg/100 g' → '< 4.5'(표준 단위)
            m = re.match(r"^\s*([<>≤≥])", str(raw))
            sfx = re.search(r"(미만|이하|초과|이상)\s*$", str(raw))
            text = f"{m.group(1)} {value:g}" if m else f"{value:g} {sfx.group(1)}" if sfx else text
        elif note and text is None:
            text = f"{raw} {v.get('unit') or ''}".strip()
        out.append({"step_key": sk, "target_text": S.TARGETS[tk]["label"] if tk else tgt_raw[:60], "value": value,
                    "value_text": text, "unit_text": unit, "basis": basis, "target_key": tk})
    return out


def _run_view(r: dict, ordinal: int, vals: list[dict]) -> dict:
    return {"xrun_id": r["xrun_id"], "label": r["label"], "alias": f"런 {ordinal}", "ordinal": ordinal,
            "conditions": json.loads(r["conditions_json"] or "{}"), "run_date": r["run_date"], "note": r["note"],
            "values": [{"xval_id": v["xval_id"], "step_key": v["step_key"], "target": v["target_text"],
                        "target_key": U.canon_target(v["target_text"]), "value": v["value"], "value_text": v["value_text"],
                        "unit": v["unit_text"], "basis": v["basis"], "kind": v["kind"]} for v in vals]}


def list_runs(exp_id: str, kind: str | None = None) -> list[dict]:
    runs = db.rows("SELECT * FROM experiment_run WHERE exp_id=? ORDER BY created_at, rowid", (exp_id,))
    q = "SELECT * FROM experiment_value WHERE xrun_id IN (SELECT xrun_id FROM experiment_run WHERE exp_id=?)"
    params: list = [exp_id]
    if kind:
        q += " AND kind=?"
        params.append(kind)
    allv: dict[str, list] = {}
    for v in db.rows(q + " ORDER BY rowid", params):
        allv.setdefault(v["xrun_id"], []).append(v)
    return [_run_view(r, i + 1, allv.get(r["xrun_id"], [])) for i, r in enumerate(runs)]


def get_run(xrun_id: str) -> dict:
    r = db.one("SELECT * FROM experiment_run WHERE xrun_id=?", (xrun_id,))
    if not r:
        raise NotFound("런을 찾지 못했습니다. 실험을 새로고침하세요.")
    for x in list_runs(r["exp_id"]):
        if x["xrun_id"] == xrun_id:
            return {**x, "exp_id": r["exp_id"]}
    raise NotFound("런을 찾지 못했습니다.")


def add_run(exp_id: str, label: str | None = None, conditions: dict | None = None, run_date: str | None = None,
            note: str | None = None, values: list[dict] | None = None) -> dict:
    steps = _flow_steps(exp_id)
    cond = clean_conditions(steps, conditions)
    vals = clean_values(steps, values)
    rid = db.new_id()
    if not label:
        n = db.one("SELECT COUNT(*) AS n FROM experiment_run WHERE exp_id=?", (exp_id,))["n"]
        label = f"런 {n + 1}"
    with db.tx() as c:
        c.execute("INSERT INTO experiment_run(xrun_id, exp_id, label, conditions_json, run_date, note) VALUES (?,?,?,?,?,?)",
                  (rid, exp_id, str(label)[:60], json.dumps(cond, ensure_ascii=False), run_date, note))
        _insert_values(c, rid, vals, "measured")
    calib.bump()
    return get_run(rid)


def _insert_values(c, rid: str, vals: list[dict], kind: str) -> None:
    for v in vals:
        c.execute("INSERT INTO experiment_value(xval_id, xrun_id, step_key, target_text, value, value_text, unit_text, basis, kind) "
                  "VALUES (?,?,?,?,?,?,?,?,?)", (db.new_id(), rid, v["step_key"], v["target_text"], v["value"], v["value_text"],
                                                 v["unit_text"], v["basis"], kind))


def update_run(xrun_id: str, label: str | None = None, conditions: dict | None = None, run_date: str | None = None,
               note: str | None = None, values: list[dict] | None = None) -> dict:
    run = get_run(xrun_id)
    steps = _flow_steps(run["exp_id"])
    sets, params = [], []
    if label is not None:
        sets.append("label=?")
        params.append(str(label)[:60])
    if conditions is not None:
        sets.append("conditions_json=?")
        params.append(json.dumps(clean_conditions(steps, conditions), ensure_ascii=False))
    if run_date is not None:
        sets.append("run_date=?")
        params.append(run_date or None)
    if note is not None:
        sets.append("note=?")
        params.append(note)
    vals = clean_values(steps, values) if values is not None else None
    with db.tx() as c:
        if sets:
            c.execute(f"UPDATE experiment_run SET {', '.join(sets)} WHERE xrun_id=?", (*params, xrun_id))
        if vals is not None:
            c.execute("DELETE FROM experiment_value WHERE xrun_id=? AND kind='measured'", (xrun_id,))
            _insert_values(c, xrun_id, vals, "measured")
    calib.bump()
    return get_run(xrun_id)


def delete_run(xrun_id: str) -> None:
    run = get_run(xrun_id)
    with db.tx() as c:
        db.log_change(c, "experiment_run", xrun_id, {k: run[k] for k in ("label", "conditions", "run_date", "note", "values")}, None)
        c.execute("DELETE FROM experiment_run WHERE xrun_id=?", (xrun_id,))
    calib.bump()


def save_predicted(xrun_id: str, values: list[dict]) -> int:
    """비교 결과의 예측값을 kind='predicted'로 남긴다(이전 예측은 지움). 보정에는 쓰지 않는다."""
    get_run(xrun_id)
    with db.tx() as c:
        c.execute("DELETE FROM experiment_value WHERE xrun_id=? AND kind='predicted'", (xrun_id,))
        _insert_values(c, xrun_id, [{"step_key": v["step_key"], "target_text": v["target_text"], "value": v["value"],
                                     "value_text": v.get("value_text"), "unit_text": v.get("unit_text"), "basis": v.get("basis")}
                                    for v in values], "predicted")
    return len(values)


def merged_params(step: dict, run: dict | None) -> dict:
    return {**step["params"], **((run or {}).get("conditions", {}).get(step["key"]) or {})}
