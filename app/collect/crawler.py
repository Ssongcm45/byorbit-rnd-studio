"""예의 바른 크롤러 — 공식 API가 없는 공개 자료 목록 페이지에서 서지·링크를 모은다.

A↔B 계약(docs/PLAN-M3.md)
- list_sites() -> list[dict]          기본(crawl_defaults.json) + 사용자(데이터 폴더 config/crawl_sites.json) 병합
- save_site(site) -> dict             새 사이트 추가·수정. 기본 사이트는 덮어쓰기(override)로 저장
- delete_site(site_id) -> None        사용자 사이트는 삭제, 기본 사이트는 enabled=false
- check_site(site_id) -> {"robots_ok", "terms_url", "message"}
- site dict: {id, name, group, start_urls[], allow_prefixes[], link_pattern, title_hint?, date_pattern?,
              pdf_pattern?, interval_s, enabled, default}
  선택 필드(있으면 쓴다): search_urls[]("{q}" 자리에 검색어), link_template("{1}" = 자바스크립트 호출 인자),
  link_rewrite[패턴, 바꿀 말], summary_hint, doc_type("report"|"web"), max_pages, max_depth, terms_url,
  terms_checked, robots_checked, note, venue,
  backend("direct"|"browser"|"apify", 없으면 direct) + 방식 옵션: wait_for(CSS 선택자), wait_ms(브라우저·Apify 대기),
  actor(Apify 액터 바꾸기), max_charge_usd(Apify 실행 비용 상한, 기본 0.5)
- backend_status() -> {direct:{ready}, browser:{ready, how, message}, apify:{ready, message}}
- test_crawl(site_id, query="", max_pages=3) -> {pages, items[{title,url,date}], messages, ...}  (시험 수집, 저장 안 함)

가져오기 방식(app/collect/backends/)은 "페이지를 어떻게 받느냐"만 바꾼다. 아래 규칙은 방식과 상관없이 이 파일의
한 크롤 루프가 지킨다(Apify가 더 많이·다른 곳을 가져와도 규칙에 맞는 페이지만 쓴다).

지키는 규칙
- robots.txt를 http.get_text로 받아 urllib.robotparser로 읽는다(호스트마다 하루 캐시). 판정은 RFC 9309의
  가장 긴 규칙 우선(*, $ 지원). 막힌 주소는 건너뛰고 이유를 남긴다. robots.txt 404/410 → 허용, 그 밖의
  실패(401·403·5xx·연결 실패) → 그 호스트 전체를 건너뛴다(보수적).
- 호스트당 간격 ≥ 3초, robots Crawl-delay가 더 길면 그것을 따른다(http.set_interval).
- 사이트 한 번 훑을 때 최대 쪽수(기본 10, 최대 30)·깊이(1–2) 제한. allow_prefixes와 link_pattern에 맞는
  링크만, 같은 호스트(또는 allow_prefixes에 적힌 호스트)만 따라간다.
- 로그인·유료 페이지는 기본 목록에 넣지 않는다. 첨부는 href로 공개된 링크만 기록하고, 받는 일은 하지 않는다
  (PDF는 pdf_url로 넘겨 수집함 승인 때 http.download가 %PDF를 확인한다).
- 밖으로 나가는 것은 목록 주소와 검색어뿐이다. Apify 방식은 시작 주소·크롤 설정이 Apify 클라우드로 나가고(유료),
  검색어는 보내지 않는다(받은 페이지에서 이 PC가 거른다).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import unicodedata
import urllib.parse
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

from .. import config
from . import backends, http
from .backends import BackendUnavailable, FetchError
from .base import Item, clean_text

log = logging.getLogger(__name__)

DEFAULTS_FILE = Path(__file__).with_name("crawl_defaults.json")
ROBOT_AGENT = "RD-Studio"          # http.USER_AGENT의 제품 이름(robots.txt 판정용)
MIN_INTERVAL_S = 3.0
MAX_INTERVAL_S = 60.0
DEFAULT_MAX_PAGES = 10
HARD_MAX_PAGES = 30
DEFAULT_MAX_DEPTH = 1
HARD_MAX_DEPTH = 2
ROBOTS_TTL_S = 86400.0
MAX_SUMMARY = 1000
MAX_SITES_PARALLEL = 4
ATTACH_EXT = re.compile(r"\.(pdf|hwp|hwpx)(?:$|[?#&;])", re.I)
DEFAULT_PDF_PATTERN = r"\.(?:pdf|hwp|hwpx)(?:$|[?#&;])"
DEFAULT_DATE_PATTERN = r"((?:19|20)\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})"
SITE_FIELDS = ("id", "name", "group", "start_urls", "allow_prefixes", "link_pattern", "title_hint",
               "date_pattern", "pdf_pattern", "interval_s", "enabled", "default")
OPTIONAL_FIELDS = ("search_urls", "link_template", "link_rewrite", "summary_hint", "doc_type", "max_pages",
                   "max_depth", "terms_url", "terms_checked", "robots_checked", "note", "venue",
                   "backend", "wait_for", "wait_ms", "actor", "max_charge_usd")
TEST_MAX_PAGES = 3
MAX_WAIT_MS = 15_000

_file_lock = threading.Lock()


# ================================================================ 사이트 목록(기본 + 사용자)

def _user_file() -> Path:
    return config.path("config", "crawl_sites.json")


def load_defaults() -> list[dict]:
    try:
        data = json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("crawl_defaults.json을 읽지 못했습니다: %s", e)
        return []
    out = []
    for s in data.get("sites", []):
        s = dict(s)
        s["default"] = True
        out.append(_with_defaults(s))
    return out


def _load_user() -> dict:
    f = _user_file()
    if not f.exists():
        return {"version": 1, "sites": [], "overrides": {}}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("crawl_sites.json을 읽지 못해 빈 목록으로 시작합니다: %s", e)
        return {"version": 1, "sites": [], "overrides": {}}
    data.setdefault("sites", [])
    data.setdefault("overrides", {})
    return data


def _save_user(data: dict) -> None:
    f = _user_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".json.part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(f)


def _with_defaults(s: dict) -> dict:
    s.setdefault("group", "사용자 사이트")
    s.setdefault("start_urls", [])
    s.setdefault("allow_prefixes", [])
    s.setdefault("link_pattern", "")
    s.setdefault("title_hint", None)
    s.setdefault("date_pattern", None)
    s.setdefault("pdf_pattern", None)
    s.setdefault("interval_s", MIN_INTERVAL_S)
    s.setdefault("enabled", True)
    s.setdefault("default", False)
    if not s.get("backend"):
        s["backend"] = "direct"           # 예전 사이트 파일(방식 필드 없음)은 기본 방식
    return s


def list_sites() -> list[dict]:
    """기본 사이트(사용자 덮어쓰기 적용) + 사용자 사이트."""
    with _file_lock:
        user = _load_user()
    out = []
    default_ids = set()
    for d in load_defaults():
        default_ids.add(d["id"])
        ov = user["overrides"].get(d["id"]) or {}
        merged = {**d, **{k: v for k, v in ov.items() if k not in ("id", "default")}}
        merged["interval_s"] = max(float(merged.get("interval_s") or 0), float(d.get("interval_s") or 0),
                                   MIN_INTERVAL_S)
        merged["default"] = True
        merged["backend"] = merged.get("backend") or "direct"
        out.append(merged)
    for s in user["sites"]:
        if s.get("id") in default_ids:
            continue
        s = _with_defaults(dict(s))
        s["default"] = False
        out.append(s)
    return out


def get_site(site_id: str) -> dict:
    for s in list_sites():
        if s["id"] == site_id:
            return s
    raise KeyError(f"크롤러 사이트 '{site_id}'가 없습니다. 설정 화면의 사이트 목록에서 다시 고르세요.")


def _slug(name: str, seed: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKC", name).lower()).strip("-")
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:6]
    return f"{base[:30]}-{h}" if base else f"site-{h}"


def _check_regex(value, label: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label}은(는) 정규식 문자열이어야 합니다.")
    try:
        re.compile(value)
    except re.error as e:
        raise ValueError(f"{label} 정규식이 잘못되었습니다({e}). 예: /board/view\\?id=\\d+") from e
    return value


def _check_url(u, label: str) -> str:
    if not isinstance(u, str) or urllib.parse.urlsplit(u.strip()).scheme not in ("http", "https") \
            or not urllib.parse.urlsplit(u.strip()).hostname:
        raise ValueError(f"{label}은(는) http(s)로 시작하는 전체 주소여야 합니다: {u!r}")
    return u.strip()


def _str_list(v, label: str) -> list[str]:
    if v in (None, ""):
        return []
    if isinstance(v, str):
        v = [x for x in re.split(r"[\n,]+", v) if x.strip()]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ValueError(f"{label}은(는) 문자열 목록이어야 합니다.")
    return [x.strip() for x in v if x.strip()]


def validate_site(site: dict, base: dict | None = None) -> dict:
    """화면에서 받은 사이트를 검사·정리한다. 잘못되면 ValueError(무엇을 고칠지 포함)."""
    if not isinstance(site, dict):
        raise ValueError("사이트 정보는 객체여야 합니다.")
    s = {**(base or {}), **{k: v for k, v in site.items() if k in SITE_FIELDS + OPTIONAL_FIELDS}}
    s["name"] = clean_text(s.get("name"))
    if not s["name"]:
        raise ValueError("사이트 이름을 적으세요.")
    starts = _str_list(s.get("start_urls"), "시작 주소")
    if not starts:
        raise ValueError("시작 주소(start_urls)를 하나 이상 넣으세요. 자료 목록 페이지의 전체 주소입니다.")
    if len(starts) > 10:
        raise ValueError("시작 주소는 10개까지 넣을 수 있습니다.")
    s["start_urls"] = [_check_url(u, "시작 주소") for u in starts]
    s["search_urls"] = _str_list(s.get("search_urls"), "검색 주소")
    for u in s["search_urls"]:
        if "{q}" not in u:
            raise ValueError(f"검색 주소에는 검색어 자리 {{q}}가 있어야 합니다: {u}")
        _check_url(u.replace("{q}", "x"), "검색 주소")
    s["allow_prefixes"] = _str_list(s.get("allow_prefixes"), "허용 경로")
    for p in s["allow_prefixes"]:
        if "://" in p:
            _check_url(p, "허용 경로")
        elif not p.startswith("/"):
            raise ValueError(f"허용 경로는 '/'로 시작하는 경로나 전체 주소여야 합니다: {p}")
    s["link_pattern"] = _check_regex(s.get("link_pattern"), "링크 패턴") or ""
    s["pdf_pattern"] = _check_regex(s.get("pdf_pattern"), "첨부 패턴")
    s["date_pattern"] = _check_regex(s.get("date_pattern"), "날짜 패턴")
    if not s["link_pattern"] and not s["pdf_pattern"]:
        raise ValueError("링크 패턴(link_pattern) 또는 첨부 패턴(pdf_pattern) 중 하나는 있어야 합니다. "
                         "자료 상세 페이지 주소의 공통 부분을 정규식으로 적으세요.")
    for k in ("title_hint", "summary_hint", "link_template", "terms_url", "note", "venue",
              "terms_checked", "robots_checked"):
        v = s.get(k)
        s[k] = clean_text(v) if isinstance(v, str) and v.strip() else None
    if s.get("terms_url"):
        s["terms_url"] = _check_url(s["terms_url"], "이용약관 주소")
    if s.get("link_template"):
        _check_url(re.sub(r"\{\d\}", "x", s["link_template"]), "링크 틀") if "://" in s["link_template"] else None
    rw = s.get("link_rewrite")
    if rw in (None, "", []):
        s["link_rewrite"] = None
    else:
        if not (isinstance(rw, list) and len(rw) == 2 and all(isinstance(x, str) for x in rw)):
            raise ValueError("link_rewrite는 [패턴, 바꿀 말] 두 문자열이어야 합니다.")
        _check_regex(rw[0], "링크 바꾸기 패턴")
    try:
        iv = float(s.get("interval_s") or MIN_INTERVAL_S)
    except (TypeError, ValueError):
        raise ValueError("간격(interval_s)은 초 단위 숫자여야 합니다.") from None
    s["interval_s"] = min(MAX_INTERVAL_S, max(MIN_INTERVAL_S, iv))
    try:
        s["max_pages"] = min(HARD_MAX_PAGES, max(1, int(s.get("max_pages") or DEFAULT_MAX_PAGES)))
        s["max_depth"] = min(HARD_MAX_DEPTH, max(1, int(s.get("max_depth") or DEFAULT_MAX_DEPTH)))
    except (TypeError, ValueError):
        raise ValueError("최대 쪽수·깊이는 정수여야 합니다.") from None
    if s.get("doc_type") not in (None, "report", "web"):
        raise ValueError("doc_type은 report 또는 web입니다.")
    s["enabled"] = bool(s.get("enabled", True))
    s["group"] = clean_text(s.get("group")) or "사용자 사이트"
    _validate_backend(s)
    return s


_SEL_ENGINE = re.compile(r"^\s*[A-Za-z_\-]+\s*=")     # Playwright의 text=, xpath= 같은 엔진 접두어(CSS만 받는다)


def _validate_backend(s: dict) -> None:
    """가져오기 방식과 그 옵션 검사. 없으면 direct."""
    b = s.get("backend") or "direct"
    if b not in backends.BACKENDS:
        raise ValueError(f"가져오기 방식(backend)은 {', '.join(backends.BACKENDS)} 중 하나입니다: {b!r}")
    s["backend"] = b
    w = s.get("wait_for")
    if w in (None, ""):
        s["wait_for"] = None
    else:
        if not isinstance(w, str) or len(w) > 200 or any(ch in w for ch in "\r\n\t\x00") or _SEL_ENGINE.match(w):
            raise ValueError("기다릴 요소(wait_for)는 200자 이내 CSS 선택자입니다(예: table.board_list, #list li).")
        s["wait_for"] = w.strip()
    try:
        s["wait_ms"] = None if s.get("wait_ms") in (None, "") else min(MAX_WAIT_MS, max(0, int(s["wait_ms"])))
    except (TypeError, ValueError):
        raise ValueError("대기 시간(wait_ms)은 밀리초 정수입니다(0–15000).") from None
    from .backends import apify as _apify
    s["actor"] = _apify.norm_actor(s["actor"]) if s.get("actor") else None
    has_cap = s.get("max_charge_usd") not in (None, "")
    s["max_charge_usd"] = _apify.charge_cap(s.get("max_charge_usd")) if (b == "apify" or has_cap) else None


def save_site(site: dict) -> dict:
    """사이트 저장. id가 기본 사이트면 덮어쓰기로, 아니면 사용자 사이트로 저장한다."""
    defaults = {d["id"]: d for d in load_defaults()}
    sid = clean_text((site or {}).get("id")) if isinstance(site, dict) else ""
    with _file_lock:
        user = _load_user()
        if sid and sid in defaults:
            base = {**defaults[sid], **(user["overrides"].get(sid) or {})}
            s = validate_site(site, base)
            s["interval_s"] = max(s["interval_s"], float(defaults[sid].get("interval_s") or MIN_INTERVAL_S))
            ov = {k: v for k, v in s.items()
                  if k not in ("id", "default") and defaults[sid].get(k) != v}
            user["overrides"][sid] = ov
            _save_user(user)
            s.update(id=sid, default=True)
            return s
        existing = next((x for x in user["sites"] if x.get("id") == sid), None) if sid else None
        s = validate_site(site, existing)
        if not sid:
            sid = _slug(s["name"], s["name"] + s["start_urls"][0])
            while sid in defaults or any(x.get("id") == sid for x in user["sites"]):
                sid = _slug(s["name"], sid + "+")
        elif not re.fullmatch(r"[A-Za-z0-9_\-]{1,60}", sid):
            raise ValueError("사이트 id는 영문·숫자·-·_ 60자 이내여야 합니다(비우면 자동으로 만듭니다).")
        s.update(id=sid, default=False)
        user["sites"] = [x for x in user["sites"] if x.get("id") != sid] + [s]
        _save_user(user)
        return s


def delete_site(site_id: str) -> None:
    defaults = {d["id"] for d in load_defaults()}
    with _file_lock:
        user = _load_user()
        if site_id in defaults:
            user["overrides"].setdefault(site_id, {})["enabled"] = False
            _save_user(user)
            return
        before = len(user["sites"])
        user["sites"] = [x for x in user["sites"] if x.get("id") != site_id]
        if len(user["sites"]) == before:
            raise KeyError(f"크롤러 사이트 '{site_id}'가 없습니다.")
        _save_user(user)


# ================================================================ robots.txt

class Robots:
    """한 호스트의 robots.txt 판정. RFC 9309: 가장 긴 규칙 우선, 같은 길이면 Allow."""

    def __init__(self, text: str | None, *, allow_all: bool = False, deny_all: bool = False, note: str = ""):
        self.allow_all = allow_all
        self.deny_all = deny_all
        self.note = note
        self.rp = None
        if text is not None:
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(text.splitlines())
            self.rp = rp

    def _rules(self) -> list[tuple[str, bool]]:
        rp = self.rp
        if rp is None:
            return []
        for entry in rp.entries:
            if entry.applies_to(ROBOT_AGENT):
                return [(r.path, r.allowance) for r in entry.rulelines]
        if rp.default_entry is not None:
            return [(r.path, r.allowance) for r in rp.default_entry.rulelines]
        return []

    def can_fetch(self, url: str) -> bool:
        if self.deny_all:
            return False
        if self.allow_all or self.rp is None:
            return True
        parts = urllib.parse.urlsplit(url)
        target = urllib.parse.unquote(parts.path or "/") + (("?" + urllib.parse.unquote(parts.query))
                                                           if parts.query else "")
        best_len, best_allow = -1, True
        for path, allow in self._rules():
            pat = urllib.parse.unquote(path)
            if pat == "":
                continue                      # 빈 Disallow = 전부 허용
            if _robots_match(pat, target):
                ln = len(pat)
                if ln > best_len or (ln == best_len and allow):
                    best_len, best_allow = ln, allow
        return best_allow

    def crawl_delay(self) -> float | None:
        if self.rp is None:
            return None
        try:
            d = self.rp.crawl_delay(ROBOT_AGENT)
        except Exception:  # noqa: BLE001
            return None
        try:
            return float(d) if d is not None else None
        except (TypeError, ValueError):
            return None


def _robots_match(pattern: str, target: str) -> bool:
    anchored = pattern.endswith("$")
    if anchored:
        pattern = pattern[:-1]
    rx = "".join(".*" if ch == "*" else re.escape(ch) for ch in pattern)
    return re.match(rx + ("$" if anchored else ""), target) is not None


_robots_cache: dict[str, tuple[float, Robots]] = {}
_robots_lock = threading.Lock()


def clear_robots_cache() -> None:
    with _robots_lock:
        _robots_cache.clear()


def robots_for(url: str) -> Robots:
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    now = time.time()
    with _robots_lock:
        hit = _robots_cache.get(origin)
        if hit and now - hit[0] < ROBOTS_TTL_S:
            return hit[1]
    try:
        txt = http.get_text(origin + "/robots.txt", max_bytes=500_000)
        if re.search(r"<html|<!doctype", txt[:500], re.I):
            # 없는 파일을 오류 페이지(HTML, 200)로 돌려주는 사이트 → robots.txt 없음으로 본다
            rb = Robots(None, allow_all=True, note="robots.txt 없음(오류 페이지 응답) — 일반 규칙(간격·쪽수 제한)만 적용")
        else:
            rb = Robots(txt, note="robots.txt 확인")
    except http.HttpError as e:
        if e.status in (404, 410):
            rb = Robots(None, allow_all=True, note="robots.txt 없음(404) — 일반 규칙만 적용")
        else:
            rb = Robots(None, deny_all=True, note=f"robots.txt를 받지 못해 건너뜀({e})")
    with _robots_lock:
        _robots_cache[origin] = (now, rb)
    return rb


def _apply_interval(url: str, site_interval: float, rb: Robots) -> float:
    host = urllib.parse.urlsplit(url).hostname or ""
    gap = max(MIN_INTERVAL_S, float(site_interval or 0), rb.crawl_delay() or 0)
    gap = min(gap, 120.0)
    if http.MIN_INTERVAL.get(host, 0) < gap:
        http.set_interval(host, gap)
    return gap


# ================================================================ 작은 HTML 트리

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
        "track", "wbr"}
_BLOCK = {"br", "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "ul", "ol",
          "table", "section", "article", "header", "footer", "nav", "hr", "img"}
NO_TEXT = {"script", "style", "noscript", "template", "head", "select", "option", "button"}
_AUTO_CLOSE = {
    "li": ({"li"}, {"ul", "ol", "menu"}),
    "tr": ({"tr"}, {"table", "tbody", "thead", "tfoot"}),
    "td": ({"td", "th"}, {"tr", "table"}),
    "th": ({"td", "th"}, {"tr", "table"}),
    "p": ({"p"}, {"div", "td", "th", "li", "table", "section", "article", "body", "dd", "form"}),
    "option": ({"option"}, {"select"}),
    "dt": ({"dt", "dd"}, {"dl"}),
    "dd": ({"dt", "dd"}, {"dl"}),
}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict, parent: "Node | None"):
        self.tag, self.attrs, self.children, self.parent = tag, attrs, [], parent

    def iter(self):
        stack = [self]
        while stack:
            n = stack.pop()
            yield n
            stack.extend(c for c in reversed(n.children) if isinstance(c, Node))

    def text(self) -> str:
        out: list[str] = []

        def walk(n: Node):
            for c in n.children:
                if isinstance(c, str):
                    out.append(c)
                elif c.tag not in NO_TEXT:
                    block = c.tag in _BLOCK
                    if block:
                        out.append(" ")
                    walk(c)
                    if block:
                        out.append(" ")
        walk(self)
        return clean_text("".join(out)) if out else ""

    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        rule = _AUTO_CLOSE.get(tag)
        if rule:
            same, bounds = rule
            for i in range(len(self.stack) - 1, 0, -1):
                t = self.stack[i].tag
                if t in same:
                    del self.stack[i:]
                    break
                if t in bounds:
                    break
        parent = self.stack[-1]
        n = Node(tag, {k.lower(): (v or "") for k, v in attrs}, parent)
        parent.children.append(n)
        if tag not in VOID:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        parent = self.stack[-1]
        parent.children.append(Node(tag.lower(), {k.lower(): (v or "") for k, v in attrs}, parent))

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data:
            self.stack[-1].children.append(data)


def parse_html(html: str) -> Node:
    b = _Builder()
    try:
        b.feed(html)
        b.close()
    except Exception as e:  # noqa: BLE001 — 망가진 HTML도 읽은 만큼은 쓴다
        log.debug("HTML 파싱 중 오류(읽은 만큼 사용): %s", e)
    return b.root


def _parse_selector(sel: str) -> list[tuple[str | None, set[str], str | None]]:
    out = []
    for part in (sel or "").split(","):
        part = part.strip()
        if not part:
            continue
        part = part.split()[-1]               # 'div .x' 같은 자손 선택자는 마지막 단계만 본다
        m = re.fullmatch(r"([a-zA-Z][a-zA-Z0-9]*)?((?:[.#][\w\-]+)*)", part)
        if not m:
            continue
        tag = (m.group(1) or "").lower() or None
        classes = set(re.findall(r"\.([\w\-]+)", m.group(2) or ""))
        ids = re.findall(r"#([\w\-]+)", m.group(2) or "")
        out.append((tag, classes, ids[0] if ids else None))
    return out


def select_first(node: Node, sel: str | None) -> Node | None:
    if not sel:
        return None
    alts = _parse_selector(sel)
    for n in node.iter():
        if n is node:
            continue
        for tag, classes, nid in alts:
            if (tag is None or n.tag == tag) and classes <= n.classes() and (nid is None or n.attrs.get("id") == nid):
                return n
    return None


# ================================================================ 링크·항목 뽑기

_JS_CALL = re.compile(r"^\s*javascript:\s*(?:void\(0\);?\s*)?[\w.$]+\s*\((.*)\)\s*;?\s*$", re.I | re.S)
_JS_ARG = re.compile(r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"|(-?\d+(?:\.\d+)?)")
_ONCLICK_HREF = re.compile(r"location(?:\.href)?\s*=\s*['\"]([^'\"]+)['\"]", re.I)
_ONCLICK_CALL = re.compile(r"([\w.$]+)\s*\(([^()]*)\)")


def _js_args(argstr: str) -> list[str]:
    return [next(g for g in m.groups() if g is not None) for m in _JS_ARG.finditer(argstr or "")]


def resolve_link(node: Node, page_url: str, site: dict) -> str | None:
    """요소 하나가 가리키는 주소(href, onclick location.href, javascript:함수('인자') + link_template)."""
    href = (node.attrs.get("href") or "").strip()
    url = None
    tmpl = site.get("link_template")
    if href and not href.lower().startswith("javascript:") and not href.startswith("#"):
        url = href
    elif href.lower().startswith("javascript:") and tmpl:
        m = _JS_CALL.match(href)
        if m:
            args = _js_args(m.group(1))
            if args:
                url = _fill_template(tmpl, args)
    if url is None:
        onclick = node.attrs.get("onclick") or ""
        m = _ONCLICK_HREF.search(onclick)
        if m:
            url = m.group(1)
        elif tmpl and onclick:
            mc = _ONCLICK_CALL.search(onclick)
            if mc:
                args = _js_args(mc.group(2))
                if args:
                    url = _fill_template(tmpl, args)
    if not url:
        return None
    try:
        absu = urllib.parse.urljoin(page_url, url)
    except ValueError:
        return None
    absu = absu.split("#", 1)[0]
    rw = site.get("link_rewrite")
    if rw:
        absu = re.sub(rw[0], rw[1], absu)
    if urllib.parse.urlsplit(absu).scheme not in ("http", "https"):
        return None
    return absu


def _fill_template(tmpl: str, args: list[str]) -> str | None:
    def rep(m):
        i = int(m.group(1)) - 1
        return urllib.parse.quote(args[i], safe="") if 0 <= i < len(args) else ""
    out = re.sub(r"\{(\d)\}", rep, tmpl)
    return out or None


def _hosts(site: dict) -> set[str]:
    hs = {urllib.parse.urlsplit(u).hostname for u in site.get("start_urls", []) + site.get("search_urls", [])}
    hs |= {urllib.parse.urlsplit(p).hostname for p in site.get("allow_prefixes", []) if "://" in p}
    return {h for h in hs if h}


def link_allowed(url: str, site: dict) -> bool:
    """같은 호스트(또는 allow_prefixes의 호스트) + allow_prefixes(있으면) 안의 주소인가."""
    parts = urllib.parse.urlsplit(url)
    if parts.hostname not in _hosts(site):
        return False
    prefixes = site.get("allow_prefixes") or []
    if not prefixes:
        return True
    path_q = parts.path + (("?" + parts.query) if parts.query else "")
    for p in prefixes:
        if "://" in p:
            if url.startswith(p):
                return True
        elif path_q.startswith(p) and (parts.hostname in {urllib.parse.urlsplit(u).hostname
                                                           for u in site.get("start_urls", [])
                                                           + site.get("search_urls", [])}):
            return True
    return False


def _context(node: Node) -> Node:
    n = node
    while n is not None and n.tag != "#root":
        if n.tag in ("tr", "li", "article", "dl"):
            return n
        n = n.parent
    return node


def _link_label(node: Node) -> str:
    t = node.text()
    if t:
        return t
    for k in ("title", "download", "aria-label"):
        if node.attrs.get(k):
            return clean_text(node.attrs[k])
    for n in node.iter():
        if n.tag == "img" and n.attrs.get("alt"):
            return clean_text(n.attrs["alt"])
    return ""


def _parse_date(text: str, pattern: str | None) -> tuple[str | None, int | None]:
    try:
        rx = re.compile(pattern or DEFAULT_DATE_PATTERN)
    except re.error:
        rx = re.compile(DEFAULT_DATE_PATTERN)
    m = rx.search(text or "")
    if not m:
        return None, None
    groups = [g for g in m.groups() if g] or [m.group(0)]
    try:
        if len(groups) >= 3:
            y, mo, d = int(groups[0]), int(groups[1]), int(groups[2])
            if 1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{mo:02d}-{d:02d}", y
            return None, None
        y = int(re.search(r"(19|20)\d{2}", groups[0]).group(0))
        return None, y
    except (ValueError, AttributeError):
        return None, None


def _pdf_rx(site: dict):
    return re.compile(site.get("pdf_pattern") or DEFAULT_PDF_PATTERN, re.I)


def _clean_title(t: str) -> str:
    t = re.sub(r"\s*(새창열림|새창|\[새창\]|글보기|첨부파일\s*있음|NEW)\s*$", "", clean_text(t))
    return t.strip(" -·|")


def extract_entries(html: str, page_url: str, site: dict) -> tuple[list[dict], list[dict], Node]:
    """목록·상세 페이지 한 장에서 (항목 후보, 첨부 링크, 트리)를 뽑는다.

    항목 후보: link_pattern에 맞는 링크(또는 그 자체가 첨부인 링크). 첨부: pdf_pattern에 맞는 공개 href."""
    root = parse_html(html)
    link_rx = re.compile(site["link_pattern"]) if site.get("link_pattern") else None
    pdf_rx = _pdf_rx(site)
    entries: dict[str, dict] = {}
    attachments: dict[str, dict] = {}
    hosts = _hosts(site)
    for n in root.iter():
        if n.tag == "#root":
            continue
        if not (n.attrs.get("href") or n.attrs.get("onclick")):
            continue
        url = resolve_link(n, page_url, site)
        if not url or urllib.parse.urlsplit(url).hostname not in hosts:
            continue                          # 다른 호스트는 보지 않는다
        is_attach = bool(pdf_rx.search(url))  # 첨부는 기록만 하므로 같은 호스트면 된다(robots는 나중에 확인)
        is_item = bool(link_rx and link_rx.search(url)) and link_allowed(url, site)
        if is_attach:
            name = _link_label(n) or urllib.parse.unquote(url.rsplit("/", 1)[-1])
            attachments.setdefault(url, {"url": url, "name": name[:200], "ext": _ext(url)})
        if not (is_item or (is_attach and link_rx is None)):
            continue                          # link_pattern이 없으면 첨부 링크 자체가 항목이다
        ctx = _context(n)
        hint = select_first(n, site.get("title_hint")) or select_first(ctx, site.get("title_hint"))
        title = _clean_title(hint.text() if hint else "") or _clean_title(_link_label(n))
        if len(title) < 2:
            continue
        row_text = ctx.text()
        summ_node = select_first(ctx, site.get("summary_hint"))
        summary = summ_node.text() if summ_node else None
        date, year = _parse_date(f"{row_text} {url}", site.get("date_pattern"))
        row_att = []
        for a in ctx.iter():
            if a.attrs.get("href"):
                au = resolve_link(a, page_url, site)
                if au and pdf_rx.search(au) and urllib.parse.urlsplit(au).hostname in hosts:
                    row_att.append({"url": au, "name": (_link_label(a) or au.rsplit("/", 1)[-1])[:200],
                                    "ext": _ext(au)})
        prev = entries.get(url)
        if prev and len(prev["title"]) >= len(title):
            continue
        entries[url] = {"url": url, "title": title[:500], "row_text": row_text[:2000], "summary": summary,
                        "date": date, "year": year, "attachments": row_att, "is_attachment": is_attach,
                        "page": page_url}
    return list(entries.values()), list(attachments.values()), root


def _ext(url: str) -> str:
    m = ATTACH_EXT.search(url)
    return m.group(1).lower() if m else ""


def page_meta(root: Node) -> dict:
    """상세 페이지의 제목·요약·라이선스(공공누리)."""
    meta: dict = {}
    title = None
    for n in root.iter():
        if n.tag == "meta":
            p = (n.attrs.get("property") or n.attrs.get("name") or "").lower()
            c = clean_text(n.attrs.get("content"))
            if p in ("og:description", "description") and c and "summary" not in meta:
                meta["summary"] = c
            elif p == "og:title" and c:
                title = title or c
        elif n.tag == "title" and title is None:
            title = n.text() or None
        elif n.tag == "a":
            m = re.search(r"kogl\.or\.kr/info/licenseType(\d)", n.attrs.get("href") or "")
            if m and "license" not in meta:
                meta["license"] = f"공공누리 제{m.group(1)}유형"
        elif n.tag == "img" and "license" not in meta:
            m = re.search(r"공공누리[, ]*제?\s*(\d)\s*유형", n.attrs.get("alt") or "")
            if m:
                meta["license"] = f"공공누리 제{m.group(1)}유형"
    if title:
        meta["title"] = _clean_title(re.sub(r"^\[[^\]]{1,10}\]\s*", "", title))
    return meta


# ================================================================ 검색어 맞추기

def _norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s or "").lower())


def query_terms(query: str) -> list[str]:
    q = unicodedata.normalize("NFKC", query or "")
    q = re.sub(r"\b(AND|OR|NOT)\b", " ", q)
    terms = [re.sub(r"[\"'()\[\]{}+*]", "", t) for t in q.split()]
    return [_norm(t) for t in terms if _norm(t)]


def matches(terms: list[str], *texts: str | None) -> bool:
    """모든 검색어가 제목·요약 등에 들어 있는가(대소문자·띄어쓰기 무시 — '사과 박'도 '사과박'에 맞음)."""
    if not terms:
        return True
    hay = _norm(" ".join(t for t in texts if t))
    return all(t in hay for t in terms)


# ================================================================ 한 사이트 훑기

class CrawlReport:
    def __init__(self, site: dict):
        self.site_id = site.get("id")
        self.name = site.get("name")
        self.backend = site.get("backend") or "direct"
        self.pages = 0
        self.skipped: list[str] = []
        self.messages: list[str] = []
        self.robots_ok = True
        self.backend_ready = True

    def to_dict(self) -> dict:
        return {"site_id": self.site_id, "name": self.name, "backend": self.backend, "pages": self.pages,
                "robots_ok": self.robots_ok, "backend_ready": self.backend_ready,
                "skipped": self.skipped[:20], "messages": self.messages[:20]}


class _Crawl:
    """크롤 한 번의 상태. 방식(direct·browser·apify)과 상관없이 같은 규칙으로 페이지를 받아들인다."""

    def __init__(self, site: dict, rep: CrawlReport, terms: list[str], budget: int, max_depth: int):
        self.site, self.rep, self.terms, self.budget, self.max_depth = site, rep, terms, budget, max_depth
        self.items: dict[str, dict] = {}
        self.seen: set[str] = set()
        self.site_desc: set[str] = set()
        self.queue: list[tuple[str, int, str | None]] = []      # (주소, 깊이, 항목 열쇠)
        self.hosts = _hosts(site)

    def robots_allows(self, url: str, depth: int) -> "Robots | None":
        """robots.txt가 허용하면 Robots, 막으면 None(이유를 남김)."""
        rb = robots_for(url)
        if rb.can_fetch(url):
            return rb
        self.rep.skipped.append(url)
        msg = f"robots.txt가 막은 주소라 건너뜀: {url}" if not rb.deny_all else f"{rb.note}: {url}"
        self.rep.messages.append(msg)
        if depth == 0:
            self.rep.robots_ok = False
        return None

    def accept(self, page_url: str, html: str, depth: int, owner: str | None, *, follow: bool) -> None:
        """받은 페이지 한 장을 읽는다: 항목 뽑기, 상세 페이지면 항목 보강, follow면 상세 주소를 줄에 넣는다."""
        site, items = self.site, self.items
        self.rep.pages += 1
        entries, attachments, root = extract_entries(html, page_url, site)
        if depth == 0:
            d0 = page_meta(root).get("summary")
            if d0:
                self.site_desc.add(d0)                        # 사이트 공통 설명(요약으로 쓰지 않음)
        if owner and owner in items:                          # 상세 페이지 → 그 항목을 보강
            it = items[owner]
            meta = page_meta(root)
            if not it.get("summary"):
                sn = select_first(root, site.get("summary_hint"))
                st = sn.text() if sn else None
                if not st and meta.get("summary") and meta["summary"] not in self.site_desc:
                    st = meta["summary"]
                if st:
                    it["summary"] = st[:MAX_SUMMARY]
            if meta.get("license"):
                it["license"] = meta["license"]
            if not it.get("date"):
                d, y = _parse_date(root.text()[:5000], site.get("date_pattern"))
                it["date"], it["year"] = it.get("date") or d, it.get("year") or y
            known = {a["url"] for a in it["attachments"]}
            for a in attachments:
                if a["url"] not in known and a["url"] != it["url"]:
                    it["attachments"].append(a)
                    known.add(a["url"])
            it["detail_fetched"] = True
        for e in entries:
            k = e["url"]
            if k in items or k == page_url:
                continue
            e["depth"] = depth
            items[k] = e
            hit = matches(self.terms, e["title"], e.get("summary"), e["row_text"])
            e["hit"] = hit
            if follow and hit and not e["is_attachment"] and depth + 1 <= self.max_depth:
                self.queue.append((k, depth + 1, k))
        # 검색어가 맞는 상세 페이지를 먼저 본다(쪽수 예산을 아끼기 위해)
        self.queue.sort(key=lambda x: x[1])

    # ---- 쪽 단위 방식(direct·browser): 주소마다 robots·간격을 지킨 뒤 받는다
    def run_paged(self, session, seeds: list[str]) -> None:
        self.queue = [(u, 0, None) for u in seeds]
        while self.queue and self.rep.pages < self.budget:
            url, depth, owner = self.queue.pop(0)
            if url in self.seen:
                continue
            self.seen.add(url)
            rb = self.robots_allows(url, depth)
            if rb is None:
                continue
            _apply_interval(url, self.site.get("interval_s") or MIN_INTERVAL_S, rb)
            try:
                pg = session.fetch(url)
            except FetchError as e:
                self.rep.messages.append(f"페이지를 받지 못함: {e}")
                continue
            final = pg.final_url or url
            if final != url:                                  # 리디렉션: 다른 호스트·robots가 막은 곳이면 버린다
                if not backends.is_web_url(final) or urllib.parse.urlsplit(final).hostname not in self.hosts:
                    self.rep.skipped.append(final)
                    self.rep.messages.append(f"다른 사이트로 넘어가 버림: {url} → {final}")
                    continue
                if not robots_for(final).can_fetch(final):
                    self.rep.skipped.append(final)
                    self.rep.messages.append(f"robots.txt가 막은 주소로 넘어가 버림: {final}")
                    continue
            if pg.note:
                self.rep.messages.append(pg.note)
            self.accept(final, pg.html or "", depth, owner, follow=True)

    # ---- 일괄 방식(apify): 받은 페이지를 같은 규칙으로 거른다(시작 주소·허용 경로·robots·깊이·쪽수)
    def run_bulk(self, be, seeds: list[str]) -> None:
        pages, notes = be.crawl(self.site, seeds, self.budget, self.max_depth)
        self.rep.messages.extend(notes)
        seed_set = set(seeds)

        def depth_of(pg):
            if pg.url in seed_set or pg.final_url in seed_set:
                return 0
            return pg.depth if isinstance(pg.depth, int) and pg.depth >= 1 else 1
        dropped = outside = 0
        for pg in sorted(pages, key=depth_of):               # 목록(깊이 0)을 먼저 읽어야 상세가 항목에 붙는다
            url = pg.final_url or pg.url
            depth = depth_of(pg)
            if url in self.seen:
                continue
            self.seen.add(url)
            if self.rep.pages >= self.budget:
                dropped += 1
                continue
            if not backends.is_web_url(url) or urllib.parse.urlsplit(url).hostname not in self.hosts \
                    or (depth > 0 and not link_allowed(url, self.site)) or depth > self.max_depth:
                self.rep.skipped.append(url)
                outside += 1
                continue
            if self.robots_allows(url, depth) is None:
                continue
            if pg.status is not None and pg.status >= 400:
                self.rep.messages.append(f"페이지를 받지 못함: HTTP {pg.status}: {url.split('?')[0]}")
                continue
            owner = url if url in self.items else (pg.url if pg.url in self.items else None)
            self.accept(url, pg.html or "", depth, owner, follow=False)
        if dropped:
            self.rep.messages.append(f"쪽수 제한({self.budget}쪽)을 넘어 받은 {dropped}쪽은 버렸습니다.")
        if outside:
            self.rep.messages.append(f"허용 경로·깊이 규칙에 맞지 않아 버린 페이지 {outside}쪽")


def _seeds(site: dict, query: str, bulk: bool) -> list[str]:
    if bulk:                                  # 일괄(클라우드) 방식에는 검색어를 보내지 않는다 → 시작 주소만, 거르기는 이 PC에서
        return list(site.get("start_urls", []))
    if site.get("search_urls") and query.strip():
        q = urllib.parse.quote(query.strip())
        return [u.replace("{q}", q) for u in site["search_urls"]]
    return list(site.get("start_urls", []))   # 사이트 검색이 있으면 그 결과만 본다(쪽수 예산 절약)


def crawl_site(site: dict | str, query: str, *, limit: int = 25, since_year: int | None = None,
               max_pages: int | None = None) -> tuple[list[Item], CrawlReport]:
    """사이트 하나를 예의 바르게 훑어 검색어와 맞는 Item을 돌려준다(가져오기 방식은 site['backend'])."""
    if isinstance(site, str):
        site = get_site(site)
    rep = CrawlReport(site)
    budget = min(HARD_MAX_PAGES, int(max_pages or site.get("max_pages") or DEFAULT_MAX_PAGES))
    max_depth = min(HARD_MAX_DEPTH, max(1, int(site.get("max_depth") or DEFAULT_MAX_DEPTH)))
    terms = query_terms(query)
    bkey = site.get("backend") or "direct"
    run = _Crawl(site, rep, terms, budget, max_depth)
    try:
        be = backends.get(bkey)
        if be.bulk:
            run.run_bulk(be, _seeds(site, query, True))
        else:
            with be.open(site) as session:
                run.run_paged(session, _seeds(site, query, False))
    except BackendUnavailable as e:
        rep.backend_ready = False
        rep.messages.append(f"{backends.LABELS.get(bkey, bkey)}: {e}")
        return [], rep
    except FetchError as e:
        rep.messages.append(f"{backends.LABELS.get(bkey, bkey)}: {e}")

    out: list[Item] = []
    for e in run.items.values():
        if not matches(terms, e["title"], e.get("summary"), e["row_text"]):
            continue
        if since_year and e.get("year") and e["year"] < since_year:
            continue
        out.append(_to_item(site, e, rb_allowed=lambda u: robots_for(u).can_fetch(u)))
        if len(out) >= limit:
            break
    if rep.pages == 0 and not rep.messages:
        rep.messages.append("가져온 페이지가 없습니다. 시작 주소를 확인하세요.")
    return out, rep


def _to_item(site: dict, e: dict, rb_allowed) -> Item:
    atts = [a for a in e.get("attachments", []) if rb_allowed(a["url"])]
    if e.get("is_attachment"):
        atts = [{"url": e["url"], "name": e["title"], "ext": _ext(e["url"])}] + \
               [a for a in atts if a["url"] != e["url"]]
    pdf = next((a["url"] for a in atts if a["ext"] == "pdf"), None)
    doc_type = site.get("doc_type") or ("report" if atts else "web")
    sid = hashlib.sha1(e["url"].encode("utf-8")).hexdigest()[:16]
    summary = e.get("summary")
    if summary and len(summary) > MAX_SUMMARY:
        summary = summary[:MAX_SUMMARY] + "…"
    return Item(
        source="crawler", source_id=f"{site['id']}:{sid}", title=e["title"], year=e.get("year"),
        venue=site.get("venue") or site.get("name"), abstract=summary, url=e["url"], pdf_url=pdf,
        oa=True if pdf else None, language="ko", doc_type=doc_type, license=e.get("license"),
        extra={"site_id": site["id"], "site_name": site.get("name"), "date": e.get("date"),
               "listing_url": e.get("page"), "attachments": atts[:20],
               "detail_fetched": bool(e.get("detail_fetched"))},
    ).normalized()


# ================================================================ 점검·전체 검색

def check_site(site_id: str) -> dict:
    """robots.txt로 시작·검색 주소를 가져갈 수 있는지 점검한다(목록 페이지 자체는 받지 않는다)."""
    site = get_site(site_id)
    urls = list(site.get("start_urls", [])) + [u.replace("{q}", "test") for u in site.get("search_urls", [])]
    ok, lines = True, []
    for u in urls:
        try:
            rb = robots_for(u)
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f"{u}: robots.txt 확인 실패({e})")
            continue
        if rb.can_fetch(u):
            cd = rb.crawl_delay()
            gap = max(MIN_INTERVAL_S, float(site.get("interval_s") or 0), cd or 0)
            if any(urllib.parse.urlsplit(u).path in ln and ln.startswith("허용") for ln in lines):
                continue                       # 같은 경로(목록·검색 주소)는 한 번만 적는다
            lines.append(f"허용 — {urllib.parse.urlsplit(u).path or '/'} ({rb.note}, 간격 {gap:g}초"
                         + (f", Crawl-delay {cd:g}초" if cd else "") + ")")
        else:
            ok = False
            lines.append(f"막힘 — {u} ({rb.note}). 이 사이트는 자동 수집에서 빠집니다.")
    terms = site.get("terms_url")
    if not terms:
        lines.append("이용약관 주소가 없습니다. 사이트의 저작권 정책·이용약관을 직접 확인한 뒤 켜세요.")
    bkey = site.get("backend") or "direct"
    try:
        bst = backends.get(bkey).status()
    except Exception as e:  # noqa: BLE001
        bst = {"ready": False, "message": f"상태를 확인하지 못했습니다: {e}"}
    if bkey != "direct":
        lines.append(f"가져오기 방식 {backends.LABELS.get(bkey, bkey)} — {bst.get('message', '')}")
        if bkey == "apify" and ok and any((robots_for(u).crawl_delay() or 0) > MIN_INTERVAL_S for u in urls):
            lines.append("주의: 이 사이트는 robots Crawl-delay가 있는데 Apify는 Crawl-delay를 지원하지 않습니다"
                         "(한 번에 한 쪽씩만 요청하도록 설정). 가능하면 기본·브라우저 방식을 쓰세요.")
    return {"robots_ok": ok, "terms_url": terms, "message": " / ".join(lines), "backend": bkey,
            "backend_ready": bool(bst.get("ready")), "backend_message": bst.get("message", "")}


def backend_status() -> dict:
    """가져오기 방식별 준비 상태 — {direct:{ready}, browser:{ready, how, message}, apify:{ready, message}}."""
    return backends.backend_status()


def test_crawl(site_id: str, query: str = "", max_pages: int = TEST_MAX_PAGES) -> dict:
    """시험 수집: 작은 크롤(최대 3쪽)로 찾은 제목을 보여 준다. 수집함에는 넣지 않는다."""
    site = get_site(site_id)
    n = max(1, min(TEST_MAX_PAGES, int(max_pages or TEST_MAX_PAGES)))
    items, rep = crawl_site(site, query or "", limit=20, max_pages=n)
    return {**rep.to_dict(), "query": query or "", "max_pages": n,
            "items": [{"title": i.title, "url": i.url, "date": (i.extra or {}).get("date"), "year": i.year,
                       "pdf_url": i.pdf_url} for i in items]}


test_crawl.__test__ = False      # pytest가 이 함수를 시험으로 모으지 않게


_last_reports: list[dict] = []


def last_reports() -> list[dict]:
    """마지막 search()의 사이트별 결과(쪽수·건너뛴 주소·메시지)."""
    return list(_last_reports)


def search_all(query: str, *, limit: int = 25, since_year: int | None = None,
               site_ids: list[str] | None = None) -> tuple[list[Item], list[dict]]:
    sites = [s for s in list_sites() if s.get("enabled")]
    if site_ids:
        sites = [s for s in list_sites() if s["id"] in site_ids]
    results: list[Item] = []
    reports: list[dict] = []
    if not sites:
        return [], []

    def run(s):
        try:
            return crawl_site(s, query, limit=limit, since_year=since_year)
        except Exception as e:  # noqa: BLE001 — 한 사이트가 깨져도 나머지는 쓴다
            r = CrawlReport(s)
            r.messages.append(f"크롤링 실패: {e}")
            return [], r

    with ThreadPoolExecutor(max_workers=min(MAX_SITES_PARALLEL, len(sites))) as ex:
        for its, rep in ex.map(run, sites):
            results.extend(its)
            reports.append(rep.to_dict())
    _last_reports[:] = reports
    seen, uniq = set(), []
    for it in results:
        if it.url in seen:
            continue
        seen.add(it.url)
        uniq.append(it)
    return uniq[:limit], reports
