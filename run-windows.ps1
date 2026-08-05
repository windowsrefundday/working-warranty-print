$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "Created by Joel Manuel for the VA 2026" -ForegroundColor Green
Write-Host "Thanks to Steve, Anthony, Chris, and Ernes" -ForegroundColor Green

$python = "$PSScriptRoot\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing .venv. Run .\setup-windows.ps1 first."
}

& $python main.py --mode cli @args
exit $LASTEXITCODE
