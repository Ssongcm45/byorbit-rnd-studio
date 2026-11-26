# 자료 수집 출처 안내 (M3)

> 작성 2026-11-25. 수집 화면의 출처 목록과 같은 순서로 정리했다. 국내·키 필요 API와 크롤러는 묶음 B(`app/collect/sources/{kci,scienceon,ntis,kipris,datagokr_*}.py`, `app/collect/crawler.py`), 해외 학술 API는 묶음 A(`openalex`·`crossref`·`europepmc`·`semanticscholar`)가 맡는다.

## 0. 공통 원칙

- **PC 밖으로 나가는 것**: 검색어와 그 출처가 요구하는 API 키뿐이다. 자료함 문서·CoA·시료·실험 데이터는 어떤 출처에도 보내지 않는다. User-Agent는 `ByOrbit-RD-Studio/0.3 (local research tool)`이고 이메일·이름 같은 개인 정보는 넣지 않는다.
- **API 키는 환경 변수로만** 받는다. 설정 파일·DB·로그에 쓰지 않는다. 오류 메시지에 키가 섞일 수 있는 곳(요청 주소를 되돌려 주는 서버 등)은 `***`로 가린다. 원래 예외를 잇지 않으므로(`raise … from None`) 추적 정보에도 키가 붙은 주소가 남지 않는다.
- **키가 없으면** 출처 상태가 `ready: false`이고 빠진 환경 변수 이름과 발급 방법(아래 각 절)을 보여 준다. 그 상태에서 검색을 부르면 `MissingKey`가 난다.
- **원문 PDF는 오픈 액세스만** `pdf_url`로 넘긴다. 국내 API 대부분은 무료 원문 직접 주소를 주지 않으므로 서지·초록·랜딩 주소만 수집하고, 원문은 해당 사이트에서 직접 연다.
- 수집 결과는 수집함(검토 대기)으로 들어가며, 승인해야 자료함에 들어간다.

### 환경 변수 지정 방법(Windows)

```powershell
# 현재 사용자에 영구 지정 — 지정 후 start.bat으로 앱을 다시 켠다
[Environment]::SetEnvironmentVariable("BYORBIT_KCI_KEY", "발급받은키", "User")
```

키 값은 이 문서·설정 파일·메모에 적지 않는다(보안 원칙).

## 한눈에 보기

| 출처 key | 묶음 | 돌려주는 것 | 환경 변수 | 확인 상태 |
|---|---|---|---|---|
| `openalex`·`crossref`·`europepmc`·`semanticscholar` | 해외 학술 | 해외 논문 서지·초록·오픈 액세스 원문 위치 (묶음 A, 키 없이 사용) | (선택 키만) | A 문서 참고 |
| `kci` | 국내 학술 | KCI 등재 학술지 논문(article) | `BYORBIT_KCI_KEY` | 문서 + 키 없이 호출한 오류 응답 / **실제 키로 미검증** |
| `scienceon` | 국내 학술 | 국내외 논문(article·thesis) + 국가R&D 보고서(report) | `BYORBIT_SCIENCEON_CLIENT_ID`, `BYORBIT_SCIENCEON_KEY`, `BYORBIT_SCIENCEON_MAC` | 문서·공식 샘플 코드 + 오류 응답 / **실제 키로 미검증** |
| `ntis` | 국가 R&D·특허 | 국가R&D 과제(project) + 연구보고서(report) | `BYORBIT_NTIS_KEY` | 매뉴얼 + 오류 응답 / **실제 키로 미검증** |
| `kipris` | 국가 R&D·특허 | 특허·실용신안(patent) — 출원번호·출원인·IPC | `BYORBIT_KIPRIS_KEY` | 문서 예시 + 오류 응답 / **실제 키로 미검증** |
| `datagokr_foodnutri` | 공공데이터 | 식약처 식품영양성분DB(dataset) — 원물 영양성분 | `BYORBIT_DATAGOKR_KEY` | 명세(swagger) + 오류 응답 / **실제 키로 미검증** |
| `datagokr_hffunc` | 공공데이터 | 식약처 건강기능식품 기능성 원료 인정현황 I-0040(dataset) | `BYORBIT_FOODSAFETY_KEY` | **공개 sample 키로 실제 호출해 해석 확인**(2026-11-25) |
| `datagokr_byprod` | 공공데이터 | 농사로 농식품부산물 영양정보(dataset) — 사료용 부산물 성분 | `BYORBIT_NONGSARO_KEY` | 매뉴얼(HWP) + 오류 응답 / **실제 키로 미검증** |
| `crawler` | 크롤러 | 공개 자료 목록 페이지(report·web) — 가져오기 방식 direct·browser·apify | 없음(Apify 방식만 `BYORBIT_APIFY_TOKEN`) | 기본 사이트 실제 크롤링 확인(direct·browser) / Apify는 **실제 토큰으로 미검증** |

"실제 키로 미검증"인 출처는 공식 문서의 필드 이름(또는 문서 예시를 충실히 재구성한 응답)으로 시험했다. 키를 받으면 첫 검색 결과를 꼭 눈으로 확인하고, 이상하면 해당 모듈 머리 주석의 "확인 필요" 항목부터 본다.

## KCI 한국학술지인용색인 (`kci`)

- **돌려주는 것**: 논문명(원어·영문), 저자(소속 괄호 제거), 학술지·발행기관, 연도, 권·호·쪽, 초록, DOI, KCI 랜딩 주소, 피인용 수. 원문 PDF 주소는 API에 없으므로 `pdf_url`은 비운다.
- **요청**: `GET https://open.kci.go.kr/po/openapi/openApiSearch.kci?apiCode=articleSearch&key=…&title=검색어&displayCount=…&page=1[&dateFrom=YYYYMM]` (예전 안내의 `open-api.kci.go.kr`는 DNS에 없음)
- **문서**: https://www.kci.go.kr/kciportal/po/openapi/openDataView.kci?datasetBean.dtstSeqNo=1 (2026-11-25 확인)
- **키 발급**: KCI 포털 로그인 → OPEN API → 키신청 https://www.kci.go.kr/kciportal/po/openapi/openApiKeyRequest.kci?datasetBean.dtstTyCd=02 → 발급 키를 `BYORBIT_KCI_KEY`에. 키에는 사용 기간이 있다("사용기간이 종료되었습니다" 오류).
- **이용 조건**: 저작자·출처 표시, 영리 목적 사용 불가. 호출 한도 명시 없음 → 앱은 1초 간격.
- **주의**: 응답의 `inputData`에 보낸 키가 그대로 되돌아온다. 앱은 이 부분을 메시지로 쓰지 않고, 오류 문구는 가려서 보여 준다.

## KISTI ScienceON (`scienceon`)

- **돌려주는 것**: 논문(ARTI: 국내외 학술지·학위논문·학술대회) + 보고서(REPORT: 국가R&D 최종보고서 TRKO… 등)를 번갈아 섞어서. 제목·저자·연도·학술지/발행기관·초록·DOI·랜딩 주소, 보고서의 과제번호(Pjn). 원문 주소(FulltextURL)가 `.pdf`로 끝날 때만 `pdf_url`.
- **토큰 흐름**(공식 샘플 그대로): `{"datetime":"YYYYMMDDHHMMSS","mac_address":"AA-BB-…"}` → AES-256-CBC(PKCS7, 키 = 32자 인증키, IV = 고정 `jvHJ1EFA0IXBrxxz`) → URL-safe Base64 → `GET https://apigateway.kisti.re.kr/tokenrequest.do?client_id=…&accounts=…` → access_token(2시간). 토큰은 **메모리에만** 두고 만료·E4103이면 다시 발급한다. 문서 예시가 표준 Base64를 보이므로 E4006이면 표준 Base64로 한 번 더 시도한다. AES는 표준 라이브러리만으로 구현했고 FIPS-197 시험 벡터와 `cryptography` 결과로 검사한다(새 패키지 불필요).
- **검색**: `GET https://apigateway.kisti.re.kr/openapicall.do?client_id&token&version=1.0&action=search&target=ARTI|REPORT&searchQuery={"BI":"검색어"}&curPage=1&rowCount≤100`
- **문서**: https://scienceon.kisti.re.kr/por/api/way/guide/tokenGuide.do, …/arti/serviceArtiSearchApi.do, …/report/serviceReportSearchApi.do, …/guide/errorCodeGuide.do, 자료실 공식 샘플 https://scienceon.kisti.re.kr/por/api/material/pdsList.do (2026-11-25 확인)
- **키 발급**: ScienceON 가입·로그인 → API Gateway "API 활용신청" https://scienceon.kisti.re.kr/por/api/useRequest/useRequestList.do 에서 **이 PC의 MAC 주소**를 적어 신청 → 승인 후 client_id(64자)·인증키(32자). 환경 변수 `BYORBIT_SCIENCEON_CLIENT_ID`, `BYORBIT_SCIENCEON_KEY`, `BYORBIT_SCIENCEON_MAC`(신청 때 적은 MAC, 예 `B4-2E-99-AD-48-7D`).
- **한도**: 초당 2회(E4901) → 앱은 0.6초 간격.
- **밖으로 나가는 것**: 검색어, client_id, 암호화된 (시각·MAC), 토큰.
- 참고: ScienceON 웹사이트는 robots.txt가 검색엔진 외 봇을 막으므로 크롤링하지 않는다(API만).

## NTIS 국가R&D (`ntis`)

- **돌려주는 것**: (1) 과제 — 과제명·과제번호·연구책임자·참여연구원·주관연구기관·전문기관·부처·사업명·기준연도·연구기간·정부연구비, 연구목표/내용/기대효과(요약 칸), 상세 주소 `https://www.ntis.go.kr/project/pjtInfo.do?pjtId=…`(로그인 필요). (2) 연구보고서 — 제목·보고서번호(TRKO… = ScienceON 보고서 번호)·발행기관·발행연월·초록·과제번호, 원문 보기 주소(DocUrl, PDF 직접 주소가 아니라 `pdf_url`은 비움). 검색어 강조 태그는 지운다.
- **요청**: `https://www.ntis.go.kr/rndopen/openApi/public_project?apprvKey&collection=project&query&searchField=BI&sortby=RANK/DESC&startPosition=1&displayCount[&addQuery=PY=YYYY/MORE]`, 보고서는 `…/openApi/rresearchpdf?…&collection=rresearchpdf`(r 두 개).
- **문서**: https://www.ntis.go.kr/rndopen/api/mng/apiMain.do, 일반 매뉴얼 https://www.ntis.go.kr/rndopen/menual/openapi_menual.pdf, API별 매뉴얼(과제검색 2025-12-16, 연구보고서 2024-01-03 — 로그인 필요라 공개 사본으로 확인). 매뉴얼의 매개변수 표와 예제 호출이 서로 달라 **예제 호출 이름**을 썼다 — 첫 실사용 때 확인 필요.
- **키 발급**: NTIS 가입 → 내정보에 소속기관 등록(없으면 신청 불가) → 데이터활용 > OpenAPI에서 "국가R&D 과제검색"과 "연구보고서 검색"을 각각 활용신청 → 승인키(apprvKey)를 `BYORBIT_NTIS_KEY`에. 신청에 IP 제한이 붙을 수 있다. 보고서 API가 승인 전이면 과제 결과만 돌려주고 경고를 남긴다.
- **이용 조건**: 연구개발 활동 목적·신청기관 내부 활용, 공공누리 제1유형. 외부 공개 화면에는 정해진 항목만 보일 수 있다(이 앱은 개인 PC 안에서만 사용). 한도 30 tps → 앱은 1초 간격.
- **주의**: 잘못된 키 오류가 **보낸 키를 그대로 되돌려 준다**("유효한 인증키가 아닙니다. 인증키 : …", 2026-11-25 확인) → 앱은 가려서 보여 준다.

## KIPRIS Plus 특허 (`kipris`)

- **돌려주는 것**: 발명의 명칭, 출원인(authors와 extra.출원인), 출원번호·출원일, 공개·공고·등록 번호와 날짜, 등록상태, IPC 목록, 요약, 대표도면 주소. 원문 PDF는 없음. 랜딩 주소는 출원번호로 만든 특허 DOI(`https://doi.org/10.8080/출원번호`, 추정 — 미검증).
- **요청**: `GET https://plus.kipris.or.kr/kipo-api/kipi/patUtiModInfoSearchSevice/getAdvancedSearch?word=…&patent=true&utility=true&numOfRows&pageNo=1&ServiceKey=…[&applicationDate=YYYY0101~…]` ("Sevice"는 공식 철자). getWordSearch는 폐기 예정이라 쓰지 않는다.
- **문서**: https://plus.kipris.or.kr/portal/data/service/DBII_000000000000001/view.do?menuNo=200100 (2026-11-25 확인)
- **키 발급**: KIPRIS Plus 가입 → 데이터 신청 > Open API https://plus.kipris.or.kr/portal/data/request/apiFsmtmList.do?menuNo=290005 → 승인 후 마이페이지에서 키 → `BYORBIT_KIPRIS_KEY`.
- **요금·한도**: 월 1,000건 무료(매월 1일 초기화), 초과 유료 — https://plus.kipris.or.kr/portal/use/paymentMmg.do?menuNo=210112. 앱은 1초 간격, 한 번에 최대 100건.

## 공공데이터 (농식품)

부산물 R&D에 직접 쓰이는 세 가지를 골랐다. 농사로에는 일반 "연구보고서 검색" API가 없다(136종 목록 확인) — 농촌진흥청 보고서는 NTIS 연구보고서·ScienceON 보고서 또는 크롤러(농과원·원예원 시험연구보고서)로 찾는다.

### 식약처 식품영양성분DB (`datagokr_foodnutri`)
- **돌려주는 것**: 식품명별 영양성분(100g 등 기준량) — 에너지·수분·단백질·지방·탄수화물·당류·식이섬유(수용성·불용성)·무기질·비타민 C·폐기율 등(`extra.영양성분`), 요약 문장. 부산물 원물(사과·감귤·커피 등)의 비교 근거로 쓴다.
- **요청**: `GET https://apis.data.go.kr/1471000/FoodNtrCpntDbInfo03/getFoodNtrCpntDbInq03?serviceKey&type=json&FOOD_NM_KR=검색어&pageNo=1&numOfRows`
- **문서**: https://www.data.go.kr/data/15127578/openapi.do (명세 기준, 2026-11-25)
- **키 발급**: 공공데이터포털 로그인 → 위 페이지 "활용신청"(개발계정 대개 자동 승인) → 마이페이지 개발계정의 일반 인증키(Decoding 권장, Encoding 키도 자동으로 풀어 씀) → `BYORBIT_DATAGOKR_KEY`.
- **한도·약관**: 개발계정 하루 10,000건, 공공데이터포털 이용약관 https://www.data.go.kr/ugs/selectPortalPolicyView.do. 미등록 키는 HTTP 403(활용신청 승인 확인 안내).

### 식약처 건강기능식품 기능성 원료 인정현황 I-0040 (`datagokr_hffunc`)
- **돌려주는 것**: 인정번호·인정일자·업체·신청 원료명·기능성 내용·일일 섭취량·섭취 주의. 부산물 유래 원료(예: 풋사과추출물 애플페논)가 이미 개별인정형으로 인정됐는지 확인할 때.
- **요청**: `GET http://openapi.foodsafetykorea.go.kr/api/{인증키}/I-0040/json/1/{n}/APLC_RAWMTRL_NM=검색어` — **키가 주소 경로에 들어간다**(오류 메시지의 주소는 가림).
- **문서**: https://www.foodsafetykorea.go.kr/api/openApiInfo.do?menu_grp=MENU_GRP31&menu_no=661&svc_no=I-0040&svc_type_cd=API_TYPE06
- **키 발급**: 식품안전나라 가입 → 데이터활용서비스 > OpenAPI > 이용신청 → 인증키 관리에서 키 → I-0040 이용 신청 → `BYORBIT_FOODSAFETY_KEY`(공공데이터포털 키와 다름).
- **한도**: 증분 조건 없이 시간당 100회(INFO-320) → 앱은 3초 간격. 2026-11-25 공개 `sample` 키로 "사과"를 실제 조회해 해석을 확인했다(3건: 풋사과추출물 애플페논, 2015·2019·2020 인정).

### 농사로 농식품부산물 영양정보 (`datagokr_byprod`)
- **돌려주는 것**: 부산물명(예: 사과박), 가축 구분, 특성·이용 수준/주의, 성분(수분·조단백·조지방·가용무질소물·조섬유·조회분·칼슘·인·TDN·DE). 앞쪽 5건만 상세(성분)를 추가로 부른다.
- **요청**: `http://api.nongsaro.go.kr/service/foodbyprdNtrinfo/foodbyprdNtrinfoLst?apiKey&sText=검색어&pageNo&numOfRows`, 상세 `…/foodbyprdNtrinfoDtl?apiKey&cntntsNo`
- **문서**: 목록 https://www.nongsaro.go.kr/portal/ps/psn/psnj/openApiLst.ps?menuId=PS65428, 매뉴얼 https://www.nongsaro.go.kr/portal/apiManual/foodbyprdNtrinfo.zip
- **키 발급**: 농사로 가입·본인 확인 → Open API 신청 https://www.nongsaro.go.kr/portal/ps/psz/psza/contentMain.ps?menuId=PS00191 (서비스 도메인 입력) → 신청 내역의 키 → `BYORBIT_NONGSARO_KEY`.
- **주의**: 농사로 키는 신청한 도메인에 묶이고 매뉴얼은 브라우저(AJAX) 호출만 설명한다. 서버(이 앱) 호출은 문서에 없어 오류 15(도메인 불일치)가 날 수 있다 — 그때는 도메인을 다시 신청. 정상 응답 틀은 매뉴얼에 없어 공공 API 관례(response/header + body/items/item)로 재구성했다.


## 크롤러 (`crawler`, 묶음 "크롤러")

공식 API가 없는 **공개 자료 목록 페이지**에서 제목·날짜·요약·상세 주소·공개 첨부 링크를 모은다. 키가 필요 없다.

### 지키는 규칙

| 규칙 | 내용 |
|---|---|
| robots.txt | 호스트마다 `robots.txt`를 받아(하루 캐시) `urllib.robotparser`로 읽고, RFC 9309의 **가장 긴 규칙 우선**(`*`, `$` 지원)으로 판정한다. 우리 이름은 `ByOrbit-RD-Studio`. 막힌 주소는 건너뛰고 이유를 결과에 남긴다. |
| robots.txt를 못 받을 때 | 404/410 → 없음으로 보고 일반 규칙만 적용. 401·403·5xx·연결 실패 → 그 호스트 전체를 건너뜀(보수적). |
| 간격 | 호스트당 **최소 3초**. 사이트 `interval_s`나 robots `Crawl-delay`가 더 길면 그것을 따른다. 기본 사이트는 5초. |
| 양 | 사이트 한 번 훑을 때 기본 10쪽(최대 30쪽), 깊이 1(최대 2). 사이트 검색 주소(`search_urls`)가 있으면 그 결과 목록만 보고, 검색어가 맞는 항목의 상세 페이지만 연다. |
| 따라갈 링크 | 시작 주소와 **같은 호스트**(또는 `allow_prefixes`에 전체 주소로 적은 호스트) + `allow_prefixes` 안 + `link_pattern`(정규식)에 맞는 링크만. |
| 첨부 | `pdf_pattern`(기본: .pdf/.hwp/.hwpx)에 맞는 **href로 공개된 링크**만 기록한다. robots가 막은 다운로드 주소(예: 농진청 `/fileDownLoad.do`)는 기록하지 않는다. `pdf_url`은 `.pdf`일 때만. 실제로 받는 일은 수집함에서 승인할 때 `http.download`가 하며 `%PDF`인지 확인한다. |
| 검색어 | 모든 검색어가 제목·요약·목록 줄에 들어 있어야 한다. 대소문자·띄어쓰기는 무시한다('사과 박' = '사과박'). |
| 로그인·유료 | 기본 목록에 넣지 않는다. 로그인 화면이 오는 사이트는 항목이 나오지 않는다. |
| 나가는 것 | 목록·상세 페이지 주소와 검색어(사이트 검색 주소에 넣을 때)뿐. |

### 사이트 설정 필드

계약 필드: `id, name, group, start_urls[], allow_prefixes[], link_pattern, title_hint?, date_pattern?, pdf_pattern?, interval_s, enabled, default`

선택 필드(있으면 쓴다):

| 필드 | 뜻 |
|---|---|
| `search_urls[]` | 사이트 자체 검색 주소. `{q}` 자리에 검색어(URL 인코딩)가 들어간다. |
| `link_template` | `javascript:goView('PJ016988')`처럼 자바스크립트로 여는 링크를 주소로 바꾸는 틀. `{1}`, `{2}` = 호출 인자. |
| `link_rewrite` | `[정규식, 바꿀 말]` — 상세 주소 정리(예: 조회수 올리는 `mode=updateCnt`를 `mode=view`로). |
| `title_hint`, `summary_hint` | 줄(tr·li) 안에서 제목·요약을 담은 요소 선택자(`.c-tit`, `td.title`, `#id`). |
| `date_pattern` | 날짜 정규식. 그룹 3개 = 연·월·일, 1개 = 연도만. 기본은 `2025.03.04`·`2025-03-04`·`2025년 3월 4일`. |
| `doc_type` | `report` 또는 `web`. 없으면 첨부가 있으면 report. |
| `max_pages`, `max_depth` | 쪽수·깊이 제한(최대 30·2). |
| `terms_url`, `terms_checked`, `robots_checked`, `note`, `venue` | 이용 조건 기록과 표시용. |

사용자 사이트와 기본 사이트 변경(켜기/끄기 등)은 데이터 폴더 `config/crawl_sites.json`에 저장된다(`sites` = 사용자 사이트, `overrides` = 기본 사이트 덮어쓰기). 기본 사이트는 지우면 꺼질 뿐이며, 기본 간격보다 짧게 줄일 수 없다.

### 가져오기 방식 (backend, 2026-11-25 추가)

사이트마다 페이지를 **어떻게 받아 올지**를 고른다. 위 규칙(robots.txt·간격·허용 경로·같은 호스트·쪽수·깊이·검색어)은 방식과 상관없이 `app/collect/crawler.py`의 한 크롤 루프가 지킨다. 방식 코드는 `app/collect/backends/`.

| 방식 (`backend`) | 어디서 | 준비 | PC 밖으로 나가는 것 | 쓰는 때 |
|---|---|---|---|---|
| `direct` (기본) | 이 PC — 표준 라이브러리 HTTP | 없음 | 목록·상세 주소, 검색어(사이트 검색 주소에 넣을 때) → **그 사이트로만** | 서버가 HTML로 목록을 그리는 사이트(기본 5곳 모두) |
| `browser` | 이 PC — Playwright 파이썬 라이브러리 + 헤드리스 Chrome | `install-browser.bat` | direct와 같음 + 그 페이지가 화면을 그리려고 부르는 스크립트·데이터 요청(그 사이트·CDN) | 자바스크립트로 목록을 그리는 사이트 |
| `apify` (선택·유료) | **Apify 클라우드**(Website Content Crawler) | 환경 변수 `BYORBIT_APIFY_TOKEN` | **사이트 시작 주소와 크롤 설정(허용 경로·쪽수·깊이·기다릴 요소)이 Apify로**. 검색어는 보내지 않는다(받은 페이지에서 이 PC가 거름). Apify 크레딧이 든다 | 이 PC에서 막히거나 브라우저를 깔 수 없을 때 |

어떤 방식이든 자료함·CoA·시료·실험 데이터는 보내지 않는다. 화면(수집 → 크롤러 사이트)의 사이트 카드에서 '가져오기 방식'을 고르고, **시험 수집**(최대 3쪽, 수집함에 넣지 않음)으로 찾은 제목을 바로 확인한다. 준비되지 않은 방식은 '미설치'·'키 없음'으로 흐리게 보이고 할 일을 알려 준다. 상태는 `GET /api/collect/sites/backends`, 시험 수집은 `POST /api/collect/sites/{id}/test`.

사이트 필드(모두 선택): `backend`(없으면 `direct` — 예전 `crawl_sites.json`은 그대로 동작), `wait_for`(CSS 선택자 — 이 요소가 나타날 때까지 기다림), `wait_ms`(대기 상한, 최대 15000ms), `actor`(Apify 액터 바꾸기, 기본 `apify~website-content-crawler`), `max_charge_usd`(Apify 실행 1회 비용 상한, 기본 0.5, 0.05–5).

#### 브라우저 방식 (`browser`)

- **설치**: `install-browser.bat` → `requirements-browser.txt`(playwright 1.65.2 고정)를 `.venv`에 설치 → 설치된 Chrome을 찾으면 그것을 쓴다(브라우저 추가 다운로드 없음). Chrome이 없을 때만 `python -m playwright install chromium`(약 150MB)을 물어본 뒤 받는다 → 자가 점검으로 `https://example.com`을 헤드리스 Chrome으로 열어 제목("Example Domain")을 출력한다.
- **안전장치**
  - http/https가 아닌 주소(`file:///C:/…`, `data:`, `javascript:`, `chrome:`, `about:` 등)로는 **이동하지 않는다**. 페이지 안의 모든 요청을 가로채(route) http/https가 아니면 끊는다 — 웹 페이지가 이 PC의 파일을 읽게 하지 못한다(로컬 서버로 실제 확인: `file://` fetch·이동 모두 막힘).
  - 이미지·글꼴·영상은 받지 않는다. 다운로드·서비스 워커는 끈다. 크롤 한 번마다 새 컨텍스트(쿠키·저장소 없음)를 열고 끝나면 닫는다. 동시에 띄우는 브라우저는 2개까지.
  - 리디렉션 뒤 주소가 다른 사이트이거나 robots.txt가 막은 곳이면 버린다. 이동마다 direct와 같은 호스트별 간격(≥3초·Crawl-delay)을 둔다.
  - User-Agent는 일반 Chrome 문자열 + `ByOrbit-RD-Studio/0.3 (local research tool)`(개인 정보 없음).
- 크롤러 백그라운드 스레드에서 sync API를 그대로 쓴다(Windows에서 주 스레드가 아닌 스레드에서도 동작 확인).

#### 왜 Playwright MCP가 아닌가

Playwright MCP는 **AI가 브라우저를 직접 조종**하는 통로다. 앱 안의 Claude에 브라우저 MCP를 붙이면 AI가 `file://` 주소로 이 PC의 파일(기밀 자료 포함)을 열어 읽을 수 있어, 앱이 AI에 보내기 전에 하는 기밀 가림(masking)을 우회하게 된다. 그래서 브라우저는 **크롤러 코드만** 정해진 규칙(http/https만, 사이트 허용 경로만, robots·간격 준수)으로 쓰고, AI에게는 도구로 주지 않는다.

#### Apify 방식 (`apify`) — 유료, 선택

- **토큰**: Apify 가입 → Console → Settings → API & Integrations(https://console.apify.com/settings/integrations)에서 API 토큰을 복사 → 환경 변수 `BYORBIT_APIFY_TOKEN`에 넣고 앱을 다시 켠다. 토큰은 설정 파일·DB·로그에 쓰지 않고 `Authorization: Bearer` 헤더로만 보낸다(주소에 넣지 않음). 오류 문구에서는 가린다(`***`).
  ```powershell
  [Environment]::SetEnvironmentVariable("BYORBIT_APIFY_TOKEN", "발급받은토큰", "User")
  ```
- **비용**: Apify 크레딧이 든다. 실행마다 `maxTotalChargeUsd`(사이트의 `max_charge_usd`, 기본 0.5 USD, 최대 5)로 상한을 걸고, 실행 시간 300초·메모리 4096MB로 묶는다. 이 PC는 최대 360초 기다리고, 넘으면 실행을 **중단(abort)** 한다. 끝나면 결과 메시지에 실제 비용(`usageTotalUsd`)을 적는다. 시험 수집도 크레딧이 든다(화면에서 한 번 더 묻는다).
- **호출 흐름**(공식 문서 https://docs.apify.com/api/v2, 2026-11-25 확인): `POST /v2/actors/apify~website-content-crawler/runs?timeout=300&memory=4096&maxTotalChargeUsd=…` → `GET /v2/actor-runs/{id}?waitForFinish=60`(끝날 때까지 반복) → `GET /v2/datasets/{datasetId}/items?format=json&clean=true`. 동기 호출(run-sync-get-dataset-items)은 300초를 넘으면 408이고 연결이 끊기면 상태를 모른다고 문서가 경고해 쓰지 않았다.
- **보내는 입력**(액터 입력 스키마 version-0 0.3.108 기준): `startUrls`(사이트 시작 주소만), `crawlerType: playwright:adaptive`(자바스크립트 있으면 브라우저), `includeUrlGlobs`(허용 경로 → `https://호스트/경로**`), `excludeUrlGlobs`(첨부 파일 확장자), `maxCrawlPages`·`maxResults`(쪽수 제한), `maxCrawlDepth`(깊이), **`respectRobotsTxtFile: true`**(액터 기본값은 false라 반드시 켬), `maxConcurrency: 1`, `saveHtml: true` + `htmlTransformer: none`(링크·표를 이 PC에서 다시 읽기 위해), `blockMedia: true`, `wait_for`가 있으면 `softWaitForSelector`.
- **받은 뒤**: Apify가 더 많이·다른 곳을 가져와도 이 PC가 다시 거른다 — 같은 호스트·허용 경로·깊이·robots.txt(이 PC가 직접 받아 판정)·쪽수 제한에 맞는 페이지만 쓰고 나머지는 버린 수를 메시지로 남긴다. `file:` 같은 주소는 버린다.
- **한계**: Apify는 robots `Crawl-delay`를 지원하지 않는다(한 번에 한 쪽씩만 요청하도록 설정, `robots 확인`에서 경고). `link_pattern` 정규식은 glob으로 옮길 수 없어 Apify가 목록의 다른 링크에 쪽수를 쓸 수 있다. **실제 토큰으로는 아직 확인하지 못했다(가짜 응답으로만 시험)** — 처음 쓸 때 `max_charge_usd`를 작게 두고 시험 수집 결과·비용 메시지를 확인한다.

#### 기본 사이트와 방식 (2026-11-25 확인)

기본 사이트 5곳은 모두 서버가 HTML로 목록을 그리므로 `backend: "direct"`로 둔다. 브라우저 방식으로 농촌진흥청 보도자료를 '부산물'로 5쪽 훑은 결과가 direct와 같았다(아래). 자바스크립트로만 그리는 공개 목록을 찾으려고 국립축산과학원 보도자료, 농림축산식품부, 농업기술실용화재단(그린바이오 소재 원료 정보), KATI 농식품수출정보 보고서, 한국농촌경제연구원 보고서 목록을 direct·브라우저로 비교했지만 모두 direct로 같은 내용이 나와 **브라우저 전용 기본 사이트는 추가하지 않았다**(이용약관 검토는 하지 않음 — 넣고 싶으면 사이트 추가로). 한국식품연구원 두 곳은 같은 날 다시 확인해도 저작권 정책·이용약관 페이지가 없어(`/web/policy/00001`~`00005` 중 개인정보·영상정보 방침만) 계속 꺼 둔다.

브라우저 방식 실제 크롤링(2026-11-25, 설치된 Chrome 헤드리스, 크롤러 백그라운드 스레드, 사이트당 5쪽 이하, 검색어 "부산물"): 농촌진흥청 보도자료 5쪽·10건·26.9초, 국립농업과학원 시험연구보고서 5쪽·10건·48.8초 — 제목·날짜·상세 주소가 direct 결과와 같았다(예: "농촌진흥청, 농식품부산물로 사료비 줄인 한우농가 방문", "발효기술을 통한 약선 소재 발굴 및 배 가공부산물 이용기술 개발"). 간격 5초를 이동마다 지켰다.

### 기본 사이트 (2026-11-25 확인)

| id | 사이트 | 켜짐 | robots.txt (2026-11-25) | 이용 조건 (2026-11-25) | 비고 |
|---|---|---|---|---|---|
| `rda-press` | 농촌진흥청 보도자료 (`www.rda.go.kr/board/board.do?mode=list&prgId=day_farmprmninfoEntry`) | 켜짐 | `User-agent : *` — Disallow `/search`, `/fileDownLoadDw.do`, `/fileDownLoad.do`, Allow `/` → 목록·상세 허용, 첨부 다운로드는 막힘 | [저작권정책](https://www.rda.go.kr/datacprprot.do): 공공누리 1~4유형 표시 저작물 자유 이용 | 제목 검색(`searchKey=subject`) 사용. 상세의 공공누리 유형을 license로 기록. 첨부(hwpx·pdf)는 robots가 막은 `/fileDownLoad.do`라 기록하지 않음 |
| `naas-reports` | 국립농업과학원 시험연구보고서 (`www.naas.go.kr/02_research/Research_List3.do`) | 켜짐 | `User-agent: *` — Allow `/`, Disallow `/search/`, `/mem/`, `/dis/`, `/evl/`, `/bips/` 등 → `/02_research/` 허용 | [저작권정책](https://www.naas.go.kr/05_etc/Etc_List.do?menu_code=6&tg=1&mmode=3): 공공누리 부착물 유형별 자유 이용, 미부착은 담당자 협의 → 제목·요약·주소만 기록 | `keyword` 검색. 상세는 `javascript:goView('PJ…')` → `link_template`로 GET 주소. 원문 파일 없음(사이트 안내: ScienceON에서 검색) |
| `nihhs-reports` | 국립원예특작과학원 시험연구보고서 (`www.nihhs.go.kr/usr/farmer/examResearchReportList.do`) | 켜짐 | `User-agent: *` — Allow `/`, Disallow는 `/common/`, `/css/`, `/js/`, `/images/` 등 자원 폴더뿐 | [저작권 정책](https://www.nihhs.go.kr/usr/extras/datacprprot.do?mc=MN0000000194): 공공누리 제1유형 | `searchWord` 검색. 보고서 ID(TRKO…)는 ScienceON 보고서 ID와 같음 |
| `kfri-press` | 한국식품연구원 보도자료 (`www.kfri.re.kr/web/board/9/postList`) | **꺼짐** | `User-agent: *` / `Allow: /` (전체 허용) | 저작권 정책·이용약관 페이지를 찾지 못함(하단에 개인정보처리방침·영상정보처리기기 방침과 "All Rights Reserved"만 있음) | 이용 조건 미확인이라 꺼 둠. 직접 확인 후 켜기. 제목 검색(`searchOption=title`) |
| `kfri-pubs` | 한국식품연구원 발간자료(PDF) (`www.kfri.re.kr/web/board/52/postList`) | **꺼짐** | 위와 같음(전체 허용) | 위와 같음 | 목록의 공개 PDF 링크(`/upload/attach/…pdf`)를 항목으로 기록 |

검토했지만 넣지 않은 곳(2026-11-25)

| 사이트 | 이유 |
|---|---|
| 농림식품기술기획평가원(`www.ipet.re.kr`) | robots.txt가 `User-agent: *` 전체 `Disallow: /`(Googlebot·Yeti만 허용) |
| ScienceON 웹(`scienceon.kisti.re.kr`) | robots.txt가 구글·네이버 검색 봇 외 전부 차단 → 공식 API(`scienceon`)만 사용 |
| 농촌진흥청 농업과학도서관(`lib.rda.go.kr`) | robots.txt가 `/search/`, `/research/` 등 자료 목록 경로를 막음 |
| 농사로(`www.nongsaro.go.kr`) | robots는 대부분 허용하나 자체 Open API(농사로 인증키)가 있어 API 쪽이 맞음. `/portal/search`·파일 다운로드는 막힘 |
| 국립수산과학원(`www.nifs.go.kr`) | 농식품 부산물과 거리가 있고 AI 봇 차단 규칙을 명시 |

### 실제 크롤링 결과 (2026-11-25, 사이트당 5쪽 이하)

검색어 "사과박"은 다섯 곳 모두 0건이었다(제목에 '사과박'이 들어간 자료가 이 목록들에는 없음 — 검색어 판정이 정상 동작). 같은 실행에서:

| 사이트 | "부산물" (≤6쪽) | "감귤" (≤4쪽) | robots | 비고 |
|---|---|---|---|---|
| 농촌진흥청 보도자료 | 6쪽, 10건 (예: "농촌진흥청, 농식품부산물로 사료비 줄인 한우농가 방문", "'도토리 가공부산물' 기능성 소재로 탈바꿈…") | 4쪽, 10건 | 허용 | 상세 본 항목은 공공누리 제1유형 기록. 첨부는 robots가 막은 다운로드라 0건(의도대로) |
| 국립농업과학원 시험연구보고서 | 6쪽, 10건 (예: "배 가공부산물 이용기술 개발", "미생물 활용 농업부산물 처리 기술 개발") | 4쪽, 5건 | 허용 | 상세의 '주요결과요약'을 요약으로 기록 |
| 국립원예특작과학원 시험연구보고서 | 5쪽, 4건 (예: "감귤부산물을 활용한 고기능성 소재 개발"(2017), "원예특용작물 부산물의 버섯 배지 자원화…") | 4쪽, 5건 | 허용 | 초록은 선택자로 집기 어려워 비어 있음 |
| 한국식품연구원 보도자료(꺼짐) | 3쪽, 2건 — 둘 다 공개 PDF 첨부 | 3쪽, 2건 (예: "알코올성 간손상 감귤과피 추출물로 예방한다", PDF) | 허용 | 이용 조건 미확인으로 기본 꺼짐(점검용으로만 실행) |
| 한국식품연구원 발간자료(꺼짐) | 1쪽, 0건 | 1쪽, 0건 | 허용 | 목록 18건(식초 가이드라인 등)에 해당 검색어 없음 |

사이트별 결과(쪽수·건너뛴 주소·메시지)는 `SOURCE.last_reports()` / `crawler.last_reports()`로 볼 수 있다.

## 알려진 한계

- 키 필요 API 7종은 키가 없어 **실제 성공 응답으로 검증하지 못했다**(I-0040만 공개 sample 키로 확인). 오류 형식은 키 없이 실제 호출해 맞췄다.
- NTIS 매뉴얼의 매개변수 이름이 표와 예제에서 달라 예제 이름을 썼다. ScienceON의 Base64 종류(URL-safe/표준)는 문서와 샘플이 달라 둘 다 시도한다. KIPRIS 랜딩 주소(DOI 10.8080)는 추정이다.
- 기본(direct) 방식은 자바스크립트로 그리는 목록을 읽지 못한다 → 사이트의 가져오기 방식을 `browser`로(`install-browser.bat`). 어떤 방식이든 POST로만 열리는 상세와 로그인 페이지는 읽지 않는다(GET으로 열리는 상세는 `link_template`로 처리).
- Apify 방식은 실제 토큰으로 확인하지 못했다(공식 문서·액터 입력 스키마와 가짜 응답으로만 시험). Crawl-delay를 지원하지 않는다.
- 문자 인코딩은 응답 헤더(charset)를 따른다. 헤더 없이 EUC-KR로 주는 사이트는 글자가 깨질 수 있다(기본 사이트는 모두 UTF-8).
