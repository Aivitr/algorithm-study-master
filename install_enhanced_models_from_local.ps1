param(
    [string]$RepoRoot = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [string]$ModelRoot = "",
    [string]$GalleryRoot = "",
    [string]$PyannoteSource = "",
    [string]$WeSpeakerSource = "",
    [string]$TalkNetSource = "",
    [string]$InsightFaceSource = "",
    [string]$ClipSource = "",
    [string]$BgeSource = "",
    [string]$GallerySource = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $ModelRoot) {
    $ModelRoot = Join-Path $RepoRoot "storage\research_models"
}
if (-not $GalleryRoot) {
    $GalleryRoot = Join-Path $RepoRoot "storage\research_gallery"
}

$copyTasks = @(
    @{ Name = "pyannote"; Source = $PyannoteSource; Target = Join-Path $ModelRoot "pyannote" },
    @{ Name = "wespeaker"; Source = $WeSpeakerSource; Target = Join-Path $ModelRoot "wespeaker" },
    @{ Name = "talknet_asd"; Source = $TalkNetSource; Target = Join-Path $ModelRoot "talknet_asd" },
    @{ Name = "insightface"; Source = $InsightFaceSource; Target = Join-Path $ModelRoot "insightface" },
    @{ Name = "clip_vit_b16"; Source = $ClipSource; Target = Join-Path $ModelRoot "clip_vit_b16" },
    @{ Name = "bge_m3"; Source = $BgeSource; Target = Join-Path $ModelRoot "bge_m3" }
)

Write-Host "[STEP] Preparing layout first..."
powershell -ExecutionPolicy Bypass -File (Join-Path $RepoRoot "prepare_enhanced_model_layout.ps1") -RepoRoot $RepoRoot -ModelRoot $ModelRoot -GalleryRoot $GalleryRoot | Out-Null

foreach ($task in $copyTasks) {
    if (-not $task.Source) {
        continue
    }

    if (-not (Test-Path $task.Source)) {
        throw "Source path not found for $($task.Name): $($task.Source)"
    }

    New-Item -ItemType Directory -Force -Path $task.Target | Out-Null
    Write-Host "[COPY] $($task.Name): $($task.Source) -> $($task.Target)"
    Copy-Item -Path (Join-Path $task.Source "*") -Destination $task.Target -Recurse -Force
}

if ($GallerySource) {
    if (-not (Test-Path $GallerySource)) {
        throw "Gallery source path not found: $GallerySource"
    }
    New-Item -ItemType Directory -Force -Path $GalleryRoot | Out-Null
    Write-Host "[COPY] gallery: $GallerySource -> $GalleryRoot"
    Copy-Item -Path (Join-Path $GallerySource "*") -Destination $GalleryRoot -Recurse -Force
}

Write-Host ""
Write-Host "[OK] Local enhanced assets copied."
Write-Host "Run .\\check_enhanced_runtime.ps1 next."
Write-Host "If you rely on bridge mode for WeSpeaker or TalkNet-ASD, remember to edit bridge.py and set BRIDGE_READY = True."
