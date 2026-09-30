param(
    [string]$RepoRoot = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [string]$PythonExe = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$modelRoot = Join-Path $RepoRoot "storage\research_models"
$galleryRoot = Join-Path $RepoRoot "storage\research_gallery"

if (-not $PythonExe) {
    if ($env:RESEARCH_ENHANCED_PYTHON) {
        $PythonExe = $env:RESEARCH_ENHANCED_PYTHON
    } else {
        $PythonExe = "python"
    }
}

Write-Host "[CHECK] Repo root: $RepoRoot"
Write-Host "[CHECK] Model root: $modelRoot"
Write-Host "[CHECK] Gallery root: $galleryRoot"
Write-Host "[CHECK] Python: $PythonExe"
Write-Host ""

$slots = @("pyannote", "wespeaker", "talknet_asd", "insightface", "clip_vit_b16", "bge_m3")
foreach ($slot in $slots) {
    $path = Join-Path $modelRoot $slot
    $exists = Test-Path $path
    Write-Host ("[DIR] {0,-14} {1}" -f $slot, $(if ($exists) { "OK" } else { "MISSING" }))
}

Write-Host ""
& $PythonExe -c "import importlib.util; mods=['pyannote.audio','wespeaker','insightface','cv2','numpy','torch','huggingface_hub','transformers']; [print(f'[PY] {m:<16} {bool(importlib.util.find_spec(m))}') for m in mods]"
Write-Host ""
& $PythonExe -c "from research_runtime import research_runtime; import json; print(json.dumps(research_runtime.get_runtime_summary(), ensure_ascii=False, indent=2))"
