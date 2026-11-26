@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto venv_ok
echo [!] .venv가 없습니다. 먼저 install.bat을 실행해 기본 설치를 끝내세요.
pause
exit /b 1

:venv_ok
echo.
echo === ByOrbit R^&D Studio - 크롤러 브라우저 방식(Playwright) 설치 ===
echo 자바스크립트로 그리는 자료 목록을 이 PC의 헤드리스 Chrome으로 읽습니다.
echo 브라우저는 크롤러만 씁니다(http/https 주소만, 이미지·글꼴·영상은 받지 않음). AI에게 브라우저를 도구로 주지 않습니다.
echo.
echo [1/3] 패키지 설치 (requirements-browser.txt: playwright)...
".venv\Scripts\python.exe" -m pip install -r requirements-browser.txt
if errorlevel 1 goto pip_fail

echo.
echo [2/3] 설치된 Chrome 찾기...
set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not defined CHROME goto no_chrome
echo       찾음: %CHROME%
echo       설치된 Chrome을 쓰므로 브라우저를 따로 받지 않습니다.
goto selfcheck

:no_chrome
echo       설치된 Chrome이 없습니다.
echo       대신 Playwright의 chromium을 받을 수 있습니다(인터넷에서 약 150MB, %%LOCALAPPDATA%%\ms-playwright 에 저장).
choice /C YN /M "chromium을 받을까요"
if errorlevel 2 goto skip_chromium
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto chromium_fail
goto selfcheck

:skip_chromium
echo.
echo chromium을 받지 않았습니다. Chrome을 설치한 뒤 이 파일을 다시 실행하세요. 그 전까지 브라우저 방식은 '미설치'로 보입니다.
pause
exit /b 1

:selfcheck
echo.
echo [3/3] 자가 점검(헤드리스 Chrome으로 https://example.com 을 열어 제목 읽기)...
set PYTHONUTF8=1
".venv\Scripts\python.exe" -c "import re; from app.collect.backends import browser as b; st=b.status(); print('브라우저 방식:', st['message']); s=b.open({'id':'selfcheck'}); s.__enter__(); pg=s.fetch('https://example.com'); s.__exit__(None,None,None); m=re.search(r'<title>(.*?)</title>', pg.html, re.S|re.I); t=m.group(1).strip() if m else ''; print('자가점검 결과 - 페이지 제목:', t or '(제목 없음)'); raise SystemExit(0 if t else 1)"
if errorlevel 1 goto check_fail

echo.
echo 설치가 끝났습니다. 앱을 다시 켠 뒤 자료 수집 - 크롤러 사이트에서 사이트별 '가져오기 방식'을 '브라우저'로 고르세요.
pause
exit /b 0

:pip_fail
echo [!] 패키지 설치 실패 - 인터넷 연결을 확인하고 다시 실행하세요.
pause
exit /b 1

:chromium_fail
echo [!] chromium 받기 실패 - 인터넷 연결을 확인하거나 Chrome을 설치한 뒤 다시 실행하세요.
pause
exit /b 1

:check_fail
echo [!] 자가 점검 실패 - 위 오류 메시지를 확인하세요. 회사망에서 https://example.com 이 막혀 있어도 실패할 수 있습니다.
pause
exit /b 1
