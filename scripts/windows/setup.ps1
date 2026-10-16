param([switch]$Models, [switch]$Cleanup, [switch]$Digital, [switch]$HackRF)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Push-Location $projectRoot
try {
    python scripts/bootstrap.py
    if ($LASTEXITCODE -ne 0) { throw 'Python setup failed' }
    $installers = @()
    if ($Models) { $installers += 'scripts/install_silero.py' }
    if ($Cleanup) { $installers += 'scripts/install_rnnoise.py' }
    if ($Digital) { $installers += 'scripts/install_digital.py' }
    if ($HackRF) { $installers += 'scripts/windows/portable_hackrf.py' }
    foreach ($installer in $installers) {
        & ./.venv/Scripts/python.exe $installer
        if ($LASTEXITCODE -ne 0) { throw "Installer failed: $installer" }
    }
} finally { Pop-Location }
