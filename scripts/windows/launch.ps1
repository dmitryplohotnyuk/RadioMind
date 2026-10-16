param(
    [string]$Config = '',
    [string]$DataDir = 'data',
    [string]$Library = 'tools/hackrf/Library/bin/hackrf-0.dll',
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [switch]$NoBrowser,
    [switch]$Paused
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$url = "http://127.0.0.1:$Port/"
$mutex = New-Object System.Threading.Mutex($false, "Local\RadioMind-launch-$Port")
$locked = $false

function Get-RadioMindStatus {
    try {
        $status = Invoke-RestMethod "${url}api/status" -TimeoutSec 2
        if ($status.source -notin @('hackrf', 'mock') -or $status.running -isnot [bool]) { return $null }
        $page = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2
        if ($page.Content -notmatch '<title(?:\s[^>]*)?>RadioMind(?:\s|<)') { return $null }
        return $status
    } catch { return $null }
}

function Open-RadioMind {
    Write-Host "RadioMind: $url"
    if (-not $NoBrowser) { Start-Process $url }
}

Push-Location $projectRoot
try {
    try { $locked = $mutex.WaitOne(60000) }
    catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { throw 'Another RadioMind launch is still in progress. Try again shortly.' }
    if ($null -ne (Get-RadioMindStatus)) {
        Write-Host 'RadioMind is already running. Opening the existing instance.'
        Open-RadioMind
        exit 0
    }
    # A different or unresponsive listener must not trigger a second RX owner.
    $probe = New-Object System.Net.Sockets.TcpClient
    try {
        $connection = $probe.ConnectAsync('127.0.0.1', $Port)
        try { $null = $connection.Wait(1000) } catch { }
        if ($probe.Connected) { throw "Port $Port is occupied but RadioMind is not ready. No second instance was started." }
    } finally { $probe.Dispose() }

    $python = Join-Path $projectRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Python environment missing. Run scripts/windows/setup.ps1 first.' }
    if (-not $Config) {
        foreach ($candidate in @('config/local.yaml', 'config/hackrf-recorder.yaml')) {
            if (Test-Path -LiteralPath $candidate) { $Config = $candidate; break }
        }
        if (-not $Config) { throw 'RX profile missing. Create config/local.yaml as described in docs/en/guide.md.' }
    }
    $configPath = (Resolve-Path -LiteralPath $Config).Path
    $source = & $python -c 'import sys; from pathlib import Path; from radiomind.config import load_settings; print(load_settings(Path(sys.argv[1])).source)' $configPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not validate the receiver profile. See the error above.' }
    $arguments = @('-m', 'radiomind', '--config', $configPath, '--data-dir', $DataDir, '--port', "$Port")
    if ($source -eq 'hackrf') {
        $libraryPath = (Resolve-Path -LiteralPath $Library).Path
        $arguments += @('--approve-rx', '--hackrf-library', $libraryPath)
    }
    if ($Paused) { $arguments += '--paused' }
    # Start-Process joins ArgumentList: quote paths explicitly (including spaces).
    # File paths cannot contain a quote. Double directory-ending backslashes
    # so they do not escape the closing quote in Windows command-line parsing.
    $quoted = foreach ($argument in $arguments) {
        if ($argument.Contains('"')) { throw 'A launch argument contains an unsupported quote.' }
        '"' + ($argument -replace '(\\+)$', '$1$1') + '"'
    }
    $null = New-Item -ItemType Directory -Force -Path 'runtime'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $stdout = Join-Path $projectRoot "runtime/windows-launch-$stamp.stdout.log"
    $stderr = Join-Path $projectRoot "runtime/windows-launch-$stamp.stderr.log"
    Write-Host 'Starting RadioMind...'
    $process = Start-Process -FilePath $python -ArgumentList $quoted -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $deadline = (Get-Date).AddSeconds(45)
    do {
        Start-Sleep -Milliseconds 500
        $status = Get-RadioMindStatus
        if ($null -ne $status) {
            if ($status.error) { Write-Warning "Receiver: $($status.error). Open the interface to check the device." }
            Open-RadioMind
            exit 0
        }
        $process.Refresh()
        if ($process.HasExited) { throw "RadioMind exited during startup. Log: $stderr" }
    } while ((Get-Date) -lt $deadline)
    throw "Startup is taking too long. The process may still be starting; do not run another copy. Log: $stderr"
} catch {
    Write-Host "RadioMind: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
