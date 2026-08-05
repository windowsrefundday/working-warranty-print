param(
    [ValidateSet("menu", "help", "setup", "doctor", "printer", "safe", "cli", "web", "verify")]
    [string]$Command = "menu",
    [int]$Port = 9191,
    [switch]$Tunnel,
    [switch]$WithTunnelRuntime,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ExtraArgs
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
Write-Host "Created by Joel Manuel for the VA 2026" -ForegroundColor Green
Write-Host "Thanks to Steve, Anthony, Chris, and Ernes" -ForegroundColor Green
$python = "$PSScriptRoot\.venv\Scripts\python.exe"

function Show-Help {
    Write-Host @"
Warranty Label Printer - Windows Operator Tool

Usage:
  .\warranty-windows.ps1              Interactive menu
  .\warranty-windows.ps1 setup
  .\warranty-windows.ps1 setup -WithTunnelRuntime
  .\warranty-windows.ps1 doctor
  .\warranty-windows.ps1 printer
  .\warranty-windows.ps1 safe
  .\warranty-windows.ps1 cli
  .\warranty-windows.ps1 web -Port 9191
  .\warranty-windows.ps1 web -Port 9191 -Tunnel
  .\warranty-windows.ps1 verify

Commands:
  setup    Create .venv, install dependencies/Chromium, and diagnose
  doctor   Read-only check of Python, Chromium, storage, driver, and queue
  printer  Select and save one validated local USB TSC MB341 queue
  safe     Start the scanner with virtual-file output only
  cli      Start normal scanner mode; physical output requires a valid binding
  web      Start the browser interface; add -Tunnel for secure phone camera use
  verify   Run unit tests, compilation, and Pyright when Node.js is available
"@
}

function Require-Environment {
    if (-not (Test-Path -LiteralPath $python)) {
        Write-Host "The local environment is missing." -ForegroundColor Red
        Write-Host "Run: Set-ExecutionPolicy -Scope Process Bypass"
        Write-Host "Then: .\warranty-windows.ps1 setup"
        exit 1
    }
}

function Assert-ExitCode {
    param([string]$Description)
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Invoke-Menu {
    while ($true) {
        Write-Host ""
        Write-Host "Warranty Label Printer" -ForegroundColor Cyan
        Write-Host "  1. Start CLI printer mode"
        Write-Host "  2. Start web mode"
        Write-Host "  3. Start safe virtual-output mode"
        Write-Host "  4. Run diagnostics"
        Write-Host "  5. Run printer setup"
        Write-Host "  6. Run environment setup"
        Write-Host "  0. Exit"
        $choice = Read-Host "Select an option"
        switch ($choice) {
            "1" { & $PSCommandPath cli; return }
            "2" { & $PSCommandPath web; return }
            "3" { & $PSCommandPath safe; return }
            "4" { & $PSCommandPath doctor; Read-Host "Press Enter to continue" | Out-Null }
            "5" { & $PSCommandPath printer; Read-Host "Press Enter to continue" | Out-Null }
            "6" { & $PSCommandPath setup; Read-Host "Press Enter to continue" | Out-Null }
            "0" { return }
            default { Write-Host "Choose a number from 0 to 6." -ForegroundColor Yellow }
        }
    }
}

switch ($Command) {
    "menu" {
        Invoke-Menu
    }
    "help" {
        Show-Help
    }
    "setup" {
        $setupArgs = @()
        if ($WithTunnelRuntime) {
            $setupArgs += "-WithTunnelRuntime"
        }
        & "$PSScriptRoot\setup-windows.ps1" @setupArgs
        exit $LASTEXITCODE
    }
    "doctor" {
        Require-Environment
        $diagnosticText = (& $python main.py --diagnose | Out-String)
        Assert-ExitCode "Diagnostics"
        $diagnostic = $diagnosticText | ConvertFrom-Json

        Write-Host ""
        Write-Host "Warranty Label Printer - Windows Readiness" -ForegroundColor Cyan
        Write-Host "No print or calibration command was sent."
        Write-Host ""

        $osColor = if ($diagnostic.supported) { "Green" } else { "Red" }
        Write-Host ("[OS]       {0} / {1}" -f $diagnostic.os, $diagnostic.architecture) -ForegroundColor $osColor
        Write-Host ("[Python]   {0}" -f $diagnostic.python) -ForegroundColor $osColor

        $pathColor = if ($diagnostic.paths.writable) { "Green" } else { "Red" }
        Write-Host ("[Data]     {0}" -f $diagnostic.paths.data_dir) -ForegroundColor $pathColor

        $browserReady = $diagnostic.browser.playwright_installed -and $diagnostic.browser.chromium_installed
        $browserColor = if ($browserReady) { "Green" } else { "Yellow" }
        $browserText = if ($browserReady) { "Playwright and Chromium are ready" } else { "Browser components need repair; rerun setup" }
        Write-Host ("[Browser]  {0}" -f $browserText) -ForegroundColor $browserColor

        if ($diagnostic.printer.is_ready) {
            Write-Host ("[Printer]  READY: {0}, {1} dpi, USB binding confirmed" -f $diagnostic.printer.queue_name, $diagnostic.printer.dpi) -ForegroundColor Green
        } elseif (@($diagnostic.printer.candidate_queues).Count -gt 0) {
            Write-Host ("[Printer]  FOUND but not bound: {0}" -f (@($diagnostic.printer.candidate_queues) -join ", ")) -ForegroundColor Yellow
            Write-Host "           Run: .\warranty-windows.ps1 printer"
        } else {
            Write-Host "[Printer]  No validated local USB TSC MB341 queue found" -ForegroundColor Yellow
            Write-Host "           1. Download the official WHQL Windows driver:"
            Write-Host "              https://usca.tscprinters.com/en/downloads"
            Write-Host "           2. Filter for MB341 and install the Windows x64 driver."
            Write-Host "           3. Connect the printer directly by USB and turn it on."
            Write-Host "           4. In Windows Settings > Bluetooth & devices > Printers & scanners,"
            Write-Host "              confirm the TSC MB341 queue is online and not paused."
            Write-Host "           5. Run: .\warranty-windows.ps1 printer"
        }
        Write-Host ""
    }
    "printer" {
        Require-Environment
        & $python main.py --setup-printer
        exit $LASTEXITCODE
    }
    "safe" {
        Require-Environment
        & $python main.py --mode cli --printer file @ExtraArgs
        exit $LASTEXITCODE
    }
    "cli" {
        Require-Environment
        & $python main.py --mode cli --printer tsc @ExtraArgs
        exit $LASTEXITCODE
    }
    "web" {
        Require-Environment
        $webArgs = @("main.py", "--mode", "web", "--port", $Port)
        if ($Tunnel) {
            $webArgs += "--tunnel"
        }
        $webArgs += $ExtraArgs
        & $python @webArgs
        exit $LASTEXITCODE
    }
    "verify" {
        Require-Environment
        Write-Host "[1/3] Running unit tests" -ForegroundColor Cyan
        & $python -m unittest discover -s tests -v
        Assert-ExitCode "Unit tests"
        Write-Host "[2/3] Compiling Python sources" -ForegroundColor Cyan
        & $python -m compileall -q core interfaces main.py tests
        Assert-ExitCode "Compilation"
        Write-Host "[3/3] Running Pyright when Node.js is installed" -ForegroundColor Cyan
        if (Get-Command npx -ErrorAction SilentlyContinue) {
            & npx --yes pyright
            Assert-ExitCode "Pyright"
        } else {
            Write-Host "Skipped Pyright because npx is not installed." -ForegroundColor Yellow
        }
        Write-Host "Verification completed." -ForegroundColor Green
    }
}
