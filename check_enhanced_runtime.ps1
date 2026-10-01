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
Write-Host "[GPU] nvidia-smi:"
try {
    & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
}
catch {
    Write-Host "  nvidia-smi 不可用（宿主没装驱动，或不在 PATH 上）"
}

Write-Host ""
& $PythonExe -c "import importlib.util; mods=['pyannote.audio','wespeaker','insightface','cv2','numpy','torch','huggingface_hub','transformers']; [print(f'[PY] {m:<16} {bool(importlib.util.find_spec(m))}') for m in mods]"
Write-Host ""
& $PythonExe -c "import importlib.util as u; s=u.find_spec('torch'); print('[GPU] torch installed:', bool(s)); print('[GPU] torch.cuda.is_available():', (__import__('torch').cuda.is_available() if s else False)); print('[GPU] device:', (__import__('torch').cuda.get_device_name(0) if s and __import__('torch').cuda.is_available() else '-'))"
Write-Host ""
# sys.path 里必须先有仓库根：本脚本是 `python -c`，sys.path[0] 是当前工作目录而不是脚本
# 所在目录，不插进去的话 `import app.services...` 只在恰好从仓库根调用时才能成功。
& $PythonExe -c "import sys; sys.path.insert(0, r'$RepoRoot'); from app.services.research_runtime import research_runtime; import json; print(json.dumps(research_runtime.get_runtime_summary(), ensure_ascii=False, indent=2))"
