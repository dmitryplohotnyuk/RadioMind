$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $projectRoot
try {
    & ./.venv/Scripts/python.exe scripts/check.py
    if ($LASTEXITCODE -ne 0) { throw 'Checks failed' }
} finally { Pop-Location }
