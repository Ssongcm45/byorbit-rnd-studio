@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 먼저 install.bat 을 실행하세요.
  pause
  exit /b 1
)
set PYTHONUTF8=1
rem 1) 설치·로그인·자료 도구 등록 상태 (질문을 보내지 않음)
".venv\Scripts\python.exe" -m app.cli setup-claude --check
echo.
rem 2) 실제 호출 점검은 고를 때만 (짧은 시험 질문 하나가 Anthropic으로 감)
set "ans="
set /p ans=실제 호출로 앱 연결 점검도 할까요? 시험 질문 하나가 Anthropic으로 갑니다 (y/N): 
if /i "%ans%"=="y" ".venv\Scripts\python.exe" -m app.cli check-claude
pause
