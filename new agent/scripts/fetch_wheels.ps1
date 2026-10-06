# 下载课堂小组分析 Agent 的离线依赖（wheel），供无网 / 弱网环境安装。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\fetch_wheels.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\fetch_wheels.ps1 -OutDir D:\wheels -Python "C:\Python312\python.exe"
#
# 说明：
#   * 默认下载的是**当前平台 + 当前 Python 版本**的 wheel。
#     Windows 上得到 cp312-win_amd64，Linux/WSL 上得到 manylinux，两者不能混用。
#   * 想为指定 Python 版本下载，加 -TargetPython 3.12，
#     脚本会附带 --only-binary=:all: --python-version 3.12。
#   * webrtcvad 在 3.12+ 的 Windows 上没有 wheel，会以源码包形式出现并编译失败；
#     这不是错误，改用本目录 compat/webrtcvad.py 即可。

param(
    [string]$OutDir = (Join-Path $PSScriptRoot "..\wheels"),
    [string]$RequirementFile = (Join-Path $PSScriptRoot "requirements-agent-pinned.txt"),
    [string]$Python = "python",
    [string]$TargetPython = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $RequirementFile)) {
    throw "找不到依赖清单：$RequirementFile"
}

New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$pipArgs = @("-m", "pip", "download", "--no-cache-dir", "-d", $OutDir, "-r", $RequirementFile)
if ($TargetPython) {
    $pipArgs += @("--only-binary=:all:", "--python-version", $TargetPython)
}

Write-Host "正在下载依赖到 $OutDir ..."
& $Python @pipArgs
if ($LASTEXITCODE -ne 0) {
    throw "pip download 失败，退出码 $LASTEXITCODE"
}

$files = Get-ChildItem $OutDir -File
$totalMb = [math]::Round((($files | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host ("完成：{0} 个文件，共 {1} MB" -f $files.Count, $totalMb)
Write-Host "离线安装命令："
Write-Host ("  {0} -m pip install --no-index --find-links `"{1}`" -r `"{2}`"" -f $Python, $OutDir, $RequirementFile)
