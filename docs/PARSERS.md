# 파서 도구 안내 (M3-2 문서 작업대 · 파서 선택)

자료마다 파서(문서 → 제목·본문·표 블록)를 골라 **다시 파싱**하고, 결과를 **나란히 비교**한 뒤, 마음에 드는 결과로
**다시 청킹**합니다. 화면: 문서 작업대의 '파싱' 탭(단독 확인: `/static/doc/parse-dev.html?doc=<doc_id>`).
API: `/api/parse` (`app/routes_parse.py`). 코드: `app/ingest/parser_tools/`.

## 0. 공통 원칙

- **문서 파일이 PC 밖으로 나가는 도구는 Upstage 하나뿐입니다.** 나머지는 모두 이 PC 안에서 읽습니다.
  (Docling·RapidOCR은 처음 한 번 모델 파일을, kordoc은 설치 때 npm 패키지를 내려받을 뿐 문서는 보내지 않습니다.)
- '기밀' 문서는 클라우드 도구로 **보낼 수 없습니다** — 화면이 버튼을 잠그고, API가 403으로 막고, 도구 모듈도 한 번 더 확인합니다.
  보안 등급을 알 수 없을 때도 보내지 않습니다. '내부' 문서는 실행할 때마다 화면에서 '보낸다'를 확인해야 합니다(API 409).
- 도구를 실행하는 것만으로는 청크·라벨이 **바뀌지 않습니다.** 결과는 `데이터 폴더\parsed\<doc_id>\<도구>-<id>.json`과
  `parse_result` 표에 쌓이고, '이 결과로 다시 청킹'을 눌러야 바뀝니다.
- 새로 넣는 파일은 **형식별 기본 도구**로 읽습니다(`데이터 폴더\config\parsers.json`, 화면에서 변경).
  기본 도구가 설치되지 않았거나 실패하면 기존 파서로 대신 읽고 자료 메모에 남깁니다. 클라우드 도구는 기본으로 둘 수 없습니다.
  어떤 도구로 읽었는지는 `document.parse_status.tool`·`document.parser_ver`(`<도구>/<판>`)에 남습니다.

## 1. 한눈에 보기

| 도구 (key) | 형식 | 어디서 | 설치 | 강점 | 약점 |
|---|---|---|---|---|---|
| PyMuPDF (`pymupdf`) — PDF 기본 | PDF | 로컬 | install.bat에 포함 | 가장 빠름, 일반 논문 PDF | 표가 본문보다 앞에 나옴(쪽 안 순서), 2단 순서가 섞일 수 있음 |
| pdfplumber (`pdfplumber`) | PDF | 로컬 | requirements.txt에 포함(약 8MB) | 선 있는 표, 글자 크기로 제목·단계 판단, 표를 제자리 순서로 | 셀 밖으로 넘친 글자가 옆 칸에 붙을 수 있음, OCR 없음 |
| RapidOCR (`rapidocr`) — 이미지 기본 | PDF·이미지 | 로컬 | install-ocr.bat(약 60MB + 모델 20~25MB) | 스캔본·사진·글자층이 깨진 PDF | 느림(쪽당 수 초), 인식 오류 가능 |
| Docling (`docling`) | PDF·이미지 | 로컬 | install-docling.bat(약 1.5GB + 첫 실행 모델 약 500MB) | 2단 논문 읽기 순서, 캡션을 표에 붙임, 복잡한 표 | 매우 큼, 첫 실행 30초 이상 |
| kordoc (`kordoc`) — .hwp 기본 | HWP(구 형식)·HWPX·PDF | 로컬(Node) | install-kordoc.bat(Node 18+, 약 100MB) | **구 형식 .hwp**, 병합 셀 표, 목록·각주 | PDF의 한글 CID 글꼴을 못 읽는 경우가 있음(아래 5절) |
| HWPX 기본 (`hwpx`) | HWPX | 로컬 | 없음 | 빠름 | 쪽 번호 없음, 병합 셀 단순 처리 |
| 엑셀 기본 (`xlsx`) | XLSX·XLSM | 로컬 | 없음 | 시트별 표 | — |
| 텍스트 기본 (`text`) | TXT·MD·CSV | 로컬 | 없음 | 인코딩 자동 | — |
| Upstage Document Parse (`upstage`) | PDF·이미지·HWP·HWPX | **클라우드** | 키 `BYORBIT_UPSTAGE_KEY` | 한국어 스캔본, 복잡한 표 | **파일이 밖으로 나감**, 쪽당 요금, 동기 API 100쪽·50MB까지 |

## 2. 설치

- **pdfplumber**: `requirements.txt`에 고정판(`pdfplumber==0.11.11`, 의존 pdfminer.six·pypdfium2 — 합쳐 약 8MB, 순수 파이썬+작은 휠)으로
  넣었습니다. 가벼워서 선택 설치로 빼지 않았습니다. 이미 설치한 PC는 `install.bat`을 다시 실행하거나
  `.venv\Scripts\python -m pip install -r requirements.txt`.
- **RapidOCR**: `install-ocr.bat` (기존).
- **Docling**: `install-docling.bat` → `requirements-docling.txt`(`docling==2.152.0`). PyTorch(CPU)가 함께 들어와 약 1.5GB,
  설치 4분 안팎(2026-11-25 측정). 처음 변환할 때 레이아웃·표 모델 약 500MB를 Hugging Face에서 받아 사용자 폴더 `.cache\huggingface`에 둡니다.
  첫 변환 약 30초, 그다음은 예시 1쪽 PDF 약 1초(같은 프로세스) / 8초(새 프로세스, 모델 적재 포함).
- **kordoc**: `install-kordoc.bat` → `tools\node`에 `kordoc@2.5.2` + `pdfjs-dist@4.10.38`(PDF용)을 npm으로 설치(약 100MB, 5초 안팎).
  `tools\node\.gitignore`가 함께 생겨 저장소에 올라가지 않습니다. 찾는 순서: 환경 변수 `BYORBIT_KORDOC_DIR`(node_modules가 있는 폴더)
  → `tools\node` → 옆 폴더 `04_byorbit-agent`(이미 설치된 것을 읽기 전용으로 사용, 이 경우 pdfjs-dist가 없어 HWP·HWPX만).
  Node 경로는 `BYORBIT_NODE`로 바꿀 수 있습니다.
- **Upstage**: 콘솔(https://console.upstage.ai)에서 키를 만들어 환경 변수에 넣습니다(설정 파일·DB에 저장하지 않음):
  ```powershell
  [Environment]::SetEnvironmentVariable("BYORBIT_UPSTAGE_KEY", "<키>", "User")   # 지정 후 start.bat으로 앱을 다시 켠다
  ```

## 3. Upstage Document Parse (클라우드) — 보내는 것과 비용

- 공식 문서(2026-11-25 확인): API https://console.upstage.ai/api/parse/document-parsing ,
  기능 안내 https://console.upstage.ai/docs/capabilities/document-digitization/document-parsing
- 요청: `POST https://api.upstage.ai/v1/document-digitization`, `Authorization: Bearer <키>`, multipart —
  `document`(파일), `model=document-parse`, `mode=standard|enhanced|auto`, `ocr=auto|force`, `output_formats=['html', 'text']`, `coordinates=false`.
- **보내는 것: 문서 파일 내용 전체.** 파일 이름은 보내지 않습니다(`document.pdf`처럼 확장자만). 프로젝트명·보안 등급·다른 자료는 보내지 않습니다.
- 응답 `elements[]`의 category를 블록으로 바꿉니다: `heading1`(…) → 제목, `table`(HTML) → 표(행·열, 병합 칸은 빈 칸), `paragraph`·`list`·`caption`·
  `footnote`·`equation`·`index` → 본문, `header`·`footer`·`figure` → 건너뜀(경고에 개수).
- 비용(https://www.upstage.ai/pricing , 2026-11-25 확인, 부가세 10% 별도): Standard **$0.01/쪽**, Enhanced **$0.03/쪽**(auto는 최대치로 추정).
  실행 전 확인 창에 `쪽 수 × 단가` 추정을 보여 줍니다(PDF·이미지만 쪽 수를 미리 셉니다). 실제 청구 쪽수는 결과의 `billed_pages`.
- 한도: 동기 API 100쪽, 파일 50MB — 넘으면 보내기 전에 막습니다.
- 오류 메시지에서 키를 가립니다(`app/collect/http.py`의 redact + 도구에서 한 번 더). 401/403 → 키 확인, 402 → 크레딧 확인 안내.
- **실제 키로는 아직 검증하지 않았습니다**(가짜 응답 시험만). 응답 형식이 바뀌면 `upstage_tool.convert`를 고칩니다.

## 4. 어떻게 고르나

1. 먼저 기본 도구 결과(자료를 넣을 때 자동으로 생김, '지금 청크')를 봅니다.
2. 표가 중요한 PDF(성적서·보고서) → **pdfplumber**를 실행해 표 셀을 비교합니다.
3. 2단 논문에서 문단 순서가 뒤섞이거나 캡션이 본문에 섞이면 → **Docling**.
4. 쪽마다 글자 수가 0에 가깝거나 '스캔본 추정' 경고 → **RapidOCR**(로컬). 그래도 나쁘면, 기밀이 아닌 자료에 한해 **Upstage**.
5. 구 형식 `.hwp` → **kordoc**(기본). 한글 HWPX에서 병합 셀 표가 깨지면 kordoc과 HWPX 기본을 비교합니다.
6. 비교 화면의 쪽 막대(쪽별 글자 수)에서 한쪽만 0인 쪽은 그 도구가 그 쪽을 놓친 것입니다.

## 5. 다시 청킹이 라벨·측정값에 주는 영향

'이 결과로 다시 청킹'(`POST /api/parse/docs/{doc_id}/choose`, `pipeline.reprocess_from_blocks`)은 문서·출처 행과 원본 파일은 그대로 두고:

- 섹션·표·청크를 새로 만듭니다. 작업대 규칙이 있으면 청커 값(`chunk_rules.chunker_params`)과 규칙 적용(`chunk_rules.apply`)을 다시 합니다.
- **사전·AI 라벨(dict·regex·llm)은 지웁니다.** 사전 라벨은 바로 다시 만들고, AI 라벨은 'AI 라벨'을 다시 실행해야 합니다.
- **사용자 라벨(method='human')과 검토에서 승인한 라벨(status='accepted')은 옮깁니다.** 같은 표기가 새 청크에 있는 자리 중
  문서 안 상대 위치가 가장 가깝고 같은 쪽인 곳으로 옮기며, `ann_id`를 그대로 써서 측정값·라벨 사례·관계 연결이 유지됩니다.
  옮긴 라벨과 같은 자리의 새 사전 라벨은 중복이라 뺍니다. 같은 표기를 못 찾은 라벨은 **옮기지 못한 목록**으로 보고합니다.
- **측정값은 지우지 않습니다.** 지워진 라벨(사전·AI·못 옮긴 사용자 라벨)에 연결되어 있던 측정값은 외래키(ON DELETE SET NULL)로
  라벨 연결(`ann_id`)만 비고 측정값 표에 그대로 남습니다. 그 개수를 보고합니다.
- 리포트 인용이 옛 청크를 가리키면 청크 연결만 끊습니다(인용 문장은 남음). 개수를 보고합니다.
- CoA(엑셀) 측정값은 파서와 무관하게 파일에서 읽으므로 그대로 둡니다(아직 없으면 새로 읽습니다).
- 시작 전에 옮길 라벨과 옛 청크를 `parsed\<doc_id>\rechunk-backup-<시각>.json`에 적어 둡니다(중간에 앱이 꺼져도 되살릴 수 있게).

## 6. 알려진 한계

- kordoc의 PDF 읽기(pdfjs)는 cMap 설정 없이 동작해, 한글 CID 글꼴로 만든 PDF(예: 예시 논문)는 '글자 없음'으로 실패합니다.
  PDF는 PyMuPDF·pdfplumber·Docling을 쓰고 kordoc은 HWP·HWPX에 쓰세요.
- HWP·HWPX의 '쪽'은 kordoc에서 구역(section) 단위 근사치이고, HWPX 기본 파서는 쪽 정보가 없습니다(비교 화면에서 '쪽 정보 없음').
- 한 칸·한 줄짜리 표(한글 문서의 제목 상자 등)는 kordoc 결과에서 본문(또는 제목)으로 바꿉니다.
- 같은 도구를 다시 실행하면 그 도구의 이전 결과(선택되지 않은 것)를 바꿉니다. 선택된 결과는 남습니다.
- 작업 진행 상태(`/api/parse/jobs/{id}`)는 메모리에만 있어 앱을 다시 켜면 사라집니다(결과 자체는 DB·파일에 남음).
