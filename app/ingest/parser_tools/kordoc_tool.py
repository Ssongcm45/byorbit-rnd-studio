"""kordoc (Node) — 한글 문서 전용 파서. HWP(구 형식, 5.x)·HWPX·PDF를 읽는다.

npm 패키지 kordoc(MIT)을 Node로 돌리고(kordoc_bridge.mjs), 결과 블록(IRBlock)을 우리 블록으로 바꾼다.
찾는 순서: 환경 변수 BYORBIT_KORDOC_DIR → 이 저장소의 tools/node(install-kordoc.bat이 설치)
          → 옆 폴더 04_byorbit-agent(이미 설치된 것을 읽기 전용으로 사용).
PDF는 pdfjs-dist가 같이 있어야 한다(install-kordoc.bat이 함께 설치). 문서는 PC 밖으로 나가지 않는다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from ... import config
from .base import NotReady, Tool, ToolError, grid_from_spans, looks_like_heading, table_or_text

BRIDGE = Path(__file__).with_name("kordoc_bridge.mjs")
MARK = "@@KORDOC_JSON@@"   # 다리 스크립트가 결과 줄 앞에 붙이는 표시(pdfjs 경고 출력과 섞이지 않게)
HINT = ("kordoc을 찾지 못했습니다. install-kordoc.bat을 실행하세요(Node.js 18 이상 필요, 약 100MB). "
        "이미 다른 폴더에 설치했다면 환경 변수 BYORBIT_KORDOC_DIR에 그 폴더(node_modules가 있는 곳)를 지정하세요.")
NODE_HINT = "Node.js가 없습니다. https://nodejs.org 에서 LTS를 설치(또는 winget install OpenJS.NodeJS.LTS)한 뒤 앱을 다시 켜세요."
TIMEOUT_SEC = 300

_version_cache: dict[str, str | None] = {}


def node_exe() -> str | None:
    return os.environ.get("BYORBIT_NODE") or shutil.which("node")


def candidates() -> list[Path]:
    out = []
    env = os.environ.get("BYORBIT_KORDOC_DIR", "").strip()
    if env:
        out.append(Path(env))
    out.append(config.APP_ROOT / "tools" / "node")
    out.append(config.APP_ROOT.parent / "04_byorbit-agent")
    return out


def _entry_in(d: Path) -> Path | None:
    for p in (d / "node_modules" / "kordoc" / "dist" / "index.js", d / "dist" / "index.js"):
        if p.is_file() and (p.parent.parent / "package.json").is_file():
            try:
                if json.loads((p.parent.parent / "package.json").read_text(encoding="utf-8")).get("name") == "kordoc":
                    return p
            except (OSError, json.JSONDecodeError):
                continue
    return None


def find_kordoc() -> tuple[Path | None, Path | None]:
    """(kordoc dist/index.js, 찾은 폴더)."""
    for d in candidates():
        e = _entry_in(d)
        if e:
            return e, d
    return None, None


def has_pdfjs(entry: Path) -> bool:
    """kordoc이 pdfjs-dist를 불러올 수 있는지(Node 모듈 찾기 규칙을 흉내: 실제 위치에서 위로 올라가며)."""
    pkg = Path(os.path.realpath(entry)).parent.parent
    for d in [pkg, *pkg.parents]:
        if (d / "node_modules" / "pdfjs-dist" / "package.json").is_file():
            return True
        if d.name == "node_modules" and (d / "pdfjs-dist" / "package.json").is_file():
            return True
    return False


def _status() -> dict:
    if not node_exe():
        return {"ready": False, "message": "Node.js가 없습니다.", "hint": NODE_HINT}
    entry, where = find_kordoc()
    if not entry:
        return {"ready": False, "message": "kordoc이 설치되어 있지 않습니다.", "hint": HINT}
    detail = f"위치: {where}"
    if not has_pdfjs(entry):
        detail += " · PDF는 pdfjs-dist가 없어 못 읽습니다(HWP·HWPX만). PDF도 쓰려면 install-kordoc.bat을 실행하세요."
    return {"ready": True, "detail": detail, "pdf": has_pdfjs(entry)}


def _run_bridge(entry: Path, file_arg: str, options: dict, timeout: int = TIMEOUT_SEC) -> dict:
    node = node_exe()
    if not node:
        raise NotReady(NODE_HINT)
    args = [node, str(BRIDGE), str(entry), file_arg]
    if options:
        args.append(json.dumps(options, ensure_ascii=False))
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"kordoc이 {timeout}초 안에 끝나지 않았습니다. 문서가 매우 크면 쪽 범위를 나눠 보세요.") from e
    raw = p.stdout.decode("utf-8", errors="replace")
    line = next((ln[len(MARK):] for ln in raw.splitlines() if ln.startswith(MARK)), raw.strip())
    try:
        return json.loads(line)
    except json.JSONDecodeError as e:
        err = p.stderr.decode("utf-8", errors="replace").strip()[-400:]
        raise ToolError(f"kordoc 결과를 읽지 못했습니다(종료 코드 {p.returncode}): {err or raw[:300]}") from e


def _version() -> str | None:
    entry, _ = find_kordoc()
    if not entry or not node_exe():
        return None
    key = str(entry)
    if key not in _version_cache:
        try:
            _version_cache[key] = _run_bridge(entry, "--version", {}, timeout=30).get("version")
        except ToolError:
            _version_cache[key] = None
    return _version_cache[key]


_ERR = {
    "MISSING_DEPENDENCY": "PDF를 읽으려면 pdfjs-dist가 필요합니다. install-kordoc.bat을 실행하세요(kordoc과 pdfjs-dist를 함께 설치).",
    "ENCRYPTED": "암호가 걸린 문서입니다. 한글에서 암호를 푼 뒤 다시 넣으세요.",
    "DRM_PROTECTED": "DRM(문서 보안)이 걸린 문서라 읽을 수 없습니다. 보안을 해제한 사본을 넣으세요.",
    "IMAGE_BASED_PDF": ("kordoc(pdfjs)이 이 PDF에서 글자를 읽지 못했습니다. 스캔본이면 RapidOCR 도구를, 글자가 있는 PDF인데 "
                        "이 메시지가 나오면(한글 CID 글꼴은 pdfjs가 cMap 없이 못 읽는 경우가 있음) PyMuPDF·pdfplumber를 쓰세요."),
    "CORRUPTED": "파일이 손상되었습니다. 원본을 다시 저장해 넣으세요.",
    "UNSUPPORTED_FORMAT": "kordoc이 읽지 못하는 형식입니다.",
}


def _list_text(b: dict, depth: int = 0) -> list[str]:
    lines = []
    ordered = b.get("listType") == "ordered"
    for i, ch in enumerate(b.get("children") or [], start=1):
        if ch.get("type") == "list":
            lines.extend(_list_text(ch, depth + 1))
            continue
        t = (ch.get("text") or "").strip()
        if t:
            lines.append(("  " * depth) + (f"{i}. " if ordered else "- ") + t)
        if ch.get("children"):
            lines.extend(_list_text({"children": ch["children"], "listType": b.get("listType")}, depth + 1))
    if not lines and (b.get("text") or "").strip():
        lines.append(b["text"].strip())
    return lines


def convert(result: dict) -> dict:
    """kordoc 결과(JSON) → {"blocks", "meta"}. 시험은 기록해 둔 결과로 이 함수만 검증한다."""
    if not result.get("success"):
        code = result.get("code") or ""
        raise ToolError(_ERR.get(code) or f"kordoc 실패: {result.get('error') or code}")
    blocks, skipped = [], {}
    for b in result.get("blocks") or []:
        t = b.get("type")
        page = b.get("pageNumber")
        if t == "table":
            tb = b.get("table") or {}
            rows = grid_from_spans(tb.get("cells") or [], tb.get("rows"), tb.get("cols"))
            blk = table_or_text(rows, page)
            if blk:
                blocks.append(blk)
            continue
        if t == "heading":
            txt = (b.get("text") or "").strip()
            if txt:
                blocks.append({"type": "heading", "text": txt, "level": int(b.get("level") or 1), "page": page})
            continue
        if t == "list":
            txt = "\n".join(_list_text(b))
            if txt:
                blocks.append({"type": "text", "text": txt, "page": page})
            continue
        if t == "paragraph":
            txt = (b.get("text") or "").strip()
            if b.get("footnoteText"):
                txt = f"{txt} (주: {b['footnoteText'].strip()})"
            if not txt:
                continue
            if looks_like_heading(txt, 60):   # HWP 문단은 제목 정보가 없을 때가 많다 — 기존 HWPX 파서와 같은 규칙
                blocks.append({"type": "heading", "text": txt, "level": 1, "page": page})
            else:
                blocks.append({"type": "text", "text": txt, "page": page})
            continue
        skipped[t or "?"] = skipped.get(t or "?", 0) + 1
    warnings = [str(w.get("message") if isinstance(w, dict) else w) for w in result.get("warnings") or []][:50]
    if skipped:
        warnings.append("건너뛴 블록: " + ", ".join(f"{k} {v}개" for k, v in sorted(skipped.items())))
    meta = {"pages": result.get("pageCount") or (result.get("metadata") or {}).get("pageCount"),
            "file_type": result.get("fileType"), "title": (result.get("metadata") or {}).get("title"),
            "warnings": warnings, "needs_ocr": bool(result.get("isImageBased"))}
    if result.get("fileType") in ("hwp", "hwpx"):
        meta["page_unit"] = "section"   # HWP·HWPX의 '쪽'은 구역(section) 단위 근사치
    return {"blocks": blocks, "meta": meta}


def _parse(path, options: dict) -> dict:
    entry, _ = find_kordoc()
    if not entry:
        raise NotReady(HINT)
    path = Path(path)
    if path.suffix.lower() == ".pdf" and not has_pdfjs(entry):
        raise NotReady(_ERR["MISSING_DEPENDENCY"])
    opts = {k: options[k] for k in ("pages", "removeHeaderFooter") if options.get(k)}
    return convert(_run_bridge(entry, str(path), opts, int(options.get("timeout") or TIMEOUT_SEC)))


TOOL = Tool(
    key="kordoc", name="kordoc (한글 문서)", formats={".hwp", ".hwpx", ".pdf"}, kind="local",
    description="한글 문서 전용 파서(Node). 구 형식 HWP(5.x)까지 읽고, 병합 셀 표·목록·각주를 살립니다. PDF도 읽습니다(pdfjs-dist 필요).",
    strengths="구 형식 .hwp · 병합 셀 표 · 공공기관 문서 · 로컬",
    install_hint=HINT, parse_fn=_parse, status_fn=_status, version_fn=_version, slow=True,
    options=[{"key": "removeHeaderFooter", "label": "PDF 머리글·바닥글 빼기", "type": "bool", "default": False}],
)
