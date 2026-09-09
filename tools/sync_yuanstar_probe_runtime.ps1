[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$RuntimePath
)

$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runtimeRoot = (Resolve-Path -LiteralPath $RuntimePath).Path
$backupTag = Get-Date -Format 'yyyyMMdd-HHmmss'

function Backup-TargetFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Copy-Item -LiteralPath $Path -Destination "$Path.yuanstar-probe-backup-$backupTag" -Force
    }
}

function Copy-ProbeFile {
    param(
        [Parameter(Mandatory = $true)][string]$SourceRelativePath,
        [Parameter(Mandatory = $true)][string]$RuntimeRelativePath
    )
    $source = Join-Path $sourceRoot $SourceRelativePath
    $target = Join-Path $runtimeRoot $RuntimeRelativePath
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "开发文件不存在: $source"
    }
    $targetDirectory = Split-Path -Parent $target
    if (-not (Test-Path -LiteralPath $targetDirectory -PathType Container)) {
        throw "runtime 目录不存在: $targetDirectory"
    }
    Backup-TargetFile -Path $target
    Copy-Item -LiteralPath $source -Destination $target -Force
    Write-Host "已同步: $SourceRelativePath -> $RuntimeRelativePath"
}

# 只同步 B1 probe 与 B2 连续采集所需文件（含单次滑动校准、真实位移 selector、direct normal proposer、行 envelope 语义 overlap 与连续截图编排）；不触碰 config、日志、MaaYuan.exe、MFAAvalonia 或 Python runtime。
Copy-ProbeFile -SourceRelativePath 'agent/custom/action/star_backpack_capture_probe.py' -RuntimeRelativePath 'agent/custom/action/star_backpack_capture_probe.py'
Copy-ProbeFile -SourceRelativePath 'agent/custom/action/__init__.py' -RuntimeRelativePath 'agent/custom/action/__init__.py'
Copy-ProbeFile -SourceRelativePath 'assets/resource/base/pipeline/star_backpack_capture_probe.json' -RuntimeRelativePath 'resource/base/pipeline/star_backpack_capture_probe.json'
Copy-ProbeFile -SourceRelativePath 'assets/resource/base/pipeline/star_backpack_scroll_pair_probe.json' -RuntimeRelativePath 'resource/base/pipeline/star_backpack_scroll_pair_probe.json'
Copy-ProbeFile -SourceRelativePath 'assets/resource/base/pipeline/star_backpack_feedback_probe.json' -RuntimeRelativePath 'resource/base/pipeline/star_backpack_feedback_probe.json'
Copy-ProbeFile -SourceRelativePath 'assets/resource/base/pipeline/star_backpack_continuous_capture.json' -RuntimeRelativePath 'resource/base/pipeline/star_backpack_continuous_capture.json'

$sourceInterfacePath = Join-Path $sourceRoot 'assets/interface.json'
$runtimeInterfacePath = Join-Path $runtimeRoot 'interface.json'
if (-not (Test-Path -LiteralPath $runtimeInterfacePath -PathType Leaf)) {
    throw "runtime interface.json 不存在: $runtimeInterfacePath"
}

$sourceInterface = Get-Content -LiteralPath $sourceInterfacePath -Encoding UTF8 -Raw | ConvertFrom-Json
$runtimeInterface = Get-Content -LiteralPath $runtimeInterfacePath -Encoding UTF8 -Raw | ConvertFrom-Json
if ($null -eq $sourceInterface.task -or $null -eq $runtimeInterface.task) {
    throw 'interface schema 缺少 task，拒绝覆盖 runtime interface.json'
}

$probeNames = @(
    '开发调试｜星石背包截图探针',
    '开发调试｜星石背包单次滑动探针',
    '开发调试｜星石背包反馈滑动探针',
    '开发调试｜星石背包连续采集'
)
$sourceTasksByName = @{}
foreach ($probeName in $probeNames) {
    $sourceTask = @($sourceInterface.task | Where-Object { $_.name -eq $probeName })
    if ($sourceTask.Count -ne 1) {
        throw "开发 interface 中未找到唯一 probe task: $probeName"
    }
    $sourceTasksByName[$probeName] = $sourceTask[0]
}

# 仅增补或替换四个星石背包任务，保留 runtime 的 version、agent、controller、资源和所有其他任务。
$patchedTasks = New-Object System.Collections.Generic.List[object]
$patchedNames = New-Object System.Collections.Generic.HashSet[string]
$probeNames | ForEach-Object {
    $patchedTasks.Add($sourceTasksByName[$_])
    [void]$patchedNames.Add($_)
}
foreach ($task in @($runtimeInterface.task)) {
    if (-not $patchedNames.Contains([string]$task.name)) {
        $patchedTasks.Add($task)
    }
}

Backup-TargetFile -Path $runtimeInterfacePath
$runtimeInterface.task = $patchedTasks.ToArray()
$runtimeInterface | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $runtimeInterfacePath -Encoding UTF8
Write-Host "已安全 patch runtime interface.json（仅四个星石背包任务）"
Write-Host "完成。每个改写目标已有同目录 .yuanstar-probe-backup-$backupTag 备份。"
