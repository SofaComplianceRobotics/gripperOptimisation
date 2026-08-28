<#
install_dev.ps1 - One-shot dev setup for lab_shapeOPT.

Run this AFTER cloning lab_shapeOPT into <emio-labs assets>\labs\lab_shapeOPT (git and that
clone are the only prerequisites this can't do for you). It then:
  1. Locates the emio-labs bundled Python (auto-detected, or pass -SofaPy).
  2. Clones sofaopt next to this repo if missing, or pulls it if already there.
  3. Installs sofaopt (editable) and this lab's pinned dependencies into that Python.
  4. Registers lab_shapeOPT in labsConfig.json (idempotent - safe to re-run).

Usage:
    powershell -ExecutionPolicy Bypass -File tools\install_dev.ps1
    powershell -ExecutionPolicy Bypass -File tools\install_dev.ps1 -SofaPy "D:\Compliance\resources\sofa\bin\python\python.exe"
    powershell -ExecutionPolicy Bypass -File tools\install_dev.ps1 -SofaOptDir "C:\dev\SofaOptimisation"
#>

param(
    [string]$SofaPy = "",
    [string]$SofaOptDir = "$env:USERPROFILE\Documents\SofaOptimisation"
)

$ErrorActionPreference = "Stop"

$LabRoot      = (Resolve-Path "$PSScriptRoot\..").Path
$AssetsLabsDir = (Resolve-Path "$LabRoot\..").Path
$LabsConfigPath = Join-Path $AssetsLabsDir "labsConfig.json"

Write-Host "Lab root:        $LabRoot"
Write-Host "assets\labs dir: $AssetsLabsDir"

# --- 1. Locate the emio-labs bundled Python ---------------------------------
if (-not $SofaPy) {
    Write-Host "`nLooking for the emio-labs bundled Python..."
    $standard = "$env:LOCALAPPDATA\Programs\emio-labs\resources\sofa\bin\python\python.exe"
    if (Test-Path $standard) {
        $SofaPy = $standard
    } else {
        # Portable / non-standard installs (e.g. a copy dropped in Documents): search a
        # handful of common roots for emio-labs.exe and derive the python path from it.
        $roots = @(
            "$env:LOCALAPPDATA\Programs",
            "$env:ProgramFiles",
            "${env:ProgramFiles(x86)}",
            "$env:USERPROFILE\Documents",
            "$env:USERPROFILE\Desktop"
        ) | Where-Object { $_ -and (Test-Path $_) }

        $found = $roots | ForEach-Object {
            Get-ChildItem -Path $_ -Recurse -Depth 4 -Filter "emio-labs.exe" -ErrorAction SilentlyContinue
        } | Select-Object -ExpandProperty FullName -Unique

        if ($found.Count -eq 1) {
            $exeDir = Split-Path $found[0] -Parent
            $candidate = Join-Path $exeDir "resources\sofa\bin\python\python.exe"
            if (Test-Path $candidate) { $SofaPy = $candidate }
        } elseif ($found.Count -gt 1) {
            Write-Host "Found multiple emio-labs.exe installs:"
            $found | ForEach-Object { Write-Host "  $_" }
            throw "Ambiguous install. Re-run with -SofaPy pointing at the right one's resources\sofa\bin\python\python.exe"
        }
    }
}

if (-not $SofaPy -or -not (Test-Path $SofaPy)) {
    throw "Could not find the emio-labs bundled Python. Locate emio-labs.exe yourself, then re-run with -SofaPy `"<its folder>\resources\sofa\bin\python\python.exe`""
}

Write-Host "Using Python: $SofaPy"
& $SofaPy --version

# --- 2. Clone or update sofaopt ----------------------------------------------
if (Test-Path (Join-Path $SofaOptDir ".git")) {
    Write-Host "`nsofaopt already cloned at $SofaOptDir, pulling..."
    git -C $SofaOptDir pull
} else {
    Write-Host "`nCloning sofaopt into $SofaOptDir..."
    git clone https://github.com/SofaComplianceRobotics/SofaOptimisation.git $SofaOptDir
}

# --- 3. Install dependencies --------------------------------------------------
Write-Host "`nInstalling sofaopt (editable, with dashboard+preview extras)..."
& $SofaPy -m pip install -e "$SofaOptDir[dashboard,preview]"
if ($LASTEXITCODE -ne 0) { throw "pip install of sofaopt failed" }

Write-Host "`nInstalling lab_shapeOPT dependencies..."
& $SofaPy -m pip install -r (Join-Path $LabRoot "tools\requirements-bundle.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install of lab dependencies failed" }

# --- 4. Register the lab in labsConfig.json -----------------------------------
Write-Host "`nRegistering lab_shapeOPT in labsConfig.json..."
if (-not (Test-Path $LabsConfigPath)) {
    throw "labsConfig.json not found at $LabsConfigPath - is $AssetsLabsDir really the emio-labs assets\labs folder?"
}

$labsConfig = Get-Content $LabsConfigPath -Raw | ConvertFrom-Json
$already = $labsConfig.labs | Where-Object { $_.name -eq "lab_shapeOPT" }
if ($already) {
    Write-Host "lab_shapeOPT is already registered, leaving labsConfig.json untouched."
} else {
    $entry = [PSCustomObject]@{
        name        = "lab_shapeOPT"
        filename    = "lab_shapeOPT.md"
        title       = "Shape Optimization"
        description = "optimise the shape of a structure to meet a target performance"
    }
    $labsConfig.labs = @($labsConfig.labs) + $entry
    ($labsConfig | ConvertTo-Json -Depth 10) | Set-Content -Path $LabsConfigPath -Encoding utf8
    Write-Host "Added lab_shapeOPT to labsConfig.json."
}

Write-Host "`nDone. Restart EmioLabs, or launch directly with:"
Write-Host "  & `"$SofaPy`" `"$LabRoot\launcher\launch_web.py`""
