"""(?) 도움말: app/static/help/help.js의 HELP가 메뉴·쪽 제목·모듈 표시를 모두 덮는지, 내용이 비지 않았는지,
없는 화면·없는 기능을 말하지 않는지 검사한다(브라우저 없이 정적 파일만 읽는다)."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
HELP_JS = STATIC / "help" / "help.js"
INDEX = STATIC / "index.html"
MODULES = [STATIC / p for p in (
    "collect/collect.js", "exp/exp.js", "stats/stats.js", "kg/kg.js", "doc/workbench.js", "doc/parse.js",
    "viz/flow.js", "viz/drying.js", "viz/equipment.js", "viz/predict.js", "viz/molecule.js")]
OUT_KINDS = {"none", "mix", "query", "web", "ai", "key", "food", "name", "site", "cloud"}
# 지금 화면에 있는 출처 묶음(자료 수집)과 키 묶음(설정 → API 키 관리). 템플릿이 data-help="group.${g}"로 붙인다.
COLLECT_GROUPS = ["해외 학술", "국내 학술", "국가 R&D·특허", "공공데이터", "크롤러"]
KEY_GROUPS = ["해외 학술", "국내 학술", "국가 R&D·특허", "공공데이터", "크롤러·파서(클라우드)"]


def _help() -> dict:
    s = HELP_JS.read_text(encoding="utf-8")
    m = re.search(r"/\*HELP-JSON-START\*/(.*?)/\*HELP-JSON-END\*/", s, re.S)
    assert m, "HELP JSON 구간 표시가 없습니다"
    return json.loads(m.group(1))


@pytest.fixture(scope="module")
def H():
    return _help()


@pytest.fixture(scope="module")
def index():
    return INDEX.read_text(encoding="utf-8")


def _routes(index: str) -> dict:
    m = re.search(r"const ROUTES = \{(.*?)\};", index, re.S)
    return dict(re.findall(r"(\w+):'([^']+)'", m.group(1)))


def test_every_entry_is_complete(H):
    assert len(H) >= 60
    for k, h in H.items():
        assert h["title"].strip(), k
        assert len(h["what"].strip()) >= 10, k
        assert isinstance(h["how"], list) and 1 <= len(h["how"]) <= 4 and all(s.strip() for s in h["how"]), k
        assert h["out"]["k"] in OUT_KINDS, k
        assert h["out"]["t"].strip(), k
        for t in h.get("tips", []):
            assert t.strip(), k
        # 중학생 수준·짧게: 문장 하나가 너무 길지 않게
        for s in [h["what"], *h["how"], *h.get("tips", [])]:
            assert len(s) <= 140, (k, s)


def test_guide_refers_to_real_chapter(H):
    outline = json.loads((ROOT / "guidebook" / "outline.json").read_text(encoding="utf-8"))
    titles = {int(re.search(r"(\d+)", c["file"]).group(1)): c["title"] for c in outline["chapters"]}
    for k, h in H.items():
        m = re.fullmatch(r"안내서 (\d+)장 · (.+)", h["guide"])
        assert m, (k, h["guide"])
        n, title = int(m.group(1)), m.group(2)
        assert n in titles and titles[n] == title, (k, h["guide"], titles.get(n))


def test_every_sidebar_item_has_help(H, index):
    nav = re.findall(r'<a class="ni" href="#(\w+)" data-v="(\w+)" data-help="([^"]+)"', index)
    all_ni = re.findall(r'<a class="ni" href="#(\w+)"', index)
    assert len(nav) == len(all_ni) == 13, (len(nav), len(all_ni))
    for href, v, hid in nav:
        assert href == v == hid
        assert hid in H, hid


def test_every_page_title_has_help(H, index):
    routes = _routes(index)
    heads = re.findall(r'<header class="ph"><div class="ph-t"><h1 id="(\w+)"([^>]*)>', index)
    assert len(heads) >= 10
    for hid, attrs in heads:
        m = re.search(r'data-help="([^"]+)"', attrs)
        assert m, f"쪽 제목 #{hid}에 (?)가 없습니다"
        assert m.group(1) in H and m.group(1) in routes, (hid, m.group(1))
    # 쪽 머리가 모듈 안에 있는 화면(내 실험·통계 분석)과 시작 화면
    exp = (STATIC / "exp/exp.js").read_text(encoding="utf-8")
    st = (STATIC / "stats/stats.js").read_text(encoding="utf-8")
    assert 'data-help="exp">내 실험</h2>' in exp
    assert 'data-help="stats">통계 분석</h2>' in st
    assert 'data-help="home.checklist"' in index


def test_all_hooks_point_to_existing_entries(H, index):
    texts = [index] + [p.read_text(encoding="utf-8") for p in MODULES]
    used = set()
    for t in texts:
        for m in re.finditer(r'data-help="([^"$]+)"', t):
            used.add(m.group(1))
        for m in re.finditer(r'data-help-chips="([^"]+)"', t):
            used.update(x.strip() for x in m.group(1).split(","))
    missing = sorted(u for u in used if u not in H)
    assert not missing, missing
    for g in COLLECT_GROUPS + KEY_GROUPS:
        assert f"group.{g}" in H, g
    # 붙일 곳이 없는(쓰이지 않는) 설명은 두지 않는다 — 묶음 설명은 템플릿이 이름으로 붙인다
    dyn = {f"group.{g}" for g in COLLECT_GROUPS + KEY_GROUPS}
    unused = sorted(k for k in H if k not in used and k not in dyn)
    assert not unused, unused
    # 꼭 있어야 할 곳(요청 목록)
    must = ["home.checklist", "home.safety", "home.stats", "library.drop", "library.conf", "library.stages", "library.ailabel",
            "library.actions", "search.expand", "review.learn", "review.keys", "meas.evidence", "kg.depth", "kg.layout",
            "kg.edges", "kg.export", "ask.role", "ask.write", "ask.send", "collect.inbox", "collect.saved", "collect.sites",
            "collect.backend", "collect.robots", "collect.test", "wb.tools", "wb.compare", "wb.rechunk", "wb.chunks",
            "wb.rules", "wb.manual", "wb.synonym", "wb.learned", "exp.flow", "exp.steps", "exp.acid", "exp.import",
            "exp.compare", "exp.calib", "exp.suggest", "stats.source", "stats.roles", "stats.terms", "stats.checks",
            "stats.table1", "stats.fig1", "stats.interp", "stats.repro", "viz.flow", "viz.drying", "viz.play",
            "viz.evidence", "viz.molecule", "settings.engine", "settings.coa", "settings.keys", "settings.food",
            "settings.paths"]
    for k in must:
        assert k in used, k


def test_no_entry_refers_to_missing_view(H, index):
    routes = _routes(index)
    for k in H:
        top = k.split(".")[0]
        assert top in routes or top == "group", k
    # 본문이 화면 이름을 부를 때는 실제 메뉴 이름이어야 한다
    names = set(routes.values()) | {"개념 사전 · 지식그래프"}
    for k, h in H.items():
        for s in [h["what"], *h["how"], *h.get("tips", [])]:
            for ref in re.findall(r"(\S+) 화면", s):
                assert ref.strip("‘’'\"") not in {"보고서", "대시보드", "알림"}, (k, s)
    assert names


def test_text_does_not_promise_unavailable_things(H):
    blob = json.dumps(H, ensure_ascii=False)
    # 이 앱에 없는 것: 자동 번역, 로그인·계정, 다른 사람과 공유, 모델 재학습, 클라우드 동기화·자동 백업, 실시간 협업
    for bad in ["자동 번역", "로그인하", "회원가입", "공유 링크", "다시 학습시킵니다", "재학습합니다", "자동 백업", "동기화합니다", "실시간 협업", "자동으로 승인"]:
        assert bad not in blob, bad
    # 정직한 한계는 그대로 남긴다
    assert "실행해 보지 않았습니다" in H["stats.repro"]["tips"][0]
    assert "모델 추정치" in json.dumps(H["viz.predict"], ensure_ascii=False)
    assert "예시입니다" in json.dumps(H["viz.play"], ensure_ascii=False)
    # 밖으로 나가는 것: 클라우드 파서는 '없음'이라 하지 않는다, 검색·통계는 이 PC 안
    assert H["wb.tools"]["out"]["k"] == "cloud" and "Upstage" in H["wb.tools"]["out"]["t"]
    assert H["ask"]["out"]["k"] == "ai" and "Anthropic" in H["ask"]["out"]["t"]
    assert H["search"]["out"]["k"] == "none" and H["stats"]["out"]["k"] == "none" and H["exp"]["out"]["k"] == "none"
    assert H["collect"]["out"]["k"] == "query"
    assert H["viz.molecule"]["out"]["k"] == "name" and "PubChem" in H["viz.molecule"]["out"]["t"]
    assert H["settings.food"]["out"]["k"] == "food"
    assert "Windows 자격 증명 관리자" in json.dumps(H["settings.keys"], ensure_ascii=False)


def test_spot_check_facts_match_code(H):
    """도움말 숫자·이름이 코드와 같은지 몇 곳 맞춰 본다."""
    idx = INDEX.read_text(encoding="utf-8")
    # 자료함 처리 단계 다섯 개
    for st in ["파싱", "정규화", "청킹", "라벨", "적재"]:
        assert f"'{st}'" in idx and st in H["library.stages"]["what"]
    # 역할 세 개
    for role in ["자료 사서", "성분 분석가", "리포트 작성자"]:
        assert role in idx and role in json.dumps(H["ask.role"], ensure_ascii=False)
    # 가져오기 방식 세 개(collect.js의 BACKENDS)
    col = (STATIC / "collect/collect.js").read_text(encoding="utf-8")
    for lab in ["기본(HTTP)", "브라우저(Chrome)", "Apify(클라우드·유료)"]:
        assert lab in col and lab in json.dumps(H["collect.backend"], ensure_ascii=False)
    assert "최대 3쪽" in col and "최대 3쪽" in H["collect.test"]["what"]
    # 지식그래프 선 종류
    kg = (STATIC / "kg/kg.js").read_text(encoding="utf-8")
    for lab in ["상위 분류", "원료", "발생 공정", "함유 성분", "측정", "언급", "기타 관계"]:
        assert f"'{lab}'" in kg and lab in H["kg.edges"]["how"][0]
    # 산 종류 목록 예시
    steps = (ROOT / "app/experiment/steps.py").read_text(encoding="utf-8")
    assert "구연산" in steps and "염산" in steps
    # 단축키
    for k in ["J", "K", "A", "R", "U"]:
        assert f"<kbd>{k}</kbd>" in idx


def test_help_is_wired_and_static(index):
    assert '/static/help/help.css' in index
    assert "import {initHelp} from '/static/help/help.js'" in index
    assert 'id="helpToggle"' in index and 'role="switch" aria-checked="true"' in index
    assert "(?) 도움말 단추" in index        # ? 도움말 대화상자에도 적었다
    js = HELP_JS.read_text(encoding="utf-8")
    assert "fetch(" not in js                 # 서버에 묻지 않는다(정적)
    assert "return false" not in js           # 키 입력을 막는 처리기 금지
    assert "aria-expanded" in js and "aria-controls" in js and "도움말: " in js
    assert "<dialog" not in js                # dialog[open]을 보는 단축키 처리와 엉키지 않게 div로 띄운다
