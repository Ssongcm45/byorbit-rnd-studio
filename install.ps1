# R&D Studio V0.5 - 설치 (Windows PowerShell)
# 실행: 폴더에서 마우스 오른쪽 > "PowerShell에서 실행" 또는  powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Continue"   # 네이티브 명령의 경고(stderr)로 멈추지 않게; 종료 코드로 판단
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot
Write-Host ""
Write-Host "=== R&D Studio V0.5 설치 ===" -ForegroundColor Cyan
# GitHub ZIP으로 받으면 스크립트에 "인터넷에서 받음" 표시가 붙어 start.ps1 등이 막힐 수 있다 — 이 폴더 것만 풀어 준다
try { Get-ChildItem -Path (Join-Path $PSScriptRoot '*') -Include *.ps1,*.bat -File -ErrorAction Stop | Unblock-File -ErrorAction Stop } catch {}

# 1) 파이썬 3.11 이상 찾기 (py 런처 우선)
$py = $null; $pyArgs = @(); $v = ""
$cands = @(@{exe="py"; args=@("-3.13")}, @{exe="py"; args=@("-3.12")}, @{exe="py"; args=@("-3.11")}, @{exe="python"; args=@()})
foreach ($c in $cands) {
  if (-not (Get-Command $c.exe -ErrorAction SilentlyContinue)) { continue }
  try {
    $out = & $c.exe @($c.args + @("-c", "import sys;print('%d.%d'%sys.version_info[:2])")) 2>$null
    if ($LASTEXITCODE -eq 0 -and $out -and ([version]$out.Trim() -ge [version]"3.11")) { $py = $c.exe; $pyArgs = $c.args; $v = $out.Trim(); break }
  } catch {}
}
if (-not $py) {
  Write-Host "[!] Python 3.11 이상이 필요합니다." -ForegroundColor Yellow
  Write-Host "    winget install Python.Python.3.12   (또는 python.org에서 설치, 'Add to PATH' 체크)"
  exit 1
}
Write-Host "[1/5] Python 확인: $py $($pyArgs -join ' ') ($v)"

# 2) 가상환경
if (-not (Test-Path ".venv\Scripts\python.exe")) {
  & $py @($pyArgs + @("-m", "venv", ".venv"))
}
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Write-Host "[2/5] 가상환경: .venv"

# 3) 패키지
& $vpy -m pip install --upgrade pip -q
& $vpy -m pip install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) { Write-Host "[!] 패키지 설치 실패" -ForegroundColor Red; exit 1 }
Write-Host "[3/5] 패키지 설치 완료"

# 4) 데이터 폴더·DB·시드·MCP 설정
$env:PYTHONUTF8 = "1"
& $vpy -m app.cli init
if ($LASTEXITCODE -ne 0) { Write-Host "[!] 초기화 실패" -ForegroundColor Red; exit 1 }
Write-Host "[4/5] 데이터 폴더 준비 완료 (기본: $env:USERPROFILE\ByOrbit-RD)"

# 5) Claude Code 찾기·로그인 확인·(원하면) 내 Claude Code 대화창에 자료 도구 등록
#    종료 코드: 0 준비됨 · 2 로그인 안 됨 · 3 설치 안 됨 · 4 설치됨(로그인 모름) · 5 이미 등록됨 · 그 밖(1 등)은 오류
Write-Host "[5/5] Claude Code 연결 확인 (질문은 보내지 않습니다)"
& $vpy -m app.cli setup-claude --check
$cc = $LASTEXITCODE
if ($cc -eq 0 -or $cc -eq 4) {
  Write-Host ""
  Write-Host "  자료 도구(byorbit-rd)를 등록하면 이 PC의 Claude Code 대화창에서도"
  Write-Host "  'byorbit-rd로 사과박 식이섬유 자료 찾아줘'처럼 자료를 찾을 수 있습니다. (앱 안의 AI 기능은 등록과 관계없이 됩니다)"
  Write-Host "  주의: 대화창의 Claude는 자기 파일 읽기·셸 도구도 쓰므로, 기밀 원본 보호는 앱 안 'AI에 묻기'보다 약합니다." -ForegroundColor Yellow
  $ans = Read-Host "  내 Claude Code 대화창에도 자료 도구를 등록할까요? (Y/n, Enter = 예)"
  if ($null -eq $ans) { $ans = "" }
  if ($ans.Trim() -eq "" -or $ans.Trim() -match "^(y|yes|예|네|ㅛ)$") {
    & $vpy -m app.cli setup-claude --register
    if ($LASTEXITCODE -ne 0) { Write-Host "  등록하지 못했습니다. 나중에 앱의 설정 > Claude Code 연결 마법사에서 다시 해 보세요." -ForegroundColor Yellow }
  } else {
    Write-Host "  건너뜁니다. 나중에 앱의 설정 > Claude Code 연결 마법사 ④에서 등록할 수 있습니다."
  }
} elseif ($cc -eq 5) {
  Write-Host "  자료 도구는 이미 내 Claude Code에 등록되어 있습니다."
} elseif ($cc -eq 2 -or $cc -eq 3) {
  Write-Host "  위 '다음 할 일'을 마친 뒤 check-claude.bat 을 실행하거나 앱의 설정 > Claude Code 연결 마법사를 여세요." -ForegroundColor Yellow
} else {
  Write-Host "  Claude Code 상태를 확인하지 못했습니다(코드 $cc). 앱의 설정 > Claude Code 연결 마법사에서 확인하세요." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "설치가 끝났습니다. start.bat 을 더블클릭하면 브라우저에서 열립니다." -ForegroundColor Green
