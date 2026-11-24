# ByOrbit R&D Studio 개인용 — 1단계(M1)

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
| 자료함 | 파일을 끌어다 놓거나 받은편지함 폴더에 넣습니다. 파싱 → 정규화 → 청킹 → 사전 라벨 → 적재 단계가 표시됩니다. "AI 라벨"은 Claude Code가 수치 라벨을 제안하는 베타 기능입니다. |
| 검색 | 동의어까지 넓혀서 찾습니다. 예를 들어 "사과 포마스 TDF"는 사과박·apple pomace… 그리고 식이섬유·총식이섬유…로 넓어집니다. 결과를 누르면 원문과 라벨이 보입니다. |
| 라벨 검토 | AI가 제안한 수치 라벨과 신뢰도 0.9 미만 라벨을 승인하거나 거절합니다. 승인한 수치는 측정값 표로 올라갑니다. |
| 측정값 | CoA에서 읽은 값과 승인한 추출값을 봅니다. CSV로 저장할 수 있습니다. |
| 개념 | 부산물 분류 트리(표준 시드)와 동의어를 보고, 내 확장 개념을 추가합니다. |
| AI에 묻기 | Claude Code가 자료를 찾아 출처를 달아 답합니다. "리포트 작성자"를 고르면 근거 번호가 달린 초안을 `reports` 폴더에 저장합니다. |
| 설정 | 엔진 상태, CoA 전송 규칙, 기본 프로젝트, 데이터 폴더 경로를 다룹니다. |

**받은편지함**: 데이터 폴더의 `inbox`에 파일을 넣으면 자동으로 처리되어 `library\<프로젝트>\`로 옮겨집니다. `inbox\<프로젝트명>\`에 넣으면 그 프로젝트로 들어갑니다.

**예시 자료로 시험하기**: `.venv\Scripts\python -m app.cli samples --project "사과박 식이섬유"`를 실행하면 가상 논문 PDF, CoA 엑셀, HWPX 보고서, 메모가 받은편지함에 들어갑니다. 수치는 모두 가짜입니다.

## 지원 형식

| 형식 | 처리 |
|---|---|
| PDF | 본문과 표를 추출합니다(PyMuPDF). 스캔본은 "OCR 필요"로 표시하며, OCR은 2단계에서 다룹니다. |
| HWPX | 본문과 표를 추출합니다. 구 HWP는 한글에서 "HWPX로 저장"한 뒤 넣으세요. |
| XLSX | 표로 넣습니다. CoA 양식(시험항목·결과 머리글)이면 시료와 측정값으로 자동 적재하고, 등급을 "기밀"로 둡니다. |
| TXT / MD / CSV | 문단 단위로 넣습니다. |

CoA 머리글 별칭은 `app/ingest/coa.py`의 `COA_TEMPLATE`에서 늘릴 수 있습니다. 실제 성적서 양식이 오면 여기에 맞춥니다.

## AI로 무엇이 나가나

Claude Code를 쓰는 순간에는 질문과 도구가 돌려준 본문 일부가 Anthropic으로 전송됩니다. 자료함, DB, 원본 파일 자체는 올라가지 않습니다.

| CoA 규칙 | AI에 넘어가는 것 |
|---|---|
| 필요한 값만·식별 정보 가림 (기본) | 측정값과 본문은 넘기되, 로트번호·공급처·시료번호는 `[가림]`으로 바꿉니다. 측정값 표는 "시료 n"으로만 구분합니다. |
| 보내지 않기 | 기밀(CoA) 본문과 측정값을 전혀 넘기지 않습니다. |

Claude Code에는 이 앱의 도구 7개만 허용하고, 파일 읽기를 포함한 내장 도구(셸·파일 읽기/수정·웹·하위 에이전트)는 모두 없애고 실행합니다(`--tools ""`, `--strict-mcp-config`, `--allowedTools`, `--disallowedTools`). 그래서 Claude Code가 `library\`의 원본 파일을 직접 읽어 가림을 우회할 수 없습니다.

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
  ingest\           parsers · chunker · coa · pipeline · watcher
  tools.py          MCP 도구 (가림·검토 대기 규칙 포함)
  mcp_server.py     MCP 서버 byorbit-rd (stdio)
  engines\          claude_code(기본) · codex(2단계)
  server.py         FastAPI
  static\index.html 화면
agents\             라벨러·사서·성분 분석가·검증자·리포트 작성자 지침
tests\test_m1.py    시험 29개
```

## 시험

```
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

DB·시드, 4개 형식 투입, CoA 측정값, 중복 거절, 동의어 검색, 기밀 가림·차단, 라벨 저장 규칙, 리포트 근거 검사를 확인합니다. 실제 MCP 서버 프로세스와의 stdio 연결, Claude Code 명령 구성과 결과 해석(가짜 CLI), 웹 API도 함께 시험합니다.

## 다음 단계

- **M2**: 라벨링 본격화(청크 일괄 처리, 진행률, 재시도), 라벨 검토 단축키, 실제 CoA 양식 템플릿, Codex 연결, OCR(선택 설치)
- **M3**: 에이전트 5종 캔버스(드래그앤드롭), 검증자 자동 실행, 리포트 내보내기(DOCX/PDF), `.byorbit` 내보내기 패키지
