"""Upstage Document Parse (클라우드) — 문서 파일을 Upstage 서버로 보내 레이아웃 분석 결과를 받는다.

!! 이 도구만 문서 파일을 PC 밖으로 보낸다 !!
- '기밀' 문서는 무조건 막는다(화면·API·이 모듈 세 곳에서 확인). 보안 등급을 모르면 보내지 않는다.
- '내부' 문서는 실행할 때마다 화면에서 '보낸다'를 확인해야 한다(confirm_cloud).
- 키: 환경 변수 BYORBIT_UPSTAGE_KEY (설정 파일·DB에 저장하지 않는다). 오류 메시지에서 키를 가린다.

공식 문서(2026-11-25 확인):
- API: https://console.upstage.ai/api/parse/document-parsing
  POST https://api.upstage.ai/v1/document-digitization, Authorization: Bearer <키>, multipart/form-data
  필드 document(파일)·model(document-parse)·mode(standard|enhanced|auto)·ocr(auto|force)·output_formats·coordinates
  응답 elements[]: category·content{html,markdown,text}·page·id, usage.pages
- 기능 안내: https://console.upstage.ai/docs/capabilities/document-digitization/document-parsing (동기 API 100쪽까지)
- 요금: https://www.upstage.ai/pricing — Document Parse Standard $0.01/쪽, Enhanced $0.03/쪽(부가세 10% 별도)
"""
from __future__ import annotations

import json
import os
import uuid
from html.parser import HTMLParser
from pathlib import Path

from ...collect import http
from .base import IMAGE_EXTS, CloudBlocked, NeedsConfirm, NotReady, Tool, ToolError, table_block

ENDPOINT = "https://api.upstage.ai/v1/document-digitization"
KEY_ENV = "BYORBIT_UPSTAGE_KEY"
DOCS_URL = "https://console.upstage.ai/api/parse/document-parsing"
PRICING_URL = "https://www.upstage.ai/pricing"
CHECKED = "2026-11-25"
PRICE_USD = {"standard": 0.01, "enhanced": 0.03, "auto": 0.03}   # 쪽당, 부가세 별도. auto는 쪽마다 정해져 최대치로 잡는다
SYNC_MAX_PAGES = 100
MAX_MB = 50
TIMEOUT_SEC = 300
HINT = (f"Upstage 콘솔(https://console.upstage.ai)에서 API 키를 만든 뒤 설정 → API 키 관리의 {KEY_ENV}에 넣으세요(또는 같은 이름의 환경 변수). "
        "쪽당 요금이 듭니다.")
BLOCK_MSG = ("'기밀' 문서는 클라우드 파서(Upstage)로 보낼 수 없습니다. 로컬 도구(PyMuPDF·pdfplumber·RapidOCR·"
             "Docling·kordoc)를 쓰세요. 꼭 보내야 하면 먼저 자료의 보안 등급을 바꾸세요.")

http.set_interval("api.upstage.ai", 0.5)


def _key() -> str:
    return os.environ.get(KEY_ENV, "").strip()


def _status() -> dict:
    if not _key():
        return {"ready": False, "message": f"API 키({KEY_ENV})가 없습니다.", "hint": HINT}
    return {"ready": True, "detail": "실행하면 문서 파일이 Upstage 서버로 전송됩니다. '기밀' 문서는 막힙니다."}


def guard(confidentiality: str | None, confirmed: bool) -> None:
    """보내도 되는지 확인. 기밀 → CloudBlocked, 모름 → CloudBlocked, 내부 + 미확인 → NeedsConfirm."""
    if confidentiality == "기밀":
        raise CloudBlocked(BLOCK_MSG)
    if confidentiality not in ("일반", "내부"):
        raise CloudBlocked("보안 등급을 알 수 없어 클라우드로 보내지 않습니다. 자료의 보안 등급을 확인하세요.")
    if confidentiality == "내부" and not confirmed:
        raise NeedsConfirm("'내부' 문서입니다. 문서 파일이 Upstage 서버로 전송된다는 것을 확인한 뒤 다시 실행하세요.")


def page_count(path: Path) -> int | None:
    if path.suffix.lower() == ".pdf":
        try:
            import pymupdf
            with pymupdf.open(str(path)) as d:
                return d.page_count
        except Exception:  # noqa: BLE001
            return None
    if path.suffix.lower() in IMAGE_EXTS:
        return 1
    return None


def estimate(path, options: dict) -> dict:
    path = Path(path)
    mode = options.get("mode") or "standard"
    pages = page_count(path)
    usd = round(pages * PRICE_USD.get(mode, 0.03), 4) if pages else None
    return {"pages": pages, "mode": mode, "usd": usd, "usd_per_page": PRICE_USD.get(mode),
            "vat_note": "부가세 10% 별도", "pricing_url": PRICING_URL, "checked": CHECKED,
            "size_mb": round(path.stat().st_size / 1e6, 2) if path.exists() else None,
            "message": (f"약 {pages}쪽 × ${PRICE_USD.get(mode)} = ${usd} (부가세 별도, {CHECKED} 확인 요금)"
                        if pages else "쪽 수를 미리 알 수 없습니다(HWP 등). 요금은 Upstage 사용량 화면에서 확인하세요.")}


def build_request(path: Path, options: dict) -> tuple[bytes, dict]:
    """multipart/form-data 본문과 헤더. 시험은 이 결과(가짜 opener가 받은 요청)를 검사한다."""
    boundary = "byorbit" + uuid.uuid4().hex
    fields = {
        "model": options.get("model") or "document-parse",
        "mode": options.get("mode") or "standard",
        "ocr": "force" if options.get("ocr") == "force" else "auto",
        "output_formats": "['html', 'text']",
        "coordinates": "false",
    }
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8"))
    # 파일 이름은 확장자만 남긴다(파일명에 과제명·업체명이 들어 있을 수 있다)
    safe_name = "document" + path.suffix.lower()
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{safe_name}"\r\n'
                  f"Content-Type: application/octet-stream\r\n\r\n").encode("utf-8") + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    headers = {"Authorization": f"Bearer {_key()}", "Content-Type": f"multipart/form-data; boundary={boundary}",
               "Accept": "application/json"}
    return body, headers


class _TableHTML(HTMLParser):
    """<table> HTML → 행 목록. colspan·rowspan은 빈 칸으로 채워 격자를 맞춘다."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._span = (1, 1)
        self._pending: dict[tuple[int, int], str] = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
            self._span = (int(a.get("colspan") or 1), int(a.get("rowspan") or 1))
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            ri = len(self.rows)
            while (ri, len(self._row)) in self._pending:
                self._row.append(self._pending.pop((ri, len(self._row))))
            cs, rs = self._span
            ci = len(self._row)
            self._row.append(" ".join("".join(self._cell).split()))
            self._row.extend([""] * (cs - 1))
            for dr in range(1, rs):
                for dc in range(cs):
                    self._pending[(ri + dr, ci + dc)] = ""
            self._cell = None
        elif tag == "tr" and self._row is not None:
            ri = len(self.rows)
            while (ri, len(self._row)) in self._pending:
                self._row.append(self._pending.pop((ri, len(self._row))))
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def html_table_rows(html: str) -> list[list[str]]:
    p = _TableHTML()
    p.feed(html or "")
    return p.rows


def _html_text(html: str) -> str:
    class T(HTMLParser):
        def __init__(self):
            super().__init__()
            self.buf = []

        def handle_data(self, d):
            self.buf.append(d)

        def handle_starttag(self, tag, attrs):
            if tag in ("br", "p", "li"):
                self.buf.append(" ")
    t = T()
    t.feed(html or "")
    return " ".join("".join(t.buf).split())


SKIP = {"header", "footer", "figure"}


def convert(resp: dict) -> dict:
    """Upstage 응답 JSON → {"blocks", "meta"}."""
    blocks, skipped = [], {}
    for el in resp.get("elements") or []:
        cat = str(el.get("category") or "").lower()
        content = el.get("content") or {}
        html, text = content.get("html") or "", (content.get("text") or "").strip()
        page = el.get("page")
        if cat == "table" or (cat == "chart" and "<table" in html):
            blk = table_block(html_table_rows(html), page)
            if blk:
                blocks.append(blk)
            continue
        if cat in SKIP:
            skipped[cat] = skipped.get(cat, 0) + 1
            continue
        text = text or _html_text(html)
        if not text:
            continue
        if cat.startswith("heading") or cat == "title":
            digits = "".join(ch for ch in cat if ch.isdigit())
            blocks.append({"type": "heading", "text": text, "level": int(digits or 1), "page": page})
        else:   # paragraph·list·caption·footnote·equation·index·chart(표 아님)
            blocks.append({"type": "text", "text": text, "page": page})
    usage = resp.get("usage") or {}
    warnings = []
    if skipped:
        warnings.append("건너뛴 요소: " + ", ".join(f"{k} {v}개" for k, v in sorted(skipped.items())))
    pages = usage.get("pages") or max((b["page"] for b in blocks if b.get("page")), default=None)
    return {"blocks": blocks, "meta": {"pages": pages, "model": resp.get("model"), "api": resp.get("api"),
                                       "billed_pages": usage.get("pages"), "warnings": warnings, "cloud": True}}


def _parse(path, options: dict) -> dict:
    guard(options.get("confidentiality"), bool(options.get("confirm_cloud")))
    if not _key():
        raise NotReady(HINT)
    path = Path(path)
    if path.stat().st_size > MAX_MB * 1_000_000:
        raise ToolError(f"Upstage는 {MAX_MB}MB까지만 받습니다. 파일을 나눠 넣으세요.")
    n = page_count(path)
    if n and n > SYNC_MAX_PAGES:
        raise ToolError(f"{n}쪽 문서입니다. 즉시 처리(동기) API는 {SYNC_MAX_PAGES}쪽까지라 나눠 넣어야 합니다.")
    body, headers = build_request(path, options)
    try:
        with http.request(ENDPOINT, None, headers, TIMEOUT_SEC, data=body, method="POST") as r:
            raw = r.read(200_000_000)
    except http.HttpError as e:
        msg = str(e).replace(_key(), "***") if _key() else str(e)
        if e.status in (401, 403):
            msg = f"Upstage가 키를 거절했습니다({e.status}). {KEY_ENV} 값을 확인하세요."
        elif e.status == 402:
            msg = "Upstage 크레딧·결제 정보를 확인하세요(402)."
        raise ToolError(msg) from e
    try:
        resp = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ToolError("Upstage 응답이 JSON이 아닙니다. 잠시 뒤 다시 시도하세요.") from e
    return convert(resp)


TOOL = Tool(
    key="upstage", name="Upstage Document Parse (클라우드)", formats={".pdf", ".hwp", ".hwpx"} | IMAGE_EXTS,
    kind="cloud",
    description="문서 파일을 Upstage 서버로 보내 레이아웃 분석(제목·표·읽기 순서) 결과를 받습니다. 한국어 스캔본·복잡한 표에 강합니다.",
    strengths="한국어 스캔본 · 복잡한 표 · 설치 없음 — 대신 파일이 PC 밖으로 나가고 쪽당 요금",
    install_hint=HINT, parse_fn=_parse, status_fn=_status, version_fn=lambda: "document-parse (API)", slow=True,
    estimate_fn=estimate,
    options=[{"key": "mode", "label": "모드", "type": "select",
              "choices": [["standard", "standard ($0.01/쪽)"], ["enhanced", "enhanced ($0.03/쪽)"],
                          ["auto", "auto (쪽마다 자동)"]], "default": "standard"},
             {"key": "ocr", "label": "OCR", "type": "select", "choices": [["auto", "자동"], ["force", "항상"]],
              "default": "auto"}],
)
