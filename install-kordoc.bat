@echo off
chcp 65001 >nul
cd /d "%~dp0"

where node >nul 2>nul
if not errorlevel 1 goto node_ok
echo [!] Node.js가 없습니다. https://nodejs.org 에서 LTS를 설치하거나
echo     PowerShell에서 winget install OpenJS.NodeJS.LTS 를 실행한 뒤 이 파일을 다시 실행하세요.
pause
exit /b 1

:node_ok
echo.
echo === ByOrbit R^&D Studio - kordoc(한글 문서 파서) 설치 ===
echo 구 형식 HWP(5.x), HWPX, PDF를 이 PC에서 읽는 Node 패키지 kordoc(MIT)을 설치합니다.
echo 문서 파일은 PC 밖으로 나가지 않습니다. 설치 위치: tools\node  (약 100MB, 인터넷으로 npm 패키지를 받습니다)
echo.
if not exist "tools\node" mkdir "tools\node"
rem 설치 폴더는 저장소에 올리지 않는다
echo *> "tools\node\.gitignore"

echo [1/2] npm 패키지 설치 (kordoc 2.5.2 + PDF용 pdfjs-dist 4.10.38)...
call npm install --prefix "tools\node" --no-audit --no-fund kordoc@2.5.2 pdfjs-dist@4.10.38
if errorlevel 1 goto npm_fail

echo.
echo [2/2] 자가 점검(예시 HWPX 만들기 -^> kordoc 변환)...
set PYTHONUTF8=1
set BYORBIT_KORDOC_DIR=%~dp0tools\node
if not exist ".venv\Scripts\python.exe" goto no_venv
".venv\Scripts\python.exe" -c "import tempfile, pathlib; from app import sample_files as s; from app.ingest import parser_tools as PT; d=pathlib.Path(tempfile.mkdtemp()); f=s.make_hwpx(d/'check.hwpx'); o=PT.run('kordoc', f); st=PT.stats(o); print('kordoc 자가점검:', PT.get('kordoc').version(), '-', st['blocks'], '블록,', st['tables'], '표'); raise SystemExit(0 if st['tables'] else 1)"
if errorlevel 1 goto check_fail

echo.
echo 설치가 끝났습니다. 앱을 다시 켜면 .hwp 파일도 자료함에 넣을 수 있고, '파싱' 탭에서 kordoc을 고를 수 있습니다.
pause
exit /b 0

:no_venv
echo [i] .venv가 없어 자가 점검은 건너뜁니다(install.bat 후 다시 실행하면 점검합니다).
pause
exit /b 0

:npm_fail
echo [!] npm 설치 실패 - 인터넷 연결을 확인하세요.
pause
exit /b 1

:check_fail
echo [!] 자가 점검 실패 - 위 오류 메시지를 확인하세요.
pause
exit /b 1
