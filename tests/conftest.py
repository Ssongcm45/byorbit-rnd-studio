"""시험 전체 공통: 실제 OS 자격 증명 저장소(Windows 자격 증명 관리자)를 읽거나 쓰지 않도록 메모리 보관소를 끼운다.
(앱 시작(lifespan)이 보관소의 키를 os.environ에 올리므로, 이게 없으면 이 PC에 저장된 실제 키가 시험에 섞인다.)"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True, scope="session")
def _no_real_keyring():
    try:
        import keyring
    except ImportError:
        yield
        return
    from tests.test_keys import MemKeyring
    prev = keyring.get_keyring()
    keyring.set_keyring(MemKeyring())
    yield
    keyring.set_keyring(prev)
