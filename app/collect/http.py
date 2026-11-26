"""수집용 HTTP — 표준 라이브러리만 쓴다. 모든 출처·크롤러가 이 모듈로만 밖에 나간다.

- 사용자 이메일·이름 같은 개인 정보를 헤더나 URL에 넣지 않는다(일반 클라이언트 이름만).
- 도메인마다 최소 간격(rate limit)을 둔다. 429/503은 Retry-After를 따라 한 번 더 시도한다.
- 테스트는 set_opener()로 가짜 응답을 넣는다(네트워크 없이).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "ByOrbit-RD-Studio/0.3 (local research tool)"
DEFAULT_TIMEOUT = 20
MIN_INTERVAL = {"default": 1.0}     # 도메인별 최소 간격(초). 출처 모듈이 set_interval로 바꾼다.

_last: dict[str, float] = {}
_lock = threading.Lock()
_opener = None                      # 테스트용 대체 opener: callable(Request, timeout) -> response-like


def redact(msg: str) -> str:
    """오류 메시지에서 API 키(BYORBIT_* 환경 변수 값)를 가린다 — 키가 주소 경로에 들어가는 출처가 있다."""
    for k, v in os.environ.items():
        if k.startswith("BYORBIT_") and v and len(v) >= 8 and v in msg:
            msg = msg.replace(v, "***")
    return msg


class HttpError(Exception):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(redact(msg))
        self.status = status


def set_opener(fn) -> None:
    global _opener
    _opener = fn


def set_interval(domain: str, seconds: float) -> None:
    MIN_INTERVAL[domain] = seconds


def _wait(url: str) -> None:
    host = urllib.parse.urlsplit(url).hostname or ""
    gap = MIN_INTERVAL.get(host, MIN_INTERVAL["default"])
    with _lock:
        now = time.monotonic()
        wait = _last.get(host, 0) + gap - now
        _last[host] = max(now, _last.get(host, 0) + gap)
    if wait > 0:
        time.sleep(wait)


def _open(url: str, params: dict | None, headers: dict | None, timeout: float, data: bytes | None = None,
          method: str | None = None):
    if params:
        q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
        url = url + ("&" if "?" in url else "?") + q
    h = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h, data=data, method=method)
    for attempt in (1, 2):
        _wait(url)
        try:
            if _opener:
                return _opener(req, timeout)
            return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — http(s)만 허용(아래 검사)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt == 1:
                ra = e.headers.get("Retry-After") if e.headers else None
                time.sleep(min(30.0, float(ra)) if ra and ra.isdigit() else 3.0)
                continue
            raise HttpError(f"HTTP {e.code}: {url.split('?')[0]}", e.code) from e
        except urllib.error.URLError as e:
            raise HttpError(f"연결 실패: {urllib.parse.urlsplit(url).hostname} ({e.reason})") from e
    raise HttpError("다시 시도했지만 실패했습니다.")


def _check_scheme(url: str) -> None:
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise HttpError(f"http(s) 주소만 쓸 수 있습니다: {url}")


def get_text(url: str, params: dict | None = None, headers: dict | None = None,
             timeout: float = DEFAULT_TIMEOUT, max_bytes: int = 5_000_000) -> str:
    _check_scheme(url)
    with _open(url, params, headers, timeout) as r:
        raw = r.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise HttpError(f"응답이 너무 큽니다(>{max_bytes // 1_000_000}MB): {url.split('?')[0]}")
        charset = None
        try:
            charset = r.headers.get_content_charset()
        except AttributeError:
            pass
    if not charset:  # 헤더에 없으면 HTML meta charset (EUC-KR 사이트 대비)
        m = re.search(rb"<meta[^>]+charset=[\"']?([A-Za-z0-9_-]+)", raw[:4096], re.I)
        charset = m.group(1).decode("ascii") if m else None
    try:
        return raw.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def get_json(url: str, params: dict | None = None, headers: dict | None = None,
             timeout: float = DEFAULT_TIMEOUT):
    txt = get_text(url, params, {"Accept": "application/json", **(headers or {})}, timeout)
    try:
        return json.loads(txt)
    except json.JSONDecodeError as e:
        raise HttpError(f"JSON이 아닌 응답: {url.split('?')[0]} — {txt[:200]}") from e


def download(url: str, dest: Path, max_mb: int = 50, timeout: float = 60,
             expect_pdf: bool = True) -> Path:
    """파일 받기. PDF를 기대하면 첫 바이트가 %PDF인지 확인한다(로그인 페이지 등을 걸러냄)."""
    _check_scheme(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    limit = max_mb * 1_000_000
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _open(url, None, {"Accept": "application/pdf,*/*"}, timeout) as r, open(tmp, "wb") as f:
        total, first = 0, b""
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            if not first:
                first = chunk[:5]
            total += len(chunk)
            if total > limit:
                f.close()
                tmp.unlink(missing_ok=True)
                raise HttpError(f"파일이 {max_mb}MB를 넘습니다: {url}")
            f.write(chunk)
    if expect_pdf and not first.startswith(b"%PDF"):
        tmp.unlink(missing_ok=True)
        raise HttpError("PDF가 아닌 응답입니다(로그인·안내 페이지일 수 있음). 원문 링크를 직접 열어 확인하세요.")
    tmp.replace(dest)
    return dest


# ---------------------------------------------------------------- 공개 출구 (다른 모듈은 _wait·_open 대신 이것을 쓴다)

def wait_turn(url: str) -> None:
    """이 호스트의 최소 간격을 기다린다(브라우저 엔진처럼 다른 경로로 요청할 때도 같은 간격을 지키도록)."""
    _wait(url)


def request(url: str, params: dict | None = None, headers: dict | None = None,
            timeout: float = DEFAULT_TIMEOUT, data: bytes | None = None, method: str | None = None):
    """응답 객체(with 문으로 닫기)를 돌려준다. POST·업로드처럼 get_text/get_json으로 안 되는 호출용.
    간격·재시도·키 가림·http(s) 검사는 다른 함수와 같다."""
    _check_scheme(url)
    return _open(url, params, headers, timeout, data=data, method=method)
