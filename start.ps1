# ByOrbit R&D Studio 개인용 - 실행
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location $PSScriptRoot
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $vpy)) { Write-Host "먼저 install.ps1 을 실행하세요." -ForegroundColor Yellow; exit 1 }
$env:PYTHONUTF8 = "1"
& $vpy -m app.cli serve @args
