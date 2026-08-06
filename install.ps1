# One-Liner Windows Installer Script for Warranty Label Printer (working-warranty-print)
$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Created by Joel Manuel for the VA 2026" -ForegroundColor Green
Write-Host "Thanks to Steve, Anthony, Chris, and Ernes" -ForegroundColor Green
Write-Host "Warranty Label Printer - One-Liner Installer" -ForegroundColor Cyan
Write-Host "--------------------------------------------------" -ForegroundColor Cyan

function Refresh-EnvPath {
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Install-WingetPackage {
    param([string]$PackageId, [string]$DisplayName)
    Write-Host "Installing $DisplayName via winget..." -ForegroundColor Yellow
    try {
        & winget install --id $PackageId -e --accept-source-agreements --accept-package-agreements
        Refresh-EnvPath
    } catch {
        Write-Host "Warning: winget installation of $DisplayName failed or was restricted." -ForegroundColor Yellow
    }
}

# 1. Prerequisite Check & Winget Installation
Refresh-EnvPath

if (-not (Test-Command "git")) {
    if (Test-Command "winget") {
        Install-WingetPackage "Git.Git" "Git"
    }
}

$hasPython = $false
if (Test-Command "python") {
    try {
        $pythonCheck = & python -c "import platform,sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}:{platform.machine()}')" 2>$null
        if ($pythonCheck -like "3.1[1-9]*:AMD64" -or $pythonCheck -like "3.1[1-9]*:x86_64") {
            $hasPython = $true
        }
    } catch {}
}

if (-not $hasPython -and (Test-Command "py")) {
    try {
        $pyCheck = & py -3 -c "import platform,sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}:{platform.machine()}')" 2>$null
        if ($pyCheck -like "3.1[1-9]*:AMD64" -or $pyCheck -like "3.1[1-9]*:x86_64") {
            $hasPython = $true
        }
    } catch {}
}

if (-not $hasPython) {
    if (Test-Command "winget") {
        Install-WingetPackage "Python.Python.3.11" "Python 3.11 (64-bit)"
    }
}

# Re-check after winget
Refresh-EnvPath

if (-not (Test-Command "git")) {
    Write-Host ""
    Write-Host "Git is required but was not found on PATH." -ForegroundColor Red
    Write-Host "If winget is disabled on your device, download Git from https://git-scm.com/download/win" -ForegroundColor Yellow
    Write-Host "Press Enter to exit..." -ForegroundColor Gray
    $null = Read-Host
    exit 1
}

# 2. Target Directory & Clone/Pull
$targetDir = "$env:USERPROFILE\working-warranty-print"
if (Test-Path -LiteralPath $targetDir) {
    Write-Host "Updating existing installation in $targetDir..." -ForegroundColor Cyan
    Set-Location -LiteralPath $targetDir
    & git pull origin main
} else {
    Write-Host "Cloning repository to $targetDir..." -ForegroundColor Cyan
    & git clone https://github.com/windowsrefundday/working-warranty-print.git "$targetDir"
    Set-Location -LiteralPath $targetDir
}

# 3. Environment Setup
Write-Host ""
Write-Host "Running environment setup script..." -ForegroundColor Cyan
& "$targetDir\setup-windows.ps1"

# 4. Printer Queue & Driver Auto-Detection
Write-Host ""
Write-Host "Checking for connected TSC MB341 thermal printer queue..." -ForegroundColor Cyan
$tscPrinter = Get-Printer | Where-Object { $_.Name -like "*MB341*" -or $_.DriverName -like "*TSC*" } -ErrorAction SilentlyContinue
if ($tscPrinter) {
    Write-Host "[Printer] Found online TSC printer queue: $($tscPrinter.Name)" -ForegroundColor Green
} else {
    Write-Host "[Printer] No local TSC MB341 USB queue detected." -ForegroundColor Yellow
    Write-Host "           Physical printing requires the WHQL Windows driver:" -ForegroundColor Yellow
    Write-Host "           https://usca.tscprinters.com/en/downloads" -ForegroundColor Yellow
}

# 5. Shortcut Creation
Write-Host ""
Write-Host "Creating Windows Start Menu and Desktop shortcuts..." -ForegroundColor Cyan
if (Test-Path -LiteralPath "$targetDir\tools\create_shortcut.ps1") {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$targetDir\tools\create_shortcut.ps1" -StartMenu -Desktop
}

Write-Host ""
Write-Host "Installation completed successfully!" -ForegroundColor Green
Write-Host "Opening Warranty Label Printer..." -ForegroundColor Cyan
Write-Host ""

# 5. Launch Application Menu
& "$targetDir\warranty-windows.bat"
