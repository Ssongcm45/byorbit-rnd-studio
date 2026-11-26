"""CSV·XLSX 가져오기(열 대응 미리보기 → 확정) / CSV 내보내기.

- 올린 파일은 메모리에만 잠시 둔다(받은편지함·자료함에 넣지 않는다 → 기밀 실험 자료가 다른 경로로 새지 않음).
- 열 이름으로 역할을 짐작한다: 런 이름·날짜·비고 / 조건(건조 온도·시간 …) / 실측값(수분·TPC·TDF·수율 …).
  '[dry1] 수분 (%)'처럼 대괄호에 단계 키를 쓰면 그 단계로 바로 간다(내보내기 형식과 같다).
- 값: 숫자, ND·불검출(값 없음), '< 0.01'·'0.01 미만'(검출 한계 — 값은 0.01, 글자 보존, 잔차 계산에서 뺌).
- 단위: 열 이름 괄호 속 단위를 읽어 표준 단위로 바꾼다(mg GAE/100 g → mg GAE/g, min → h 등).
"""
from __future__ import annotations

import csv
import io
import re
import threading
import time
from datetime import date, datetime

from ..ingest import coa
from ..viz import drying
from . import steps as S, store, units as U

MAX_BYTES = 5 * 1024 * 1024
_uploads: dict[str, dict] = {}
_lock = threading.Lock()
TTL_S = 3600


class ImportError_(ValueError):  # noqa: N801 — 내장 ImportError와 구분
    pass


# ---------------------------------------------------------------- 파일 읽기

def read_grid(file_name: str, content: bytes) -> list[list]:
    if not content:
        raise ImportError_("빈 파일입니다. 표가 들어 있는 CSV나 XLSX 파일을 올리세요.")
    if len(content) > MAX_BYTES:
        raise ImportError_("파일이 5 MB보다 큽니다. 필요한 열만 남겨 다시 올리세요.")
    name = (file_name or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
        except Exception as ex:  # noqa: BLE001
            raise ImportError_("XLSX를 열지 못했습니다. 엑셀에서 다시 저장하거나 CSV(UTF-8)로 내보내 올리세요.") from ex
        try:
            for ws in wb.worksheets:
                grid = [list(r) for r in ws.iter_rows(values_only=True)]
                grid = [r for r in grid if any(c not in (None, "") for c in r)]
                if len(grid) >= 2:
                    return grid
        finally:
            wb.close()
        raise ImportError_("XLSX에 머리글과 데이터 행이 있는 시트가 없습니다. 첫 줄에 열 이름, 둘째 줄부터 런을 적으세요.")
    if name.endswith(".xls"):
        raise ImportError_("옛 엑셀(.xls)은 읽지 못합니다. .xlsx나 CSV(UTF-8)로 저장해 올리세요.")
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ImportError_("글자 인코딩을 읽지 못했습니다. CSV(UTF-8)로 저장해 올리세요.")
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delim = dialect.delimiter
    except csv.Error:
        delim = "\t" if sample.count("\t") > sample.count(",") else ","
    grid = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    if len(grid) < 2:
        raise ImportError_("머리글과 데이터 행이 없습니다. 첫 줄에 열 이름, 둘째 줄부터 런을 적으세요.")
    return grid


def _header_row(grid: list[list]) -> int:
    for i, r in enumerate(grid[:10]):
        cells = [c for c in r if c not in (None, "")]
        if len(cells) >= 2 and sum(1 for c in cells if U.parse_cell(c)[2] in ("num", "censored")) <= len(cells) / 3:
            return i
    return 0


# ---------------------------------------------------------------- 열 짐작

ROLE_WORDS = {
    "label": ["런", "run", "라벨", "label", "시료명", "이름", "name", "번호", "no", "id", "구분"],
    "date": ["날짜", "date", "일자", "실험일"],
    "note": ["비고", "메모", "note", "memo", "설명", "comment"],
}
# (단계 종류, 조건 키, 열 이름 열쇠 조각) — 위에서부터 확인
COND_RULES: list[tuple[str, str, list[str]]] = [
    ("feed", "moisture_pct", ["원료수분", "생시료수분", "초기수분", "투입수분", "원물수분", "rawmoisture", "initialmoisture"]),
    ("feed", "tpc_mg_g", ["원료tpc", "생시료tpc", "초기tpc", "원료폴리페놀", "생시료폴리페놀", "rawtpc"]),
    ("feed", "tdf_g_100g", ["원료tdf", "생시료tdf", "원료식이섬유", "생시료식이섬유", "rawtdf"]),
    ("feed", "mass_kg", ["투입량", "원료량", "투입질량"]),
    ("press", "target_moisture_pct", ["압착후수분", "탈수후수분", "압착수분"]),
    ("dry", "target_moisture", ["목표수분"]),
    ("dry", "method", ["건조방식", "건조방법", "method", "방식"]),
    ("mill", "particle_mm", ["입자", "particle"]),
    ("sieve", "yield_pct", ["체통과수율설정"]),
    ("sieve", "mesh_um", ["체눈", "메시", "mesh", "체크기"]),
    ("extract", "ethanol_pct", ["에탄올", "ethanol", "etoh", "주정"]),
    ("extract", "ratio_ml_g", ["용매비", "고액비", "ratio"]),
    ("extract", "solvent", ["용매종류", "추출용매", "solventtype", "solvent"]),
    ("extract", "acid", ["산종류", "산의종류", "사용산", "추출산", "acidtype", "acidused"]),
    ("extract", "temp_c", ["추출온도"]),
    ("extract", "time_min", ["추출시간"]),
    ("store", "package", ["포장", "package"]),
    ("store", "days", ["저장기간", "저장일", "보관기간", "보관일"]),
    ("store", "temp_c", ["저장온도", "보관온도"]),
    ("store", "rh", ["저장습도", "보관습도"]),
    ("dry", "pressure_pa", ["압력", "진공도", "pressure"]),
    ("dry", "air_velocity_ms", ["풍속", "velocity", "airspeed"]),
    ("dry", "thickness_mm", ["두께", "thickness"]),
    ("dry", "outlet_c", ["출구"]),
    ("dry", "residence_s", ["체류"]),
]
EXACT_COND = {"산": ("extract", "acid"), "acid": ("extract", "acid"), "용매": ("extract", "solvent"),
              "solvent": ("extract", "solvent"), "산종류": ("extract", "acid"), "용매종류": ("extract", "solvent")}
GENERIC_COND = [("dry", "temp_c", ["온도", "temp", "℃"]), ("dry", "time_h", ["시간", "time"]), ("dry", "rh", ["습도", "rh"])]
VALUE_STEP_WORDS = [("store", ["저장후", "보관후"]), ("extract", ["추출"]), ("sieve", ["체분리후", "분말"]),
                    ("wash", ["세척후"]), ("press", ["압착후", "탈수후"]), ("mill", ["분쇄후"]), ("dry", ["건조후", "건조물", "건조"]),
                    ("feed", ["원료", "생시료", "투입"])]
DEFAULT_VALUE_STEP = {"moisture": "dry", "tpc": "dry", "tdf": "dry", "tpc_ret": "dry", "time_target": "dry", "energy": "dry",
                      "energy_total": "dry", "sieve_yield": "sieve", "tpc_extract_yield": "extract", "extract_tpc": "extract",
                      "extract_solids": "extract", "dm_yield": None, "mass": None}
_UNIT_TAIL = re.compile(r"\s(℃|°C|%|h|hr|min|s|Pa|kPa|mbar|Torr|mm|cm|µm|um|kg|g|일|분|시간)$", re.I)


def _unit_of(h: str) -> str | None:
    """열 이름의 둥근 괄호 속 단위(기준 낱말은 뺀다) → 끝에 붙은 단위 → ℃ 기호."""
    par = re.findall(r"[\(（]([^\)）]*)[\)）]", h)
    if par:
        u = re.sub(r"(건량|습량|dry basis|wet basis|\bdb\b|\bwb\b|d\.b\.|w\.b\.)", " ", par[-1], flags=re.I).strip(" ,;")
        if u:
            return u
    m = _UNIT_TAIL.search(h)
    if m:
        return m.group(1)
    return "℃" if "℃" in h else None


def _first(steps: list[dict], type_: str | None) -> dict | None:
    if type_ is None:
        en = [s for s in steps if s.get("enabled", True)]
        return en[-1] if en else None
    return next((s for s in steps if s["type"] == type_ and s.get("enabled", True)), None) or \
        next((s for s in steps if s["type"] == type_), None)


def detect_column(header, steps: list[dict]) -> dict:
    h = str(header or "").strip()
    hk = U.key(h)
    raw_k = re.sub(r"[\s_\-·.:/]+", "", h.lower())
    col = {"header": h, "role": "ignore", "step_key": None, "key": None, "unit": _unit_of(h), "basis": U.basis_of(h), "note": None}
    if not hk:
        col["note"] = "빈 열 이름"
        return col
    # 1) 대괄호 단계 키: '[dry1] 수분 (%)'
    m = re.match(r"^\[([^\]]+)\]\s*(.+)$", h)
    by_key = {s["key"]: s for s in steps}
    by_label = {s["label"]: s for s in steps}
    if m and (m.group(1) in by_key or m.group(1) in by_label):
        st = by_key.get(m.group(1)) or by_label[m.group(1)]
        rest = m.group(2)
        rk = U.key(rest)
        for spec in S.specs_for(st["type"], st["params"]):
            if rk in (U.key(spec["label"]), U.key(spec["key"])):
                return {**col, "role": "condition", "step_key": st["key"], "key": spec["key"], "unit": _unit_of(rest) or col["unit"]}
        tk = U.canon_target(rest)
        if tk:
            return {**col, "role": "value", "step_key": st["key"], "key": tk, "unit": _unit_of(rest) or col["unit"]}
        col["note"] = f"'{st['label']}' 단계의 조건·대상 이름을 알아보지 못했습니다 — 직접 고르세요."
        return col
    # 2) 런 이름·날짜·비고
    for role, words in ROLE_WORDS.items():
        if hk in [U.key(w) for w in words] or raw_k in words:
            return {**col, "role": role, "unit": None}
    # 3) 조건(구체적인 것). '산'·'용매'처럼 짧은 이름은 열 이름 전체가 같을 때만
    exact = EXACT_COND.get(hk) or EXACT_COND.get(raw_k)
    if exact:
        st = _first(steps, exact[0])
        if st:
            return {**col, "role": "condition", "step_key": st["key"], "key": exact[1], "unit": None}
    for type_, pk, words in COND_RULES:
        if any(w in hk for w in words):
            st = _first(steps, type_)
            if st:
                return {**col, "role": "condition", "step_key": st["key"], "key": pk}
            col["note"] = f"'{S.DEFAULT_LABELS[type_]}' 단계가 흐름에 없어 쓰지 못합니다 — 흐름에 단계를 넣거나 무시하세요."
            return col
    # 4) 실측 대상
    tk = U.canon_target(h)
    if tk:
        type_ = DEFAULT_VALUE_STEP.get(tk)
        for t2, words in VALUE_STEP_WORDS:
            if any(w in hk for w in words):
                type_ = t2
                break
        st = _first(steps, type_)
        if st:
            return {**col, "role": "value", "step_key": st["key"], "key": tk}
        col.update(role="value", key=tk, note=f"이 값을 잴 '{S.DEFAULT_LABELS.get(type_, type_)}' 단계가 흐름에 없습니다 — 단계를 고르세요.")
        return col
    # 5) 일반 온도·시간·습도 → 건조
    for type_, pk, words in GENERIC_COND:
        if any(w in hk for w in words) or (pk == "temp_c" and "℃" in h):
            st = _first(steps, type_)
            if st:
                return {**col, "role": "condition", "step_key": st["key"], "key": pk}
    col["note"] = "알아보지 못한 열 — 역할을 직접 고르거나 무시하세요."
    return col


# ---------------------------------------------------------------- 값 바꾸기

def _cell_str(c) -> str:
    if c is None:
        return ""
    if isinstance(c, (datetime, date)):
        return c.date().isoformat() if isinstance(c, datetime) else c.isoformat()
    if isinstance(c, float) and c.is_integer():
        return str(int(c))
    return str(c)


def _select_value(spec: dict, raw) -> str:
    s = str(raw).strip()
    if s in spec["options"]:
        return s
    if spec.get("free"):  # 산·용매 종류: 목록 이름·별칭(HCl, citric …) 또는 직접 입력
        return S.canon_choice(spec, s)
    if spec["key"] == "method":
        m = drying.canonical(s) or coa.drying_method(s)
        if m in spec["options"]:
            return m
    if spec["key"] == "package":
        k = s.lower()
        if any(w in k for w in ("알루미늄", "방습", "alu", "foil")):
            return "방습(알루미늄)"
        if any(w in k for w in ("pe", "비닐", "폴리")):
            return "일반 PE"
        if any(w in k for w in ("개방", "없음", "open")):
            return "개방"
    raise ImportError_(f"'{spec['label']}' 값 '{s}'를 알아보지 못했습니다. {', '.join(spec['options'])} 중 하나로 적으세요.")


def row_to_run(row: list, columns: list[dict], steps: dict[str, dict]) -> dict | None:
    """한 행 → {label, run_date, note, conditions, values}. 모든 대응 칸이 비면 None."""
    out = {"label": None, "run_date": None, "note": None, "conditions": {}, "values": []}
    filled = False
    for col in columns:
        i = col.get("index")
        if i is None or i >= len(row) or col.get("role") in (None, "ignore"):
            continue
        cell = row[i]
        if cell in (None, "") or (isinstance(cell, str) and not cell.strip()):
            continue
        filled = True
        role = col["role"]
        if role in ("label", "note"):
            out[role] = _cell_str(cell)[:200]
        elif role == "date":
            out["run_date"] = _cell_str(cell)[:20]
        elif role == "condition":
            st = steps.get(col.get("step_key"))
            if not st:
                raise ImportError_(f"'{col['header']}' 열의 단계를 고르세요.")
            spec = next((s for s in S.specs_for(st["type"], {**st["params"], **out["conditions"].get(st["key"], {})})
                         if s["key"] == col.get("key")), None)
            if not spec:
                raise ImportError_(f"'{col['header']}' 열: '{st['label']}' 단계에 '{col.get('key')}' 조건이 없습니다. 조건을 다시 고르세요.")
            if spec.get("type") == "select":
                val = _select_value(spec, cell)
            else:
                v, txt, kind = U.parse_cell(cell)
                if kind not in ("num", "censored"):
                    raise ImportError_(f"'{col['header']}' 값 '{_cell_str(cell)}'를 숫자로 읽지 못했습니다. 숫자만 적으세요.")
                try:
                    val, _ = U.normalize(col["key"], v, col.get("unit"))
                except ValueError as ex:
                    raise ImportError_(f"'{col['header']}': {ex}") from ex
                val = round(val, 6)
            out["conditions"].setdefault(st["key"], {})[col["key"]] = val
        elif role == "value":
            if not col.get("step_key") or col["step_key"] not in steps:
                raise ImportError_(f"'{col['header']}' 열이 가리킬 단계를 고르세요.")
            out["values"].append({"step_key": col["step_key"], "target": col.get("key") or col["header"], "value": cell,
                                  "unit": col.get("unit"), "basis": col.get("basis")})
    return out if filled else None


# ---------------------------------------------------------------- 미리보기·확정

def _gc() -> None:
    now = time.time()
    for k in [k for k, v in _uploads.items() if now - v["t"] > TTL_S]:
        _uploads.pop(k, None)
    while len(_uploads) > 20:
        _uploads.pop(min(_uploads, key=lambda k: _uploads[k]["t"]))


def preview(exp_id: str, file_name: str, content: bytes) -> dict:
    exp = store.get_experiment(exp_id, with_runs=False)
    steps = exp["flow"]["steps"]
    grid = read_grid(file_name, content)
    hi = _header_row(grid)
    header = [_cell_str(c) for c in grid[hi]]
    data = grid[hi + 1:]
    cols = []
    for i, hname in enumerate(header):
        c = detect_column(hname, steps)
        c["index"] = i
        c["sample"] = [_cell_str(r[i]) if i < len(r) else "" for r in data[:3]]
        cols.append(c)
    token = __import__("uuid").uuid4().hex
    with _lock:
        _gc()
        _uploads[token] = {"exp_id": exp_id, "file_name": file_name, "header": header, "data": data, "t": time.time()}
    issues = [f"'{c['header']}': {c['note']}" for c in cols if c.get("note")]
    # 첫 몇 행을 지금 대응으로 읽어 본 결과
    trial, errors = [], []
    smap = {s["key"]: s for s in steps}
    for n, row in enumerate(data[:5], start=hi + 2):
        try:
            r = row_to_run(row, cols, smap)
            if r:
                store.clean_conditions(smap, r["conditions"])
                vals = store.clean_values(smap, r["values"])
                trial.append({"row": n, "label": r["label"], "conditions": r["conditions"],
                              "values": [{k: v[k] for k in ("step_key", "target_text", "value", "value_text", "unit_text", "basis")} for v in vals]})
        except (ImportError_, store.StoreError) as ex:
            errors.append({"row": n, "error": str(ex)})
    return {"token": token, "file_name": file_name, "n_rows": len(data), "header_row": hi + 1, "columns": cols,
            "rows": [[_cell_str(c) for c in r] for r in data[:10]], "trial": trial, "errors": errors, "issues": issues,
            "steps": [{"key": s["key"], "label": s["label"], "type": s["type"],
                       "params": [{"key": p["key"], "label": p["label"], "unit": p.get("unit", ""), "type": p.get("type", "number"), "options": p.get("options")} for p in S.specs_for(s["type"], s["params"])]}
                      for s in steps],
            "targets": [{"key": k, "label": v["label"], "unit": v["unit"]} for k, v in S.TARGETS.items()],
            "privacy": "올린 파일은 이 앱의 메모리에만 1시간 둡니다. 자료함·받은편지함에 넣지 않고 밖으로 보내지 않습니다."}


def commit(exp_id: str, token: str, columns: list[dict] | None = None) -> dict:
    with _lock:
        up = _uploads.get(token)
    if not up or up["exp_id"] != exp_id:
        raise ImportError_("가져오기 미리보기가 만료되었습니다. 파일을 다시 올리세요.")
    exp = store.get_experiment(exp_id, with_runs=False)
    smap = {s["key"]: s for s in exp["flow"]["steps"]}
    if columns is None:
        columns = [{**detect_column(h, exp["flow"]["steps"]), "index": i} for i, h in enumerate(up["header"])]
    created, errors = [], []
    for n, row in enumerate(up["data"], start=2):
        try:
            r = row_to_run(row, columns, smap)
            if not r:
                continue
            run = store.add_run(exp_id, label=r["label"], conditions=r["conditions"], run_date=r["run_date"], note=r["note"],
                                values=r["values"])
            created.append(run["xrun_id"])
        except (ImportError_, store.StoreError) as ex:
            errors.append({"row": n, "error": str(ex)})
    with _lock:
        _uploads.pop(token, None)
    return {"created": len(created), "runs": created, "errors": errors,
            "message": f"런 {len(created)}개를 넣었습니다." + (f" {len(errors)}개 행은 오류로 건너뜀 — 행 번호와 이유를 확인하세요." if errors else "")}


# ---------------------------------------------------------------- 내보내기

def export_csv(exp_id: str) -> str:
    exp = store.get_experiment(exp_id)
    steps = exp["flow"]["steps"]
    order = {s["key"]: i for i, s in enumerate(steps)}
    labels = {s["key"]: s for s in steps}
    conds, vals = [], []
    for run in exp["runs"]:
        for sk, c in run["conditions"].items():
            for pk in c:
                if (sk, pk) not in conds:
                    conds.append((sk, pk))
        for v in run["values"]:
            if v["kind"] == "measured" and (v["step_key"], v["target"], v["basis"]) not in vals:
                vals.append((v["step_key"], v["target"], v["basis"]))
    conds.sort(key=lambda x: order.get(x[0], 99))
    vals.sort(key=lambda x: order.get(x[0], 99))

    def cond_header(sk, pk):
        st = labels.get(sk)
        spec = next((s for s in S.specs_for(st["type"], st["params"]) if s["key"] == pk), None) if st else None
        lab = spec["label"] if spec else pk
        u = spec.get("unit") if spec else ""
        return f"[{sk}] {lab}" + (f" ({u})" if u else "")

    def val_header(sk, tgt, basis):
        tk = U.canon_target(tgt)
        unit = S.TARGETS[tk]["unit"] if tk else ""
        if tk in ("tpc", "tdf", "moisture"):
            unit = unit.replace(" 건량", "").replace(" 습량", "") + (f" {basis}" if basis else "")
        return f"[{sk}] {tgt}" + (f" ({unit})" if unit else "")

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["런", "날짜", "비고"] + [cond_header(*c) for c in conds] + [val_header(*v) for v in vals])
    for run in exp["runs"]:
        row = [run["label"] or run["alias"], run["run_date"] or "", run["note"] or ""]
        row += [run["conditions"].get(sk, {}).get(pk, "") for sk, pk in conds]
        for sk, tgt, basis in vals:
            v = next((x for x in run["values"] if x["kind"] == "measured" and x["step_key"] == sk and x["target"] == tgt
                      and x["basis"] == basis), None)
            row.append("" if not v else (v["value_text"] if v["value_text"] and (v["value"] is None or str(v["value_text"])[:1] in "<>≤≥")
                                         else _cell_str(v["value"])))
        w.writerow(row)
    return "﻿" + buf.getvalue()
