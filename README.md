# ByOrbit R&D Studio 개인용 — 2단계(M2)

농·임·수산 부산물 연구 자료(논문·보고서·CoA)를 **내 PC에서** 모으고, 찾고, Claude Code에게 근거 있는 답을 받는 로컬 웹앱입니다.

- 자료·DB·온톨로지는 모두 이 PC의 데이터 폴더(기본 `C:\Users\<이름>\ByOrbit-RD`)에만 저장됩니다.
- AI는 이 PC에 설치·로그인된 **Claude Code**를 씁니다. Claude Code는 이 앱의 자료 서버(MCP `byorbit-rd`)를 통해서만 자료를 읽고 씁니다.
- 브라우저 화면은 `http://127.0.0.1:8765`. 같은 PC에서만 열립니다.

## 설치 (Windows)

1. **Python 3.11 이상**: `winget install Python.Python.3.12` 또는 python.org에서 설치합니다. 설치할 때 "Add to PATH"를 체크하세요.
2. **Claude Code**: PowerShell에서 `irm https://claude.ai/install.ps1 | iex`를 실행합니다(또는 `npm install -g @anthropic-ai/claude-code`). 그다음 `claude`를 한 번 실행해 로그인합니다.
3. 이 폴더에서 **`install.bat`**을 더블클릭합니다. 가상환경, 패키지, 데이터 폴더, 표준 시드, MCP 설정이 준비됩니다.
4. **`start.bat`**을 더블클릭하면 브라우저가 열립니다. 끝낼 때는 검은 창에서 Ctrl+C를 누릅니다.
5. 앱의 **설정 → 연결 점검(실제 호출)**에서 "통과"가 나오면 Claude Code 연결이 끝난 것입니다. `check-claude.bat`으로도 점검할 수 있습니다.

> PowerShell이 스크립트 실행을 막으면 `install.bat`을 쓰세요(실행 정책을 이번 실행에만 우회합니다).

## 쓰는 법

| 화면 | 하는 일 |
|---|---|
| 자료함 | 파일을 끌어다 놓거나 받은편지함 폴더에 넣습니다. 파싱 → 정규화 → 청킹 → 사전 라벨 → 적재 단계가 표시됩니다. "AI 라벨"은 청크를 5개씩 묶어 Claude Code에 맡기고 진행률(성공·오류·건너뜀)을 보여 줍니다. 엔진이 실패한 묶음은 2번까지 다시 시도하고, AI가 라벨할 내용을 찾지 못한 청크는 2번 확인한 뒤 건너뜁니다. 이미 AI 라벨이 있는 청크는 건너뜁니다. "취소"는 지금 묶음이 끝나면 멈추고, "재시도"는 남은(대기·오류) 청크만 다시 처리합니다. 앱을 껐다 켜면 끝나지 못한 실행은 "중단됨"으로 표시되고 재시도로 이어 할 수 있습니다. |
| 검색 | 동의어까지 넓혀서 찾습니다. 예를 들어 "사과 포마스 TDF"는 사과박·apple pomace… 그리고 식이섬유·총식이섬유…로 넓어집니다. 결과를 누르면 원문과 라벨이 보입니다. |
| 라벨 검토 | AI가 제안한 수치 라벨과 신뢰도 0.9 미만 라벨을 승인하거나 거절합니다. 승인한 수치는 측정값 표로 올라가고, 그 자료의 부산물(CoA 시료 또는 본문에 가장 많이 나온 부산물)에 연결됩니다. 단축키: J/K(↓/↑) 이동, A 승인, R 거절, U 마지막 결정 되돌리기(승인으로 올린 측정값도 지움), ? 도움말. 입력칸에 쓰는 동안에는 동작하지 않습니다. |
| 측정값 | CoA에서 읽은 값과 승인한 추출값을 봅니다. CSV로 저장할 수 있습니다. |
| 개념 | 부산물 분류 트리(표준 시드)와 동의어를 보고, 내 확장 개념을 추가합니다. |
| AI에 묻기 | Claude Code가 자료를 찾아 출처를 달아 답합니다. "리포트 작성자"를 고르면 근거 번호가 달린 초안을 `reports` 폴더에 저장합니다. |
| 시각화 | **흐름**·**건조 방식**·**분자 구조** 세 화면입니다(아래 "시각화" 참고). |
| 설정 | 엔진 상태, CoA 전송 규칙, 기본 프로젝트, 데이터 폴더 경로, 식품 영양 DB 연결을 다룹니다. |

**받은편지함**: 데이터 폴더의 `inbox`에 파일을 넣으면 자동으로 처리되어 `library\<프로젝트>\`로 옮겨집니다. `inbox\<프로젝트명>\`에 넣으면 그 프로젝트로 들어갑니다.

**예시 자료로 시험하기**: `.venv\Scripts\python -m app.cli samples --project "사과박 식이섬유"`를 실행하면 가상 논문 PDF, CoA 엑셀, HWPX 보고서, 메모, 그리고 건조 방법 비교용 열풍건조 CoA가 받은편지함에 들어갑니다. 수치는 모두 가짜입니다.

## 지원 형식

| 형식 | 처리 |
|---|---|
| PDF | 본문과 표를 추출합니다(PyMuPDF). 글자가 거의 없는 스캔 쪽은 로컬 OCR(RapidOCR)을 설치했으면 자동으로 읽습니다. 미설치면 "OCR 필요"로 표시합니다. |
| 이미지 (PNG/JPG/JPEG/TIF/TIFF) | 사진·스캔 CoA를 로컬 OCR로 읽습니다(설치 필요). 줄과 칸이 맞는 글자는 표로, 나머지는 문단으로 넣습니다. |
| HWPX | 본문과 표를 추출합니다. 구 HWP는 한글에서 "HWPX로 저장"한 뒤 넣으세요. |
| XLSX | 표로 넣습니다. CoA 양식(시험항목·결과 머리글)이면 시료와 측정값으로 자동 적재하고, 등급을 "기밀"로 둡니다. |
| TXT / MD / CSV | 문단 단위로 넣습니다. |

**CoA 양식**: ByOrbit CoA 필드를 읽습니다 — 부산물종·품종·산지·수확시기·분석기관·분석일·건조방법/온도/시간, TDF·TPC·펙틴·조단백·당류·조지방·수분(생시료/건조 후)·pH·중금속(Pb·Cd·As·Hg)·일반세균·대장균·살모넬라·리스테리아. 건조 정보는 시료의 전처리로 "열풍건조; 60 ℃; 12 h" 형식으로 저장됩니다. "ND·불검출"은 값 없이 글자로, "< 0.01"은 값 0.01과 원래 표기를 함께 남깁니다. 품종·산지 등은 자료 메모에 적힙니다. 머리글 별칭은 `app/ingest/coa.py`의 `COA_TEMPLATE`에서 늘릴 수 있습니다.

### 로컬 OCR 설치 (선택)

스캔 PDF와 CoA 사진의 글자를 이 PC에서만 인식합니다(RapidOCR, 한국어 인식 모델). **이미지는 PC 밖으로 나가지 않습니다.**

1. 이 폴더에서 **`install-ocr.bat`**을 더블클릭합니다.
2. 처음 실행할 때 인식 모델 3개(약 23MB)를 인터넷에서 한 번 내려받습니다(`.venv\Lib\site-packages\rapidocr\models\`). 이후에는 다시 받지 않습니다.
3. 끝나면 자가 점검 결과(한글·숫자 인식)가 화면에 나옵니다.

설치하지 않아도 앱은 그대로 동작합니다. 띄어쓰기는 빠질 수 있지만 숫자·단위는 정확히 읽습니다. 기울어진 사진이나 병합 셀이 있는 표는 약할 수 있습니다.

## AI로 무엇이 나가나

Claude Code를 쓰는 순간에는 질문과 도구가 돌려준 본문 일부가 Anthropic으로 전송됩니다. 자료함, DB, 원본 파일 자체는 올라가지 않습니다.

| CoA 규칙 | AI에 넘어가는 것 |
|---|---|
| 필요한 값만·식별 정보 가림 (기본) | 측정값과 본문은 넘기되, 로트번호·공급처·시료번호는 `[가림]`으로 바꿉니다. 측정값 표는 "시료 n"으로만 구분합니다. |
| 보내지 않기 | 기밀(CoA) 본문과 측정값을 전혀 넘기지 않습니다. |

Claude Code에는 이 앱의 도구 7개만 허용하고, 파일 읽기를 포함한 내장 도구(셸·파일 읽기/수정·웹·하위 에이전트)는 모두 없애고 실행합니다(`--tools ""`, `--strict-mcp-config`, `--allowedTools`, `--disallowedTools`). 그래서 Claude Code가 `library\`의 원본 파일을 직접 읽어 가림을 우회할 수 없습니다.

| Codex CLI (보조 엔진) | Claude Code와 같은 CoA 규칙으로 byorbit-rd 도구가 돌려준 내용만. 사용자 Codex 설정(`~/.codex/config.toml`의 MCP·플러그인)은 싣지 않고, 셸·이미지 보기·브라우저·플러그인·웹 검색을 끄고 읽기 전용 샌드박스로 실행합니다. 2026-11-24 실제 시험에서 데이터 폴더 파일을 직접 읽지 못함을 확인했습니다. |
| 시각화 — PubChem | 로컬에 없는 성분을 "PubChem에서 가져오기"로 누를 때만 **영문 성분명 하나**. 시료·공급처·로트 정보는 보내지 않습니다. |
| OCR | 아무것도 보내지 않습니다(처음 한 번 모델 파일만 내려받음). |

식품 영양 DB 연결을 켜면 식품 도구 12개(읽기 전용)가 더해지고, 식품명·성분값이 Food MCP의 Neon DB로 질의됩니다. 파일·URL을 읽는 `extract_label_table`은 늘 막습니다(아래 "식품 영양 DB 연결" 참고).

기밀 자료는 본문뿐 아니라 파일명·제목·섹션 제목도 가립니다. 파일명은 `기밀자료-xxxxxx.확장자`로 바꿔 넘기고, 근거는 chunk_id로 남으므로 내 화면에서는 원래 파일명이 보입니다.

## 데이터 폴더

```
ByOrbit-RD\
  inbox\        받은편지함 (넣으면 자동 처리)
  library\      프로젝트별 자료 사본
  db\rd.sqlite  DB (30개 테이블 + 전문검색)
  ontology\     seed.ttl(표준 시드) · mine.ttl(내 확장)
  agents\       에이전트 지침(.md) — 직접 고쳐도 됩니다
  reports\      리포트 초안(.md)
  config\       settings.json · mcp.json
  logs\         처리 실패 기록
```

백업은 이 폴더를 통째로 복사하면 됩니다. 다른 위치를 쓰려면 환경 변수 `BYORBIT_HOME`을 지정하세요.

## Claude Code에서 직접 쓰기

앱 밖에서도 Claude Code 대화창에 이 자료 서버를 붙일 수 있습니다.

```
claude --mcp-config "%USERPROFILE%\ByOrbit-RD\config\mcp.json"
```

도구는 `search_chunks`, `get_chunk`, `lookup_concept`, `query_measurements`, `save_annotations`, `save_report_draft`, `propose_concept`입니다.

## 식품 영양 DB 연결 (선택)

옆 프로젝트 `04_byorbit-agent`의 **ByOrbit Food MCP**(농진청 원물·식약처 식품 성분 DB)를 Claude Code 실행에 함께 붙일 수 있습니다. 켜면 AI가 부산물의 측정 성분을 원물 기준값과 견주거나(`search_food`·`get_food`·`compare_foods`), 주장된 영양 성분 값을 확인하고(`verify_nutrition`), 표시 기준을 볼 수 있습니다(`nutrition_analysis`·`verify_food_claim`). 식품 DB 값은 참고 기준값이므로 답변에서 "식품 DB(출처명)"로 자료 근거와 따로 표시합니다.

**켜는 법**

- 앱의 **설정 → 식품 영양 DB 연결**에서 "켜기"를 체크하고 저장합니다. "연결 점검"으로 서버가 도구 목록을 내주는지 확인합니다(DB 조회는 하지 않습니다).
- 폴더는 비워 두면 이 저장소 옆의 `04_byorbit-agent`를 자동으로 찾습니다. 다른 곳에 있으면 화면에서 경로를 넣거나 환경 변수 `BYORBIT_FOOD_MCP_DIR`를 지정합니다.
- `settings.json`에서 직접 바꿀 수도 있습니다: `"food_mcp": true`, `"food_mcp_dir": ""`.

**필요한 것**

- Node.js(`node`가 PATH에 있거나 환경 변수 `BYORBIT_NODE`에 경로 지정)
- `04_byorbit-agent` 폴더에 `npm install`로 `node_modules`가 설치되어 있을 것
- 그 폴더의 `.env.local`에 `DATABASE_URL`(Neon Postgres). 이 앱은 그 파일을 읽지 않으며, `mcp.json`에도 시크릿을 넣지 않습니다. 서버가 자기 `.env.local`을 직접 읽습니다.

**무엇이 PC 밖으로 나가나**: 식품 도구를 부를 때 식품명과 성분값이 Food MCP의 Neon DB로 질의됩니다. AI 지침은 `[가림]` 표시·로트번호·공급처·시료번호를 식품 도구 인자에 넣지 말라고 정해 둡니다. CoA 규칙이 "보내지 않기"이면 기밀 수치가 처음부터 Claude에게 보이지 않으므로 식품 DB로도 나갈 수 없습니다.

**막아 둔 도구**: Food MCP의 `extract_label_table`은 로컬 파일 경로나 URL을 받아 읽습니다. 이것을 열면 내장 파일 읽기를 없앤 방어가 우회되어 `library\`의 기밀 원본을 가림 없이 읽을 수 있으므로, 허용 목록에서 빼고 켜짐 여부와 관계없이 `--disallowedTools`에 늘 넣습니다. 허용하는 식품 도구는 읽기 전용 12개입니다.

## Codex로 실행하기 (선택)

1. `npm i -g @openai/codex` 설치 후 터미널에서 `codex login`.
2. 설정 → AI 엔진을 Codex로 바꾸고, 연결 점검에서 '사과박' 응답을 확인합니다.
3. 모델을 고르려면 환경 변수 `BYORBIT_CODEX_MODEL`을 지정합니다.
4. 더 엄격하게: `BYORBIT_CODEX_FORCE_BLOCK=1`이면 Codex 실행 동안 기밀 수치를 항상 '보내지 않기'로 강제합니다.

Codex CLI를 업데이트하면 보안 시험을 다시 해야 합니다(`app/engines/codex.py`의 `PROBE`).

## 시각화

- **흐름**: R&D Studio(이 PC)와 ByOrbit Food MCP가 Claude Code를 가운데 두고 어떻게 이어지는지, 각 경계를 무엇이 넘는지(PC 밖으로 나가는 것) 보여 줍니다. 상자·선을 누르면 자세히 나옵니다. 아래에 자료 → 청크 → 라벨 → 측정값 → 리포트 개수가 프로젝트별로 나옵니다.
- **건조 설비(3D·P&ID)**: 방식마다 실제 설비 구조를 3D로 보여 줍니다 — 동결건조기(챔버·가열 선반·콘덴서·진공 펌프·냉동기), 캐비닛형 열풍 트레이 건조기(히터·송풍기·댐퍼·기류), 진공 선반 오븐, 분무건조기(분무기·건조탑·사이클론·백 필터), 노지 건조대·하우스형 태양열 건조기. 절개 보기, 부품을 누르면 역할·일반 설정값, 단계 재생에 따라 게이지가 바뀝니다. 공정 흐름도(P&ID)로 바꿔 볼 수 있습니다. 계기값은 단계별 예시이며 실제 운전 기록이 아닙니다.
- **건조 결과 예측**: 온도·시간·압력·풍속·두께를 바꾸면 최종 수분·목표 수분 도달 시간·총폴리페놀 잔존율·식이섬유·비에너지가 바로 바뀝니다. 값마다 식과 파라미터, 근거(문헌[DOI 확인·원문 위치]·실측[n]·설비 사양·가정), 적용 범위(외삽 경고)를 보여 주고, 내 CoA 실측으로 보정합니다. 슬라이더는 3D 설비 게이지와 연동됩니다. 모델·출처·가정 목록은 `docs/PREDICT-SOURCES.md`, 내 설비 사양은 데이터 폴더 `config/equipment.json`에서 고칩니다.
- **건조 방식**: 동결·열풍·진공·분무·자연건조의 공정 애니메이션, 물의 상평형도 위 공정 경로, 3D 입자 단면(기공·수축 비교, 개념도), CoA·논문 측정값의 방식별 비교(시료는 '시료 n'으로만 표시)를 봅니다. 조건·효과는 일반 문헌 경향이며 측정값이 아닙니다.
- **분자 구조**: 성분명(한글·영문·동의어)으로 2D 구조식·3D 모델·성질을 봅니다. 구조는 이 PC의 시드 24종과 RDKit으로 그려 인터넷이 필요 없습니다. 펙틴·셀룰로스·식이섬유·폴리페놀처럼 단일 분자가 아닌 것은 대표 단위체(갈락투론산·셀로비오스·갈산)로 보여 주고 그 사실을 표시합니다.
- 3D 라이브러리(3Dmol.js 2.4.2, three.js r170)는 `app/static/vendor/`에 고정 버전으로 들어 있어 오프라인에서도 동작합니다. 구조 그림에는 RDKit(requirements.txt에 포함)이 필요하며, 없으면 분자 구조 화면에 설치 안내가 나옵니다.

## 보안: 화면 접근

화면은 127.0.0.1/localhost 주소로만 열리고, 다른 사이트에서 보낸 쓰기 요청(POST 등)은 막습니다(DNS 리바인딩·CSRF 방어). 명령줄처럼 Origin이 없는 요청은 그대로 허용합니다.

## 명령줄

```
.venv\Scripts\python -m app.cli init            데이터 폴더·DB·시드·MCP 설정
.venv\Scripts\python -m app.cli serve           웹앱 (--port, --no-browser, --no-watch)
.venv\Scripts\python -m app.cli ingest <파일|폴더> --project 이름
.venv\Scripts\python -m app.cli search "사과 포마스 식이섬유"
.venv\Scripts\python -m app.cli check-claude    Claude Code 연결 점검
.venv\Scripts\python -m app.cli ask "질문"       Claude Code로 자료에 질문
```

## 구조

```
app\
  schema.sql        30개 테이블 (팀판과 같은 이름·UUID → 나중에 팀판으로 옮길 수 있음)
  db.py             연결·초기화·시드 적재·TTL 내보내기
  seed\seed_data.py 농·임·수산 분류 골격 + 사과박 상세 + 기본 시소러스
  thesaurus.py      표기→개념, 동의어 확장, 사전 라벨링
  search.py         FTS5 trigram(3글자 이상) + LIKE(짧은 말) + 동의어 확장
  ingest\           parsers(+로컬 OCR) · chunker · coa · pipeline · watcher
  labeling.py       AI 라벨 실행: 묶음·재시도·취소·이어하기(run·run_step에 진행 기록)
  tools.py          MCP 도구 (가림·검토 대기 규칙 포함)
  mcp_server.py     MCP 서버 byorbit-rd (stdio)
  engines\          claude_code(기본) · food_mcp(식품 영양 DB, 선택) · codex(보조)
  viz\              structures(분자 구조·RDKit·PubChem) · drying(건조 모델·상평형도·비교) · system(흐름 지도)
  routes_viz.py     /api/viz
  server.py         FastAPI
  static\           index.html 화면 · viz\ 시각화 모듈 · vendor\ 3Dmol.js·three.js
agents\             라벨러·사서·성분 분석가·검증자·리포트 작성자 지침
tests\             test_m1 · test_m2 · test_codex · test_ocr · test_viz (시험 125개)
docs\PLAN-M2.md    M2·시각화 계획과 작업 계약
```

## 시험

```
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

DB·시드, 4개 형식 투입, CoA 측정값, 중복 거절, 동의어 검색, 기밀 가림·차단, 라벨 저장 규칙, 리포트 근거 검사를 확인합니다. 실제 MCP 서버 프로세스와의 stdio 연결, Claude Code 명령 구성과 결과 해석(가짜 CLI), 식품 DB 연결(허용·차단 목록, 가짜 Food MCP 서버 점검), 웹 API도 함께 시험합니다. M2에서는 라벨 일괄 실행(묶음·재시도·취소·이어하기, 가짜 엔진), 검토 되돌리기, CoA 양식, 시드 업그레이드, 접근 방어, Codex 명령 구성·결과 해석, OCR(실제 엔진 시험은 RapidOCR 설치 시), 분자 구조·건조 비교·흐름 지도를 시험합니다.

## 다음 단계

- **M2 (완료)**: 라벨 일괄 처리·진행률·재시도, 검토 단축키, ByOrbit CoA 양식, Codex 연결, 로컬 OCR, 시각화(흐름·건조 방식·분자 구조)
- **M3**: 에이전트 5종 캔버스(드래그앤드롭), 검증자 자동 실행, 리포트 내보내기(DOCX/PDF), `.byorbit` 내보내기 패키지
