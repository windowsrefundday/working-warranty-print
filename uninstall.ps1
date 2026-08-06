# One-Liner Windows Uninstaller Script for Warranty Label Printer
$ErrorActionPreference = "SilentlyContinue"

Write-Host ""
Write-Host "Created by Joel Manuel for the VA 2026" -ForegroundColor Green
Write-Host "Thanks to Steve, Anthony, Chris, and Ernes" -ForegroundColor Green
Write-Host "Warranty Label Printer - One-Liner Uninstaller" -ForegroundColor Cyan
Write-Host "----------------------------------------------------" -ForegroundColor Cyan

# 1. Stop running processes
Write-Host "Stopping running application instances..." -ForegroundColor Yellow
Get-Process | Where-Object { $_.ProcessName -eq "python" -and $_.CommandLine -like "*main.py*" } | Stop-Process -Force

# 2. Remove shortcuts
Write-Host "Removing Windows shortcuts..." -ForegroundColor Yellow
$startMenuLnk = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Warranty Label Printer.lnk"
$desktopLnk = [Path]::Combine([Environment]::GetFolderPath("Desktop"), "Warranty Label Printer.lnk")
$startupLnk = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Warranty Label Printer.lnk"

Remove-Item -LiteralPath $startMenuLnk -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $desktopLnk -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $startupLnk -Force -ErrorAction SilentlyContinue

# 3. Remove local runtime data
Write-Host "Removing local runtime data and cache..." -ForegroundColor Yellow
$appDataDir = "$env:LOCALAPPDATA\WarrantyLabelPrinter"
Remove-Item -LiteralPath $appDataDir -Recurse -Force -ErrorAction SilentlyContinue

# 4. Remove installation folder
Write-Host "Removing application installation files..." -ForegroundColor Yellow
$installDir = "$env:USERPROFILE\working-warranty-print"
if (Test-Path -LiteralPath $installDir) {
    Remove-Item -LiteralPath $installDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Warranty Label Printer has been completely removed." -ForegroundColor Green
Write-Host "Note: Python and Git remain installed on your system." -ForegroundColor Cyan
Write-Host ""
