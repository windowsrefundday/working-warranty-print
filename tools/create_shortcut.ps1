param(
    [switch]$StartMenu,
    [switch]$Desktop,
    [switch]$Startup,
    [string]$Mode = "menu"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$wsh = New-Object -ComObject WScript.Shell

function Create-Lnk {
    param([string]$Path, [string]$AppMode)
    $shortcut = $wsh.CreateShortcut($Path)
    $shortcut.TargetPath = "powershell.exe"
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$repoRoot\warranty-windows.ps1`" $AppMode"
    $shortcut.WorkingDirectory = "$repoRoot"
    $shortcut.Description = "Warranty Label Printer ($AppMode)"
    $shortcut.Save()
    Write-Host "Created shortcut: $Path" -ForegroundColor Green
}

if (-not ($StartMenu -or $Desktop -or $Startup)) {
    $StartMenu = $true
}

if ($StartMenu) {
    $dir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
    Create-Lnk "$dir\Warranty Label Printer.lnk" $Mode
}

if ($Desktop) {
    $dir = [Environment]::GetFolderPath("Desktop")
    Create-Lnk "$dir\Warranty Label Printer.lnk" $Mode
}

if ($Startup) {
    $dir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
    Create-Lnk "$dir\Warranty Label Printer.lnk" $Mode
}
