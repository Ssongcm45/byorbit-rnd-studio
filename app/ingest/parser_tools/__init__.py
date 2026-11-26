"""파서 도구 목록 — 문서마다 파서를 고르고, 다시 파싱하고, 결과를 나란히 비교한다(M3-2 묶음 P).

- 도구: pymupdf(기본 PDF)·pdfplumber·rapidocr(전 쪽 OCR)·hwpx·xlsx·text·docling(선택)·kordoc(Node)·upstage(클라우드)
- 형식별 기본 도구는 데이터 폴더 config/parsers.json에 저장하고 화면에서 바꾼다. 클라우드 도구는 기본으로 둘 수 없다
  (새로 들어오는 모든 파일이 자동으로 밖으로 나가게 되므로).
- 결과 저장·비교·선택은 parser_tools.results.
"""
from __future__ import annotations

import importlib
import json
import time
from pathlib import Path

from ... import config
from .base import CloudBlocked, NeedsConfirm, NotReady, Tool, ToolError, stats  # noqa: F401

MODULES = ["pymupdf_tool", "pdfplumber_tool", "rapidocr_tool", "hwpx_tool", "xlsx_tool", "text_tool",
           "docling_tool", "kordoc_tool", "upstage_tool"]

# 형식 → 기본 도구(사용자 설정이 없을 때). 지금까지의 동작과 같다(+ .hwp는 kordoc).
BUILTIN_DEFAULTS = {".pdf": "pymupdf", ".hwpx": "hwpx", ".hwp": "kordoc", ".xlsx": "xlsx", ".xlsm": "xlsx",
                    ".txt": "text", ".md": "text", ".csv": "text",
                    ".png": "rapidocr", ".jpg": "rapidocr", ".jpeg": "rapidocr", ".tif": "rapidocr", ".tiff": "rapidocr"}

_tools: dict[str, Tool] | None = None
_load_errors: dict[str, str] = {}


def tools(reload: bool = False) -> dict[str, Tool]:
    global _tools
    if _tools is None or reload:
        out = {}
        _load_errors.clear()
        for m in MODULES:
            try:
                mod = importlib.import_module(f"{__name__}.{m}")
                if reload:
                    mod = importlib.reload(mod)
                out[mod.TOOL.key] = mod.TOOL
            except Exception as e:  # noqa: BLE001 — 도구 하나가 깨져도 나머지는 쓴다
                _load_errors[m] = str(e)
        _tools = out
    return _tools


def get(key: str) -> Tool:
    t = tools().get(key)
    if not t:
        raise ToolError(f"모르는 파서 도구입니다: {key}. 목록에서 고르세요.")
    return t


def for_ext(ext: str) -> list[Tool]:
    ext = ext.lower()
    return [t for t in tools().values() if ext in t.formats]


# ---------------------------------------------------------------- 형식별 기본 도구

def defaults_file() -> Path:
    return config.path("config", "parsers.json")


def load_defaults() -> dict[str, str]:
    data = dict(BUILTIN_DEFAULTS)
    f = defaults_file()
    if f.exists():
        try:
            user = json.loads(f.read_text(encoding="utf-8")).get("defaults") or {}
            for ext, key in user.items():
                t = tools().get(key)
                if t and t.kind == "local" and ext in t.formats:
                    data[ext] = key
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    return data


def save_defaults(updates: dict[str, str]) -> dict[str, str]:
    """{".pdf": "pdfplumber", ...}. 형식을 못 읽는 도구·클라우드 도구는 거절한다."""
    cur = {}
    f = defaults_file()
    if f.exists():
        try:
            cur = json.loads(f.read_text(encoding="utf-8")).get("defaults") or {}
        except (OSError, json.JSONDecodeError):
            cur = {}
    for ext, key in (updates or {}).items():
        ext = ext.lower() if ext.startswith(".") else "." + ext.lower()
        if ext not in BUILTIN_DEFAULTS:
            raise ToolError(f"기본 도구를 정할 수 없는 형식입니다: {ext}")
        t = get(key)
        if t.kind != "local":
            raise ToolError("클라우드 도구는 기본으로 둘 수 없습니다(새로 들어오는 파일이 모두 밖으로 나가게 됩니다). "
                            "필요한 문서에서만 직접 실행하세요.")
        if ext not in t.formats:
            raise ToolError(f"{t.name}은(는) {ext} 파일을 읽지 못합니다.")
        if key == BUILTIN_DEFAULTS[ext]:
            cur.pop(ext, None)
        else:
            cur[ext] = key
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"defaults": cur}, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_defaults()


def default_for(ext: str) -> str | None:
    return load_defaults().get(ext.lower())


# ---------------------------------------------------------------- 실행

def run(key: str, path: Path, options: dict | None = None) -> dict:
    """도구 하나로 파싱. meta에 tool·tool_ver·duration_ms·warnings를 채운다. 실패하면 ToolError(또는 원래 예외)."""
    t = get(key)
    path = Path(path)
    if path.suffix.lower() not in t.formats:
        raise ToolError(f"{t.name}은(는) {path.suffix.lower()} 파일을 읽지 못합니다. "
                        f"이 도구가 읽는 형식: {', '.join(sorted(t.formats))}")
    st = t.status()
    if not st.get("ready"):
        raise NotReady(f"{t.name}: {st.get('message')} {st.get('hint') or ''}".strip())
    t0 = time.perf_counter()
    parsed = t.parse(path, options or {})
    meta = parsed.setdefault("meta", {})
    meta.setdefault("warnings", [])
    meta["tool"] = t.key
    meta["tool_ver"] = t.version()
    meta["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    if meta.get("needs_ocr") and t.key in ("pymupdf", "pdfplumber", "kordoc"):
        meta["warnings"].append("글자가 거의 없는 쪽이 있습니다(스캔본 추정). RapidOCR 도구로 다시 파싱해 보세요.")
    return parsed


def parse_default(path: Path) -> dict:
    """새로 들어온 파일: 형식별 기본 도구로 파싱한다. 기본 도구가 준비되지 않았거나 실패하면 기존 파서(parsers.parse)로
    되돌아간다(기존 동작 보장). meta.tool에 실제로 쓴 도구, meta.fallback_from에 실패한 기본 도구를 남긴다."""
    from .. import parsers
    path = Path(path)
    ext = path.suffix.lower()
    key = default_for(ext)
    builtin = BUILTIN_DEFAULTS.get(ext)
    if key:
        try:
            return run(key, path)
        except (ToolError, ImportError) as e:
            if ext == ".hwp":   # 기존 파서는 .hwp를 못 읽는다 — 이유와 해결 방법을 그대로 알린다
                raise parsers.UnsupportedFile(
                    f"HWP(구 형식)는 kordoc 도구로 읽습니다: {e} 또는 한글에서 'HWPX로 저장' 후 넣어 주세요.") from e
            if key == builtin and not isinstance(e, NotReady):
                raise
            fallback_err = str(e)
        except Exception as e:  # noqa: BLE001 — 사용자가 고른 기본 도구가 터지면 기존 파서로
            if key == builtin:
                raise
            fallback_err = str(e)
    else:
        fallback_err = None
    t0 = time.perf_counter()
    parsed = parsers.parse(path)
    meta = parsed.setdefault("meta", {})
    meta.setdefault("warnings", [])
    meta["tool"] = builtin or "builtin"
    t = tools().get(meta["tool"])
    meta["tool_ver"] = t.version() if t else parsers.PARSER_VER
    meta["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    if fallback_err and key != meta["tool"]:
        meta["fallback_from"] = key
        meta["warnings"].append(f"기본 도구 {key} 실패로 기존 파서를 썼습니다: {fallback_err}")
    return parsed
