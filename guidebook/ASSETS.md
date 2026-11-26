# 안내서 그림 계약 (2026-11-26)

책: bookforge `practical` 스타일, 원고는 `chapters/ch-NN.md`, 그림은 `assets/`에 PNG로 둔다(마크다운에서는 파일명만: `![캡션](s01-library.png "출처: ByOrbit R&D Studio 화면")`).
독자: 중학생·AI를 처음 쓰는 연구원. 그림은 글보다 먼저 이해되게, 글자는 크게(인쇄 폭 139 mm 기준 본문 8pt 이상으로 읽히게).

## 원칙
- 화면 캡처는 **데모 데이터 폴더**(`guidebook/demo-home`, 예시·가짜 수치만)로 띄운 앱에서 찍는다. 사용자 실제 데이터 폴더·개인 이름·이메일·`C:\Users\…` 경로가 화면에 나오면 안 된다.
- 화면 캡처는 가로 1400 px 창에서 필요한 부분만 잘라 2배율(devicePixelRatio 2)로 저장, 폭 최대 2400 px.
- 인포그래픽은 HTML/SVG로 그려 headless Chrome으로 2배율 PNG를 만든다. 원본 HTML/SVG는 `assets/src/`에 함께 둔다. 색은 practical 팔레트(brand #2DA082, brand-deep #1F7A63, brand-pale #EAF4F0, ink #231F20, gray #6D6E71, warn 주황 #E07B39)와 Pretendard 계열 글꼴(없으면 맑은 고딕).
- 그림 안 글자는 한국어, 짧게. 숫자를 넣으면 실제 앱·문서에 있는 값만.

## 화면 캡처 (s = screen)
| 파일 | 내용 |
|---|---|
| s01-library.png | 자료함: 예시 자료 5개, 처리 단계 표시, AI 라벨 진행 카드 |
| s02-search.png | 검색: "사과 포마스 식이섬유" 결과 + 동의어 확장 칩 + 오른쪽 청크 원문 |
| s03-review.png | 라벨 검토: 대기 라벨 목록과 단축키 도움말 |
| s04-measurements.png | 측정값 표 |
| s05-concepts.png | 개념(부산물 분류 트리·동의어) |
| s06-ask.png | AI에 묻기 화면(질문 입력·역할 선택. 실제 AI 호출 없이 빈 화면 또는 예시 문구) |
| s07-settings.png | 설정: 엔진 상태·CoA 규칙·식품 DB 연결 카드 |
| s08-collect.png | 수집: 검색창·출처 그룹(해외 학술 체크, 국내는 키 필요 표시) |
| s09-collect-inbox.png | 수집함: 실제 검색 결과 카드(OA·PDF 배지) + 저장 검색 + 크롤러 사이트 |
| s10-exp-flow.png | 실험: 공정 흐름 편집기(단계 사슬과 질량·수분 막대) |
| s11-exp-data.png | 실험: 런 데이터 표(가져오기 후) |
| s12-exp-result.png | 실험: 예측 대 실측·패리티 그림·보정 |
| s13-stats-setup.png | 분석: 데이터 고르기·변수 역할 |
| s14-stats-result.png | 분석: 가정 점검 카드 + 표 1 미리보기 + 해석 세 문장 |
| s15-viz-flow.png | 시각화 흐름: 두 시스템을 묶은 구조 지도 |
| s16-viz-drying-3d.png | 건조 방식: 동결건조기 3D 모델(라벨 켬) |
| s17-viz-predict.png | 건조 결과 예측 패널(근거 요약·근거 보기 펼침) |
| s18-viz-molecule.png | 분자 구조: 클로로겐산 2D·3D |
| s19-wb-parse.png | 작업대 파싱: 도구 카드 + 나란히 비교 |
| s20-wb-chunks.png | 작업대 청크: 문제 표시와 고치기 버튼 |
| s21-wb-labels.png | 작업대 라벨: 수동 라벨 팝업 |
| s22-wb-learned.png | 작업대 배운 것 |
| s23-install.png | install.bat 실행 창 모양(실제 출력 텍스트를 터미널 모양으로 렌더) |
| s24-start.png | 첫 화면(앱을 막 연 모습) |
| s25-fig1.png | 통계 분석 결과 그림 1(예시 데이터, 2배율) |
| s26-table1.png | 통계 분석 결과 표 1(HTML 렌더) |

## 인포그래픽 (i = infographic)
| 파일 | 내용 |
|---|---|
| i01-why.png | 연구원의 하루 문제(자료가 흩어짐·수치 찾기·기밀 걱정·반복 정리) → 이 도구가 하는 일 |
| i02-overview.png | 한 장 지도: 자료 넣기 → 청크 → 라벨 → 측정값 → 검색·AI 답변·리포트, 옆으로 수집·실험·분석·시각화 |
| i03-architecture.png | 기술 층: 브라우저 화면 / FastAPI 서버 / SQLite·데이터 폴더 / MCP 서버 / Claude Code·Codex / 외부 API (각 층에 '무엇을·왜' 한 줄) |
| i04-security.png | PC 안·밖 경계: 밖으로 나가는 것(질문·가린 본문·검색어·API 키)과 안 나가는 것(원본 파일·DB·CoA 식별 정보) |
| i05-ai-team.png | AI로 만든 팀 구성: 사람(요청·결정) → 메인 AI(기획·계약·검증) → 구현 AI들(큰 일/단순한 일/정밀한 일) → 시험·화면 확인 → 커밋 |
| i06-build-loop.png | 한 기능을 만드는 순환: 요청 → 질문으로 결정 → 계약 문서 → 나눠 맡기기 → 검증(시험·화면·원문 대조) → 사용자 확인 → 커밋 |
| i07-pipeline.png | 자료 처리 파이프라인: 파싱(도구 선택) → 정규화 → 청킹 → 사전 라벨 → 적재 → (AI 라벨 → 사람 검토 → 측정값) |
| i08-learning.png | 고치면 배우는 구조: 청크 수정 → 규칙 / 라벨 수정 → 동의어·부정 사례·AI 예시 → 다음 문서에 자동 적용 |
| i09-collect.png | 수집 흐름: 공식 API(해외·국내)·크롤러(직접·브라우저·Apify) → 수집함(중복 합치기) → 검토 → 자료함 |
| i10-experiment.png | 실험 흐름: 공정 흐름 편집 → 내 데이터 → 모형 예측과 비교 → 보정 → 다음 실험 제안 |
| i11-stats.png | 분석 흐름: 데이터 → 회귀·t검정 → 가정 점검 → 표 1·그림 1·세 문장 → Python·R·Stata 재현 |
| i12-evidence.png | 근거 배지 4종 설명: 문헌(DOI 확인)·실측(n)·설비 사양·가정 — 언제 믿고 언제 의심하나 |
| i13-prompt.png | 좋은 AI 요청의 4요소: 목적 · 조건(지켜야 할 것) · 결과물(모양) · 확인 방법 — 예시 문장 포함 |
