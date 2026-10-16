param(
    [string]$Config = 'config/example.yaml', [switch]$ApproveRx,
    [string]$Library = 'tools/hackrf/Library/bin/hackrf-0.dll',
    [string]$DataDir = 'data', [int]$Port = 8765, [switch]$Paused
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $projectRoot
try {
    if (-not (Test-Path '.venv/Scripts/python.exe')) { throw 'Run setup.ps1 first' }
    $runArgs = @('-m', 'radiomind', '--config', $Config, '--data-dir', $DataDir, '--port', "$Port")
    if ($ApproveRx) {
        if (-not (Test-Path -LiteralPath $Library)) { throw 'HackRF library missing; run setup.ps1 -HackRF or pass -Library' }
        $runArgs += @('--approve-rx', '--hackrf-library', $Library)
    }
    if ($Paused) { $runArgs += '--paused' }
    & ./.venv/Scripts/python.exe @runArgs
    if ($LASTEXITCODE -ne 0) { throw 'RadioMind exited with an error' }
} finally { Pop-Location }
