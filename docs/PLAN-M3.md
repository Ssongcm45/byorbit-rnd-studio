# M3 계획 — 자료 수집(공식 API·크롤러) + 내 실험 (2026-11-25 확정)

사용자 결정
- 공식 API: 해외 학술(OpenAlex·Crossref·Europe PMC·Semantic Scholar, 키 불필요) + 국내 학술(KCI·ScienceON) + 국가 R&D·특허(NTIS·KIPRIS) + 공공데이터포털(농진청·식약처 등 농식품). 키는 환경 변수로만.
- 크롤러: 기본 사이트 목록(API 없는 공개 자료 페이지) + 설정 화면에서 직접 추가. robots.txt·이용약관을 지키고, 막힌 곳은 자동 제외.
- 실행: 수동 검색 + 저장 검색 자동(앱이 켜져 있는 동안 하루 한 번).
- 내 실험: 내 데이터를 넣어 실험한다. 공정 흐름(원료→전처리→건조→분말화→추출…)과 건조 방식을 토대로 하고, 흐름은 사용자가 조절(단계 추가·삭제·순서·파라미터)할 수 있어야 한다.

## 공통 원칙
- 밖으로 나가는 것: 검색어와 그 출처가 요구하는 API 키뿐. 기밀 자료·CoA·시료·실험 데이터는 외부로 보내지 않는다. User-Agent는 일반 이름(app/collect/http.py), 이메일 등 개인 정보 금지.
- 수집 결과는 바로 자료함에 넣지 않는다 → 수집함(collect_item, status=new)에서 검토 → 승인하면 자료함으로(pipeline.ingest_file). 중복은 DOI → (출처, 출처 ID) → 제목 열쇠(base.title_key) 순으로 판정.
- 원문 PDF는 오픈 액세스만 자동으로 받는다(Item.pdf_url). 유료 원문은 서지·초록만(초록 텍스트를 .md로 만들어 넣는다). 받은 자료의 source 레코드에 출처·DOI·라이선스를 남긴다.
- 예측·시뮬레이션 값에는 근거(문헌[DOI 확인]·실측[n]·설비 사양·가정)와 적용 범위를 붙인다(메모리: 예측에는 근거 표시 필수).

## 고정된 기반 (메인 루프가 작성 — 수정 금지, 필요하면 보고)
- `app/schema.sql`: collect_query, collect_item, collect_job, experiment, experiment_run, experiment_value (표 36개). 기존 workflow(graph_json)·experiment_plan 재사용.
- `app/collect/base.py`: Item(정규화 형식), Source(출처 기본형: key·name·kind·group·needs_env·key_help·search()), MissingKey, SourceError, norm_doi, clean_text, title_key.
- `app/collect/http.py`: get_text·get_json·download(PDF 확인)·set_interval·set_opener(테스트용). 모든 외부 호출은 이 모듈로만.
- `app/collect/registry.py`: app/collect/sources/*.py의 전역 SOURCE 자동 등록.

## 작업 묶음과 파일 소유권
| 묶음 | 소유 파일 |
|---|---|
| A. 수집 핵심 + 해외 API + 수집 화면 | `app/collect/store.py`, `app/collect/scheduler.py`, `app/collect/sources/{openalex,crossref,europepmc,semanticscholar}.py`, `app/routes_collect.py`, `app/static/collect/*`, `tests/test_collect.py` |
| B. 국내·키 필요 API + 크롤러 | `app/collect/sources/{kci,scienceon,ntis,kipris,datagokr*}.py`, `app/collect/sources/crawler.py`, `app/collect/crawler.py`, `app/collect/crawl_defaults.json`, `tests/test_collect_kr.py`, `docs/COLLECT-SOURCES.md`, `requirements.txt`(파서 라이브러리 추가 시에만) |
| C. 내 실험 | `app/experiment/*`, `app/routes_experiment.py`, `app/static/exp/*`, `app/viz/predict.py`(내 실험 실측을 보정 근거로 추가), `tests/test_experiment.py`, `docs/EXPERIMENT.md` |
| 메인 | `app/server.py`(include_router), `app/static/index.html`(탭 연결), `README.md`, 기반 파일 |

## A↔B 크롤러 계약 (`app/collect/crawler.py`, B가 구현하고 A의 화면·API가 부른다)
- `list_sites() -> list[dict]` — 기본(crawl_defaults.json) + 사용자(데이터 폴더 config/crawl_sites.json) 병합.
- `save_site(site: dict) -> dict` / `delete_site(site_id: str) -> None` (기본 사이트는 삭제 대신 enabled=false).
- `check_site(site_id: str) -> {"robots_ok": bool, "terms_url": str|None, "message": str}`
- site dict: `{id, name, group, start_urls[], allow_prefixes[], link_pattern(정규식), title_hint?, date_pattern?, pdf_pattern?, interval_s, enabled, default}`
- 크롤러 출처 key는 `crawler` 하나이며, search(query)는 켜진 사이트들에서 query와 맞는 항목을 돌려준다.

## 화면 계약 (메인이 index.html에 탭으로 붙인다)
- A: `app/static/collect/collect.js` → `export function mountCollect(el, {api, toast, project})`, 확인용 `app/static/collect/dev.html`.
- C: `app/static/exp/exp.js` → `export function mountExperiment(el, {api, toast, project, openDrying})`, 확인용 `app/static/exp/dev.html`.
- 스타일은 index.html의 CSS 변수와 app/static/viz/viz.css의 모양을 따른다(라이트·다크·모바일).
