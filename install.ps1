# ByOrbit R&D Studio 개인용 - 설치 (Windows PowerShell)
# 실행: 폴더에서 마우스 오른쪽 > "PowerShell에서 실행" 또는  powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Continue"   # 네이티브 명령의 경고(stderr)로 멈추지 않게; 종료 코드로 판단
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot
Write-Host ""
Write-Host "=== ByOrbit R&D Studio 개인용 설치 ===" -ForegroundColor Cyan

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

# 5) Claude Code 확인
$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
  $cv = & claude --version 2>$null
  Write-Host "[5/5] Claude Code 확인: $cv"
  Write-Host "      처음이라면 터미널에서 'claude'를 한 번 실행해 로그인하세요."
} else {
  Write-Host "[5/5] Claude Code를 찾지 못했습니다." -ForegroundColor Yellow
  Write-Host "      설치:  irm https://claude.ai/install.ps1 | iex     (또는 npm install -g @anthropic-ai/claude-code)"
  Write-Host "      설치 후 'claude'를 실행해 로그인하고, 앱의 설정 > 연결 점검을 누르세요."
}
Write-Host ""
Write-Host "설치가 끝났습니다. start.bat 을 더블클릭하면 브라우저에서 열립니다." -ForegroundColor Green
