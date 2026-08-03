$ErrorActionPreference = 'Stop'

if ($args.Count -lt 1) {
    [Console]::Error.WriteLine('Usage: run-skill-script.ps1 <script.py> [arguments...]')
    exit 64
}

$scriptName = [string]$args[0]
[string[]]$scriptArgs = @()
if ($args.Count -gt 1) {
    $scriptArgs = @($args[1..($args.Count - 1)])
}

if ($scriptName -notmatch '^[A-Za-z0-9_.-]+\.py$' -or $scriptName.Contains('..')) {
    [Console]::Error.WriteLine("Only a Python script in this Skill's scripts directory is allowed: $scriptName")
    exit 64
}

$targetScript = Join-Path -Path $PSScriptRoot -ChildPath $scriptName
if (-not (Test-Path -LiteralPath $targetScript -PathType Leaf)) {
    [Console]::Error.WriteLine("Script not found: $scriptName")
    exit 66
}

$pythonCandidates = @(
    @{ Name = 'py'; Arguments = @('-3') },
    @{ Name = 'python'; Arguments = @() },
    @{ Name = 'python3'; Arguments = @() }
)

$pythonCommand = $null
[string[]]$pythonPrefix = @()
foreach ($candidate in $pythonCandidates) {
    $command = Get-Command -Name $candidate.Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $command) { continue }
    & $command.Source @($candidate.Arguments) -c 'import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)' *> $null
    if ($LASTEXITCODE -eq 0) {
        $pythonCommand = $command.Source
        $pythonPrefix = @($candidate.Arguments)
        break
    }
}

if ($null -eq $pythonCommand) {
    [Console]::Error.WriteLine('Python 3 was not found. Install Python 3 and make it available to the local command line.')
    exit 69
}

$env:PYTHONDONTWRITEBYTECODE = '1'
$env:ONEOS_YUNXIAO_TEMP_DIR = Join-Path -Path ([IO.Path]::GetTempPath()) -ChildPath 'oneos-yunxiao'
New-Item -ItemType Directory -Path $env:ONEOS_YUNXIAO_TEMP_DIR -Force | Out-Null

[string[]]$invocationArgs = @($pythonPrefix) + @($targetScript) + @($scriptArgs)
& $pythonCommand @invocationArgs
exit $LASTEXITCODE
