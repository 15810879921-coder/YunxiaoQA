[CmdletBinding()]
param(
    [string]$OutputRoot
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = [System.IO.Path]::GetFullPath((Join-Path $scriptRoot '..'))
$skillName = 'YunxiaoQA'
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $repoRoot 'packages'
}
$resolvedOutput = [System.IO.Path]::GetFullPath($OutputRoot)
$tempBase = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$tempRoot = Join-Path $tempBase ('oneos-qa-skill-' + [guid]::NewGuid().ToString('N'))

if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'SKILL.md'))) {
    throw "缺少 Skill：$repoRoot"
}
if (-not ([System.IO.Path]::GetFullPath($tempRoot)).StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "临时目录不在系统临时根目录内：$tempRoot"
}

New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    foreach ($client in @('codex', 'cursor')) {
        $clientOutput = Join-Path $resolvedOutput $client
        $stageRoot = Join-Path $tempRoot $client
        $stageSkill = Join-Path $stageRoot $skillName
        New-Item -ItemType Directory -Path $clientOutput -Force | Out-Null
        New-Item -ItemType Directory -Path $stageSkill -Force | Out-Null

        foreach ($fileName in @('SKILL.md', 'requirements.txt')) {
            $sourceFile = Join-Path $repoRoot $fileName
            if (Test-Path -LiteralPath $sourceFile) {
                Copy-Item -LiteralPath $sourceFile -Destination $stageSkill -Force
            }
        }
        foreach ($folderName in @('assets', 'references', 'scripts')) {
            $sourceFolder = Join-Path $repoRoot $folderName
            if (Test-Path -LiteralPath $sourceFolder) {
                Copy-Item -LiteralPath $sourceFolder -Destination $stageSkill -Recurse -Force
            }
        }
        Get-ChildItem -LiteralPath $stageSkill -Directory -Recurse -Force |
            Where-Object { $_.Name -eq '__pycache__' } |
            Sort-Object FullName -Descending |
            Remove-Item -Recurse -Force
        Get-ChildItem -LiteralPath $stageSkill -File -Recurse -Force |
            Where-Object { $_.Extension -in @('.pyc', '.pyo') } |
            Remove-Item -Force
        if ($client -eq 'codex' -and (Test-Path -LiteralPath (Join-Path $repoRoot 'agents'))) {
            Copy-Item -LiteralPath (Join-Path $repoRoot 'agents') -Destination $stageSkill -Recurse -Force
        }

        $archive = Join-Path $clientOutput ($skillName + '.zip')
        if (Test-Path -LiteralPath $archive) {
            Remove-Item -LiteralPath $archive -Force
        }
        Compress-Archive -LiteralPath $stageSkill -DestinationPath $archive -CompressionLevel Optimal
        $entry = [ordered]@{
            client = $client
            skill = $skillName
            archive = [System.IO.Path]::GetFileName($archive)
            sha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        @($entry) | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $clientOutput 'manifest.json') -Encoding utf8
    }
}
finally {
    $resolvedTemp = [System.IO.Path]::GetFullPath($tempRoot)
    if ($resolvedTemp.StartsWith($tempBase, [System.StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $resolvedTemp).StartsWith('oneos-qa-skill-', [System.StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $resolvedTemp)) {
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
    }
}

Write-Output "已生成 Codex/Cursor 双版本包：$resolvedOutput"
