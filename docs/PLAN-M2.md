# M2 + 시각화 계획 (2026-11-24 확정)

사용자 결정: 구조 데이터 = 로컬 시드 + RDKit, 없는 성분만 PubChem 보조(성분명만 전송) /
건조 시각화 = 2D 애니메이션 공정도 + 3D 입자 단면 + 방식별 측정값 비교 / OCR = 로컬(RapidOCR, 선택 설치).

## 작업 묶음과 파일 소유권 (겹치지 않게)

| 묶음 | 담당 | 소유 파일 (이 파일들만 수정) |
|---|---|---|
| A. M2 핵심 | implementer | `app/server.py`, `app/static/index.html`, `app/ingest/coa.py`, `app/ingest/pipeline.py`, `app/seed/seed_data.py`, `app/sample_files.py`, `app/labeling.py`(신규), `tests/test_m2.py`(신규) |
| B. 시각화 | implementer | `app/viz/*`(신규), `app/routes_viz.py`(신규), `app/static/viz/*`(신규), `app/static/vendor/*`(신규), `requirements.txt`, `tests/test_viz.py`(신규) |
| C. 로컬 OCR | implementer-fast | `app/ingest/parsers.py`, `requirements-ocr.txt`(신규), `install-ocr.bat`(신규), `tests/test_ocr.py`(신규) |
| D. Codex 엔진 | implementer | `app/engines/codex.py`, `app/tools.py`(`_rule()`만), `tests/test_codex.py`(신규) |
| 통합 | 메인 루프 | `README.md`, `index.html`에 시각화 탭 연결(B 완료 후), `server.py`에 `include_router` 한 줄 |

`tests/test_m1.py`는 아무도 고치지 않는다(기존 38개 유지). 단 A가 시드 개념을 추가해 기존 단언이 깨지면 그 단언만 최소 수정하고 보고한다.

## 공유 계약

### 건조 정보 (A가 쓰고 B가 읽는다)
- CoA의 건조 방법은 `sample.pretreatment_concept_id` = 공정 체계의 건조 개념(동결건조·열풍건조·진공건조·분무건조·자연건조).
- `sample.pretreatment_text` 표준 형식: `"<방법 표준명>; <온도> ℃; <시간> h"` — 모르는 칸은 생략. 예: `"동결건조; -50 ℃; 48 h"`, `"열풍건조; 60 ℃"`.
- B는 이 형식 외의 자유 표기(논문 본문 등)도 관대하게 파싱한다.

### 시드 개념 (A가 seed_data에 넣고, B의 구조 시드와 같은 한글 표준명을 쓴다)
- 공정: 동결건조, 열풍건조, 진공건조, **분무건조**, **자연건조(천일건조·양건)** — 굵은 것은 신규.
- 성분(구조를 그릴 수 있는 것): 클로로겐산, 퀘르세틴, 플로리진, 카테킨, 에피카테킨, 프로시아니딘 B2, 헤스페리딘, 나린진, 갈산, 카페산, 시아니딘-3-글루코시드, 루틴, 탄닌산, 갈락투론산(펙틴 단위체), 셀로비오스(셀룰로스 단위체), 포도당, 과당, 자당, 말산, 시트르산, 아스코르브산, 리모넨, 베타카로틴, 카페인.
- 펙틴·셀룰로스·식이섬유·폴리페놀은 단일 분자가 아니다 → B는 "대표 단위체/대표 화합물"로 연결하고 화면에 그 사실을 밝힌다(펙틴 → 갈락투론산, 셀룰로스 → 셀로비오스, 폴리페놀(TPC) → 갈산(GAE 기준 물질)).

### 화면 통합 (B → 메인)
- B는 `app/static/viz/viz.js`에 ES 모듈 `export function mountViz(el, {api, initial})`와 `export function openStructure(term)`을 둔다. 독립 확인용 `app/static/viz/dev.html`.
- B의 API는 `app/routes_viz.py`의 `router = APIRouter(prefix="/api/viz")`. 메인이 `app.include_router`로 붙인다.
- 외부 라이브러리는 CDN이 아니라 `app/static/vendor/`에 고정 버전으로 둔다(오프라인 동작).

### 보안 불변조건 (모두)
- Claude 실행은 `--tools ""` 유지. 새 MCP 도구가 파일·URL을 읽으면 허용하지 않는다.
- PubChem에는 성분명(영문 표준명)만 보낸다. 시료·공급처·로트 정보는 절대 보내지 않는다.
- OCR은 로컬에서만. 이미지가 PC 밖으로 나가지 않는다.
- Codex는 셸을 끄고 실행하되, 실제 시험에서 파일 읽기가 막히지 않으면 Codex 실행 동안 CoA 규칙을 '보내지 않기'로 강제한다.
