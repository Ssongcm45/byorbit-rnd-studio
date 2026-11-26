"""브라우저 방식 — Playwright 파이썬 라이브러리로 이 PC의 헤드리스 Chrome을 띄워 자바스크립트로 그리는 목록을 읽는다.

- 설치: install-browser.bat(requirements-browser.txt의 고정 버전 playwright). 설치된 Chrome(channel="chrome")을 먼저 쓰므로
  브라우저를 따로 받지 않는다. Chrome이 없을 때만 Playwright의 chromium을 쓴다(설치 때 약 150MB 받기).
- 크롤 한 번 = 브라우저 하나 + 새 컨텍스트 하나(쿠키·저장소 없음, 끝나면 닫음). 다운로드·서비스 워커 끔.
- 안전장치
  * http/https가 아닌 주소(file:, data:, javascript:, chrome:, about: …)로는 이동하지 않는다(check_navigation).
  * 페이지 안의 모든 요청을 route로 가로채 http/https가 아니면 끊는다. 이미지·글꼴·영상도 끊는다(should_block).
  * 리디렉션 뒤 주소도 http/https인지 다시 본다.
  * User-Agent는 일반 Chrome 문자열 + 이 앱 이름(개인 정보 없음).
- 간격·robots.txt·쪽수 제한은 크롤 루프(app/collect/crawler.py)가 이동(navigation)마다 지킨다. 페이지가 스스로 부르는
  스크립트·XHR은 그 페이지를 보여 주는 데 필요한 만큼만 나간다(이미지·글꼴·영상은 끊음).
- sync API를 부르는 스레드에서 그대로 쓴다(크롤러는 이미 백그라운드 스레드에서 돈다). 실행 중인 asyncio 루프가 있는
  스레드에서는 쓸 수 없으므로 그때는 새 스레드에서 돌린다.
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import http
from . import BackendUnavailable, FetchError, Page, is_web_url

log = logging.getLogger(__name__)

key = "browser"
bulk = False
NOT_INSTALLED = "브라우저 엔진 미설치 — install-browser.bat을 실행하세요"
PAGE_TIMEOUT_MS = 30_000        # 이동(goto) 한 번
DEFAULT_WAIT_MS = 8_000         # wait_for 선택자 기다리기
NETWORKIDLE_CAP_MS = 10_000     # 선택자가 없을 때 네트워크가 잠잠해지길 기다리는 상한
MAX_WAIT_MS = 15_000
MAX_HTML = 4_000_000
BLOCK_TYPES = frozenset({"image", "font", "media"})
BROWSER_SLOTS = threading.BoundedSemaphore(2)   # 동시에 띄우는 브라우저 수(메모리 보호)


# ---------------------------------------------------------------- 안전장치(브라우저 없이 시험 가능)

def check_navigation(url: str) -> str:
    """이동해도 되는 주소인지. http(s)가 아니면 FetchError — file:///C:/… 같은 PC 파일은 절대 열지 않는다."""
    if not is_web_url(url):
        scheme = urllib.parse.urlsplit(url or "").scheme or "(없음)"
        raise FetchError(f"브라우저는 http/https 주소만 엽니다(거절한 주소 형식: {scheme}).")
    return url


def should_block(url: str, resource_type: str | None = None) -> str | None:
    """끊을 요청이면 이유, 통과면 None. http(s)가 아닌 요청은 종류와 상관없이 끊는다."""
    if not is_web_url(url):
        return "http/https가 아닌 요청"
    if (resource_type or "") in BLOCK_TYPES:
        return f"{resource_type} 요청(필요 없음)"
    return None


def _route_handler(route) -> None:
    req = route.request
    try:
        reason = should_block(req.url, req.resource_type)
    except Exception:  # noqa: BLE001 — 판정이 깨지면 보수적으로 끊는다
        reason = "판정 실패"
    if reason:
        route.abort()
    else:
        route.continue_()


# ---------------------------------------------------------------- 준비 상태

def _installed() -> bool:
    return importlib.util.find_spec("playwright") is not None


def find_chrome() -> str | None:
    """설치된 Chrome 실행 파일(Windows 표준 위치)."""
    cands = []
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            cands.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    cands.append(Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"))
    for c in cands:
        if c.is_file():
            return str(c)
    return None


def bundled_chromium() -> bool:
    """Playwright가 받아 둔 chromium이 있는가(PLAYWRIGHT_BROWSERS_PATH 또는 %LOCALAPPDATA%\\ms-playwright)."""
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    roots = [Path(root)] if root and root != "0" else []
    if os.environ.get("LOCALAPPDATA"):
        roots.append(Path(os.environ["LOCALAPPDATA"]) / "ms-playwright")
    for r in roots:
        try:
            if any(p.is_dir() for p in r.glob("chromium-*")):
                return True
        except OSError:
            continue
    return False


def status() -> dict:
    if not _installed():
        return {"ready": False, "how": None, "message": NOT_INSTALLED + " (Playwright 파이썬 패키지가 없습니다)."}
    if find_chrome():
        return {"ready": True, "how": "chrome",
                "message": "사용 가능 — 설치된 Chrome을 헤드리스로 씁니다(이 PC 안에서만)."}
    if bundled_chromium():
        return {"ready": True, "how": "chromium", "message": "사용 가능 — Playwright chromium을 헤드리스로 씁니다."}
    return {"ready": False, "how": None,
            "message": "Chrome이 없습니다 — install-browser.bat을 실행하면 chromium(약 150MB)을 받을 수 있습니다."}


# ---------------------------------------------------------------- 세션

def _in_running_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


class Session:
    """with open(site) as s: s.fetch(url). 크롤 한 번 동안 브라우저 하나·컨텍스트 하나."""

    def __init__(self, site: dict):
        self.site = site
        self.wait_for = (site.get("wait_for") or "").strip() or None
        try:
            self.wait_ms = max(0, min(MAX_WAIT_MS, int(site.get("wait_ms") or 0)))
        except (TypeError, ValueError):
            self.wait_ms = 0
        self._pw = self._browser = self._ctx = self._page = None
        self._slot = False
        self._ex: ThreadPoolExecutor | None = None

    # 실행 중인 asyncio 루프가 있는 스레드(예: async 엔드포인트)라면 전용 스레드 하나에서 모든 호출을 돌린다
    def _call(self, fn, *a):
        if self._ex is None:
            return fn(*a)
        return self._ex.submit(fn, *a).result()

    def __enter__(self):
        st = status()
        if not st["ready"]:
            raise BackendUnavailable(st["message"])
        if _in_running_loop():
            self._ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="byorbit-browser")
        BROWSER_SLOTS.acquire()
        self._slot = True
        try:
            self._call(self._start, st["how"])
        except BackendUnavailable:
            self.__exit__(None, None, None)
            raise
        except Exception as e:  # noqa: BLE001
            self.__exit__(None, None, None)
            raise BackendUnavailable(f"브라우저를 띄우지 못했습니다: {http.redact(str(e))[:300]}. "
                                     "install-browser.bat을 다시 실행해 보세요.") from None
        return self

    def _start(self, how: str) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BackendUnavailable(NOT_INSTALLED) from None
        self._pw = sync_playwright().start()
        kw = {"headless": True, "args": ["--disable-extensions", "--no-first-run", "--no-default-browser-check"]}
        if how == "chrome":
            kw["channel"] = "chrome"
        self._browser = self._pw.chromium.launch(**kw)
        ver = (self._browser.version or "131.0.0.0").split()[0]
        ua = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              f"Chrome/{ver} Safari/537.36 {http.USER_AGENT}")
        self._ctx = self._browser.new_context(user_agent=ua, locale="ko-KR", accept_downloads=False,
                                              service_workers="block", java_script_enabled=True)
        self._ctx.route("**/*", _route_handler)
        self._ctx.on("page", self._close_popup)
        self._page = self._ctx.new_page()
        self._page.set_default_timeout(PAGE_TIMEOUT_MS)

    def _close_popup(self, pg) -> None:
        if self._page is not None and pg is not self._page:
            try:
                pg.close()
            except Exception:  # noqa: BLE001
                pass

    def __exit__(self, *exc):
        try:
            self._call(self._stop)
        finally:
            if self._ex is not None:
                self._ex.shutdown(wait=True)
                self._ex = None
            if self._slot:
                BROWSER_SLOTS.release()
                self._slot = False
        return False

    def _stop(self) -> None:
        for obj, meth in ((self._ctx, "close"), (self._browser, "close"), (self._pw, "stop")):
            if obj is not None:
                try:
                    getattr(obj, meth)()
                except Exception as e:  # noqa: BLE001
                    log.debug("브라우저 정리 중 오류: %s", e)
        self._pw = self._browser = self._ctx = self._page = None

    def fetch(self, url: str) -> Page:
        check_navigation(url)
        http.wait_turn(url)   # direct와 같은 호스트별 간격(크롤 루프가 정한 ≥3초·Crawl-delay)
        return self._call(self._fetch, url)

    def _fetch(self, url: str) -> Page:
        from playwright.sync_api import Error as PwError
        from playwright.sync_api import TimeoutError as PwTimeout
        pg = self._page
        note = None
        try:
            resp = pg.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        except PwTimeout:
            raise FetchError(f"페이지가 {PAGE_TIMEOUT_MS // 1000}초 안에 열리지 않았습니다: {url}") from None
        except PwError as e:
            m = str(e)
            if "Download is starting" in m or "download" in m.lower():
                raise FetchError(f"파일 다운로드 주소라 브라우저로 열지 않았습니다: {url}") from None
            if "ERR_FAILED" in m or "ERR_ABORTED" in m or "ERR_BLOCKED" in m:
                raise FetchError(f"열기가 막혔습니다(허용되지 않은 요청): {url}") from None
            raise FetchError(f"페이지를 열지 못했습니다: {http.redact(m.splitlines()[0])[:200]}") from None
        final = pg.url
        if not is_web_url(final):
            raise FetchError(f"http/https가 아닌 주소로 넘어가려 해서 멈췄습니다: {url}")
        code = resp.status if resp is not None else None
        if code is not None and code >= 400:
            raise FetchError(f"HTTP {code}: {url.split('?')[0]}", code)
        try:
            if self.wait_for:
                pg.wait_for_selector(self.wait_for, state="attached", timeout=self.wait_ms or DEFAULT_WAIT_MS)
            else:
                pg.wait_for_load_state("networkidle", timeout=min(self.wait_ms or 5_000, NETWORKIDLE_CAP_MS))
        except PwTimeout:
            note = (f"'{self.wait_for}' 요소가 나타나지 않아 그때까지 그려진 내용으로 읽었습니다"
                    if self.wait_for else None)
        except PwError as e:
            note = f"기다리는 중 오류(그려진 만큼 읽음): {str(e).splitlines()[0][:120]}"
        html = pg.content()
        if len(html) > MAX_HTML:
            raise FetchError(f"페이지가 너무 큽니다(>{MAX_HTML // 1_000_000}MB): {url.split('?')[0]}")
        return Page(url=url, final_url=pg.url, status=code, html=html, note=note)


def open(site: dict) -> Session:  # noqa: A001 — 방식 공통 이름
    return Session(site)
