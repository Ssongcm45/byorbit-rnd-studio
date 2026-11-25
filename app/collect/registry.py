"""출처 자동 등록: app/collect/sources/*.py 의 모듈 전역 SOURCE를 모은다."""
from __future__ import annotations

import importlib
import logging
import pkgutil

from .base import Source

log = logging.getLogger(__name__)
_cache: dict[str, Source] | None = None


def sources(reload: bool = False) -> dict[str, Source]:
    global _cache
    if _cache is not None and not reload:
        return _cache
    from . import sources as pkg
    out: dict[str, Source] = {}
    for m in pkgutil.iter_modules(pkg.__path__):
        if m.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{pkg.__name__}.{m.name}")
        except Exception as e:  # noqa: BLE001 — 한 출처가 깨져도 나머지는 쓴다
            log.warning("수집 출처 %s를 불러오지 못했습니다: %s", m.name, e)
            continue
        src = getattr(mod, "SOURCE", None)
        if isinstance(src, Source) and src.key:
            out[src.key] = src
    _cache = out
    return out


def get(key: str) -> Source:
    s = sources().get(key)
    if not s:
        raise KeyError(f"수집 출처 '{key}'가 없습니다. 사용 가능: {', '.join(sorted(sources()))}")
    return s
