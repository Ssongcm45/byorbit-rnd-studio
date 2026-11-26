"""API 키 관리(app/keys.py · /api/keys) 시험 — 가짜 메모리 보관소(keyring.set_keyring)로, 실제 자격 증명 관리자를 건드리지 않는다.

- 저장·목록·삭제, 우선순위(실제 환경 변수 > 보관소), os.environ 올리기·내리기, 가림 형식(••••끝4자리)
- 키 값이 어떤 API 응답·설정 파일·DB·로그에도 없다(전수 검사)
- redact가 보관소 값과 BYORBIT_*가 아닌 이름(OPENALEX_API_KEY 등)도 가린다
- 검증 오류(빈 값·공백·줄바꿈·길이·모르는 이름·JSON 아님)는 받은 값을 되돌려 주지 않는다
- 연결 시험: 가짜 HTTP(http.set_opener) — Apify 계정 조회(요금 없음), 출처 시험 검색, Upstage는 호출하지 않음
- 보관소를 못 쓰면 평문 대체 없이 503 + 환경 변수 안내
"""
from __future__ import annotations

import io
import json
import logging
import os
import urllib.error

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.backends import fail
from keyring.errors import PasswordDeleteError

from app import keys
from app.collect import http


class MemKeyring(KeyringBackend):
    """메모리 보관소(시험 전용)."""
    priority = 1

    def __init__(self):
        super().__init__()
        self.d: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.d.get((service, username))

    def set_password(self, service, username, password):
        self.d[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.d:
            raise PasswordDeleteError("없음")
        del self.d[(service, username)]


# 시험용 가짜 키(실제 키 아님). 모양만 실제와 비슷하게.
KCI = "kciSECRET9f3a7c21e0b4d5f6"
OPENALEX = "oaSECRET+key/with=chars7788"     # 퍼센트 인코딩되면 모양이 바뀌는 글자 포함
APIFY = "apify_api_SECRETtok3n0123456789"
UPSTAGE = "up_SECRET_6d1e2f3a4b5c"
ENVVAL = "envSECRETvalue11112222"
ALL_SECRETS = [KCI, OPENALEX, APIFY, UPSTAGE, ENVVAL]


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    from app import db, thesaurus
    prev = os.environ.get("BYORBIT_HOME")
    h = tmp_path_factory.mktemp("byorbit_home_keys")
    os.environ["BYORBIT_HOME"] = str(h)
    thesaurus.invalidate()
    db.init(seed=True)
    yield h
    if prev is None:
        os.environ.pop("BYORBIT_HOME", None)
    else:
        os.environ["BYORBIT_HOME"] = prev
    thesaurus.invalidate()


@pytest.fixture
def kr(home, monkeypatch):
    """깨끗한 메모리 보관소 + 키 이름 환경 변수 전부 지움(이 PC에 실제 키가 있어도 시험이 영향받지 않게)."""
    for n in keys.secret_names():
        monkeypatch.delenv(n, raising=False)
    keys._from_keyring.clear()
    meta = keys._meta_file()
    if meta.exists():
        meta.unlink()
    prev = keyring.get_keyring()
    mem = MemKeyring()
    keyring.set_keyring(mem)
    monkeypatch.setattr(http, "MIN_INTERVAL", {"default": 0.0})
    monkeypatch.setattr(http.time, "sleep", lambda s: None)
    yield mem
    keyring.set_keyring(prev)
    for n in list(keys._from_keyring):
        os.environ.pop(n, None)
    keys._from_keyring.clear()
    http.set_opener(None)


@pytest.fixture
def client(kr):
    from fastapi.testclient import TestClient
    from app import server
    return TestClient(server.app)   # with 없이: lifespan(감시·스케줄러)을 띄우지 않는다


def _no_secret(text: str, secrets=ALL_SECRETS):
    for s in secrets:
        assert s not in text, f"키 값이 새어 나왔습니다: …{s[-4:]}"


# ================================================================ 키 자리

def test_slots_cover_sources_and_cloud_keys(home):
    names = keys.secret_names()
    for n in ["BYORBIT_KCI_KEY", "BYORBIT_SCIENCEON_CLIENT_ID", "BYORBIT_SCIENCEON_KEY", "BYORBIT_SCIENCEON_MAC",
              "BYORBIT_NTIS_KEY", "BYORBIT_KIPRIS_KEY", "BYORBIT_DATAGOKR_KEY", "BYORBIT_FOODSAFETY_KEY",
              "BYORBIT_NONGSARO_KEY", "OPENALEX_API_KEY", "SEMANTIC_SCHOLAR_API_KEY", "BYORBIT_APIFY_TOKEN",
              "BYORBIT_UPSTAGE_KEY"]:
        assert n in names, n
    for cfg, _ in keys.CONFIG_ENV:           # 비밀이 아닌 설정 값은 키 자리가 아니다
        assert cfg not in names
    by = {s["name"]: s for s in keys.slots()}
    sci = [s for s in keys.slots() if s["set"] == "scienceon"]
    assert len(sci) == 3 and all(s["set_size"] == 3 and s["required"] for s in sci)
    assert "MAC" in by["BYORBIT_SCIENCEON_MAC"]["label"]
    assert by["OPENALEX_API_KEY"]["required"] is False and by["OPENALEX_API_KEY"]["group"] == "해외 학술"
    assert by["BYORBIT_APIFY_TOKEN"]["group"] == keys.CLOUD_GROUP and by["BYORBIT_UPSTAGE_KEY"]["group"] == keys.CLOUD_GROUP
    assert by["BYORBIT_KCI_KEY"]["help"] and by["BYORBIT_KCI_KEY"]["url"].startswith("https://")
    # redact가 아는 이름에도 들어간다
    keys._sync_redact()
    assert {"OPENALEX_API_KEY", "BYORBIT_UPSTAGE_KEY"} <= http._SECRET_NAMES


def test_router_included():
    from app import server
    paths = set(server.app.openapi()["paths"])
    assert {"/api/keys", "/api/keys/{name}", "/api/keys/{name}/test"} <= paths


def test_mask_format():
    assert keys.mask("abcdef123f9a") == "••••3f9a"
    assert keys.mask("short") == "••••"          # 짧은 값은 끝자리도 보이지 않는다
    assert keys.mask("") is None and keys.mask(None) is None


# ================================================================ 저장·목록·삭제

def test_save_list_delete(client, kr):
    r = client.post("/api/keys/BYORBIT_KCI_KEY", json={"value": KCI})
    assert r.status_code == 200, r.text
    _no_secret(r.text)
    st = r.json()["slot"]
    assert st["source"] == "keyring" and st["present"] and st["mask"] == "••••" + KCI[-4:] and st["saved_at"]
    assert kr.d[(keys.SERVICE, "BYORBIT_KCI_KEY")] == KCI
    assert os.environ["BYORBIT_KCI_KEY"] == KCI and "BYORBIT_KCI_KEY" in keys.loaded_from_keyring()

    lst = client.get("/api/keys")
    _no_secret(lst.text)
    d = lst.json()
    assert d["store"]["available"] and d["service"] == keys.SERVICE
    row = next(s for s in d["slots"] if s["name"] == "BYORBIT_KCI_KEY")
    assert row["source"] == "keyring" and row["stored"] and not row["env_set"]
    assert "value" not in row
    assert next(s for s in d["slots"] if s["name"] == "BYORBIT_NTIS_KEY")["source"] == "none"
    assert d["groups"][0] == "해외 학술" and keys.CLOUD_GROUP in d["groups"]
    assert any(c["name"] == "BYORBIT_HOME" for c in d["config"])

    # 출처 상태가 바로 바뀐다(앱 재시작 없이)
    from app.collect import registry
    assert registry.get("kci").status()["ready"] is True

    r = client.delete("/api/keys/BYORBIT_KCI_KEY")
    assert r.status_code == 200 and r.json()["slot"]["source"] == "none"
    assert (keys.SERVICE, "BYORBIT_KCI_KEY") not in kr.d
    assert "BYORBIT_KCI_KEY" not in os.environ and "BYORBIT_KCI_KEY" not in keys.loaded_from_keyring()
    assert registry.get("kci").status()["ready"] is False
    assert "BYORBIT_KCI_KEY" not in keys._meta()
    # 없는 것을 지워도 오류가 아니다
    assert client.delete("/api/keys/BYORBIT_KCI_KEY").status_code == 200


def test_env_wins_over_keyring(client, kr, monkeypatch):
    monkeypatch.setenv("BYORBIT_NTIS_KEY", ENVVAL)
    r = client.post("/api/keys/BYORBIT_NTIS_KEY", json={"value": KCI})
    assert r.status_code == 200 and "환경 변수" in r.json()["message"]
    st = r.json()["slot"]
    assert st["source"] == "env" and st["env_set"] and st["stored"] and st["shadowed"]
    assert st["mask"] == "••••" + ENVVAL[-4:] and st["stored_mask"] == "••••" + KCI[-4:]
    assert os.environ["BYORBIT_NTIS_KEY"] == ENVVAL                  # 실제 환경 변수를 덮어쓰지 않는다
    assert "BYORBIT_NTIS_KEY" not in keys.loaded_from_keyring()
    keys.load_into_env()
    assert os.environ["BYORBIT_NTIS_KEY"] == ENVVAL
    r = client.delete("/api/keys/BYORBIT_NTIS_KEY")
    assert r.json()["slot"]["source"] == "env"
    assert os.environ["BYORBIT_NTIS_KEY"] == ENVVAL                  # 지워도 실제 환경 변수는 그대로
    _no_secret(client.get("/api/keys").text)


def test_load_into_env_and_unload(kr, monkeypatch):
    kr.set_password(keys.SERVICE, "BYORBIT_KIPRIS_KEY", KCI)
    kr.set_password(keys.SERVICE, "BYORBIT_NTIS_KEY", APIFY)
    monkeypatch.setenv("BYORBIT_NTIS_KEY", ENVVAL)                   # 실제 환경 변수가 있는 이름은 건너뜀
    kr.set_password(keys.SERVICE, "NOT_A_SLOT", "zzzzzzzzzzzz")      # 모르는 이름은 올리지 않는다
    r = keys.load_into_env()
    assert "BYORBIT_KIPRIS_KEY" in r["loaded"] and "BYORBIT_NTIS_KEY" in r["env"]
    assert os.environ["BYORBIT_KIPRIS_KEY"] == KCI and os.environ["BYORBIT_NTIS_KEY"] == ENVVAL
    assert "NOT_A_SLOT" not in os.environ
    assert keys.loaded_from_keyring() == {"BYORBIT_KIPRIS_KEY"}
    # 보관소에서 바깥(자격 증명 관리자 화면 등)으로 지워졌으면 다음 올리기에서 내린다
    del kr.d[(keys.SERVICE, "BYORBIT_KIPRIS_KEY")]
    keys.load_into_env()
    assert "BYORBIT_KIPRIS_KEY" not in os.environ and not keys.loaded_from_keyring()
    # 삭제 API로 내리기
    keys.save("BYORBIT_KIPRIS_KEY", KCI)
    assert os.environ["BYORBIT_KIPRIS_KEY"] == KCI
    keys.delete("BYORBIT_KIPRIS_KEY")
    assert "BYORBIT_KIPRIS_KEY" not in os.environ
    assert os.environ["BYORBIT_NTIS_KEY"] == ENVVAL


def test_lifespan_loads_keyring(kr):
    from fastapi.testclient import TestClient
    from app import server
    kr.set_password(keys.SERVICE, "BYORBIT_UPSTAGE_KEY", UPSTAGE)
    server.app.state.no_watch = True
    try:
        with TestClient(server.app) as c:
            assert os.environ.get("BYORBIT_UPSTAGE_KEY") == UPSTAGE
            assert c.get("/api/keys").status_code == 200
    finally:
        server.app.state.no_watch = False


def test_scienceon_token_reset_on_change(kr):
    from app.collect import registry
    sci = registry.get("scienceon")
    sci._token = ("old-token", 9e18)
    keys.save("BYORBIT_SCIENCEON_KEY", "k" * 32)
    assert sci._token is None


# ================================================================ 값이 어디에도 남지 않는다

def test_values_never_in_responses_files_db_logs(client, kr, home, caplog):
    caplog.set_level(logging.DEBUG)
    resp_text = []
    for name, v in [("BYORBIT_KCI_KEY", KCI), ("OPENALEX_API_KEY", OPENALEX), ("BYORBIT_APIFY_TOKEN", APIFY),
                    ("BYORBIT_UPSTAGE_KEY", UPSTAGE)]:
        r = client.post(f"/api/keys/{name}", json={"value": v})
        assert r.status_code == 200
        resp_text.append(r.text)
    # 설정 저장·건강 확인·목록 응답에도 없다
    resp_text.append(client.post("/api/settings", json={"watch_inbox": False}).text)
    resp_text.append(client.get("/api/health").text)
    resp_text.append(client.get("/api/settings").text)
    resp_text.append(client.get("/api/keys").text)
    resp_text.append(client.get("/api/collect/sources").text)
    resp_text.append(client.post("/api/keys/BYORBIT_UPSTAGE_KEY/test").text)
    for t in resp_text:
        _no_secret(t)
    # 데이터 폴더의 모든 파일(settings.json·keys-meta.json·DB 포함)을 바이트로 훑는다
    files = [p for p in home.rglob("*") if p.is_file()]
    assert any(p.name == "keys-meta.json" for p in files) and any(p.suffix == ".sqlite" for p in files)
    for p in files:
        raw = p.read_bytes()
        for s in ALL_SECRETS:
            for enc in ("utf-8", "utf-16-le"):
                assert s.encode(enc) not in raw, f"{p.name}에 키가 있습니다"
    meta = json.loads(keys._meta_file().read_text(encoding="utf-8"))
    assert set(meta) == {"BYORBIT_KCI_KEY", "OPENALEX_API_KEY", "BYORBIT_APIFY_TOKEN", "BYORBIT_UPSTAGE_KEY"}
    assert all(set(v) == {"saved_at"} for v in meta.values())
    _no_secret(caplog.text)


# ================================================================ 가리기

def test_redact_covers_keyring_and_non_byorbit_names(kr):
    keys.save("OPENALEX_API_KEY", OPENALEX)          # 보관소 → os.environ (BYORBIT_ 아님)
    import urllib.parse
    msg = (f"HTTP 500: https://api.openalex.org/works?api_key={urllib.parse.quote_plus(OPENALEX)} "
           f"raw={OPENALEX} path=/{urllib.parse.quote(OPENALEX, safe='')}/x")
    out = http.redact(msg)
    assert OPENALEX not in out and urllib.parse.quote_plus(OPENALEX) not in out
    assert urllib.parse.quote(OPENALEX, safe="") not in out and out.count("***") == 3
    # 이름만 등록된 BYORBIT_ 아닌 키(실제 환경 변수)
    os.environ["SEMANTIC_SCHOLAR_API_KEY"] = ENVVAL
    try:
        assert ENVVAL not in http.redact(f"x-api-key: {ENVVAL}")
        assert str(http.HttpError(f"bad {ENVVAL}")) == "bad ***"
    finally:
        os.environ.pop("SEMANTIC_SCHOLAR_API_KEY", None)
    # 짧은 값·관계없는 글은 그대로
    assert http.redact("hello world") == "hello world"


def test_server_error_handler_redacts(kr):
    from fastapi.testclient import TestClient
    from app import server
    keys.save("BYORBIT_KCI_KEY", KCI)

    @server.app.get("/api/_test_boom_keys")
    def _boom():
        raise RuntimeError(f"failed with {KCI}")
    try:
        r = TestClient(server.app, raise_server_exceptions=False).get("/api/_test_boom_keys")
        assert r.status_code == 500 and KCI not in r.text and "***" in r.text
    finally:
        server.app.router.routes = [rt for rt in server.app.router.routes if getattr(rt, "path", "") != "/api/_test_boom_keys"]


# ================================================================ 검증

@pytest.mark.parametrize("body,code", [
    ({"value": ""}, 400), ({"value": "   "}, 400), ({"value": "abc"}, 400),
    ({"value": "abcd efgh1234"}, 400), ({"value": "abcdefgh\n1234"}, 400), ({"value": "abc\tdefgh123"}, 400),
    ({"value": "x" * 1025}, 400), ({"value": 1234567890123}, 400), ({"value": ["SECRETlistvalue1"]}, 400),
    ({"nothing": "SECRETnovalue12"}, 400),
])
def test_validation_errors_do_not_echo(client, kr, body, code):
    r = client.post("/api/keys/BYORBIT_KCI_KEY", json=body)
    assert r.status_code == code, r.text
    for v in body.values():
        sv = v if isinstance(v, str) else json.dumps(v)
        if len(sv.strip()) >= 4:
            assert sv.strip() not in r.text
    assert not kr.d and "BYORBIT_KCI_KEY" not in os.environ


def test_outer_whitespace_is_trimmed(client, kr):
    r = client.post("/api/keys/BYORBIT_KCI_KEY", json={"value": f"  {KCI}\r\n"})
    assert r.status_code == 200 and kr.d[(keys.SERVICE, "BYORBIT_KCI_KEY")] == KCI


def test_unknown_name_and_bad_json(client, kr):
    assert client.post("/api/keys/BYORBIT_HOME", json={"value": "C:\\x\\yyyy"}).status_code == 404
    assert client.post("/api/keys/NOPE_KEY", json={"value": KCI}).status_code == 404
    assert client.delete("/api/keys/NOPE_KEY").status_code == 404
    assert client.post("/api/keys/NOPE_KEY/test").status_code == 404
    r = client.post("/api/keys/BYORBIT_KCI_KEY", content=b"value=" + KCI.encode(), headers={"Content-Type": "text/plain"})
    assert r.status_code == 400 and KCI not in r.text
    assert not kr.d


def test_cross_origin_blocked(client, kr):
    r = client.post("/api/keys/BYORBIT_KCI_KEY", json={"value": KCI}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and not kr.d
    r = client.get("/api/keys", headers={"Host": "evil.example"})
    assert r.status_code == 403


def test_store_unavailable_no_plaintext_fallback(client, kr, home):
    keyring.set_keyring(fail.Keyring())
    d = client.get("/api/keys").json()
    assert d["store"]["available"] is False
    r = client.post("/api/keys/BYORBIT_KCI_KEY", json={"value": KCI})
    assert r.status_code == 503 and "SetEnvironmentVariable" in r.json()["detail"] and KCI not in r.text
    assert "BYORBIT_KCI_KEY" not in os.environ and not keys._meta_file().exists()
    for p in home.rglob("*"):
        if p.is_file():
            assert KCI.encode() not in p.read_bytes()


# ================================================================ 연결 시험(가짜 HTTP)

class Opener:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, req, timeout):
        url = req.full_url
        self.calls.append((url, dict(req.header_items())))
        for prefix, (code, body) in self.routes.items():
            if url.startswith(prefix):
                if code != 200:
                    raise urllib.error.HTTPError(url, code, "err", {}, io.BytesIO(b""))
                from tests.test_collect_kr import FakeResp
                return FakeResp(json.dumps(body).encode())
        raise urllib.error.URLError("no route")


def test_test_apify_auth_check(client, kr):
    keys.save("BYORBIT_APIFY_TOKEN", APIFY)
    op = Opener({keys.APIFY_ME: (200, {"data": {"username": "tester"}})})
    http.set_opener(op)
    r = client.post("/api/keys/BYORBIT_APIFY_TOKEN/test")
    assert r.status_code == 200 and r.json()["ok"] is True and "tester" in r.json()["message"]
    _no_secret(r.text)
    (url, hdr), = op.calls
    assert url == keys.APIFY_ME and APIFY not in url                       # 토큰은 주소가 아니라 헤더로만
    assert {k.lower(): v for k, v in hdr.items()}["authorization"] == f"Bearer {APIFY}"
    http.set_opener(Opener({keys.APIFY_ME: (401, None)}))
    r = client.post("/api/keys/BYORBIT_APIFY_TOKEN/test")
    assert r.json()["ok"] is False and "거절" in r.json()["message"]
    _no_secret(r.text)


def test_test_source_redacts_key_in_url(client, kr):
    keys.save("BYORBIT_FOODSAFETY_KEY", KCI)                              # 이 출처는 키를 주소 경로에 넣는다
    op = Opener({"http://openapi.foodsafetykorea.go.kr": (500, None)})
    http.set_opener(op)
    r = client.post("/api/keys/BYORBIT_FOODSAFETY_KEY/test")
    body = r.json()
    assert body["ok"] is False and op.calls, body and KCI in op.calls[0][0]       # 실제로 키를 써서 불렀고
    _no_secret(r.text)                                                       # 결과에는 없다


def test_test_optional_source_and_missing(client, kr):
    op = Opener({"https://api.openalex.org/works": (200, {"results": []})})
    http.set_opener(op)
    r = client.post("/api/keys/OPENALEX_API_KEY/test").json()
    assert r["ok"] is False and not op.calls                                # 선택 키가 없으면 부르지 않는다
    keys.save("OPENALEX_API_KEY", OPENALEX)
    r = client.post("/api/keys/OPENALEX_API_KEY/test")
    assert r.json()["ok"] is True, r.json()
    assert "per_page=1" in op.calls[0][0]       # 1건만 요청
    _no_secret(r.text)
    # 필수 키가 없을 때
    r = client.post("/api/keys/BYORBIT_KCI_KEY/test").json()
    assert r["ok"] is False and "없습니다" in r["message"]
    # ScienceON: 셋 중 하나만 있으면 시험하지 않고 무엇이 빠졌는지 알린다
    keys.save("BYORBIT_SCIENCEON_CLIENT_ID", "c" * 64)
    r = client.post("/api/keys/BYORBIT_SCIENCEON_CLIENT_ID/test").json()
    assert r["ok"] is False and "BYORBIT_SCIENCEON_KEY" in r["message"] and "BYORBIT_SCIENCEON_MAC" in r["message"]


def test_test_upstage_makes_no_call(client, kr):
    keys.save("BYORBIT_UPSTAGE_KEY", UPSTAGE)
    op = Opener({})
    http.set_opener(op)
    r = client.post("/api/keys/BYORBIT_UPSTAGE_KEY/test").json()
    assert r["ok"] is None and "사용할 때" in r["message"] and not op.calls
