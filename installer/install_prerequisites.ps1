<#
.SYNOPSIS
    Installs all prerequisites for the BOF Asset Decryptor.

.DESCRIPTION
    Checks for and installs:
    - WSL2 (Windows Subsystem for Linux)
    - Ubuntu distribution in WSL

    The BOF Asset Decryptor app handles installing the remaining WSL tools
    (GPG, tar, xvfb, GDRE Tools) automatically via its built-in
    "Install Prerequisites" button.

    This script is safe to re-run — it checks before installing and skips
    anything that is already present.

.NOTES
    Must be run as Administrator (required for WSL installation).
    May require a reboot if WSL2 was not previously enabled.
#>

# --- Require admin ---
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "This script must be run as Administrator." -ForegroundColor Red
    Write-Host "Right-click and select 'Run as administrator', or run from an elevated PowerShell." -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

$ErrorActionPreference = "Continue"
$needsReboot = $false
$results = @()

function Write-Step($msg) {
    Write-Host "`n=== $msg ===" -ForegroundColor Cyan
}

function Write-OK($msg) {
    Write-Host "  [OK] $msg" -ForegroundColor Green
    $script:results += [PSCustomObject]@{ Name = $msg; Status = "OK" }
}

function Write-Installed($msg) {
    Write-Host "  [INSTALLED] $msg" -ForegroundColor Green
    $script:results += [PSCustomObject]@{ Name = $msg; Status = "Installed" }
}

function Write-FAIL($msg) {
    Write-Host "  [MISSING] $msg" -ForegroundColor Red
    $script:results += [PSCustomObject]@{ Name = $msg; Status = "Missing" }
}

function Write-SKIP($msg) {
    Write-Host "  [SKIP] $msg" -ForegroundColor Yellow
    $script:results += [PSCustomObject]@{ Name = $msg; Status = "Skipped" }
}

# ============================================================
# 1. WSL2
# ============================================================
Write-Step "Checking WSL2..."

$wslAvailable = $false
try {
    $wslStatus = wsl --status 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0) {
        $wslAvailable = $true
        Write-OK "WSL2"
    }
} catch {}

if (-not $wslAvailable) {
    Write-Host "  WSL2 is not installed or not enabled." -ForegroundColor Yellow
    $install = Read-Host "  Install WSL2 with Ubuntu now? (y/n)"
    if ($install -eq 'y') {
        Write-Host "  Installing WSL2 with Ubuntu (this may take several minutes)..." -ForegroundColor Cyan
        wsl --install -d Ubuntu 2>&1 | ForEach-Object { Write-Host "    $_" }
        $needsReboot = $true
        Write-Installed "WSL2 + Ubuntu (reboot required)"
    } else {
        Write-SKIP "WSL2"
    }
}

# ============================================================
# 2. Ubuntu distribution
# ============================================================
Write-Step "Checking Ubuntu distribution..."

$ubuntuFound = $false
if ($wslAvailable) {
    try {
        $distros = wsl --list --quiet 2>&1 | Out-String
        if ($distros -match 'Ubuntu') {
            $ubuntuFound = $true
            Write-OK "Ubuntu"
        }
    } catch {}
}

if (-not $ubuntuFound -and -not $needsReboot) {
    if ($wslAvailable) {
        Write-Host "  No Ubuntu distribution found in WSL." -ForegroundColor Yellow
        $install = Read-Host "  Install Ubuntu now? (y/n)"
        if ($install -eq 'y') {
            Write-Host "  Installing Ubuntu (this may take several minutes)..." -ForegroundColor Cyan
            wsl --install -d Ubuntu 2>&1 | ForEach-Object { Write-Host "    $_" }
            if ($LASTEXITCODE -eq 0) {
                $ubuntuFound = $true
                Write-Installed "Ubuntu"
            } else {
                Write-FAIL "Ubuntu (installation failed)"
            }
        } else {
            Write-SKIP "Ubuntu"
        }
    } else {
        Write-SKIP "Ubuntu (WSL2 not available yet — install after reboot)"
    }
} elseif ($needsReboot -and -not $ubuntuFound) {
    Write-SKIP "Ubuntu (will install after WSL2 reboot)"
}

# ============================================================
# Summary
# ============================================================
Write-Host "`n"
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Prerequisites Summary" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

foreach ($r in $results) {
    $color = switch ($r.Status) {
        "OK"        { "Green" }
        "Installed" { "Green" }
        "Missing"   { "Red" }
        "Skipped"   { "Yellow" }
        default     { "White" }
    }
    Write-Host ("  {0,-25} {1}" -f $r.Name, $r.Status) -ForegroundColor $color
}

if ($wslAvailable -and $ubuntuFound) {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "  WSL2 is ready!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Next: Launch BOF Asset Decryptor and click" -ForegroundColor Green
    Write-Host "  'Install Prerequisites' to install GPG," -ForegroundColor Green
    Write-Host "  xvfb, and GDRE Tools inside WSL." -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
}

# ============================================================
# Reboot prompt
# ============================================================
if ($needsReboot) {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Yellow
    Write-Host "  A REBOOT IS REQUIRED to finish WSL2 setup." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  After rebooting, run this script again" -ForegroundColor Yellow
    Write-Host "  from the Start Menu to finish setup." -ForegroundColor Yellow
    Write-Host "============================================" -ForegroundColor Yellow
    Write-Host ""
    $reboot = Read-Host "  Reboot now? (y/n)"
    if ($reboot -eq 'y') {
        Restart-Computer -Force
    }
}

Write-Host ""
Read-Host "Press Enter to exit"
