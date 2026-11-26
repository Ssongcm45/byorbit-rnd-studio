@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto venv_ok
echo [!] .venv가 없습니다. 먼저 install.bat을 실행해 기본 설치를 끝내세요.
pause
exit /b 1

:venv_ok
echo.
echo === ByOrbit R^&D Studio - Docling 파서 설치 (선택) ===
echo 레이아웃 모델로 2단 논문의 읽기 순서, 제목 단계, 병합 셀 표를 복원하는 로컬 PDF 파서입니다.
echo 문서 파일은 이 PC 밖으로 나가지 않습니다. 인터넷으로 받는 것은 패키지와 모델 파일뿐입니다.
echo.
echo [주의] 크기가 큽니다:
echo   - 패키지 약 1.5GB (PyTorch CPU 포함) - 설치에 4~10분
echo   - 처음 변환할 때 레이아웃/표 모델 약 500MB를 Hugging Face에서 받습니다 (사용자 폴더 .cache\huggingface)
echo   - 첫 변환은 30초 이상, 그다음부터 쪽당 1초 안팎
echo.
choice /m "계속 설치할까요"
if errorlevel 2 exit /b 0

echo.
echo [1/2] 패키지 설치 (requirements-docling.txt: docling)...
".venv\Scripts\python.exe" -m pip install -r requirements-docling.txt
if errorlevel 1 goto pip_fail

echo.
echo [2/2] 자가 점검(예시 PDF 만들기 -^> Docling 변환, 처음이면 모델을 받습니다)...
set PYTHONUTF8=1
".venv\Scripts\python.exe" -c "import tempfile, pathlib; from app import sample_files as s; from app.ingest import parser_tools as PT; d=pathlib.Path(tempfile.mkdtemp()); f=s.make_pdf(d/'check.pdf'); o=PT.run('docling', f); st=PT.stats(o); print('Docling 자가점검:', st['blocks'], '블록,', st['tables'], '표,', st['duration_ms'], 'ms'); raise SystemExit(0 if st['blocks'] else 1)"
if errorlevel 1 goto check_fail

echo.
echo 설치가 끝났습니다. 앱을 다시 켜면 자료의 '파싱' 탭에서 Docling을 고를 수 있습니다.
pause
exit /b 0

:pip_fail
echo [!] 패키지 설치 실패 - 인터넷 연결과 디스크 여유 공간(2GB 이상)을 확인하세요.
pause
exit /b 1

:check_fail
echo [!] 자가 점검 실패 - 위 오류 메시지를 확인하세요. 모델 다운로드가 막혔다면 인터넷 연결을 확인한 뒤 다시 실행하세요.
pause
exit /b 1
