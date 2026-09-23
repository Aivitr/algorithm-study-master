param(
    [string]$RepoRoot = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [string]$ModelRoot = "",
    [string]$GalleryRoot = "",
    [string]$PythonExe = "",
    [string]$HFToken = "",
    [switch]$InstallPythonDeps = $true,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $ModelRoot) {
    $ModelRoot = Join-Path $RepoRoot "storage\research_models"
}
if (-not $GalleryRoot) {
    $GalleryRoot = Join-Path $RepoRoot "storage\research_gallery"
}
if (-not $PythonExe) {
    if ($env:RESEARCH_ENHANCED_PYTHON) {
        $PythonExe = $env:RESEARCH_ENHANCED_PYTHON
    } else {
        $PythonExe = "python"
    }
}
if (-not $HFToken -and $env:RESEARCH_HF_TOKEN) {
    $HFToken = $env:RESEARCH_HF_TOKEN
}

Write-Host "[STEP] Preparing enhanced layout..."
powershell -ExecutionPolicy Bypass -File (Join-Path $RepoRoot "prepare_enhanced_model_layout.ps1") -RepoRoot $RepoRoot -ModelRoot $ModelRoot -GalleryRoot $GalleryRoot -Force:$Force | Out-Null

if ($InstallPythonDeps) {
    Write-Host "[STEP] Installing enhanced runtime Python dependencies..."
    & $PythonExe -m pip install -r (Join-Path $RepoRoot "requirements_enhanced_runtime.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install requirements_enhanced_runtime.txt"
    }
}

Write-Host "[STEP] Downloading open-source models and repos for enhanced mode..."
$argsList = @(
    (Join-Path $RepoRoot "download_enhanced_open_models.py"),
    "--repo-root", $RepoRoot,
    "--model-root", $ModelRoot,
    "--gallery-root", $GalleryRoot,
    "--python-exe", $PythonExe
)

if ($HFToken) {
    $argsList += @("--hf-token", $HFToken)
}
if ($Force) {
    $argsList += "--force"
}

& $PythonExe @argsList
if ($LASTEXITCODE -ne 0) {
    throw "Enhanced open-source model download failed"
}

Write-Host ""
Write-Host "[OK] Enhanced runtime setup finished."
Write-Host "Next:"
Write-Host "1. Set RESEARCH_DEPLOYMENT_PROFILE=enhanced"
Write-Host "2. Set RESEARCH_MODULES_ENABLED=true"
Write-Host "3. Set RESEARCH_RUNTIME_MODE=enhanced_strict"
Write-Host "4. If you use a dedicated venv, set RESEARCH_ENHANCED_PYTHON to that Python path"
Write-Host "5. Run .\\check_enhanced_runtime.ps1 -PythonExe $PythonExe"
