"""API 키 보관 — 이 PC의 OS 자격 증명 저장소(Windows: 자격 증명 관리자)에만 둔다.

원칙(전역 보안 규칙: 비밀 값은 환경 변수 또는 OS 자격 증명 저장소에만)
- 키 값은 keyring(Windows Credential Manager / DPAPI)에만 저장한다. settings.json·DB·로그·change_log·
  내보내기·작업 기록·오류 메시지에 쓰지 않는다. 보관소를 못 쓰면 평문 대체 저장을 하지 않는다.
- API는 키 값을 돌려주지 않는다 — 있는지·어디서 왔는지(env | keyring | none)·끝 4자리 가림(••••3f9a)·저장 시각만.
- 우선순위: 실제 환경 변수 > 보관소. 앱을 켤 때와 저장·삭제 뒤, 실제 환경에 없는 이름만 보관소 값을 os.environ에 올린다.
  어떤 이름을 보관소에서 올렸는지 기억해 두었다가, 삭제할 때 그 이름만 os.environ에서 내린다(실제 환경 변수는 건드리지 않음).
- 저장 시각은 키 값이 전혀 없는 config/keys-meta.json에 둔다.

키 자리(slot)는 수집 출처의 needs_env·optional_env와 크롤러(Apify)·파서(Upstage) 키로 동적으로 만든다.
"""
from __future__ import annotations

import json
import os
import threading
import time

from . import config
from .collect import http

SERVICE = "RD-Studio-V0.5"          # 자격 증명 관리자에 보이는 이름(대상: 변수이름@RD-Studio-V0.5 또는 RD-Studio-V0.5)
MIN_LEN, MAX_LEN = 4, 1024          # Windows 자격 증명 하나는 2560바이트(UTF-16)까지 — 1024자면 넉넉하다
GROUP_ORDER = ["해외 학술", "국내 학술", "국가 R&D·특허", "공공데이터", "크롤러·파서(클라우드)"]
CLOUD_GROUP = "크롤러·파서(클라우드)"
ENV_HELP = ('PowerShell에서 [Environment]::SetEnvironmentVariable("{name}", "값", "User") 를 실행한 뒤 '
            "start.bat으로 앱을 다시 켜세요. 환경 변수가 있으면 보관소 값보다 먼저 쓰입니다.")

# 비밀이 아닌 설정 값(읽기 전용 안내). 값은 보여 주지 않고 지정 여부만 알린다.
CONFIG_ENV = [
    ("BYORBIT_HOME", "데이터 폴더 위치(기본: 사용자 홈의 ByOrbit-RD)"),
    ("BYORBIT_CLAUDE", "Claude Code 실행 파일 경로(기본: PATH에서 찾기)"),
    ("BYORBIT_CODEX", "Codex 실행 파일 경로(기본: PATH에서 찾기)"),
    ("BYORBIT_CODEX_MODEL", "Codex 모델 이름"),
    ("BYORBIT_CODEX_FORCE_BLOCK", "=1이면 Codex에 CoA 수치를 보내지 않도록 강제"),
    ("BYORBIT_CODEX_ALLOW_CONFIDENTIAL", "=1이면 Codex에 기밀 자료 허용(그때도 CoA 수치는 보내지 않음)"),
    ("BYORBIT_FORCE_COA_RULE", "=block이면 CoA 전송 규칙을 '보내지 않기'로 고정"),
    ("BYORBIT_NODE", "Node.js 실행 파일 경로(kordoc·식품 DB)"),
    ("BYORBIT_KORDOC_DIR", "kordoc 설치 폴더"),
    ("BYORBIT_FOOD_MCP_DIR", "ByOrbit Food MCP 폴더"),
    ("BYORBIT_COLLECT_SCHEDULER", "=0이면 저장 검색 자동 실행을 끔"),
    ("PLAYWRIGHT_BROWSERS_PATH", "브라우저 크롤러(Playwright) 브라우저 위치"),
]

_lock = threading.RLock()
_from_keyring: set[str] = set()     # 보관소에서 os.environ으로 올린 이름(실제 환경 변수와 구분)


class KeyStoreError(Exception):
    """사용자에게 그대로 보여 줄 한국어 오류(키 값은 절대 넣지 않는다)."""


class UnknownSlot(KeyStoreError):
    pass


class StoreUnavailable(KeyStoreError):
    pass


# ================================================================ 키 자리(slot)

def _source_slots() -> list[dict]:
    from .collect import registry
    out = []
    for src in registry.sources().values():
        req = tuple(getattr(src, "needs_env", ()) or ())
        opt = tuple(getattr(src, "optional_env", ()) or ())
        labels = getattr(src, "env_labels", {}) or {}
        for name, required in [(n, True) for n in req] + [(n, False) for n in opt]:
            help_ = src.key_help if required else (getattr(src, "optional_key_help", "") or src.key_help)
            out.append({
                "name": name, "label": labels.get(name, "API 키"), "group": src.group or "기타",
                "set": src.key, "set_name": src.name, "set_size": len(req) if required else 1,
                "consumer": f"자료 수집 · {src.name}", "required": required,
                "help": help_, "url": getattr(src, "key_url", "") or src.homepage, "terms_url": src.terms_url,
                "test": "source", "source_key": src.key,
                "note": "" if required else "없어도 쓸 수 있습니다. 넣으면 한도가 늘어납니다.",
            })
    return out


def _cloud_slots() -> list[dict]:
    from .collect.backends import apify
    from .ingest.parser_tools import upstage_tool as up
    return [
        {"name": apify.TOKEN_ENV, "label": "API 토큰", "group": CLOUD_GROUP, "set": "apify", "set_name": "Apify",
         "set_size": 1, "consumer": "자료 수집 · 크롤러 가져오기 방식 'Apify'(클라우드·유료)", "required": False,
         "help": ("Apify 가입 → Console → Settings → API & Integrations에서 API 토큰을 복사합니다. "
                  "크롤러 사이트에서 'Apify' 방식을 고를 때만 필요하고, 쓸 때마다 크레딧이 듭니다."),
         "url": apify.TOKEN_URL, "terms_url": "https://docs.apify.com/legal", "test": "apify",
         "note": "Apify 방식을 쓸 때만 필요합니다(선택)."},
        {"name": up.KEY_ENV, "label": "API 키", "group": CLOUD_GROUP, "set": "upstage", "set_name": "Upstage Document Parse",
         "set_size": 1, "consumer": "문서 파싱 · Upstage Document Parse(클라우드·유료)", "required": False,
         "help": ("Upstage 콘솔(https://console.upstage.ai)에 가입 → API Keys에서 키를 만듭니다. "
                  "쪽당 요금이 들고, 실행하면 문서 파일이 Upstage 서버로 갑니다('기밀' 문서는 막힘)."),
         "url": "https://console.upstage.ai", "terms_url": up.PRICING_URL, "test": "none",
         "note": "클라우드 파서를 쓸 때만 필요합니다(선택)."},
    ]


def slots() -> list[dict]:
    """모든 키 자리(값 없음). 같은 이름이 여러 번 나오면 처음 것만."""
    seen, out = set(), []
    for s in _source_slots() + _cloud_slots():
        if s["name"] not in seen:
            seen.add(s["name"])
            out.append(s)
    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    out.sort(key=lambda s: (order.get(s["group"], 99), not s["required"], s["set_name"]))
    return out


def slot(name: str) -> dict:
    for s in slots():
        if s["name"] == name:
            return s
    raise UnknownSlot(f"'{name}'은(는) 이 앱이 쓰는 키 이름이 아닙니다. 설정 → API 키 관리의 목록에서 고르세요.")


def secret_names() -> list[str]:
    return [s["name"] for s in slots()]


# ================================================================ 보관소(keyring)

def _kr():
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def backend_info() -> dict:
    kr = _kr()
    if kr is None:
        return {"available": False, "backend": None,
                "message": "keyring 패키지가 설치되어 있지 않습니다. install.bat을 다시 실행하거나 환경 변수를 쓰세요."}
    try:
        b = kr.get_keyring()
    except Exception as e:  # noqa: BLE001
        return {"available": False, "backend": None, "message": f"자격 증명 저장소를 열지 못했습니다: {type(e).__name__}"}
    mod, cls = type(b).__module__, type(b).__name__
    dead = mod.endswith((".fail", ".null")) or (cls == "ChainerBackend" and not getattr(b, "backends", None))
    name = f"{mod.rsplit('.', 1)[-1]}.{cls}"
    if dead:
        return {"available": False, "backend": name,
                "message": "이 PC에서 쓸 수 있는 자격 증명 저장소가 없습니다. 환경 변수로 키를 넣으세요."}
    label = "Windows 자격 증명 관리자" if "Windows" in mod or "WinVault" in cls else name
    return {"available": True, "backend": name, "label": label, "message": f"{label}에 저장합니다."}


def _need_store():
    info = backend_info()
    if not info["available"]:
        raise StoreUnavailable(info["message"])
    return _kr()


def _get_stored(name: str) -> str | None:
    kr = _kr()
    if kr is None or not backend_info()["available"]:
        return None
    try:
        return kr.get_password(SERVICE, name) or None
    except Exception:  # noqa: BLE001 — 읽기 실패는 '없음'으로(값·예외 문구를 내보내지 않는다)
        return None


# ================================================================ 저장 시각(비밀 아님)

def _meta_file():
    return config.path("config", "keys-meta.json")


def _meta() -> dict:
    try:
        return json.loads(_meta_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _meta_write(d: dict) -> None:
    f = _meta_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


# ================================================================ 상태

def mask(v: str | None) -> str | None:
    """끝 4자리만 보인다. 8자보다 짧으면 아무것도 보이지 않는다."""
    if not v:
        return None
    return "••••" + (v[-4:] if len(v) >= 8 else "")


def _real_env(name: str) -> str | None:
    if name in _from_keyring:
        return None
    return os.environ.get(name) or None


def status(name: str, s: dict | None = None) -> dict:
    s = s or slot(name)
    with _lock:
        env_v = _real_env(name)
        kr_v = _get_stored(name)
    src = "env" if env_v else "keyring" if kr_v else "none"
    meta = _meta().get(name, {})
    return {**s, "present": src != "none", "source": src,
            "mask": mask(env_v or kr_v), "env_set": bool(env_v), "stored": bool(kr_v),
            "stored_mask": mask(kr_v), "saved_at": meta.get("saved_at") if kr_v else None,
            "shadowed": bool(env_v and kr_v)}


def listing() -> dict:
    ss = slots()
    out = [status(s["name"], s) for s in ss]
    groups = [g for g in GROUP_ORDER if any(x["group"] == g for x in out)] + \
        sorted({x["group"] for x in out} - set(GROUP_ORDER))
    cfg = [{"name": n, "desc": d, "set": bool(os.environ.get(n))} for n, d in CONFIG_ENV]
    return {"service": SERVICE, "store": backend_info(), "groups": groups, "slots": out, "config": cfg,
            "env_help": ENV_HELP}


# ================================================================ 환경 변수 올리기·내리기

def _sync_redact() -> None:
    http.set_secret_names(secret_names())


def load_into_env() -> dict:
    """보관소 값을 os.environ에 올린다(실제 환경 변수가 없는 이름만). 앱 시작·저장·삭제 뒤에 부른다."""
    loaded, skipped = [], []
    with _lock:
        names = secret_names()
        http.set_secret_names(names)
        for n in names:
            if n in _from_keyring:
                v = _get_stored(n)
                if v:
                    os.environ[n] = v
                    loaded.append(n)
                else:
                    os.environ.pop(n, None)
                    _from_keyring.discard(n)
                continue
            if os.environ.get(n):
                skipped.append(n)       # 실제 환경 변수가 이긴다
                continue
            v = _get_stored(n)
            if v:
                os.environ[n] = v
                _from_keyring.add(n)
                loaded.append(n)
    return {"loaded": loaded, "env": skipped}


def loaded_from_keyring() -> set[str]:
    return set(_from_keyring)


def _reset_consumers(name: str) -> None:
    """키가 바뀌면 출처가 메모리에 둔 토큰 등을 버린다(ScienceON access_token)."""
    try:
        from .collect import registry
        for src in registry.sources().values():
            if name in tuple(getattr(src, "needs_env", ())) + tuple(getattr(src, "optional_env", ())):
                getattr(src, "reset", lambda: None)()
    except Exception:  # noqa: BLE001
        pass


def validate(value) -> str:
    if not isinstance(value, str):
        raise KeyStoreError("키는 글자로 넣어야 합니다.")
    v = value.strip()
    if not v:
        raise KeyStoreError("키가 비어 있습니다. 발급받은 값을 붙여 넣으세요.")
    if len(v) < MIN_LEN:
        raise KeyStoreError(f"키가 너무 짧습니다({MIN_LEN}자 이상). 발급받은 값을 모두 붙여 넣었는지 확인하세요.")
    if len(v) > MAX_LEN:
        raise KeyStoreError(f"키가 너무 깁니다({MAX_LEN}자 이하). 다른 글이 함께 붙여 넣어지지 않았는지 확인하세요.")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in v):
        raise KeyStoreError("키 안에 띄어쓰기·줄바꿈·제어 문자가 있습니다. 키만 한 줄로 붙여 넣으세요.")
    return v


def save(name: str, value) -> dict:
    s = slot(name)
    v = validate(value)
    kr = _need_store()
    with _lock:
        try:
            kr.set_password(SERVICE, name, v)
        except Exception as e:  # noqa: BLE001 — 예외 문구에 값이 섞일 수 있어 종류만 알린다
            raise KeyStoreError(f"자격 증명 저장소에 저장하지 못했습니다({type(e).__name__}). "
                            "환경 변수로 넣는 방법을 쓰세요.") from None
        m = _meta()
        m[name] = {"saved_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        _meta_write(m)
        if not _real_env(name):
            os.environ[name] = v
            _from_keyring.add(name)
        _sync_redact()
    _reset_consumers(name)
    return status(name, s)


def delete(name: str) -> dict:
    s = slot(name)
    kr = _need_store()
    with _lock:
        try:
            if kr.get_password(SERVICE, name) is not None:
                kr.delete_password(SERVICE, name)
        except Exception as e:  # noqa: BLE001
            raise KeyStoreError(f"자격 증명 저장소에서 지우지 못했습니다({type(e).__name__}).") from None
        m = _meta()
        if m.pop(name, None) is not None:
            _meta_write(m)
        if name in _from_keyring:
            os.environ.pop(name, None)
            _from_keyring.discard(name)
    _reset_consumers(name)
    return status(name, s)


# ================================================================ 연결 시험

TEST_QUERY = {"해외 학술": "apple pomace", "국내 학술": "사과", "국가 R&D·특허": "사과", "공공데이터": "사과"}
APIFY_ME = "https://api.apify.com/v2/users/me"


def test(name: str) -> dict:
    """그 키를 쓰는 곳의 가장 싼 실제 확인. 돈이 드는 호출은 하지 않는다. 결과 문구에서 키를 가린다."""
    s = status(name)
    via = {"env": "환경 변수 값으로", "keyring": "보관소 값으로"}.get(s["source"], "")
    try:
        r = _run_test(s)
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "message": f"시험하지 못했습니다: {e}"}
    msg = http.redact(r["message"])
    if via and r.get("ok") is not None:
        msg = f"{msg} ({via} 시험)"
    return {"name": name, "ok": r.get("ok"), "message": msg, "source": s["source"]}


def _run_test(s: dict) -> dict:
    from .collect.base import MissingKey, SourceError
    if not s["present"] and s["required"]:
        return {"ok": False, "message": "키가 없습니다. 먼저 저장하세요."}
    if s["test"] == "source":
        from .collect import registry
        src = registry.get(s["source_key"])
        st = src.status()
        if not st.get("ready"):
            miss = ", ".join(st.get("missing_env") or [])
            return {"ok": False, "message": f"아직 키가 다 있지 않습니다{': ' + miss if miss else ''}. "
                                            f"{src.name}에는 값 {len(src.needs_env)}개가 모두 필요합니다."}
        if not s["present"]:
            return {"ok": False, "message": "선택 키가 없습니다. 키 없이도 이 출처를 쓸 수 있습니다."}
        try:
            items = src.search(TEST_QUERY.get(src.group, "apple"), limit=1)
        except MissingKey as e:
            return {"ok": False, "message": str(e)}
        except (SourceError, http.HttpError) as e:
            return {"ok": False, "message": f"{src.name} 응답 오류: {e}"}
        return {"ok": True, "message": f"연결됨 — {src.name} 시험 검색 결과 {len(items)}건(1건만 요청)"}
    if s["test"] == "apify":
        if not s["present"]:
            return {"ok": False, "message": "토큰이 없습니다. 먼저 저장하세요."}
        tok = os.environ.get(s["name"], "").strip()
        try:
            data = http.get_json(APIFY_ME, headers={"Authorization": f"Bearer {tok}"}, timeout=15)
        except http.HttpError as e:
            if e.status in (401, 403):
                return {"ok": False, "message": "Apify가 토큰을 거절했습니다. Apify 콘솔에서 토큰을 다시 복사해 바꾸세요."}
            return {"ok": False, "message": f"Apify 연결 실패: {e}"}
        user = (data or {}).get("data", {}) if isinstance(data, dict) else {}
        who = user.get("username") or "계정"
        return {"ok": True, "message": f"연결됨 — Apify 계정({who}) 확인. 계정 정보 조회라 크레딧이 들지 않습니다"}
    if not s["present"]:
        return {"ok": False, "message": "키가 없습니다. 먼저 저장하세요."}
    return {"ok": None, "message": "저장됨 — 실제 호출은 사용할 때 확인합니다(요금 없이 키만 확인하는 방법이 없어 "
                                   "시험 호출을 하지 않습니다)."}
