"""데이터 폴더 위치와 설정 파일.

데이터 폴더는 BYORBIT_HOME 환경 변수가 있으면 그곳, 없으면 사용자 홈의 ByOrbit-RD.
Windows 예: C:\\Users\\<이름>\\ByOrbit-RD
"""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent  # 저장소 루트
APP_VERSION = "0.1.0-m1"

DEFAULT_SETTINGS = {
    "default_project": "기본 프로젝트",
    "engine": "claude",            # claude | codex
    "coa_rule": "mask",            # mask: 필요한 값만·식별 정보 가림 / block: 기밀 수치 미전송
    "watch_inbox": True,
    "port": 8765,
    "claude_timeout_sec": 600,
}

SUBDIRS = ["inbox", "library", "ontology", "agents", "db", "reports", "exports", "config", "logs"]


def data_home() -> Path:
    env = os.environ.get("BYORBIT_HOME")
    return Path(env).expanduser().resolve() if env else (Path.home() / "ByOrbit-RD")


def path(*parts: str) -> Path:
    return data_home().joinpath(*parts)


def db_path() -> Path:
    return path("db", "rd.sqlite")


def ensure_dirs() -> None:
    for d in SUBDIRS:
        path(d).mkdir(parents=True, exist_ok=True)


def settings_file() -> Path:
    return path("config", "settings.json")


def load_settings() -> dict:
    f = settings_file()
    data = dict(DEFAULT_SETTINGS)
    if f.exists():
        try:
            data.update(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return data


def save_settings(updates: dict) -> dict:
    data = load_settings()
    for k, v in updates.items():
        if k in DEFAULT_SETTINGS:
            data[k] = v
    settings_file().parent.mkdir(parents=True, exist_ok=True)
    settings_file().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
