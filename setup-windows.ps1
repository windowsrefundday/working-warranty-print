param(
    [switch]$WithTunnelRuntime,
    [string]$BrowserCaCert
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Write-Step {
    param([int]$Number, [string]$Message)
    Write-Host ""
    Write-Host "[$Number/2] $Message" -ForegroundColor Cyan
}

function Assert-LastCommand {
    param([string]$Description)
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

Write-Host "Created by Joel Manuel for the VA 2026" -ForegroundColor Green
Write-Host "Thanks to Steve, Anthony, Chris, and Ernes" -ForegroundColor Green
Write-Host "Warranty Label Printer - Windows Setup" -ForegroundColor Green
Write-Host "This creates a local Python environment and runs read-only checks."
Write-Host "It will NOT print a label, calibrate a printer, or install a printer driver."

Write-Step 1 "Finding a supported 64-bit Python"
$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($launcher) {
    $pythonExe = $launcher.Source
    $pythonPrefix = @("-3")
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        Write-Host ""
        Write-Host "Python was not found." -ForegroundColor Red
        Write-Host "Install 64-bit Python 3.11 or newer from https://www.python.org/downloads/windows/"
        Write-Host "During installation, enable 'Add python.exe to PATH', then reopen PowerShell."
        exit 1
    }
    $pythonExe = $pythonCommand.Source
    $pythonPrefix = @()
}

& $pythonExe @pythonPrefix -c "import platform,sys; ok=sys.version_info >= (3,11) and platform.machine().lower() in {'amd64','x86_64'}; print(f'Python {platform.python_version()} ({platform.machine()})'); raise SystemExit(0 if ok else '64-bit Python 3.11 or newer is required.')"
Assert-LastCommand "Python compatibility check"

Write-Step 2 "Running the shared read-only setup"
$setupArgs = @()
$hasNpm = [bool](Get-Command npm -ErrorAction SilentlyContinue)
if ($WithTunnelRuntime -or $hasNpm) {
    $setupArgs += "--with-tunnel-runtime"
}
if ($BrowserCaCert) {
    $setupArgs += @("--browser-ca-cert", $BrowserCaCert)
}
& $pythonExe @pythonPrefix "$PSScriptRoot\tools\setup.py" @setupArgs
Assert-LastCommand "Shared setup"

Write-Host ""
Write-Host "Setup completed successfully." -ForegroundColor Green
Write-Host "Next:"
Write-Host "  1. Bind the USB printer: .\warranty-windows.ps1 printer"
Write-Host "  2. Try virtual output:   .\warranty-windows.ps1 safe"
Write-Host "  3. Start normal mode:    .\warranty-windows.ps1 cli"
