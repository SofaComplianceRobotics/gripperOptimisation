<#
build_bundle.ps1 - Produce a self-contained lab_shapeOPT distribution zip.

Stages the lab source plus its Python 3.10 dependencies (installed with the
emio-labs SOFA python so the ABI and OCP cp310 build match), then zips it.
A user unzips the result into emio-labs\...\assets\labs and clicks Run - no
pip, no venv, no further setup.

Usage:
    powershell -ExecutionPolicy Bypass -File tools\build_bundle.ps1
    powershell -ExecutionPolicy Bypass -File tools\build_bundle.ps1 -SofaRoot "D:\emio-labs\resources\sofa"
    powershell -ExecutionPolicy Bypass -File tools\build_bundle.ps1 -SourceOnly

-SourceOnly skips the dependencies and produces a small lab_shapeOPT_source.zip
containing just the lab source. Extract it over an existing install to update
the code without touching runtime\modules\site-packages.
#>

param(
    [string]$SofaRoot = "$env:LOCALAPPDATA\Programs\emio-labs\resources\sofa",
    [string]$OutDir   = "$PSScriptRoot\..\dist",
    [switch]$SourceOnly
)

$ErrorActionPreference = "Stop"

$LabRoot      = (Resolve-Path "$PSScriptRoot\..").Path
$SofaPython   = Join-Path $SofaRoot "bin\python\python.exe"
$Requirements = Join-Path $PSScriptRoot "requirements-bundle.txt"

if ($SourceOnly) {
    Write-Host "Building source-only patch (no dependencies)"
} else {
    if (-not (Test-Path $SofaPython)) {
        throw "SOFA python not found at $SofaPython. Pass -SofaRoot <emio-labs>\resources\sofa."
    }
    $pyVer = (& $SofaPython -c "import sys;print('%d.%d'%sys.version_info[:2])").Trim()
    Write-Host "Building with SOFA python $pyVer at $SofaPython"
}

# --- 1. Clean staging dir (zip root is the lab folder itself) ---------------
$StageRoot = Join-Path $env:TEMP "lab_shapeOPT_bundle"
$Stage     = Join-Path $StageRoot "lab_shapeOPT"
if (Test-Path $StageRoot) { Remove-Item $StageRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

# --- 2. Copy the source from the working tree -------------------------------
# git ls-files (cached + untracked-not-ignored) gives the real project files
# from disk, so uncommitted edits ship and .venv / .git / caches are skipped.
Push-Location $LabRoot
$files = git ls-files --cached --others --exclude-standard
Pop-Location

# runtime/modules is rebuilt fresh below; runtime/{exports,logs,...} and other
# generated or machine-local artifacts never ship.
$skip = '^(\.venv/|dist/|tools/|runtime/modules/|runtime/(exports|logs|trials|recordings)/|runtime/.*\.(db|log)$|.*__pycache__/|.*\.pyc$|.*\.crproj$|failed_generation\.png$)'

$copied = 0
foreach ($f in $files) {
    if ($f -match $skip) { continue }
    $src = Join-Path $LabRoot $f
    if (-not (Test-Path $src)) { continue }
    $dst = Join-Path $Stage $f
    New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
    Copy-Item $src $dst
    $copied++
}
Write-Host "Staged $copied source files"

# --- 3. Install lab deps for Python 3.10 into the bundle's site-packages -----
if (-not $SourceOnly) {
    $BundleSP = Join-Path $Stage "runtime\modules\site-packages"
    New-Item -ItemType Directory -Force -Path $BundleSP | Out-Null
    Write-Host "Installing dependencies into runtime\modules\site-packages ..."
    & $SofaPython -m pip install --no-cache-dir --target $BundleSP -r $Requirements
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

    # --- 4. Slim the installed packages -------------------------------------
    Get-ChildItem $BundleSP -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem $BundleSP -Recurse -File -Include *.pyc -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    # Keep only the 3.10 ABI; drop any other-version compiled extensions.
    Get-ChildItem $BundleSP -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '\.cp3(?!10)\d\d-' } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

# --- 5. Zip ------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$zipName = if ($SourceOnly) { "lab_shapeOPT_source.zip" } else { "lab_shapeOPT_bundle.zip" }
$Zip = Join-Path $OutDir $zipName
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Write-Host "Compressing (this can take a minute) ..."
Compress-Archive -Path $Stage -DestinationPath $Zip

$sizeMB = [math]::Round((Get-Item $Zip).Length / 1MB, 1)
Write-Host ""
Write-Host "Bundle written: $Zip ($sizeMB MB)"
if ($SourceOnly) {
    Write-Host "Extract OVER an existing assets\labs\lab_shapeOPT to update the code (deps untouched)."
} else {
    Write-Host "Unzip into <emio-labs>\v25.12.00\assets\labs\ to get assets\labs\lab_shapeOPT."
}
