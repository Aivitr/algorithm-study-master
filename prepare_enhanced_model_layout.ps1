param(
    [string]$RepoRoot = (Split-Path -Parent $MyInvocation.MyCommand.Path),
    [string]$ModelRoot = "",
    [string]$GalleryRoot = "",
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

$modelDirs = @(
    "pyannote",
    "wespeaker",
    "talknet_asd",
    "insightface",
    "clip_vit_b16",
    "bge_m3"
)

$templateRoot = Join-Path $RepoRoot "enhanced_bridge_templates"

New-Item -ItemType Directory -Force -Path $ModelRoot | Out-Null
New-Item -ItemType Directory -Force -Path $GalleryRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $GalleryRoot "README_examples") | Out-Null

foreach ($name in $modelDirs) {
    $dir = Join-Path $ModelRoot $name
    New-Item -ItemType Directory -Force -Path $dir | Out-Null

    $placeholder = Join-Path $dir "PLACE_MODEL_FILES_HERE.txt"
    if ($Force -or -not (Test-Path $placeholder)) {
        @"
Model slot: $name

Place the local model files or local repo output for this enhanced runtime slot here.

Expected by runtime:
- pyannote: local diarization model snapshot
- wespeaker: local embedding model files and optional bridge.py
- talknet_asd: local repo/model files and bridge.py
- insightface: local model pack such as buffalo_l
- clip_vit_b16: local CLIP backbone files if you extend runtime further
- bge_m3: local embedding model files if you extend runtime further
"@ | Set-Content -Path $placeholder -Encoding UTF8
    }
}

$bridgeMappings = @(
    @{ Template = "wespeaker_bridge.py"; Target = Join-Path $ModelRoot "wespeaker\bridge.py" },
    @{ Template = "talknet_asd_bridge.py"; Target = Join-Path $ModelRoot "talknet_asd\bridge.py" }
)

foreach ($mapping in $bridgeMappings) {
    $source = Join-Path $templateRoot $mapping.Template
    $target = $mapping.Target
    if ((Test-Path $source) -and ($Force -or -not (Test-Path $target))) {
        Copy-Item -LiteralPath $source -Destination $target -Force
    }
}

$galleryReadme = Join-Path $GalleryRoot "README_examples\HOW_TO_PLACE_GALLERY_FILES.txt"
@"
Optional face gallery layout:

storage/research_gallery/
  2023214001/
    face_01.jpg
    face_02.jpg
  student_zhangsan/
    face_01.jpg

If the folder name matches a student_id or username, InsightFace gallery matching can provide stronger ID correction evidence.
"@ | Set-Content -Path $galleryReadme -Encoding UTF8

Write-Host ""
Write-Host "[OK] Enhanced model layout prepared"
Write-Host "Model root : $ModelRoot"
Write-Host "Gallery root: $GalleryRoot"
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. For automatic enhanced deployment, run .\setup_enhanced_runtime.ps1."
Write-Host "2. For manual/local copy deployment, run .\install_enhanced_models_from_local.ps1."
Write-Host "3. Optionally put per-user face gallery images into storage\research_gallery."
Write-Host "4. Set RESEARCH_DEPLOYMENT_PROFILE=enhanced in .env when you are ready."
