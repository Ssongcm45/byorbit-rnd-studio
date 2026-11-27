# R&D Studio V0.5

> **처음이라면** → [빠른 사용 설명서 (docs/QUICKSTART.md, 4쪽 PDF: docs/QUICKSTART.pdf)](docs/QUICKSTART.md) · 자세한 안내서: `guidebook/final/guidebook.pdf`

농·임·수산 부산물 연구 자료(논문·보고서·CoA)를 **내 PC에서** 모으고, 찾고, Claude Code에게 근거 있는 답을 받는 로컬 웹앱입니다.

- 자료·DB·온톨로지는 모두 이 PC의 데이터 폴더(기본 `C:\Users\<이름>\ByOrbit-RD`)에만 저장됩니다.
- AI는 이 PC에 설치·로그인된 **Claude Code**를 씁니다. Claude Code는 이 앱의 자료 서버(MCP `byorbit-rd`)를 통해서만 자료를 읽고 씁니다.
- 브라우저 화면은 `http://127.0.0.1:8765`. 같은 PC에서만 열립니다.

## 설치 (Windows)

1. **Python 3.11 이상**: `winget install Python.Python.3.12` 또는 python.org에서 설치합니다. 설치할 때 "Add to PATH"를 체크하세요.
2. **Claude Code**: PowerShell에서 `irm https://claude.ai/install.ps1 | iex`를 실행합니다(또는 `npm install -g @anthropic-ai/claude-code`). 그다음 `claude`를 한 번 실행해 로그인합니다.
3. 이 폴더에서 **`install.bat`**을 더블클릭합니다. 가상환경, 패키지, 데이터 폴더, 표준 시드, MCP 설정이 준비됩니다.
4. **`start.bat`**을 더블클릭하면 브라우저가 열립니다. 끝낼 때는 검은 창에서 Ctrl+C를 누릅니다.
5. 앱의 **설정 → Claude Code 연결 마법사**에서 ① 설치 ② 로그인을 확인하고 ③ 연결 점검(실제 호출)에서 "통과"가 나오면 Claude Code 연결이 끝난 것입니다. `check-claude.bat`으로도 상태를 볼 수 있습니다(실제 호출은 물을 때 `y`를 누를 때만).

> PowerShell이 스크립트 실행을 막으면 `install.bat`을 쓰세요(실행 정책을 이번 실행에만 우회합니다).

## 다른 PC에 설치하고 Claude Code와 연결하기

새 PC에서는 GitHub에서 받아 설치하고, **그 PC에 설치·로그인된 Claude Code**와 연결합니다. 자료·API 키·로그인은 PC마다 따로이며 자동 동기화는 없습니다.

1. **받기** — 공개 저장소이므로 GitHub 계정이나 로그인 없이 받을 수 있습니다.
   - Git이 있으면:
     ```
     git clone https://github.com/Ssongcm45/byorbit-rnd-studio.git
     ```
     (고친 내용을 저장소에 올리려면 쓰기 권한이 있는 계정으로 `gh auth login`(GitHub CLI) 또는 GitHub Desktop 로그인이 필요합니다.)
   - Git이 없으면: https://github.com/Ssongcm45/byorbit-rnd-studio → Code → Download ZIP으로 받아 풀어 둡니다.
2. **Python 3.11 이상**과 **Claude Code**를 설치합니다(위 "설치" 1·2번). Claude Code는 새 PC에서 `claude`를 한 번 실행해 **그 PC에서** 로그인합니다.
3. **`install.bat`** 더블클릭 — 가상환경·패키지·데이터 폴더를 만든 뒤 마지막 [5/5]에서 이 PC의 Claude Code를 찾아(공식 설치·npm 설치·WinGet·`BYORBIT_CLAUDE` 지정) 버전과 로그인 상태를 보여 줍니다. 돈이 드는 호출은 하지 않습니다.
   - 설치·로그인이 되어 있으면 "내 Claude Code 대화창에도 자료 도구를 등록할까요? (Y/n)"를 묻습니다. Enter(=예)를 누르면 등록합니다(아래 "Claude Code에서 직접 쓰기").
   - 설치·로그인이 안 되어 있으면 다음에 할 명령을 그대로 보여 줍니다. 마친 뒤 `check-claude.bat`을 실행해 다시 확인합니다.
4. **`start.bat`** 더블클릭 → 앱의 **설정 → Claude Code 연결 마법사**에서 ① 설치 ② 로그인 ③ 연결 점검(실제 호출) ④ 자료 도구 등록을 차례로 확인합니다. 시작 화면 체크리스트 1번의 "연결 마법사 열기"로도 갑니다.
5. **API 키 다시 넣기** — 키는 각 PC의 Windows 자격 증명 관리자에만 있어 옮겨지지 않습니다. 설정 → API 키 관리에서 다시 저장합니다.
6. **자료 옮기기(선택)** — 이전 PC의 데이터 폴더(`C:\Users\<이름>\ByOrbit-RD`)를 앱을 끈 상태에서 통째로 새 PC의 같은 위치에 복사합니다. 두 PC에서 따로 고친 자료는 합쳐지지 않습니다.

명령줄로도 같은 확인·등록을 할 수 있습니다.

```
.venv\Scripts\python -m app.cli setup-claude --check        설치·로그인·등록 상태 (질문 보내지 않음)
.venv\Scripts\python -m app.cli setup-claude --register     내 Claude Code(사용자 범위)에 자료 도구 등록
.venv\Scripts\python -m app.cli setup-claude --unregister   등록 해제
```

`--check`의 종료 코드: 0 준비됨 · 2 로그인 안 됨 · 3 설치 안 됨 · 4 설치됨(로그인 상태 모름 — 오래된 CLI) · 5 이미 등록됨 · 1 오류. 로그인 상태는 `claude auth status`(Claude Code 2.1.x)로 읽고, 이메일·조직 이름은 화면에 담지 않습니다.

> npm으로 설치한 Claude Code(`claude.cmd`)는 콘솔 없이 도는 앱에서 실패할 수 있어, 앱은 그 안쪽의 `claude.exe`를 직접 부릅니다. Claude Code가 여러 군데 설치되어 있으면 마법사가 알려 주며, 다른 것을 쓰려면 환경 변수 `BYORBIT_CLAUDE`에 경로를 넣습니다.

## 쓰는 법

앱을 켜면 **시작** 화면이 열립니다. 왼쪽 메뉴는 시작 / 자료(자료함·자료 수집·검색·개념 사전·지식그래프) / 라벨(라벨 검토) / 실험·분석(측정값·내 실험·통계 분석) / 보기·AI(시각화·AI에 묻기) / 설정으로 묶여 있습니다(좁은 화면에서는 ☰ 버튼). 시작 화면의 **처음 사용 체크리스트**를 위에서부터 따라 하면 됩니다 — "예시 자료 넣기" 버튼은 가짜 수치의 예시 자료를 받은편지함에 넣고 바로 처리합니다. 위쪽 검색창(Ctrl+K 또는 /)에서 어디서든 검색하고, ? 버튼(또는 입력칸 밖에서 ?)으로 단축키 도움말을 엽니다. 메뉴·화면 제목·주요 카드 옆의 **(?)** 를 누르면 그 기능이 무엇인지, 언제·어떻게 쓰는지, PC 밖으로 무엇이 나가는지, 안내서 몇 장을 보면 되는지 나옵니다(머리글의 '도움말 표시'로 켜고 끔). 설명 문구는 `app/static/help/help.js` 한 곳에 모여 있습니다.

| 화면 | 하는 일 |
|---|---|
| 자료함 | 파일을 끌어다 놓거나 받은편지함 폴더에 넣습니다. 파싱 → 정규화 → 청킹 → 사전 라벨 → 적재 단계가 표시됩니다. "AI 라벨"은 청크를 5개씩 묶어 Claude Code에 맡기고 진행률(성공·오류·건너뜀)을 보여 줍니다. 엔진이 실패한 묶음은 2번까지 다시 시도하고, AI가 라벨할 내용을 찾지 못한 청크는 2번 확인한 뒤 건너뜁니다. 이미 AI 라벨이 있는 청크는 건너뜁니다. "취소"는 지금 묶음이 끝나면 멈추고, "재시도"는 남은(대기·오류) 청크만 다시 처리합니다. 앱을 껐다 켜면 끝나지 못한 실행은 "중단됨"으로 표시되고 재시도로 이어 할 수 있습니다. |
| 검색 | 동의어까지 넓혀서 찾습니다. 예를 들어 "사과 포마스 TDF"는 사과박·apple pomace… 그리고 식이섬유·총식이섬유…로 넓어집니다. 결과를 누르면 원문과 라벨이 보입니다. |
| 라벨 검토 | AI가 제안한 수치 라벨과 신뢰도 0.9 미만 라벨을 승인하거나 거절합니다. 승인한 수치는 측정값 표로 올라가고, 그 자료의 부산물(CoA 시료 또는 본문에 가장 많이 나온 부산물)에 연결됩니다. 단축키: J/K(↓/↑) 이동, A 승인, R 거절, U 마지막 결정 되돌리기(승인으로 올린 측정값도 지움), ? 도움말. 입력칸에 쓰는 동안에는 동작하지 않습니다. |
| 측정값 | CoA에서 읽은 값과 승인한 추출값을 봅니다. CSV로 저장할 수 있습니다. |
| 개념 | **분류·목록**: 부산물 분류 트리(표준 시드)와 동의어를 보고, 내 확장 개념을 추가합니다. **지식그래프**: 개념(점)과 관계(선)에 언급 자료·측정값을 이어 붙인 지도입니다(아래 "지식그래프"). |
| AI에 묻기 | Claude Code가 자료를 찾아 출처를 달아 답합니다. "리포트 작성자"를 고르면 근거 번호가 달린 초안을 `reports` 폴더에 저장합니다. |
| 수집 | 공식 API(해외 학술·국내 학술·국가 R&D·특허·공공데이터)와 크롤러로 논문·보고서·특허·데이터를 찾아 **수집함**에 모읍니다. 검토 후 '자료함에 넣기'(오픈 액세스면 원문, 아니면 서지·초록). 검색을 저장하면 앱이 켜져 있는 동안 정한 주기로 새 자료를 찾습니다(아래 "자료 수집"). |
| 실험 | 공정 흐름(원료→세척→탈수→분쇄→건조→분말화→추출→저장)을 직접 고치고, 내 실험 데이터를 넣어(표 입력·CSV/XLSX) 예측과 비교하고 모델을 보정합니다(아래 "내 실험"). |
| 분석 | 회귀분석·t검정·가정 점검과 논문용 표 1개·그림 1장·해석 세 문장, Python·R·Stata 재현 파일(아래 "통계 분석"). |
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
  config\       settings.json · mcp.json · keys-meta.json(키 저장 시각만 — 키 값 없음)
  logs\         처리 실패 기록
```

백업은 이 폴더를 통째로 복사하면 됩니다. 다른 위치를 쓰려면 환경 변수 `BYORBIT_HOME`을 지정하세요.

## Claude Code에서 직접 쓰기

앱 밖, 평소 쓰는 Claude Code 대화창에서도 이 자료 서버(`byorbit-rd`)를 쓸 수 있습니다.

**한 번 등록해 두기(권장)** — 설정 → Claude Code 연결 마법사 ④ "등록"(또는 `install.bat`의 질문, `app.cli setup-claude --register`). 내부적으로 다음을 실행해 Claude Code **사용자 범위**(모든 폴더의 대화)에 넣습니다. 설정 값은 앱의 `mcp.json`과 같습니다(이 PC의 가상환경 파이썬, `BYORBIT_HOME`·`PYTHONPATH`·`PYTHONUTF8`).

```
claude mcp add-json --scope user byorbit-rd "{...mcp.json의 byorbit-rd 설정...}"
```

그다음 아무 Claude Code 대화에서 "byorbit-rd로 사과박 식이섬유 자료 찾아줘"처럼 부탁하면 됩니다. 앱 폴더나 데이터 폴더를 옮겼으면 마법사가 "지금 앱과 다름"으로 알려 주니 다시 등록하세요. 빼려면 마법사의 "해제"(또는 `claude mcp remove --scope user byorbit-rd`).

**한 번만 붙여 쓰기** — 등록하지 않고 그 대화에만:

```
claude --mcp-config "%USERPROFILE%\ByOrbit-RD\config\mcp.json"
```

도구는 `search_chunks`, `get_chunk`, `lookup_concept`, `query_measurements`(읽기)와 `save_annotations`, `save_report_draft`, `propose_concept`(쓰기 — DB를 직접 고치지 않고 라벨·리포트 초안·개념 제안을 남기며, 수치 라벨과 개념 제안은 검토 대기)입니다. 식품 영양 DB 서버는 등록하지 않습니다.

> **보안 주의** — 내 Claude Code 대화창에서는 Claude가 자기 파일 읽기(Read·Grep)·셸 같은 내장 도구도 함께 씁니다. 그래서 내장 도구를 모두 끄고 실행하는 앱 안 "AI에 묻기"(`--tools ""`)보다 기밀 원본 보호가 약합니다. Claude가 데이터 폴더의 CoA 원본 파일을 직접 읽으면(권한을 허락했거나 묻지 않는 모드일 때) 가림이 적용되지 않습니다. `byorbit-rd` 도구 자체는 CoA 규칙(식별 정보 가림·보내지 않기)을 그대로 지킵니다. 기밀 자료는 앱 안 "AI에 묻기"로 다루세요.

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

## 지식그래프 (개념 탭)

개념 탭 위쪽의 **지식그래프**를 누르면, 개념(점)과 관계(선)로 이어진 지식 지도가 나옵니다. 동의어는 같은 점으로 모입니다. 처음에는 **사과박**을 가운데에 두고 바로 이어진 점(1단계)을 보여 줍니다.

- **점**: 개념은 체계마다 색이 다릅니다(부산물·분류·원물·공정·성분·물성·단위·시험법·용도). 네모는 그 개념을 라벨로 가리킨 **자료(문서)** 입니다. 테두리가 점선인 점은 지금 보이지 않는 이웃이 더 있다는 뜻입니다.
- **선**: 상위 분류(broader) · 원료(derivedFrom) · 발생 공정(generatedBy) · 함유 성분(contains) · 측정(부산물 → 측정 항목, 값 개수·평균·범위) · 언급(자료 → 개념, 라벨 수) · 기타 관계. 위의 선 칩을 눌러 켜고 끕니다.
- **찾기**: 표준명·동의어·숨은 표기 어느 것으로 찾아도 됩니다. 예: "사과 포마스"를 치면 `사과 포마스 → 사과박`으로 보여 주고 고르면 사과박이 가운데로 옵니다.
- **깊이** 1단계·2단계, **배치** 그물(cose)·단계(가운데에서 1·2단계를 둥근 띠로). 점이 150개를 넘으면 가까운 것만 보이고 "더 있음"이 표시됩니다.
- 점을 누르면 옆 패널에 표준명·영문·동의어·숨은 표기·체계·IRI·관계 목록·언급 자료(작업대 열기·검색 열기)·측정값 요약이 나옵니다. 두 번 누르면 그 개념을 가운데로 옮기고, **← 이전**으로 돌아갑니다. 그림 아래 **이웃 목록**은 같은 내용을 키보드로 볼 수 있게 한 목록입니다.
- **TTL 내보내기**: 표준 시드 + 내 확장을 SKOS Turtle 파일 하나로(Protégé 등에서 열 수 있음). **JSON 내보내기**: 점·선 목록. JSON은 PC 밖으로 옮겨질 수 있으므로 기밀 자료 이름은 `기밀자료-xxxxxx`로 가리고 기밀 자료·시료의 측정값은 넣지 않습니다. 로트·공급처·시료번호는 화면·내보내기 어디에도 싣지 않습니다.
- API: `/api/kg/search` · `/api/kg/graph` · `/api/kg/concept/{id}` · `/api/kg/document/{id}` · `/api/kg/stats` · `/api/kg/export.ttl` · `/api/kg/export.json`. 그래프 라이브러리 cytoscape.js 3.30.2는 `app/static/vendor/`에 고정 버전으로 들어 있어 인터넷 없이 동작합니다.
- 온톨로지·시소러스·지식그래프가 이 앱에서 무엇이고 어떻게 늘리는지는 `docs/ONTOLOGY.md`에 쉽게 정리했습니다.

## 시각화

- **흐름**: R&D Studio(이 PC)와 ByOrbit Food MCP가 Claude Code를 가운데 두고 어떻게 이어지는지, 각 경계를 무엇이 넘는지(PC 밖으로 나가는 것) 보여 줍니다. 상자·선을 누르면 자세히 나옵니다. 아래에 자료 → 청크 → 라벨 → 측정값 → 리포트 개수가 프로젝트별로 나옵니다.
- **건조 설비(3D·P&ID)**: 방식마다 실제 설비 구조를 3D로 보여 줍니다 — 동결건조기(챔버·가열 선반·콘덴서·진공 펌프·냉동기), 캐비닛형 열풍 트레이 건조기(히터·송풍기·댐퍼·기류), 진공 선반 오븐, 분무건조기(분무기·건조탑·사이클론·백 필터), 노지 건조대·하우스형 태양열 건조기. 절개 보기, 부품을 누르면 역할·일반 설정값, 단계 재생에 따라 게이지가 바뀝니다. 공정 흐름도(P&ID)로 바꿔 볼 수 있습니다. 계기값은 단계별 예시이며 실제 운전 기록이 아닙니다.
- **건조 결과 예측**: 온도·시간·압력·풍속·두께를 바꾸면 최종 수분·목표 수분 도달 시간·총폴리페놀 잔존율·식이섬유·비에너지가 바로 바뀝니다. 값마다 식과 파라미터, 근거(문헌[DOI 확인·원문 위치]·실측[n]·설비 사양·가정), 적용 범위(외삽 경고)를 보여 주고, 내 CoA 실측으로 보정합니다. 슬라이더는 3D 설비 게이지와 연동됩니다. 모델·출처·가정 목록은 `docs/PREDICT-SOURCES.md`, 내 설비 사양은 데이터 폴더 `config/equipment.json`에서 고칩니다.
- **건조 방식**: 동결·열풍·진공·분무·자연건조의 공정 애니메이션, 물의 상평형도 위 공정 경로, 3D 입자 단면(기공·수축 비교, 개념도), CoA·논문 측정값의 방식별 비교(시료는 '시료 n'으로만 표시)를 봅니다. 조건·효과는 일반 문헌 경향이며 측정값이 아닙니다.
- **분자 구조**: 성분명(한글·영문·동의어)으로 2D 구조식·3D 모델·성질을 봅니다. 구조는 이 PC의 시드 24종과 RDKit으로 그려 인터넷이 필요 없습니다. 펙틴·셀룰로스·식이섬유·폴리페놀처럼 단일 분자가 아닌 것은 대표 단위체(갈락투론산·셀로비오스·갈산)로 보여 주고 그 사실을 표시합니다.
- 3D 라이브러리(3Dmol.js 2.4.2, three.js r170)는 `app/static/vendor/`에 고정 버전으로 들어 있어 오프라인에서도 동작합니다. 구조 그림에는 RDKit(requirements.txt에 포함)이 필요하며, 없으면 분자 구조 화면에 설치 안내가 나옵니다.

## 자료 수집

- **해외 학술(키 불필요)**: OpenAlex · Crossref · Europe PMC · Semantic Scholar.
- **국내·키 필요**: KCI · ScienceON · NTIS(과제·보고서) · KIPRIS(특허) · 공공데이터(식약처 식품영양성분DB · 기능성 원료 인정현황 · 농사로 농식품부산물 영양정보). 키는 **설정 → API 키 관리**에서 넣습니다(아래 'API 키 넣기'). 발급 방법은 그 카드의 '발급 안내'와 `docs/COLLECT-SOURCES.md`에 있고, 수집 화면에서 키가 없는 출처의 **설정에서 키 넣기**를 누르면 그 칸으로 바로 갑니다.
- **크롤러**: API가 없는 공개 자료 목록(농촌진흥청 보도자료, 국립농업과학원·원예특작과학원 시험연구보고서 등). robots.txt·이용약관을 확인해 허용된 곳만, 사이트마다 간격을 두고 읽습니다. 사이트는 수집 화면에서 추가·끄기.
- **크롤러 가져오기 방식**(사이트마다 선택, 규칙은 같음): **기본**(이 PC에서 HTTP) · **브라우저**(이 PC의 헤드리스 Chrome — 자바스크립트로 그리는 목록용, `install-browser.bat`로 설치. 설치된 Chrome을 쓰고 http/https 주소만 엽니다) · **Apify**(클라우드·유료, 선택 — 사이트 주소와 크롤 설정이 Apify로 나가고 크레딧이 듭니다. 토큰은 설정 → API 키 관리의 `BYORBIT_APIFY_TOKEN`, 실행마다 비용 상한 기본 0.5 USD, 실제 토큰으로 미검증). 사이트 카드의 **시험 수집**(최대 3쪽)으로 바로 확인합니다. AI에게 브라우저를 도구로 주지 않습니다(Playwright MCP를 쓰지 않는 이유: `docs/COLLECT-SOURCES.md`).
- **나가는 것**: 검색어(와 그 출처의 API 키)뿐. 자료함·CoA·시료·실험 데이터는 보내지 않고, 오류 메시지에서도 키를 가립니다. 같은 자료는 DOI·출처 ID·제목으로 하나로 합칩니다.
### API 키 넣기 (설정 → API 키 관리)

1. 각 서비스에서 키를 발급받습니다(카드의 **발급 안내**에 순서와 공식 페이지 링크가 있습니다).
2. **설정 → API 키 관리**에서 그 출처의 **저장**을 누르고, 대화상자에 키를 붙여 넣은 뒤 **저장**합니다. 앱을 다시 켤 필요가 없습니다.
3. **연결 시험**으로 확인합니다 — 수집 출처는 1건짜리 시험 검색, Apify는 요금이 들지 않는 계정 조회를 합니다. Upstage는 요금 없이 키만 확인하는 방법이 없어 호출하지 않고, 실제로 쓸 때 확인합니다.

묶음: 해외 학술(OpenAlex·Semantic Scholar 선택 키) · 국내 학술(KCI, ScienceON — client_id·인증키·MAC 세 값) · 국가 R&D·특허(NTIS·KIPRIS) · 공공데이터(식약처 2종·농사로) · 크롤러·파서(클라우드: Apify 토큰·Upstage 키).

**키는 어디에 저장되나** — 이 PC의 **Windows 자격 증명 관리자**(지금 로그인한 Windows 계정으로 암호화, 항목 이름 `RD-Studio-V0.5`)에만 둡니다. 설정 파일·DB·로그·내보내기에는 쓰지 않고, 화면과 API에는 끝 4자리(`••••3f9a`)와 저장 시각만 보입니다(저장 시각은 키 값이 없는 `config\keys-meta.json`). 각 키는 그 키를 발급한 서비스로만 나갑니다. 오류 문구에서는 키를 `***`로 가립니다.

**환경 변수를 쓰는 방법(대안)** — 같은 이름의 환경 변수가 있으면 보관소 값보다 **먼저** 쓰입니다(화면에 '환경 변수'로 표시, 앱이 바꾸거나 지우지 않음). 자격 증명 저장소를 쓸 수 없는 PC에서는 화면이 이 방법을 안내합니다(파일에 적어 두는 대체 저장은 하지 않습니다):

```powershell
[Environment]::SetEnvironmentVariable("BYORBIT_KCI_KEY", "발급받은키", "User")   # 지정 후 start.bat으로 앱을 다시 켠다
```

- 한계: OpenAlex는 키 없이 하루 약 100회, Semantic Scholar는 키가 없으면 자주 잠시 막힙니다. 국내 API 7개 중 6개는 실제 키로 아직 확인하지 못했습니다.

## 통계 분석 (분석 탭)

- **데이터**: 내 실험(런별 조건·측정값, 산 종류는 런 메모에 `산=구연산`처럼 적음) · CSV/XLSX(열 맞추기) · 예시(사과박 펙틴 산 추출 수율, 가짜 수치).
- **분석**: 다중회귀 `수율 ~ 온도 + 반응 시간 + 산 종류`(B·SE·β·t·p·95% CI, R²·F, 이분산이면 HC3 강건 SE 병기) + 산 종류별 비교(2종: Levene → Welch/Student t, Hedges' g, Mann–Whitney 민감도 / 3종 이상: Welch ANOVA + Holm 보정 짝별 Welch t). 산 종류의 '단순 비교'와 '온도·시간 보정 효과'의 차이도 설명합니다.
- **가정 점검**: 잔차 정규성(Shapiro–Wilk), 등분산(Breusch–Pagan), 다중공선성(VIF), 영향점(Cook's D > 4/n, 런 이름 표시), 선형성, 집단별 정규성·Levene, 표본 크기 — 통과·주의·위반과 기준값을 함께 보이고, 작은 표본에서는 '유의하지 않음 = 만족'으로 단정하지 않습니다.
- **논문용 산출물**: 표 1(A 회귀·B 산 종류 비교, APA 형식 — DOCX·HTML·CSV·LaTeX·Markdown), 그림 1((a) 온도별 수율과 모형선, (b) 산 종류별 분포와 검정 — PNG 300 dpi·SVG·PDF, 1단 85 mm/2단 175 mm, 한글·영문), 해석 세 문장(한국어·영어, 계산 결과로만 만든 문장), 가정 점검 보고서·진단 그림. '논문용 묶음'으로 한 번에 받습니다.
- **재현 파일**: `data.csv`·`codebook.csv` + `analysis.py`(Python, 앱과 같은 수치를 시험으로 확인) · `analysis.R` · `analysis.do`(Stata). **R·Stata 스크립트는 이 PC에 R·Stata가 없어 실행 확인을 하지 못했습니다.** 자세히: `docs/STATS.md`.

## 문서 작업대 (파싱·청크·라벨)

자료함·검색·라벨 검토에서 **작업대**를 누르면 문서 하나를 깊게 다룹니다.

- **파싱**: 문서마다 파서를 골라 다시 파싱하고 결과를 나란히 비교한 뒤 '이 결과로 다시 청킹'. PyMuPDF(기본)·pdfplumber(표)·RapidOCR(스캔, `install-ocr.bat`)·Docling(고급, `install-docling.bat`, 약 1.5GB)·kordoc(HWP·HWPX, 구 .hwp 포함, `install-kordoc.bat` 또는 04 프로젝트의 kordoc)·Upstage(클라우드, `BYORBIT_UPSTAGE_KEY`, **기밀 문서는 차단**, 내부 문서는 매번 확인). 다시 청킹해도 사람이 붙인·승인한 라벨은 새 청크로 옮기고 측정값은 지우지 않습니다. 자세히: `docs/PARSERS.md`.
- **청크**: 너무 짧음·긺·끊긴 문장·쪼개진 표·머리말/쪽번호 잡음을 표시. 글 고치기·나누기·합치기·제목으로 올리기·잡음 줄 지우기·되돌리기.
- **규칙 학습**: 고친 내용에서 규칙(제목 패턴·잡음 줄·짧은 조각 합치기·표 유지·길이)을 제안하고, 범위(이 문서·파일 이름 패턴·제목 앞부분·형식·전체)를 골라 저장하면 비슷한 문서와 다시 파싱할 때 자동 적용합니다. 미리보기 후 적용, 규칙별 적중 수.
- **라벨**: 자동(사전 라벨 다시·AI 라벨)과 수동(본문을 골라 종류·개념·수치/단위 지정 — 수치는 측정값으로). 단축키 J/K/A/R/L.
- **사례 학습**: 모르던 표기는 '동의어로 배우기', 거절한 사전 라벨은 다음부터 건너뜀, 사람이 붙이거나 고친 라벨은 AI 라벨러의 예시(최대 8개)로 들어갑니다. 기밀 문서의 예시는 가리거나(가림 규칙) 빼고(보내지 않기·Codex) 보냅니다. 'AI에 보낼 사례 보기'로 실제로 보낼 내용을 확인할 수 있습니다.
- **배운 것**: 규칙·동의어·부정 사례·예시를 모두 목록으로 보고 끄거나 지웁니다. 자세히: `docs/WORKBENCH.md`.

## 내 실험

- **공정 흐름 편집**: 틀(사과박 동결건조 분말 · 열풍건조 분말 · 열풍건조 + 에탄올 추출)에서 시작해 단계 추가·삭제·순서·끄기·파라미터를 고칩니다. 단계 사이에 질량·수분·TPC 변화가 막대로 보입니다. 건조 단계는 '건조 방식' 탭의 예측 엔진을 그대로 써서 값과 근거가 같습니다.
- **내 데이터**: 런(조건)별로 단계·대상·값을 표에 넣거나 CSV/XLSX를 가져옵니다(열 맞추기, ND·"< 0.01"·단위 변환). 내보내기도 됩니다.
- **결과·보정**: 예측 대 실측(잔차·패리티·MAE/RMSE), 조건 하나를 바꿔 보는 민감도 곡선, 내 데이터로 모델 보정(보정 전후를 함께 표시, 활성화 에너지는 온도 3개 이상일 때 선택 시에만 다시 맞춤), 다음 실험 조건 제안.
- 근거: 건조 외 단계(세척·압착·분쇄·추출·저장)의 계수는 대부분 '가정'으로 표시됩니다. 내 값으로 바꾸면 '내 입력'이 됩니다. 자세한 내용은 `docs/EXPERIMENT.md`.

## 보안: 화면 접근

화면은 127.0.0.1/localhost 주소로만 열리고, 다른 사이트에서 보낸 쓰기 요청(POST 등)은 막습니다(DNS 리바인딩·CSRF 방어). 명령줄처럼 Origin이 없는 요청은 그대로 허용합니다.

## 명령줄

```
.venv\Scripts\python -m app.cli init            데이터 폴더·DB·시드·MCP 설정
.venv\Scripts\python -m app.cli serve           웹앱 (--port, --no-browser, --no-watch)
.venv\Scripts\python -m app.cli ingest <파일|폴더> --project 이름
.venv\Scripts\python -m app.cli search "사과 포마스 식이섬유"
.venv\Scripts\python -m app.cli check-claude    Claude Code 연결 점검 (실제 호출)
.venv\Scripts\python -m app.cli setup-claude    Claude Code 찾기·로그인 확인 (--register·--unregister: 자료 도구 등록·해제)
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
  engines\          claude_code(기본) · claude_setup(설치 찾기·로그인 확인·내 Claude Code 등록) · food_mcp(식품 영양 DB, 선택) · codex(보조)
  viz\              structures(분자 구조·RDKit·PubChem) · drying(건조 모델·상평형도·비교) · system(흐름 지도)
  routes_viz.py     /api/viz · routes_predict.py /api/viz/predict
  routes_kg.py      /api/kg — 지식그래프(찾기·그래프·자세히·통계·TTL/JSON 내보내기)
  collect\          자료 수집: base·http·registry · store·scheduler · crawler · sources\(출처별 모듈)
  experiment\       내 실험: steps(단계 모델) · store · sim · importer · calib · plan
  routes_collect.py /api/collect · routes_experiment.py /api/exp
  server.py         FastAPI
  static\           index.html 화면 · viz\ 시각화 모듈 · kg\ 지식그래프 · vendor\ 3Dmol.js·three.js·cytoscape.js
agents\             라벨러·사서·성분 분석가·검증자·리포트 작성자 지침
tests\             test_m1 · test_m2 · test_codex · test_ocr · test_viz · test_predict · test_collect · test_collect_kr · test_experiment · test_kg 등 (시험 313개)
docs\              PLAN-M2·PLAN-M3(계획·작업 계약) · PREDICT-SOURCES · COLLECT-SOURCES · EXPERIMENT · ONTOLOGY(온톨로지·시소러스·지식그래프)
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
